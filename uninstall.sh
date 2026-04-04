#!/bin/bash
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE

echo ""
echo "◎  Kernora — uninstalling"
echo ""

# Stop LaunchAgents (macOS)
launchctl unload ~/Library/LaunchAgents/ai.kernora.daemon.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/ai.kernora.dashboard.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/ai.kernora.daemon.plist
rm -f ~/Library/LaunchAgents/ai.kernora.dashboard.plist
echo "✓ LaunchAgents removed"

# Stop background processes (Linux)
[ -f ~/.kernora/daemon.pid ] && kill "$(cat ~/.kernora/daemon.pid)" 2>/dev/null || true
pkill -f "kernora/dashboard.py" 2>/dev/null || true

# Remove hook
rm -f ~/.claude/hooks/kernora_hook.py
echo "✓ Hook removed"

echo ""
echo "  Your data at ~/.kernora/ was NOT deleted."
echo "  To also remove all data: rm -rf ~/.kernora"
echo ""
echo "✓ Kernora uninstalled."
echo ""
