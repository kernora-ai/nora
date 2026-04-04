# PRFAQ: Kernora Universal Agent Control Planes

## Press Release
**San Francisco, CA — Kernora Launches Universal "Agent Control Planes" to Stop AI Hallucinations Before They Start**
Today, Kernora announces the release of two native architectural tools designed to catch, analyze, and optimize developer prompts *before* they are sent to AI coding agents like Cursor, Roo Code, and Claude CLI. 
Instead of developers wasting hours debugging code hallucinated from a vague prompt, Kernora’s new Model Context Protocol (MCP) Server and Native CLI Hooks sit silently in the background, pausing execution locally when a developer’s request is too broad, risky, or architecturally unsafe.

"We fundamentally believe the highest ROI in AI engineering isn't a better model; it's a better human prompt," said Mihir, Architect at Kernora. "By intercepting bad prompts at the terminal layer, we are literally preventing billions of logic errors per year."

## Smooth End-User Experience (Least Friction)
We designed the Agent Control Planes to be completely invisible until you make a mistake.
1. **For GUI IDEs (Roo Code / Cursor / Kiro):** You drop a single JSON snippet into your MCP configuration pointing to `kernora_mcp.py`. The IDE agent autonomously pings the tool in the background. You never leave your editor interface. If you type *"Refactor the whole database"*, the chat simply replies: *"Kernora Control Plane: Scope too large. Please decompose."*
2. **For Headless CLIs (Claude Code):** You run one command to inject `/bin/cli_shield.py` into your `~/.claude/settings.json` lifecycle hooks. It operates with zero latency. If you accidentally attempt to modify a protected `auth/` directory, your terminal immediately halts with a red `[Kernora Control Plane]` warning before spending a single token.

## Market Assessment
*   **TAM (Total Addressable Market):** 5-10 Million Daily Active Agent Users by 2027.
*   **The Pain Point:** "Context Collapse" and "Token Fatigue." Engineers frequently trust autonomous agents with massive scopes and end up spending 5x the time unwinding the resulting spaghetti code. 
*   **The Competitors (Langfuse, Datadog):** They only observe the *output* limits. Kernora is the only tool preventing bad *input* actively at the developer's execution layer without requiring a proxy API hack.
*   **Enterprise Valuation:** Catching just one architectural regression before it merges saves a company roughly $2,000 in QA and incident response time. Charging $50/user/mo is highly elastic.

## Detailed Tech Spec

### Component 1: `kernora_mcp.py` (Local IDE Guardrail)
*   **Protocol:** Model Context Protocol (MCP) JSON-RPC over `stdio`.
*   **Registered Tool:** `kernora_scope_validation(intent: string)`.
*   **Logic:** Reads standard input for the `tools/call` JSON-RPC method. Extracts the `intent` argument. Executes a rapid static heuristic (Regex matching words like "rewrite everything", "refactor all"). Returns an MCP-compliant markdown payload rejecting the scope if the heuristic fails.

### Component 2: `cli_shield.py` & Native Slash Orchestrator
*   **Protocol:** OS-Level hooks and CLI Standard Input manipulation (`/todos`, `/compact`, `/plan`).
*   **Logic:** Executes exactly at the `OnSpecGenerated` lifecycle point. If a developer prompt fails the Kernora architecture evaluation block (e.g., scoping is too massive), Kernora does not just kill the process. It programmatically injects the `/compact` command to summarize the context (saving tokens), switches Kiro to the `/plan` agent, and automatically pipes the decomposed batch plan into Kiro's native `/todos` tracking system.
*   **Exit Conditions:** Converts monolithic failures into elegant, trackable ToDo lists directly inside the terminal.

### Component 3: Kiro IDE Webview Package (`.vsix`)
*   **Protocol:** VS Code / OpenVSX Extension API (`WebviewViewProvider`).
*   **Logic:** Acts as the "smooth end-user" interface. Delivers a native Sidebar pane directly inside Kiro Desktop embedding `http://localhost:2742` via an `iframe`. 
*   **Distribution:** Packaged into a standalone `.vsix` file allowing instant local installation in Kiro on Mac, completely bypassing the browser.
