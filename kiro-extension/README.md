# Nora — grounding & verification for AI work

**Turn your rules, facts & standards into the rails your AI runs on.**

Nora captures decisions as cited factlets, keeps them current, and applies them in your AI tools — Claude Code, Cursor, Kiro, Claude Desktop, and Antigravity. Before the model writes, grounding injects the facts that govern the work. After it writes, verification checks the output against those same facts.

Built on the open [Factlet protocol](https://factlet.ai) — git-native, vendor-neutral, W3C PROV-O lineage.

## What this extension does (v2.8.1)

| Capability | What happens |
|---|---|
| **Grounding** | On relevant turns, Nora injects matching factlets from your project's factbook before the model answers. Citations show which fact was used. |
| **Point-of-action enforcement** | Pre-write MUST-NOT checks block tool calls that violate directive factlets (e.g. "MUST NOT hardcode founder-specific data") before they run. A post-output secret scanner warns when tool output accidentally prints secrets. |
| **Verification / reinforced trust** | Factlets carry a trust basis (`execution-proof`, `human-confirmed`, or `agent-asserted`). Reinforced / in-use state tracks citations that hold up in later work; `verified` stays reserved for execution proof or human confirmation. |
| **Directive factlets** | Factlets are actionable (do / do-not / check), not bare descriptions — so grounding and MUST-NOT enforcement have something to enforce. |

Same factbook everywhere. Switch tools; the rails stay.

## Install

### 1. Install the Kernora backend first

The desktop app and this extension expect the backend under `~/.kernora/`. Install it once per machine:

```bash
curl -fsSL https://kernora.ai/install | bash
```

That creates the local venv, registers MCP where it can, and installs session hooks. The desktop app will refuse to start until this step is done.

**Tiers (fail closed):** Free / Lite exposes **15 MCP tools**. Pro exposes the full surface (**62 MCP tools**). If Nora cannot prove your tier, it runs the 15-tool Lite surface — it never guesses upward. Call `nora_help` in chat to see what's active for you.

### 2. Install this extension

**VS Code:** Marketplace → search **Kernora**, or:

```bash
code --install-extension Kernora.kernora
```

**Cursor / Kiro:** side-load the same extension (Extensions → Install from VSIX), or install from the Marketplace where available.

**Claude Code / Claude Desktop:** the install script above registers Nora as a local MCP server. Restart the agent; factbook tools appear.

**First project:**

```bash
cd ~/code/your-project
kernora generate   # emit CLAUDE.md / .cursorrules / steering from the factbook
```

Open the project in your IDE. Grounding fires on relevant turns when a factbook exists (cold-start can seed candidates from the repo on first session).

Dashboard (optional): [http://localhost:2742](http://localhost:2742).

## Privacy — local-first, zero egress by default

- **0 bytes to Kernora servers.** Telemetry is off by default on every tier (v2.8).
- Free / Lite is local-stdio only. Pro+ can opt in to sync to **your** S3 (your bucket, your keys) — off by default.
- Data lives in `~/.kernora/` and `<project>/.nora/` on your machine.
- Verify: `kernora network-check` (AST audit of hot-path modules). Or run `tcpdump` yourself.

See [kernora.ai/security](https://kernora.ai/security.html).

## Measured (open methodology)

Without a factbook, three frontier models contradicted documented team decisions **12 times in 18 answers**. With one: **0 across 36**. Counted from published raw runs — [factlet-ai/evals](https://github.com/factlet-ai/evals) (N=6 tasks, 2026-05). Recount it yourself.

Grounding latency is hard-capped at **250ms** in the hook — over-budget lookups are skipped.

## Day-to-day commands

In IDE chat (MCP), start with:

| Say | What it does |
|---|---|
| `nora_help` | Lists the MCP tools active on your tier |
| `nora_search <query>` | Search patterns, decisions, bugs |
| `nora_factbook_view` | Show the active factbook |
| `nora_context_for_task <task>` | Pull relevant facts before you start work |
| `nora_generate` | Re-emit steering files from the factbook |

Shell: `kernora help`, `kernora tour`, `kernora network-check`.

## Links

- Website: [kernora.ai](https://kernora.ai)
- Docs: [kernora.ai/docs](https://kernora.ai/docs.html)
- Security: [kernora.ai/security](https://kernora.ai/security.html)
- Source: [github.com/kernora-ai/nora](https://github.com/kernora-ai/nora)
- Issues: [github.com/kernora-ai/nora/issues](https://github.com/kernora-ai/nora/issues)
