# Nora — Your AI Leverage, Compounding

Nora is the AI work intelligence layer for developers. It runs silently alongside your AI coding tools, captures every session, analyzes it, and feeds that knowledge back into your next session. Every session makes the next one smarter.

Your **AI Leverage Score** — a composite metric of prompt quality, context injection effectiveness, decision acceptance rate, and pattern accumulation — starts at 1.0x and compounds toward 5.0x as Nora learns your patterns.

No cloud required. Run a local Ollama for fully-local analysis with no API key, or BYOK (Anthropic / OpenAI / Google / Bedrock / Grok). Your data stays on your machine.

## Install

### Kiro / VS Code / Cursor
Download the latest `.vsix` from [Releases](https://github.com/kernora-ai/nora/releases), then:
```
Extensions → Install from VSIX → select kernora-*.vsix
```
Nora bootstraps automatically — creates a Python venv, installs deps, starts the dashboard.

### Claude Code
```bash
curl -fsSL https://raw.githubusercontent.com/kernora-ai/nora/main/install.sh | bash
```

The installer registers Nora's MCP server automatically. If you want to add it to an existing Claude Code install manually:
```bash
claude mcp add nora ~/.kernora/venv/bin/python3 -- ~/.kernora/app/nora_mcp.py
```

### Claude Desktop (chat.claude.ai app)

The installer detects Claude Desktop and writes to `~/Library/Application Support/Claude/claude_desktop_config.json` automatically. For manual setup:

```json
{
  "mcpServers": {
    "nora": {
      "command": "/Users/YOUR_USERNAME/.kernora/venv/bin/python3",
      "args": ["/Users/YOUR_USERNAME/.kernora/app/nora_mcp.py"]
    }
  }
}
```

Restart Claude Desktop after editing the config.

### Cowork (Claude desktop app)

Install the `nora.plugin` from the [Releases](https://github.com/kernora-ai/nora/releases) page. After Nora is installed locally, the plugin connects Cowork to the open-core MCP tools.

## What Happens

**Session 1** — You code normally. Nora captures the transcript.

**Between sessions** — Nora analyzes the transcript: extracts patterns, architectural decisions, bugs, anti-patterns, and your AI Leverage Score.

**Session 2** — Your second session starts smarter. Nora injects relevant context from past sessions directly into your prompt.

## Dashboard

Open http://localhost:2742 to see:

| Tab | What it shows |
|-----|--------------|
| **Home** | AI Leverage Score, loop health, top projects, rule suggestions |
| **Projects** | Per-project AI metrics, patterns, decisions, bugs |
| **Activity** | Session history with outcome indicators |
| **Coach** | AI Leverage sparkline, coaching notes, decision patterns, certificate export |
| **Knowledge** | Best practices, playbooks, anti-patterns |
| **Memory** | Context injection feed, steering file viewer |
| **Decisions** | Searchable architectural decisions |
| **Bugs** | Bug inventory with severity, fix suggestions, mark resolved |
| **Settings** | LLM provider config, local AI status, telemetry |

## AI Leverage Score

A composite metric measuring your AI effectiveness:

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

## How It Works

```
Your IDE (Kiro / Claude Code / Cursor)
    │
    ├── hooks (capture at the moment of decision)
    │     ├── on session end → capture transcript
    │     ├── on prompt → inject relevant past context
    │     ├── on tool use → track patterns
    │     └── on session start → check steering freshness
    │
    ├── MCP server (open core — 13 tools)
    │     └── nora_search, nora_patterns, nora_decisions, nora_bugs,
    │         nora_stats, nora_session, nora_scope_validation,
    │         nora_skills, nora_retro, nora_inventory, nora_coach,
    │         nora_onboard, nora_help
    │
    ├── LLM provider (BYOK or Ollama)
    │     └── Anthropic, OpenAI, Google, Bedrock, Grok, or local Ollama
    │
    └── dashboard (localhost:2742)
          ├── Prompt-quality signals + trend
          ├── Project-level intelligence
          ├── Decision trace analysis
          ├── Loop health monitoring
          └── Steering file management
```

All data in `~/.kernora/echo.db`. Zero bytes leave your machine in BYOK mode.

## LLM Provider Priority

Nora tries these in order — the first available one wins:

1. **IDE LLM** (Kiro, Cursor, VS Code) — uses your IDE's built-in model, zero config
2. **BYOK API keys** — Anthropic, OpenAI, Google, Bedrock, Grok
3. **Ollama** — local, free

Use Ollama for fully-local inference.

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

## MCP Tools

13 tools available to your AI agent in the open-core build:

| Tool | What it does |
|------|-------------|
| `nora_search` | Full-text search across patterns, decisions, bugs |
| `nora_patterns` | List effective coding patterns |
| `nora_decisions` | List architectural decisions |
| `nora_bugs` | List known bugs with fixes |
| `nora_stats` | Dashboard stats |
| `nora_session` | Session details by ID |
| `nora_scope_validation` | Safety check before multi-file edits |
| `nora_skills` | Distilled team methodology |
| `nora_retro` | Engineering retrospective with git velocity |
| `nora_inventory` | Feature audit: SHIP/POLISH/WIRE/BLOCKER |
| `nora_coach` | Prompt-quality signals (sessions analyzed, avg quality, repetitions) |
| `nora_onboard` | Onboard a new developer |
| `nora_help` | List all tools |

## Privacy

- **BYOK mode**: analysis runs on YOUR machine with YOUR API key. Zero bytes reach Kernora servers.
- **Local LLM mode**: analysis runs entirely on-device via Apple Neural Engine. No network calls.
- **Team mode** (coming soon): data syncs to YOUR S3 bucket. Kernora reads via a revocable IAM role you control.

Verify with `tcpdump` during install — the install script includes a network audit.

## License

Elastic License 2.0 — free for personal and team self-hosted use.
Commercial managed service requires agreement. hello@kernora.ai

## Links

- Dashboard: http://localhost:2742
- Website: [kernora.ai](https://kernora.ai)
- GitHub: [github.com/kernora-ai/nora](https://github.com/kernora-ai/nora)
