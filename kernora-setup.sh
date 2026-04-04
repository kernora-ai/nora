#!/bin/bash
# Kernora — CLI Setup Script
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
#
# PURPOSE: This script does everything the extension's activate() does,
# but as a standalone shell command. It ensures MCP, hooks, venv, DB,
# and dashboard are all configured BEFORE kiro-cli starts.
#
# WHY IT EXISTS: When you run `kiro --install-extension kernora.vsix`,
# Kiro extracts the VSIX but does NOT run activate(). When kiro-cli
# starts, it reads ~/.kiro/settings/mcp.json BEFORE loading extensions.
# Without this script, MCP tools aren't available on first launch.
#
# USAGE (after installing VSIX):
#   bash kernora-setup.sh
#
# Or one-liner:
#   kiro --install-extension kernora-1.5.4.vsix && bash kernora-setup.sh
#
# This script is idempotent — safe to run multiple times.

set -e

KERNORA_DIR="$HOME/.kernora"
APP_DIR="$KERNORA_DIR/app"
VENV_DIR="$KERNORA_DIR/venv"
PYTHON="$VENV_DIR/bin/python3"
PIP="$VENV_DIR/bin/pip"

# ── Locate bundled Python files ────────────────────────────────────────────
# We could be running from:
#   1. The repo directory (~/code/kernora/kernora-setup.sh)
#   2. The installed extension (~/. kiro/extensions/kernora.kernora-*/bundled/kernora-setup.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find bundled dir
if [ -d "$SCRIPT_DIR/kiro-extension/bundled" ]; then
    # Running from repo root
    BUNDLED_DIR="$SCRIPT_DIR/kiro-extension/bundled"
    REPO_MODE=true
elif [ -d "$SCRIPT_DIR/bundled" ]; then
    # Running from extension root (e.g. ~/.kiro/extensions/kernora.kernora-1.5.4/)
    BUNDLED_DIR="$SCRIPT_DIR/bundled"
    REPO_MODE=false
elif [ -f "$SCRIPT_DIR/dashboard.py" ]; then
    # Running from inside bundled/ itself
    BUNDLED_DIR="$SCRIPT_DIR"
    REPO_MODE=false
else
    # Fallback: check installed extension directory
    EXT_PATTERN="$HOME/.kiro/extensions/kernora.kernora-*/bundled"
    BUNDLED_DIR=$(ls -d $EXT_PATTERN 2>/dev/null | sort -V | tail -1)
    if [ -z "$BUNDLED_DIR" ]; then
        echo "✗ Cannot find Kernora bundled files."
        echo "  Run: kiro --install-extension kernora-<version>.vsix first"
        exit 1
    fi
    REPO_MODE=false
fi

echo ""
echo "◎  Kernora CLI Setup"
echo "   Configuring hooks, MCP, dashboard — so kiro-cli works on first launch."
echo ""

# ── 1. Python check ────────────────────────────────────────────────────────
python3 -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null || {
    echo "✗ Python 3.9+ required. Install from https://python.org"
    exit 1
}
echo "✓ Python $(python3 --version | cut -d' ' -f2)"

# ── 2. Sync bundled files to ~/.kernora/app/ ───────────────────────────────
mkdir -p "$APP_DIR" "$KERNORA_DIR/logs" "$KERNORA_DIR/spool"
for f in "$BUNDLED_DIR"/*.py; do
    [ -f "$f" ] && cp "$f" "$APP_DIR/$(basename "$f")"
done
# Also sync from repo root if in repo mode (repo has latest files)
if [ "$REPO_MODE" = true ]; then
    for f in dashboard.py db.py analyzer.py daemon.py nora_mcp.py nora_context.py \
             kiro_agent_spawn.py kiro_post_tool.py kiro_spec_shield.py hook.py \
             steering_writer.py telemetry.py nora_session_start.py nora_precompact.py \
             kernora_cli.py; do
        [ -f "$SCRIPT_DIR/$f" ] && cp "$SCRIPT_DIR/$f" "$APP_DIR/$f"
    done
fi
echo "✓ App files synced to ~/.kernora/app/"

# ── 3. Virtual environment + dependencies ──────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi
if [ ! -f "$PYTHON" ]; then
    echo "✗ Failed to create venv — check Python installation"
    exit 1
fi

# Install deps if flask isn't available
if ! "$PYTHON" -c "import flask" 2>/dev/null; then
    echo "→ Installing dependencies (flask, mcp, litellm)..."
    "$PIP" install flask mcp litellm --quiet 2>/dev/null
fi
echo "✓ Python environment ready"

# ── 4. Config (skip if exists) ─────────────────────────────────────────────
if [ ! -f "$KERNORA_DIR/config.toml" ]; then
    cat > "$KERNORA_DIR/config.toml" << 'TOML'
[mode]
type = "byok"

[model]
provider = "anthropic"

[analysis]
run_every_minutes = 60

[dashboard]
port = 2742
auto_open = true

[privacy]
verified = true
TOML
    echo "✓ Config created"
else
    echo "✓ Config exists"
fi

# ── 5. Initialize database ─────────────────────────────────────────────────
if [ ! -f "$KERNORA_DIR/echo.db" ]; then
    "$PYTHON" "$APP_DIR/db.py"
    echo "✓ Database initialized"
else
    # Run anyway to apply migrations
    "$PYTHON" "$APP_DIR/db.py" 2>/dev/null
    echo "✓ Database ready"
fi

# ── 6. Install Kiro hooks ──────────────────────────────────────────────────
KIRO_HOOK_DIR="$HOME/.kiro/hooks"
mkdir -p "$KIRO_HOOK_DIR"

# Map: app filename → hook filename
declare -A HOOK_MAP=(
    ["nora_context.py"]="nora_context.py"
    ["kiro_agent_spawn.py"]="nora_spawn.py"
    ["kiro_spec_shield.py"]="nora_pretool.py"
    ["kiro_post_tool.py"]="nora_posttool.py"
    ["hook.py"]="nora_stop.py"
)

for src in "${!HOOK_MAP[@]}"; do
    dest="${HOOK_MAP[$src]}"
    if [ -f "$APP_DIR/$src" ]; then
        cp "$APP_DIR/$src" "$KIRO_HOOK_DIR/$dest"
        chmod +x "$KIRO_HOOK_DIR/$dest"
    fi
done
echo "✓ Hooks installed (5 hooks → ~/.kiro/hooks/)"

# ── 7. Register hooks in ~/.kiro/settings.json ────────────────────────────
KIRO_SETTINGS="$HOME/.kiro/settings.json"
"$PYTHON" - "$KIRO_SETTINGS" "$PYTHON" << 'PYEOF'
import json, sys

settings_path = sys.argv[1]
python_bin = sys.argv[2]

# Load existing
try:
    with open(settings_path) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}

if "hooks" not in settings:
    settings["hooks"] = {}

hook_defs = {
    "userPromptSubmit": {"hooks": [{"type": "command", "command": f"{python_bin} ~/.kiro/hooks/nora_context.py", "timeout": 3}]},
    "agentSpawn": {"hooks": [{"type": "command", "command": f"{python_bin} ~/.kiro/hooks/nora_spawn.py"}]},
    "preToolUse": {"matcher": "", "hooks": [{"type": "command", "command": f"{python_bin} ~/.kiro/hooks/nora_pretool.py", "timeout": 5}]},
    "postToolUse": {"matcher": "", "hooks": [{"type": "command", "command": f"{python_bin} ~/.kiro/hooks/nora_posttool.py", "async": True}]},
    "stop": {"hooks": [{"type": "command", "command": f"{python_bin} ~/.kiro/hooks/nora_stop.py", "async": True}]},
}

for name, definition in hook_defs.items():
    if name not in settings["hooks"]:
        settings["hooks"][name] = []
    # Remove old Nora entries (idempotent)
    settings["hooks"][name] = [
        h for h in settings["hooks"][name]
        if "nora_" not in json.dumps(h)
    ]
    settings["hooks"][name].append(definition)

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
PYEOF
echo "✓ Hooks registered in ~/.kiro/settings.json"

# ── 8. Register MCP in ~/.kiro/settings/mcp.json ──────────────────────────
#    THIS IS THE CRITICAL STEP — MCP must be here BEFORE kiro-cli starts
KIRO_MCP_DIR="$HOME/.kiro/settings"
KIRO_MCP_FILE="$KIRO_MCP_DIR/mcp.json"
mkdir -p "$KIRO_MCP_DIR"

"$PYTHON" - "$KIRO_MCP_FILE" "$PYTHON" "$APP_DIR/nora_mcp.py" << 'PYEOF'
import json, sys

mcp_path = sys.argv[1]
python_bin = sys.argv[2]
mcp_script = sys.argv[3]

# Load existing
try:
    with open(mcp_path) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    config = {}

if "mcpServers" not in config:
    config["mcpServers"] = {}

# Remove stale entries that cause error toasts
for stale in ["aws-diagrams", "aws-docs"]:
    config["mcpServers"].pop(stale, None)

# Register Nora MCP
config["mcpServers"]["nora"] = {
    "command": python_bin,
    "args": [mcp_script]
}

with open(mcp_path, "w") as f:
    json.dump(config, f, indent=2)
PYEOF
echo "✓ MCP server registered in ~/.kiro/settings/mcp.json"

# ── 9. Start dashboard ─────────────────────────────────────────────────────
pkill -f "kernora.*dashboard.py" 2>/dev/null || true
sleep 1

nohup "$PYTHON" "$APP_DIR/dashboard.py" > "$KERNORA_DIR/logs/dashboard.log" 2>&1 &
DASH_PID=$!
echo "✓ Dashboard starting (PID $DASH_PID)"

# Wait for dashboard to be ready (max 10s)
for i in $(seq 1 10); do
    if curl -sf http://localhost:2742/health >/dev/null 2>&1; then
        echo "✓ Dashboard live at http://localhost:2742"
        break
    fi
    sleep 1
done

# ── 10. Generate steering files ────────────────────────────────────────────
if [ -f "$APP_DIR/steering_writer.py" ]; then
    "$PYTHON" "$APP_DIR/steering_writer.py" 2>/dev/null && echo "✓ Steering files generated" || echo "✓ Steering files skipped (no data yet)"
fi

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "  ┌──────────────────────────────────────────────────────────────────┐"
echo "  │                                                                  │"
echo "  │  ◎  Kernora CLI setup complete                                  │"
echo "  │                                                                  │"
echo "  │  Everything is configured. Start kiro-cli now:                  │"
echo "  │                                                                  │"
echo "  │    kiro-cli                                                     │"
echo "  │                                                                  │"
echo "  │  Then try:                                                      │"
echo "  │    \"Use nora_stats to show my coding statistics\"                │"
echo "  │    \"Use nora_session to import my recent session\"              │"
echo "  │                                                                  │"
echo "  │  Dashboard  →  http://localhost:2742                            │"
echo "  │  Config     →  ~/.kernora/config.toml                           │"
echo "  │  Database   →  ~/.kernora/echo.db                               │"
echo "  │                                                                  │"
echo "  └──────────────────────────────────────────────────────────────────┘"
echo ""
