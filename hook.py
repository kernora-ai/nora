#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
"""
Post-session hook for Claude Code.
Installed at: ~/.claude/hooks/kernora_hook.py
Triggered by: Claude Code Stop event (async=true)

SECURITY: This file uses stdlib only. No external deps.
No network calls. No API keys. Sends to local daemon socket only.
"""
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

SOCK  = Path.home() / ".kernora" / "daemon.sock"
SPOOL = Path.home() / ".kernora" / "spool"


def read_transcript(path: str) -> list:
    turns = []
    if not path:
        return turns
    p = Path(path)
    if not p.exists() or not p.is_file():
        return turns
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return turns


def send_to_daemon(payload: dict) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(str(SOCK))
            s.sendall((json.dumps(payload) + "\n").encode())
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False


def spool(payload: dict):
    SPOOL.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    sid = payload.get("session_id", "unknown")[:8]
    path = SPOOL / f"{ts}_{sid}.json"
    path.write_text(json.dumps(payload))
    print(f"[nora] daemon offline — spooled {path.name}", file=sys.stderr)


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[nora] hook: bad JSON: {e}", file=sys.stderr)
        return

    session_id      = data.get("session_id", "")
    transcript_path = data.get("transcript_path", "")
    cwd             = data.get("cwd", os.getcwd())

    turns = read_transcript(transcript_path)

    payload = {
        "session_id":  session_id,
        "project":     cwd,
        "started_at":  data.get("started_at", ""),
        "ended_at":    datetime.now(timezone.utc).isoformat(),
        "tokens_in":   data.get("usage", {}).get("input_tokens", 0),
        "tokens_out":  data.get("usage", {}).get("output_tokens", 0),
        "model":       data.get("model", ""),
        "turns":       turns,
    }

    if not send_to_daemon(payload):
        spool(payload)
    else:
        print(f"[nora] sent session {session_id[:8]}", file=sys.stderr)


if __name__ == "__main__":
    main()
