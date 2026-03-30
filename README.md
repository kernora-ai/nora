# Nora — AI Session Intelligence Engine

Nora captures your AI coding sessions, analyzes them for patterns and bugs, and makes that knowledge available to future sessions. Every session makes the next one smarter.

No cloud. No proxy. Your data stays on your machine.

## Install

```bash
git clone https://github.com/kernora-ai/nora.git
cd nora && bash install.sh
```

This installs the Nora engine: daemon, analyzer, dashboard, and MCP server. To connect your AI coding agent, install a **claw**:

| Agent | Claw | Install |
|-------|------|---------|
| Claude Code | [claude-claw](https://github.com/kernora-ai/claude-claw) | `claude plugin add kernora-ai/claude-claw` |
| Kiro | [kiro-claw](https://github.com/kernora-ai/kiro-claw) | `ext install kernora-ai.kiro-claw` |
| Cursor | [cursor-claw](https://github.com/kernora-ai/cursor-claw) | Coming soon |

## Architecture

```
AI Coding Agent (Claude Code, Kiro, Cursor, ...)
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

All data in `~/.kernora/echo.db`. All analysis uses your own API key (BYOK). Zero bytes leave your machine.

## What's in this repo

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

## MCP Server Tools

The MCP server exposes session intelligence to any MCP-compatible client (Claude Code, Claude Desktop, etc.):

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

## Claw Protocol

Claws communicate with Nora via the [Claw Protocol](docs/CLAW-PROTOCOL.md) — a simple JSON envelope over Unix socket. Building a claw for a new agent is straightforward: capture the session transcript, wrap it in the protocol envelope, and send it to `~/.kernora/daemon.sock`.

## Configuration

Edit `~/.kernora/config.toml`:

```toml
[mode]
type = "byok"           # your API key, your machine

[model]
provider = "anthropic"   # or "bedrock" or "ollama"

[analysis]
run_every_minutes = 60   # analysis frequency

[dashboard]
port = 2742
```

## License

Elastic License 2.0 — [kernora.ai](https://kernora.ai)
