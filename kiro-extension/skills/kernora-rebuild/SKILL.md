---
name: kernora-rebuild
description: "Complete nuke-and-rebuild of the Kernora extension. Handles EVERYTHING: kill processes, wipe state, build VSIX, register hooks, verify. Incorporates strict SDLC guards to prevent data loss."
---

# Kernora Rebuild — Complete Nuke & Rebuild Pipeline

Full pipeline for completely rebuilding the Kernora extension payload and VSIX.

> [!CAUTION]
> **Data Loss Vector:** This command performs a destructive `rm -rf ~/.kernora/app`. 
> If you have been conducting "live development" directly inside `~/.kernora/app/` instead of `~/code/kernora/`, **ALL UNCOMMITTED CHANGES WILL BE PERMANENTLY DELETED**.

## Modern SDLC Workflow (v2.0.3+)
**Rule #1:** ALL development must happen natively inside `~/code/kernora/`.
**Rule #2:** NEVER manually edit files in `~/.kernora/app/`.

### Live Development (Hot Reloading)
Instead of running this heavy rebuild command during UI/Python dev, run the watcher:
```bash
bash sync.sh
```
Or via NPM:
```json
npm run watch:py
```
This instantly syncs `~/code/kernora/*.py` directly into both `bundled/` and the live `~/.kernora/app/` target, giving you instant IDE-native hot-reloads.

---

## One-Block Rebuild Command

Paste this in your Mac terminal at your repository root (`~/code/kernora/`). It does everything:

```bash
cd ~/code/kernora \
  && pkill -f "kernora.*dashboard.py" 2>/dev/null; pkill -f "kernora.*daemon" 2>/dev/null \
  ; launchctl unload ~/Library/LaunchAgents/ai.kernora.daemon.plist 2>/dev/null \
  ; launchctl unload ~/Library/LaunchAgents/ai.kernora.dashboard.plist 2>/dev/null \
  ; rm -rf ~/.kernora/app ~/.kernora/echo.db ~/.kernora/logs ~/.kernora/spool ~/.kernora/dashboard.pid ~/.kernora/skills \
  ; (rm -f ~/.kiro/steering/nora-*.md 2>/dev/null; rm -f ~/.kiro/steering/kernora-*.md 2>/dev/null; rm -f ~/.kiro/hooks/nora_*.py 2>/dev/null; rm -f ~/.claude/hooks/nora_*.py 2>/dev/null; rm -f ~/.claude/hooks/kernora_*.py 2>/dev/null; true) \
  && echo "Syncing root files to bundle..." \
  && for f in *.py; do [ -f "$f" ] && [ "$f" != "dashboard_installed.py" ] && cp "$f" kiro-extension/bundled/; done \
  && cp -r .skills/* kiro-extension/skills/ 2>/dev/null; true \
  && echo "Building native Swift inferencer..." \
  && cd ~/code/kernora/kernora-native-mac && swift build -c release \
  && cd ~/code/kernora/kiro-extension && rm -f *.vsix && npm run compile && npx vsce package --allow-missing-repository \
  && kiro --uninstall-extension kernora.kernora 2>/dev/null; true \
  && cd ~/code/kernora && bash install.sh
```

### Key Differences in Modernization:
- Absolute paths are strictly confined to `~/code/kernora` (abandoned `kernora-old` references).
- The glob `for` loop dynamically captures all `*.py` files, significantly reducing drift omissions for newly added tools/hooks without exhausting rigid filename lists.
- Acknowledges the explicit `dashboard_installed.py` root exception.
- Standardizes the `rm -f` wrapper array block for idempotent shell safety.

## Verification After Rebuild

```bash
# 1. Check hooks registered (Kiro)
python3 -c "
import json
s = json.load(open('$HOME/.kiro/settings.json'))
hooks = s.get('hooks', {})
for h in ['userPromptSubmit','agentSpawn','preToolUse','postToolUse','stop']:
    found = any('nora' in str(e) for e in hooks.get(h, []))
    print(f'  {chr(10003) if found else chr(10007)} {h}')
" 2>/dev/null || echo "  ✗ Could not parse ~/.kiro/settings.json"

# 2. Check dashboard startup
curl -sf http://localhost:2742/health 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'  ✓ Dashboard: {d[\"status\"]}  Sessions: {d[\"sessions\"]}')
" 2>/dev/null || echo "  ✗ Dashboard not responding"
```
