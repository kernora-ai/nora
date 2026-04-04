# Kernora — Product Requirements Document

**Version:** 0.1 (Phase 0 — BYOK Solo)
**Owner:** Mihir Choudhary
**Status:** In development

---

## Problem

Developers using AI coding agents have no visibility into the quality or cost of their AI usage. They don't know which sessions were productive, which prompts caused hallucination loops, how much they're spending per feature, or what patterns their best sessions have in common. Engineering leaders have even less visibility — they pay for AI licenses across hundreds of developers with no data on ROI.

The result: token burn on vague prompts, repeated mistakes across sessions, no organizational learning, and no way to improve.

---

## Users

**The Individual Developer**
Uses Claude Code, Cursor, or Kiro daily. Wants to understand which of their AI sessions were productive and why. Wants to get better at prompting without reading a guide. Values privacy — doesn't want session transcripts leaving their machine.

Success metric: After one week, they can name one specific pattern they've changed based on Nora's feedback.

**The Principal Engineer**
Owns engineering methodology for a team of 10–50 developers. Currently tries to encode best practices in CLAUDE.md files and code review feedback, but it doesn't stick. Wants the methodology to be automatically present when the agent is doing relevant work.

Success metric: After one sprint, at least 3 developers on the team have a relevant skill injected by Kernora during a session.

**The VP of Engineering**
Pays $5k–$20k/month in AI subscriptions across the team. Has no idea whether this is generating ROI. Wants aggregate data: token spend, session quality, recurring bugs, and high-value patterns across the team.

Success metric: Can show the CFO a dollar figure for "estimated hours saved" with supporting data.

---

## Phase 0 — BYOK Solo (current)

### Features

**Session Hook**
After each Claude Code session ends, `hook.py` fires asynchronously (non-blocking). It reads the session metadata, connects to the local daemon via Unix socket, and hands off the payload. If the daemon is offline, the payload is spooled to `~/.kernora/spool/` and replayed on next restart.

Acceptance criteria:
- Hook fires within 1 second of session end
- Hook never blocks or slows the IDE
- Spool/replay works correctly when daemon was offline

**Local Daemon**
`daemon.py` runs as a LaunchAgent (macOS) or background process. Receives sessions via Unix socket, stores them in SQLite (`~/.kernora/echo.db`), and runs analysis hourly against unanalyzed sessions.

Acceptance criteria:
- Starts automatically on login
- Survives crashes — restarts via LaunchAgent KeepAlive
- DB writes are WAL-mode safe under concurrent access

**Analysis (BYOK)**
`analyzer.py` calls the user's own LLM (Anthropic Haiku, Bedrock Nova, Ollama) to analyze each session transcript. Returns structured JSON: themes, bugs, optimizations, prompt quality score, skill opportunity.

Acceptance criteria:
- Works with ANTHROPIC_API_KEY, AWS credentials, or local Ollama — configurable via config.toml
- Handles empty/short sessions gracefully (returns empty arrays, not an error)
- Token cost is logged per session

**Notification**
After analysis completes, `notifier.py` fires a macOS notification from "Nora · Kernora" with the session summary. Falls back to Linux notify-send, then Discord webhook, then stderr.

Acceptance criteria:
- Notification appears within 60 seconds of session end (assuming daemon is running)
- Notification never crashes the daemon if the platform doesn't support it

**Dashboard**
Flask app at http://localhost:2742. Five tabs: Overview (KPIs), Sessions (list), Bugs (cards by severity), Learnings (CLAUDE.md rule suggestions), Settings (provider switcher, privacy badge).

Acceptance criteria:
- All routes return 200
- `/health` returns JSON with session and analyzed counts
- Settings tab allows switching provider without restarting dashboard
- Privacy badge visible on every page confirming BYOK mode

**Installer**
Single command: `./install.sh`. Detects Python 3.9+ (including Homebrew/pyenv installs), installs deps, creates `~/.kernora/`, registers Claude Code hook, initializes DB, installs LaunchAgents.

Acceptance criteria:
- Works on macOS 13+ with Python 3.9–3.13
- Idempotent — safe to run multiple times
- `./uninstall.sh` cleanly removes all Kernora artifacts

---

## Phase 1 — Team Observability (next)

### Features

**Team Swarm Sync**
`swarm_sync.py --push` uploads distilled skill_opportunity strings from the local DB to a shared S3 bucket. `--pull` downloads teammates' skills. Only skill strings sync — never raw transcripts or source code. Requires explicit `mode.type = "team"` and an S3 bucket configured in config.toml.

**MCP Scope Validation**
`kernora_mcp.py` exposes two tools to Claude Code, Cursor, and Kiro via stdio MCP: `kernora_scope_validation` (classifies prompt as APPROVED/VAGUE/MONOLITHIC) and `kernora_fetch_corporate_skills` (returns team's distilled methodology from the local DB, not hardcoded examples).

**Proxy Interceptor**
`interceptor_proxy.py` runs at localhost:2743. IDEs set this as their API base URL. Prompts are classified using a cheap LLM call before being forwarded to the real upstream model. Injects team skills into the system message for approved prompts.

**Team Dashboard**
Cloud-hosted aggregate view of token spend, session quality, bugs, and top skills across the team. Tenant-isolated via AWS Lake Formation. Access via the API Gateway at the team's provisioned endpoint.

---

## Out of Scope (Phase 0)

- Multi-tenant cloud dashboard
- SSO / enterprise auth
- Real-time collaboration
- VS Code extension (kiro-extension is a prototype, not shipped)
- Chrome extension

---

## Success Metrics (Phase 0)

- 10 individual developers actively using the local install (sessions being analyzed weekly)
- Average notification latency < 90 seconds from session end
- Zero reports of hook blocking or slowing the IDE
- Dashboard loads in < 500ms with 100 sessions in the DB
