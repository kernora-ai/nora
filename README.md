# kiro-claw

**Nora's adapter for [Kiro](https://kiro.dev) — captures sessions and extends every hook.**

kiro-claw connects Kiro to [Nora](https://github.com/kernora-ai/nora), giving you:

- **Context injection** — past session patterns surface when you type a prompt
- **Spec shield** — dangerous tool operations blocked before they execute
- **Post-tool warnings** — known error signatures flagged in real-time
- **Steering files** — `.kiro/steering/nora-*.md` generated from your session history, read by Kiro automatically
- **Session capture** — every session analyzed for bugs, patterns, and decisions

## How it works

Nora registers 5 hooks in `~/.kiro/settings.json`:

| Hook | What Nora Does | Blocks? |
|------|---------------|---------|
| `agentSpawn` | Checks daemon health, refreshes steering files | No |
| `userPromptSubmit` | Searches past sessions, injects relevant context | No |
| `preToolUse` | Validates tool input against known anti-patterns | **Yes** (exit 2) |
| `postToolUse` | Checks output for known error signatures, logs metrics | No |
| `stop` | Captures transcript, sends to daemon for analysis | No |

## Install

kiro-claw is installed automatically when you install Nora with Kiro present:

```bash
curl -fsSL https://kernora.ai/install | bash
```

If you installed Nora before Kiro, re-run the installer to activate all 5 hooks.

### Manual install (advanced)

```bash
# From the nora repo directory:
cp kiro_agent_spawn.py ~/.kiro/hooks/nora_spawn.py
cp nora_context.py ~/.kiro/hooks/nora_context.py
cp kiro_spec_shield.py ~/.kiro/hooks/nora_pretool.py
cp kiro_post_tool.py ~/.kiro/hooks/nora_posttool.py
cp hook.py ~/.kiro/hooks/nora_stop.py
chmod +x ~/.kiro/hooks/nora_*.py
```

Then add the hooks to `~/.kiro/settings.json`. See [Nora install.sh](https://github.com/kernora-ai/nora/blob/main/install.sh) section 7 for the exact JSON.

## Steering files

After analyzing your sessions, Nora generates steering files at `.kiro/steering/`:

| File | Contains | Updated |
|------|----------|---------|
| `nora-patterns.md` | Effective patterns, playbooks, reusable code | After each analysis batch |
| `nora-decisions.md` | Architectural decisions, project rules | After each analysis batch |
| `nora-antipatterns.md` | Known bugs, anti-patterns to avoid | After each analysis batch |

Kiro reads these automatically on every prompt — your agent gets smarter with every session.

## VS Code extension (fallback)

The `kernora-ai.kiro-claw` VS Code extension provides a file-watcher based session capture mechanism. This is a fallback for environments where hook registration isn't available. The 5 hooks installed by `install.sh` are the primary integration and provide richer functionality.

## Architecture

```
Kiro session lifecycle:
  agentSpawn     →  nora_spawn.py      →  daemon health check + steering refresh
  prompt submit  →  nora_context.py    →  FTS5 search + context injection
  tool call      →  nora_pretool.py    →  anti-pattern validation (can BLOCK)
  tool result    →  nora_posttool.py   →  error signature check + metrics
  session end    →  nora_stop.py       →  transcript → daemon → analysis
                                           ↓
                                    steering_writer.py
                                           ↓
                                    .kiro/steering/nora-*.md
                                           ↓
                                    Kiro reads on next prompt
```

## Kiro Power

kiro-claw is also available as a [Kiro Power](https://github.com/kernora-ai/nora/blob/main/POWER.md) — a curated package of hooks + steering + MCP configuration.

## Privacy

Zero bytes leave your device. All hooks run locally. Session data stays in `~/.kernora/echo.db`. Steering files stay in `.kiro/steering/`. LLM calls (for analysis) use your own API key and go directly to your provider.

## License

[Elastic License 2.0](https://github.com/kernora-ai/nora/blob/main/LICENSE)

---

Built by [Kernora](https://kernora.ai). Part of the [Nora](https://github.com/kernora-ai/nora) ecosystem.
