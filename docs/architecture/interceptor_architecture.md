# Architecture: Multi-Surface Pre-Flight Prompt Interceptor

To successfully intercept user prompts *before* they result in expensive, hallucinated LLM generation, Kernora cannot rely on post-session log trailing. It must shift from an **Observer** to a **Proxy Layer**. 

Here is the "Build Architecture" breakdown for implementing zero-latency prompt interception across five distinct AI surfaces.

---

### Core Component: The Local Proxy API
At its core, Kernora transitions from just reading `sqlite` to running a local API proxy (`http://localhost:2742/v1`). Instead of connecting these tools directly to Anthropic/OpenAI servers, the user configures their tool's "Base URL" to point to Kernora. Kernora catches the payload, inspects the prompt, and either forwards it to the real LLM or instantly returns a simulated "assistant" response containing the optimization choices.

---

### 1. Claude Code (CLI)
**The Problem:** The user types a massive refactor command in their terminal, or the agent hallucinates an edit to a locked architectural file.
**The Architecture:** 
*   **Native Lifecycle Hooks:** We completely bypass local proxies alias hacks. Claude Code natively supports HTTP hooks directly inside `~/.claude/settings.json`. 
    *   **Prompt Control Plane (`UserPromptSubmit`):** We register an HTTP hook here. Before Claude processes the raw prompt, the payload hits Kernora. Kernora evaluates the scope and returns a blocked status if vague, natively forcing the CLI to halt and display: *"Kernora Warning: Scope too large. Please decompose."*
    *   **Read-Only Guardrails (`PreToolUse`):** If the agent attempts to execute a file-write tool on a locked core module, Kernora interrupts the agent mid-flight deterministically and forces a human override.

### 2. Claude Chat (Web Interface)
**The Problem:** The user is typing in `claude.ai` and doesn't have local CLI access.
**The Architecture:**
*   **Component:** Kernora Browser Extension (Manifest V3).
*   **Data Flow:** A content script attaches an `addEventListener('keydown', handleEnter)` onto the Claude Chat input box. When the user hits Enter, the event propagation is `preventDefault()`.
*   **Action:** The extension sends the prompt to the Kernora Local Daemon. If it detects vagueness, it renders a floating UI overlay directly inside the browser above the chatbox: *"Optimize this prompt for Next.js constraints before sending?"*

### 3. Claude Co-work (Shared Workspace)
**The Problem:** A developer tags the Co-work agent in a pull request or shared markdown file with a massive, unconstrained task.
**The Architecture:**
*   **Component:** An asynchronous Middleware Webhook Layer.
*   **Data Flow:** Co-work operates in an async, multiplayer environment. When User A pushes a prompt to the Co-work backend, a pre-flight webhook fires to the Kernora Enterprise Cloud Router. 
*   **Action:** Kernora evaluates the repo's knowledge base. Before the Co-work agent spins up compute instances, Kernora replies to the thread: *"This request touches 5 locked microservices. I have decomposed this into Batch A and Batch B. Click to authorize Batch A."*

### 4. Antigravity (Advanced Agentic Systems)
**The Problem:** High-autonomy agents like Antigravity receive a single `USER_REQUEST` string and dictate their own tool execution loops.
**The Architecture:**
*   **Component:** A mandatory `prompt_interception` tool added to the Agent's system prompt schema.
*   **Data Flow:** Instead of a proxy, the architecture relies on System Instructions. The agent is strictly commanded: *"CRITICAL INSTRUCTION: Before executing ANY file modification tools based on a new USER_REQUEST, you MUST call the `prompt_interception` tool with your planned approach."* 
*   **Action:** The tool parses the agent's intent. If the agent plans to modify 14 files at once, the tool forces an error block: *"Reject: Scope too large. Decompose your plan."*

### 5. Xcode Claude Panel (IDE Extensions)
**The Problem:** Copilot or Claude IDE panels have zero knowledge of deep architectural conventions outside of the currently open tabs.
**The Architecture:**
*   **Component:** Language Server Protocol (LSP) Middleware or Custom Base URL.
*   **Data Flow:** Most IDE extensions (like Cursor or Xcode plugins) allow setting a generic OpenAI-compatible Base URL payload. Kernora hooks into the IDE on `localhost:2742`.
*   **Action:** When the user highlights 3 functions in Xcode and hits `CMD+K -> "Refactor"`, the payload hits Kernora. Kernora instantly returns a synthetic UI stream back to the Xcode panel: *"[Kernora Control Plane] - You are refactoring a core UI component, but you did not include the Design System tokens file in your context. Click to attach it."*

---

### V2 Bottlenecks & Tradeoffs
1. **Latency:** Putting a proxy between the developer and the LLM can introduce 200-400ms of lag if Kernora has to parse heavy Regex or local LLM checks. **Solution:** The interceptor must run instantaneous static heuristic checks (word count, keyword matching) before relying on a local LLM for deeper analysis.
2. **Context Truncation:** IDEs often send 20,000 tokens of background context alongside the prompt. Kernora's proxy must swiftly ignore the background files and isolate the `role: user` prompt text for evaluation without crashing.
