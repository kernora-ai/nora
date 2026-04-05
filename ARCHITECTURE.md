# Kernora — Architecture Reference
# Last updated: March 2026
# All deployment modes, data flows, storage options, trust boundaries

---

## Overview

Kernora has four deployment modes. Every mode uses the same core components
(hook.py, daemon.py, analyzer.py, SQLite). They differ only in where data
goes after local analysis and who has access to it.

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

---

## Mode B — Team (S3 + IAM)

**Who:** Engineering teams of 5–50 developers. Manager wants team-wide patterns.
Developer wants their data to stay in their company's control.

**Data boundary:** Customer's own S3 bucket. Kernora reads via IAM role
that the customer creates and can delete at any time.

### Two storage sub-options

#### B1 — insights_only (default, recommended)

Only structured analysis goes to S3. Raw transcripts NEVER leave the
developer's machine.

```
DEVELOPER'S MACHINE                    CUSTOMER'S AWS ACCOUNT
┌──────────────────────────┐           ┌──────────────────────────────┐
│ hook.py → daemon         │           │ s3://acme/kernora/            │
│ → SQLite                 │           │   dev-1/echo.db (WAL stream) │
│ → LiteLLM (your key)     │           │     contains:                │
│   → bugs[]               │  Litestream│     • bugs[]                 │
│   → themes[]             │ ─────────▶│     • themes[]               │
│   → prompt_quality       │  WAL sync │     • prompt_quality         │
│   → skill_opportunity    │           │     • skill_opportunity       │
│   → summary              │           │     • summary                │
│                          │           │     NO turns_json            │
│ turns_json stays here ✓  │           │     NO raw transcripts ✓     │
└──────────────────────────┘           └──────────────────────────────┘
                                                    │
                                        Customer creates IAM role:
                                        kernora-reader
                                        → s3:GetObject, s3:ListBucket
                                        → scoped to s3://acme/kernora/*
                                        → trust: Kernora AWS account only
                                        Customer deletes role → Kernora blind
                                                    │
                                                    ▼
                                       KERNORA CONTROL PLANE
                                       ┌────────────────────────────┐
                                       │ Ingestion Lambda            │
                                       │ → assumes kernora-reader   │
                                       │ → reads S3 snapshots       │
                                       │ → aggregates team data     │
                                       │ → writes to S3 Tables      │
                                       │   (Kernora's own account)  │
                                       │                            │
                                       │ Athena → VP dashboard      │
                                       │ acme.kernora.ai            │
                                       └────────────────────────────┘
```

#### B2 — raw_and_insights (opt-in)

Full session content AND analysis go to the customer's S3 bucket.
Enables Kernora to re-analyze sessions with newer/better models in future.
Customer still owns the bucket. Customer can delete it anytime.

```
DEVELOPER'S MACHINE                    CUSTOMER'S AWS ACCOUNT
┌──────────────────────────┐           ┌──────────────────────────────┐
│ hook.py → daemon         │           │ s3://acme/kernora/            │
│ → SQLite (full schema)   │  Litestream│   dev-1/echo.db              │
│ → LiteLLM analysis       │ ─────────▶│     contains:                │
│                          │  WAL sync │     • bugs[], themes[], etc  │
│ turns_json: stored here  │           │     • turns_json (full       │
│ AND synced to S3         │           │       session transcript)    │
└──────────────────────────┘           └──────────────────────────────┘
                                                    │
                                        Same IAM role as B1.
                                        Customer controls what's in
                                        their bucket. They can delete
                                        the bucket entirely at any time.
                                                    │
                                                    ▼
                                       KERNORA CONTROL PLANE
                                       ┌────────────────────────────┐
                                       │ Same as B1, PLUS:          │
                                       │ → can re-analyze raw turns │
                                       │   with newer models        │
                                       │ → richer insights over time│
                                       └────────────────────────────┘
```

**Config:**
```toml
[mode]
type = "team"

[storage]
s3_content = "insights_only"   # or "raw_and_insights"

[s3]
enabled = true
bucket  = "acme-corp-kernora"
prefix  = "kernora/sessions"
region  = "us-east-1"

[team]
kernora_role_arn = "arn:aws:iam::123456789:role/kernora-reader"
team_id          = "team_abc123"
```

---

## Mode C — Enterprise

Same as Team (Mode B) but:
- Per-org S3 prefix isolation (multiple business units in one enterprise)
- Dedicated IAM role per org
- SSO / SAML via Cognito
- SLA, audit logs, dedicated support
- Deployed via AWS SaaS Builder Toolkit (MIT-0)

**Config:** Same as Team with additional `[enterprise]` section.

---

## Mode D — Air-gapped (Phase 3)

For banks, defense contractors, government agencies that cannot use any
external service. Everything runs on-premise.

```
CUSTOMER'S ON-PREMISE NETWORK (no external internet)
┌────────────────────────────────────────────────────┐
│ Developers: hook.py → daemon → SQLite → LiteLLM   │
│             (Ollama running on-premise)             │
│                                                    │
│ Litestream → MinIO (on-premise S3-compatible)      │
│                                                    │
│ Kernora control plane: deployed in customer VPC    │
│ → Lambda equivalent (ECS Fargate)                  │
│ → Reads MinIO instead of S3                        │
│ → VP dashboard served internally                  │
└────────────────────────────────────────────────────┘
```

---

## IAM Role — What the customer creates

The customer creates this once during team onboarding. Kernora provides
the exact JSON to paste into their AWS console.

**Trust policy** (who can assume this role):
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "AWS": "arn:aws:iam::KERNORA_ACCOUNT_ID:role/kernora-ingestion"
    },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {
        "sts:ExternalId": "CUSTOMER_TEAM_ID"
      }
    }
  }]
}
```

**Permission policy** (what Kernora can do):
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::CUSTOMER_BUCKET",
      "arn:aws:s3:::CUSTOMER_BUCKET/kernora/*"
    ]
  }]
}
```

Read-only. Scoped to the `kernora/` prefix only. The ExternalId
condition prevents confused deputy attacks. Customer deletes the role
→ Kernora gets a 403 on next scheduled run → access permanently revoked.

---

## Litestream — how it connects

Litestream runs as a sidecar alongside the Kernora daemon. Zero code
changes to any Kernora Python file. It watches the SQLite WAL and
streams changed pages to S3 continuously (~1s lag).

For `insights_only` mode: Litestream watches a **view-based shadow DB**
that contains only the insights table, not the sessions table with
turns_json. This guarantees raw transcripts are never in the WAL stream.

For `raw_and_insights` mode: Litestream watches the full echo.db.

**Litestream config (~/.kernora/litestream.yml):**
```yaml
# insights_only mode
dbs:
  - path: /root/.kernora/insights_only.db   # shadow DB, no turns_json
    replicas:
      - type: s3
        bucket: ${KERNORA_S3_BUCKET}
        path: kernora/sessions/${KERNORA_DEV_ID}
        region: ${KERNORA_S3_REGION}
        sync-interval: 1s
```

```yaml
# raw_and_insights mode
dbs:
  - path: /root/.kernora/echo.db            # full DB including turns_json
    replicas:
      - type: s3
        bucket: ${KERNORA_S3_BUCKET}
        path: kernora/sessions/${KERNORA_DEV_ID}
        region: ${KERNORA_S3_REGION}
        sync-interval: 1s
```

---

## Storage option decision guide

```
Developer asking: "Does Kernora see my code?"

  → BYOK solo:       No. Nothing leaves your machine.
  → Team insights_only: No. Analysis scores only. No code, no prompts.
  → Team raw_and_insights: Your transcripts go to YOUR S3 bucket.
                            Kernora reads them via your IAM role.
                            You control the bucket. You can delete it.

Manager asking: "Can we re-analyze old sessions with better models?"
  → Only with raw_and_insights. That's the tradeoff.
  → You own the data in your S3 bucket regardless.
```

---

## Kernora control plane — what it does with S3 data

1. **Scheduled Lambda** (every 15 min) assumes each tenant's IAM role
2. Reads new Litestream WAL segments since last run (incremental)
3. Deserializes SQLite snapshot into memory
4. Runs aggregation SQL:
   - Top bugs by frequency across all team members
   - Prompt quality trend per developer and squad
   - Skill opportunities ranked by estimated hours saved
   - Token cost by model and developer
5. Writes results to Kernora's own S3 Tables (Apache Iceberg format)
6. Athena named queries serve the VP dashboard
7. For `raw_and_insights`: optionally re-runs LiteLLM analysis with
   latest model version, writes enriched insights back to Iceberg

The Lambda never writes back to the customer's bucket.
The Lambda only reads from the customer's bucket.
If the IAM role is revoked, the Lambda logs a 403 and skips that tenant.

---

## rqlite — when it's used

rqlite (distributed SQLite with Raft consensus) is used only for
**air-gapped enterprise** deployments where the team needs a fully
local distributed cluster without S3.

For all other team deployments, rqlite is NOT needed. The architecture is:
- Each developer runs their own local SQLite (single node, simple)
- Litestream syncs their individual SQLite to their prefix in S3
- Kernora's control plane aggregates across all prefixes

This is simpler than rqlite because developer laptops move between
networks (office, home, coffee shop) and a Raft cluster requiring
quorum would constantly lose leadership as nodes go offline.

---

## Build phases

| Phase | Mode | Storage | Key components |
|-------|------|---------|----------------|
| 0 (done) | BYOK solo | Local SQLite only | hook, daemon, analyzer, dashboard |
| 0 Batch 6 | BYOK solo + S3 | SQLite + Litestream | Add Litestream, shadow DB |
| 1 Sprint 1 | + Claude Code plugin | — | Plugin, MCP server |
| 1 Sprint 2 | + VS Code extension | — | Iframe wrapper |
| 1 Sprint 3 | Team B1 | insights_only → S3 | Team onboarding, ingestion Lambda, VP dashboard |
| 1 Sprint 4 | Team B2 | raw_and_insights → S3 | Storage toggle, re-analysis Lambda |
| 2 | Enterprise | Per-org S3 + SSO | SBT, Cognito, dedicated IAM |
| 3 | Air-gapped | MinIO + rqlite | On-premise Kernora deploy |
