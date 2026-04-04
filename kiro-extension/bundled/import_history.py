#!/usr/bin/env python3
import json
import socket
import sys
from pathlib import Path

# Kernora Historical Session Importer
HOME = Path.home()
CLAUDE_PROJ = HOME / ".claude" / "projects"
DAEMON_SOCK = HOME / ".kernora" / "daemon.sock"

def push_to_daemon(payload: dict):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(str(DAEMON_SOCK))
            s.sendall(json.dumps(payload).encode() + b"\n")
            return True
    except FileNotFoundError:
        print("[error] Kernora daemon socket not found. Is it running?")
        return False
    except Exception as e:
        print(f"[error] Failed to send: {e}")
        return False

def main():
    if not CLAUDE_PROJ.exists():
        print(f"No Claude sessions found at {CLAUDE_PROJ}")
        return

    # Gather all transcripts and sort by modified time (newest first)
    all_transcripts = []
    for proj_dir in CLAUDE_PROJ.iterdir():
        if proj_dir.is_dir():
            all_transcripts.extend(list(proj_dir.glob("*.jsonl")))
    
    all_transcripts.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    limit = -1 if "--all" in sys.argv else 5
    count = 0

    print(f"Found {len(all_transcripts)} historical Claude Code transcripts.")

    for transcript in all_transcripts:
        session_id = transcript.stem
        # Estimate tokens roughly as 1 token per 4 chars of json string
        raw_text = transcript.read_text(errors='ignore')
        estimated_tokens = len(raw_text) // 4
        
        # We don't have the exact hook payload Claude uses, so we build a synthetic one.
        # The daemon will store it, and analyzer.py will read the transcript_path directly.
        payload = {
            "session_id": session_id,
            "transcript_path": str(transcript),
            "cwd": "historical-import",
            "usage": {"input_tokens": estimated_tokens, "output_tokens": 0},
            "model": "unknown"
        }

        if push_to_daemon(payload):
            print(f"[import] Queued {session_id[:8]} ({transcript.parent.name})")
            count += 1
        
        if limit > 0 and count >= limit:
            print(f"\n[info] Stopped after {limit} sessions.")
            print("To import all, run: python3 import_history.py --all")
            break
            
    if limit == -1:
        print(f"\n[success] Imported all {count} sessions!")
        
    print("\nThey are now queued in Kernora. To analyze them immediately, run:")
    print('python3 -c "from daemon import run_analysis_now; run_analysis_now()"')

if __name__ == "__main__":
    main()
