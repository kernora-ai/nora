---
name: prompt-coach
description: >
  Force Monolithic Prompt Decomposition. Triggered automatically by the Kernora Control Plane when a massive unconstrained Refactor is detected.
---

Orchestrate a massive refactor safely without hallucination loops.

Steps:
1. Acknowledge that the Kernora Control Plane blocked the previous monolithic prompt.
2. Immediately execute the `/compact` routine to clear the bloated context window.
3. Generate a Markdown plan breaking the original request into 3 strict, independent `/todos`.
4. Ask the user for permission to execute Todo #1.

Tell the user:
"Kernora Control Plane Intercept: Your request was too broad. I have compacted the context window and decomposed the execution into 3 safe batches. Proceed with Batch 1?"
