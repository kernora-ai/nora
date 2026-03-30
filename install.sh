#!/bin/bash
# Nora — AI Session Intelligence Engine
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora
set -e

KERNORA_DIR="$HOME/.kernora"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo ""
echo "◎  Nora — your AI sessions, remembered"
echo "   Mode: BYOK — zero bytes leave your device."
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
mkdir -p "$KERNORA_DIR/logs" "$KERNORA_DIR/spool" "$KERNORA_DIR/app"
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

# ── 5. Copy engine files to ~/.kernora/app/ ──────────────────────────────────
for f in daemon.py analyzer.py db.py dashboard.py notifier.py nora_mcp.py cli_shield.py; do
    [ -f "$REPO_DIR/$f" ] && cp "$REPO_DIR/$f" "$KERNORA_DIR/app/$f"
done
echo "✓ Engine files installed at ~/.kernora/app/"

# ── 6. Register Nora MCP server ─────────────────────────────────────────────
# MCP server works with Claude Code, Claude Desktop, and any MCP-compatible client.
MCP_CONFIG="$HOME/.claude/.mcp.json"
NORA_MCP="{\"command\":\"$PYTHON\",\"args\":[\"$KERNORA_DIR/app/nora_mcp.py\"]}"
if command -v jq &>/dev/null; then
    if [ -f "$MCP_CONFIG" ]; then
        tmp=$(mktemp)
        jq ".mcpServers.nora = $NORA_MCP" "$MCP_CONFIG" > "$tmp" && mv "$tmp" "$MCP_CONFIG"
    else
        mkdir -p "$(dirname "$MCP_CONFIG")"
        echo "{\"mcpServers\":{\"nora\":$NORA_MCP}}" | jq . > "$MCP_CONFIG"
    fi
    echo "✓ Nora MCP server registered in ~/.claude/.mcp.json"
else
    echo "⚠  jq not found. Add Nora MCP to ~/.claude/.mcp.json manually:"
    echo "   {\"mcpServers\":{\"nora\":$NORA_MCP}}"
fi

# ── 7. Initialize database ──────────────────────────────────────────────────
"$PYTHON" "$KERNORA_DIR/app/db.py"

# ── 8. Stop any existing Nora processes ─────────────────────────────────────
[ -f "$KERNORA_DIR/daemon.pid" ] && kill "$(cat "$KERNORA_DIR/daemon.pid")" 2>/dev/null && rm "$KERNORA_DIR/daemon.pid" || true
pkill -f "nora.*dashboard.py" 2>/dev/null || true

# ── 9. Auto-start on login ──────────────────────────────────────────────────
if [ "$(uname)" = "Darwin" ]; then
    mkdir -p "$LAUNCH_AGENTS"
    WHOAMI=$(whoami)

    DETECTED_KEY="${ANTHROPIC_API_KEY:-}"
    if [ -z "$DETECTED_KEY" ]; then
        echo ""
        echo "→ No ANTHROPIC_API_KEY found in current shell."
        echo "  Enter your Anthropic API key for the background daemon,"
        echo "  or press Enter to skip (use Bedrock/Ollama instead):"
        read -r -s DETECTED_KEY
        echo ""
    fi

    ENV_BLOCK=""
    if [ -n "$DETECTED_KEY" ]; then
        ENV_BLOCK="  <key>EnvironmentVariables</key>
  <dict>
    <key>ANTHROPIC_API_KEY</key>
    <string>${DETECTED_KEY}</string>
  </dict>"
        echo "✓ API key injected into daemon LaunchAgent"
    fi

    cat > "$LAUNCH_AGENTS/ai.kernora.daemon.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.kernora.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${KERNORA_DIR}/app/daemon.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/${WHOAMI}/.kernora/logs/daemon.log</string>
  <key>StandardErrorPath</key><string>/Users/${WHOAMI}/.kernora/logs/daemon.err</string>
${ENV_BLOCK}
</dict>
</plist>
PLIST

    cat > "$LAUNCH_AGENTS/ai.kernora.dashboard.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.kernora.dashboard</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${KERNORA_DIR}/app/dashboard.py</string>
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
    echo "✓ Auto-start configured (LaunchAgents)"

else
    nohup "$PYTHON" "$KERNORA_DIR/app/daemon.py" > "$KERNORA_DIR/logs/daemon.log" 2>&1 &
    echo $! > "$KERNORA_DIR/daemon.pid"
    nohup "$PYTHON" "$KERNORA_DIR/app/dashboard.py" > "$KERNORA_DIR/logs/dashboard.log" 2>&1 &
    echo "✓ Daemon + dashboard started (Linux)"
fi

sleep 2

# ── 10. Smoke test ──────────────────────────────────────────────────────────
echo ""
if curl -sf http://localhost:2742 > /dev/null 2>&1; then
    echo "✓ Dashboard is live at http://localhost:2742"
else
    echo "→ Dashboard starting up — open http://localhost:2742 in a moment"
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo "  ┌─ Nora engine is running ─────────────────────────────────────────┐"
echo "  │                                                                   │"
echo "  │  Dashboard  →  http://localhost:2742                             │"
echo "  │  MCP server →  registered in ~/.claude/.mcp.json                 │"
echo "  │  Config     →  ~/.kernora/config.toml                            │"
echo "  │                                                                   │"
echo "  │  Next: install a claw to connect your AI coding agent:           │"
echo "  │                                                                   │"
echo "  │    Claude Code:  claude plugin add kernora-ai/claude-claw        │"
echo "  │    Kiro:         ext install kernora-ai.kiro-claw                │"
echo "  │                                                                   │"
echo "  └──────────────────────────────────────────────────────────────────┘"
echo ""
