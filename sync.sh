#!/bin/bash
# sync.sh - Kernora Development Hot-Reloader
# Usage: Run this script directly, or use `npm run watch:py` from kiro-extension/

cd "$(dirname "$0")"

echo "[Sync] Copying tracking source..."
for f in *.py; do
  if [ -f "$f" ] && [ "$f" != "dashboard_installed.py" ]; then
    cp "$f" kiro-extension/bundled/
  fi
done
cp -r .skills/* kiro-extension/skills/ 2>/dev/null || true

echo "[Sync] Deploying to ~/.kernora/app/..."
cp kiro-extension/bundled/*.py ~/.kernora/app/
cp -r kiro-extension/skills/* ~/.kernora/skills/ 2>/dev/null || true

echo "[Sync] Restarting dashboard daemon..."
pkill -f "dashboard.py" 2>/dev/null || true
lsof -ti:2742 | xargs kill -9 2>/dev/null || true
sleep 1

export KERNORA_IDE=vscode
nohup ~/.kernora/venv/bin/python3 ~/.kernora/app/dashboard.py > ~/.kernora/logs/dashboard.out.log 2> ~/.kernora/logs/dashboard.err.log &

echo "[Sync] Hot-reload complete. Dashboard running on localhost:2742"
