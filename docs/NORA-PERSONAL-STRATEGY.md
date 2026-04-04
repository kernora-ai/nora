# Nora Personal — Strategy Analysis

**Version:** 1.0
**Date:** April 1, 2026
**Owner:** Mihir Choudhary
**Status:** Strategic assessment — decision needed before building

---

## The Problem Statement

Mihir uses ChatGPT, Grok, Claude (Code, Chat, Desktop), and Gemini daily. He's an Apple ecosystem user — iPhone and Mac. Every AI conversation happens in a different silo. He can't search across them. He can't find "that pricing analysis I asked Claude about on Tuesday." He can't see which tool he uses most effectively for which task type. He has no institutional memory across his own AI usage.

This isn't Mihir's problem alone. It's the problem of every knowledge worker who uses 2+ AI tools in 2026. And that's most of them.

---

## The Competitive Landscape: Who's Here Already

### The Dead and Acquired

**Limitless (formerly Rewind AI)** was the closest thing to this vision. It recorded your screen and audio 24/7, stored everything locally, made it searchable. Meta acquired it in December 2025. Post-acquisition, the non-Pendant screen/audio capture features were sunset. The product is now a hardware-dependent (Pendant) meeting transcription tool inside Meta's ecosystem. The general-purpose "memory for everything on your computer" product no longer exists.

**This is a gift.** The market leader vacated the market. The use case didn't go away — the product did.

### The Active Competitors

| Product | What It Does | Price | Limitation |
|---------|-------------|-------|-----------|
| **Screenpipe** | Open source screen+audio recording, local storage, MCP server | $400 lifetime | Records *everything* (heavy, ~5-10 GB/mo). Doesn't understand AI conversations specifically. No cross-tool intelligence — it's a raw recording tool, not an analysis engine. |
| **Magai** | Unified chat interface for 30+ AI models | $19/mo | You must use *their* interface. Doesn't capture conversations you have in ChatGPT, Claude, or Grok directly. It's a replacement, not a unifier. |
| **Jenova** | Cross-model persistent memory, model switching | ~$15/mo | Same problem as Magai — requires you to use their interface. Doesn't capture your existing workflows. |
| **ChatGPT PersonalContextAgentTool** | Search across ChatGPT history | Plus/Pro ($20-200/mo) | Only searches ChatGPT conversations. Doesn't know about your Claude, Gemini, or Grok usage. Vendor lock-in by design. |
| **Mem AI** | AI-first note-taking with auto-organization | $12/mo | You have to manually save things to Mem. No automatic capture. It's a destination, not a listener. |
| **Notion AI** | AI-powered workspace search and generation | $20/user/mo (Business) | Same as Mem — manual input required. Doesn't capture AI conversations. |
| **Apple Intelligence** | On-device summarization, Shortcuts automation | Built into Apple ecosystem | Doesn't capture or analyze AI conversations. Shortcuts can chain AI calls but don't build persistent memory. |

### The Gap

Every existing solution falls into one of two traps:

1. **"Use our interface instead"** (Magai, Jenova) — Forces you to abandon ChatGPT, Claude, Grok. Nobody will. People use specific AI tools for specific reasons. The solution must be additive, not substitutive.

2. **"Record everything on your screen"** (Screenpipe, old Rewind) — Captures too much. Most screen activity is noise. The signal-to-noise ratio is terrible. And it's ~5-10 GB/month of storage for mostly irrelevant data.

**What nobody does:** Intelligently capture AI-specific conversations across tools, analyze them for patterns/quality/themes, make them searchable, and build a compounding personal intelligence layer — without requiring the user to change their workflow.

That's the Nora Personal opportunity.

---

## The Honest Assessment: Should We Build This?

Before getting excited about the TAM, let's interrogate this idea hard.

### Arguments FOR Nora Personal

**1. Massive TAM expansion.**
Nora Open/Pro/Teams targets developers using AI coding tools. That's ~5-10M people globally and growing. "People who use 2+ AI tools daily" is 100-500M and growing faster. Nora Personal is a 50-100x TAM multiplier.

**2. Same core technology.**
The Nora engine is: capture session → analyze with LLM → extract patterns/themes/decisions → store in SQLite → make searchable via MCP. Nora Personal is the same pipeline with different capture sources. The analysis engine, storage layer, MCP server, and dashboard are reusable.

**3. Natural brand extension.**
"Nora remembers" works for both developer sessions and personal AI conversations. The brand doesn't need to change. The tagline doesn't need to change. Nora is already positioned as "AI work intelligence" — personal AI usage is work.

**4. The market leader just left.**
Rewind/Limitless was acquired by Meta and its core product was sunset. Screenpipe is the only remaining player and it's a raw recording tool, not an intelligence layer. The timing is rare.

**5. Apple ecosystem advantage.**
Mihir is an Apple user. Apple's Shortcuts automation (especially the "Use Model" action in iOS/macOS 26) and Safari extensions create legitimate capture mechanisms that don't require screen recording. This is a cleaner, more privacy-respecting approach than Screenpipe's "record everything."

**6. The funnel inverts.**
Currently: Developer installs Nora → gets hooked → tells team → team upgrade. With Personal: *Anyone* installs Nora Personal → knowledge worker gets hooked → realizes they want it for coding too → installs Open → tells team → team upgrade. Personal becomes the top of the funnel for the entire Kernora business.

### Arguments AGAINST Nora Personal

**1. Focus dilution — this is the biggest risk.**
Nora Open isn't shipped yet. Pro isn't built. Teams is a roadmap item. Adding a Personal tier means building capture adapters for ChatGPT, Claude, Gemini, Grok, plus a non-developer dashboard, plus Apple ecosystem integrations. That's 2-3 months of building a different product surface while the developer product isn't monetizing yet.

**2. Capture is technically harder than it looks.**
Developer session capture works because Claude Code has a hook system (`hooks.json`). ChatGPT, Grok, and Gemini don't have hook systems. Capture requires either:
- Browser extension (fragile, breaks on UI updates, each platform needs its own adapter)
- Export file parsing (ChatGPT has export, Claude has export, Gemini has Takeout — but these are batch/manual, not real-time)
- Screen capture (Screenpipe approach — heavy, privacy-invasive, noisy)
- API access (only available if the user uses the API, not the chat UI)

None of these are as clean as a CLI hook. The maintenance burden is real.

**3. Different user, different expectations.**
Developers tolerate CLI tools, SQLite databases, and MCP servers. Knowledge workers expect polished apps with native UI, iCloud sync, and "it just works" simplicity. Building for both audiences simultaneously means building two front-ends.

**4. Screenpipe has a head start.**
Screenpipe is open source, has MCP integration, works on Mac/Windows/Linux, and has an active community. If Nora Personal is "Screenpipe but smarter about AI conversations," Screenpipe could add that intelligence layer faster than we can build the recording layer.

**5. Platform risk.**
ChatGPT, Claude, and Gemini could all add cross-conversation search and memory natively. ChatGPT already has PersonalContextAgentTool. Claude has Projects. If each platform solves its own memory problem, the cross-platform value proposition weakens. (Counter-argument: each platform solves its *own* memory problem. Nobody solves the *cross-platform* problem. That's still Nora's lane.)

### Verdict

**Build it — but not now. Build it as Phase 3, after Pro is shipping and generating revenue.**

The opportunity is real and the timing is good (Rewind vacated, Screenpipe is raw, no one does cross-platform AI intelligence). But focus matters more than TAM right now. The developer product is the beachhead. Get it monetizing first. Then expand.

However: **design the architecture NOW so that Nora Personal is a natural extension, not a rewrite.** This means:
- The analysis engine must be source-agnostic (not hardcoded to Claude Code sessions)
- The storage schema must support non-coding conversation types
- The MCP server must handle queries about any topic, not just code
- The dashboard must be extensible to non-developer views

---

## If We Build It: The Architecture

### Capture Mechanisms (Ranked by Feasibility)

**Tier 1: Clean and Reliable**

| Mechanism | Platforms | How It Works | Effort |
|-----------|----------|-------------|--------|
| Export file import | ChatGPT, Claude, Gemini (Takeout) | User exports → Nora parses JSON/HTML → imports to echo.db | S — parsing is straightforward |
| Claude Code/Desktop hooks | Claude Code, Claude Desktop | Existing hook system — already built | Done |
| Kiro hooks | Kiro | Existing hook system — already built | Done |
| Apple Shortcuts integration | All (via Safari) | Shortcut triggers after AI conversation → captures clipboard/selection → sends to Nora | M — requires Shortcut template + Nora intake endpoint |

**Tier 2: Feasible but Fragile**

| Mechanism | Platforms | How It Works | Effort |
|-----------|----------|-------------|--------|
| Safari extension | ChatGPT, Claude, Gemini, Grok (web) | Extension detects AI chat pages, extracts conversation DOM on page leave | L — each platform has different DOM, breaks on UI updates |
| Chrome extension | Same as Safari | Same approach, different extension API | L |
| macOS Services menu | All (via text selection) | User selects text → Services → "Save to Nora" | S — but manual, not automatic |

**Tier 3: Heavy (Screenpipe Territory)**

| Mechanism | Platforms | How It Works | Effort |
|-----------|----------|-------------|--------|
| Screen OCR | All (including native apps) | Capture screenshots, OCR text, detect AI conversation patterns | XL — Screenpipe already does this, don't rebuild |
| Accessibility API | macOS native apps | Read window content via Accessibility framework | L — app-specific, fragile |

**Recommendation:** Start with Tier 1 only. Export import + Apple Shortcuts covers the 80% case. The user does a weekly "sync" (export from ChatGPT, export from Claude, import to Nora). It's not real-time, but it's reliable, privacy-respecting, and low-maintenance. Safari extension is Phase 2. Screen capture is never — that's Screenpipe's lane.

### The Apple Shortcuts Play

This is the most interesting angle. Apple's Shortcuts in iOS/macOS 26 now has:
- "Use Model" action (on-device Apple model, server Apple model, or ChatGPT)
- Share Sheet integration (capture content from any app)
- Automation triggers (time-based, app-open, NFC tag)
- Notes/Files integration for storage

A Nora Shortcut template could work like this:

```
Trigger: User taps Share → "Save to Nora" (from any AI app)
  ↓
Action 1: Get selected text / clipboard content
  ↓
Action 2: "Use Model" (Apple on-device) to extract:
  - Topic/theme of the conversation
  - Key decisions or facts
  - Which AI tool was used
  ↓
Action 3: HTTP POST to Nora's local intake endpoint (localhost:2742/api/capture)
  ↓
Action 4: Notification: "Saved to Nora — 'Pricing analysis for Q2 launch'"
```

This is lightweight, privacy-preserving (Apple on-device model for extraction, local storage), and works across every app. The user builds a habit: finish an important AI conversation → tap Share → "Save to Nora." Over time, Nora accumulates a searchable, analyzed history of every important AI interaction.

For power users: an automation that runs at 6pm daily, checks if there are new exports in a designated iCloud folder, and imports them automatically.

### Storage Schema Extension

Current echo.db schema is developer-session-centric. For Personal, extend:

```sql
-- New table for non-coding AI conversations
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,         -- 'chatgpt', 'claude', 'gemini', 'grok', 'apple_intelligence'
    source_id TEXT,               -- original conversation ID from the platform
    topic TEXT,                   -- LLM-extracted topic summary
    captured_at TEXT NOT NULL,
    content_json TEXT,            -- structured conversation (messages array)
    analysis_json TEXT,           -- LLM analysis: themes, decisions, quality
    tags TEXT,                    -- comma-separated tags from analysis
    project TEXT                  -- optional link to a coding project
);

-- Unified search across both sessions and conversations
CREATE VIRTUAL TABLE unified_search USING fts5(
    content,
    source,
    type                         -- 'session' or 'conversation'
);
```

This lets `nora_search` return results from both coding sessions AND personal AI conversations. Same tool, wider scope. No new tool needed.

### New MCP Tools (Personal-Specific)

Only 2-3 new tools needed, not a full rebuild:

| Tool | What It Does |
|------|-------------|
| `nora_capture` | Intake endpoint for Shortcuts/extensions. Receives raw conversation text, runs analysis, stores in echo.db. |
| `nora_topics` | "What have I been thinking about this week?" Aggregates themes across all AI conversations. Shows topic frequency, evolution over time. |
| `nora_recall` | "What did I learn about X?" Searches across all conversations for a specific topic and synthesizes findings. Different from `nora_search` (which returns raw results) — `nora_recall` synthesizes. |

Everything else (`nora_search`, `nora_stats`, `nora_patterns`, `nora_decisions`) works as-is with the extended schema.

---

## Product Positioning: Not a Tier — A Surface

After deep consideration, Nora Personal is NOT a pricing tier. It's a **product surface**.

Here's why:

Tiers gate *features* by willingness to pay. Personal doesn't gate features — it changes the *input source*. A developer using Nora Open captures coding sessions. A knowledge worker using Nora Personal captures AI conversations. They both use the same search, the same analysis, the same patterns engine. The tools are identical. The data is different.

**The correct architecture:**

```
                    ┌─────────────────────┐
                    │    Nora Engine       │
                    │  (analysis, storage, │
                    │   search, MCP)       │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼───────┐ ┌──────▼───────┐
    │  Nora for Devs │ │ Nora Personal│ │ Nora for     │
    │  (CLI hooks,   │ │ (Shortcuts,  │ │ Teams        │
    │   MCP server)  │ │  imports,    │ │ (dashboard,  │
    │                │ │  extensions) │ │  aggregation)│
    └────────────────┘ └──────────────┘ └──────────────┘
```

A person can use one surface, two, or all three. Mihir uses all three: Nora for Devs (when coding with Claude Code), Nora Personal (when researching with ChatGPT/Gemini), and eventually Nora for Teams (when his team grows).

**Pricing follows the tier structure from the Tier Strategy PRD:**
- Open: Free. Both Dev and Personal surfaces. Local only.
- Pro ($9/mo): Both surfaces + BYOS persistence + cross-project/cross-topic intelligence.
- Teams ($29-99/mo): All surfaces + shared team intelligence.
- Enterprise: All surfaces + compliance.

Personal is not a separate price. It's a surface that comes free with Open and gets enhanced with Pro. This is important because: if Personal were a separate $5/month product, you'd split the user base. A developer who also wants Personal shouldn't pay twice. And a knowledge worker who discovers Nora Personal and later starts coding shouldn't have to "upgrade" to a different product.

---

## The Honest Business Case

### Why This Matters for Kernora's Business

**1. Top-of-funnel expansion.**
A knowledge worker installs Nora Personal to search their ChatGPT history. They tell a developer friend. The developer installs Nora for Devs. The developer tells their team lead. The team lead evaluates Nora for Teams. Personal → Devs → Teams is the viral chain that doesn't require Kernora to spend on developer marketing.

**2. Retention through breadth.**
A user who only uses Nora for coding might churn when they switch to a different AI coding tool. A user who uses Nora for coding AND for personal AI research has double the switching cost. Their echo.db contains their entire AI life, not just their coding life.

**3. Data network effect.**
Cross-surface intelligence creates unique value. "You researched this authentication pattern in ChatGPT last week. Your Claude Code session today is hitting the same topic. Here's what you learned." No other tool can make that connection because no other tool sees both surfaces.

### Why This Should Wait Until After Pro Ships

**1. Pro is the revenue engine.** Personal expands the funnel but doesn't change the monetization. Pro at $9/month with BYOS is the first dollar. Ship it first.

**2. Personal's capture adapters are maintenance-heavy.** ChatGPT's UI changes quarterly. A Safari extension that works today breaks in 3 months. This requires ongoing maintenance capacity that doesn't exist yet.

**3. The developer product needs to be excellent first.** If a developer installs Nora because a knowledge worker recommended it, and the developer experience is 80% polished, trust erodes. Ship a 100% developer experience, then expand.

### Recommended Timeline

| Phase | When | What |
|-------|------|------|
| **Now** | April 2026 | Design echo.db schema to be source-agnostic. Don't hardcode "session" assumptions. |
| **Pro launch** | May-June 2026 | Ship Pro with BYOS. Revenue starts flowing. |
| **Personal alpha** | July 2026 | Build `nora_capture` intake endpoint + Apple Shortcuts template + ChatGPT/Claude export import. Test with Mihir's own usage. |
| **Personal beta** | August 2026 | Safari extension for ChatGPT/Claude/Gemini web. `nora_topics` and `nora_recall` tools. |
| **Personal launch** | September 2026 | Ship as a surface alongside Devs. Same pricing tiers. |

---

## What "Nora Remembers" Looks Like for Mihir

A day in Mihir's AI life, 6 months from now:

**8:00 AM** — Opens ChatGPT, asks about Indian health data regulations for Jivant. Finishes the conversation. Taps Share → "Save to Nora."

**9:30 AM** — Opens Claude Code, works on Jivant iOS. Nora's MCP server is active. Session ends, hook fires, analysis runs automatically.

**11:00 AM** — Opens Gemini, asks for competitive analysis on health apps in India. Finishes. Taps Share → "Save to Nora."

**2:00 PM** — Opens Claude Desktop, asks about investor pitch strategy. Taps Share → "Save to Nora."

**4:00 PM** — Opens Grok on X, asks about trending health-tech takes. Copies the thread, pastes into Nora capture (or uses Shortcut).

**6:00 PM** — Runs `nora topics`:
```
This week's AI topics (across 23 conversations):
1. Indian health data regulation (7 conversations — ChatGPT, Claude, Gemini)
2. Jivant iOS upload pipeline (5 sessions — Claude Code)
3. Investor pitch strategy (4 conversations — Claude Desktop, ChatGPT)
4. Health app competitive landscape (3 conversations — Gemini, Grok)
5. Nora product strategy (4 conversations — Claude Desktop)
```

**6:05 PM** — Runs `nora recall "Indian health data regulation"`:
```
Across 7 conversations this week, you explored:
- DPDP Act 2023 requirements for health data (ChatGPT, March 28)
- ABDM integration requirements and user consent flow (Gemini, March 29)
- Comparison: India DPDP vs GDPR for health apps (Claude, March 30)
- Key finding you keep coming back to: India doesn't require BAAs like HIPAA,
  but the DPDP Act's data fiduciary obligations are stricter on consent.
- You haven't resolved: whether Jivant needs a Data Protection Officer under
  DPDP if processing health data for <100 users.
```

That last line — "you haven't resolved" — is the magic. Nora doesn't just remember what you asked. It notices what you're still circling around. It surfaces the unresolved question. No other tool does this because no other tool has the cross-platform view.

---

## Stress Test: Five Ways This Could Fail

**1. Capture fragility.** Browser extensions break. Export formats change. Apple Shortcuts has limitations. Mitigation: start with import-based capture (export files), which is the most stable. Real-time capture is Phase 2.

**2. Analysis cost.** Each captured conversation needs LLM analysis. At $0.01-0.03 per conversation (Claude Haiku), a heavy user with 10 conversations/day costs $3-9/month in analysis. Mitigation: use local models (Apple on-device via Shortcuts) for initial extraction, cloud models only for deep analysis. Batch analysis nightly, not real-time.

**3. Privacy backlash.** "You're recording my AI conversations" sounds invasive. Mitigation: Nora Personal captures ONLY what the user explicitly shares (Share Sheet) or imports (export files). It does NOT record the screen. It does NOT listen to audio. The user chooses what Nora sees. This is fundamentally different from Screenpipe/Rewind's "record everything" approach.

**4. Platform lock-out.** ChatGPT could block export. Claude could change its export format. Mitigation: export-based capture is legally protected (GDPR right to data portability, CCPA right to access). Platforms can make it harder but can't legally block it.

**5. "Why not just use Notion/Obsidian?"** A user could manually copy AI conversations into Notion and use Notion AI to search them. Mitigation: manual is the enemy. The value of Nora is that capture is 1-tap (Shortcut) or automatic (hooks), analysis is automatic (LLM), and search is natural language. Notion requires manual organization that nobody maintains.

---

## Key Decisions Needed

| Decision | Options | Recommendation |
|----------|---------|----------------|
| Build Personal now or later? | Now / After Pro / Never | **After Pro ships** (July 2026). Design schema now. |
| Separate product or surface? | Separate product / Nora tier / Product surface | **Product surface** within Nora. Same engine, different input sources. |
| Separate pricing? | Separate price / Included in tiers / Freemium add-on | **Included in existing tiers.** Open gets local Personal. Pro gets persistent Personal. |
| Primary capture mechanism? | Browser extension / Export import / Shortcuts / Screen capture | **Export import + Apple Shortcuts** (Tier 1). Safari extension later (Tier 2). Never screen capture. |
| Brand name? | Nora Personal / Nora Remember / Nora for Everyone | **Nora Personal.** Clean, parallel to "Nora for Devs" and "Nora for Teams." |
| First platform? | macOS only / iOS only / Both / Web | **macOS first** (Shortcuts + Safari extension + local echo.db). iOS later (Shortcuts + iCloud sync). |

---

## Appendix: Competitive Positioning After Personal Launch

```
                    Records Everything              Understands AI
                    (screen, audio, all apps)       (conversations specifically)
                           │                               │
    ┌──────────────────────┼───────────────────────────────┼──────────┐
    │                      │                               │          │
    │   Screenpipe ────────┤                               │          │
    │   ($400 lifetime)    │                               │          │
    │                      │                               │          │
    │                      │            Nora Personal ─────┤          │
    │                      │            (Free–$9/mo)       │          │
    │                      │                               │          │
    │                      │                               │          │
    │                      │      ┌── ChatGPT Memory ──────┤          │
    │                      │      │   (ChatGPT only)       │          │
    │                      │      │                        │          │
    │                      │      ├── Claude Projects ─────┤          │
    │                      │      │   (Claude only)        │          │
    │                      │      │                        │          │
    │                      │      ├── Magai ───────────────┤          │
    │                      │      │   ($19/mo, own UI)     │          │
    │                      │      │                        │          │
    └──────────────────────┼──────┴────────────────────────┼──────────┘
                           │                               │
               Breadth of capture              Depth of understanding
```

Nora Personal sits in the unique quadrant: AI-specific understanding (not recording everything) × cross-platform (not locked to one vendor) × additive (doesn't replace your existing tools) × local-first (your data, your machine).

Nobody else is there.
