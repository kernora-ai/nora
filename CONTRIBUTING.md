# Contributing to Nora

Thank you for your interest in contributing. Here's how to get involved.

## Building a claw

The highest-impact contribution is building a claw for an AI coding agent we don't support yet. If you use Kiro, Cursor, Windsurf, Copilot, or any other agent, you can build a claw in an afternoon.

**Start here:** Read the [Claw Protocol](docs/CLAW-PROTOCOL.md). A claw is typically 50-200 lines that capture transcripts from your agent and pipe them to Nora's Unix socket.

**Naming:** Use `{agent}-claw` as the repo name (e.g., `windsurf-claw`). Create it under your own GitHub account or contribute it to the `kernora` org — either is welcome.

## Contributing to the engine

For changes to Nora itself (analyzer, dashboard, database, daemon):

1. Fork the repo
2. Create a feature branch
3. Make your changes
4. Run tests: `python -m pytest tests/`
5. Open a PR with a clear description of what and why

### Areas where help is welcome

- **Dashboard improvements** — the Flask+HTMX dashboard is functional but basic
- **Trend analysis** — week-over-week comparisons of prompt quality, bug recurrence
- **Test coverage** — more unit tests for the two-phase analyzer
- **Platform support** — Linux systemd service (currently macOS launchd only)

## Code style

- Python 3.10+
- No build tools, no npm, no node_modules
- Type hints where they add clarity
- Docstrings on public functions

## License

By contributing, you agree that your contributions will be licensed under the [Elastic License 2.0](LICENSE).
