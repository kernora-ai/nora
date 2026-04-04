# Kernora — Technical Design Document

**Version:** 0.1
**Status:** Phase 0 complete, Phase 1 in design

---

## Architecture Overview

Kernora has two deployment modes with a hard boundary between them.

**Mode A — BYOK Solo (default)**
Everything runs on the user's machine. No data leaves except the LLM API call the user makes with their own key. This mode is the foundation — it has to work perfectly before anything else ships.

**Mode B — Team (opt-in)**
Adds S3-backed skill sync and a cloud aggregate dashboard. Requires explicit configuration. Only skill strings (not transcripts) leave the machine.

---

## Local Stack

```
Claude Code session ends
        │
        ▼
   hook.py  (stdlib only, async, non-blocking)
        │  Unix socket  │  spool if offline
        ▼               ▼
   daemon.py       ~/.kernora/spool/
        │
   SQLite WAL
   ~/.kernora/echo.db
    ├── sessions table
    └── insights table
        │
        ▼ (hourly, or on-demand)
   analyzer.py  ──── LiteLLM ────► user's LLM provider
        │                          (Anthropic / Bedrock / Ollama / OpenAI / Gemini)
        ▼
   notifier.py  ──── macOS notification (Nora · Kernora)
        │
        ▼
   dashboard.py ──── Flask @ localhost:2742
```

### hook.py

Installed at `~/.claude/hooks/kernora_hook.py`. Registered as a Claude Code Stop hook with `async: true`. Uses stdlib only — no external dependencies, so it can never fail due to a missing package.

Reads session JSON from stdin: `session_id`, `transcript_path`, `cwd`, `usage`. Reads the transcript file, builds a payload dict, and attempts to send to `~/.kernora/daemon.sock` (Unix socket, 5-second timeout). If the daemon is unreachable, writes the payload to `~/.kernora/spool/` as a timestamped JSON file.

### daemon.py

Long-running background process managed by a LaunchAgent (`ai.kernora.daemon`). Three threads:

- **Main thread:** 60-second sleep loop, handles KeyboardInterrupt
- **socket_server thread:** Accepts connections on `~/.kernora/daemon.sock`, calls `store_session()` for each payload
- **analysis_loop thread:** Wakes hourly, fetches unanalyzed sessions from DB, calls `analyzer.analyze()` for each, writes results via `mark_analyzed()`, fires notification

On startup: initializes DB, replays any files in `~/.kernora/spool/`.

### db.py

SQLite with WAL journal mode. Two tables:

```sql
sessions (
    id           TEXT PRIMARY KEY,   -- Claude Code session_id
    project      TEXT,               -- cwd at session end
    started_at   TEXT,
    ended_at     TEXT,
    tokens_in    INTEGER DEFAULT 0,
    tokens_out   INTEGER DEFAULT 0,
    model        TEXT,
    turns_json   TEXT,               -- JSON array of conversation turns
    analyzed     INTEGER DEFAULT 0,
    inserted_at  TEXT DEFAULT (datetime('now'))
)

insights (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT REFERENCES sessions(id),
    analyzed_at      TEXT,
    themes           TEXT,           -- JSON array
    bugs             TEXT,           -- JSON array
    optimizations    TEXT,           -- JSON array
    prompt_quality   REAL DEFAULT 0, -- 0.0–1.0
    prompt_avg_words INTEGER DEFAULT 0,
    repetition_count INTEGER DEFAULT 0,
    skill_opportunity TEXT,          -- single CLAUDE.md rule string
    summary          TEXT,
    token_cost       INTEGER DEFAULT 0
)
```

`get_unanalyzed(limit)` and `mark_analyzed(session_id, insight)` are the primary read/write paths from daemon.py.

### analyzer.py

Takes a `session` dict (a row from the sessions table), extracts `turns_json`, chunks it into segments of ~3000 tokens, and runs a structured JSON prompt against the configured LLM via LiteLLM.

Provider selection from `~/.kernora/config.toml`:
- `anthropic` → `anthropic/claude-haiku-4-5-20251001` (default)
- `bedrock` → `bedrock/amazon.nova-lite-v1:0`
- `ollama` → `ollama/llama3.2:3b`
- `google` → `gemini/gemini-2.5-pro`
- `openai` → `openai/gpt-4o-mini`
- `grok` → `xai/grok-beta`
- `auto` → first available based on env vars

The Nora prompt instructs the model to return structured JSON with themes, bugs, optimizations, prompt quality score, skill opportunity, and summary. Markdown code fences are stripped if the model wraps the response despite `response_format: json_object`.

### notifier.py

Chain: macOS `osascript` → Linux `notify-send` → Discord webhook → stderr. Never raises — daemon continues regardless.

Env var `KERNORA_NOTIFY` can be set to `none`, `macos`, `linux`, `discord`, or `auto` (default).

### dashboard.py

Flask app. Binds to `127.0.0.1:2742` only — never exposed to the network. Five routes: `/`, `/sessions`, `/bugs`, `/learnings`, `/settings`. The `/settings` POST handler updates `provider = "..."` in config.toml via regex replace. `/health` returns JSON for monitoring.

All user-supplied data passed through `html.escape()` before rendering.

---

## MCP Server (Phase 1)

`kernora_mcp.py` implements the MCP stdio protocol (JSON-RPC 2.0). Two tools:

**kernora_scope_validation**
Receives `intent` (the user's prompt, verbatim) and `files_to_touch` (optional list). Returns APPROVED, VAGUE, or MONOLITHIC verdict with a concrete recommendation. Skill injection happens automatically on APPROVED — reads from `insights.skill_opportunity` in the local DB.

**kernora_fetch_corporate_skills**
Returns the last N skill opportunities from the local DB, plus recent bug patterns. These are real distilled insights from the user's own sessions — not hardcoded examples.

---

## Proxy Interceptor (Phase 1)

`interceptor_proxy.py` binds to `127.0.0.1:2743`. IDEs that support overriding the API base URL can point to this proxy. Scope classification uses a real LLM call (Haiku) rather than keyword matching to keep the false-positive rate low. On APPROVED, injects team skills into the system message before forwarding the request upstream via LiteLLM. Falls back gracefully if classifier is unavailable — never blocks the user.

---

## Team Swarm Sync (Phase 1)

`swarm_sync.py` is gated behind `mode.type = "team"` in config.toml. Only runs with explicit S3 bucket configuration. Syncs `skill_opportunity` strings only — one JSON file per unique skill (SHA-256 deduplicated). Never syncs raw session transcripts, source code, turns, or API keys.

---

## Cloud Backend (Phase 2)

`cloud_backend/kernora_cloud_stack.py` is an AWS CDK stack that provisions the team analytics infrastructure:

- S3 master bucket for encrypted skill storage (versioned, access-logged, SSL-enforced)
- S3 Tables (Apache Iceberg) for Athena-queryable session analytics
- Lake Formation row-level security for tenant isolation (filter: `org_id = CURRENT_USER`)
- Lambda provisioner for dynamic SaaS tenant onboarding (creates scoped IAM users)
- API Gateway with throttling (1000 req/s burst, DoS protection)

This stack is not deployed in Phase 0. It is designed but not activated until team sync has been validated with real users.

---

## Security Notes

- Hook uses stdlib only — no network calls, no API keys
- Unix socket is `chmod 600` — readable only by the owning user
- Dashboard binds to `127.0.0.1` only
- Proxy binds to `127.0.0.1` only
- All HTML output is `html.escape()`'d
- API keys stay in environment variables — never written to disk by Kernora
- Swarm sync is gated and opt-in — not part of default BYOK install

---

## File Map

```
kernora/
├── hook.py                  # Claude Code Stop hook (stdlib only)
├── daemon.py                # Background daemon (socket + analysis + spool replay)
├── db.py                    # SQLite schema + read/write functions
├── analyzer.py              # LiteLLM analysis — BYOK, multi-provider
├── notifier.py              # Notification chain (macOS / Linux / Discord / stderr)
├── dashboard.py             # Flask dashboard @ localhost:2742
├── kernora_mcp.py           # MCP server (scope validation + skill injection)
├── interceptor_proxy.py     # LLM proxy @ localhost:2743 (Phase 1)
├── swarm_sync.py            # Team S3 sync (team mode only)
├── install.sh               # Single-command installer + LaunchAgents
├── uninstall.sh             # Clean removal
├── config.toml.example      # Documented config template
├── requirements.txt         # Python deps
├── cloud_backend/           # AWS CDK stack (Phase 2, not deployed)
├── kernora-plugin/          # Claude plugin (skills + agents)
│   ├── agents/nora-weekly/  # Weekly digest subagent
│   └── skills/              # insights, dashboard, prompt-coach skills
└── docs/
    ├── PRFAQ.md
    ├── PRD.md
    ├── TECHNICAL_DESIGN.md
    └── architecture/        # strategy, competitive, onboarding docs
```
