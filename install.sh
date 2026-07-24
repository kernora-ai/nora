#!/bin/bash
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
set -e

KERNORA_DIR="$HOME/.kernora"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-__pipe__}")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

# ── Pipe-install guard (curl ... | bash sets BASH_SOURCE[0] to empty/stdin) ──
# dashboard.py, db.py etc. won't exist at REPO_DIR (user's CWD) — auto-clone.
if [ ! -f "$REPO_DIR/dashboard.py" ]; then
    if command -v git &>/dev/null; then
        echo "→ Pipe install detected — cloning kernora-ai/nora..."
        _clone_dir=$(mktemp -d)
        git clone --quiet https://github.com/kernora-ai/nora.git "$_clone_dir/nora" || {
            echo "✗ git clone failed."
            echo "  Run: git clone https://github.com/kernora-ai/nora.git && cd nora && bash install.sh"
            exit 1
        }
        REPO_DIR="$_clone_dir/nora"
        echo "✓ Cloned to $REPO_DIR"
    else
        echo "✗ Pipe install requires git. Install git first, then run:"
        echo "  git clone https://github.com/kernora-ai/nora.git && cd nora && bash install.sh"
        exit 1
    fi
fi

echo ""
echo "◎  Kernora — AI Work Intelligence"
echo "   Your coding sessions, remembered. Zero bytes leave your device."
echo ""

# ── 0. Detect IDEs ──────────────────────────────────────────────────────────
KIRO_DETECTED=false
CLAUDE_DETECTED=false
CURSOR_DETECTED=false
VSCODE_DETECTED=false

[ -d "$HOME/.kiro" ] && KIRO_DETECTED=true
[ -d "$HOME/.claude" ] && CLAUDE_DETECTED=true
[ -d "$HOME/.cursor" ] && CURSOR_DETECTED=true
# VS Code: check extensions dir or code CLI
{ [ -d "$HOME/.vscode" ] || command -v code &>/dev/null; } && VSCODE_DETECTED=true

if [ "$KIRO_DETECTED" = false ] && [ "$CLAUDE_DETECTED" = false ] && [ "$CURSOR_DETECTED" = false ] && [ "$VSCODE_DETECTED" = false ]; then
    echo "⚠  No supported IDE detected (~/.kiro, ~/.claude, ~/.cursor, or ~/.vscode)"
    echo "   Install Kiro, Claude Code, Cursor, or VS Code first."
    echo "   Continuing anyway — you can re-run install.sh after IDE setup."
    echo ""
fi

# ── 1. Python check ─────────────────────────────────────────────────────────
# Prefer 3.12/3.11 over bleeding-edge (3.14+) — litellm and some wheels lag.
PYTHON_SYS=""
for _cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$_cand" >/dev/null 2>&1; then
        if "$_cand" -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null; then
            PYTHON_SYS="$_cand"
            break
        fi
    fi
done
if [ -z "$PYTHON_SYS" ]; then
    echo "✗ Python 3.9+ required. Install from https://python.org"
    exit 1
fi
echo "✓ Python $($PYTHON_SYS --version | cut -d' ' -f2) ($PYTHON_SYS)"

# ── 2. Virtual environment + dependencies ────────────────────────────────────
VENV_DIR="$KERNORA_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment..."
    "$PYTHON_SYS" -m venv "$VENV_DIR"
fi
PYTHON="$VENV_DIR/bin/python3"
PIP="$VENV_DIR/bin/pip"
echo "→ Installing dependencies..."
# Core Free runtime (dashboard + MCP) must succeed. Optional analyzer deps
# (litellm) are best-effort — a Free install without session-analysis is still
# a runnable product (dashboard + MCP + hooks).
if ! "$PIP" install -r "$REPO_DIR/requirements.txt" --quiet; then
    echo "⚠  Full requirements install failed — retrying core Free runtime deps only"
    "$PIP" install "flask>=3.0.0" "mcp>=1.0.0" "tomli>=2.0.0" --quiet \
        || { echo "✗ Could not install core Free runtime deps (flask/mcp)"; exit 1; }
    "$PIP" install "anthropic>=0.40.0" --quiet 2>/dev/null || true
    "$PIP" install "litellm>=1.35.0" --quiet 2>/dev/null \
        || echo "⚠  litellm unavailable on this Python — session analysis deferred (dashboard + MCP still work)"
fi
echo "✓ Dependencies installed"

# ── 3. Directories + app files ───────────────────────────────────────────────
mkdir -p "$KERNORA_DIR/logs" "$KERNORA_DIR/spool" "$KERNORA_DIR/app"

# Copy ALL Python files that the extension bundles — keeps install.sh and
# extension's syncBundledFiles() in perfect sync.
#
# model_router.py (launch-loop L1 sandbox E2E, 2026-07-19): this list was
# missing model_router.py, a module dashboard.py's probe_llm() imports
# function-locally. probe_llm() is called from shell() — the page chrome
# every dashboard.py route renders through, including /welcome, which is
# where a FRESH install (0 sessions, 0 factlets) redirects on its very
# first page load (the OOBE gate). Verified empirically: a dashboard.py
# started from an ~/.kernora/app copy containing only the files below
# (pre-fix) 500'd on /welcome with "ModuleNotFoundError: No module named
# 'model_router'" — i.e. every fresh install's first page was broken.
# This is the same failure CLASS as the 2026-07-18 LOOP-B closure fix in
# kernora_installer.py (nora_mcp.py's lazy imports) — kernora_installer.py's
# own transitive-closure walk was rooted at daemon.py + nora_mcp.py only and
# does NOT include model_router.py either (dashboard.py was never a walk
# root there), so that Python install path likely has the same gap; flagged
# separately, not fixed here (out of this change's file scope).
# NOTE: dashboard.py has ~29 module-level-reachable local imports beyond
# this list (advisor_policy, capture, cost, forget, kernora_mode, score_utils,
# etc.) — most are guarded/feature-specific and not verified to break the
# core install→dashboard path the way model_router.py did. Do not assume
# this list is now closure-complete; see the candidate factlet in this
# session's report for the follow-up (compute the closure properly, the way
# kernora_installer.py's APP_FILES + test_installer_app_files_manifest.py
# already do for daemon.py/nora_mcp.py, with dashboard.py added as a root).
# Free/open-core installs ship a REDUCED file set by design. Files listed here
# that are absent from the distribution are skip-with-warn — never hard-fail
# under set -e. Founder 2026-07-24: Free ships FULL kernora_cli.py + daemon.py
# (asymmetry is MCP tool count only). Premium-only modules (telemetry.py,
# doc_portal.py, model_router.py) may still be missing on Free.
APP_FILES=(
    dashboard.py db.py analyzer.py daemon.py nora_mcp.py
    nora_context.py hook.py kernora_cli.py model_router.py
    kiro_agent_spawn.py kiro_post_tool.py kiro_spec_shield.py
    steering_writer.py telemetry.py
    nora_precompact.py nora_session_start.py
    doc_portal.py
    # Free-tier hook / init / CLI closure (present when publish allowlist includes them)
    nora_init.py nora_jsonl.py factbook_telemetry.py nora_bridge.py
    factbook_git.py kernora_network_audit.py
)
COPIED=0
SKIPPED=0
for f in "${APP_FILES[@]}"; do
    if [ -f "$REPO_DIR/$f" ]; then
        cp "$REPO_DIR/$f" "$KERNORA_DIR/app/$f"
        COPIED=$((COPIED + 1))
    else
        echo "  ⚠  App file missing: $f — skipping (Free/open-core builds omit some modules by design)"
        SKIPPED=$((SKIPPED + 1))
    fi
done
# Also copy any other root-level .py the distribution actually ships (e.g.
# CLEAN hook deps like knowledge_pack.py) so Free installs aren't limited to
# the hand-maintained APP_FILES list when the tarball/repo has more.
if command -v find >/dev/null 2>&1; then
    while IFS= read -r -d '' _py; do
        _base="$(basename "$_py")"
        if [ ! -f "$KERNORA_DIR/app/$_base" ]; then
            cp "$_py" "$KERNORA_DIR/app/$_base"
            COPIED=$((COPIED + 1))
        fi
    done < <(find "$REPO_DIR" -maxdepth 1 -name '*.py' -type f -print0 2>/dev/null)
fi

# Write version file (matches extension's syncBundledFiles behavior)
VERSION=$("$PYTHON" -c "import json; print(json.load(open('$REPO_DIR/kiro-extension/package.json'))['version'])" 2>/dev/null || echo "unknown")
echo "$VERSION" > "$KERNORA_DIR/app/.version"

echo "✓ App files installed to ~/.kernora/app/ ($COPIED files, ${SKIPPED:-0} skipped, v$VERSION)"

# ── 3.5. Build nora-ui bundle (required for /agent + /factbook + /sessions SPA) ─
# dashboard.py resolves NORA_UI_DIST as Path(__file__).parent/"nora-ui"/"dist",
# which is ~/.kernora/app/nora-ui/dist/ in production. We build in the repo,
# then copy the dist to that location so the installed dashboard can serve it.
NORA_UI_DIR="$REPO_DIR/nora-ui"
NORA_UI_DIST="$NORA_UI_DIR/dist"
if [ -d "$NORA_UI_DIR" ]; then
    if [ -d "$NORA_UI_DIST" ] && [ -n "$(ls -A "$NORA_UI_DIST" 2>/dev/null)" ]; then
        echo "✓ nora-ui bundle already built (skip — delete nora-ui/dist to force rebuild)"
    elif command -v npm &>/dev/null; then
        echo "→ Building nora-ui bundle (first install — takes ~30s)..."
        _build_log=$(mktemp)
        (cd "$NORA_UI_DIR" && npm install --silent 2>&1 && npm run build 2>&1) > "$_build_log" 2>&1 \
            && echo "✓ nora-ui bundle built — /agent, /factbook, /sessions will render" \
            || { echo "⚠  nora-ui build failed — /agent, /factbook, /sessions will return 503."
                 echo "   Build log: $_build_log"
                 echo "   Fix: cd nora-ui && npm install && npm run build"; }
        rm -f "$_build_log"
    else
        echo "⚠  npm not found — nora-ui bundle not built. /agent, /factbook, /sessions will return 503."
        echo "   Install Node.js (https://nodejs.org) then run: cd nora-ui && npm install && npm run build"
    fi
    # Deploy built bundle to ~/.kernora/app/nora-ui/dist/ (dashboard.py's runtime path).
    # Runs on every install so reinstalls pick up updated assets.
    if [ -d "$NORA_UI_DIST" ] && [ -n "$(ls -A "$NORA_UI_DIST" 2>/dev/null)" ]; then
        mkdir -p "$KERNORA_DIR/app/nora-ui"
        rm -rf "$KERNORA_DIR/app/nora-ui/dist"
        cp -r "$NORA_UI_DIST" "$KERNORA_DIR/app/nora-ui/dist"
        echo "✓ nora-ui bundle deployed → ~/.kernora/app/nora-ui/dist/"
    fi
fi

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
    # H-3 fix (launch-loop L1, 2026-07-19): count what was ACTUALLY copied
    # instead of hardcoding "(5 hooks)" — a source file missing (e.g. on a
    # future repo reorg, or a truncated distribution) must not silently claim
    # success. Per-file existence check also means one missing hook source
    # degrades gracefully instead of `set -e` aborting the entire install.
    KIRO_HOOK_DIR="$HOME/.kiro/hooks"
    KIRO_STEERING_DIR="$HOME/.kiro/steering"
    mkdir -p "$KIRO_HOOK_DIR" "$KIRO_STEERING_DIR"
    KIRO_HOOK_PAIRS=(
        "kiro_agent_spawn.py:nora_spawn.py"
        "nora_context.py:nora_context.py"
        "kiro_spec_shield.py:nora_pretool.py"
        "kiro_post_tool.py:nora_posttool.py"
        "hook.py:nora_stop.py"
    )
    KIRO_HOOKS_COPIED=0
    for _pair in "${KIRO_HOOK_PAIRS[@]}"; do
        _src="${_pair%%:*}"
        _dst="${_pair##*:}"
        if [ -f "$REPO_DIR/$_src" ]; then
            cp "$REPO_DIR/$_src" "$KIRO_HOOK_DIR/$_dst"
            KIRO_HOOKS_COPIED=$((KIRO_HOOKS_COPIED + 1))
        else
            echo "  ⚠  Hook source missing: $_src — skipping $_dst"
        fi
    done
    chmod +x "$KIRO_HOOK_DIR"/*.py 2>/dev/null || true
    echo "  ✓ Hooks installed ($KIRO_HOOKS_COPIED/${#KIRO_HOOK_PAIRS[@]} hooks)"

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

    # Always use Python to write mcp.json — reliable, no jq dependency.
    # Honesty (clean-VM 2026-07-24): autoApprove is DERIVED from the installed
    # nora_mcp.py (LITE_TOOL_NAMES or name="nora_*" decls). Never a hardcoded
    # Pro/legacy phantom list (nora_stats/nora_patterns/…).
    export KIRO_MCP_FILE INSTALL_PYTHON="$PYTHON" INSTALL_NORA_MCP="$KERNORA_DIR/app/nora_mcp.py"
    KIRO_MCP_FILE="$KIRO_MCP_FILE" INSTALL_PYTHON="$PYTHON" INSTALL_NORA_MCP="$KERNORA_DIR/app/nora_mcp.py" \
    "$PYTHON" <<'PY' || echo "  ⚠ Could not write mcp.json"
import json, re, os
mcp_file = os.environ["KIRO_MCP_FILE"]
python_bin = os.environ["INSTALL_PYTHON"]
nora_mcp = os.environ["INSTALL_NORA_MCP"]

config = {}
try:
    with open(mcp_file) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass

config.setdefault("mcpServers", {})
for stale in ["aws-diagrams", "aws-docs"]:
    config["mcpServers"].pop(stale, None)

src = ""
try:
    with open(nora_mcp, encoding="utf-8") as f:
        src = f.read()
except FileNotFoundError:
    pass

auto_approve = []
m = re.search(r"LITE_TOOL_NAMES\s*=\s*frozenset\(\{([^}]*)\}", src, re.S)
if m:
    auto_approve = sorted(set(re.findall(r"['\"]([a-z0-9_]+)['\"]", m.group(1))))
if not auto_approve and src:
    auto_approve = sorted(set(re.findall(r"name=['\"](nora_[a-z0-9_]+)['\"]", src)))
if not auto_approve:
    auto_approve = [
        "nora_search", "nora_context_for_task", "nora_factbook_view",
        "nora_factbook_add", "nora_factbook", "nora_factbook_inject",
        "nora_factbook_verify", "nora_generate", "nora_help", "nora_roi",
        "nora_claude_memory", "nora_pe_review", "nora_factbook_promote",
        "nora_factbook_reverse", "nora_provenance",
    ]

config["mcpServers"]["nora"] = {
    "command": python_bin,
    "args": [nora_mcp],
    "autoApprove": auto_approve,
}
with open(mcp_file, "w") as f:
    json.dump(config, f, indent=2)
print(f"  ✓ MCP registered in ~/.kiro/settings/mcp.json ({len(auto_approve)} tools, autoApprove)")
PY

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
# KERNORA_NO_CLAUDE_WIRE=1 → install the runtime but do NOT wire ~/.claude
# hooks/MCP. Used by the Claude Code PLUGIN (kernora-plugin), which owns the
# hook + MCP wiring via its manifest — without this guard a plugin-managed
# install would double-register every hook (fire twice per prompt).
if [ "$CLAUDE_DETECTED" = true ] && [ "${KERNORA_NO_CLAUDE_WIRE:-}" != "1" ]; then
    echo ""
    echo "── Claude Code detected ─────────────────────────────────────────"

    HOOK_DIR="$HOME/.claude/hooks"
    SETTINGS="$HOME/.claude/settings.json"
    mkdir -p "$HOOK_DIR"
    # H-3 fix (launch-loop L1, 2026-07-19): count what was ACTUALLY copied —
    # see matching note on the Kiro hooks loop above.
    CLAUDE_HOOK_PAIRS=(
        "hook.py:kernora_hook.py"
        "nora_context.py:nora_context.py"
        "kiro_spec_shield.py:nora_pretool.py"
        "kiro_post_tool.py:nora_posttool.py"
        "nora_session_start.py:nora_session_start.py"
        "nora_precompact.py:nora_precompact.py"
    )
    CLAUDE_HOOKS_COPIED=0
    for _pair in "${CLAUDE_HOOK_PAIRS[@]}"; do
        _src="${_pair%%:*}"
        _dst="${_pair##*:}"
        if [ -f "$REPO_DIR/$_src" ]; then
            cp "$REPO_DIR/$_src" "$HOOK_DIR/$_dst"
            CLAUDE_HOOKS_COPIED=$((CLAUDE_HOOKS_COPIED + 1))
        else
            echo "  ⚠  Hook source missing: $_src — skipping $_dst"
        fi
    done
    chmod +x "$HOOK_DIR"/*.py 2>/dev/null || true
    echo "  ✓ Hooks installed ($CLAUDE_HOOKS_COPIED/${#CLAUDE_HOOK_PAIRS[@]} hooks)"

    STOP_HOOK="{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/kernora_hook.py\",\"async\":true}]}"
    CONTEXT_HOOK="{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_context.py\",\"timeout\":3}]}"
    PRETOOL_HOOK="{\"matcher\":\"Write|Edit|Bash\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_pretool.py\",\"timeout\":5}]}"
    # 2026-07-23: widened Bash -> Bash|Read so the secret-output scanner
    # (docs/POSTTOOL-SECRET-SCANNER-REDESIGN-JUL-23-2026.md) also sees
    # Read tool output (e.g. a Read of a .env that echoes a live key).
    POSTTOOL_HOOK="{\"matcher\":\"Bash|Read\",\"hooks\":[{\"type\":\"command\",\"command\":\"$PYTHON ~/.claude/hooks/nora_posttool.py\",\"async\":true}]}"
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

    # Register MCP server.
    # B-5 fix (launch-loop L1, 2026-07-19): was "$REPO_DIR/nora_mcp.py" — under
    # curl|bash, REPO_DIR is the mktemp clone dir from the pipe-install guard
    # above (not guaranteed to survive after this script exits). Register
    # against the persistent $KERNORA_DIR/app/nora_mcp.py copy instead —
    # matches the principle in kernora_installer.py (register MCP against the
    # durable installed path, not the ephemeral source clone) and matches
    # what the Kiro (7b2) and Cursor (8b) sections below already do correctly.
    # M-6 fix: rewritten in Python (no jq dependency) — the previous jq-gated
    # form had two live bugs: (a) if $MCP_CONFIG existed and jq was absent,
    # NEITHER branch ran — MCP registration silently no-op'd; (b) if
    # $MCP_CONFIG did NOT exist and jq was absent, `echo ... | jq .` failed
    # (jq: command not found, exit 127) and `set -e` aborted the ENTIRE
    # install. Python (stdlib json, merge-preserving) removes both failure
    # modes and needs no external binary.
    MCP_CONFIG="$HOME/.claude/.mcp.json"
    "$PYTHON" -c "
import json
mcp_file = '$MCP_CONFIG'
python_bin = '$PYTHON'
nora_mcp = '$KERNORA_DIR/app/nora_mcp.py'

config = {}
try:
    with open(mcp_file) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass

config.setdefault('mcpServers', {})
config['mcpServers']['nora'] = {'command': python_bin, 'args': [nora_mcp]}

with open(mcp_file, 'w') as f:
    json.dump(config, f, indent=2)
" && echo "  ✓ MCP server registered in ~/.claude/.mcp.json" \
   || echo "  ⚠ Could not write .mcp.json"

    echo "  ✓ Claude Code setup complete"
fi

# ── 8b. Cursor setup ────────────────────────────────────────────────────────
if [ "$CURSOR_DETECTED" = true ]; then
    echo ""
    echo "── Cursor detected ──────────────────────────────────────────────"

    # Install VSIX to ~/.cursor/extensions/
    VSIX=$(ls "$REPO_DIR/kiro-extension"/kernora-*.vsix 2>/dev/null | sort -V | tail -1)
    if [ -n "$VSIX" ]; then
        VSIX_VERSION=$(echo "$VSIX" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
        EXT_DIR="$HOME/.cursor/extensions/kernora.kernora-${VSIX_VERSION}"
        rm -rf "$HOME/.cursor/extensions/kernora.kernora-"* 2>/dev/null || true
        mkdir -p "$EXT_DIR"
        TMP_VSIX=$(mktemp -d)
        unzip -qo "$VSIX" -d "$TMP_VSIX"
        cp -R "$TMP_VSIX/extension/"* "$EXT_DIR/"
        rm -rf "$TMP_VSIX"
        echo "  ✓ Extension v${VSIX_VERSION} installed to ~/.cursor/extensions/"
    else
        echo "  ⚠  No .vsix found — build with: cd kiro-extension && npm run compile && npx vsce package"
    fi

    # Register Nora MCP server in ~/.cursor/mcp.json (Cursor's global MCP config).
    # M-6-class fix (launch-loop L1, 2026-07-19): the previous jq-gated form's
    # `else` branch fired whenever jq was absent — INCLUDING when CURSOR_MCP
    # already existed — and blindly overwrote the file with only the nora
    # entry, destroying any other MCP servers or settings the user had.
    # Python (merge-preserving, no jq dependency) removes that data-loss path.
    CURSOR_MCP="$HOME/.cursor/mcp.json"
    "$PYTHON" -c "
import json
mcp_file = '$CURSOR_MCP'
python_bin = '$PYTHON'
nora_mcp = '$KERNORA_DIR/app/nora_mcp.py'

config = {}
try:
    with open(mcp_file) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    pass

config.setdefault('mcpServers', {})
config['mcpServers']['nora'] = {'command': python_bin, 'args': [nora_mcp]}

with open(mcp_file, 'w') as f:
    json.dump(config, f, indent=2)
" && echo "  ✓ MCP server registered in ~/.cursor/mcp.json" \
   || echo "  ⚠ Could not write ~/.cursor/mcp.json"

    # Deploy .cursorrules steering file if DB has data
    if [ -f "$KERNORA_DIR/echo.db" ] && [ -f "$REPO_DIR/steering_writer.py" ]; then
        "$PYTHON" "$REPO_DIR/steering_writer.py" 2>/dev/null && echo "  ✓ .cursorrules steering file generated" || true
    fi

    echo "  ✓ Cursor setup complete"
fi

# ── 8c. VS Code setup ───────────────────────────────────────────────────────
if [ "$VSCODE_DETECTED" = true ]; then
    echo ""
    echo "── VS Code detected ─────────────────────────────────────────────"

    VSIX=$(ls "$REPO_DIR/kiro-extension"/kernora-*.vsix 2>/dev/null | sort -V | tail -1)
    if [ -n "$VSIX" ]; then
        VSIX_VERSION=$(echo "$VSIX" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
        if command -v code &>/dev/null; then
            # Install via CLI (preferred — handles hot-reload)
            code --install-extension "$VSIX" --force 2>/dev/null \
                && echo "  ✓ Extension v${VSIX_VERSION} installed via 'code --install-extension'" \
                || echo "  ⚠  code CLI install failed — installing manually"
        fi
        # Also extract to ~/.vscode/extensions/ as fallback
        EXT_DIR="$HOME/.vscode/extensions/kernora.kernora-${VSIX_VERSION}"
        if [ ! -d "$EXT_DIR" ]; then
            rm -rf "$HOME/.vscode/extensions/kernora.kernora-"* 2>/dev/null || true
            mkdir -p "$EXT_DIR"
            TMP_VSIX=$(mktemp -d)
            unzip -qo "$VSIX" -d "$TMP_VSIX"
            cp -R "$TMP_VSIX/extension/"* "$EXT_DIR/"
            rm -rf "$TMP_VSIX"
            echo "  ✓ Extension extracted to ~/.vscode/extensions/"
        fi
    else
        echo "  ⚠  No .vsix found — build with: cd kiro-extension && npm run compile && npx vsce package"
    fi

    echo "  ✓ VS Code setup complete (restart VS Code to activate)"
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
    if [ -t 0 ] && [ "${KERNORA_NONINTERACTIVE:-}" != "1" ]; then
        echo "  Or press Enter to skip (configure later in the dashboard Settings tab):"
        read -r -s DETECTED_KEY
        echo ""
    else
        echo "  (noninteractive — skipping API-key prompt; configure later in dashboard Settings)"
        DETECTED_KEY=""
    fi
fi

# ── 10. Auto-start on login (macOS) ─────────────────────────────────────────
# KERNORA_FORCE_NOHUP=1 → use the Linux nohup path even on Darwin (clean-HOME
# / CI tests must not write LaunchAgents under the real operator home).
if [ "$(uname)" = "Darwin" ] && [ "${KERNORA_FORCE_NOHUP:-}" != "1" ]; then
    mkdir -p "$LAUNCH_AGENTS"
    WHOAMI=$(whoami)

    # ── 10a. Write ~/.kernora/launch.env (0600) — secrets out of plists (§10.2) ──
    # ANTHROPIC_API_KEY moves from 0644 plist EnvironmentVariables to this 0600 file.
    # License is NOT stored here — it goes through `kernora license activate` (D5).
    LAUNCH_ENV="$KERNORA_DIR/launch.env"
    if [ ! -f "$LAUNCH_ENV" ]; then
        touch "$LAUNCH_ENV"
        chmod 0600 "$LAUNCH_ENV"
    fi
    # Write ANTHROPIC_API_KEY if set and not already present
    if [ -n "$DETECTED_KEY" ]; then
        if ! grep -q "^ANTHROPIC_API_KEY=" "$LAUNCH_ENV" 2>/dev/null; then
            echo "ANTHROPIC_API_KEY=${DETECTED_KEY}" >> "$LAUNCH_ENV"
            chmod 0600 "$LAUNCH_ENV"
        fi
    fi
    # Propagate KERNORA_DEV_BYPASS if set
    if [ -n "${KERNORA_DEV_BYPASS:-}" ]; then
        if ! grep -q "^KERNORA_DEV_BYPASS=" "$LAUNCH_ENV" 2>/dev/null; then
            echo "KERNORA_DEV_BYPASS=${KERNORA_DEV_BYPASS}" >> "$LAUNCH_ENV"
            chmod 0600 "$LAUNCH_ENV"
        fi
    fi

    # ── 10b. Generate 3 plists using shell-wrapper form (§10.1/10.2) ────────────
    # ProgramArguments = [/bin/sh, -c, "set -a; source launch.env; exec python <svc>"]
    # exec is REQUIRED — KeepAlive must track the python PID, not the /bin/sh wrapper.
    # Secrets stay in launch.env (0600); no EnvironmentVariables in plist.
    # $HOME in the sh -c string is escaped as \$HOME so /bin/sh expands it at launch.

    generate_plist() {
        local SVC="$1"    # daemon | dashboard | docportal
        local PYFILE="$2" # daemon.py | dashboard.py | doc_portal.py
        local PLIST="$LAUNCH_AGENTS/ai.kernora.${SVC}.plist"
        # H-1 fix (launch-loop L1, 2026-07-19): if PYFILE never made it into
        # ~/.kernora/app (missing from a distribution, or an APP_FILES entry
        # that didn't get copied — see the COPIED-count check in step 3),
        # KeepAlive={SuccessfulExit:false} would restart the "python <missing
        # file>" launch forever (ENOENT → non-zero exit → not a successful
        # exit → respawn). Skip generating the plist entirely rather than
        # write a LaunchAgent that's guaranteed to crash-loop.
        if [ ! -f "$KERNORA_DIR/app/${PYFILE}" ]; then
            echo "⚠  ${PYFILE} not found in ~/.kernora/app — skipping ${SVC} LaunchAgent (would crash-loop on a missing script)"
            return
        fi
        cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.kernora.${SVC}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>set -a; [ -f \$HOME/.kernora/launch.env ] &amp;&amp; . \$HOME/.kernora/launch.env; exec \$HOME/.kernora/venv/bin/python3 \$HOME/.kernora/app/${PYFILE}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <!-- KeepAlive=SuccessfulExit:false — restart ONLY on crash (exit!=0); a clean exit 0
       (singleton-loser / unlicensed clean-degrade per K1) is not respawned. -->
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>/Users/${WHOAMI}/.kernora/logs/${SVC}.log</string>
  <key>StandardErrorPath</key><string>/Users/${WHOAMI}/.kernora/logs/${SVC}.err</string>
</dict>
</plist>
PLISTEOF
        echo "✓ Plist generated: $PLIST"
    }

    generate_plist daemon    daemon.py
    generate_plist dashboard dashboard.py
    generate_plist docportal doc_portal.py

    launchctl unload "$LAUNCH_AGENTS/ai.kernora.daemon.plist" 2>/dev/null || true
    launchctl unload "$LAUNCH_AGENTS/ai.kernora.dashboard.plist" 2>/dev/null || true
    launchctl load "$LAUNCH_AGENTS/ai.kernora.daemon.plist" 2>/dev/null || true
    launchctl load "$LAUNCH_AGENTS/ai.kernora.dashboard.plist" 2>/dev/null || true
    # docportal: generated but not loaded by install.sh — orchestrator handles bootstrap
    echo "✓ Auto-start configured (LaunchAgents — daemon + dashboard loaded; docportal generated, not loaded)"
else
    # Linux / KERNORA_FORCE_NOHUP path (clean-HOME CI + Free installs).
    if [ -f "$KERNORA_DIR/app/daemon.py" ]; then
        nohup "$PYTHON" "$KERNORA_DIR/app/daemon.py" > "$KERNORA_DIR/logs/daemon.log" 2>&1 &
        echo $! > "$KERNORA_DIR/daemon.pid"
        echo "✓ Daemon started (nohup)"
    else
        echo "⚠  daemon.py not in this build — skipping background daemon"
    fi
    if [ -f "$KERNORA_DIR/app/dashboard.py" ]; then
        nohup "$PYTHON" "$KERNORA_DIR/app/dashboard.py" > "$KERNORA_DIR/logs/dashboard.log" 2>&1 &
        echo "✓ Dashboard started (nohup)"
    else
        echo "✗ dashboard.py missing — Free install is not runnable without it" >&2
        exit 1
    fi
fi

# ── 10c. CLI wrapper → ~/.local/bin/kernora (+ nora alias) ──────────────────
# Founder 2026-07-24: Free ships the full CLI. website/install.sh already
# wrapped this for curl|bash; root install.sh must too so clean-HOME /
# repo-local installs get a working `kernora` on PATH.
if [ -f "$KERNORA_DIR/app/kernora_cli.py" ]; then
    mkdir -p "$HOME/.local/bin"
    cat > "$HOME/.local/bin/kernora" << CLIWRAP
#!/bin/sh
exec "$PYTHON" "$KERNORA_DIR/app/kernora_cli.py" "\$@"
CLIWRAP
    chmod +x "$HOME/.local/bin/kernora"
    ln -sf "$HOME/.local/bin/kernora" "$HOME/.local/bin/nora"
    echo "✓ CLI installed: ~/.local/bin/kernora (alias: nora)"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) echo "  ⚠  Add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
else
    echo "⚠  kernora_cli.py missing — CLI wrapper not created"
fi

sleep 2

# ── 11. Smoke test ──────────────────────────────────────────────────────────
# H-3 fix (launch-loop L1, 2026-07-19): verify the response is actually
# Kernora, not just "something is listening on :2742" — a pre-existing
# unrelated server on that port would otherwise make this print false success.
# Port is read from config.toml (default 2742) so clean-HOME tests on an
# alternate port are not false-negatives against a host dashboard.
echo ""
DASH_PORT=$("$PYTHON" -c "
import re
from pathlib import Path
p = Path('$KERNORA_DIR/config.toml')
port = 2742
if p.exists():
    m = re.search(r'(?m)^\s*port\s*=\s*(\d+)', p.read_text())
    if m: port = int(m.group(1))
print(port)
" 2>/dev/null || echo 2742)
if curl -sfL "http://localhost:${DASH_PORT}/" 2>/dev/null | grep -qi kernora; then
    echo "✓ Dashboard live at http://localhost:${DASH_PORT}"
else
    echo "→ Dashboard starting — will be ready in a few seconds (http://localhost:${DASH_PORT})"
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
echo "  │  Kiro: Cmd+Shift+P → Developer: Reload Window                  │"
# H-3 fix: report the actual copied count, not a hardcoded "5 hooks".
echo "  │        extension + ${KIRO_HOOKS_COPIED:-0} hooks + MCP + dashboard                │"
fi
if [ "$CLAUDE_DETECTED" = true ] && [ "${KERNORA_NO_CLAUDE_WIRE:-}" != "1" ]; then
echo "  │  Claude Code: ${CLAUDE_HOOKS_COPIED:-0} hooks + MCP active                        │"
fi
if [ "$CURSOR_DETECTED" = true ]; then
echo "  │  Cursor: restart Cursor to activate extension + MCP            │"
fi
if [ "$VSCODE_DETECTED" = true ]; then
echo "  │  VS Code: restart VS Code to activate extension                │"
fi
echo "  │                                                                  │"
echo "  │  Dashboard →  http://localhost:2742                             │"
if [ -f "$KERNORA_DIR/app/kernora_cli.py" ]; then
echo "  │  CLI        →  kernora help  (or nora help)                     │"
fi
echo "  │  Config     →  ~/.kernora/config.toml                           │"
echo "  │  Database   →  ~/.kernora/echo.db                               │"
echo "  │                                                                  │"
echo "  └──────────────────────────────────────────────────────────────────┘"
echo ""
