# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Nora, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email: **security@kernora.ai**

We will acknowledge your report within 48 hours and provide a timeline for a fix.

## Scope

Security issues we care about:
- Data leakage (session transcripts leaving the machine in BYOK mode)
- Unauthorized access to `echo.db` or steering files
- Code injection via session transcripts or MCP tool inputs
- Extension privilege escalation
- Dependency vulnerabilities in bundled packages

## Architecture Security Notes

- All analysis runs locally — no data reaches Kernora servers in BYOK mode
- Dashboard binds to `127.0.0.1` only — not accessible from the network
- Unix socket uses mode `0600` — only the owning user can connect
- The Swift local LLM server binds to loopback only via `NWListener`
- SQL queries use parameterized statements — no string interpolation

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.x     | ✅ Active |
| 1.x     | ❌ End of life |
