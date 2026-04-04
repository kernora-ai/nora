---
name: dashboard
description: >
  Open the Kernora AI Work Intelligence Control Plane dashboard in the browser. 
  Use when the user types /kernora:dashboard, asks to "see my ROI", "open kernora", 
  or "open localhost 2742".
---

Open the Kernora Agent Control Plane at http://localhost:2742.

Steps:
1. Check if dashboard is reachable: `curl -sf http://localhost:2742/health`
2. If reachable: open in browser
   - macOS: `open http://localhost:2742`
   - Linux: `xdg-open http://localhost:2742`
3. If not reachable: start the telemetry daemon first
   `python3 ~/.kernora-engine/dashboard.py &`
   Wait 3 seconds, then open.

Tell the user:
"Opening Kernora AI Work Intelligence Control Plane at localhost:2742"
