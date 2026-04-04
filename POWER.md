---
name: "nora"
displayName: "Nora — AI Work Intelligence"
description: "Your AI gets smarter every session. Nora captures sessions, learns patterns, injects context, and compounds your AI Leverage — all locally."
keywords: ["nora", "kernora", "patterns", "context", "memory", "intelligence", "learning", "steering", "session", "decisions", "bugs", "anti-patterns", "knowledge", "leverage", "coaching"]
author: "Kernora AI"
---

# Nora — AI Work Intelligence

Nora is your silent coding partner. She captures every session, extracts patterns, decisions, and anti-patterns, then feeds them back as context and steering. Your AI Leverage Score compounds toward 5.0x as Nora learns your patterns.

100% local. Zero bytes leave your machine. No API key required on Mac.

## Onboarding

### Step 1: Check Prerequisites

Verify the following are installed:

- **Python 3.9+** — Run `python3 --version` to confirm
- **git** — Run `git --version` to confirm

If either is missing, halt setup and inform the user.

### Step 2: Install Nora

Nora bootstraps automatically when installed as a Kiro extension or Power.

For manual install:
```bash
git clone https://github.com/kernora-ai/nora.git /tmp/nora-install && bash /tmp/nora-install/install.sh && rm -rf /tmp/nora-install
```

### Step 3: Configure LLM (Optional)

Nora works out of the box with no API key on Mac (Apple FoundationModels on macOS 26+, MLX-LM on macOS 14+).

For cloud analysis, set any of these environment variables:
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `AWS_PROFILE` (for Bedrock)

Provider priority: IDE LLM → Apple FoundationModels → MLX-LM → BYOK API keys → Ollama.

### Step 4: Verify Installation

1. Check dashboard: `curl -sf http://localhost:2742/health` (should return JSON with `"status":"ok"`)
2. Check steering: `ls ~/.kiro/steering/nora-*.md` (should list 3 files)

## Available MCP Server

### nora

**Connection:** Local stdio process

Nora's MCP server provides 18 tools for querying your session intelligence. All data stays local in `~/.kernora/echo.db`.

**Tools (18):**

- **nora_search** — Full-text search across patterns, decisions, bugs, and insights
- **nora_patterns** — List effective coding patterns, optionally filtered by project
- **nora_decisions** — List architectural decisions recorded across sessions
- **nora_bugs** — List known bugs with severity, file path, and fix code
- **nora_stats** — Dashboard stats: sessions, insights, AI Leverage Score
- **nora_session** — Get full details for a specific session by ID
- **nora_scope_validation** — Validate execution scope before multi-file edits
- **nora_skills** — Fetch distilled methodology from your best sessions
- **nora_scan** — Seed database from git history
- **nora_pe_review** — Principal Engineer 4-tier code audit
- **nora_coe** — Blameless root cause investigation (5 whys)
- **nora_coe_product** — Product COE — why was this built wrong
- **nora_retro** — Engineering retrospective with git velocity
- **nora_sofac** — Factory health status
- **nora_inventory** — Feature audit: SHIP/POLISH/WIRE/BLOCKER
- **nora_coach** — AI leverage coaching
- **nora_onboard** — Onboard a new developer
- **nora_help** — List all tools

## How Nora Works

1. **You code normally.** Nora is silent during your session.
2. **Session ends.** Hooks capture the transcript locally.
3. **Nora analyzes.** Extracts patterns, decisions, bugs, and your AI Leverage Score.
4. **Steering evolves.** Steering files regenerate with the latest intelligence.
5. **Next session is smarter.** Context from past sessions is injected into your prompts.

## Privacy

- Session transcripts stored in `~/.kernora/echo.db` on your machine
- Local LLM analysis via Apple FoundationModels or MLX-LM — zero network calls
- Optional cloud analysis uses YOUR API key if configured
- Zero telemetry, zero cloud storage, zero data sharing

## Dashboard

Open http://localhost:2742 to see:

| Tab | What it shows |
|-----|--------------|
| **Home** | AI Leverage Score, loop health, top projects, rule suggestions |
| **Projects** | Per-project AI metrics, patterns, decisions, bugs |
| **Activity** | Session history with outcome indicators |
| **Coach** | AI Leverage sparkline, coaching notes, decision patterns, certificate |
| **Knowledge** | Best practices, playbooks, anti-patterns |
| **Memory** | Context injection feed, steering file viewer |
| **Decisions** | Searchable architectural decisions |
| **Bugs** | Bug inventory with severity, fix suggestions, mark resolved |
| **Settings** | LLM provider config, local AI status |

## Configuration

Edit `~/.kernora/config.toml`:

```toml
[mode]
type = "byok"           # your data stays on your machine

[model]
provider = "auto"       # tries IDE → local → BYOK → Ollama

[dashboard]
port = 2742
```

## Resources

- [GitHub: kernora-ai/nora](https://github.com/kernora-ai/nora)
- [Dashboard](http://localhost:2742)
- [kernora.ai](https://kernora.ai)
