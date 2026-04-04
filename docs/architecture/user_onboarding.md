# Kernora: End User Experience Guide

The ultimate goal of Kernora is frictionless acceleration. Developers do not need to learn a new syntax, change their IDE, or alter their workflow. They simply install the Control Plane, and it orchestrates their agents invisibly in the background.

---

## 1. Installation & Setup (The "1-Minute Onboarding")

**Step 1: Ignite the Kernora Engine**
Open any standard Mac terminal and turn the engine on. This spins up the local SQLite intelligence database and the Model Context Protocol (MCP) server.
```bash
$ source ~/code/kernora/venv/bin/activate
$ python3 ~/code/kernora/dashboard.py
```

**Step 2: Install the UI Panel**
Open your AWS Kiro IDE (or Cursor/VS Code).
Navigate to the **Extensions view** (`Cmd+Shift+X`).
Click the `...` menu -> **"Install from VSIX..."**
Select `kernora-1.0.0.vsix`. A clean "Kernora" tracking icon immediately pops onto your left-hand Activity Bar.

**Step 3: Register the MCP Intel Node**
In Kiro, open your Configuration/Settings JSON and register Kernora as a foundational Tool so the internal agents can fetch advanced skills natively.
```json
"mcpServers": {
  "kernora": {
    "command": "python3",
    "args": ["/Users/mihirchoudhary/code/kernora/kernora_mcp.py"]
  }
}
```
*Setup Complete. You never have to touch config files again.*

---

## 2. Daily Usage (The "10x Accelerator")

**Scenario:** You are building a complex Next.js application.

1. **The Abstract Prompt:** You open the Kiro Agent chat and type: *"Rewrite the entire authentication flow from scratch to use standard JWTs, and delete the old database schema."*
2. **The Intelligence Node (Zero-Friction):** You hit enter. Before Kiro spends a single penny of your Anthropic API tokens generating a hallucinated loop, Kiro's background engine automatically queries the Kernora MCP Server.
3. **The Executive Optimization:** The Kernora MCP statically evaluates the monolithic intent. Recognizing that this will result in massive code churn, Kernora autonomously intercepts the request.
4. **Auto-Orchestration:** Kiro autonomously pauses the generation loop. It renders Kernora's Markdown optimization directly into your Kiro Chat panel:
   > 🛑 **[Kernora Control Plane]** Monolithic Spec Optimization Triggered.
   > Detected massive architectural directive. Decomposing your intent into safe batches to prevent AI hallucination and speed up generation.
5. **Auto-Batched Recovery:** Kernora uses Slash Command Orchestration to automatically inject the `/compact` command, saving your 30k token window, and dynamically injects the proprietary Corporate Skill [Enterprise NextAuth Sync] directly into the agent's buffer execution plan.
6. **The Executive Sidebar Review:** You click the Kernora Intelligence Core icon in your Kiro Activity Bar. The webview pane slides open and displays your live productivity multiplier:
   - **Pre-Flight Optimizations:** `1`
   - **Tokens Saved:** `32,500` ($0.10 saved instantly)
   - **Nora Skills Executed:** `1`

**Result:** The developer never had to alt-tab to a browser. Kernora sat invisibly in the background until the exact microsecond the developer needed architectural context, forcefully optimized the prompt, and documented the financial ROI seamlessly into the IDE sidebar.
