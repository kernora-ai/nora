#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
"""
Kiro agentSpawn hook — initializes Nora context when an agent starts.

Installed at: ~/.kiro/hooks/nora_spawn.py
Triggered by: Kiro agentSpawn

What it does:
  1. Checks if Nora daemon is running, starts it if not
  2. Ensures steering files are up-to-date
  3. Reports session count and last analysis time
  4. Primes the context cache for faster userPromptSubmit responses

CONTRACT:
  - Reads JSON from stdin: {"hook": "agentSpawn", "session_id": "...", ...}
  - Exit 0 always (agentSpawn is initialization, never blocks)
  - stdout = status message (captured by Kiro, not shown to user)

SECURITY: stdlib only, no network calls, no API keys.
"""
import db
import json
import os
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

DB_PATH = Path.home() / ".kernora" / "echo.db"
SOCK_PATH = Path.home() / ".kernora" / "daemon.sock"
DASHBOARD_HEALTH_URL = "http://127.0.0.1:2742/health"
STEERING_DIR_GLOBAL = Path.home() / ".kiro" / "steering"


def ensure_daemon_running():
    """Check if dashboard (with merged daemon) is alive. Try HTTP first, then socket."""
    # Preferred: check dashboard HTTP health endpoint
    try:
        req = Request(DASHBOARD_HEALTH_URL, method="GET")
        resp = urlopen(req, timeout=3)
        if resp.status == 200:
            return True
    except (URLError, OSError):
        pass

    # Fallback: check Unix socket (legacy daemon or merged socket listener)
    if SOCK_PATH.exists():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(str(SOCK_PATH))
                return True
        except (ConnectionRefusedError, OSError):
            SOCK_PATH.unlink(missing_ok=True)

    # Try to start dashboard (which now includes daemon threads)
    venv_python = Path.home() / ".kernora" / "venv" / "bin" / "python3"
    dashboard_path = Path.home() / ".kernora" / "app" / "dashboard.py"
    if venv_python.exists() and dashboard_path.exists():
        try:
            # FIX #7: start_new_session=True so dashboard outlives the hook process
            subprocess.Popen(
                [str(venv_python), str(dashboard_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception:
            pass
    return False


def get_session_stats() -> dict:
    """Get quick stats for agent initialization context."""
    if not DB_PATH.exists():
        return {"sessions": 0, "insights": 0, "last_analysis": "never"}
    try:
        conn = db.get_conn()
        sessions = conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
        insights = conn.execute("SELECT count(*) FROM insights").fetchone()[0]
        last = conn.execute(
            "SELECT analyzed_at FROM insights ORDER BY analyzed_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return {
            "sessions": sessions,
            "insights": insights,
            "last_analysis": last[0] if last else "never",
        }
    except Exception:
        return {"sessions": 0, "insights": 0, "last_analysis": "error"}


def check_steering_freshness() -> bool:
    """Check if steering files exist and are reasonably fresh."""
    patterns_file = STEERING_DIR_GLOBAL / "kernora-patterns.md"
    if not patterns_file.exists():
        return False
    # Check if older than 24 hours
    import time
    age_hours = (time.time() - patterns_file.stat().st_mtime) / 3600
    return age_hours < 24


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # Ensure daemon is running
    daemon_ok = ensure_daemon_running()

    # Get stats
    stats = get_session_stats()
    steering_ok = check_steering_freshness()

    # Report status (stdout captured by Kiro, not shown)
    status = {
        "nora": "ready" if daemon_ok else "starting",
        "sessions_analyzed": stats["insights"],
        "total_sessions": stats["sessions"],
        "last_analysis": stats["last_analysis"],
        "steering_current": steering_ok,
    }

    # If steering is stale, trigger regeneration
    if not steering_ok and stats["insights"] > 0:
        try:
            venv_python = Path.home() / ".kernora" / "venv" / "bin" / "python3"
            writer_path = Path.home() / ".kernora" / "app" / "steering_writer.py"
            if venv_python.exists() and writer_path.exists():
                subprocess.Popen(
                    [str(venv_python), str(writer_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                status["steering_regenerating"] = True
        except Exception:
            pass

    # Notify dashboard that a session has started (for live tracking)
    try:
        session_id = data.get("session_id", "")
        project = data.get("project", "") or data.get("cwd", "") or os.getcwd()
        req = Request(
            "http://127.0.0.1:2742/api/session/start",
            data=json.dumps({"session_id": session_id, "project": project}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urlopen(req, timeout=2)
    except (URLError, OSError):
        pass  # dashboard might not be running yet

    try:
        req = Request(
            "http://127.0.0.1:2742/api/hook/event",
            data=json.dumps({
                "event_type": "agent_spawn",
                "session_id": session_id,
                "file_path": "kiro_agent_spawn.py",
                "detail": "Agent spawned"
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urlopen(req, timeout=1)
    except (URLError, OSError):
        pass

    print(json.dumps(status))
    sys.exit(0)


if __name__ == "__main__":
    main()
