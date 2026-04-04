# Kernora Global Agent Rules

## SDLC Hot-Reload Constraint
Whenever you modify frontend Python routing, dashboard structures, SQL logic, or any visual components belonging to `dashboard.py` within `~/code/kernora/`, **you must rebuild the payload**.

**Trigger:** "UI edits", "python saves in frontend root", "HTMX routing".
**Instruction:** Run `bash sync.sh` or `npm run watch:py` to properly build and reboot the local `~/.kernora/app/` payload. Do NOT directly `cp` files into the `~/.kernora/` hidden directory manually.
