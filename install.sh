#!/bin/bash
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora
set -e

KERNORA_DIR="$HOME/.kernora"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo ""
echo "◎  Kernora — AI Work Intelligence"
echo "   Your coding sessions, remembered. Zero bytes leave your device."
echo ""

# ── 0. Detect IDEs ──────────────────────────────────────────────────────────
KIRO_DETECTED=false
CLAUDE_DETECTED=false
CURSOR_DETECTED=false

[ -d "$HOME/.kiro" ] && KIRO_DETECTED=true
[ -d "$HOME/.claude" ] && CLAUDE_DETECTED=true
[ -d "$HOME/.cursor" ] && CURSOR_DETECTED=true

if [ "$KIRO_DETECTED" = false ] && [ "$CLAUDE_DETECTED" = false ] && [ "$CURSOR_DETECTED" = false ]; then
    echo "⚠  No supported IDE detected (~/.kiro, ~/.claude, or ~/.cursor)"
    echo "   Install Kiro, VS Code + Claude Code, or Cursor first."
    echo "   Continuing anyway — you can re-run install.sh after IDE setup."
    echo ""
fi

# ── 1. Python check ─────────────────────────────────────────────────────────
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

# ── 3. Directories + app files ───────────────────────────────────────────────
mkdir -p "$KERNORA_DIR/logs" "$KERNORA_DIR/spool" "$KERNORA_DIR/app"

# Copy ALL Python files that the extension bundles — keeps install.sh and
# extension's syncBundledFiles() in perfect sync.
APP_FILES=(
    dashboard.py db.py analyzer.py daemon.py nora_mcp.py
    nora_context.py hook.py kernora_cli.py
    kiro_agent_spawn.py kiro_post_tool.py kiro_spec_shield.py
    steering_writer.py telemetry.py
    nora_precompact.py nora_session_start.py
)
COPIED=0
for f in "${APP_FILES[@]}"; do
    if [ -f "$REPO_DIR/$f" ]; then
        cp "$REPO_DIR/$f" "$KERNORA_DIR/app/$f"
        COPIED=$((COPIED + 1))
    fi
done

# Write version file (matches extension's syncBundledFiles behavior)
VERSION=$("$PYTHON" -c "import json; print(json.load(open('$REPO_DIR/kiro-extension/package.json'))['version'])" 2>/dev/null || echo "unknown")
echo "$VERSION" > "$KERNORA_DIR/app/.version"

echo "✓ App files installed to ~/.kernora/app/ ($COPIED files, v$VERSION)"

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
else
    echo "✓ Config already exists — keeping ~/.kernora/config.toml"
fi

# ── 5. Initialize database ──────────────────────────────────────────────────
"$PYTHON" "$REPO_DIR/db.py"
echo "✓ Database ready"

# ── 6. Stop any existing Kernora processes ──────────────────────────────────
[ -f "$KERNORA_DIR/daemon.pid" ] && kill "$(cat "$KERNORA_DIR/daemon.pid")" 2>/dev/null && rm "$KERNORA_DIR/daemon.pid" || true
pkill -f "kernora.*dashboard.py" 2>/dev/null || true
pkill -f "kernora.*daemon.py" 2>/dev/null || true

# ── 7. Kiro setup ───────────────────────────────────────────────────────────
if [ "$KIRO_DETECTED" = true ]; then
    echo ""
    echo "── Kiro detected ────────────────────────────────────────────────"

    # 7a. Install hooks
    KIRO_HOOK_DIR="$HOME/.kiro/hooks"
    KIRO_STEERING_DIR="$HOME/.kiro/steering"
    mkdir -p "$KIRO_HOOK_DIR" "$KIRO_STEERING_DIR"
    cp "$REPO_DIR/kiro_agent_spawn.py" "$KIRO_HOOK_DIR/nora_spawn.py"
    cp "$REPO_DIR/nora_context.py" "$KIRO_HOOK_DIR/nora_context.py"
    cp "$REPO_DIR/kiro_spec_shield.py" "$KIRO_HOOK_DIR/nora_pretool.py"
    cp "$REPO_DIR/kiro_post_tool.py" "$KIRO_HOOK_DIR/nora_posttool.py"
    cp "$REPO_DIR/hook.py" "$KIRO_HOOK_DIR/nora_stop.py"
    chmod +x "$KIRO_HOOK_DIR"/*.py
    echo "  ✓ Hooks installed (5 hooks)"

    # 7b. Register hooks in Kiro settings.json
    KIRO_SETTINGS="$HOME/.kiro/settings.json"
    KIRO_SPAWN="{\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.kiro/hooks/nora_spawn.py\"}]}"
    KIRO_PROMPT="{\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.kiro/hooks/nora_context.py\",\"timeout\":3}]}"
    KIRO_PRETOOL="{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.kiro/hooks/nora_pretool.py\",\"timeout\":5}]}"
    KIRO_POSTTOOL="{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.kiro/hooks/nora_posttool.py\",\"async\":true}]}"
    KIRO_STOP="{\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.kiro/hooks/nora_stop.py\",\"async\":true}]}"

    if [ -f "$KIRO_SETTINGS" ] && command -v jq &>/dev/null; then
        tmp=$(mktemp)
        jq ".hooks.agentSpawn += [$KIRO_SPAWN] | .hooks.userPromptSubmit += [$KIRO_PROMPT] | .hooks.preToolUse += [$KIRO_PRETOOL] | .hooks.postToolUse += [$KIRO_POSTTOOL] | .hooks.stop += [$KIRO_STOP]" "$KIRO_SETTINGS" > "$tmp" && mv "$tmp" "$KIRO_SETTINGS"
        echo "  ✓ Hooks registered in ~/.kiro/settings.json"
    elif [ ! -f "$KIRO_SETTINGS" ]; then
        mkdir -p "$(dirname "$KIRO_SETTINGS")"
        cat > "$KIRO_SETTINGS" << KIRO_EOF
{
  "hooks": {
    "agentSpawn": [$KIRO_SPAWN],
    "userPromptSubmit": [$KIRO_PROMPT],
    "preToolUse": [$KIRO_PRETOOL],
    "postToolUse": [$KIRO_POSTTOOL],
    "stop": [$KIRO_STOP]
  }
}
KIRO_EOF
        echo "  ✓ Created ~/.kiro/settings.json (hooks)"
    else
        echo "  ⚠  jq not found — install jq to auto-register hooks"
    fi

    # 7b2. Register MCP in mcp.json FIRST (kiro-cli reads this at startup)
    # This MUST happen before kiro-cli launches so nora loads without WARNING.
    KIRO_MCP_DIR="$HOME/.kiro/settings"
    KIRO_MCP_FILE="$KIRO_MCP_DIR/mcp.json"
    mkdir -p "$KIRO_MCP_DIR"

    # Always use Python to write mcp.json — reliable, no jq dependency, includes autoApprove
    "$PYTHON" -c "
import json, os
mcp_file = '$KIRO_MCP_FILE'
python_bin = '$PYTHON'
nora_mcp = '$KERNORA_DIR/app/nora_mcp.py'

# Read existing config if present
config = {}
try:
    with open(mcp_file) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass

config.setdefault('mcpServers', {})

# Remove stale entries
for stale in ['aws-diagrams', 'aws-docs']:
    config['mcpServers'].pop(stale, None)

# Register nora with autoApprove for all 16 tools
config['mcpServers']['nora'] = {
    'command': python_bin,
    'args': [nora_mcp],
    'autoApprove': [
        'nora_search', 'nora_patterns', 'nora_decisions', 'nora_bugs',
        'nora_stats', 'nora_session', 'nora_scope_validation', 'nora_skills',
        'nora_scan', 'nora_pe_review', 'nora_coe', 'nora_coe_product',
        'nora_retro', 'nora_sofac', 'nora_inventory', 'nora_help',
    ],
}

with open(mcp_file, 'w') as f:
    json.dump(config, f, indent=2)
" && echo "  ✓ MCP registered in ~/.kiro/settings/mcp.json (16 tools, autoApprove)" \
   || echo "  ⚠ Could not write mcp.json"

    # Also try kiro-cli mcp add (syncs in-memory if kiro is already running)
    if command -v kiro-cli-chat &>/dev/null; then
        kiro-cli-chat mcp add --name "nora" --scope global --command "$PYTHON" --args "$KERNORA_DIR/app/nora_mcp.py" --force 2>/dev/null \
            && echo "  ✓ MCP synced via kiro-cli-chat mcp add --force" || true
    elif command -v kiro-cli &>/dev/null; then
        kiro-cli mcp add --name "nora" --scope global --command "$PYTHON" --args "$KERNORA_DIR/app/nora_mcp.py" --force 2>/dev/null \
            && echo "  ✓ MCP synced via kiro-cli mcp add --force" || true
    fi

    # 7c. Install Kiro extension (VSIX)
    VSIX=$(ls "$REPO_DIR/kiro-extension"/kernora-*.vsix 2>/dev/null | sort -V | tail -1)
    if [ -n "$VSIX" ]; then
        VSIX_VERSION=$(echo "$VSIX" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
        EXT_DIR="$HOME/.kiro/extensions/kernora.kernora-${VSIX_VERSION}"

        # Remove old versions
        rm -rf "$HOME/.kiro/extensions/kernora.kernora-"* 2>/dev/null || true

        # Extract VSIX (it's a zip with extension/ subfolder)
        mkdir -p "$EXT_DIR"
        TMP_VSIX=$(mktemp -d)
        unzip -qo "$VSIX" -d "$TMP_VSIX"
        cp -R "$TMP_VSIX/extension/"* "$EXT_DIR/"
        rm -rf "$TMP_VSIX"
        echo "  ✓ Extension v${VSIX_VERSION} installed to ~/.kiro/extensions/"
    else
        echo "  ⚠  No .vsix found in kiro-extension/ — build with: cd kiro-extension && npm run compile && npx vsce package"
    fi

    # 7d. Generate steering files if DB has data
    if [ -f "$KERNORA_DIR/echo.db" ] && [ -f "$REPO_DIR/steering_writer.py" ]; then
        "$PYTHON" "$REPO_DIR/steering_writer.py" 2>/dev/null && echo "  ✓ Steering files generated" || true
    fi

    echo "  ✓ Kiro setup complete"
fi

# ── 8. Claude Code setup ────────────────────────────────────────────────────
if [ "$CLAUDE_DETECTED" = true ]; then
    echo ""
    echo "── Claude Code detected ─────────────────────────────────────────"

    HOOK_DIR="$HOME/.claude/hooks"
    SETTINGS="$HOME/.claude/settings.json"
    mkdir -p "$HOOK_DIR"
    cp "$REPO_DIR/hook.py" "$HOOK_DIR/kernora_hook.py"
    cp "$REPO_DIR/nora_context.py" "$HOOK_DIR/nora_context.py"
    cp "$REPO_DIR/kiro_spec_shield.py" "$HOOK_DIR/nora_pretool.py"
    cp "$REPO_DIR/kiro_post_tool.py" "$HOOK_DIR/nora_posttool.py"
    cp "$REPO_DIR/nora_session_start.py" "$HOOK_DIR/nora_session_start.py"
    cp "$REPO_DIR/nora_precompact.py" "$HOOK_DIR/nora_precompact.py"
    chmod +x "$HOOK_DIR"/*.py
    echo "  ✓ Hooks installed (6 hooks)"

    STOP_HOOK="{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/kernora_hook.py\",\"async\":true}]}"
    CONTEXT_HOOK="{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_context.py\",\"timeout\":3}]}"
    PRETOOL_HOOK="{\"matcher\":\"Write|Edit|Bash\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_pretool.py\",\"timeout\":5}]}"
    POSTTOOL_HOOK="{\"matcher\":\"Bash\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_posttool.py\",\"async\":true}]}"
    SESSION_START_HOOK="{\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_session_start.py\",\"timeout\":5}]}"
    PRECOMPACT_HOOK="{\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_precompact.py\",\"timeout\":3}]}"

    if [ -f "$SETTINGS" ] && command -v jq &>/dev/null; then
        tmp=$(mktemp)
        jq ".hooks.Stop += [$STOP_HOOK] | .hooks.UserPromptSubmit += [$CONTEXT_HOOK] | .hooks.PreToolUse += [$PRETOOL_HOOK] | .hooks.PostToolUse += [$POSTTOOL_HOOK] | .hooks.SessionStart += [$SESSION_START_HOOK] | .hooks.PreCompact += [$PRECOMPACT_HOOK]" "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
        echo "  ✓ Hooks registered in ~/.claude/settings.json"
    elif [ ! -f "$SETTINGS" ]; then
        mkdir -p "$(dirname "$SETTINGS")"
        cat > "$SETTINGS" << SETTINGS_EOF
{
  "hooks": {
    "UserPromptSubmit": [$CONTEXT_HOOK],
    "PreToolUse": [$PRETOOL_HOOK],
    "PostToolUse": [$POSTTOOL_HOOK],
    "SessionStart": [$SESSION_START_HOOK],
    "PreCompact": [$PRECOMPACT_HOOK],
    "Stop": [$STOP_HOOK]
  }
}
SETTINGS_EOF
        echo "  ✓ Created ~/.claude/settings.json"
    else
        echo "  ⚠  jq not found — add hooks to ~/.claude/settings.json manually"
    fi

    # Register MCP server
    MCP_CONFIG="$HOME/.claude/.mcp.json"
    NORA_MCP="{\"command\":\"$PYTHON\",\"args\":[\"$REPO_DIR/nora_mcp.py\"]}"
    if [ -f "$MCP_CONFIG" ] && command -v jq &>/dev/null; then
        tmp=$(mktemp)
        jq ".mcpServers.nora = $NORA_MCP" "$MCP_CONFIG" > "$tmp" && mv "$tmp" "$MCP_CONFIG"
        echo "  ✓ MCP server registered in ~/.claude/.mcp.json"
    elif [ ! -f "$MCP_CONFIG" ]; then
        mkdir -p "$(dirname "$MCP_CONFIG")"
        echo "{\"mcpServers\":{\"nora\":$NORA_MCP}}" | jq . > "$MCP_CONFIG"
        echo "  ✓ Created ~/.claude/.mcp.json"
    fi

    echo "  ✓ Claude Code setup complete"
fi

# ── 9. API key (only needed for BYOK — not Kiro/Cursor) ─────────────────────
DETECTED_KEY="${ANTHROPIC_API_KEY:-}"
if [ "$KIRO_DETECTED" = true ] || [ "$CURSOR_DETECTED" = true ]; then
    echo ""
    echo "✓ IDE-provided LLM detected — no API key required for session analysis"
    echo "  (Kiro/Cursor provide their own model. BYOK config is for CLI use only.)"
elif [ -z "$DETECTED_KEY" ]; then
    echo ""
    echo "  ┌─ Set your LLM provider (choose one) ────────────────────────────┐"
    echo "  │  Anthropic:  export ANTHROPIC_API_KEY=sk-ant-...                │"
    echo "  │  OpenAI:     export OPENAI_API_KEY=sk-...                       │"
    echo "  │  Bedrock:    aws configure --profile kernora                     │"
    echo "  │  Ollama:     ollama pull llama3.2:3b                            │"
    echo "  │              then in config.toml: provider = \"ollama\"           │"
    echo "  └──────────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  Or press Enter to skip (configure later in the dashboard Settings tab):"
    read -r -s DETECTED_KEY
    echo ""
fi

# ── 10. Auto-start on login (macOS) ─────────────────────────────────────────
if [ "$(uname)" = "Darwin" ]; then
    mkdir -p "$LAUNCH_AGENTS"
    WHOAMI=$(whoami)

    ENV_BLOCK=""
    if [ -n "$DETECTED_KEY" ]; then
        ENV_BLOCK="  <key>EnvironmentVariables</key>
  <dict>
    <key>ANTHROPIC_API_KEY</key>
    <string>${DETECTED_KEY}</string>
  </dict>"
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

    # Dashboard plist — runs from ~/.kernora/app/ not repo dir
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

    launchctl unload "$LAUNCH_AGENTS/ai.kernora.daemon.plist" 2>/dev/null || true
    launchctl unload "$LAUNCH_AGENTS/ai.kernora.dashboard.plist" 2>/dev/null || true
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

# ── 11. Smoke test ──────────────────────────────────────────────────────────
echo ""
if curl -sf http://localhost:2742 > /dev/null 2>&1; then
    echo "✓ Dashboard live at http://localhost:2742"
else
    echo "→ Dashboard starting — will be ready in a few seconds"
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo "  ┌──────────────────────────────────────────────────────────────────┐"
echo "  │                                                                  │"
echo "  │  ◎  Kernora is ready                                            │"
echo "  │                                                                  │"
echo "  │  Your second session starts smarter than your first.            │"
echo "  │                                                                  │"
if [ "$KIRO_DETECTED" = true ]; then
echo "  │  Kiro App: Open Kiro → Cmd+Shift+P → Developer: Reload Window   │"
echo "  │  Kiro CLI: Just run 'kiro-cli' — MCP tools work immediately    │"
echo "  │                                                                  │"
echo "  │  Try it: ask Kiro's AI —                                        │"
echo "  │    \"Use nora_stats to show my coding statistics\"                │"
echo "  │                                                                  │"
echo "  │  Kiro: extension + 5 hooks + MCP + dashboard                   │"
elif [ "$CLAUDE_DETECTED" = true ]; then
echo "  │  Dashboard  →  http://localhost:2742                            │"
echo "  │                                                                  │"
echo "  │  Claude Code: 6 hooks + MCP active                             │"
fi
echo "  │  Config     →  ~/.kernora/config.toml                           │"
echo "  │  Database   →  ~/.kernora/echo.db                               │"
echo "  │                                                                  │"
echo "  └──────────────────────────────────────────────────────────────────┘"
echo ""
