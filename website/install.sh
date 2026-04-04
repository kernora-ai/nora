#!/bin/bash
# Kernora — One-click installer for Mac (and Linux)
# Usage: curl -fsSL https://kernora.ai/install | bash
#
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
set -e

KERNORA_HOME="$HOME/.kernora"
KERNORA_APP="$KERNORA_HOME/app"
REPO="https://github.com/kernora-ai/nora.git"
BIN_DIR="/usr/local/bin"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
info() { echo -e "${CYAN}→${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }

echo ""
echo -e "${CYAN}◎  Kernora${NC} — meet Nora, your AI work intelligence colleague"
echo "   One-click setup: clone → configure → hook → dashboard → done."
echo ""

# ── 1. OS check ──────────────────────────────────────────────────────────────
OS="$(uname -s)"
if [ "$OS" != "Darwin" ] && [ "$OS" != "Linux" ]; then
    fail "Unsupported OS: $OS. Kernora supports macOS and Linux."
fi

# ── 2. Python 3.9+ ──────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 \
                 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null; then
            PYTHON="$(command -v "$candidate")"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.9+ required. Install from https://python.org or: brew install python3"
fi
ok "Python $($PYTHON --version | cut -d' ' -f2) → $PYTHON"

# ── 3. Git check ────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    fail "git is required. Install from https://git-scm.com or: xcode-select --install"
fi

# ── 4. Stop existing Kernora if running ──────────────────────────────────────
if pgrep -f "kernora.*daemon" &>/dev/null || pgrep -f "kernora.*dashboard" &>/dev/null; then
    info "Stopping existing Kernora..."
    if [ "$(uname)" = "Darwin" ]; then
        launchctl unload "$HOME/Library/LaunchAgents/ai.kernora.daemon.plist" 2>/dev/null || true
        launchctl unload "$HOME/Library/LaunchAgents/ai.kernora.dashboard.plist" 2>/dev/null || true
    fi
    pkill -f "kernora.*daemon" 2>/dev/null || true
    pkill -f "kernora.*dashboard" 2>/dev/null || true
    sleep 1
    ok "Stopped existing processes"
fi

# ── 5. Clone or update ──────────────────────────────────────────────────────
if [ -d "$KERNORA_APP/.git" ]; then
    info "Updating existing install..."
    cd "$KERNORA_APP"
    # Always reset remote to public URL (cleans up any stale auth tokens)
    git remote set-url origin "$REPO" 2>/dev/null || true
    git pull --ff-only origin main 2>/dev/null || git pull origin main
    ok "Updated to latest"
else
    info "Downloading Kernora..."
    rm -rf "$KERNORA_APP"
    git clone --depth 1 "$REPO" "$KERNORA_APP" 2>&1 | tail -1
    ok "Downloaded to ~/.kernora/app/"
fi

# ══════════════════════════════════════════════════════════════════════════════
# ── 6. Interactive Setup Wizard ──────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
#
# Only runs on FRESH install (no existing config.toml).
# Re-installs (updates) skip the wizard — user already configured.
# To re-run the wizard: rm ~/.kernora/config.toml && re-run installer.

mkdir -p "$KERNORA_HOME"

if [ ! -f "$KERNORA_HOME/config.toml" ]; then

    echo ""
    echo -e "  ┌──────────────────────────────────────────────────────────────────┐"
    echo -e "  │  ${BOLD}Setup Wizard${NC}                                                   │"
    echo -e "  │  ${DIM}3 questions. Takes 30 seconds. Skip any with Enter.${NC}           │"
    echo -e "  └──────────────────────────────────────────────────────────────────┘"

    # ── Q1: LLM Provider ─────────────────────────────────────────────────────
    echo ""
    echo -e "  ${BOLD}1. Which LLM should analyze your coding sessions?${NC}"
    echo ""
    echo -e "     ${GREEN}1${NC}) Anthropic (Claude)  ${DIM}— best quality, needs API key${NC}"
    echo -e "     ${GREEN}2${NC}) Google (Gemini)      ${DIM}— great quality, needs API key${NC}"
    echo -e "     ${GREEN}3${NC}) OpenAI (GPT-4o)      ${DIM}— good quality, needs API key${NC}"
    echo -e "     ${GREEN}4${NC}) xAI (Grok)           ${DIM}— good quality, needs API key${NC}"
    echo -e "     ${GREEN}5${NC}) Ollama (local)        ${DIM}— free, runs on your Mac, no key${NC}"
    echo -e "     ${GREEN}6${NC}) Auto-detect           ${DIM}— uses best available from your keys (recommended)${NC}"
    echo -e "     ${GREEN}7${NC}) Skip for now          ${DIM}— configure later in ~/.kernora/config.toml${NC}"
    echo ""
    echo -ne "     Choice [6]: "
    read -r LLM_CHOICE
    LLM_CHOICE="${LLM_CHOICE:-6}"

    # Map choice to provider
    PROVIDER="auto"
    API_KEY_VAR=""
    API_KEY_VAL=""
    case "$LLM_CHOICE" in
        1) PROVIDER="anthropic"; API_KEY_VAR="anthropic" ;;
        2) PROVIDER="google";    API_KEY_VAR="gemini" ;;
        3) PROVIDER="openai";    API_KEY_VAR="openai" ;;
        4) PROVIDER="grok";      API_KEY_VAR="xai" ;;
        5) PROVIDER="ollama" ;;
        6) PROVIDER="auto" ;;
        7) PROVIDER="auto" ;;
        *) PROVIDER="auto" ;;
    esac

    # ── Q1b: API Key (if provider needs one) ─────────────────────────────────
    if [ -n "$API_KEY_VAR" ]; then
        # Check if key already exists in environment
        case "$API_KEY_VAR" in
            anthropic) EXISTING_KEY="${ANTHROPIC_API_KEY:-}" ;;
            gemini)    EXISTING_KEY="${GEMINI_API_KEY:-}" ;;
            openai)    EXISTING_KEY="${OPENAI_API_KEY:-}" ;;
            xai)       EXISTING_KEY="${XAI_API_KEY:-}" ;;
        esac

        if [ -n "$EXISTING_KEY" ]; then
            MASKED="${EXISTING_KEY:0:8}...${EXISTING_KEY: -4}"
            echo -e "     ${GREEN}✓${NC} Found ${API_KEY_VAR} key in environment: ${DIM}${MASKED}${NC}"
            API_KEY_VAL="$EXISTING_KEY"
        else
            echo ""
            echo -ne "     Paste your API key ${DIM}(hidden, Enter to skip)${NC}: "
            read -r -s API_KEY_VAL
            echo ""
            if [ -n "$API_KEY_VAL" ]; then
                MASKED="${API_KEY_VAL:0:8}...${API_KEY_VAL: -4}"
                ok "Key saved: ${DIM}${MASKED}${NC}"
            else
                warn "No key provided — you can add it later to ~/.kernora/config.toml"
            fi
        fi
    elif [ "$PROVIDER" = "auto" ] && [ "$LLM_CHOICE" != "7" ]; then
        # Auto-detect: check what keys are already in env
        FOUND_KEYS=0
        [ -n "${ANTHROPIC_API_KEY:-}" ] && FOUND_KEYS=$((FOUND_KEYS + 1)) && ok "Found Anthropic key in environment"
        [ -n "${GEMINI_API_KEY:-}" ]    && FOUND_KEYS=$((FOUND_KEYS + 1)) && ok "Found Gemini key in environment"
        [ -n "${OPENAI_API_KEY:-}" ]    && FOUND_KEYS=$((FOUND_KEYS + 1)) && ok "Found OpenAI key in environment"
        [ -n "${XAI_API_KEY:-}" ]       && FOUND_KEYS=$((FOUND_KEYS + 1)) && ok "Found xAI key in environment"

        if [ "$FOUND_KEYS" -eq 0 ]; then
            echo ""
            echo -e "     ${DIM}No API keys found in environment. Paste one now or add later.${NC}"
            echo -e "     ${DIM}Anthropic recommended for best results.${NC}"
            echo ""
            echo -ne "     Paste any API key ${DIM}(hidden, Enter to skip)${NC}: "
            read -r -s API_KEY_VAL
            echo ""
            if [ -n "$API_KEY_VAL" ]; then
                # Auto-detect key type from prefix
                case "$API_KEY_VAL" in
                    sk-ant-*) API_KEY_VAR="anthropic"; ok "Detected Anthropic key" ;;
                    sk-*)     API_KEY_VAR="openai";    ok "Detected OpenAI key" ;;
                    AI*)      API_KEY_VAR="gemini";    ok "Detected Gemini key" ;;
                    xai-*)    API_KEY_VAR="xai";       ok "Detected xAI key" ;;
                    *)        API_KEY_VAR="anthropic"
                              warn "Couldn't detect key type — saving as Anthropic" ;;
                esac
            fi
        else
            ok "Auto-detect will use best available from ${FOUND_KEYS} key(s)"
        fi
    elif [ "$PROVIDER" = "ollama" ]; then
        # Check if Ollama is running
        if curl -sf http://localhost:11434/api/version &>/dev/null; then
            ok "Ollama is running"
        else
            warn "Ollama not detected at localhost:11434"
            echo -e "     ${DIM}Install: https://ollama.ai → then: ollama pull llama3.2:8b${NC}"
        fi
    fi

    # ── Q2: Knowledge Backup ─────────────────────────────────────────────────
    echo ""
    echo -e "  ${BOLD}2. Back up your knowledge base?${NC}"
    echo -e "     ${DIM}Your knowledge DB (~/.kernora/echo.db) lives locally by default.${NC}"
    echo -e "     ${DIM}Pick a sync folder and your existing cloud service handles the rest.${NC}"
    echo ""
    if [ "$OS" = "Darwin" ]; then
        ICLOUD_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
        if [ -d "$ICLOUD_DIR" ]; then
            echo -e "     ${GREEN}1${NC}) iCloud Drive         ${DIM}→ syncs across your Apple devices${NC}"
        else
            echo -e "     ${DIM}1) iCloud Drive         (not detected)${NC}"
        fi
        DROPBOX_DIR="$HOME/Dropbox"
        if [ -d "$DROPBOX_DIR" ]; then
            echo -e "     ${GREEN}2${NC}) Dropbox               ${DIM}→ syncs across all your devices${NC}"
        else
            echo -e "     ${DIM}2) Dropbox              (not detected)${NC}"
        fi
    else
        echo -e "     ${DIM}1) iCloud Drive         (macOS only)${NC}"
        echo -e "     ${DIM}2) Dropbox              (not detected)${NC}"
    fi
    echo -e "     ${GREEN}3${NC}) Custom path           ${DIM}→ you pick the folder${NC}"
    echo -e "     ${GREEN}4${NC}) No backup             ${DIM}→ local only (default)${NC}"
    echo ""
    echo -ne "     Choice [4]: "
    read -r BACKUP_CHOICE
    BACKUP_CHOICE="${BACKUP_CHOICE:-4}"

    BACKUP_PATH=""
    case "$BACKUP_CHOICE" in
        1)
            if [ "$OS" = "Darwin" ] && [ -d "$ICLOUD_DIR" ]; then
                BACKUP_PATH="$ICLOUD_DIR/Kernora"
                mkdir -p "$BACKUP_PATH"
                ok "Backup: iCloud Drive → $BACKUP_PATH"
            else
                warn "iCloud Drive not available — skipping backup"
            fi
            ;;
        2)
            if [ -d "$DROPBOX_DIR" ]; then
                BACKUP_PATH="$DROPBOX_DIR/Kernora"
                mkdir -p "$BACKUP_PATH"
                ok "Backup: Dropbox → $BACKUP_PATH"
            else
                warn "Dropbox not found — skipping backup"
            fi
            ;;
        3)
            echo -ne "     Enter folder path: "
            read -r CUSTOM_PATH
            if [ -n "$CUSTOM_PATH" ]; then
                # Expand ~ if present
                CUSTOM_PATH="${CUSTOM_PATH/#\~/$HOME}"
                mkdir -p "$CUSTOM_PATH" 2>/dev/null
                if [ -d "$CUSTOM_PATH" ]; then
                    BACKUP_PATH="$CUSTOM_PATH"
                    ok "Backup: $BACKUP_PATH"
                else
                    warn "Could not create $CUSTOM_PATH — skipping backup"
                fi
            fi
            ;;
        4|"")
            info "No backup — local only"
            ;;
    esac

    # ── Q3: Team Sync (S3) ───────────────────────────────────────────────────
    echo ""
    echo -e "  ${BOLD}3. Team knowledge sync?${NC}"
    echo -e "     ${DIM}Share patterns and decisions across your team via S3.${NC}"
    echo -e "     ${DIM}Each team member runs Kernora locally; S3 is the shared brain.${NC}"
    echo ""
    echo -e "     ${GREEN}1${NC}) Connect S3 bucket     ${DIM}→ team sync (needs AWS credentials)${NC}"
    echo -e "     ${GREEN}2${NC}) Solo mode              ${DIM}→ just me, no sync (default)${NC}"
    echo ""
    echo -ne "     Choice [2]: "
    read -r TEAM_CHOICE
    TEAM_CHOICE="${TEAM_CHOICE:-2}"

    S3_BUCKET=""
    S3_REGION=""
    AWS_ACCESS=""
    AWS_SECRET=""
    if [ "$TEAM_CHOICE" = "1" ]; then
        echo ""
        echo -ne "     S3 bucket name: "
        read -r S3_BUCKET
        echo -ne "     AWS region [us-east-1]: "
        read -r S3_REGION
        S3_REGION="${S3_REGION:-us-east-1}"

        # Check for AWS credentials in env or ~/.aws
        if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
            ok "Found AWS credentials in environment"
            AWS_ACCESS="${AWS_ACCESS_KEY_ID}"
            AWS_SECRET="${AWS_SECRET_ACCESS_KEY}"
        elif [ -f "$HOME/.aws/credentials" ]; then
            ok "Found AWS credentials at ~/.aws/credentials"
            info "Kernora will use your default AWS profile"
        else
            echo ""
            echo -ne "     AWS Access Key ID: "
            read -r AWS_ACCESS
            echo -ne "     AWS Secret Access Key ${DIM}(hidden)${NC}: "
            read -r -s AWS_SECRET
            echo ""
        fi

        if [ -n "$S3_BUCKET" ]; then
            ok "Team sync: s3://$S3_BUCKET ($S3_REGION)"
        else
            warn "No bucket provided — skipping team sync"
            TEAM_CHOICE="2"
        fi
    fi

    # ── Write config.toml ────────────────────────────────────────────────────
    echo ""
    info "Writing configuration..."

    cat > "$KERNORA_HOME/config.toml" << TOML
# Kernora — AI Work Intelligence
# Generated by get-kernora.sh on $(date '+%Y-%m-%d %H:%M')
# Edit anytime: ~/.kernora/config.toml

[mode]
type = "byok"

[keys]
# API keys for LLM analysis. More keys = better model selection.
TOML

    # Write the key that was provided
    if [ -n "$API_KEY_VAL" ] && [ -n "$API_KEY_VAR" ]; then
        echo "$API_KEY_VAR = \"$API_KEY_VAL\"" >> "$KERNORA_HOME/config.toml"
    fi
    # Also capture any env keys the user already has
    [ -n "${ANTHROPIC_API_KEY:-}" ] && [ "$API_KEY_VAR" != "anthropic" ] && \
        echo "anthropic = \"${ANTHROPIC_API_KEY}\"" >> "$KERNORA_HOME/config.toml"
    [ -n "${GEMINI_API_KEY:-}" ] && [ "$API_KEY_VAR" != "gemini" ] && \
        echo "gemini = \"${GEMINI_API_KEY}\"" >> "$KERNORA_HOME/config.toml"
    [ -n "${OPENAI_API_KEY:-}" ] && [ "$API_KEY_VAR" != "openai" ] && \
        echo "openai = \"${OPENAI_API_KEY}\"" >> "$KERNORA_HOME/config.toml"
    [ -n "${XAI_API_KEY:-}" ] && [ "$API_KEY_VAR" != "xai" ] && \
        echo "xai = \"${XAI_API_KEY}\"" >> "$KERNORA_HOME/config.toml"

    cat >> "$KERNORA_HOME/config.toml" << TOML

[model]
provider = "$PROVIDER"

[analysis]
run_every_minutes = 60

[dashboard]
port = 2742
auto_open = true

[privacy]
verified = true
TOML

    # Backup config
    if [ -n "$BACKUP_PATH" ]; then
        cat >> "$KERNORA_HOME/config.toml" << TOML

[backup]
enabled = true
path = "$BACKUP_PATH"
# Kernora copies echo.db here after every analysis run.
# Your cloud service (iCloud/Dropbox/etc.) handles the sync.
TOML
    fi

    # Team/S3 config
    if [ "$TEAM_CHOICE" = "1" ] && [ -n "$S3_BUCKET" ]; then
        cat >> "$KERNORA_HOME/config.toml" << TOML

[swarm]
type = "byok_s3"
bucket = "$S3_BUCKET"
region = "$S3_REGION"

[aws]
access_key = "$AWS_ACCESS"
secret_key = "$AWS_SECRET"
TOML
    fi

    ok "Config written to ~/.kernora/config.toml"

    echo ""
    echo -e "  ┌──────────────────────────────────────────────────────────────────┐"
    echo -e "  │  ${GREEN}Setup complete!${NC} Installing Kernora...                          │"
    echo -e "  └──────────────────────────────────────────────────────────────────┘"
    echo ""

else
    info "Config exists — keeping ~/.kernora/config.toml (delete it to re-run wizard)"
fi

# ── 7. Run the real installer ────────────────────────────────────────────────
info "Running setup..."
cd "$KERNORA_APP"
bash install.sh

# ── 8. Set up backup cron (if backup path configured) ────────────────────────
if [ -n "$BACKUP_PATH" ] && [ -d "$BACKUP_PATH" ]; then
    # Create a backup script
    cat > "$KERNORA_HOME/backup.sh" << BSCRIPT
#!/bin/bash
# Kernora knowledge backup — copies echo.db to sync folder
SRC="$KERNORA_HOME/echo.db"
DST="$BACKUP_PATH/echo.db"
if [ -f "\$SRC" ]; then
    cp "\$SRC" "\$DST"
fi
BSCRIPT
    chmod +x "$KERNORA_HOME/backup.sh"

    # On macOS, add a LaunchAgent for hourly backup
    if [ "$OS" = "Darwin" ]; then
        cat > "$HOME/Library/LaunchAgents/ai.kernora.backup.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.kernora.backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$KERNORA_HOME/backup.sh</string>
  </array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
PLIST
        launchctl load "$HOME/Library/LaunchAgents/ai.kernora.backup.plist" 2>/dev/null || true
        ok "Hourly backup to $BACKUP_PATH"
    fi
fi

# ── 9. Create `kernora` CLI command ──────────────────────────────────────────
KERNORA_BIN="$KERNORA_APP/cli.py"
WRAPPER="$KERNORA_HOME/kernora"

cat > "$WRAPPER" << SCRIPT
#!/bin/bash
# Kernora CLI wrapper — auto-generated by get-kernora.sh
exec "$PYTHON" "$KERNORA_APP/cli.py" "\$@"
SCRIPT
chmod +x "$WRAPPER"

# Also create `nora` alias — shorter, friendlier, same thing
NORA_WRAPPER="$KERNORA_HOME/nora"
cat > "$NORA_WRAPPER" << SCRIPT
#!/bin/bash
# Nora CLI — alias for kernora. Same thing, fewer keystrokes.
exec "$PYTHON" "$KERNORA_APP/cli.py" "\$@"
SCRIPT
chmod +x "$NORA_WRAPPER"

# Symlink both `kernora` and `nora` into PATH
if [ -w "$BIN_DIR" ]; then
    ln -sf "$WRAPPER" "$BIN_DIR/kernora"
    ln -sf "$NORA_WRAPPER" "$BIN_DIR/nora"
    ok "CLI available: kernora (or just nora)"
elif sudo ln -sf "$WRAPPER" "$BIN_DIR/kernora" 2>/dev/null && \
     sudo ln -sf "$NORA_WRAPPER" "$BIN_DIR/nora" 2>/dev/null; then
    ok "CLI available: kernora / nora (used sudo for /usr/local/bin)"
else
    warn "Could not symlink to $BIN_DIR. Add this to your PATH:"
    echo "    export PATH=\"\$HOME/.kernora:\$PATH\""
    # Add to shell profile as fallback
    SHELL_RC=""
    [ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"
    [ -f "$HOME/.bashrc" ] && SHELL_RC="$HOME/.bashrc"
    if [ -n "$SHELL_RC" ] && ! grep -q 'kernora' "$SHELL_RC" 2>/dev/null; then
        echo 'export PATH="$HOME/.kernora:$PATH"' >> "$SHELL_RC"
        ok "Added to $SHELL_RC — restart your terminal or: source $SHELL_RC"
    fi
fi

# ── 10. Open dashboard ──────────────────────────────────────────────────────
sleep 1
if curl -sf http://localhost:2742 > /dev/null 2>&1; then
    if [ "$OS" = "Darwin" ]; then
        open "http://localhost:2742" 2>/dev/null || true
    fi
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ┌─ ${GREEN}Nora is ready${NC} ───────────────────────────────────────────────┐"
echo "  │                                                                   │"
echo "  │  Dashboard   →  http://localhost:2742                            │"
echo "  │  CLI         →  nora --help  (or kernora --help)                 │"
echo "  │  Config      →  ~/.kernora/config.toml                          │"
echo "  │  Update      →  curl -fsSL https://kernora.ai/install | bash    │"
echo "  │  Uninstall   →  bash ~/.kernora/app/uninstall.sh                │"
echo "  │                                                                   │"
echo "  └───────────────────────────────────────────────────────────────────┘"
echo ""
echo -e "  ${CYAN}Quick start — just use Claude normally. Nora watches silently:${NC}"
echo ""
echo "  Claude Code:    claude → code → /exit → Nora captures the session"
echo "  Cowork:         Automatic. Check localhost:2742 for Nora's learnings."
echo ""
echo "  CLI commands (use nora or kernora — same thing):"
echo "    nora status           Daemon status, DB size, session counts"
echo "    nora kiq              Knowledge Intelligence Quotient score"
echo "    nora search <q>       Search patterns, decisions, bugs"
echo "    nora bugs             Top bugs by recurrence"
echo "    nora patterns         Top patterns by effectiveness"
echo "    nora decisions        Recent architectural decisions"
echo "    nora savings          Token savings from memory injection"
echo ""
