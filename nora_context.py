#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
"""
Nora Context Injection Pre-Hook v2
Registered as: UserPromptSubmit hook in .claude/settings.json

Architecture:
  1. User types prompt → hook receives JSON on stdin
  2. Extract keywords → search FTS5 index (O(1) lookup)
  3. Rank results: relevance × recency × effectiveness
  4. Format as branded "Nora suggests" numbered options
  5. Print to stdout → Claude presents options to user
  6. Log impression metrics to nora_metrics table

SECURITY: stdlib only. No network calls. Local SQLite only.
PERFORMANCE: Target <50ms total. FTS5 index, no LIKE scans.
"""
import json
import math
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"

# ─── Stop words ──────────────────────────────────────────────────────────────
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "before", "after", "between", "out", "off", "over", "under", "then",
    "here", "there", "when", "where", "why", "how", "all", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "not", "only",
    "own", "same", "so", "than", "too", "very", "just", "now", "and",
    "but", "or", "if", "this", "that", "these", "those", "what", "which",
    "who", "it", "its", "my", "me", "we", "us", "you", "your", "he",
    "she", "they", "them", "i", "about", "like", "make", "get", "use",
}


# ─── FTS5 Setup ──────────────────────────────────────────────────────────────

def ensure_fts_index(conn: sqlite3.Connection):
    """Create FTS5 virtual tables if they don't exist. Idempotent."""
    conn.executescript("""
        -- FTS index over patterns
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_patterns USING fts5(
            pattern, code_example, domains, context,
            content='patterns', content_rowid='id'
        );

        -- FTS index over decisions
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_decisions USING fts5(
            decision, context, rationale, alternatives,
            content='decisions', content_rowid='id'
        );

        -- FTS index over bugs
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_bugs USING fts5(
            title, file_path, error_signature, fix_code,
            content='reported_bugs', content_rowid='id'
        );

        -- FTS index over insights
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_insights USING fts5(
            summary, themes, playbook, anti_patterns, claude_md_rules,
            knowledge_domains, reusable_patterns,
            content='insights', content_rowid='id'
        );

        -- Metrics table for tracking suggestion impressions/selections
        CREATE TABLE IF NOT EXISTS nora_metrics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,  -- 'impression', 'selection', 'dismissal'
            prompt_hash TEXT,           -- hash of the triggering prompt
            result_type TEXT,           -- 'pattern', 'decision', 'bug', 'insight'
            result_id   INTEGER,        -- ID of the matched item
            rank        INTEGER,        -- position in suggestions (1-based)
            keywords    TEXT,           -- JSON array of extracted keywords
            latency_ms  REAL,           -- total hook execution time
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_nora_metrics_type
            ON nora_metrics(event_type, created_at);
    """)
    conn.commit()


def rebuild_fts_index(conn: sqlite3.Connection):
    """Rebuild FTS indexes from source tables. Called on first run or after bulk insert."""
    for table in ['fts_patterns', 'fts_decisions', 'fts_bugs', 'fts_insights']:
        try:
            conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass  # Table might already be up to date
    conn.commit()


# ─── Keyword Extraction ──────────────────────────────────────────────────────

def extract_keywords(prompt: str) -> list[str]:
    """Extract meaningful keywords from the user's prompt."""
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_.-]{2,}\b', prompt.lower())
    keywords = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    seen = set()
    unique = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique[:8]


def prompt_hash(prompt: str) -> str:
    """Simple hash of prompt for metrics deduplication."""
    import hashlib
    return hashlib.md5(prompt.strip().lower().encode()).hexdigest()[:12]


# ─── FTS Search ──────────────────────────────────────────────────────────────

def fts_search(conn: sqlite3.Connection, table: str, source_table: str,
               keywords: list[str], limit: int = 5) -> list[dict]:
    """Search FTS5 index with OR query. Returns ranked results with BM25 score."""
    if not keywords:
        return []

    # Build FTS5 query: keyword1 OR keyword2 OR keyword3
    fts_query = " OR ".join(keywords)

    try:
        # bm25() returns negative values (more negative = more relevant)
        rows = conn.execute(f"""
            SELECT s.*, bm25({table}) as relevance_score
            FROM {table} ft
            JOIN {source_table} s ON s.id = ft.rowid
            WHERE {table} MATCH ?
            ORDER BY bm25({table})
            LIMIT ?
        """, (fts_query, limit)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # FTS index might be empty or corrupted — fall back to LIKE
        return _fallback_like_search(conn, source_table, keywords, limit)


def _fallback_like_search(conn: sqlite3.Connection, table: str,
                          keywords: list[str], limit: int) -> list[dict]:
    """Fallback LIKE search when FTS is unavailable."""
    if table == 'patterns':
        cols = ['pattern', 'code_example', 'domains', 'context']
    elif table == 'decisions':
        cols = ['decision', 'context', 'rationale', 'alternatives']
    elif table == 'reported_bugs':
        cols = ['title', 'file_path', 'error_signature', 'fix_code']
    elif table == 'insights':
        cols = ['summary', 'themes', 'playbook', 'anti_patterns']
    else:
        return []

    conditions = []
    params = []
    for kw in keywords:
        like = f"%{kw}%"
        for col in cols:
            conditions.append(f"{col} LIKE ?")
            params.append(like)

    where = " OR ".join(conditions)
    try:
        rows = conn.execute(
            f"SELECT *, 0.0 as relevance_score FROM {table} WHERE {where} LIMIT ?",
            params + [limit]
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ─── Ranking ─────────────────────────────────────────────────────────────────

def compute_rank(item: dict, item_type: str) -> float:
    """
    Composite ranking: relevance × recency × effectiveness
    Higher = better match.
    """
    # BM25 relevance (already negative, more negative = better)
    relevance = abs(item.get('relevance_score', 0))

    # Recency: exponential decay, half-life of 7 days
    created = item.get('created_at', '')
    if created:
        try:
            created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            age_days = (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400
            recency = math.exp(-0.693 * age_days / 7)  # half-life = 7 days
        except (ValueError, TypeError):
            recency = 0.5
    else:
        recency = 0.5

    # Effectiveness (patterns only)
    effectiveness = item.get('effectiveness', 0.7)

    # Severity boost for bugs
    severity_boost = 1.0
    if item_type == 'bug':
        severity_map = {'critical': 2.0, 'high': 1.5, 'medium': 1.0, 'low': 0.5}
        severity_boost = severity_map.get(item.get('severity', ''), 1.0)

    # Status penalty for resolved bugs (still useful but lower priority)
    status_penalty = 1.0
    if item.get('status') == 'resolved' or item.get('status') == 'fixed':
        status_penalty = 0.3

    return (relevance * 0.4 + recency * 0.3 + effectiveness * 0.3) * severity_boost * status_penalty


# ─── Suggestion Formatting ───────────────────────────────────────────────────

def format_suggestions(ranked_items: list[tuple]) -> str:
    """
    Format ranked results as branded Nora suggestions with numbered options.

    Output format that Claude will present to the user:
    ┌─ Nora found relevant context from your past sessions ─┐
    │                                                        │
    │  1. [Pattern] Use WAL mode for SQLite...              │
    │  2. [Decision] Use SQLite over Firestore...           │
    │  3. [Bug] SQLite locked on concurrent writes          │
    │                                                        │
    │  Reply 1, 2, 3 to use, or continue without.          │
    └────────────────────────────────────────────────────────┘
    """
    if not ranked_items:
        return ""

    lines = []
    lines.append("")
    lines.append("◎ Nora found relevant context from your past sessions:")
    lines.append("")

    for i, (item, item_type, score) in enumerate(ranked_items[:5], 1):
        label = _type_label(item_type)
        summary = _item_summary(item, item_type)
        detail = _item_detail(item, item_type)

        lines.append(f"  {i}. [{label}] {summary}")
        if detail:
            lines.append(f"     {detail}")
        lines.append("")

    lines.append("  Reply with a number to apply, or continue without Nora context.")
    lines.append("")

    return "\n".join(lines)


def _type_label(item_type: str) -> str:
    labels = {
        'pattern': 'Pattern',
        'decision': 'Decision',
        'bug': 'Bug',
        'insight': 'Playbook',
    }
    return labels.get(item_type, 'Context')


def _item_summary(item: dict, item_type: str) -> str:
    if item_type == 'pattern':
        eff = item.get('effectiveness', 0)
        return f"{item.get('pattern', '?')} (eff: {eff:.0%})"
    elif item_type == 'decision':
        return item.get('decision', '?')
    elif item_type == 'bug':
        sev = item.get('severity', '?')
        status = item.get('status', 'open')
        return f"[{sev}] {item.get('title', '?')} ({status})"
    elif item_type == 'insight':
        return item.get('summary', '?')[:120]
    return '?'


def _item_detail(item: dict, item_type: str) -> str:
    if item_type == 'pattern' and item.get('code_example'):
        return f"Example: {item['code_example'][:100]}"
    elif item_type == 'decision' and item.get('rationale'):
        return f"Why: {item['rationale'][:100]}"
    elif item_type == 'bug' and item.get('file_path'):
        return f"File: {item['file_path']}"
    elif item_type == 'insight' and item.get('playbook'):
        return f"Playbook: {item['playbook'][:100]}"
    return ""


# ─── Full Context for Selected Item ─────────────────────────────────────────

def format_selected_context(item: dict, item_type: str) -> str:
    """When user selects an option, return the full context for injection."""
    lines = []
    lines.append(f"─── Nora Context ({_type_label(item_type)}) ───")

    if item_type == 'pattern':
        lines.append(f"Pattern: {item.get('pattern', '')}")
        if item.get('code_example'):
            lines.append(f"Example:\n{item['code_example']}")
        if item.get('context'):
            lines.append(f"Context: {item['context']}")
        if item.get('domains'):
            lines.append(f"Domains: {item['domains']}")

    elif item_type == 'decision':
        lines.append(f"Decision: {item.get('decision', '')}")
        if item.get('rationale'):
            lines.append(f"Rationale: {item['rationale']}")
        if item.get('alternatives'):
            lines.append(f"Alternatives considered: {item['alternatives']}")
        if item.get('linked_files'):
            lines.append(f"Files: {item['linked_files']}")

    elif item_type == 'bug':
        lines.append(f"Bug: {item.get('title', '')}")
        lines.append(f"Severity: {item.get('severity', '?')} | Status: {item.get('status', '?')}")
        if item.get('file_path'):
            lines.append(f"File: {item['file_path']}")
        if item.get('fix_code'):
            lines.append(f"Fix:\n{item['fix_code']}")
        if item.get('error_signature'):
            lines.append(f"Error signature: {item['error_signature']}")

    elif item_type == 'insight':
        if item.get('summary'):
            lines.append(f"Summary: {item['summary']}")
        if item.get('playbook'):
            lines.append(f"Playbook: {item['playbook']}")
        if item.get('claude_md_rules'):
            lines.append(f"Rules: {item['claude_md_rules']}")
        if item.get('anti_patterns'):
            lines.append(f"Anti-patterns: {item['anti_patterns']}")

    lines.append("─── End Nora Context ───")
    return "\n".join(lines)


# ─── Metrics ─────────────────────────────────────────────────────────────────

def log_metric(conn: sqlite3.Connection, event_type: str, p_hash: str,
               results: list[tuple], keywords: list[str], latency_ms: float):
    """Log an impression metric for all suggested items."""
    try:
        for rank, (item, item_type, score) in enumerate(results, 1):
            conn.execute("""
                INSERT INTO nora_metrics (event_type, prompt_hash, result_type,
                    result_id, rank, keywords, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                event_type,
                p_hash,
                item_type,
                item.get('id', 0),
                rank,
                json.dumps(keywords),
                latency_ms,
            ))
        conn.commit()
    except Exception:
        pass  # Metrics should never break the hook


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    start_time = time.time()

    # Read hook input
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    prompt = data.get("prompt", "")
    if not prompt or len(prompt) < 5:
        sys.exit(0)

    if not DB_PATH.exists():
        sys.exit(0)

    # Extract keywords
    keywords = extract_keywords(prompt)
    if not keywords:
        sys.exit(0)

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        # Ensure FTS indexes exist (idempotent, fast if already exists)
        ensure_fts_index(conn)

        # Rebuild FTS on first run (checks if content is synced)
        # This is cheap for small tables and only needed once
        try:
            count = conn.execute("SELECT count(*) FROM fts_patterns").fetchone()[0]
            if count == 0:
                rebuild_fts_index(conn)
        except sqlite3.OperationalError:
            rebuild_fts_index(conn)

        # Search all tables via FTS5
        patterns = fts_search(conn, 'fts_patterns', 'patterns', keywords, 3)
        decisions = fts_search(conn, 'fts_decisions', 'decisions', keywords, 3)
        bugs = fts_search(conn, 'fts_bugs', 'reported_bugs', keywords, 3)
        insights = fts_search(conn, 'fts_insights', 'insights', keywords, 2)

        # Tag results with type and compute composite rank
        all_results = []
        for p in patterns:
            all_results.append((p, 'pattern', compute_rank(p, 'pattern')))
        for d in decisions:
            all_results.append((d, 'decision', compute_rank(d, 'decision')))
        for b in bugs:
            all_results.append((b, 'bug', compute_rank(b, 'bug')))
        for i in insights:
            all_results.append((i, 'insight', compute_rank(i, 'insight')))

        # Sort by composite rank (highest first)
        all_results.sort(key=lambda x: x[2], reverse=True)

        # Deduplicate by content similarity (same pattern text = skip)
        seen_text = set()
        deduped = []
        for item, itype, score in all_results:
            key_text = _item_summary(item, itype)[:60]
            if key_text not in seen_text:
                seen_text.add(key_text)
                deduped.append((item, itype, score))

        # Take top 5
        top_results = deduped[:5]

        latency_ms = (time.time() - start_time) * 1000

        if top_results:
            # Log impression metrics
            p_hash_val = prompt_hash(prompt)
            log_metric(conn, 'impression', p_hash_val, top_results, keywords, latency_ms)

            # Format and output suggestions
            output = format_suggestions(top_results)
            print(output)

        conn.close()

    except Exception:
        pass  # Hook must never crash or block

    sys.exit(0)


if __name__ == "__main__":
    main()
