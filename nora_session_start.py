#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
"""
Claude Code SessionStart hook — injects project context at session start.

Installed at: ~/.claude/hooks/nora_session_start.py
Triggered by: Claude Code SessionStart (startup, resume, compact)

What it does:
  1. Checks daemon health via socket
  2. Gets session stats for the current project directory
  3. On source="startup": inject brief status + top 3 patterns for project
  4. On source="resume": inject minimal status only
  5. On source="compact": restore context from pre_compact_context.json (critical findings that were lost to compaction)

CONTRACT:
  - Reads JSON from stdin: {"hook_event_name": "SessionStart", "session_id": "...", "cwd": "...", "source": "startup|resume|clear|compact"}
  - stdout = context injected into Claude's context window (ONLY for startup/compact)
  - Exit 0 always

SECURITY: stdlib only, no network calls, no API keys.
"""
import json
import os
import socket
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"
SOCK_PATH = Path.home() / ".kernora" / "daemon.sock"
PRE_COMPACT_CONTEXT_FILE = Path.home() / ".kernora" / "pre_compact_context.json"


def check_daemon_health() -> bool:
    """Test if daemon is alive via socket."""
    if not SOCK_PATH.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(str(SOCK_PATH))
        return True
    except (ConnectionRefusedError, OSError, FileNotFoundError):
        return False


def get_project_sessions(project_path: str) -> int:
    """Count sessions for the given project directory."""
    if not DB_PATH.exists():
        return 0
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            "SELECT count(*) as cnt FROM sessions WHERE project = ?",
            (project_path,)
        ).fetchone()
        conn.close()
        return result['cnt'] if result else 0
    except Exception:
        return 0


def get_top_patterns_for_project(project_path: str, limit: int = 3) -> list:
    """
    Get top patterns by effectiveness/recency for the given project.
    Returns list of {pattern, code_example, effectiveness}.
    """
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        conn.row_factory = sqlite3.Row

        # Get patterns from sessions in this project, ordered by effectiveness and recency
        rows = conn.execute("""
            SELECT DISTINCT p.id, p.pattern, p.code_example, p.effectiveness, p.created_at
            FROM patterns p
            JOIN sessions s ON s.id = p.session_id
            WHERE s.project = ?
            ORDER BY p.effectiveness DESC, p.created_at DESC
            LIMIT ?
        """, (project_path, limit)).fetchall()

        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def format_startup_context(project_path: str, session_count: int, patterns: list) -> str:
    """Format context for startup source."""
    lines = []
    lines.append("")
    lines.append("─── Nora Session Started ───")

    if session_count == 0:
        lines.append(f"[Nora] New project. Ready to learn.")
    else:
        lines.append(f"[Nora] Session started for {Path(project_path).name}")
        lines.append(f"[Nora] Found {session_count} past sessions in this project.")

    if patterns:
        lines.append("")
        lines.append("Top patterns from past sessions:")
        for i, p in enumerate(patterns, 1):
            pattern_text = p.get('pattern', '?')
            effectiveness = p.get('effectiveness', 0)
            lines.append(f"  {i}. {pattern_text} (effectiveness: {effectiveness:.0%})")
            if p.get('code_example'):
                example = p['code_example'][:80]
                lines.append(f"     Example: {example}")

    lines.append("─── End Nora Context ───")
    lines.append("")

    return "\n".join(lines)


def format_compact_context(saved_context: dict) -> str:
    """Format context from pre_compact_context.json for recovery after compaction."""
    lines = []
    lines.append("")
    lines.append("─── Nora Pre-Compaction Recovery ───")
    lines.append("These insights were captured before context compaction.")
    lines.append("")

    # Format each saved insight type
    if saved_context.get('critical_patterns'):
        lines.append("CRITICAL PATTERNS (must remember):")
        for p in saved_context['critical_patterns']:
            lines.append(f"  • {p}")
        lines.append("")

    if saved_context.get('recent_decisions'):
        lines.append("RECENT ARCHITECTURAL DECISIONS:")
        for d in saved_context['recent_decisions']:
            lines.append(f"  • {d}")
        lines.append("")

    if saved_context.get('open_issues'):
        lines.append("OPEN ISSUES TO REMEMBER:")
        for issue in saved_context['open_issues']:
            lines.append(f"  • {issue}")
        lines.append("")

    if saved_context.get('summary'):
        lines.append(f"SUMMARY: {saved_context['summary']}")
        lines.append("")

    lines.append("─── End Recovery Context ───")
    lines.append("")

    return "\n".join(lines)


def format_resume_context(session_count: int) -> str:
    """Format minimal context for resume source."""
    lines = []
    lines.append("")
    lines.append(f"[Nora] Session resumed. {session_count} sessions in memory.")
    lines.append("")
    return "\n".join(lines)


def main():
    """Main hook entry point."""
    start_time = time.time()

    # Read hook input from Claude Code
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    hook_event_name = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")
    cwd = data.get("cwd", os.getcwd())
    source = data.get("source", "startup")  # startup, resume, clear, compact

    if hook_event_name != "SessionStart":
        sys.exit(0)

    # Get session count for this project
    session_count = get_project_sessions(cwd)

    # Generate context based on source
    output = ""

    if source == "startup":
        # Startup: inject status + top patterns
        patterns = get_top_patterns_for_project(cwd, limit=3)
        output = format_startup_context(cwd, session_count, patterns)

    elif source == "compact":
        # Compact: restore critical context from pre-compaction save
        if PRE_COMPACT_CONTEXT_FILE.exists():
            try:
                saved = json.loads(PRE_COMPACT_CONTEXT_FILE.read_text())
                output = format_compact_context(saved)
            except (json.JSONDecodeError, Exception):
                # If recovery file corrupted, fall back to patterns
                patterns = get_top_patterns_for_project(cwd, limit=3)
                output = format_startup_context(cwd, session_count, patterns)
        else:
            # No pre-compact file; inject patterns as fallback
            patterns = get_top_patterns_for_project(cwd, limit=3)
            output = format_startup_context(cwd, session_count, patterns)

    elif source == "resume":
        # Resume: minimal context only
        output = format_resume_context(session_count)

    # elif source == "clear" — no output needed

    # Output to stdout (Claude Code adds to context)
    if output:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
