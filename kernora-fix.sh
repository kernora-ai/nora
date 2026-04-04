#!/usr/bin/env python3
"""
Kernora Fix — run this once to get your dashboard updating.
Usage: python3 kernora-fix.sh
"""
import subprocess, sqlite3, sys, re
from pathlib import Path

PLIST = Path.home() / "Library/LaunchAgents/ai.kernora.daemon.plist"
DB    = Path.home() / ".kernora/echo.db"

print("\n◎  Kernora Fix\n──────────────────────────────")

# ── 1. Check plist exists ─────────────────────────────────────────────────────
if not PLIST.exists():
    print(f"✗  Plist not found at {PLIST}")
    print("   Run install.sh from your kernora repo first.")
    sys.exit(1)

# ── 2. Get API key ────────────────────────────────────────────────────────────
import os
key = os.environ.get("ANTHROPIC_API_KEY", "")

if not key:
    print("\nPaste your Anthropic API key (from console.anthropic.com/settings/keys)")
    print("It starts with sk-ant-  — input is hidden:")
    import getpass
    key = getpass.getpass("API key: ").strip()

if not key:
    print("✗  No key provided. Exiting.")
    sys.exit(1)

print(f"✓  Key received ({key[:12]}...)")

# ── 3. Patch plist ────────────────────────────────────────────────────────────
txt = PLIST.read_text()

env_block = f"""  <key>EnvironmentVariables</key>
  <dict>
    <key>ANTHROPIC_API_KEY</key>
    <string>{key}</string>
  </dict>
"""

if "EnvironmentVariables" not in txt:
    txt = txt.replace("</dict>\n</plist>", env_block + "</dict>\n</plist>")
    PLIST.write_text(txt)
    print("✓  API key injected into LaunchAgent plist")
else:
    # Update existing key value
    txt = re.sub(
        r'(<key>ANTHROPIC_API_KEY</key>\s*<string>)[^<]*(</string>)',
        rf'\g<1>{key}\g<2>',
        txt
    )
    PLIST.write_text(txt)
    print("✓  API key updated in LaunchAgent plist")

# ── 4. Reload daemon ──────────────────────────────────────────────────────────
subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
result = subprocess.run(["launchctl", "load", str(PLIST)], capture_output=True)
if result.returncode == 0:
    print("✓  Daemon reloaded with API key")
else:
    print(f"⚠  Daemon reload issue: {result.stderr.decode()}")

# ── 5. Reset stuck sessions ───────────────────────────────────────────────────
if not DB.exists():
    print("⚠  No database found — no sessions to reset")
else:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute("""
        SELECT s.id, s.project
        FROM sessions s
        JOIN insights i ON i.session_id = s.id
        WHERE s.analyzed = 1
          AND (i.summary = '' OR i.summary = 'Empty session.' OR i.summary IS NULL)
          AND length(s.turns_json) > 10
    """).fetchall()

    if rows:
        for sid, proj in rows:
            conn.execute("UPDATE sessions SET analyzed = 0 WHERE id = ?", (sid,))
            conn.execute("DELETE FROM insights WHERE session_id = ?", (sid,))
            print(f"   ↺  Queued for re-analysis: {proj}")
        conn.commit()
        print(f"✓  {len(rows)} session(s) reset")
    else:
        print("✓  No stuck sessions found")
    conn.close()

# ── Done ──────────────────────────────────────────────────────────────────────
print("""
──────────────────────────────
Done. Nora will analyze your session within 60 seconds.

→ Reload http://localhost:2742/sessions to see results.
""")
