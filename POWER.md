---
name: Nora by Kernora
description: AI Work Intelligence — captures sessions, learns patterns, injects context, evolves steering
version: 0.2.0
author: Kernora AI
repository: https://github.com/kernora-ai/nora
license: Elastic-2.0
tags: [productivity, patterns, context, intelligence, session-analysis]
---

# Nora — AI Work Intelligence for Kiro

Nora is your silent coding partner. She captures every Kiro session, extracts patterns, decisions, and anti-patterns, then feeds them back into your next session as context and steering.

## What Nora Does

- **Captures** every Kiro session transcript automatically (stop hook)
- **Analyzes** sessions with two-phase extraction: deterministic + LLM
- **Injects context** from past sessions when you type a prompt (userPromptSubmit hook)
- **Validates** tool use against danger patterns and learned anti-patterns (preToolUse hook)
- **Monitors** tool outputs for known error signatures (postToolUse hook)
- **Generates steering** files that Kiro reads on every prompt (`.kiro/steering/nora-*.md`)
- **Tracks** everything in a local dashboard at http://localhost:2742

## Onboarding

### Prerequisites

- Python 3.9+
- One of: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, AWS Bedrock profile, or Ollama

### Install

```bash
curl -fsSL https://kernora.ai/install | bash
```

This installs hooks for both Kiro and Claude Code. Your data never leaves your machine.

### Verify

After installing, start a Kiro session and check:

1. Dashboard is live: http://localhost:2742
2. Steering files exist: `ls ~/.kiro/steering/nora-*.md`
3. After your first session completes, check for analysis: open the dashboard

## Steering

Nora generates three global steering files:

| File | Content | Updated |
|------|---------|---------|
| `~/.kiro/steering/nora-patterns.md` | Reusable patterns, playbooks, tech domains | After each analysis |
| `~/.kiro/steering/nora-decisions.md` | Architectural decisions, project rules | After each analysis |
| `~/.kiro/steering/nora-antipatterns.md` | Mistakes to avoid, common bugs | After each analysis |

These are read by Kiro automatically on every prompt — no hook needed.

## Hooks

| Hook | Script | Purpose |
|------|--------|---------|
| `agentSpawn` | `nora_spawn.py` | Ensure daemon running, check steering freshness |
| `userPromptSubmit` | `nora_context.py` | Inject relevant context from past sessions |
| `preToolUse` | `nora_pretool.py` | Block dangerous tool use, warn on anti-patterns |
| `postToolUse` | `nora_posttool.py` | Detect known errors, log tool metrics |
| `stop` | `kernora_hook.py` | Capture session transcript for analysis |

## Privacy

Nora runs 100% locally. Your session transcripts, analysis results, and steering files never leave your machine. The only network call is to your own LLM provider (Anthropic, AWS Bedrock, Google, or local Ollama) for Phase 2 analysis.
