#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""
Post-session hook for Claude Code / Kiro / Cursor.
Installed at: ~/.claude/hooks/kernora_hook.py
Triggered by: Claude Code Stop event (async=true)

Delivery priority:
  1. HTTP POST to dashboard (localhost:2742) — works for all IDEs
  2. Unix socket to daemon.sock — legacy fallback
  3. Spool to disk — offline fallback (replayed on next dashboard start)

SECURITY: This file uses stdlib only. No external deps.
No outbound network calls. No API keys. Local delivery only.
"""
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

DASHBOARD_URL = "http://127.0.0.1:2742/api/session/end"
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


def send_via_http(payload: dict, retries: int = 1) -> bool:
    """Try HTTP POST to the dashboard. Fail fast and spool — don't delay session teardown."""
    import time as _time
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(retries):
        try:
            req = Request(
                DASHBOARD_URL,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urlopen(req, timeout=5)
            body = json.loads(resp.read().decode())
            return body.get("ok", False)
        except (URLError, OSError, json.JSONDecodeError, Exception):
            if attempt < retries - 1:
                _time.sleep(1)  # Wait for dashboard to finish restarting
    return False


def send_via_socket(payload: dict) -> bool:
    """Fallback: send via Unix socket to merged daemon thread."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(str(SOCK))
            s.sendall((json.dumps(payload) + "\n").encode())
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False


def spool(payload: dict):
    """Last resort: write to disk. Dashboard replays on next start."""
    SPOOL.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    sid = payload.get("session_id", "unknown")[:8]
    path = SPOOL / f"{ts}_{sid}.json"
    path.write_text(json.dumps(payload))
    print(f"[nora] dashboard offline — spooled {path.name}", file=sys.stderr)


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

    # Try delivery in priority order: HTTP → socket → spool
    if send_via_http(payload):
        print(f"[nora] sent session {session_id[:8]} via HTTP", file=sys.stderr)
    elif send_via_socket(payload):
        print(f"[nora] sent session {session_id[:8]} via socket", file=sys.stderr)
    else:
        spool(payload)

    # Log stop event to hook_events
    try:
        req = Request(
            "http://127.0.0.1:2742/api/hook/event",
            data=json.dumps({
                "event_type": "session_end",
                "session_id": session_id,
                "file_path": "hook.py",
                "detail": "Session delivered"
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urlopen(req, timeout=1)
    except Exception:
        pass


if __name__ == "__main__":
    main()
