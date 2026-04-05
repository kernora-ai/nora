# Kernora — AI Work Intelligence

Kernora runs silently alongside your AI coding tools and turns every session into compounding intelligence. Patterns, decisions, and bugs are extracted into a local database and injected back into your agent's context automatically. Every session makes the next one smarter.

Your **AI Leverage Score** — a composite metric of prompt quality, context injection hit rate, decision acceptance, and pattern accumulation — starts at 1.0x and compounds toward 5.0x as Kernora learns your codebase.

No cloud. No API key required on Mac. Zero bytes sent to Kernora servers.

## Install

**VS Code / Kiro / Cursor:**
Install from the Marketplace, or install the `.vsix` directly:
Extensions → Install from VSIX → select kernora-*.vsix

Kernora bootstraps automatically — creates a Python venv, installs deps, starts the dashboard at localhost:2742.

**Claude Code:**
```bash
curl -fsSL https://raw.githubusercontent.com/kernora-ai/nora/main/install.sh | bash
```

**First run:**
```
nora scan ~/code/your-project
```
Seeds your database from git history so Kernora has context from session one.

## Dashboard

Open http://localhost:2742 to see:

| Tab | What it shows |
|-----|--------------|
| **Home** | AI Leverage Score, loop health, top projects, rule suggestions |
| **Projects** | Per-project AI metrics, patterns, decisions, bugs |
| **Activity** | Session history with outcome indicators |
| **Coach** | AI Leverage sparkline, coaching notes, certificate export |
| **Knowledge** | Best practices, playbooks, anti-patterns |
| **Memory** | Context injection feed, steering file viewer |
| **Decisions** | Searchable architectural decisions |
| **Bugs** | Bug inventory with severity, fix suggestions, mark resolved |
| **Settings** | LLM provider config, local AI status |

## AI Leverage Score

```
AI Leverage = 1.0 + (composite_quality × 4.0)

composite_quality = (prompt_quality × 0.4)
                  + (injection_hit_rate × 0.3)
                  + (decision_acceptance_rate × 0.2)
                  + (pattern_accumulation_rate × 0.1)
```

| Score | Label | What it means |
|-------|-------|--------------|
| 1.0–2.0 | Early | AI isn't helping much yet |
| 2.0–3.0 | Developing | Getting value, room to grow |
| 3.0–4.0 | Strong | Measurably effective AI usage |
| 4.0–5.0 | Excellent | Elite AI collaboration |

Export your score as a shareable certificate from the Coach tab.

## What You Can Say to Nora

All 18 tools are available as natural-language commands in your IDE's AI chat.

### Explore Your History

| Command | What It Does |
|---------|-------------|
| `nora stats` | Session count, token usage, model breakdown over time |
| `nora search <query>` | Full-text search across patterns, decisions, bugs |
| `nora session <id>` | Full detail on a specific session |

### Learn From Your Codebase

| Command | What It Does |
|---------|-------------|
| `nora patterns` | Recurring engineering patterns from your sessions |
| `nora decisions` | Architectural decisions with rationale |
| `nora bugs` | Past bugs with fix suggestions and severity |
| `nora skills` | Distilled team methodology — engineering rules and playbooks |
| `nora scan <path>` | Import a git repo's history (run once per project) |

### Quality & Reviews

| Command | What It Does |
|---------|-------------|
| `nora pe-review <focus>` | Principal Engineer 4-tier code audit |
| `nora coe <issue>` | Blameless root-cause investigation (5 Whys) |
| `nora coe product <issue>` | Product COE — why a feature shipped wrong |
| `nora retro` | Engineering retrospective with git velocity metrics |
| `nora scope <task>` | Validate a task against project history before starting |

### Factory & Coaching

| Command | What It Does |
|---------|-------------|
| `nora sofac` | Software Factory health — what shipped, what's pending (GREEN/YELLOW/RED) |
| `nora inventory` | Feature audit: SHIP/POLISH/WIRE/BLOCKER |
| `nora coach` | AI Leverage coaching — patterns, anti-patterns, before/after examples |
| `nora onboard` | Onboard a new developer with your team's methodology |

### Help

| Command | What It Does |
|---------|-------------|
| `nora help` | Full tool reference with examples |

## LLM Provider Priority

Nora tries these in order — the first available one wins:

1. **IDE LLM** (VS Code, Kiro, Cursor) — zero config
2. **Apple FoundationModels** (macOS 26+) — on-device, zero cost
3. **MLX-LM** (macOS 14+) — on-device, ~2GB one-time download
4. **BYOK** — Anthropic, OpenAI, Google, Bedrock, Grok
5. **Ollama** — local, free

On a modern Mac, Kernora works with no API key.

## Privacy

All data stays in `~/.kernora/echo.db` on your machine. Zero bytes reach Kernora servers in BYOK mode. Analysis uses your own API key — the same call you'd make directly.

## Architecture

- **Database:** `~/.kernora/echo.db` (SQLite, WAL mode)
- **Dashboard:** Flask + HTMX at `localhost:2742`
- **MCP server:** 18 tools via stdio JSON-RPC
- **Hooks:** 6 Claude Code hooks, 5 Kiro hooks
- **Steering:** Auto-generated markdown files injected into AI context
- **Config:** `~/.kernora/config.toml`

## Links

- Website: [kernora.ai](https://kernora.ai)
- Source: [github.com/kernora-ai/nora](https://github.com/kernora-ai/nora)
- Issues: [github.com/kernora-ai/nora/issues](https://github.com/kernora-ai/nora/issues)
- X / Twitter: [@KernoraAI](https://x.com/KernoraAI)
