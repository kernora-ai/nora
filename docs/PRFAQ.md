# Kernora — Press Release & FAQ

---

## Developers Finally Have a Score for Their AI Effectiveness — And It Compounds

**Seattle, WA** — Kernora today introduces the **AI Leverage Score** — the first industry-standard metric for measuring how effectively a developer uses AI coding tools. Like a credit score for AI effectiveness, it ranges from 1.0x (baseline, no improvement over unassisted work) to 5.0x (elite, measurably transformative). It compounds over time. And it's finally answerable.

Kernora is the AI work intelligence layer that runs silently alongside developer AI tools — Claude Code, Cursor, Kiro — and turns every session into structured insight. When a session ends, Kernora's local daemon analyzes the transcript using the developer's own API key, fires a macOS notification summarizing what happened, and updates a dashboard at localhost:2742 showing the developer's AI Leverage trend, bugs found, prompt quality, and suggested patterns to add to CLAUDE.md.

Zero bytes of transcript data reach Kernora's servers. The analysis runs entirely on the developer's machine with their own credentials.

For engineering leaders, Kernora adds a team layer: every developer's AI Leverage score aggregates into a team benchmark. When a teammate's Claude session touches authentication code, Kernora injects the team's proven auth patterns directly into the agent's context — before the agent has a chance to hallucinate a solution. The team's institutional knowledge compounds automatically.

The core insight: consumer platforms (Netflix, TikTok, Google) built trillion-dollar moats by compounding behavioral traces. Kernora does the same for developer AI sessions — capturing decision traces, extracting patterns, and feeding them back into every future session. The developer who has used Kernora for 12 months has a context graph that makes every future session measurably smarter. That graph cannot be replicated by switching tools.

Kernora is available today as an open-source install for individual developers, with team features in private beta.

---

## FAQ

**Q: What is the AI Leverage Score?**

AI Leverage measures how much more effective a developer is with AI compared to baseline. A score of 1.0x means AI isn't helping. A score of 4.0x means the developer is getting four times the output per unit of effort compared to unassisted work. The score is calculated from prompt quality, session outcomes, decision trace analysis, and pattern accumulation rate. It's designed to become an industry standard — the way DORA metrics became the standard for DevOps velocity.

**Q: What does Kernora actually do to my workflow?**

Nothing, until a session ends. The Claude Code hook fires asynchronously after you close a session — it never blocks execution. Within 60 seconds you get a macOS notification from Nora (Kernora's analyst persona) summarizing what the session accomplished, any bugs flagged, and the best pattern to extract from the session. The dashboard at localhost:2742 accumulates this over time, showing your AI Leverage trend.

**Q: Does Kernora send my code or prompts to the cloud?**

No. In the default BYOK mode, analysis runs locally using your own Anthropic, Bedrock, or Ollama credentials. The only thing leaving your machine is the API call you make to your own LLM provider — the same call you'd make directly. Team sync (Phase 1) is an explicit opt-in that sends only the distilled skill strings — never raw transcripts or source code.

**Q: What's the MCP server for?**

The MCP server (`nora_mcp.py`) connects to Claude Code, Cursor, or Kiro as a tool. It exposes 18 capabilities including scope validation (flags prompts that are too vague or too broad before they burn tokens on hallucinations) and skill injection (automatically adds your team's proven methodology to the agent's context when relevant). Both tools read from your local `~/.kernora/echo.db` — the same DB that the dashboard reads from.

**Q: How is this different from Langfuse or Helicone?**

Langfuse and Helicone are built for AI application developers who want to monitor their apps. Kernora is built for software engineers who use AI tools to build software. The unit of analysis is the developer session, not the API call. The output is engineering insight — AI Leverage score, bugs, prompt patterns, methodology — not latency metrics or cost dashboards.

**Q: What does team mode look like?**

A Principal Engineer sets `mode.type = "team"` in config.toml and points Kernora at a team S3 bucket. Their locally distilled skills sync to the bucket. Every developer on the team pulls those skills automatically. When their agent touches a relevant area of code, Kernora's MCP server injects the team's methodology. The VP of Engineering gets aggregate visibility into AI Leverage by developer, token spend, session quality, and recurring bug patterns across the whole team.

**Q: How much does it cost to run?**

In BYOK solo mode: whatever your LLM provider charges for analysis. With Anthropic Haiku as the analyzer, this is roughly $0.18/developer/month based on typical session volumes. AWS Bedrock Nova Lite brings this to about $0.012/developer/month. Ollama is free.

Team mode pricing: $20/developer/month. Enterprise (SSO, on-prem sync, audit logs): contact hello@kernora.ai.

**Q: Why will AI Leverage become an industry standard?**

Because there is no standard metric for "how well does this person use AI?" — and the market desperately needs one. The METR randomized controlled trial showed developers can be 19% slower with AI while believing they're 20% faster. Engineering leaders have no instrument to know which camp their team is in. AI Leverage fills that gap. We're publishing the methodology as an open standard and working with the developer community to make it as universal as DORA metrics.

---

*Kernora is built under the Elastic License 2.0. Free for personal and team self-hosted use. Commercial managed service requires an agreement.*
