# Nora R1 — Complete Batch Specs for Sonnet Implementation

**Date:** April 1, 2026
**Model:** Sonnet 4.6 for all batches
**Target:** Ship 18 MCP tools + polished dashboard + AI Coach as VSCode/Kiro extension
**Codebase:** `kiro-extension/bundled/` — all Python, Flask+HTMX, SQLite

---

## R1 Scope Summary

### IN (R1)
- 16 existing MCP tools (already built in nora_mcp.py)
- 2 new MCP tools: `nora_coach` + `nora_onboard`
- Dashboard redesign: 7 original batches + 1 new Coach tab
- AI Education: analyzer prompt expansion, nora_coach tool, /coach dashboard route
- PE fixes: connection leaks, set serialization, body size limit, file permissions
- Settings cleanup: remove plaintext AWS creds, add chmod 600

### OUT (R2)
- Storage/BYOS/Litestream → R2
- Payments/Stripe/tier gating → R2
- Team features (shared patterns, team digest) → R2
- Non-engineering personas (PM, Sales, Legal, Finance, Exec) → R2 (infra in R1, content in R2)
- `nora_dependency_audit`, `nora_test_coverage`, `nora_incident` → R2
- Charts/D3/WebSocket → R2 or never

---

## Batch Execution Order

```
Phase 1 — Foundation (no dependencies)
  Batch 1: DB schema + analyzer prompt expansion
  Batch 2: PE fixes (connection leaks, set serialization, body size)

Phase 2 — New tools (depends on Batch 1)
  Batch 3: nora_coach MCP tool
  Batch 4: nora_onboard MCP tool + nora_help update

Phase 3 — Dashboard (depends on Batch 1-2)
  Batch 5: Dashboard foundation — persona config, nav rename, CSS upgrade
  Batch 6: Home page redesign — value-first KPIs, compounding viz
  Batch 7: Knowledge + Memory + Decisions pages
  Batch 8: Coach tab + Activity polish + Settings cleanup

Phase 4 — Verification
  Batch 9: Integration test + help text update + final polish
```

Batches within each phase can run in parallel. Phases are sequential.

---

## BATCH 1: DB Schema + Analyzer Prompt Expansion

**Files:** `db.py`, `analyzer.py`
**Est:** ~10 min
**Why first:** Every downstream batch depends on the new DB columns and analyzer output.

### Task 1.1 — Add `prompt_coaching` and `prompt_antipatterns` columns to insights table

**File:** `db.py` — `init_db()` function, lines 36-49

Add two new columns to the `insights` CREATE TABLE:

```sql
prompt_coaching   TEXT,  -- JSON: {"weak_prompt": "...", "strong_version": "...", "why": "..."}
prompt_antipatterns TEXT  -- JSON: [{"pattern": "vague_request", "count": N, "example": "..."}]
```

Also add a new table for cross-session coaching aggregates:

```sql
CREATE TABLE IF NOT EXISTS coaching_trends (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start      TEXT NOT NULL,
    avg_quality     REAL DEFAULT 0,
    avg_words       INTEGER DEFAULT 0,
    total_sessions  INTEGER DEFAULT 0,
    top_antipattern TEXT,
    improvement_tip TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_coaching_week ON coaching_trends(week_start);
```

**Task 1.2 — Update `mark_analyzed()` to store new fields**

**File:** `db.py` — `mark_analyzed()` function, lines 129-153

Add `prompt_coaching` and `prompt_antipatterns` to the INSERT INTO insights statement. Map from `insight.get("prompt_coaching", "")` and `json.dumps(insight.get("prompt_antipatterns", []))`.

**Task 1.3 — Expand analyzer prompt to generate coaching output**

**File:** `analyzer.py` — `PROMPT` string, lines 32-56

Add these fields to the required JSON format:

```json
"prompt_coaching": {
    "weakest_prompt": "the user's least effective prompt from this session (verbatim, max 100 chars)",
    "stronger_version": "a rewritten version that would score higher (max 200 chars)",
    "why_better": "one sentence explaining what makes the rewrite better",
    "score_delta": "estimated score improvement e.g. '+0.3'"
},
"prompt_antipatterns": [
    {"pattern": "vague_request|missing_context|no_file_reference|repeated_instruction|no_error_message|too_broad", "count": 1, "example": "shortest example from session"}
]
```

Add these rules to the Rules section:
```
- prompt_coaching: find the WORST user prompt in the session and show how to improve it. If session is too short, return empty object.
- prompt_antipatterns: categorize the user's prompting weaknesses. Categories: vague_request (no specifics), missing_context (no file/line), no_file_reference (talks about code without paths), repeated_instruction (says the same thing twice), no_error_message (describes error without pasting it), too_broad (asks for everything at once). Return empty array if session is excellent.
```

**Done when:** `python db.py` creates the new table and columns without error. Analyzer prompt includes coaching fields. `mark_analyzed()` stores them.

---

## BATCH 2: PE Fixes — Connection Leaks, Set Serialization, Body Size

**Files:** `db.py`, `daemon.py`, `nora_mcp.py`
**Est:** ~10 min
**Why:** Correctness fixes that prevent data loss and crashes.

### Task 2.1 — Fix connection leaks in db.py (PE #2)

**File:** `db.py` — ALL functions that call `get_conn()`

Wrap every function body in `try/finally` with `conn.close()` in the finally block. Affected: `store_session()`, `get_unanalyzed()`, `mark_analyzed()`, `get_session()`. Pattern:

```python
def store_session(payload: dict):
    conn = get_conn()
    try:
        conn.execute(...)
        conn.commit()
    finally:
        conn.close()
```

### Task 2.2 — Fix set serialization in daemon.py (PE #6)

**File:** `daemon.py`

Find all `"files": set()` and replace with `"files": []`. Find all `.add(fp)` on the files list and replace with: `files = sess.get("files", []); if fp not in files: files.append(fp)`. Grep for `set()` to confirm no remaining set usage.

### Task 2.3 — Add request body size limit to daemon.py (PE #9)

**File:** `daemon.py`

In the HTTP request handler's body-reading logic, add a 1MB cap:

```python
MAX_BODY = 1_000_000  # 1MB
if content_length > MAX_BODY:
    self._respond(413, {"error": "payload too large"})
    return {}
```

Same for Unix socket reader if present — cap buffer at 1MB.

### Task 2.4 — Add file permission enforcement

**File:** `db.py` — `init_db()` function, after `conn.close()`

Add: `os.chmod(DB_PATH, 0o600)` (import os at top). This prevents other users on shared machines from reading echo.db.

**Done when:** All db.py functions use try/finally. Daemon uses lists not sets. Daemon rejects >1MB. echo.db gets 600 permissions. Existing tests pass.

---

## BATCH 3: `nora_coach` MCP Tool

**File:** `nora_mcp.py`
**Est:** ~15 min
**Why:** The METR-study killer feature. No other dev tool teaches you to prompt better.

### Task 3.1 — Add `nora_coach` to tool list

**File:** `nora_mcp.py` — inside `list_tools()`, after the `nora_help` Tool definition (line 383)

Add new Tool:

```python
Tool(
    name="nora_coach",
    description=(
        "Your AI effectiveness coach. Shows how your prompting is improving over time, "
        "identifies your most common prompting anti-patterns, and gives you concrete "
        "before/after examples from YOUR OWN sessions. "
        "Think of it as a personal trainer for working with AI. "
        "Examples: 'nora coach', 'how am I doing with AI', 'how can I prompt better', "
        "'show my prompt quality trend', 'what are my prompting mistakes'."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many days of history to analyze. Default 30.",
                "default": 30,
            }
        },
    },
),
```

### Task 3.2 — Add coach routing in call_tool()

**File:** `nora_mcp.py` — inside `call_tool()`, after the `nora_help` elif (line 432)

Add:
```python
elif name == "nora_coach":
    result = self._coach(arguments.get("days", 30))
```

### Task 3.3 — Implement `_coach()` method

**File:** `nora_mcp.py` — add as new method after `_help()`

```python
def _coach(self, days: int = 30) -> str:
    """AI effectiveness coach — cross-session prompt quality analysis."""
    conn = self._connect_db()
    try:
        # 1. Quality trend over time
        trend_rows = conn.execute("""
            SELECT
                date(i.analyzed_at) as day,
                AVG(i.prompt_quality) as avg_quality,
                AVG(i.prompt_avg_words) as avg_words,
                SUM(i.repetition_count) as total_repetitions,
                COUNT(*) as session_count
            FROM insights i
            JOIN sessions s ON i.session_id = s.id
            WHERE i.analyzed_at > datetime('now', ? || ' days')
            GROUP BY date(i.analyzed_at)
            ORDER BY day
        """, (f"-{days}",)).fetchall()

        # 2. Anti-pattern frequency across sessions
        antipattern_rows = conn.execute("""
            SELECT prompt_antipatterns
            FROM insights
            WHERE analyzed_at > datetime('now', ? || ' days')
              AND prompt_antipatterns IS NOT NULL
              AND prompt_antipatterns != ''
              AND prompt_antipatterns != '[]'
        """, (f"-{days}",)).fetchall()

        # 3. Best and worst coaching examples
        coaching_rows = conn.execute("""
            SELECT prompt_coaching, prompt_quality, session_id
            FROM insights
            WHERE analyzed_at > datetime('now', ? || ' days')
              AND prompt_coaching IS NOT NULL
              AND prompt_coaching != ''
              AND prompt_coaching != '{}'
            ORDER BY prompt_quality ASC
            LIMIT 5
        """, (f"-{days}",)).fetchall()

        # 4. Overall stats
        overall = conn.execute("""
            SELECT
                AVG(prompt_quality) as avg_quality,
                MIN(prompt_quality) as min_quality,
                MAX(prompt_quality) as max_quality,
                COUNT(*) as total_sessions,
                AVG(prompt_avg_words) as avg_words
            FROM insights
            WHERE analyzed_at > datetime('now', ? || ' days')
        """, (f"-{days}",)).fetchone()

    finally:
        conn.close()

    # Format output
    lines = ["# Your AI Effectiveness Report", ""]

    # Overall score
    avg_q = overall["avg_quality"] or 0
    total = overall["total_sessions"] or 0
    grade = "A" if avg_q >= 0.85 else "B" if avg_q >= 0.7 else "C" if avg_q >= 0.5 else "D"
    lines.append(f"**Overall Grade: {grade}** ({avg_q:.2f}/1.00 across {total} sessions in {days} days)")
    lines.append(f"Average prompt length: {int(overall['avg_words'] or 0)} words")
    lines.append("")

    # Trend
    if len(trend_rows) >= 2:
        first_week = [r for r in trend_rows[:7]]
        last_week = [r for r in trend_rows[-7:]]
        first_avg = sum(r["avg_quality"] or 0 for r in first_week) / max(len(first_week), 1)
        last_avg = sum(r["avg_quality"] or 0 for r in last_week) / max(len(last_week), 1)
        delta = last_avg - first_avg
        arrow = "↑" if delta > 0.02 else "↓" if delta < -0.02 else "→"
        lines.append(f"**Trend:** {arrow} {'+' if delta > 0 else ''}{delta:.2f} (first week → last week)")
        lines.append("")

    # Anti-patterns
    import json as _json
    pattern_counts = {}
    for row in antipattern_rows:
        try:
            patterns = _json.loads(row["prompt_antipatterns"])
            for p in patterns:
                name = p.get("pattern", "unknown")
                pattern_counts[name] = pattern_counts.get(name, 0) + p.get("count", 1)
        except (_json.JSONDecodeError, TypeError):
            pass

    if pattern_counts:
        lines.append("## Your Most Common Anti-Patterns")
        lines.append("")
        sorted_patterns = sorted(pattern_counts.items(), key=lambda x: -x[1])
        pattern_labels = {
            "vague_request": "Vague requests — be specific about what you want",
            "missing_context": "Missing context — include file paths and line numbers",
            "no_file_reference": "No file references — tell the AI which files to look at",
            "repeated_instruction": "Repeated instructions — say it once, clearly",
            "no_error_message": "No error messages — paste the actual error",
            "too_broad": "Too broad — break big asks into focused steps",
        }
        for pattern, count in sorted_patterns[:5]:
            label = pattern_labels.get(pattern, pattern)
            lines.append(f"  {count}× — {label}")
        lines.append("")

    # Coaching examples (before/after)
    if coaching_rows:
        lines.append("## Learn From Your Own Sessions")
        lines.append("")
        for row in coaching_rows[:3]:
            try:
                coaching = _json.loads(row["prompt_coaching"])
                if coaching.get("weakest_prompt"):
                    lines.append(f"**Session** (quality: {row['prompt_quality']:.2f})")
                    lines.append(f"  ✗ Your prompt: \"{coaching['weakest_prompt']}\"")
                    lines.append(f"  ✓ Better version: \"{coaching['stronger_version']}\"")
                    lines.append(f"  Why: {coaching.get('why_better', '')}")
                    lines.append("")
            except (_json.JSONDecodeError, TypeError):
                pass

    # Tips based on data
    lines.append("## Personalized Tips")
    lines.append("")
    if avg_q < 0.5:
        lines.append("Your prompts are quite short and vague. The single biggest improvement: include the file path and line number when talking about code. This alone typically raises scores by +0.2.")
    elif avg_q < 0.7:
        lines.append("You're getting there. Focus on: (1) paste error messages verbatim instead of describing them, (2) specify the desired output format, (3) include context from your last attempt when retrying.")
    elif avg_q < 0.85:
        lines.append("Strong prompting. To reach the top tier: (1) give the AI your mental model of the problem before asking for a solution, (2) specify constraints upfront, (3) reference specific functions by name.")
    else:
        lines.append("Excellent. You're in the top tier of AI-effective developers. Keep doing what you're doing — your prompts are specific, contextual, and well-structured.")

    if pattern_counts.get("repeated_instruction", 0) > 3:
        lines.append("")
        lines.append("**Repetition alert:** You're repeating yourself often. If the AI isn't getting it, try rephrasing with more context rather than repeating the same instruction.")

    return "\n".join(lines)
```

**Done when:** `nora coach` returns a formatted report with quality grade, trend, anti-patterns, before/after examples, and personalized tips. Returns gracefully when no data exists.

---

## BATCH 4: `nora_onboard` MCP Tool + Help Update

**File:** `nora_mcp.py`
**Est:** ~12 min
**Why:** First-run experience. Without this, new users install and have no idea what to do.

### Task 4.1 — Add `nora_onboard` to tool list

After `nora_coach` Tool definition, add:

```python
Tool(
    name="nora_onboard",
    description=(
        "First-run codebase tour. Scans your project to identify: architecture, "
        "key files, tech stack, test coverage, and complexity hotspots. "
        "Run this on any new project to give Nora (and yourself) a quick orientation. "
        "Examples: 'nora onboard', 'scan this project', 'what is this codebase', "
        "'give me a tour of this project'."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Project root to scan. Default: current directory.",
                "default": ".",
            }
        },
    },
),
```

### Task 4.2 — Add routing and implement `_onboard()`

Add routing in `call_tool()`:
```python
elif name == "nora_onboard":
    result = self._onboard(arguments.get("directory", "."))
```

Implement `_onboard()`: Use `subprocess.run` to execute:
1. `find <dir> -name '*.py' -o -name '*.ts' -o -name '*.js' -o -name '*.swift' -o -name '*.rs' -o -name '*.go' | head -100` — identify language
2. `wc -l` on key files — size estimation
3. `ls <dir>` — identify framework markers (package.json, Cargo.toml, go.mod, Podfile, etc.)
4. `git log --oneline -10` — recent activity
5. `find <dir> -name '*test*' -o -name '*spec*' | wc -l` — test coverage signal

Output a structured report: "This is a [language] project using [framework], ~X files, ~Y lines. Key directories: [...]. Recent activity: [...]. Test coverage: [X test files found]. Recommended next steps: nora scan <path> to import history."

### Task 4.3 — Update `_help()` to include new tools

**File:** `nora_mcp.py` — `_help()` method (lines ~1370-1480)

Add a new section before the META section:

```
━━━ AI COACHING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nora coach [days]
    Your personal AI effectiveness trainer. Shows prompt quality trend,
    identifies your anti-patterns, gives before/after examples from YOUR
    OWN sessions. The tool that closes the METR gap.
    Examples: "nora coach"       (last 30 days)
              "nora coach 90"    (last quarter)
              "how can I prompt better"

  nora onboard [dir]
    First-run project tour. Identifies language, framework, key files,
    test coverage, and complexity. Run on any new project.
    Examples: "nora onboard"           (current directory)
              "nora onboard ~/code/api" (specific project)
              "what is this codebase"
```

Update the QUICK START section:
```
  Just installed?     → nora onboard, then nora scan ~/code/your-project
  ...
  Want to improve?    → nora coach
```

Update tool count from "16" to "18" in all help text references.

**Done when:** `nora onboard` returns a structured project report. `nora help` lists 18 tools including coach and onboard. Quick start mentions both.

---

## BATCH 5: Dashboard Foundation — Persona Config, Nav, CSS

**File:** `dashboard.py`
**Est:** ~15 min
**Why:** Foundation for all dashboard page batches.

### Task 5.1 — Add PERSONA_CONFIG dict

**File:** `dashboard.py` — after the CSS string constant (after line ~126)

```python
PERSONA_CONFIG = {
    "engineering": {
        "kpi_labels": ["Sessions", "Patterns", "Bugs", "Prompt Quality"],
        "language": {"bugs": "Bugs", "learnings": "Knowledge", "sessions": "Activity"},
        "sort_key": "effectiveness",
    },
    "product": {
        "kpi_labels": ["Decisions", "Outcomes", "Velocity", "Knowledge"],
        "language": {"bugs": "Issues", "learnings": "Knowledge", "sessions": "Activity"},
        "sort_key": "recency",
    },
    # R2: Add PM, Sales, Legal, Finance, Executive personas
}

def get_persona() -> str:
    """Read persona from config.toml, default to engineering."""
    if CFG.exists() and tomllib is not None:
        try:
            with open(CFG, "rb") as f:
                cfg = tomllib.load(f)
            return cfg.get("dashboard", {}).get("persona", "engineering")
        except Exception:
            pass
    return "engineering"
```

### Task 5.2 — Rename nav tabs

**File:** `dashboard.py` — the nav generation section (around line 271)

Replace current nav list with:
```python
nav_items = [
    ("Home", "/"),
    ("Activity", "/sessions"),
    ("Issues", "/bugs"),
    ("Knowledge", "/learnings"),
    ("Memory", "/memory"),
    ("Decisions", "/decisions"),
    ("Coach", "/coach"),
    ("Settings", "/settings"),
]
```

Note: 8 tabs — the original 7 redesign tabs + Coach.

### Task 5.3 — CSS upgrade

**File:** `dashboard.py` — the CSS string constant (lines 67-126)

Apply the redesign's CSS changes:
- Font: body font from `ui-monospace,monospace` → `Inter,ui-sans-serif,system-ui,sans-serif`. Keep monospace for `code`, `.kpi-val`.
- Spacing: standardize to 8px grid (8, 16, 24, 32px).
- Card elevation: add `box-shadow: 0 1px 3px rgba(0,0,0,.3)` to `.card`.
- Active nav: change from border-bottom to `background: rgba(29,158,117,.1); border-radius: 6px`.
- Add semantic color vars: `--success:var(--teal);--warning:var(--amber);--danger:var(--red);--info:var(--blue)`.

**Done when:** Dashboard loads with new nav (8 tabs), new font, updated CSS. `get_persona()` returns "engineering" by default.

---

## BATCH 6: Home Page Redesign

**File:** `dashboard.py`
**Est:** ~15 min
**Depends on:** Batch 5

### Task 6.1 — Rewrite index() route with value-first KPIs

**File:** `dashboard.py` — `@app.route("/")` handler (line 309)

Replace the current KPI row with 4 persona-aware KPIs. Query:
- Pattern count: `SELECT COUNT(*) FROM patterns`
- Decision count: `SELECT COUNT(*) FROM decisions`
- Bug fix count: `SELECT COUNT(*) FROM reported_bugs WHERE fix_code != ''`
- Avg prompt quality: `SELECT AVG(prompt_quality) FROM insights WHERE prompt_quality > 0`

### Task 6.2 — Add Intelligence Compounding visualization

Below KPIs, add a card with horizontal progress bars showing patterns, decisions, bug fixes growing over time. Include projection: "At [X patterns/week], you'll have [Y] in 6 months." Query: `SELECT COUNT(*) FROM patterns WHERE created_at > datetime('now', '-7 days')`.

### Task 6.3 — Add Quick Wins + Recent Activity two-column layout

Left column: top 5 patterns by effectiveness DESC. Right column: last 5 sessions with time-ago formatting and outcome indicator (green/amber/red dot).

**Done when:** Home page shows 4 value KPIs, compounding progress with projection, quick wins, recent activity. No more raw data dump.

---

## BATCH 7: Knowledge + Memory + Decisions Pages

**File:** `dashboard.py`
**Est:** ~20 min
**Depends on:** Batch 5

### Task 7.1 — Rewrite /learnings as unified Knowledge page

Three sections: (a) "Best Practices" — patterns sorted by effectiveness DESC with colored bar (green >0.8, amber 0.5-0.8, red <0.5), domain pills. (b) "Playbooks" — from insights.skill_opportunity, filtered non-empty. (c) "Mistakes to Avoid" — from insights anti-patterns. Add domain filter at top via HTMX.

### Task 7.2 — Implement /memory route

Currently missing (nav link exists, no handler). Create route that shows:
- "What Nora Injects" — rendered hot memory preview (call `get_hot_memory()` from db.py if it exists, or query directly)
- "Memory Components" — 4 cards: Last Session summary, Top Patterns count, Bug Hotspots, Prompt Quality trend
- Hook event timeline — last 50 events from hook_events table, vertical timeline with colored dots by event type

### Task 7.3 — Implement /decisions route

Currently missing. Create route that queries `decisions` table: decision text, rationale, alternatives, linked files as pills. Add HTMX search filter at top. Sort by created_at DESC.

**Done when:** All 3 routes render with data. Knowledge has effectiveness bars and domain filter. Memory shows injection preview. Decisions has search. No more broken nav links.

---

## BATCH 8: Coach Tab + Activity Polish + Settings Cleanup

**File:** `dashboard.py`
**Est:** ~20 min
**Depends on:** Batch 5-7

### Task 8.1 — Implement /coach route (the flagship new feature)

New route showing the AI Education dashboard:

**Section 1: "Your AI Effectiveness Score"**
- Large grade display (A/B/C/D) based on avg prompt_quality
- Sparkline of daily prompt_quality over last 30 days (text-based, e.g., `▁▂▃▅▇▆▅▇` using Unicode block elements)
- Session count, avg words per prompt, repetition rate

**Section 2: "Your Anti-Patterns"**
- Aggregate prompt_antipatterns from insights over last 30 days
- Show top 5 anti-patterns as cards with count, description, and fix tip
- Categories: vague_request, missing_context, no_file_reference, repeated_instruction, no_error_message, too_broad
- Each card has a colored severity indicator

**Section 3: "Learn From Your Sessions"**
- Last 5 prompt_coaching entries
- Each shows: weak prompt → strong version → why better
- Sorted by prompt_quality ASC (worst first — most to learn from)

**Section 4: "Tips for Your Level"**
- Based on avg_quality: beginner (<0.5), intermediate (0.5-0.7), advanced (0.7-0.85), expert (0.85+)
- 3-5 concrete tips tailored to the level, drawn from the user's actual anti-pattern data
- Links to `nora coach` for CLI access

**Queries needed:**
```sql
-- Daily quality trend
SELECT date(analyzed_at) as day, AVG(prompt_quality) as q
FROM insights WHERE analyzed_at > datetime('now', '-30 days')
GROUP BY day ORDER BY day;

-- Anti-pattern aggregation
SELECT prompt_antipatterns FROM insights
WHERE analyzed_at > datetime('now', '-30 days')
  AND prompt_antipatterns IS NOT NULL AND prompt_antipatterns != '[]';

-- Coaching examples
SELECT prompt_coaching, prompt_quality FROM insights
WHERE prompt_coaching IS NOT NULL AND prompt_coaching != '{}'
ORDER BY prompt_quality ASC LIMIT 5;

-- Overall stats
SELECT AVG(prompt_quality), COUNT(*), AVG(prompt_avg_words),
       SUM(repetition_count) FROM insights
WHERE analyzed_at > datetime('now', '-30 days');
```

### Task 8.2 — Polish Activity (/sessions) page

- Add time-ago formatting (replace raw datetime with "2 hours ago", "Yesterday")
- Add session outcome indicator: green dot (no bugs), amber (bugs found), red (errors)
- Add HTMX session type filter pills at top
- Use persona language for session types

### Task 8.3 — Settings cleanup

- Remove AWS credential form fields from Kiro mode settings (lines 927-938 — the S3 Backup section with plaintext Access Key ID and Secret Access Key inputs)
- Replace with: "Configure cloud sync via environment variables — see docs."
- Add `os.chmod(CFG, 0o600)` after every config.toml write in the settings POST handler
- Keep: persona selector, LLM provider, model display, telemetry, privacy notice
- Add persona dropdown to topbar (next to "AI Work Intelligence" text)

**Done when:** Coach tab renders with 4 sections. Activity has time-ago and outcome dots. Settings has no credential fields. File permissions set to 600.

---

## BATCH 9: Integration Test + Final Polish

**Files:** All modified files
**Est:** ~10 min
**Depends on:** All previous batches

### Task 9.1 — Verify all routes work

Start dashboard (`python dashboard.py`) and verify:
- `/` — Home loads with KPIs, compounding viz, quick wins
- `/sessions` — Activity with time-ago, outcome dots
- `/bugs` — Issues page renders
- `/learnings` — Knowledge with patterns, playbooks, anti-patterns
- `/memory` — Memory with injection preview
- `/decisions` — Decisions with search
- `/coach` — Coach with grade, trend, anti-patterns, coaching examples
- `/settings` — No AWS creds, has persona selector

### Task 9.2 — Verify MCP tools

- `nora_help` output lists 18 tools
- `nora_coach` returns formatted report (may be empty if no sessions)
- `nora_onboard` returns project scan for current directory

### Task 9.3 — Update tool count references

Grep all files for "16 tools" or "16 Nora tools" and update to "18 tools" or "18 Nora tools":
- `nora_mcp.py` — help text, docstring
- `dashboard.py` — settings page "MCP Tools (16)" heading
- Any README references

**Done when:** All 8 dashboard routes render. 18 MCP tools listed. No "16 tools" references remain. `python db.py` initializes clean. No import errors.

---

## File Change Summary

| File | Lines Today | Changes |
|------|-----------|---------|
| `db.py` | 164 | +30 (coaching_trends table, new columns, try/finally, chmod) |
| `analyzer.py` | 204 | +20 (expanded prompt with coaching fields) |
| `nora_mcp.py` | 1502 | +200 (nora_coach ~130 lines, nora_onboard ~50 lines, help update ~20 lines) |
| `dashboard.py` | 1618 | +400 (coach route ~120, memory route ~80, decisions route ~60, home redesign ~80, CSS ~40, nav ~20) |
| `daemon.py` | 155 | +10 (set→list fix, body size limit) |
| **Total** | **~6500** | **+660 lines net** |

---

## Agent Launch Prompt

Use this prompt to launch parallel Sonnet agents for each phase:

### Phase 1 Agents (launch together — no dependencies)

**Agent A — DB + Analyzer (Batches 1-2):**
```
You are implementing Batches 1-2 of the Nora R1 release.

Working directory: kiro-extension/bundled/

BATCH 1 — DB Schema + Analyzer:
1. In db.py init_db(), add two columns to insights table: prompt_coaching TEXT, prompt_antipatterns TEXT
2. Add new coaching_trends table (see spec for schema)
3. Update mark_analyzed() to store prompt_coaching and prompt_antipatterns
4. In analyzer.py, expand the PROMPT string to include prompt_coaching and prompt_antipatterns in the required JSON format. Add rules explaining each field.

BATCH 2 — PE Fixes:
1. Wrap ALL db.py functions that call get_conn() in try/finally with conn.close() in finally
2. Add os.chmod(DB_PATH, 0o600) after DB creation in init_db()
3. In daemon.py, replace all set() usage for files with list(). Replace .add(fp) with append-if-not-present.
4. In daemon.py, add MAX_BODY = 1_000_000 check in the HTTP body reader, return 413 if exceeded.

IMPORTANT: Read each file completely before editing. Preserve all existing functionality. Do NOT break any existing tests.
```

**Agent B — New MCP Tools (Batches 3-4):**
```
You are implementing Batches 3-4 of the Nora R1 release.

Working directory: kiro-extension/bundled/
Target file: nora_mcp.py

BATCH 3 — nora_coach tool:
1. Add Tool definition for nora_coach after nora_help (line ~383). Description: AI effectiveness coach showing prompt quality trends, anti-patterns, before/after examples.
2. Add routing in call_tool(): elif name == "nora_coach": result = self._coach(arguments.get("days", 30))
3. Implement _coach() method that queries: daily quality trend, anti-pattern frequency, coaching examples, overall stats. Returns formatted markdown report with grade, trend arrow, anti-pattern list, before/after examples, personalized tips.

BATCH 4 — nora_onboard tool + help update:
1. Add Tool definition for nora_onboard after nora_coach. Description: first-run codebase tour.
2. Add routing: elif name == "nora_onboard": result = self._onboard(arguments.get("directory", "."))
3. Implement _onboard() using subprocess.run to scan project directory: identify language, framework, key files, test coverage, recent git activity. Return structured report.
4. Update _help() method: add AI COACHING section with nora_coach and nora_onboard. Update QUICK START. Change all "16 tools" to "18 tools".

IMPORTANT: Read nora_mcp.py completely before editing. The file is 1502 lines. Match existing code patterns exactly. Use _connect_db() for all DB access. All DB operations in try/finally.
```

### Phase 2 Agents (launch after Phase 1 completes)

**Agent C — Dashboard Redesign (Batches 5-8):**
```
You are implementing Batches 5-8 of the Nora R1 release — the complete dashboard redesign.

Working directory: kiro-extension/bundled/
Target file: dashboard.py (1618 lines, Flask + HTMX, server-rendered HTML)

BATCH 5 — Foundation:
1. Add PERSONA_CONFIG dict after CSS constant. Two personas for R1: engineering (default), product.
2. Add get_persona() helper that reads from config.toml.
3. Rename nav: Home, Activity, Issues, Knowledge, Memory, Decisions, Coach, Settings (8 tabs).
4. CSS upgrade: body font to Inter/system-ui, 8px grid spacing, card box-shadow, semantic color vars.

BATCH 6 — Home Page:
1. Rewrite index() route: 4 value-first KPIs (sessions, patterns, decisions, quality).
2. Add Intelligence Compounding visualization: progress bars + projection text.
3. Add Quick Wins (top 5 patterns) + Recent Activity (last 5 sessions) two-column layout.

BATCH 7 — Knowledge + Memory + Decisions:
1. Rewrite /learnings as Knowledge page: patterns with effectiveness bars, playbooks, anti-patterns. Domain filter via HTMX.
2. Create /memory route: hot memory preview, 4 component cards, hook event timeline.
3. Create /decisions route: decision cards with rationale/alternatives, HTMX search.

BATCH 8 — Coach + Activity + Settings:
1. Create /coach route with 4 sections: AI Effectiveness Score (grade + sparkline), Anti-Patterns (aggregated cards), Learn From Sessions (before/after examples), Tips for Your Level.
2. Polish /sessions: time-ago formatting, outcome dots, type filter pills.
3. Settings: remove AWS credential fields, add chmod 600 on config writes, add persona dropdown to topbar.

IMPORTANT: Read dashboard.py completely before editing. It's server-rendered HTML in Python f-strings. Match the existing dark theme (--bg:#07090d). Use HTMX for interactivity (hx-get, hx-target). No JavaScript frameworks. No npm. All queries go to echo.db via sqlite3.
```

### Phase 3 Agent (launch after Phase 2 completes)

**Agent D — Verification (Batch 9):**
```
You are running the verification pass for Nora R1.

Working directory: kiro-extension/bundled/

1. Run: python db.py — verify it creates tables without error
2. Grep all files for "16 tools" or "16 Nora" — update any remaining references to "18"
3. Verify nora_mcp.py has 18 Tool() definitions in list_tools()
4. Verify dashboard.py has 8 nav items and routes for: /, /sessions, /bugs, /learnings, /memory, /decisions, /coach, /settings
5. Verify no import errors: python -c "import db; import analyzer; import dashboard; import nora_mcp"
6. Verify daemon.py has no set() usage for files tracking
7. Verify db.py all functions use try/finally for connection cleanup
8. Report: pass/fail for each check
```
