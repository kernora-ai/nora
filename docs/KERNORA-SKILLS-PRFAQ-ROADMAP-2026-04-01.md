# Kernora: Skills Transferability, PRFAQs, Roadmap & R1 Scope

**Date:** April 1, 2026
**Author:** Mihir Choudhary + Claude
**Status:** Strategic planning document — decision-ready

---

## PART 1: SKILLS TRANSFERABILITY ANALYSIS

### 1.1 Executive Summary

52 skills evaluated across three sources: Cowork plugins (25), Jivant-specific skills (27). The analysis maps each skill's transferability to Nora (developer intelligence) and Echo (personal AI memory).

**Bottom line:**
- **12 skills transfer directly to Nora** (developer/enterprise) with renaming
- **5 skills transfer to Echo** (personal) with significant adaptation
- **8 skills transfer to BOTH** with different instantiations
- **27 skills should NOT transfer** — they're domain-specific (health, iOS, legal/sales operations) and would dilute focus

### 1.2 Skills That Transfer to Nora (Developer Intelligence)

| # | Source Skill | New Nora Name | Tier | Value | Rationale |
|---|-------------|---------------|------|-------|-----------|
| 1 | pe-code-audit | `nora_pe_review` | Open | **HIGH** | Already one of Nora's 16 tools. Multi-tier audit translates directly. Strip health/FDA lens, add OWASP/security lens. |
| 2 | bug-fix | `nora_autofix` | Pro | **HIGH** | Diagnose→fix→audit→rules pipeline is Nora's self-healing loop. COE trigger on build failure. |
| 3 | coe-tech | `nora_coe` | Open | **HIGH** | Already in Nora's 16. Amazon 5-Whys works for any codebase. Strip Jivant personas, add generic examples. |
| 4 | coe-product | `nora_coe_product` | Teams | **MEDIUM** | Product COE requires team context (specs, batch history). Enterprise value for tracing spec→implementation drift. |
| 5 | system-test | `nora_test` | Open | **HIGH** | Smart test runner scoped by changed files. Language-agnostic: swap xctest for jest/pytest/cargo test. |
| 6 | security-audit | `nora_security` | Teams | **HIGH** | 4-tier audit model transfers. Replace clinical accuracy with OWASP Top 10, SAST patterns. |
| 7 | metrics-retro | `nora_retro` | Open | **HIGH** | Already in Nora's 16. Git velocity, batch metrics, code quality signals. Universal. |
| 8 | release-strategy | `nora_release` | Enterprise | **MEDIUM** | 8-phase methodology is over-engineered for solo devs. Teams/Enterprise value for release gates. |
| 9 | feature-inventory | `nora_inventory` | Open | **MEDIUM** | Already in Nora's 16. Surface area audit works for any app. |
| 10 | sofac | `nora_sofac` | Open | **HIGH** | Already in Nora's 16. Factory heartbeat is the signature moment. Keep in Open (per Tier Strategy PRD). |
| 11 | deploy-verify | `nora_deploy` | Pro | **MEDIUM** | Health check + endpoint smoke test. Adapt to generic deployment targets (Vercel, Railway, AWS). |
| 12 | nightly-test | `nora_nightly` | Teams | **MEDIUM** | 8-phase automated pipeline. Requires CI/CD integration. Teams/Enterprise value. |
| 13 | thought-leadership | `nora_publish` | N/A | **LOW** | Content creation is tangential to developer intelligence. Defer entirely. |
| 14 | prfaq | — | N/A | **LOW** | Amazon Working Backwards is a business skill, not a developer tool. Keep in Cowork only. |

### 1.3 Skills That Transfer to Echo (Personal AI Memory)

| # | Source Skill | New Echo Name | Tier | Value | Rationale |
|---|-------------|---------------|------|-------|-----------|
| 1 | productivity:memory-management | `echo_memory` | Free | **HIGH** | Two-tier memory system is Echo's core architecture. Adapt CLAUDE.md → encounter metadata + topic index. |
| 2 | productivity:task-management | `echo_tasks` | Free | **MEDIUM** | Task tracking derived from AI conversations. "You discussed building X in 3 conversations — is this a task?" |
| 3 | ux-gaya-lens | `echo_ux_audit` | Pro | **LOW** | Adapt user-lens audit for Echo's own UI. Internal tool, not user-facing. |
| 4 | declarative-narrative | `echo_synthesis_style` | Pro | **MEDIUM** | Writing mode for weekly digests and topic syntheses. Short sentences, no bullets, story-style output. |
| 5 | peer-review | `echo_perspective` | Pro | **LOW** | Simulate multiple perspectives on a topic cluster. "Here's how a VC, a PM, and an engineer would view your research on X." |

### 1.4 Skills That Transfer to BOTH (Different Instantiations)

| # | Source Skill | Nora Version | Echo Version | Notes |
|---|-------------|-------------|-------------|-------|
| 1 | product-management:competitive-analysis | `nora_compete` (Teams) — competitor analysis for dev tools | `echo_compete` — NOT needed. Echo doesn't need competitive analysis as a skill. | Nora-only. |
| 2 | product-management:feature-spec | `nora_spec` (Teams) — PRD generation from session patterns | `echo_spec` — NOT needed. | Nora-only for Teams/Enterprise. |
| 3 | product-management:metrics-tracking | `nora_metrics` (Pro) — OKR/dashboard from retro data | `echo_metrics` — topic frequency tracking, AI tool usage breakdown | Both. |
| 4 | product-management:roadmap-management | `nora_roadmap` (Enterprise) — release planning | Not for Echo. | Nora Enterprise only. |
| 5 | product-management:stakeholder-comms | `nora_digest` (Teams) — weekly team digest | `echo_digest` (Pro) — weekly personal digest | Both. Different audience. |
| 6 | marketing:content-creation | — | — | Neither. Content creation is not core to either product. |
| 7 | investor-prep | — | — | Neither. Keep in Cowork/Jivant. Business skill, not product feature. |
| 8 | launch-campaign | `nora_launch` (one-time) — for Nora's own launch | `echo_launch` (one-time) — for Echo's own launch | One-time use, not recurring product skills. |

### 1.5 Skills NOT to Transfer (Stay Domain-Specific)

| Category | Skills | Why NOT Transfer |
|----------|--------|------------------|
| **Health/Regulatory** | regulatory-check, health-compliance, health-risk-assessment, legal-compliance | FDA/DPDP-specific. Zero relevance to developer tools or personal AI memory. |
| **iOS/Xcode Infrastructure** | xcp-batch-workflow, testflight-pipeline, e2e-test, gaya-story-test, parity-audit | Xcode-specific. Nora is language-agnostic. |
| **Legal Operations** | legal:contract-review, legal:nda-triage, legal:compliance, legal:canned-responses, legal:legal-risk-assessment, legal:meeting-briefing | Organizational process tools. Not product features. Keep in Cowork. |
| **Sales Operations** | sales:account-research, sales:call-prep, sales:competitive-intelligence, sales:create-an-asset, sales:daily-briefing, sales:draft-outreach | Same — organizational, not product. Keep in Cowork. |
| **Marketing Operations** | marketing:brand-voice, marketing:campaign-planning, marketing:performance-analytics | Same. |
| **Jivant Product** | prfaq-workflow, partner-outreach, release-management, vm-recovery | Jivant-specific or Cowork infrastructure. |

**Total: 27 skills that should NOT move.** These would be scope creep. A developer intelligence tool should not ship with NDA triage or sales call prep.

### 1.6 New Skills Needed (Don't Exist Yet)

#### For Nora

| Skill | Description | Tier | Priority |
|-------|-----------|------|----------|
| `nora_onboard` | Codebase tour: scan project, identify architecture, key files, tech debt | Open | P0 — first-run experience |
| `nora_dependency_audit` | CVE check, unmaintained deps, supply chain risk | Pro | P1 |
| `nora_incident` | Production incident postmortem (adapted from coe-tech for live incidents) | Teams | P2 |
| `nora_test_coverage` | Identify untested code paths, suggest test priorities | Pro | P2 |
| `nora_prompt_quality` | Score and improve AI prompts based on session history | Open | P1 — core value prop |

#### For Echo

| Skill | Description | Tier | Priority |
|-------|-----------|------|----------|
| `echo_capture` | Intake from Share Sheet + Shortcuts + import parsers | Free | P0 — foundational |
| `echo_extract` | Apple FM extraction pipeline (@Generable) | Free | P0 — foundational |
| `echo_topics` | Auto-clustering of encounters into topic threads | Free | P0 — core value |
| `echo_recall` | Natural language retrieval with synthesis ("what did I learn about X?") | Pro | P0 — killer feature |
| `echo_export` | Markdown, PDF, Obsidian, Notion export formats | Pro | P1 |
| `echo_source_tracking` | Which AI tool gives best answers for what problem type? | Pro | P2 |
| `echo_cross_synthesis` | Cross-encounter synthesis (BYOK cloud model) | Pro | P1 |

---

## PART 2: NORA PERSONAL vs ENTERPRISE SKILLS DISTINCTION

### 2.1 The Architecture: Same Tools, Different Depth

The Tier Strategy PRD established this principle: **"Same tool, richer output. Never gated tools."** Skills follow the same pattern. The skill is available everywhere. The depth of output scales with tier.

### 2.2 Nora Personal (Open + Pro)

Skills a solo developer gets on day one:

| Skill | Open Behavior | Pro Enhancement |
|-------|-------------|-----------------|
| `nora_pe_review` | 4-tier audit, current session only | + Regression detection ("this finding was flagged 3 weeks ago") |
| `nora_coe` | 5 Whys investigation | + COE history ("3rd COE on upload pipeline — systemic issue") |
| `nora_retro` | Last N days retrospective | + Week-over-week comparison, trend lines |
| `nora_sofac` | Health check (GREEN/YELLOW/RED) | + Delta since last check, trend direction |
| `nora_test` | Smart test runner | + Outcome tracking ("last time you touched 8+ files, 2 bugs resulted") |
| `nora_prompt_quality` | Per-session score | + 12-week trend, improvement curve |
| `nora_onboard` | Codebase scan | + Cross-project pattern recognition |
| `nora_autofix` | Diagnose + fix suggestion | + Auto-CLAUDE.md rule generation |

**Personal is about the individual developer getting smarter over time.** The compounding curve in the Tier Strategy PRD applies here: at day 0, Open and Pro produce identical output. By day 90, Pro's PE review includes regression detection and historical context. The divergence is the business model.

### 2.3 Nora Enterprise (Teams + Enterprise)

Skills that require team context or compliance infrastructure:

| Skill | Teams Behavior | Enterprise Enhancement |
|-------|---------------|----------------------|
| `nora_security` | 4-tier security audit | + SOC 2/HIPAA compliance-specific checks |
| `nora_coe_product` | Product COE with team context | + Roadmap integration, decision audit trail |
| `nora_release` | Release gate methodology | + Jira/Linear sync, burndown charts |
| `nora_nightly` | Automated test pipeline | + Incident integration (PagerDuty/Datadog) |
| `nora_inventory` | Feature inventory | + Cross-project inventory, release readiness gate |
| `nora_spec` | PRD from patterns | + Team architecture decision records (ADR) |
| `nora_digest` | Personal weekly digest | + Team aggregate digest, CEO-ready summary |
| `nora_roadmap` | — | Release planning with prioritization frameworks |
| `nora_incident` | — | Production incident postmortem + integration |

**Enterprise is about team intelligence and compliance.** The individual developer's echo.db feeds into the team bucket. The team sees aggregate patterns. The enterprise sees compliance posture.

### 2.4 What NEVER Goes in Nora (Regardless of Tier)

| Skill Type | Why Not |
|-----------|---------|
| Legal operations (contract review, NDA triage) | Organizational process, not developer tool |
| Sales operations (outreach, call prep) | Wrong user, wrong context |
| Marketing operations (campaigns, SEO) | Not Nora's job |
| Health/regulatory (FDA, DPDP) | Jivant-specific |
| Content creation (articles, posts) | Tangential to developer intelligence |

---

## PART 3: R1 SCOPE — NORA VSCode/KIRO EXTENSION

### 3.1 R1 Principles

1. **8 skills maximum.** Every additional skill adds maintenance burden and context window cost.
2. **Solo developer value first.** R1 is for Priya, not Alex or David.
3. **Self-contained.** No cloud dependency. No account required. BYOK only.
4. **Works on day one.** Cold start must deliver value within the first session.

### 3.2 R1 Skill Set (8 Skills)

| Priority | Skill | Why R1 | Cold Start Value |
|----------|-------|--------|------------------|
| **P0** | `nora_search` | Foundation. Search across patterns, decisions, bugs. | Immediate after first analyzed session. |
| **P0** | `nora_bugs` | Tracks bugs with severity, fix code. Recurring bug detection. | After 3-5 sessions, starts finding patterns. |
| **P0** | `nora_patterns` | Learned coding patterns with effectiveness scores. | After 5+ sessions, meaningful patterns emerge. |
| **P0** | `nora_retro` | Weekly/N-day retrospective with git velocity. | After 7 days of usage. |
| **P1** | `nora_pe_review` | 4-tier code audit. Nora's crown jewel. | Immediate — works on any codebase. |
| **P1** | `nora_sofac` | Factory health check. The self-healing signature moment. | After 10+ sessions. |
| **P1** | `nora_scope_validation` | Safety check before multi-file edits. | Immediate — prevents token waste. |
| **P1** | `nora_skills` | Distilled methodology from best sessions. | After 10+ sessions, auto-CLAUDE.md update. |

### 3.3 R1 Deferred (R2+)

| Skill | Why Deferred |
|-------|-------------|
| `nora_coe` | Requires enough session history for meaningful 5-Whys |
| `nora_coe_product` | Requires team context (specs, batch history) |
| `nora_session` | Session drill-down — useful but not differentiated on day one |
| `nora_stats` | Dashboard stats — nice-to-have, not essential |
| `nora_scan` | Git history bootstrap — valuable but complex to get right |
| `nora_inventory` | Feature inventory — more useful after product stabilizes |
| `nora_onboard` | Codebase tour — high value but separate from core intelligence loop |
| `nora_autofix` | Auto-fix requires high confidence in diagnosis. R2 after trust is built. |

### 3.4 R1 Extension Package

The VSCode/Kiro extension delivers:

```
kernora-nora/
├── extension.json           # VSCode/Kiro extension manifest
├── bundled/
│   ├── nora_mcp.py         # MCP server (8 R1 tools)
│   ├── analyzer.py         # Session analysis engine
│   ├── db.py               # echo.db SQLite management
│   ├── daemon.py           # Background analysis daemon
│   ├── hook.py             # Claude Code/Kiro hooks
│   └── steering_writer.py  # CLAUDE.md auto-update
├── hooks/
│   ├── nora_context.py     # UserPromptSubmit hook
│   ├── nora_session_start.py
│   ├── nora_precompact.py
│   └── kernora_hook.py     # Stop hook (session capture)
└── config.toml.example     # BYOK config template
```

### 3.5 R1 Success Metrics

| Metric | Target | Why |
|--------|--------|-----|
| Install → first `nora_bugs` output | <5 minutes | Cold start must be fast |
| Repeat bug detection rate | >30% after 10 sessions | Core value prop must work |
| CLAUDE.md auto-update accuracy | >80% useful rules | Self-healing must be trustworthy |
| Session analysis latency | <60 seconds | Background, but must feel responsive |
| Extension size | <5 MB | Dev tools must be lightweight |

---

## PART 4: ECHO PRFAQ

### Echo: Every AI Conversation, Remembered

#### *For yourself first. Then for your team.*

*Echo quietly captures your AI conversations across every tool — ChatGPT, Claude, Gemini, Grok, Apple Intelligence — extracts what you actually learned, and builds a searchable memory that compounds with every conversation. Your data stays on your device.*

---

**The Problem.** You had 23 AI conversations this week across five tools. You got a breakthrough insight from Claude about unit economics on Tuesday. On Friday, you're searching ChatGPT and Gemini trying to find it. You remember the phrase "takeaway rate" but neither tool's search finds it. The insight is locked in a conversation you can't locate. This happens every week. The richest record of your intellectual life is scattered across five silos with no index.

**The Solution.** Echo works alongside every AI tool you already use. Finish a conversation → tap Share → Echo captures it, extracts the real takeaways using Apple's on-device intelligence, and indexes everything for search. A month later, search "takeaway rate" and Echo finds the Claude conversation, surfaces related Gemini exchanges about retention, and synthesizes them into a private brief.

**Intelligent Capture.** Echo lives in your iOS Share Sheet and macOS Share menu. Tap "Echo" when you finish an interesting conversation — full thread captured in under 3 seconds. No new interface. No manual tagging.

**On-Device Extraction.** Apple Foundation Models extract topics, decisions, themes, and unresolved questions — locally, free, offline, private. Structured output via `@Generable` constrained decoding. No API calls required.

**Cross-Tool Search.** Search "DPDP compliance" and get results from Claude, ChatGPT, and Gemini — organized by topic, not by tool. Seven conversations across three tools, synthesized into one brief.

**Topic Trends.** See what you've been thinking about this week. Four topics across 23 conversations. Patterns emerge: you're circling the same compliance question in different tools.

**Weekly Digest.** Nora Pro users get a Friday synthesis: topics explored, decisions made, questions still unresolved. The arc of your thinking, organized.

**Spotlight Integration.** Echo results appear in system search alongside Mail, Notes, and Safari results. Your AI memory becomes part of your system memory.

> "I've had 30 conversations with Claude about monetization. I remember the good ones were brilliant, but I can't find them. Echo changes that." — Mihir Choudhary, Founder & First User

---

#### External FAQ

**Q: Does Echo replace ChatGPT or Claude?** No. Echo works alongside every AI tool. It doesn't provide AI responses — it learns from the responses you get and makes them findable.

**Q: How does capture work?** Share Sheet. Finish a conversation, tap "Echo." Works in Safari, Chrome, ChatGPT app, Claude app, Gemini — any app with share functionality.

**Q: Isn't this just conversation history search?** ChatGPT search finds keywords within ChatGPT. Echo finds concepts across all tools. "What did I learn about unit economics?" returns synthesized insights from Claude, ChatGPT, and Gemini conversations over 3 weeks.

**Q: Where is my data stored?** On your device in CoreData. iCloud sync (optional) is encrypted with Apple's keys. Kernora never sees your conversations. BYOK for synthesis — your API key, your LLM, direct connection.

**Q: Is Echo free?** Echo Free is free forever: local capture, on-device extraction, search, Spotlight. Nora Pro ($9/mo) adds cross-encounter synthesis, weekly digest, topic trends.

**Q: What if an AI tool changes or shuts down?** Captured conversations are permanently yours in Echo, independent of the original platform.

**Q: Does Echo work with Apple Intelligence?** Yes. Same capture mechanism works for any AI conversation on Apple platforms.

---

#### Internal FAQ (20 Questions)

**Customer (Q1-Q5)**

Q1: **Who is Echo for?** Knowledge workers using 2+ AI tools daily. Founders, researchers, consultants, engineers. 50M+ people use 3+ AI tools daily in 2026.

Q2: **What specific pain does Echo solve?** "I already figured this out" (recreating knowledge), "Which tool did I use?" (retrieval friction), "What was I working on?" (no weekly view of AI activity).

Q3: **Why will people pay?** Free tier is useful but local-only. After 50 conversations (roughly 2 months), the corpus becomes valuable enough that persistence, synthesis, and weekly digests justify $9/month.

Q4: **How is this different from Screenpipe?** Screenpipe records everything ($400 lifetime, 5-10 GB/month). Echo captures only what you explicitly share — AI-specific, lightweight, privacy-respecting.

Q5: **What if Apple Foundation Models aren't good enough?** AFM handles topic/theme extraction well. For richer analysis, Nora Pro users use their own API key (BYOK) for Claude/GPT synthesis. Fallback is built into the architecture.

**Market (Q6-Q10)**

Q6: **Why now?** Three factors: AI tool fragmentation is real (3-5 tools per worker), Apple FM makes on-device extraction free, and Limitless/Rewind vacated the market.

Q7: **TAM?** 50M multi-tool AI users × 5% conversion × $108/year = $270M SAM. Conservative Year 3 SOM: 50K users, 2,500 paying, $270K ARR (bootstrapped).

Q8: **Who are real competitors?** Screenpipe (raw recording), Magai/Jenova (own interface), ChatGPT PersonalContext (single-platform), Mem/Notion (manual input). Nobody does cross-platform AI-specific intelligence.

Q9: **What if OpenAI/Anthropic build this?** They can't build cross-platform without partnering with competitors. Each platform's incentive is lock-in, not interoperability. Echo's structural advantage is platform agnosticism.

Q10: **Acquisition upside?** Rewind acquired by Meta for ~$100M on $2M ARR. Echo at similar trajectory could be $500M+ opportunity. But optimizing for sustainable unit economics, not exits.

**Technical (Q11-Q14)**

Q11: **Why Apple Foundation Models?** On-device, zero latency, zero cost, zero API dependency. 70% as good as Claude for topic extraction. BYOK upgrade path for Pro.

Q12: **How does extraction scale?** AFM runs 2-3 seconds per conversation regardless of history. CoreData queries for search, not re-running extraction. Batch processing for digests.

Q13: **Data model?** CoreData entities: `AIEncounter` (raw + extracted), `WeeklyDigest`, `TopicCluster`. Full-text search via CoreData predicates + Spotlight indexing.

Q14: **Encryption strategy?** NSFileProtectionComplete (hardware encryption) + CloudKit with Apple-managed keys. Kernora never holds encryption keys.

**Business (Q15-Q17)**

Q15: **Unit economics?** Free tier CAC: ~$2 (word-of-mouth). Pro conversion: ~8%. ARPU: $9/mo. LTV: ~$172 (24 months). Breakeven: Month 18 at 2,000 paying users. COGS near zero (BYOK + on-device).

Q16: **Distribution?** ProductHunt launch → AI-native Twitter/X audience → organic word-of-mouth among power users. Every user with 5+ AI conversations/day recommends to peers.

Q17: **Expansion revenue?** Free → Pro (synthesis + digest) → Teams (shared topic clusters). Net dollar retention: +120% from upsell.

**Risk (Q18-Q20)**

Q18: **Capture fragility?** Share Sheet is OS-level, not platform-dependent. Works even if ChatGPT/Claude change their UI. Import parsers are backup for bulk history.

Q19: **Privacy risk?** Zero. Local-first. No PII stored beyond what users voluntarily share. No ads, no behavioral data, no data sales. Privacy architecture IS the moat.

Q20: **What if people don't pay?** Free tier is useful standalone. Even at 3% conversion (half industry average), 50K users × 1,500 paying = $162K ARR. Profitable at that level given near-zero infrastructure costs.

---

## PART 5: NORA PRFAQ

### Nora: Your AI Sessions, Remembered

#### *Every session makes the next one smarter.*

*Nora captures, analyzes, and learns from your AI coding sessions. It watches your prompts, bugs, and decisions — then builds compounding knowledge that prevents you from solving the same problem twice. 16 tools. Zero cloud dependency. Your data, your machine.*

---

**The Problem.** The METR study (2024) measured experienced developers using AI tools. They believed AI made them 20% faster. Measured result: 19% slower. The gap: 39 percentage points of illusion. The mechanism: developers spend more time reviewing and correcting AI output than the AI saves them. Knowledge scatter — the same bugs fixed repeatedly, the same prompts rewritten, the same architectural decisions unmade. AI generates code faster. It doesn't make developers learn from it.

**The Solution.** Nora is AI work intelligence that compounds. It runs as a background MCP server, hooking into Claude Code, Kiro, or Cursor. When you hit a bug and fix it, Nora traces the code path, checks session history ("have we solved this before?"), generates a prevention rule, and injects it into your next session. You don't solve it a fifth time.

**Session Intelligence.** `nora_search` finds patterns across your last 100 sessions. `nora_bugs` tracks every bug and its fix. `nora_decisions` documents architectural choices. `nora_skills` shows which prompts work best on your codebase.

**Code Quality.** `nora_pe_review` audits code like a principal engineer — reasoning errors, not lint rules. `nora_scope_validation` catches feature creep before it wastes tokens.

**Factory Operations.** `nora_retro` generates weekly retrospectives with git velocity. `nora_sofac` is the autonomous heartbeat — detects finished work, queues next task, self-heals.

**The Self-Healing Proof.** Article 38 documents it: Nora couldn't tell the developer it was running. Developer asked Nora to investigate itself. 54 seconds: found the bug, wrote the fix, generated a prevention rule. The self-healing loop is real.

> "I was debugging the same type safety issue for the fourth time. Nora found three previous fixes, generated a prevention rule, injected it into my next session. 90 minutes back." — Priya, Senior Engineer

---

#### External FAQ

**Q: How is this different from Copilot?** Copilot guesses your next keystroke. Nora learns from your mistakes. Copilot has zero session memory. Nora remembers every bug, decision, and lesson.

**Q: Doesn't Claude Code already remember context?** Claude remembers the current session. Nora remembers across sessions. "Last three times you built a payments flow, you used Stripe. The time before, Square — and hit PCI issues."

**Q: Will this send my code to the cloud?** Nora Open: everything local in echo.db. Pro: optional sync to YOUR S3/R2 bucket. Enterprise: fully air-gapped. Your code never leaves your machine.

**Q: Can I use this with multiple projects?** Open: per-project. Pro: cross-project intelligence. "You solved this in Project A — applying the same fix to Project B."

**Q: How much does it cost?** Open: free forever (all 16 tools, local, BYOK). Pro: $9/month. Teams: $29-99/month. Enterprise: custom.

**Q: Does this require Claude Code?** No. Works with Claude Code, Kiro, Cursor, or any MCP-compatible IDE. BYOK — your API key, your model.

**Q: Is this SOC 2 certified?** Open/Pro: data is local, no certification needed. Enterprise: SOC 2 audit, air-gapped, SSO, audit logs, data residency.

---

#### Internal FAQ (20 Questions)

**Customer (Q1-Q5)**

Q1: **Primary buyer?** Solo senior developers (4+ hours AI coding/day). Secondary: engineering leads wanting AI ROI measurement. Tertiary: security CTOs at regulated companies.

Q2: **Why pay when Claude Code is free?** Claude Code is a tool. Nora is memory. After Nora prevents one repeat bug (saving 90 minutes), $9/month is obvious.

Q3: **Job-to-be-done?** "Stop me from solving the same problem twice. Make me smarter about this codebase. Show me what I've learned and what's decaying."

Q4: **Adoption path?** Free tier, all 16 tools. Drop into MCP path. First time they run `nora_bugs` and see "you've hit this exact bug 3 times," adoption locks.

Q5: **Switching cost?** One folder: add `nora/` to `.mcp`. One config: update MCP JSON. One command: restart IDE. Done.

**Market (Q6-Q8)**

Q6: **TAM?** 6M developers using AI IDEs regularly. 1.2M senior enough to value knowledge compounding. TAM at Pro: ~$130M annually. Enterprise TAM: ~$50M.

Q7: **Competitors?** GitHub Copilot ($10-39, no memory), Cursor ($20-40, no learning), Kiro Powers (static prompts, no persistence), Langfuse/Helicone (API observability, not developer intelligence). 18-month market window.

Q8: **GTM?** Product-led. Free tier → individual adoption → team spread → enterprise sale. First conversation: "How many of your developers hit the same bug twice in a week?"

**Technical (Q9-Q12)**

Q9: **echo.db scale?** SQLite, tested to 500K sessions. Litestream replication for Pro tier.

Q10: **How does knowledge injection work?** MCP server. Claude Code queries Nora for context on session start. Nora returns relevant patterns and prevention rules as MCP tool output.

Q11: **Is this just grep?** No. Code path analysis — tracing where bugs happen, comparing to previous sessions, finding structural patterns. "Three CoreData concurrency bugs, all in ViewModel deinit. Pattern detected."

Q12: **Prevention rule accuracy?** Rules extracted deterministically from code paths, not hallucinated by LLM. Code-pattern matching, not generation.

**Business (Q13-Q16)**

Q13: **Unit economics?** Pro: $9/mo, COGS ~$0.50, 94% gross margin. Teams: $29-99/mo, COGS ~$2-5, 85% margin. Enterprise: $500+/mo, 80% margin. LTV at Pro: $180-360.

Q14: **Pricing strategy?** Freemium. Aha moment: prevented repeat bug. At that point, $9/mo for Pro or $50-99/seat for Teams is obvious.

Q15: **Revenue projections?** Month 6: 1,000 Open, 50 Pro, 3 Teams = $597 MRR. Month 24: 15,000 Open, 750 Pro, 50 Teams = $9,200 MRR. Conservative.

Q16: **Open source strategy?** MCP server and analysis pipeline: Elastic License 2.0 (open core). Pro/Teams/Enterprise features: proprietary. Trust from open core, revenue from commercial extensions.

**Risk (Q17-Q20)**

Q17: **What if Claude Code adds memory?** Validates market. We're platform-agnostic — work with any MCP IDE. Claude adding memory for Claude doesn't solve cross-tool intelligence.

Q18: **Data privacy at scale?** Open: local. Pro: user-controlled S3. Enterprise: air-gapped. Encrypted at rest and in transit. Audit logs immutable.

Q19: **METR study risk?** If the METR finding reverses (AI actually makes devs faster), Nora's value shifts from "are we getting worse?" to "how fast are we getting better?" Measurement is valuable either direction.

Q20: **Execution risk?** Solo founder building two products (Echo + Nora). Mitigation: Nora R1 is 8 skills, proven codebase (already works). Echo R1 reuses 60-70% of Jivant's architecture. Shared intelligence engine.

---

## PART 6: ROADMAP

### 6.1 Nora Roadmap

| Phase | Timeline | What Ships | Skills | Target User |
|-------|---------|-----------|--------|-------------|
| **R1: Open Launch** | April-May 2026 | VSCode/Kiro extension. 8 core skills. Local echo.db. BYOK. | search, bugs, patterns, retro, pe_review, sofac, scope_validation, skills | Priya (solo dev) |
| **R1.1: Open Polish** | June 2026 | Auto-CLAUDE.md update. Cursor/Windsurf hook adapters. Weekly digest notification. Sofac delta tracking. | + autofix (CLAUDE.md only), + help | Priya |
| **R2: Pro** | July-August 2026 | Litestream BYOS sync (R2/S3). Cross-project intelligence. Enhanced outputs (regression detection, delta tracking). Stripe billing. | + session, stats, scan, deploy, coe | Priya upgrading to Pro |
| **R3: Teams** | September-October 2026 | Team bucket aggregation. Shared patterns. Team dashboard (web). Sofac Pipeline. Team CLAUDE.md management. Weekly team digest. | + coe_product, security, nightly, spec, digest, release | Alex (eng lead) |
| **R4: Enterprise** | Q1 2027 | SSO/SAML. Audit logs. Data residency. Air-gapped. Custom MCP connectors (Jira/Linear/PagerDuty). Compliance reports. | + roadmap, incident, inventory (enhanced) | David (CTO) |

### 6.2 Echo Roadmap

| Phase | Timeline | What Ships | Target User |
|-------|---------|-----------|-------------|
| **E1: Mac App Alpha** | July 2026 | CoreData model. Share Extension (Safari). Apple FM extraction. Menu bar app + full window UI. ChatGPT/Claude export import. Search + Spotlight. | Mihir (alpha) |
| **E2: iPhone App** | August 2026 | iPhone Share Sheet capture. iCloud sync (Mac ↔ iPhone). Action Button shortcut. Spotlight integration. | Mihir (daily driver) |
| **E3: Automation** | September 2026 | Shortcuts templates (nightly sync, daily summary). Gemini Takeout import. Cross-encounter synthesis (BYOK). Weekly digest. | Early beta users |
| **E4: Public Launch** | October 2026 | ProductHunt launch. Topic clustering. Nora ↔ Echo bridge (shared search). | Knowledge workers |
| **E5: Pro Features** | November 2026 | BYOS persistence. Cross-encounter synthesis. Topic trends. Export formats. Source tracking. | Pro upgraders |

### 6.3 Shared Milestones

| Date | Milestone |
|------|-----------|
| **April 2026** | Nora R1 ships to VSCode Marketplace + Kiro |
| **May 2026** | First 100 installs. Feedback loop begins. |
| **June 2026** | Nora R1.1 with auto-CLAUDE.md. Cursor adapter. |
| **July 2026** | Nora Pro launch ($9/mo). Echo Mac alpha (Mihir). |
| **August 2026** | Echo iPhone alpha. Nora Pro → 50 paying users. |
| **September 2026** | Nora Teams beta. Echo automation (Shortcuts). |
| **October 2026** | Echo public launch. Nora Teams launch. |
| **December 2026** | $2,000 MRR target. |
| **Q1 2027** | Nora Enterprise beta. First enterprise customer. |

---

## PART 7: PM PE REVIEW

### 7.1 Product Management Review (Strengths)

1. **Clear persona segmentation.** Priya/Alex/David for Nora. Mihir/knowledge-worker for Echo. Each has distinct JTBD, success metrics, and pricing sensitivity.

2. **"Same tool, richer output" is a clean tier model.** Never gating tools avoids the "free tier feels crippled" trap. Solo devs get the full experience. Paying amplifies it.

3. **BYOK eliminates COGS at scale.** Near-zero marginal cost per user. The user provides storage and API keys. Kernora provides intelligence. Pure software margin.

4. **Platform-agnostic positioning is correct.** Not competing with Copilot/Cursor/Claude. Additive to all of them. This is the 1Password playbook — work across all platforms, never replace any of them.

5. **Self-healing as signature moment is strong.** Article 38 provides proof. The sofac→coe→fix→rule→sofac loop is demonstrable and viral.

### 7.2 Product Management Review (Risks & Gaps)

1. **Two products, one founder.** Echo + Nora = two roadmaps, two user bases, two support channels. Mitigation: shared intelligence engine, Nora R1 first (already built), Echo reuses Jivant architecture. But execution risk is real.

2. **Echo capture friction is underestimated.** Share Sheet requires a tap every time. Users will forget. The habit loop needs a forcing function — daily notification ("You had 5 AI conversations today. 0 captured. Tap to review.").

3. **Nora cold start problem.** Value increases with session count, but day-1 value must be non-zero. R1 mitigates with `nora_pe_review` (works immediately on any codebase) and `nora_scope_validation` (immediate token waste prevention).

4. **No pricing validation.** $9/mo is assumed from Obsidian/Copilot comps. No user interviews or willingness-to-pay surveys conducted. Need early beta feedback on pricing.

5. **Echo → Nora funnel is unproven.** The thesis that knowledge workers will discover Echo, then recommend Nora to developer friends, is untested. Could be two separate audiences that never cross-pollinate.

### 7.3 Engineering PE Review (Strengths)

1. **Nora R1 codebase exists.** MCP server, hooks, echo.db, analyzer — all functional. This is not a greenfield build.

2. **Echo reuses Jivant's CoreData + CloudKit + Apple FM stack.** 60-70% code reuse is realistic given identical patterns.

3. **SQLite + Litestream for BYOS is elegant.** No server infrastructure for Pro tier. User controls storage. Kernora controls intelligence.

4. **8-skill R1 scope is disciplined.** Avoids the "ship 16 tools on day one" trap. Core value loop (session → analysis → pattern → injection) is complete with these 8.

### 7.4 Engineering PE Review (Risks & Gaps)

1. **Hook system fragility.** Claude Code hooks are stable, but Cursor and Windsurf hooks are undocumented or non-existent. R1.1 "Cursor adapter" may be harder than estimated.

2. **Apple FM availability.** `@Generable` requires iOS 26 / macOS 26 (September 2026 GA). Echo E1 (July 2026) targeting dev beta — acceptable for alpha, risky for public launch.

3. **echo.db schema migration.** As Nora evolves from Open to Pro to Teams, the echo.db schema will need migrations. No migration strategy documented. Need to add versioned schema migrations before R2.

4. **MCP context window cost.** Injecting 8 tools into MCP context consumes tokens. At scale (100+ sessions of history), search results could overwhelm the context window. Need result size limits and relevance scoring.

5. **Cross-project intelligence (Pro) requires identity.** Linking echo.db across projects requires a user identifier without requiring an account. Options: machine ID (fragile), BYOS bucket path (ties to storage), or explicit user setup. Decision needed before R2.

---

## PART 8: KIRO AI / SOFTWARE ENGINEERING PE REVIEW

### 8.1 Nora Extension Architecture Review

**Verdict: PASS WITH COMMENTS**

The current Nora extension architecture (Python MCP server + SQLite + hooks) is sound for R1. Key comments:

| Area | Finding | Severity | Recommendation |
|------|---------|----------|----------------|
| **Hook reliability** | Claude Code hooks are async (non-blocking). If the daemon crashes, session data is lost silently. | HIGH | Add retry queue with local file backup. If daemon is down, hooks write to `~/.nora/pending/` for later processing. |
| **MCP tool registration** | All 8 tools registered at session start regardless of relevance. | MEDIUM | Implement lazy tool discovery — only advertise tools relevant to current project context. |
| **echo.db concurrency** | WAL mode handles read-write concurrency, but multiple projects writing simultaneously could cause lock contention. | MEDIUM | Use per-project echo.db with cross-project query layer in Pro. |
| **Analysis latency** | 60-second target for session analysis requires Haiku-level model. Opus analysis could take 3-5 minutes. | LOW | Use Haiku for immediate analysis, batch Opus-quality analysis nightly. |
| **Extension size** | Python bundled in extension could exceed 5MB target with dependencies. | MEDIUM | Minimize dependencies. Consider Rust/Go for MCP server in R2 (performance + single binary). |

### 8.2 Echo Architecture Review

**Verdict: PASS**

Echo's architecture directly mirrors Jivant's proven stack. No novel technical risk.

| Area | Finding | Severity | Recommendation |
|------|---------|----------|----------------|
| **Share Extension** | App Group container needed for Share Extension ↔ main app data sharing. | LOW | Standard pattern — use `UserDefaults(suiteName:)` and shared CoreData container. |
| **Apple FM context limit** | 4096 tokens limits extraction quality for long conversations. | MEDIUM | Chunk conversations into segments, extract per-segment, merge results. |
| **Topic clustering** | No ML model for clustering specified. | MEDIUM | Use Apple's NaturalLanguage framework for embedding similarity + simple hierarchical clustering. No external model needed. |
| **Export format** | Markdown/PDF/Obsidian export not specified in detail. | LOW | Standard file generation. Not architecturally complex. |

---

*End of document. All sections are decision-ready. Next step: commit to R1 scope and begin extension development.*
