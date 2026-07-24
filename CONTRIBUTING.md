# Contributing to Nora

Thanks for your interest in contributing to Nora.

## Before You Contribute

By submitting a pull request, you agree that your contributions will be
licensed under the Elastic License 2.0 (ELv2), the same license that
covers the rest of the project.

## How to Contribute

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Add tests if applicable
4. Ensure `cd kiro-extension/bundled && python3 -m pytest test_integrity.py -v` passes
5. Ensure `cd kiro-extension/bundled && python3 -c "from db import init_db; init_db()"` succeeds
6. Submit a pull request

## Code Standards

- Every Python file must have the ELv2 license header:
  ```python
  # Kernora — AI Work Intelligence
  # Elastic License 2.0 — commercial use requires agreement with kernora.ai
  # https://github.com/kernora-ai/nora/blob/main/LICENSE
  ```
- Python: stdlib only in hook files (hook.py, nora_context.py) — Tenet 12
- SQL: parameterized queries only — never interpolate user input
- All servers bind to localhost only — Tenet 3

## Project Structure

```
kiro-extension/           — VS Code / Kiro / Cursor extension
  bundled/                — Python engine (dashboard, analyzer, db, hooks)
  src/                    — TypeScript extension code
kernora-native-mac/       — Swift local LLM server (FoundationModels + MLX-LM)
docs/                     — Public documentation
```

## What We're Looking For

- Bug fixes with test coverage
- Performance improvements to the analysis pipeline
- New MCP tools that surface useful session intelligence
- Dashboard UI improvements
- Documentation improvements

## What We Won't Accept

- Changes that send data to external servers (violates Tenet 3)
- New pip dependencies in the hot path (violates Tenet 12)
- Changes to hook.py that add external imports (violates Tenet 12)
- Modifications to the AI Leverage Score formula without discussion

## Questions?

Open a GitHub Discussion or email hello@kernora.ai.
