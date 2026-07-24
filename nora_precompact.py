#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""
Claude Code PreCompact hook — saves session context before compaction.

Installed at: ~/.claude/hooks/nora_precompact.py
Triggered by: Claude Code PreCompact (fires before context window compaction)

What it does:
  1. Extracts critical context from the current session_id
  2. Queries echo.db for insights, patterns, decisions from this session
  3. Saves them to ~/.kernora/pre_compact_context.json
  4. On the next SessionStart(source="compact"), nora_session_start.py reads this file

This prevents valuable context from being discarded during compaction.

CONTRACT:
  - Reads JSON from stdin: {"hook_event_name": "PreCompact", "session_id": "...", "cwd": "...", ...}
  - Writes to ~/.kernora/pre_compact_context.json (overwrites previous)
  - Exit 0 always (PreCompact must never block)

SECURITY: stdlib only, no network calls, no API keys.
"""
# C5 fix (2026-04-23): lazy-import db inside function scope. The top-level
# `import db` was a 3s-timeout-exceeding hazard when sqlite-vec / sentence-
# transformers imports cold-started.
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"
# H1 fix (2026-04-23): session-scoped file so concurrent Claude Code
# sessions don't stomp each other's pre-compact context.
PRE_COMPACT_DIR = Path.home() / ".kernora" / "pre_compact"


def _pre_compact_file(session_id: str) -> Path:
    """Per-session path for saved context; survives concurrent sessions."""
    safe_sid = "".join(c for c in (session_id or "unknown") if c.isalnum() or c in "-_")
    return PRE_COMPACT_DIR / f"{safe_sid or 'unknown'}.json"


def get_session_insights(session_id: str) -> dict:
    """
    Query echo.db for insights from the given session.
    Returns dict with critical_patterns, recent_decisions, open_issues, summary.
    """
    if not DB_PATH.exists():
        return {}

    try:
        # Lazy import — avoids 3s+ transitive import cost on hook load.
        import db  # type: ignore
        conn = db.get_conn()
        conn.row_factory = sqlite3.Row

        # Get insights for this session
        insight = conn.execute("""
            SELECT summary, themes, anti_patterns, reusable_patterns,
                   architectural_decisions, claude_md_rules, playbook
            FROM insights
            WHERE session_id = ?
            LIMIT 1
        """, (session_id,)).fetchone()

        if not insight:
            conn.close()
            return {}

        insight_dict = dict(insight)

        # Parse JSON fields
        critical_patterns = []
        try:
            patterns = json.loads(insight_dict.get('reusable_patterns', '[]'))
            critical_patterns = patterns[:5]  # Top 5 patterns
        except json.JSONDecodeError:
            pass

        recent_decisions = []
        try:
            decisions = json.loads(insight_dict.get('architectural_decisions', '[]'))
            recent_decisions = decisions[:5]  # Top 5 decisions
        except json.JSONDecodeError:
            pass

        # Get open bugs from this session
        open_issues = []
        bugs = conn.execute("""
            SELECT title, severity FROM reported_bugs
            WHERE session_id = ? AND status IN ('open', 'in_progress')
            ORDER BY severity DESC, created_at DESC
            LIMIT 5
        """, (session_id,)).fetchall()

        for bug in bugs:
            open_issues.append(f"[{bug['severity'].upper()}] {bug['title']}")

        conn.close()

        return {
            "critical_patterns": critical_patterns,
            "recent_decisions": recent_decisions,
            "open_issues": open_issues,
            "summary": insight_dict.get('summary', ''),
        }

    except Exception:
        return {}


def save_pre_compact_context(context: dict, session_id: str):
    """Save context to a per-session file for recovery on next SessionStart."""
    PRE_COMPACT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _pre_compact_file(session_id).write_text(json.dumps(context, indent=2))
    except Exception:
        pass  # PreCompact hook must never block


def main():
    """Main hook entry point."""
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    hook_event_name = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")
    cwd = data.get("cwd", "") or os.getcwd()

    if hook_event_name != "PreCompact" or not session_id:
        sys.exit(0)

    # Get critical context from this session before it's compacted away
    context = get_session_insights(session_id)

    #  (JWM field report #3 item 1) — stamp project + saved_at
    # so the SessionStart reader can refuse to render a recovery blob that
    # belongs to a different project or has gone stale (see
    # nora_session_start.py's TTL/project check on the read side). Without
    # these fields a reader can't tell "this session's context" from "some
    # other project's context from three months ago."
    if context:
        try:
            import sys as _sys_proj
            _sys_proj.path.insert(0, str(Path.home() / ".kernora" / "app"))
            import db as _db_proj  # type: ignore
            context["project"] = _db_proj.canonical_project(cwd)
        except Exception:
            context["project"] = None
        context["saved_at"] = time.time()

    # Save to per-session file for retrieval on SessionStart(source="compact")
    if context:
        save_pre_compact_context(context, session_id)

    sys.exit(0)


if __name__ == "__main__":
    main()
