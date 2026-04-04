---
description: Validates agent execution scopes to prevent hallucinated massive refactors
---

CRITICAL REQUIREMENT:
Before you execute ANY file modification tools (e.g., write_to_file, multi_replace_file_content) based on a new USER_REQUEST, you MUST execute the `kernora_prompt_interception` tool with your planned approach.
If the tool returns a 'Decompose' or 'Constraint' warning, you MUST update your plan immediately and query the user for confirmation via `notify_user` before proceeding.