#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
"""
Pre-prompt context injection hook for Claude Code.
Registered as: UserPromptSubmit hook in .claude/settings.json

When the user types a prompt, this hook:
1. Reads the prompt from stdin (JSON)
2. Extracts keywords from the prompt
3. Searches Nora's local SQLite DB for relevant patterns, decisions, bugs
4. Prints matching context to stdout → Claude sees it before responding

SECURITY: stdlib only. No network calls. Reads local DB only.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"

# Stop words to ignore during keyword extraction
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "don", "now", "and", "but", "or", "if", "this", "that", "these",
    "those", "what", "which", "who", "whom", "it", "its", "my", "me",
    "we", "us", "you", "your", "he", "she", "they", "them", "i",
}


def extract_keywords(prompt: str) -> list[str]:
    """Extract meaningful keywords from the user's prompt."""
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_.-]{2,}\b', prompt.lower())
    keywords = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique[:10]  # Cap at 10 keywords


def search_patterns(conn: sqlite3.Connection, keywords: list[str]) -> list[dict]:
    """Search patterns table for matching entries."""
    if not keywords:
        return []
    conditions = " OR ".join(
        ["pattern LIKE ? OR code_example LIKE ? OR domains LIKE ? OR context LIKE ?"]
        * len(keywords)
    )
    params = []
    for kw in keywords:
        like = f"%{kw}%"
        params.extend([like, like, like, like])

    try:
        rows = conn.execute(f"""
            SELECT pattern, code_example, effectiveness, domains
            FROM patterns
            WHERE {conditions}
            ORDER BY effectiveness DESC
            LIMIT 3
        """, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def search_decisions(conn: sqlite3.Connection, keywords: list[str]) -> list[dict]:
    """Search decisions table for matching entries."""
    if not keywords:
        return []
    conditions = " OR ".join(
        ["decision LIKE ? OR context LIKE ? OR rationale LIKE ?"]
        * len(keywords)
    )
    params = []
    for kw in keywords:
        like = f"%{kw}%"
        params.extend([like, like, like])

    try:
        rows = conn.execute(f"""
            SELECT decision, rationale, context
            FROM decisions
            WHERE {conditions}
            LIMIT 3
        """, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def search_bugs(conn: sqlite3.Connection, keywords: list[str]) -> list[dict]:
    """Search reported bugs for matching entries."""
    if not keywords:
        return []
    conditions = " OR ".join(
        ["title LIKE ? OR file_path LIKE ? OR error_signature LIKE ?"]
        * len(keywords)
    )
    params = []
    for kw in keywords:
        like = f"%{kw}%"
        params.extend([like, like, like])

    try:
        rows = conn.execute(f"""
            SELECT title, file_path, severity, fix_code, status
            FROM reported_bugs
            WHERE {conditions}
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END
            LIMIT 3
        """, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def search_insights(conn: sqlite3.Connection, keywords: list[str]) -> list[dict]:
    """Search session insights/summaries for matching entries."""
    if not keywords:
        return []
    conditions = " OR ".join(
        ["summary LIKE ? OR themes LIKE ? OR playbook LIKE ? OR anti_patterns LIKE ?"]
        * len(keywords)
    )
    params = []
    for kw in keywords:
        like = f"%{kw}%"
        params.extend([like, like, like, like])

    try:
        rows = conn.execute(f"""
            SELECT summary, playbook, anti_patterns, claude_md_rules
            FROM insights
            WHERE {conditions}
            LIMIT 2
        """, params).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def format_context(patterns, decisions, bugs, insights) -> str:
    """Format search results into context string for Claude."""
    sections = []

    if patterns:
        lines = ["[Nora Memory — Relevant Patterns]"]
        for p in patterns:
            lines.append(f"  • {p['pattern']} (effectiveness: {p.get('effectiveness', '?')})")
            if p.get('code_example'):
                # Truncate long code examples
                code = p['code_example'][:200]
                lines.append(f"    Example: {code}")
        sections.append("\n".join(lines))

    if decisions:
        lines = ["[Nora Memory — Past Decisions]"]
        for d in decisions:
            lines.append(f"  • {d['decision']}")
            if d.get('rationale'):
                lines.append(f"    Why: {d['rationale'][:150]}")
        sections.append("\n".join(lines))

    if bugs:
        active_bugs = [b for b in bugs if b.get('status') != 'resolved']
        if active_bugs:
            lines = ["[Nora Memory — Known Bugs (unresolved)]"]
            for b in active_bugs:
                lines.append(f"  • [{b.get('severity', '?')}] {b['title']}")
                if b.get('file_path'):
                    lines.append(f"    File: {b['file_path']}")
            sections.append("\n".join(lines))

    if insights:
        lines = ["[Nora Memory — Session Insights]"]
        for i in insights:
            if i.get('playbook'):
                lines.append(f"  • Playbook: {i['playbook'][:200]}")
            if i.get('anti_patterns'):
                lines.append(f"  • Anti-patterns: {i['anti_patterns'][:200]}")
            if i.get('claude_md_rules'):
                lines.append(f"  • Rules: {i['claude_md_rules'][:200]}")
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = "─── Nora Context (from past sessions) ───"
    footer = "─── End Nora Context ───"
    return f"\n{header}\n" + "\n\n".join(sections) + f"\n{footer}\n"


def main():
    # Read hook input from stdin
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

    # Check if DB exists
    if not DB_PATH.exists():
        sys.exit(0)

    # Extract keywords from the prompt
    keywords = extract_keywords(prompt)
    if not keywords:
        sys.exit(0)

    # Search the Nora database
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3)
        conn.row_factory = sqlite3.Row

        patterns = search_patterns(conn, keywords)
        decisions = search_decisions(conn, keywords)
        bugs = search_bugs(conn, keywords)
        insights = search_insights(conn, keywords)

        conn.close()
    except Exception:
        sys.exit(0)

    # Format and output context
    context = format_context(patterns, decisions, bugs, insights)
    if context:
        # Print to stdout — Claude Code injects this as context
        print(context)

    sys.exit(0)


if __name__ == "__main__":
    main()
