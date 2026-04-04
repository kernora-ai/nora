---
name: insights
description: >
  Fetch the Distilled Corporate AI Skills from the Kernora Control Plane.
  Use when the user asks "How do we do auth?", "Check corporate skills", 
  or "Fetch company methodologies".
---

Fetch the current repository's Architectural Judgement rules.

Steps:
1. Run the local Control Plane query: `python3 ~/.kernora-engine/cli_shield.py "/kernora skills"`
2. Read the standard output from the execution.
3. Automatically append the exact Methodology parameters retrieved from the output to your execution plan before writing code.

Tell the user:
"I have successfully pulled the Principal Engineer guidelines from the Kernora Control Plane and injected them into my context window."
