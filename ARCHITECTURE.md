# Kernora — Architecture Reference
# Last updated: May 2026
# Open-core reference: BYOK Solo (Mode A) architecture

---

## Overview

This document covers Mode A — BYOK Solo, the open-core deployment mode.
Every component described here runs locally on the developer's machine with
no data leaving that machine.

Team (B), Enterprise (C), and Air-gapped (D) deployment modes are part of
the Tier 3/4 commercial product. Contact kernora.ai for details.

```
SHARED CORE (all modes)
────────────────────────────────────────────────────────────────────
Claude Code session ends
  → hook.py (stdlib only, async, zero network calls)
  → reads transcript JSONL from disk
  → Unix socket (mode 0600) → daemon.py (now typically bundled into dashboard.py for the extension-based architecture)
  → SQLite WAL mode (~/.kernora/echo.db)
  → LiteLLM → user's own API key (Haiku / Nova Lite / Ollama)
  → structured insights written back to SQLite
  → macOS / Linux notification ("Nora · Kernora")
  → dashboard at localhost:2742
```

---

## Core Architecture Additions

The v2.1.0 release completes the transition to an **extension-based architecture**. The standalone daemon is now structurally bundled and spawned by the VSIX extension to ensure resilience, relying on dynamically registered hooks.

Key systemic flows include:
- **Loop Health**: The compounding loop tracks continuous lifecycle stages: CAPTURE → LEARN → IMPROVE → COMPOUND.
- **Decision Traces**: Extracted completely out-of-band via `trace_parser.py` within the analyzer loop (never blocking).
- **AI Leverage Score**: Derived via `score_utils.py` mapping automated tool executions against manual baselines.
- **Project-Level Intelligence**: Metrics, activity, and scoring are globally tracked but filterable by contextual active project URIs.
- **Local Native LLM**: Complete Apple FoundationModels and MLX bridging (`kernora-native-mac` probing across TCP 2744/2745).
- **Tool Ecosystem**: Now providing 18 MCP Tools out of the box dynamically via `nora_mcp.py`.

## Mode A — BYOK Solo

**Who:** Individual developer. Does not trust Kernora with any data.

**Data boundary:** Developer's machine. Nothing crosses it.

```
YOUR MACHINE ONLY
┌─────────────────────────────────────────────────────────┐
│ hook.py → daemon → SQLite → LiteLLM (your key) → SQLite │
│ dashboard: localhost:2742                                │
│ notification: "Nora · Kernora"                           │
└─────────────────────────────────────────────────────────┘
                    ↑
           NOTHING LEAVES THIS BOX
           Verified by tcpdump network audit during install
```

**Config:**
```toml
[mode]
type = "byok"
[storage]
s3_content = "insights_only"  # irrelevant — S3 disabled
[s3]
enabled = false
```

