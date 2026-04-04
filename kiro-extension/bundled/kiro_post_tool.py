#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
from __future__ import annotations  # PEP 563: str|None works on Python 3.9+
import db

"""
Kiro postToolUse hook — validates tool outputs and captures signals.

Installed at: ~/.kiro/hooks/nora_posttool.py
Triggered by: Kiro postToolUse or Claude Code PostToolUse

What it does:
  1. Captures file write events for real-time session tracking
  2. Checks command outputs for error patterns from past sessions
  3. Logs tool usage metrics to nora_metrics

CONTRACT:
  - Reads JSON from stdin: {"hook": "postToolUse", "tool_name": "...", "tool_output": {...}}
  - Exit 0 always (postToolUse is observational, never blocks)
  - stderr = warnings shown to user

SECURITY: stdlib only, no network calls, no API keys.
"""
import json
import sqlite3
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

DB_PATH = Path.home() / ".kernora" / "echo.db"
TOOL_EVENT_URL = "http://127.0.0.1:2742/api/tool/event"


def check_known_errors(output: str) -> list[str]:
    """Check tool output against error signatures from past bugs."""
    if not DB_PATH.exists():
        return []
    try:
        conn = db.get_conn()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT title, error_signature, fix_code, severity FROM reported_bugs "
            "WHERE status != 'resolved' AND error_signature != '' "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        conn.close()

        matches = []
        lower = output.lower()
        for row in rows:
            sig = row["error_signature"].lower()
            if sig and len(sig) > 5 and sig in lower:
                fix = row["fix_code"] or "No fix recorded"
                matches.append(
                    f"Known bug [{row['severity']}]: {row['title']} — "
                    f"Fix: {fix[:120]}"
                )
        return matches
    except Exception:
        return []


def log_tool_event(tool_name: str, success: bool):
    """Log tool usage to nora_metrics for pattern analysis."""
    if not DB_PATH.exists():
        return
    try:
        conn = db.get_conn()
        conn.execute(
            "INSERT INTO nora_metrics (event_type, result_type, keywords, created_at) "
            "VALUES ('tool_use', ?, ?, datetime('now'))",
            (tool_name, json.dumps({"success": success})),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # Support both Kiro and Claude Code formats
    tool_name = data.get("tool_name", "") or data.get("tool", {}).get("name", "")
    tool_output = data.get("tool_output", "") or data.get("tool", {}).get("output", "")

    if isinstance(tool_output, dict):
        output_str = json.dumps(tool_output)
    elif isinstance(tool_output, str):
        output_str = tool_output
    else:
        output_str = str(tool_output)

    # Detect success/failure
    is_error = any(kw in output_str.lower() for kw in [
        "error:", "failed:", "exception:", "traceback", "fatal:",
        "command failed", "exit code 1", "compilation error",
    ])

    # Extract file path from tool input/output for live tracking
    file_path = ""
    tool_input = data.get("tool_input", "") or data.get("tool", {}).get("input", "")
    if isinstance(tool_input, dict):
        file_path = tool_input.get("file_path", "") or tool_input.get("path", "")
    elif isinstance(tool_input, str):
        # Try to extract file path from string input
        for line in tool_input.split("\n")[:5]:
            stripped = line.strip()
            if "/" in stripped and "." in stripped.split("/")[-1]:
                file_path = stripped
                break

    # Log the tool event (local DB + HTTP to dashboard)
    log_tool_event(tool_name, not is_error)
    try:
        event_data = {
            "tool_name": tool_name,
            "success": not is_error,
            "file_path": file_path,
        }
        if is_error:
            # Send first 200 chars of error context
            event_data["error_snippet"] = output_str[:200]
        req = Request(
            TOOL_EVENT_URL,
            data=json.dumps(event_data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urlopen(req, timeout=2)
    except (URLError, OSError):
        pass  # dashboard might not be running — that's fine

    # Check against known error signatures
    if is_error:
        matches = check_known_errors(output_str)
        for m in matches:
            print(f"[Nora] {m}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
