#!/usr/bin/env bash
# Kernora — Fix: inject API key into LaunchAgent + reset stuck sessions
# Run once from your kernora repo directory: bash kernora-fix.sh

set -e

KERNORA_DIR="$HOME/.kernora"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
DAEMON_PLIST="$LAUNCH_AGENTS/ai.kernora.daemon.plist"
DB="$KERNORA_DIR/echo.db"

echo ""
echo "◎  Kernora Fix — API Key + Session Reset"
echo "─────────────────────────────────────────"
echo ""

# ── 1. Get API key ────────────────────────────────────────────────────────────
if [ -n "$ANTHROPIC_API_KEY" ]; then
    KEY="$ANTHROPIC_API_KEY"
    echo "✓ Found ANTHROPIC_API_KEY in environment"
else
    echo "Enter your Anthropic API key (sk-ant-...):"
    echo "(Get it from https://console.anthropic.com/settings/keys)"
    read -r -s KEY
    echo ""
    if [ -z "$KEY" ]; then
        echo ""
        echo "No key entered. Switching config to 'auto' mode (will use Ollama if running)."
        echo "To use Anthropic later, run: export ANTHROPIC_API_KEY=sk-ant-... then re-run this script."
        # Switch config to auto
        sed -i.bak 's/provider = "anthropic"/provider = "auto"/' "$KERNORA_DIR/config.toml"
        echo "✓ Config switched to provider = \"auto\""
        KEY=""
    fi
fi

# ── 2. Patch the daemon plist to include EnvironmentVariables ────────────────
if [ -f "$DAEMON_PLIST" ] && [ -n "$KEY" ]; then
    echo "→ Patching LaunchAgent plist with API key..."

    # Unload first
    launchctl unload "$DAEMON_PLIST" 2>/dev/null || true

    # Inject EnvironmentVariables block before closing </dict>
    # Use python for reliable XML editing
    python3 - "$DAEMON_PLIST" "$KEY" << 'PYEOF'
import sys
from pathlib import Path

plist_path = Path(sys.argv[1])
api_key = sys.argv[2]
content = plist_path.read_text()

env_block = f"""  <key>EnvironmentVariables</key>
  <dict>
    <key>ANTHROPIC_API_KEY</key>
    <string>{api_key}</string>
  </dict>
"""

# Only inject if not already present
if "EnvironmentVariables" not in content:
    content = content.replace("</dict>\n</plist>", env_block + "</dict>\n</plist>")
    plist_path.write_text(content)
    print(f"✓ Injected ANTHROPIC_API_KEY into {plist_path}")
else:
    # Update existing key
    import re
    content = re.sub(
        r'(<key>ANTHROPIC_API_KEY</key>\s*<string>)[^<]*(</string>)',
        rf'\g<1>{api_key}\g<2>',
        content
    )
    plist_path.write_text(content)
    print(f"✓ Updated ANTHROPIC_API_KEY in {plist_path}")
PYEOF

    # Reload daemon
    launchctl load "$DAEMON_PLIST"
    echo "✓ Daemon reloaded with API key"

elif [ -f "$DAEMON_PLIST" ] && [ -z "$KEY" ]; then
    # Reload with auto mode (no key needed)
    launchctl unload "$DAEMON_PLIST" 2>/dev/null || true
    launchctl load "$DAEMON_PLIST"
    echo "✓ Daemon reloaded (auto mode)"

else
    echo "⚠  Daemon plist not found at $DAEMON_PLIST"
    echo "   Run install.sh first, then run this script."
    exit 1
fi

# ── 3. Reset stuck sessions (analyzed=1 but empty insights) ──────────────────
echo ""
echo "→ Resetting sessions with empty analysis for re-processing..."

python3 - "$DB" << 'PYEOF'
import sqlite3, sys
from pathlib import Path

db_path = Path(sys.argv[1])
if not db_path.exists():
    print(f"  No DB found at {db_path} — nothing to reset")
    sys.exit(0)

conn = sqlite3.connect(str(db_path))

# Find sessions that were "analyzed" but produced empty results
rows = conn.execute("""
    SELECT s.id, s.project
    FROM sessions s
    JOIN insights i ON i.session_id = s.id
    WHERE s.analyzed = 1
      AND (i.summary = '' OR i.summary = 'Empty session.' OR i.summary IS NULL)
      AND length(s.turns_json) > 10
""").fetchall()

if not rows:
    print("  No stuck sessions found — all good.")
else:
    for row in rows:
        conn.execute("UPDATE sessions SET analyzed = 0 WHERE id = ?", (row[0],))
        conn.execute("DELETE FROM insights WHERE session_id = ?", (row[0],))
        print(f"  ↺  Reset session: {row[1]} ({row[0]})")
    conn.commit()
    print(f"\n✓ {len(rows)} session(s) queued for re-analysis")

conn.close()
PYEOF

# ── 4. Trigger immediate analysis ─────────────────────────────────────────────
sleep 2
echo ""
echo "→ Triggering immediate analysis (normally runs hourly)..."

REPO_DIR="$(dirname "$(realpath "$0")")"
python3 - "$REPO_DIR" << 'PYEOF'
import sys, subprocess
from pathlib import Path

repo = Path(sys.argv[1])
daemon_py = repo / "daemon.py"

# Try to trigger via the run_now function if daemon is running
try:
    import socket, json
    sock_path = Path.home() / ".kernora" / "daemon.sock"
    if sock_path.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(str(sock_path))
            s.sendall(json.dumps({"type": "run_analysis_now"}).encode() + b"\n")
            print("✓ Sent run_analysis_now to daemon via socket")
    else:
        print("  Socket not ready yet — daemon is starting up")
        print("  Analysis will run automatically within 60 seconds")
except Exception as e:
    print(f"  Daemon starting up — analysis will run within 60 seconds ({e})")
PYEOF

echo ""
echo "─────────────────────────────────────────"
echo "✓  Fix complete. Open http://localhost:2742/sessions"
echo "   in ~60 seconds to see your analyzed session."
echo ""
