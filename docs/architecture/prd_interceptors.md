# PRD: Kernora Prompt Interceptors

**Working Backwards (The Persona):** 
*Mihir (Staff Engineer)* hits `CMD+K` in Cursor and types *"refactor the entire auth flow based on our new DB schema"*. Instead of watching the agent blindly rewrite 15 files and break production, the IDE instantly blinks: *"Kernora Control Plane: This request bridges critical microservices. Stripping this down into Batch 1 (Database) and Batch 2 (API). Proceed with Batch 1?"* Mihir clicks Yes, and watches the error rate drop to zero.

Here is the precise execution roadmap, designed in executable batches for AI agents.

---

## 1. Claude Code CLI Implementation
**Theme:** Native CLI Guardrails  
**Phase:** Core Terminal Safety  

### Batch 1.1: The Prompt Control Plane (`UserPromptSubmit`)
* **Goal:** Block vague/large prompts before Claude processes them.
* **Agent Executable Prompt:** 
  > *"Modify `~/.claude/settings.json`. Add a `commands` hook targeting the `UserPromptSubmit` lifecycle event. The hook must execute the local script `~/.kernora/cli_shield.py`. Pass the raw prompt as an argument. If the python script exits with code `1`, halt execution."*
* **Test:** Type `claude "rewrite everything"`. Expect CLI to instantly reject the input with a Kernora message.

### Batch 1.2: The Read-Only Firewall (`PreToolUse`)
* **Goal:** Protect locked architectural files from rogue agent edits.
* **Agent Executable Prompt:** 
  > *"Update `~/.claude/settings.json` to add a `PreToolUse` hook. Listen for the `GlobReplace` and `Bash` tools. If the `args.path` targets `/config/` or `/auth/`, the hook must trigger an HTTP request to `localhost:2742/auth_check`. Block execution pending Kernora dashboard approval."*
* **Test:** Ask Claude Code to delete the `config.toml` file. Expect the tool use to suspend immediately.

---

## 2. Antigravity Implementation
**Theme:** Agentic Confinement  
**Phase:** Autonomous Safety  

### Batch 2.1: The System Constraints
* **Goal:** Force the agent to validate its intention before executing any `write_to_file` tool.
* **Agent Executable Prompt:** 
  > *"Access the core Antigravity System Prompt text block. Inject a `CRITICAL REQUIREMENT` header that explicitly states: 'You must pass your planned file modifications to the `kernora_prompt_interception` tool BEFORE executing any code writing tools. Failure to do so is a strict system violation.'"*
* **Test:** Provide the agent a massive prompt. Verify the first tool called is the interception tool, not a file editor.

### Batch 2.2: The Validation Tool Schema
* **Goal:** Return actionable decomposition advice to the agent.
* **Agent Executable Prompt:** 
  > *"Write a Python backend function `def handle_prompt_interception(payload):`. Parse `planned_files_to_touch` from the JSON payload. If the list length > 5, return `{'status': 'REJECTED', 'message': 'Decompose into 3 batches.'}`. Ensure this schema is registered in the Antigravity OS tools list."*
* **Test:** The agent submits 8 files to the tool. Verify the tool returns `REJECTED` and the agent successfully updates its internal plan to a 3-file batch.

---

## 3. Cursor / Grok / OpenAI Implementation
**Theme:** Universal IDE Middleware  
**Phase:** Market Capture  

### Batch 3.1: The Local Proxy Interceptor
* **Goal:** Catch raw `/v1/chat/completions` API calls originating from outside the CLI.
* **Agent Executable Prompt:** 
  > *"Spin up a robust FastAPI server on port 2743. Create a listener for `POST /v1/chat/completions`. Parse the incoming OpenAI-format JSON. Identify the last `role: user` message. If `len(split(message))` < 10, do not proxy to OpenAI. Instead, stream back a 200 OK JSON response containing a synthetic assistant message offering optimization choices."*
* **Test:** Point Cursor's 'Custom Base URL' to `http://localhost:2743/v1`. Hit `CMD+K` and type a 3-word prompt. Expect Cursor's UI to instantly render the synthetic Kernora rejection text.

### Batch 3.2: The Deep Context Passthrough
* **Goal:** If the prompt passes initial checks, smoothly proxy traffic out to the internet without breaking IDE streaming.
* **Agent Executable Prompt:** 
  > *"Update the FastAPI server `interceptor_proxy.py`. Import `litellm`. If the prompt passes static heuristic checks, forward the exact incoming payload directly to `litellm.completion(..., stream=True)`. Map the streaming chunks natively back through FastAPI's `StreamingResponse` so the IDE UI renders character-by-character fluidly."*
* **Test:** Point Cursor to `localhost:2743/v1`. Input a well-constrained prompt. Expect Cursor to generate valid, streaming code exactly as if it were connected directly to Anthropic/OpenAI.

---

## 4. Xcode Claude Panel Implementation
**Theme:** Apple Ecosystem Guardrails  
**Phase:** Native IDE Confinement  

### Batch 4.1: The Custom Source Extension Proxy
* **Goal:** Create a bridge between Xcode's Source Editor Extension API and the local Kernora daemon.
* **Agent Executable Prompt:** 
  > *"Configure the Xcode Claude Extension preferences. Locate the 'Custom API Override' or 'Enterprise Base URL' setting. Set it to `http://localhost:2743/v1_xcode`. Update the FastAPI proxy to detect strings coming from the Xcode payload. Xcode often sends the entire active document text alongside the prompt. Mute the context payload during heuristic checks to prevent false 'Scope Decomposition' triggers on large files."*
* **Test:** Highlight 300 lines of Swift code in Xcode. Ask the Xcode Claude Panel to "Refactor to use Protocol Oriented Programming". Verify the proxy successfully masks the 300-line context block and evaluates purely the 7-word refactor prompt.

### Batch 4.2: Synthetic UI Streams within Xcode
* **Goal:** Display native-feeling warning UI elements inside Xcode's Claude panel using markdown injections.
* **Agent Executable Prompt:** 
  > *"Update the FastAPI Xcode HTTP response function. When returning a rejection payload to Xcode, wrap the markdown in a macOS-native visual style using Swift-compatible syntax highlighting or emojis. Example output: `> 🛑 **Kernora Checkpoint**\n> This requires touching SceneDelegate which is locked. Approve override?`"*
* **Test:** Trigger a rejection in Xcode. Verify the output text inside the Xcode panel formats cleanly as a distinct system warning rather than looking like hallucinated code.

---

## 5. Roo Code Implementation
**Theme:** Model Context Protocol (MCP) Guardrails  
**Phase:** Autonomous IDE Confinement  

### Batch 5.1: The Kernora MCP Server
* **Goal:** Expose Kernora's interception logic as a native tool via the Model Context Protocol, so Roo Code can interface with it directly without a proxy hack.
* **Agent Executable Prompt:** 
  > *"Build a lightweight MCP server using the official Python SDK. Register a single tool: `kernora_scope_validation(task_intent: str, files_to_edit: list)`. The tool must evaluate the payload length against project constraints and return a markdown string with either an Approval or a Decomposition Warning. Map the MCP server to run securely on an OS-level stdio transport."*
* **Test:** Start the Kernora MCP server. Configure Roo Code to connect to it via `roo_cline_mcp.json`. Use Roo Code's interface to manually call the `kernora_scope_validation` tool and verify it returns a valid markdown warning.

### Batch 5.2: Roo Code Custom Instructions Integration
* **Goal:** Force Roo Code's autonomous loop to always validate its plans through the Kernora MCP server before modifying the workspace.
* **Agent Executable Prompt:** 
  > *"Update the `.roo/custom_instructions.md` configuration file for the repository. Inject a high-priority system directive: `CRITICAL: You are connected to the Kernora MCP Server. Before you use the 'write_to_file' or 'replace_in_file' tools, you MUST first execute the 'kernora_scope_validation' tool with your execution plan. If the tool warns that the scope is too large, you must pause and request human permission before continuing.`"*
* **Test:** Ask Roo Code to "completely rewrite the database schema". Verify the agent autonomously queries the Kernora MCP tool first, receives the scope warning, and pauses the run to ask the developer for confirmation.

---

## 6. AWS Kiro Implementation
**Theme:** Enterprise Spec-Driven Safety  
**Phase:** Core Infrastructure Integration  

AWS Kiro heavily relies on "spec-driven development" and is uniquely split between a powerful headless CLI and a full GUI IDE. We must maximize interception capability natively for each surface.

### Batch 6.1: Kiro CLI (Max Functionality via Agent Hooks)
* **Goal:** Intercept the transition phase in the terminal *before* Kiro executes the code-writing agents.
* **Agent Executable Prompt:** 
  > *"Configure a Kiro Native Agent Hook listening for the `OnSpecGenerated` and `PreCommandExecute` lifecycle events. Map the hook to trigger the `kernora_cli_shield.py` script, passing the newly generated markdown spec as the payload. If Kernora detects that the spec instructs the agent to bypass AWS organizational security policies or write monolithic architecture, force exit with code `1` to halt the CLI execution flow and print the decomposition warning to `stdout`."*
* **Test:** Ask Kiro CLI to generate a spec for an insecure, monolithic auth system. Verify the Kernora hook blocks the agents from proceeding to the code-generation phase.

### Batch 6.2: Kiro IDE (Max Functionality via MCP)
* **Goal:** Use Kiro's MCP integration in the GUI to natively provide Kernora's scope validation tools, targeting active workspace edits and AWS infrastructure drift.
* **Agent Executable Prompt:** 
  > *"Register the Kernora MCP Server inside the Kiro IDE settings. Create the tool: `kernora_aws_drift_check(resources: list, files_to_edit: list)`. Inject a heavy System Directive telling the IDE agent that before it modifies any `cdk/` or `terraform/` directories, or alters enterprise IP, it must pass the resource list to Kernora. Kernora will check the AWS environment configuration and return a strict `Approved` or `Rejected: Requires Enterprise Architect Approval` status, rendering the block natively in the IDE chat side-panel."*
* **Test:** Prompt the Kiro IDE to spin up 5 new DynamoDB tables and an IAM role. Verify the IDE agent pauses, queries the Kernora MCP server *before* generating the IaC code, and renders the pause command natively in the chat interface.

### Batch 6.3: Native Slash Command Orchestration
* **Goal:** Leverage Kiro's internal slash commands (`/todos`, `/compact`, `/plan`) to gracefully handle intercept rejections and enforce architectural constraints automatically.
* **Agent Executable Prompt:**
  > *"Update the `kiro_spec_shield.py` logic. When Kernora detects a massive unconstrained spec, do not just `exit 1`. The script must programmatically output a string instructing Kiro to switch to the Plan agent (`/plan`). Kernora then parses the rejected request into three safe architectural steps, and pipes those steps natively into Kiro's `/todos` engine. Finally, if the context token analysis exceeds a custom threshold, the script must natively trigger the `/compact` command to save the developer token costs."*
* **Test:** Request a massive "Rewrite everything" app overhaul. Kernora intercepts it, switches Kiro to the `/plan` agent, triggers `/compact` to clear the massive 40k token window, and generates an automated `/todos` list containing [1. DB Schema, 2. API Routes, 3. UI].

### Batch 6.4: The Hybrid Webview Extension (.vsix)
* **Goal:** Deliver the ultimate "smooth end-user" experience by wrapping the local metrics dashboard inside a native Kiro IDE sidebar pane, operating synchronously with the MCP server.
* **Agent Executable Prompt:**
  > *"Initialize a standard VS Code extension using TypeScript. Define a `WebviewView` inside the `activitybar`. The Webview must render an iframe pointing to `http://localhost:2742`. Package the tool using `@vscode/vsce` into a portable `.vsix` binary. Ensure the extension operates strictly as a 'read-only' UI layer, deferring all operational interception to the resident Kernora MCP Server."*
* **Test:** Drag and drop `kernora-1.0.0.vsix` into Kiro Desktop. Click the Kernora Sidebar Icon. Verify the React token-burn metrics dashboard renders natively inside the IDE without breaking CSP rules.
