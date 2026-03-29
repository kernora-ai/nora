# Nora — AI Work Intelligence Engine

Your AI coding sessions contain patterns, bugs, and learnings. Nora extracts them automatically.

Your transcripts. Your API key. Your machine. Zero bytes leave your device.

[![License: ELv2](https://img.shields.io/badge/license-Elastic%20v2-blue.svg)](LICENSE)

---

## What Nora does

Every time you end a coding session, Nora captures it, analyzes it with your own API key, and surfaces:

- **Recurring bugs** — the JWT race condition you've hit 7 times this month
- **Prompt patterns** — what you're asking about, how your quality is trending
- **Skill opportunities** — one CLAUDE.md rule that would eliminate hours of rework
- **Team intelligence** — squad-level patterns for engineering managers

---

## Install

```bash
curl -sf https://kernora.ai/install | bash
```

Then install a **claw** — the adapter for your coding agent:

| Agent | Claw | Install |
|-------|------|---------|
| Claude Code | [claude-claw](https://github.com/kernora/claude-claw) | `claude plugin add kernora/claude-claw` |
| Kiro | kiro-claw | Coming soon |
| Cursor | cursor-claw | Coming soon |

---

## How it works

```
Coding session ends
  → Claw captures transcript (agent-specific)
  → Unix socket → Nora daemon → SQLite
  → LiteLLM calls your API key → structured insights
  → "Nora: 2 bugs found" notification
  → Dashboard at localhost:2742
```

**Privacy:** In BYOK mode, zero bytes of transcript data reach Kernora servers.
Verified by network audit during install.

---

## Model options (your credentials, your cost)

| Model | Provider | Cost/dev/month | Notes |
|-------|----------|----------------|-------|
| Sonnet 4.6 | Anthropic | ~$0.45 | Best quality |
| Haiku 4.5 | Anthropic | ~$0.18 | Default |
| Gemini 3.1 Pro | Google | ~$0.30 | Strong alternative |
| Nova Lite | AWS Bedrock | ~$0.012 | 50× cheaper |
| llama3.2:8b | Ollama | Free | Local, no network |

Change in `~/.kernora/config.toml`:
```toml
[model]
provider = "auto"  # detects all available keys, picks best per tier
```

---

## Architecture

Nora is the **core engine** — it's agent-agnostic. The analysis, database, dashboard, and notification system live here. Agent-specific adapters ("claws") live in their own repos and feed transcripts into Nora.

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ claude-claw  │   │  kiro-claw   │   │ cursor-claw  │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │
       └──────────────────┼──────────────────┘
                          │
                    ┌─────▼─────┐
                    │   Nora    │
                    │  Engine   │
                    ├───────────┤
                    │ analyzer  │
                    │ database  │
                    │ dashboard │
                    │ notifier  │
                    └───────────┘
```

---

## License

[Elastic License 2.0](LICENSE) — free for personal and team self-hosted use.
Commercial use (embedding in a managed service) requires agreement.

Built by [Mihir Choudhary](https://kernora.ai), with assistance from Claude.

Contact: hello@kernora.ai
