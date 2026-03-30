#!/bin/bash
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
set -e

KERNORA_DIR="$HOME/.kernora"
HOOK_DIR="$HOME/.claude/hooks"
SETTINGS="$HOME/.claude/settings.json"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo ""
echo "◎  Kernora — installing your silent coding partner"
echo "   Mode: BYOK — zero bytes will leave this machine."
echo ""

# ── 1. Python check ──────────────────────────────────────────────────────────
python3 -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null || {
    echo "✗ Python 3.9+ required. Install from https://python.org"
    exit 1
}
echo "✓ Python $(python3 --version | cut -d' ' -f2)"

# ── 2. Virtual environment + dependencies ────────────────────────────────────
VENV_DIR="$KERNORA_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi
PYTHON="$VENV_DIR/bin/python3"
PIP="$VENV_DIR/bin/pip"
echo "→ Installing dependencies..."
"$PIP" install -r "$REPO_DIR/requirements.txt" --quiet
echo "✓ Dependencies installed"

# ── 3. Directories ────────────────────────────────────────────────────────────
mkdir -p "$KERNORA_DIR/logs" "$KERNORA_DIR/spool"
echo "✓ Created ~/.kernora/"

# ── 4. Config (skip if already exists) ───────────────────────────────────────
if [ ! -f "$KERNORA_DIR/config.toml" ]; then
    cp "$REPO_DIR/config.toml.example" "$KERNORA_DIR/config.toml" 2>/dev/null || cat > "$KERNORA_DIR/config.toml" << 'TOML'
[mode]
type = "byok"

[model]
provider = "anthropic"

[bedrock]
region = "us-east-1"
model  = "amazon.nova-lite-v1:0"

[analysis]
run_every_minutes = 60

[dashboard]
port = 2742
auto_open = true

[privacy]
verified = true
TOML
    echo "✓ Config created at ~/.kernora/config.toml"
    echo ""
    echo "  ┌─ Set your API credentials (choose one) ──────────────────────┐"
    echo "  │  Anthropic:  export ANTHROPIC_API_KEY=sk-ant-...             │"
    echo "  │  Bedrock:    aws configure --profile kernora                  │"
    echo "  │              then in config.toml: provider = \"bedrock\"       │"
    echo "  │  Ollama:     ollama pull llama3.2:3b                         │"
    echo "  │              then in config.toml: provider = \"ollama\"        │"
    echo "  └───────────────────────────────────────────────────────────────┘"
    echo ""
else
    echo "✓ Config already exists — keeping ~/.kernora/config.toml"
fi

# ── 5. Claude Code hooks ─────────────────────────────────────────────────────
mkdir -p "$HOOK_DIR"
cp "$REPO_DIR/hook.py" "$HOOK_DIR/kernora_hook.py"
cp "$REPO_DIR/nora_context.py" "$HOOK_DIR/nora_context.py"
chmod +x "$HOOK_DIR/kernora_hook.py" "$HOOK_DIR/nora_context.py"
echo "✓ Hooks installed at ~/.claude/hooks/"
echo "  → kernora_hook.py (session capture on Stop)"
echo "  → nora_context.py (context injection on UserPromptSubmit)"

# ── 6. Register hooks in Claude Code settings ────────────────────────────────
STOP_HOOK="{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/kernora_hook.py\",\"async\":true}]}"
CONTEXT_HOOK="{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_context.py\",\"timeout\":3}]}"
if [ -f "$SETTINGS" ] && command -v jq &>/dev/null; then
    # Append to existing settings cleanly
    tmp=$(mktemp)
    jq ".hooks.Stop += [$STOP_HOOK] | .hooks.UserPromptSubmit += [$CONTEXT_HOOK]" "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
    echo "✓ Hooks registered in ~/.claude/settings.json"
elif [ ! -f "$SETTINGS" ]; then
    mkdir -p "$(dirname "$SETTINGS")"
    cat > "$SETTINGS" << SETTINGS_EOF
{
  "hooks": {
    "UserPromptSubmit": [$CONTEXT_HOOK],
    "Stop": [$STOP_HOOK]
  }
}
SETTINGS_EOF
    echo "✓ Created ~/.claude/settings.json with Kernora hooks"
else
    echo "⚠  jq not found. Add these hooks to ~/.claude/settings.json manually:"
    echo "   Stop: $STOP_HOOK"
    echo "   UserPromptSubmit: $CONTEXT_HOOK"
fi

# ── 7. Initialize database ────────────────────────────────────────────────────
"$PYTHON" "$REPO_DIR/db.py"

# ── 8. Stop any existing Kernora processes ────────────────────────────────────
[ -f "$KERNORA_DIR/daemon.pid" ] && kill "$(cat "$KERNORA_DIR/daemon.pid")" 2>/dev/null && rm "$KERNORA_DIR/daemon.pid" || true
pkill -f "kernora/dashboard.py" 2>/dev/null || true

# ── 9. Auto-start on login ────────────────────────────────────────────────────
if [ "$(uname)" = "Darwin" ]; then
    mkdir -p "$LAUNCH_AGENTS"
    WHOAMI=$(whoami)

    # Collect API key for plist injection
    # LaunchAgents don't inherit shell env — we must bake the key into the plist
    DETECTED_KEY="${ANTHROPIC_API_KEY:-}"
    if [ -z "$DETECTED_KEY" ]; then
        echo ""
        echo "→ No ANTHROPIC_API_KEY found in current shell."
        echo "  Enter your Anthropic API key to inject into the background daemon,"
        echo "  or press Enter to skip (use Bedrock/Ollama, or run kernora-fix.sh later):"
        read -r -s DETECTED_KEY
        echo ""
    fi

    # Build EnvironmentVariables block only if we have a key
    ENV_BLOCK=""
    if [ -n "$DETECTED_KEY" ]; then
        ENV_BLOCK="  <key>EnvironmentVariables</key>
  <dict>
    <key>ANTHROPIC_API_KEY</key>
    <string>${DETECTED_KEY}</string>
  </dict>"
        echo "✓ API key will be injected into daemon LaunchAgent"
    fi

    # Daemon plist
    cat > "$LAUNCH_AGENTS/ai.kernora.daemon.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.kernora.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${REPO_DIR}/daemon.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/${WHOAMI}/.kernora/logs/daemon.log</string>
  <key>StandardErrorPath</key><string>/Users/${WHOAMI}/.kernora/logs/daemon.err</string>
${ENV_BLOCK}
</dict>
</plist>
PLIST

    # Dashboard plist
    cat > "$LAUNCH_AGENTS/ai.kernora.dashboard.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.kernora.dashboard</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${REPO_DIR}/dashboard.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/${WHOAMI}/.kernora/logs/dashboard.log</string>
  <key>StandardErrorPath</key><string>/Users/${WHOAMI}/.kernora/logs/dashboard.err</string>
</dict>
</plist>
PLIST

    launchctl load "$LAUNCH_AGENTS/ai.kernora.daemon.plist" 2>/dev/null || true
    launchctl load "$LAUNCH_AGENTS/ai.kernora.dashboard.plist" 2>/dev/null || true
    echo "✓ Auto-start configured (LaunchAgents) — starts on every login"

else
    # Linux: start in background now
    nohup "$PYTHON" "$REPO_DIR/daemon.py" > "$KERNORA_DIR/logs/daemon.log" 2>&1 &
    echo $! > "$KERNORA_DIR/daemon.pid"
    nohup "$PYTHON" "$REPO_DIR/dashboard.py" > "$KERNORA_DIR/logs/dashboard.log" 2>&1 &
    echo "✓ Daemon + dashboard started (Linux)"
fi

sleep 2

# ── 10. Smoke test ────────────────────────────────────────────────────────────
echo ""
if curl -sf http://localhost:2742 > /dev/null 2>&1; then
    echo "✓ Dashboard is live at http://localhost:2742"
else
    echo "→ Dashboard starting up — open http://localhost:2742 in a moment"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ┌─ Kernora is installed ────────────────────────────────────────────┐"
echo "  │                                                                   │"
echo "  │  Dashboard  →  http://localhost:2742                             │"
echo "  │  Config     →  ~/.kernora/config.toml                           │"
echo "  │  Logs       →  ~/.kernora/logs/                                  │"
echo "  │                                                                   │"
echo "  │  End a Claude Code session. Nora will notify you within 60s.    │"
echo "  │                                                                   │"
echo "  └───────────────────────────────────────────────────────────────────┘"
echo ""
