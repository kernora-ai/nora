#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
"""
Background daemon.
Run:        python daemon.py
Background: nohup python daemon.py > ~/.kernora/logs/daemon.log 2>&1 &
LaunchAgent installs this automatically on macOS.
"""
import json
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

from db import init_db, store_session, get_unanalyzed, mark_analyzed

HOME  = Path.home() / ".kernora"
SOCK  = HOME / "daemon.sock"
SPOOL = HOME / "spool"


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def replay_spool():
    if not SPOOL.exists():
        return
    for f in sorted(SPOOL.glob("*.json")):
        try:
            payload = json.loads(f.read_text())
            store_session(payload)
            f.unlink()
            log(f"replayed: {f.name}")
        except Exception as e:
            log(f"spool error {f.name}: {e}")


def handle_connection(data: bytes):
    try:
        payload = json.loads(data.decode().strip())
        store_session(payload)
        sid = payload.get("session_id", "?")[:8]
        tok = payload.get("tokens_in", 0) + payload.get("tokens_out", 0)
        log(f"stored session {sid} ({tok} tokens)")
    except Exception as e:
        log(f"session parse error: {e}")


def socket_server():
    SOCK.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
        srv.bind(str(SOCK))
        SOCK.chmod(0o600)
        srv.listen(5)
        log(f"socket listening at {SOCK}")
        while True:
            conn, _ = srv.accept()
            with conn:
                data = b""
                while chunk := conn.recv(4096):
                    data += chunk
                if data:
                    handle_connection(data)


def analysis_loop():
    """Hourly: analyze unanalyzed sessions using user's own LiteLLM credentials."""
    from analyzer import analyze
    from notifier import notify

    log("analysis loop started (LiteLLM BYOK mode)")

    while True:
        time.sleep(3600)

        try:
            sessions = get_unanalyzed(limit=20)
            if not sessions:
                continue

            log(f"analyzing {len(sessions)} session(s)...")

            for session in sessions:
                try:
                    result = analyze(session)
                    mark_analyzed(session["id"], result)
                    model = result.get("model_used", "?")
                    cost  = result.get("token_cost", 0)
                    bugs  = len(result.get("bugs", []))
                    log(f"analyzed {session['id'][:8]}: {bugs} bugs, "
                        f"{cost} tokens [{model}]")
                    notify(
                        "Nora",
                        result.get("summary") or "Session analyzed. Dashboard updated."
                    )
                except Exception as e:
                    log(f"analysis failed for {session['id'][:8]}: {e}")

            # Regenerate Kiro steering files after analysis batch
            try:
                from steering_writer import generate_all
                generated = generate_all()
                if generated:
                    log(f"steering files updated: {len(generated)} files")
            except ImportError:
                pass  # steering_writer not available — OK
            except Exception as e:
                log(f"steering generation failed: {e}")

        except Exception as e:
            log(f"analysis loop error: {e}")


def run_analysis_now():
    """Force immediate analysis — for testing. Call from CLI."""
    from analyzer import analyze
    from notifier import notify

    sessions = get_unanalyzed(limit=5)
    print(f"[nora] found {len(sessions)} unanalyzed sessions")

    for session in sessions:
        print(f"[nora] analyzing {session['id'][:8]}...")
        try:
            result = analyze(session)
            mark_analyzed(session["id"], result)
            print(f"[nora] model used:  {result.get('model_used')}")
            print(f"[nora] token cost:  {result.get('token_cost')}")
            print(f"[nora] bugs found:  {len(result.get('bugs', []))}")
            print(f"[nora] summary:     {result.get('summary')}")
            notify("Nora", result.get("summary", ""))
        except Exception as e:
            print(f"[nora] error: {e}")


def main():
    HOME.mkdir(parents=True, exist_ok=True)

    log("Nora daemon starting (BYOK mode)")
    log("Zero bytes will leave this machine.")
    init_db()
    replay_spool()

    t_socket   = threading.Thread(target=socket_server, daemon=True)
    t_analysis = threading.Thread(target=analysis_loop, daemon=True)
    t_socket.start()
    t_analysis.start()

    log("daemon ready.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log("daemon stopped.")


if __name__ == "__main__":
    main()
