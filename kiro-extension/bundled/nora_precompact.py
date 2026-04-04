#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
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
import db
import json
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"
PRE_COMPACT_CONTEXT_FILE = Path.home() / ".kernora" / "pre_compact_context.json"


def get_session_insights(session_id: str) -> dict:
    """
    Query echo.db for insights from the given session.
    Returns dict with critical_patterns, recent_decisions, open_issues, summary.
    """
    if not DB_PATH.exists():
        return {}

    try:
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


def save_pre_compact_context(context: dict):
    """Save context to ~/.kernora/pre_compact_context.json for recovery after compaction."""
    PRE_COMPACT_CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        PRE_COMPACT_CONTEXT_FILE.write_text(json.dumps(context, indent=2))
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

    if hook_event_name != "PreCompact" or not session_id:
        sys.exit(0)

    # Get critical context from this session before it's compacted away
    context = get_session_insights(session_id)

    # Save to file for retrieval on SessionStart(source="compact")
    if context:
        save_pre_compact_context(context)

    sys.exit(0)


if __name__ == "__main__":
    main()
