#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
"""
Kiro preToolUse hook — validates tool invocations before execution.

Installed at: ~/.kiro/hooks/nora_pretool.py  (also works as ~/.claude/hooks/)
Triggered by: Kiro preToolUse or Claude Code PreToolUse

CONTRACT:
  - Reads JSON from stdin: {"hook": "preToolUse", "tool_name": "...", "tool_input": {...}}
  - Exit 0 = allow tool execution
  - Exit 2 = BLOCK tool execution (Kiro contract; Claude Code uses exit 1)
  - stderr = warning/error message shown to user

SECURITY: stdlib only, no network calls, no API keys.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"

# ── Danger patterns for spec/file write validation ──────────────────────────
DANGER_KEYWORDS = [
    "rewrite entire",
    "refactor all",
    "allow public access",
    "chmod 777",
    "drop table",
    "bypass auth",
    "disable security",
    "rm -rf /",
    "delete all",
    "truncate table",
]

# Tools that write files or execute commands — validate these
WRITE_TOOLS = {"fs_write", "Write", "write_file", "execute_bash", "Bash", "bash"}
SPEC_TOOLS = {"create_spec", "generate_spec", "spec_create"}


def check_danger(content: str) -> list[str]:
    """Check content for dangerous patterns. Returns list of violations."""
    lower = content.lower()
    return [kw for kw in DANGER_KEYWORDS if kw in lower]


def check_anti_patterns(content: str) -> list[str]:
    """Check content against anti-patterns learned from past sessions."""
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT anti_patterns FROM insights WHERE anti_patterns != '[]' "
            "ORDER BY analyzed_at DESC LIMIT 10"
        ).fetchall()
        conn.close()

        warnings = []
        lower = content.lower()
        for row in rows:
            try:
                patterns = json.loads(row["anti_patterns"])
                for ap in patterns:
                    pattern_text = ap.get("pattern", "").lower()
                    # Only match if the anti-pattern is specific enough (>10 chars)
                    if len(pattern_text) > 10 and pattern_text in lower:
                        warnings.append(
                            f"Anti-pattern from past session: {ap.get('pattern')} "
                            f"(impact: {ap.get('impact', 'unknown')})"
                        )
            except (json.JSONDecodeError, TypeError):
                continue
        return warnings
    except Exception:
        return []


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # Support both Kiro and Claude Code hook formats
    tool_name = data.get("tool_name", "") or data.get("tool", {}).get("name", "")
    tool_input = data.get("tool_input", {}) or data.get("tool", {}).get("input", {})

    # Only validate write/exec/spec tools — pass through reads
    if tool_name not in WRITE_TOOLS and tool_name not in SPEC_TOOLS:
        sys.exit(0)

    # Build content string to validate
    content_parts = []
    if isinstance(tool_input, dict):
        for v in tool_input.values():
            if isinstance(v, str):
                content_parts.append(v)
    elif isinstance(tool_input, str):
        content_parts.append(tool_input)

    content = "\n".join(content_parts)
    if not content:
        sys.exit(0)

    # Check for danger patterns
    violations = check_danger(content)
    if violations:
        print(
            f"[Nora Shield] Blocked: dangerous pattern(s) detected: {', '.join(violations)}. "
            f"Decompose the task or remove dangerous directives.",
            file=sys.stderr,
        )
        # Exit 2 = block in Kiro; also works as general "blocked" signal
        sys.exit(2)

    # Check against learned anti-patterns (warn, don't block)
    warnings = check_anti_patterns(content)
    if warnings:
        for w in warnings:
            print(f"[Nora] Warning: {w}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
