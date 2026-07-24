# Install the Kernora backend

This extension talks to the Kernora backend under `~/.kernora/`. Install it once per machine before you rely on grounding or MCP tools.

```bash
curl -fsSL https://kernora.ai/install | bash
```

That creates the local venv, registers MCP where it can, and installs session hooks. The Nora desktop app will refuse to start until this step is done.

**Tiers:** Free / Lite = **15 MCP tools**. Pro = **60 MCP tools**. License checks fail closed — if Nora cannot prove your tier, you get the 15-tool Lite surface.
