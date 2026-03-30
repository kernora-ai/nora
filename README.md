# Nora — AI Work Intelligence

Your AI gets smarter every session. Nora captures coding sessions, extracts patterns and decisions, and feeds them back as context and steering. No cloud. No proxy. Your data stays on your machine.

## Install

### Kiro (one-click)

Open Kiro → Powers panel (⚡) → **Add power from GitHub** → paste:

```
https://github.com/kernora-ai/nora
```

Click Install. Nora's MCP server registers, steering files land, hooks get created. Done.

### Claude Code

```bash
git clone https://github.com/kernora-ai/nora.git ~/.kernora/src && bash ~/.kernora/src/install.sh
```

Then install the Claude Code hooks:

```bash
git clone https://github.com/kernora-ai/claude-claw.git /tmp/claude-claw && bash /tmp/claude-claw/install.sh && rm -rf /tmp/claude-claw
```

### From source

```bash
git clone https://github.com/kernora-ai/nora.git
cd nora && bash install.sh
```

Then connect your AI agent with a [claw](#claws).

## How It Works

```
You code normally
    │
    ▼
Session ends → claw captures transcript → sends to Nora daemon
    │
    ▼
Nora analyzes → extracts patterns, decisions, bugs (using YOUR API key)
    │
    ▼
Steering files regenerate → Kiro reads them on next prompt
    │
    ▼
Next session is smarter. Repeat.
```

All data in `~/.kernora/echo.db`. All analysis uses your own API key (BYOK). Zero bytes leave your machine.

## Architecture

```
AI Coding Agent (Kiro, Claude Code, Cursor, ...)
    │
    ├── claw (agent-specific adapter)
    │     └── hooks capture sessions → pipe to Nora daemon
    │
    └── Nora engine (this repo)
          ├── daemon       — receives sessions via Unix socket
          ├── analyzer     — extracts patterns, decisions, bugs (LiteLLM BYOK)
          ├── MCP server   — 8 tools for querying session intelligence
          ├── dashboard    — web UI at localhost:2742
          └── echo.db      — local SQLite database
```

## Kiro Power

This repo is a **Kiro Power** — installable directly from the Kiro IDE. The Power includes:

| File | Purpose |
|------|---------|
| `POWER.md` | Power metadata, onboarding steps, MCP tool documentation |
| `mcp.json` | MCP server configuration (local stdio) |
| `steering/` | Template steering files (populated after first session analysis) |

After installation, Nora provides 8 MCP tools and 3 auto-updating steering files that Kiro reads on every prompt.

## MCP Tools

| Tool | What It Does |
|------|-------------|
| `nora_search` | Full-text search across patterns, decisions, bugs, insights |
| `nora_patterns` | List effective coding patterns from past sessions |
| `nora_decisions` | List architectural decisions |
| `nora_bugs` | List known bugs with severity and fix code |
| `nora_stats` | Dashboard stats (sessions, insights, tokens) |
| `nora_session` | Get details for a specific session |
| `nora_scope_validation` | Validate execution scope before multi-file edits |
| `nora_skills` | Fetch distilled methodology from your best sessions |

## Steering Files

Nora generates three global steering files, updated after each session analysis:

| File | Content |
|------|---------|
| `nora-patterns.md` | Reusable patterns, playbooks, tech domains |
| `nora-decisions.md` | Architectural decisions, project rules |
| `nora-antipatterns.md` | Mistakes to avoid, common bugs |

Kiro reads these automatically on every prompt. No manual loading needed.

## Claws

Claws are agent-specific adapters that capture sessions and pipe them to Nora:

| Agent | Claw | Install |
|-------|------|---------|
| **Kiro** | Built into this Power | Automatic via Power install |
| Claude Code | [claude-claw](https://github.com/kernora-ai/claude-claw) | `bash install.sh` (6 hooks) |
| Cursor | [cursor-claw](https://github.com/kernora-ai/cursor-claw) | Coming soon |
| VS Code | [vscode-claw](https://github.com/kernora-ai/vscode-claw) | Shared base for VS Code-derived agents |

## Engine Files

| File | Purpose |
|------|---------|
| `daemon.py` | Background daemon — receives sessions via Unix socket, stores in echo.db |
| `analyzer.py` | Session analysis — extracts patterns, decisions, bugs using LiteLLM |
| `db.py` | Database schema and migrations for echo.db |
| `dashboard.py` | Web dashboard at localhost:2742 |
| `nora_mcp.py` | MCP server — 8 tools for searching patterns, bugs, decisions, stats |
| `notifier.py` | macOS/Linux notifications on analysis complete |
| `cli_shield.py` | Prompt scope validation |
| `install.sh` | Engine installer (daemon + dashboard + MCP) |

## Configuration

Edit `~/.kernora/config.toml`:

```toml
[mode]
type = "byok"              # your key, your machine

[model]
provider = "anthropic"      # or "bedrock", "gemini", "ollama"

[analysis]
run_every_minutes = 60      # analysis frequency

[dashboard]
port = 2742
```

## Privacy

Nora runs 100% locally. Session transcripts, analysis, and steering files never leave your machine. The only network call is to your own LLM provider for analysis. Zero telemetry.

## License

[Elastic License 2.0](https://www.elastic.co/licensing/elastic-license) — free for personal and team self-hosted use. Commercial redistribution requires agreement with [kernora.ai](https://kernora.ai).
