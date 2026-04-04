# Nora Tier Strategy — Product Requirements Document

**Version:** 1.0
**Date:** April 1, 2026
**Owner:** Mihir Choudhary
**Status:** Draft for review

---

## The Core Insight

Nora's 16 MCP tools are the hook. Data persistence is the upgrade path. Team intelligence is the expansion. The tools themselves should never be gated — gating tools punishes the solo dev who is your evangelist. Instead, gate the *infrastructure* that makes tools compound over time.

A solo developer running `nora sofac` on day one gets a factory health check. That same developer running `nora sofac` after 90 days of persistent session history gets a factory health check *plus* trend analysis, pattern regression detection, and self-healing rule suggestions drawn from three months of institutional memory. Same tool. Radically different output. The persistence layer is what creates the difference — and that's what they pay for.

---

## Tool Audit: The 16 Nora Tools

Before defining tiers, every tool needs an honest assessment: is it complete enough to deliver standalone value in Open? Does it have a natural "enhanced" version that persistence unlocks?

### Category 1: Session Intelligence (the foundation)

| # | Tool | What It Does | Open Completeness | Enhancement with Persistence |
|---|------|-------------|-------------------|------------------------------|
| 1 | `nora_search` | Full-text search across patterns, decisions, bugs | **Complete.** Searches echo.db. Works from session one. | Cross-project search. "Find every time I hit a CORS bug across all my repos." |
| 2 | `nora_session` | Drill into a specific session's transcript and analysis | **Complete.** Shows full session detail. | Session comparison. "Compare this session with the one where I fixed it last time." |
| 3 | `nora_stats` | Dashboard overview — sessions, patterns, bugs, tokens | **Complete.** Immediate value. | Trend lines. Week-over-week improvement curves. Cost-per-feature tracking. |
| 4 | `nora_patterns` | Learned coding patterns with effectiveness scores | **Complete.** Extracts patterns from git + LLM analysis. | Cross-project pattern transfer. Pattern that works in Project A gets suggested in Project B. |
| 5 | `nora_decisions` | Architectural decisions captured from sessions | **Complete.** Records choices and rationale. | Decision search across all projects. "Did I already solve this auth architecture question?" |
| 6 | `nora_bugs` | Known bugs with severity, status, fix code | **Complete.** Tracks open/resolved bugs. | Bug recurrence detection across projects. Recurring bug auto-escalates to CLAUDE.md rule. |
| 7 | `nora_skills` | Distilled methodology — rules + bug patterns to avoid | **Complete.** Grows with each analyzed session. | Skill sharing. Export your playbook. Import a teammate's. |
| 8 | `nora_scan` | Bootstrap from git history | **Complete.** Seeds echo.db from commit log. | Deep scan mode: analyze actual session transcripts (not just commits) from backed-up history. |

**Verdict:** All 8 session intelligence tools are complete for Open. Persistence enhances them but doesn't gate them.

### Category 2: Code Quality (the differentiation)

| # | Tool | What It Does | Open Completeness | Enhancement with Persistence |
|---|------|-------------|-------------------|------------------------------|
| 9 | `nora_pe_review` | 4-tier Principal Engineer code audit | **Complete.** CRITICAL → HIGH → MEDIUM → LOW with file:line references. | Historical PE review tracking: "These 3 findings were also flagged 2 weeks ago — they're regressions." PR-level review with Approve/Block verdict. |
| 10 | `nora_scope_validation` | Safety check before multi-file edits | **Complete.** Warns on >6 files, injects relevant patterns. | Scope history: "Last time you touched >8 files in auth/, it introduced 3 bugs. Decompose first." |
| 11 | `nora_coe` | Technical COE — 5 Whys with evidence collection | **Complete.** Phase 2.5 evidence collection. Git blame timeline. Prevention rules. Self-healing proven (Article 38). | COE history: "This is the 3rd COE involving the upload pipeline. Systemic architectural issue detected." Auto-trigger on build failure. |
| 12 | `nora_coe_product` | Product COE — why was this built wrong | **Complete.** Traces spec → implementation → what shipped. | Product decision audit trail: "You've deferred this feature 4 times. Either build it or kill it." |

**Verdict:** All 4 code quality tools are complete for Open. The PE review and COE are Nora's crown jewels — the tools that create the "this tool just fixed itself" moments. Gating these would be product suicide. Persistence makes them *smarter*, not *functional*.

### Category 3: Factory & Operations (the system view)

| # | Tool | What It Does | Open Completeness | Enhancement with Persistence |
|---|------|-------------|-------------------|------------------------------|
| 13 | `nora_retro` | Engineering retrospective — git velocity, quality signals | **Complete.** Analyzes last N days of commits. | Retro comparison: "Your fix-to-feature ratio improved 20% vs last month." Investor-ready metric extraction. |
| 14 | `nora_sofac` | Factory health check — commits, pending work, self-healing | **Complete.** GREEN/YELLOW/RED status. Detects self-healing opportunities. | Factory trend: "Build health has been YELLOW for 3 consecutive checks. Investigate before it goes RED." Scheduled heartbeat (cron). |
| 15 | `nora_inventory` | Feature inventory audit — SHIP/POLISH/WIRE/BLOCKER | **Complete.** Walks project surface area, categorizes features. | Inventory diff: "Since last inventory, 3 features moved from WIRE → SHIP. 1 new BLOCKER appeared." Release readiness tracking over time. |
| 16 | `nora_help` | Meta — lists all tools | **Complete.** | N/A |

**Verdict on Sofac:** Keep it in Open. Here's why:

Sofac is the tool that makes a solo developer feel like they're running a real engineering operation, not just hacking on a weekend project. It's the "factory floor manager in your pocket." The moment a developer runs `nora sofac` and sees their project health in GREEN/YELLOW/RED with self-healing suggestions — that's the moment they become an evangelist. Moving sofac to enterprise removes the single most differentiating experience from the free tier.

The Kiro Powers version of Sofac is a 7-stage pipeline with 8 subagents, Jira/Linear sync, burndown charts, and scheduling. That's a different product. Nora's sofac is a health check. The pipeline orchestration is what belongs in Teams/Enterprise — not the health check itself.

**The pattern:** Open gets the tool. Pro gets persistence that makes it smarter. Teams gets the orchestration layer on top.

---

## The Tier Structure

### Tier 1: Nora Open — Free, Forever

**Who:** Solo developers using Claude Code, Kiro, or Cursor. The Priyas.

**What they get:** All 16 tools. Full functionality. Local echo.db. Git-native. BYOK (their own LLM API key for session analysis). Zero network calls. Zero accounts.

**What they don't get:** Persistence beyond the local machine. Cross-project intelligence. Scheduled operations. Auto-triggers.

**Why free:** The solo developer is the distribution engine. Every Priya who installs Nora and tells two colleagues generates more value than a $10/month subscription. Free Open creates the funnel. The tools are complete enough that most solo developers never need to upgrade — and that's fine. Their word-of-mouth is the payment.

**Completeness audit — gaps to close before launch:**

| Gap | Impact | Fix | Effort |
|-----|--------|-----|--------|
| No auto-CLAUDE.md update | Highest-value automation isn't wired | Wire `nora_skills` output → append to CLAUDE.md on session end | S |
| No weekly digest | Priya can't see improvement over time without checking dashboard | Generate markdown digest from `nora_retro(7)` output, show via macOS notification | M |
| No Cursor/Windsurf hook | Limits TAM to Claude Code + Kiro users | Add hook adapters for Cursor (`.cursor/hooks/`) and Windsurf session dirs | M |
| `nora_scan` imports only commits, not session transcripts | Cold start is shallow — patterns are commit-message-level, not conversation-level | Parse `.claude/projects/` session JSONL files during scan | M |
| No "what changed since last time" on sofac | Sofac is a snapshot, not a diff | Cache previous sofac output in echo.db, diff on next run | S |

These 5 gaps are the difference between "useful tool" and "tool I can't live without." Close them before any tier work.

### Tier 2: Nora Pro — BYOS (Bring Your Own Storage)

**Who:** Solo developers who want their intelligence to persist and compound. The Priya who's been using Open for 30 days and realizes her echo.db is the most valuable file on her machine.

**What triggers the upgrade:** The moment a developer loses their echo.db (machine swap, OS reinstall, disk failure) or wants to search across multiple projects from one place.

**What they get:** Everything in Open, plus:

1. **Persistent Storage Layer** — Connect a Cloudflare R2 bucket (recommended) or S3-compatible store. Nora syncs echo.db insights to the bucket via Litestream. Session intelligence survives machine changes, travels across devices, and compounds indefinitely.

2. **Cross-Project Intelligence** — With all projects' insights in one bucket, Nora can: search across all repos ("find every CORS fix I've done"), transfer patterns ("this retry logic from Project A applies to Project B"), and detect recurrence across codebases ("you've hit this SQLite locking bug in 3 different projects").

3. **Enhanced Tool Outputs** — Same 16 tools, richer results:
   - `nora_pe_review` → includes regression detection ("this finding was also flagged 3 weeks ago")
   - `nora_coe` → includes COE history ("3rd COE involving this subsystem — consider architectural review")
   - `nora_retro` → includes week-over-week comparison and trend lines
   - `nora_sofac` → includes delta since last check and trend direction
   - `nora_scope_validation` → includes outcome tracking ("last time you touched 8+ files here, 2 bugs resulted")

4. **Auto-CLAUDE.md Sync** — Prevention rules from COEs and high-effectiveness patterns auto-append to CLAUDE.md. The developer reviews and approves via diff — Nora never force-writes.

5. **Scheduled Operations** — Weekly retro digest (email or local notification). Sofac heartbeat (configurable interval). Auto-scan on new project clone.

6. **COE Auto-Triggers** — Hook into build failures, test failures, and crash reports. When a build breaks, Nora auto-runs COE on the failing commit. The developer wakes up to a root cause analysis, not a red CI badge.

**Storage recommendation — Cloudflare R2:**

| Factor | Cloudflare R2 | AWS S3 | Backblaze B2 |
|--------|---------------|--------|--------------|
| Egress cost | $0 (free forever) | $0.09/GB | $0.01/GB |
| Free tier | 10 GB storage, 1M reads/mo (permanent) | 5 GB, 12-month only | 10 GB (permanent) |
| S3-compatible API | Yes | Native | Yes |
| Setup complexity | ~5 minutes (API token) | ~10 minutes (IAM policy) | ~5 minutes (app key) |
| Reliability | Enterprise (Cloudflare infra) | Enterprise (AWS) | Enterprise (Backblaze) |
| Developer trust | High (Cloudflare brand, $0 egress messaging) | Highest (AWS is default) | Medium (less known) |
| Litestream support | Yes (S3-compatible) | Yes (native) | Yes (S3-compatible) |

**Recommendation:** Default to R2. Offer S3 and B2 as alternatives. The $0 egress is the selling point — developers can read their own data as much as they want without cost anxiety. A typical Nora Pro user generates ~50-200 MB of insights per year. That's well within R2's permanent free tier for storage. The developer's only cost is the Nora Pro subscription.

**What the developer does:**
1. Create an R2 bucket (free Cloudflare account, 2 minutes)
2. Generate an API token with read/write on that bucket (1 minute)
3. Run `nora config storage --provider r2 --bucket my-nora --access-key ... --secret-key ...`
4. Nora starts syncing. Done.

**Pricing:** $9/month or $89/year.

**Why $9:** It's below the "needs manager approval" threshold for most solo devs. It's impulse-buy territory for someone who's been using Open for 30 days and values their echo.db. It's also exactly the price point where the value prop is obvious: "One avoided debugging session per month pays for this." Copilot Individual is $10/mo. Cursor Pro is $20/mo. Nora Pro at $9/mo sits just below both, signaling "addition to your stack, not replacement."

### Tier 3: Nora for Teams — Shared Intelligence

**Who:** Engineering leads (the Alexes) managing 5-50 developers who all use AI coding tools.

**What triggers the upgrade:** Alex sees Priya using Nora. Alex wants the same visibility across the whole team. The question is always: "Is our AI investment actually working?"

**What they get:** Everything in Pro, plus:

1. **Shared Team Memory** — Patterns, decisions, and bug knowledge visible across the team. When Developer A discovers a fix for a database locking issue, Developer B gets that pattern injected in their next session. The team's institutional knowledge compounds instead of siloing in individual echo.dbs.

2. **Aggregate Retrospectives** — Team-level retro: total commits across all developers, team fix-to-feature ratio, bug density by developer (anonymizable), prompt quality distribution. Alex can answer "how is the team doing this sprint?" with data.

3. **Team Dashboard** — Web-based dashboard (team.kernora.ai or self-hosted) showing: developer activity heatmap, bug pattern frequency across team, scope warning rates, token cost by developer/model, skill adoption tracking.

4. **Sofac Pipeline** — The full factory orchestration layer. Not just a health check (that's Open), but a pipeline: detect completed work → queue next task → verify quality → schedule follow-up. Integrates with GitHub Issues/PRs for task tracking. This is the Kiro Powers-level Sofac, adapted for Nora's architecture.

5. **Team CLAUDE.md Management** — Centralized rules that apply to all team members' sessions. Alex adds a rule ("always validate JWT expiry before token refresh"), it propagates to every developer's skill injection. Individual developers can add their own rules on top.

6. **Admin Controls** — Who can see whose data. Anonymized mode (Alex sees quality metrics but not individual session content). SSO integration (Google Workspace, Okta, Azure AD).

7. **Weekly Team Digest** — Automated Friday email: top 3 bugs across the team, prompt quality trend, wins of the week, risks to watch. Alex copy-pastes the highlights into their CEO update.

**Storage:** Team bucket (one R2/S3 bucket for the team, managed by the team lead). Individual developers' insights (not raw transcripts) sync to the team bucket. Raw session transcripts never leave the developer's machine unless the team opts into `raw_and_insights` mode.

**Pricing:** $29/month for up to 10 developers. $49/month for up to 25. $99/month for up to 50. Per-developer pricing above 50 ($3/dev/month).

**Why this structure:** The "up to N" tiers avoid the nickel-and-dime feeling of pure per-seat pricing. A 10-person team pays $29/month total, not $29 × 10. This makes it easy for Alex to expense without justification. The jump from $29 → $49 at 10 developers is natural team growth. The per-developer pricing above 50 is for the Davids — and at that scale, $3/dev/month is a rounding error on their AI budget.

### Tier 4: Nora Enterprise — Compliance & Control

**Who:** CTOs at regulated companies (fintech, healthtech, defense). The Davids. 50-500+ developers.

**What triggers the upgrade:** Legal/compliance won't approve a tool unless it has SSO, audit logs, data residency controls, and a contractual SLA.

**What they get:** Everything in Teams, plus:

1. **SSO/SAML** — Cognito-backed or BYO IdP. Enforce enrollment across the org.
2. **Audit Logs** — Every session analyzed, every pattern applied, every COE triggered. Exportable for compliance reporting. Regulator asks "what AI tools touched what code?" — David has the answer.
3. **Data Residency** — Choose bucket region. Per-business-unit prefix isolation. GDPR compliance by construction.
4. **Air-Gapped Deployment** — MinIO + on-prem compute for defense/gov. No data leaves the network.
5. **Custom Integrations** — MCP connectors for Jira, Linear, CloudWatch, PagerDuty, Datadog. COE auto-triggers from production incidents. Sofac pipeline reads from and writes to project management tools.
6. **Contractual SLA** — 99.9% uptime for hosted dashboard. Priority support.
7. **Quarterly Compliance Report** — Auto-generated. AI tool usage across the org, risk signals, governance posture. Board-ready.

**Pricing:** Custom. Starting at $500/month. Annual contracts.

---

## The Tool Enhancement Matrix

This is the key architectural decision: which capabilities unlock at which tier. The principle is **same tool, richer output** — never gated tools.

| Tool | Open | Pro (BYOS) | Teams | Enterprise |
|------|------|-----------|-------|------------|
| `nora_search` | Search local echo.db | Search across all projects | Search across team | Search across org with access controls |
| `nora_session` | View session detail | Compare sessions across time | View team member sessions (opt-in) | Audit trail for all sessions |
| `nora_stats` | Snapshot stats | Trend lines over time | Team aggregate stats | Org-wide dashboard |
| `nora_patterns` | Local patterns | Cross-project pattern transfer | Shared team patterns | Org-wide pattern library |
| `nora_decisions` | Local decisions | Decision search across projects | Team decision log | Architecture decision records (ADR) integration |
| `nora_bugs` | Local bug tracking | Cross-project recurrence | Team bug frequency analysis | Org-wide bug heatmap |
| `nora_skills` | Local playbook | Auto-CLAUDE.md sync | Shared team playbook | Org-wide methodology enforcement |
| `nora_scan` | Git commit scan | Deep scan (session transcripts) | Team-wide scan | Org-wide with compliance filters |
| `nora_pe_review` | 4-tier audit | + Regression detection | + Team code quality baseline | + Compliance-specific checks (SOC2, HIPAA) |
| `nora_scope_validation` | File count warning | + Outcome tracking | + Team scope policies | + Policy enforcement (hard block) |
| `nora_coe` | 5 Whys investigation | + COE history + auto-trigger | + Cross-team COE correlation | + Incident integration (PagerDuty/Datadog) |
| `nora_coe_product` | Product investigation | + Decision audit trail | + Cross-team product alignment | + Roadmap integration |
| `nora_retro` | N-day retrospective | + Week-over-week comparison | + Team aggregate retro | + Org-wide engineering health report |
| `nora_sofac` | Health check (snapshot) | + Delta tracking + heartbeat | + Sofac Pipeline (orchestration) | + Jira/Linear sync + burndown |
| `nora_inventory` | Feature categorization | + Inventory diff over time | + Cross-project inventory | + Release readiness gate |
| `nora_help` | Tool listing | Tool listing | Tool listing | Tool listing |

---

## Why Sofac Stays in Open

This deserves its own section because the instinct to move "premium-feeling" tools to paid tiers is strong but wrong here.

**The self-healing loop is Nora's signature moment.** Article 38 documents it: Nora couldn't tell the developer it was running. The developer asked Nora to investigate itself. 54 seconds later, Nora found the bug, wrote the fix, and generated a prevention rule. That loop is: `sofac detects → coe investigates → fix committed → sofac verifies → rule added to CLAUDE.md → future sessions are better`.

If sofac is enterprise-only, the loop breaks for 95% of users. The most viral moment in Nora's entire value proposition becomes invisible to the people most likely to tell others about it.

**What moves to Teams/Enterprise is Sofac *Pipeline* — not Sofac *Check*:**

| Sofac Check (Open) | Sofac Pipeline (Teams/Enterprise) |
|--------------------|----------------------------------|
| Recent commits categorized | Task queue with priority ordering |
| Pending work (TODO/FIXME scan) | Task scheduling across team members |
| Self-healing opportunities | Auto-chain: completed task → trigger next |
| Build/test/lint health (one-shot) | Continuous monitoring with alerting |
| GREEN/YELLOW/RED status | Burndown charts with velocity tracking |
| — | Jira/Linear/GitHub Issues sync |
| — | Multi-agent orchestration (assign to XCP, Web Agent, etc.) |
| — | Quality gate enforcement (PE review before merge) |

The check is the tool. The pipeline is the orchestration layer. Tools are free. Orchestration is paid.

---

## Revenue Model

### Unit Economics (Pro)

| Metric | Value |
|--------|-------|
| Price | $9/month ($89/year) |
| COGS per user | ~$0 (user provides their own storage, their own LLM key) |
| Infrastructure cost | Litestream sync is local process. Scheduled operations are local cron. |
| Gross margin | ~95%+ |

The BYOS model means Kernora has near-zero marginal cost per Pro user. The user provides the storage. The user provides the LLM API key. Kernora provides the software. This is a pure software margin business at the Pro tier.

### Unit Economics (Teams)

| Metric | Value |
|--------|-------|
| Price | $29-99/month per team |
| COGS per team | ~$5-15/month (hosted dashboard compute, Lambda invocations for aggregation) |
| Infrastructure | Team dashboard hosting, ingestion Lambda, aggregation pipeline |
| Gross margin | ~80-85% |

Teams introduces hosted infrastructure (dashboard, aggregation). But the heavy lifting (session analysis, pattern extraction) still happens locally on each developer's machine. The hosted layer is lightweight aggregation and display.

### Pricing Positioning in the Market

| Tool | Solo | Team | Enterprise |
|------|------|------|-----------|
| **GitHub Copilot** | $10/mo | $19/seat/mo | $39/seat/mo |
| **Cursor** | $20/mo | $40/seat/mo | Custom |
| **Claude Code** | $20/mo (Max) | $30/seat/mo | $200/seat/mo |
| **Kiro** | Free | Free | $19/seat/mo (Pro), custom |
| **Nora Open** | **Free** | — | — |
| **Nora Pro** | **$9/mo** | — | — |
| **Nora for Teams** | — | **$29-99/mo (team)** | — |
| **Nora Enterprise** | — | — | **$500+/mo (org)** |

**Key differentiators:**
- Nora is *additive*, not *competitive*. It works alongside Copilot, Cursor, Claude Code, Kiro — it doesn't replace any of them. This means the pricing doesn't compete head-to-head. $9/month for Nora Pro on top of $20/month for Claude Code is $29/month total — still cheaper than Cursor Pro + a coffee.
- Per-team pricing (not per-seat) at the Teams tier makes the TCO dramatically lower than competitors' per-seat models. A 10-person team on Nora Teams pays $29/month. The same team on Copilot Business pays $190/month.
- BYOS eliminates the "where does my data go?" question that blocks enterprise adoption of every other tool.

### Revenue Projections (Conservative)

Assumptions: 1,000 Open installs in first 6 months (developer tools typically see 5-10% install-to-active). 5% Pro conversion (industry average for freemium dev tools). 2% Teams conversion (from Pro users who become team leads).

| Month | Open Users | Pro ($9/mo) | Teams ($49/mo avg) | MRR |
|-------|-----------|-------------|---------------------|-----|
| 3 | 300 | 15 | 0 | $135 |
| 6 | 1,000 | 50 | 3 | $597 |
| 12 | 3,000 | 150 | 10 | $1,840 |
| 18 | 8,000 | 400 | 25 | $4,825 |
| 24 | 15,000 | 750 | 50 | $9,200 |

These are conservative numbers. The key accelerant is whether Nora ships as a Kiro/Claude Code plugin (marketplace distribution) or relies on organic `curl install` adoption. Marketplace distribution could 10x the install base.

---

## Competitive Moat

### Why Persistence + BYOS Is Defensible

GitHub Copilot and Cursor are code completion tools. They don't store session history. They don't learn from your mistakes. They don't build institutional memory. They have no concept of "you hit this same bug 3 weeks ago."

Claude Code has "Auto Memory" (memory.md) and Kiro has Powers — but these are prompt-level, not data-level. They don't analyze sessions for quality, they don't track bug recurrence, they don't run retrospectives. They're static context injection, not dynamic intelligence.

Nora's moat is the **compounding data flywheel:**

```
Session → Analysis → Pattern/Bug/Decision → Stored in echo.db → Synced to BYOS →
→ Injected into next session → Better session → Richer analysis → Deeper patterns
```

Each session makes the next session better. After 90 days, a Nora Pro user's intelligence store is irreplaceable. They can't switch to a competing tool without losing 90 days of compounded learning. This is the stickiest kind of lock-in: the user's own data, on their own storage, that they don't want to lose.

### Why Open Source Core + Proprietary Extensions Works

The MCP server (`nora_mcp.py`) and the local analysis pipeline are open source (Elastic License 2.0). Anyone can read the code, verify there's no telemetry, contribute improvements. This builds trust with security-conscious developers (David persona).

The Pro/Teams/Enterprise enhancements (cross-project intelligence, Sofac Pipeline, team dashboard, compliance tooling) are proprietary. They build on the open core but require the Kernora commercial license.

This is the GitLab/Elastic/HashiCorp playbook: open core for trust and distribution, commercial extensions for revenue.

---

## Storage Architecture: BYOS Deep Dive

### What Gets Stored (and What Doesn't)

| Data Type | Stored Locally (echo.db) | Synced to BYOS | Notes |
|-----------|------------------------|----------------|-------|
| Session transcripts (raw) | Yes | **No** (default) | Raw transcripts contain code. Never synced unless user opts into `raw_and_insights` mode. |
| Session metadata (timestamp, model, token count) | Yes | Yes | Lightweight. No code content. |
| Patterns (effectiveness-scored) | Yes | Yes | Distilled insights, not raw code. |
| Decisions (choice + rationale) | Yes | Yes | Architectural summaries. |
| Bugs (severity + fix code) | Yes | Yes | Fix patterns are the high-value data. |
| Skills (rules + anti-patterns) | Yes | Yes | The team playbook. |
| Quality scores | Yes | Yes | Numeric scores, no code content. |
| Theme summaries | Yes | Yes | Short text summaries. |

**Privacy guarantee:** In `insights_only` mode (the default for BYOS), raw session transcripts never leave the developer's machine. Only distilled intelligence (patterns, decisions, bugs, scores) syncs to the bucket. This is the same guarantee that got Legal to approve Kernora in the existing PRODUCT_STRATEGY.md (David persona).

### Litestream Sync Architecture

```
Developer's Machine                          BYOS Bucket (R2/S3/B2)
┌─────────────────┐                         ┌──────────────────┐
│  echo.db (WAL)  │──── Litestream ────────►│  insights.db     │
│  (full data)    │     (continuous sync)    │  (insights only) │
└─────────────────┘                         └──────────────────┘
                                                     │
                                            ┌────────┴────────┐
                                            │ Cross-project    │
                                            │ query engine     │
                                            │ (Pro feature)    │
                                            └─────────────────┘
```

Litestream replicates the SQLite WAL (write-ahead log) to the BYOS bucket continuously. For `insights_only` mode, a filtered view excludes the `turns_json` column from the `sessions` table. The bucket contains everything needed for cross-project intelligence but zero raw code.

### Setup Flow (Target: Under 3 Minutes)

**R2 (recommended):**
```bash
# 1. Create bucket (Cloudflare dashboard or CLI)
wrangler r2 bucket create nora-intelligence

# 2. Create API token (R2 read/write scope)
# → Cloudflare dashboard → API Tokens → Create Token → R2 Read & Write

# 3. Configure Nora
nora config storage \
  --provider r2 \
  --endpoint https://<account-id>.r2.cloudflarestorage.com \
  --bucket nora-intelligence \
  --access-key <key> \
  --secret-key <secret>

# 4. Verify
nora storage status
# → "Syncing to R2: nora-intelligence | 47 insights | Last sync: 2s ago"
```

**S3:**
```bash
nora config storage \
  --provider s3 \
  --bucket my-nora-bucket \
  --region us-east-1 \
  --access-key <key> \
  --secret-key <secret>
```

**B2:**
```bash
nora config storage \
  --provider b2 \
  --bucket my-nora-bucket \
  --key-id <id> \
  --app-key <key>
```

---

## Naming: "Nora for Teams" Not "Enterprise"

The word "enterprise" signals: long sales cycles, custom contracts, procurement departments, and minimum 6-figure deals. That's Tier 4, not Tier 3.

Tier 3 — the team tier — should feel accessible to an engineering lead who can expense $49/month on a corporate card. "Nora for Teams" is the right name. It says: "this is for your team, not your procurement department."

| Tier | Name | Signal |
|------|------|--------|
| Free | **Nora Open** | "Open source, open access, open book." |
| $9/mo | **Nora Pro** | "Professional developer who takes their craft seriously." |
| $29-99/mo | **Nora for Teams** | "Your team, not your procurement department." |
| Custom | **Nora Enterprise** | "Legal, compliance, and the board are involved." |

---

## Implementation Roadmap

### Phase 0 (Now): Close Open Gaps

| Task | Effort | Impact |
|------|--------|--------|
| Auto-CLAUDE.md update from nora_skills output | S (2 days) | Highest-value automation for Priya |
| Weekly digest via macOS notification | M (3 days) | Visible improvement loop |
| Sofac delta tracking (cache previous, diff on next) | S (1 day) | Transforms sofac from snapshot to trend |
| Deep scan (parse .claude/projects/ session JSONL) | M (3 days) | Richer cold start |
| Cursor/Windsurf hook adapters | M (4 days) | 2-3x TAM expansion |

### Phase 1 (Month 1-2): Ship Pro

| Task | Effort | Impact |
|------|--------|--------|
| Litestream BYOS sync (R2/S3/B2) | M (1 week) | Foundation for all paid tiers |
| Cross-project query engine | M (1 week) | Core Pro differentiator |
| Enhanced tool outputs (regression detection, delta tracking) | M (1 week) | "Same tool, smarter output" |
| COE auto-trigger on build failure | S (3 days) | Self-healing at scale |
| Stripe billing + license validation | M (1 week) | Monetization infrastructure |
| `nora config storage` CLI flow | S (2 days) | Under-3-minute setup |

### Phase 2 (Month 3-4): Ship Teams

| Task | Effort | Impact |
|------|--------|--------|
| Team bucket aggregation pipeline | L (2 weeks) | Foundation for team features |
| Shared team patterns/skills/bugs | M (1 week) | Cross-pollination of knowledge |
| Team dashboard (web) | L (2 weeks) | Alex's primary interface |
| Sofac Pipeline (orchestration layer) | L (2 weeks) | The premium Sofac experience |
| Team CLAUDE.md management | M (1 week) | Centralized methodology enforcement |
| Weekly team digest automation | M (1 week) | Friday email Alex pastes into CEO update |

### Phase 3 (Month 5+): Enterprise

| Task | Effort | Impact |
|------|--------|--------|
| SSO/SAML integration | L (2 weeks) | Enterprise gate requirement |
| Audit logging | M (1 week) | Compliance requirement |
| Custom MCP connectors (Jira/Linear/PagerDuty) | L (3 weeks) | Integration moat |
| Air-gapped deployment option | L (3 weeks) | Defense/gov market |
| Quarterly compliance report generator | M (1 week) | Board-ready output |

---

## Key Decision Summary

| Question | Decision | Rationale |
|----------|----------|-----------|
| Should sofac move to Enterprise? | **No.** Sofac Check stays in Open. Sofac Pipeline (orchestration) is Teams/Enterprise. | Sofac is the "wow" moment. Moving it kills the viral loop. |
| Should any tool be gated? | **No.** All 16 tools are in every tier. Persistence and orchestration are what's gated. | Tools are the hook. Data persistence is the upgrade path. |
| What storage should we recommend? | **Cloudflare R2.** $0 egress, permanent 10GB free tier, S3-compatible API. | Eliminates cost anxiety. Dev's only cost is the Nora subscription. |
| Per-seat or per-team pricing? | **Per-team for Teams tier.** Per-seat above 50 devs. | Per-team is frictionless to expense. Per-seat at scale is standard. |
| Should raw transcripts sync to BYOS? | **No by default.** `insights_only` mode syncs patterns/decisions/bugs/scores. `raw_and_insights` is opt-in. | Privacy-by-default gets Legal approval. Opt-in raw is there for power users. |
| Open source or proprietary? | **Open core (ELv2) + proprietary extensions.** MCP server and local pipeline are open. Pro/Teams features are proprietary. | Trust and distribution from open core. Revenue from commercial extensions. |
| What's the naming? | Open / Pro / for Teams / Enterprise. | "Teams" is accessible. "Enterprise" signals procurement. |

---

## Appendix A: Kiro Powers Comparison

The uploaded PDF (PE-Review-Sofac-COE-Skills.pdf) shows three Kiro "Powers" — static system prompts that guide Kiro's AI through structured workflows. These are free to all Kiro users.

| Dimension | Kiro Powers | Nora Tools |
|-----------|-------------|------------|
| Architecture | Static prompt templates | MCP tools backed by live SQLite data |
| Learning | No memory between sessions | Compounding echo.db across sessions |
| Subagents | Declared in prompt (8 for Sofac) | Not yet — Pro/Teams roadmap |
| Integrations | CloudWatch, Jira, Linear (in prompt) | Git-native only (Open); integrations in Enterprise |
| Self-healing | Mentioned in Sofac prompt | Proven in production (Article 38) |
| Data backing | None — prompt-only | echo.db with patterns, decisions, bugs, scores |

**Recommendation:** Nora's tools are strictly superior because they're backed by data, not just prompts. But Kiro Powers' subagent decomposition and integration declarations are good architectural ideas to adopt for Pro/Teams. Specifically:
- **Adopt subagent decomposition for PE review** (Pro): `@code-scorer`, `@fix-suggester`, `@security-checker` as separate analysis passes
- **Adopt integration declarations for Sofac Pipeline** (Teams): Jira/Linear task sync
- **Do NOT adopt auto-trigger hooks in Open** — these require persistence (Pro feature)

## Appendix B: The Compounding Curve

Why persistence is worth paying for — the value of Nora's output vs. time:

```
Value of nora_pe_review output
│
│                                          ╱ Pro (persistent)
│                                        ╱
│                                      ╱
│                                    ╱
│                     ╱─────────── Open (local only, resets on machine change)
│                   ╱
│                 ╱
│               ╱
│             ╱
│           ╱
│         ╱
│       ╱
│     ╱
│   ╱
│ ╱
└──────────────────────────────────────────► Time (days)
    0     30     60     90     120    150
```

At day 0, Open and Pro produce identical output. By day 90, Pro's PE review includes: "This exact finding was flagged 6 weeks ago in commit abc123 and regressed. The fix that worked last time was X." Open's PE review has no memory of the previous finding — it's a fresh audit every time.

The divergence is the business model.
