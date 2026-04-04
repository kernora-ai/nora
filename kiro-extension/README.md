# Kernora — AI Work Intelligence

Kernora remembers your coding sessions. Every pattern, decision, and bug is extracted into a local database and injected into your AI agent's context automatically. Your AI gets smarter every session — no configuration required.

## Getting Started

**Kiro / Cursor (GUI IDE):**
Install the `.vsix` extension. Kernora auto-starts its MCP server and dashboard on launch.

**Kiro CLI / Claude Code:**
```bash
chmod +x install.sh && ./install.sh
```
The installer registers MCP hooks in `~/.kiro/settings.json`. The dashboard starts automatically on first use at `localhost:2742`.

**First thing to do after install:**
```
nora scan ~/code/your-project
```
This imports your git history — patterns, decisions, and bugs — so Kernora has context immediately.

## What You Can Say to Nora

All 16 tools are available as natural-language commands in your IDE's AI chat.

### Explore Your History

| Command | What It Does |
|---------|-------------|
| `nora stats` | Session count, token usage, costs, model breakdown over time |
| `nora search <query>` | Find past sessions by keyword (e.g., `nora search the auth refactor`) |
| `nora session <id>` | Full detail on a specific session — summary, bugs, optimizations |

### Learn From Your Codebase

| Command | What It Does |
|---------|-------------|
| `nora patterns` | Recurring engineering patterns extracted from your sessions |
| `nora decisions` | Architectural decisions with rationale and context |
| `nora bugs` | Past bugs, how they happened, and how they were fixed |
| `nora skills` | Your team's playbook — engineering rules and bug patterns distilled into reusable methodology |
| `nora scan <path>` | Import a git repo's history into Kernora (run once per project) |

### Quality & Reviews

| Command | What It Does |
|---------|-------------|
| `nora pe-review <focus>` | Principal engineer code review — can target a directory, file, or concern |
| `nora coe <issue>` | Technical root-cause investigation using 5 Whys (e.g., `nora coe upload returns 500 on large PDFs`) |
| `nora coe product <issue>` | Product/UX COE — why a feature shipped wrong or a user journey is broken |
| `nora retro` | Engineering retrospective with velocity metrics and trend analysis |
| `nora scope <task>` | Validate a planned task against project history before starting |

### Factory Operations

| Command | What It Does |
|---------|-------------|
| `nora sofac` | Software Factory health check — what shipped, what's pending, build status (GREEN/YELLOW/RED) |
| `nora inventory` | Feature inventory — what exists in the codebase, what's missing, surface area audit |

### Help

| Command | What It Does |
|---------|-------------|
| `nora help` | Full tool reference with examples and quick-start workflows |

## How It Works

1. **Session capture:** Kernora hooks into your IDE's session lifecycle. Every coding session is logged locally.
2. **Git scan:** `nora scan` walks your git history and extracts patterns, decisions, and bugs from commit messages and diffs.
3. **Semantic analysis:** Your IDE's LLM analyzes raw sessions into structured insights (themes, bugs, optimizations, skill opportunities).
4. **Steering injection:** Patterns, decisions, and anti-patterns are written into steering files (`~/.kiro/steering/kernora-*.md`) that your IDE reads automatically on every prompt.
5. **MCP tools:** All 16 Nora tools are registered as MCP tools, callable from your IDE's AI chat.

## Architecture

- **Database:** `~/.kernora/echo.db` (SQLite) — all data stays local
- **Dashboard:** Flask server on `localhost:2742` — sessions, bugs, learnings, settings
- **MCP server:** Python stdio server registered in your IDE's settings
- **Steering files:** Markdown files at `~/.kiro/steering/` injected into AI context
- **Config:** `~/.kernora/config.toml` — optional provider/model settings for standalone analysis

## Privacy

All data stays on your machine. Zero bytes sent to Kernora. Your sessions, your database, your steering files. Kernora ships execution code only.
