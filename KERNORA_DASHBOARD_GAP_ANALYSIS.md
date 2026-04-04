# Kernora Dashboard Feature Gap Analysis
## OLD vs CURRENT Version Comparison

**Comparison Date**: March 31, 2026
**Repositories**:
- OLD: Root-level `dashboard.py` (1523 lines, commit 229055d)
- CURRENT: `kiro-extension/bundled/dashboard.py` (1618 lines)
- ALSO EXISTS: Root-level `dashboard.py` (1703 lines) and `dashboard_installed.py` (1013 lines)

**Analysis Method**: Examined HTML generation code, KPI cards, page sections, interactive features, API routes, CSS, and visualizations across all routes.

---

## EXECUTIVE SUMMARY

The CURRENT version is a **refactored, streamlined dashboard** with:

| Aspect | Status |
|--------|--------|
| **Total Size** | +95 lines (+6.2%) |
| **Page Count** | 5 routes (unchanged) |
| **API Routes** | 8 routes → 10 routes (+2 NEW) |
| **Home KPI Cards** | 6 cards → 6 cards (2 replaced) |
| **Session Detail Cards** | 9 cards → 4 cards (-5, 56% reduction) |
| **Learnings Sections** | 6 sections → 4 sections (-2, 33% reduction) |
| **Live Session UI** | ❌ Missing → ✅ NEW (HTMX auto-refresh) |
| **DB Schema** | Fundamentally different (patterns, decisions tables) |

**Key Finding**: This is NOT a pure refactor. The current version targets a **different database schema** (with `patterns` and `decisions` tables instead of detailed metadata). Many features are removed not from laziness, but because the underlying data model changed.

---

## DETAILED FEATURE-BY-FEATURE COMPARISON

### HOME PAGE (`/`)

#### KPI Cards

| OLD KPIs (6) | NEW KPIs (6) | Status |
|--------------|--------------|--------|
| Total Sessions | Total Sessions | ✅ SAME |
| Total Tokens Tracked | Total Tokens Tracked | ✅ SAME |
| Analyzed Sessions | Analyzed Sessions | ✅ SAME |
| Rules Distilled | Rules Distilled | ✅ SAME |
| **Playbooks Captured** | **Patterns Found** | ⚠️ REPLACED |
| **Knowledge Domains** | **Decisions Captured** | ⚠️ REPLACED |

**What Changed**:
- `Playbooks Captured` → `Patterns Found` — reflects new `patterns` table in DB schema
- `Knowledge Domains` → `Decisions Captured` — reflects new `decisions` table in DB schema
- Both changes are **backward-incompatible** with old DB schema

#### Home Page Sections

| Section | OLD | NEW | Status |
|---------|-----|-----|--------|
| Intro card | "Kernora Deep Intelligence" | Same | ✅ SAME |
| KPI row | 6 KPI cards | 6 KPI cards (different metrics) | ⚠️ SAME UI, different data |
| Latest Rules card | Shows skill_opportunity rules | Shows skill_opportunity rules | ✅ SAME |
| Recent sessions table | 5 most recent with token counts | 5 most recent with token counts | ✅ SAME |
| Engine Status card | 6 engine metrics grid | 6 engine metrics grid | ✅ SAME |
| **Live Session card** | ❌ MISSING | ✅ NEW HTMX auto-refresh | 🆕 NEW |

#### Live Session Feature (NEW)

```
/api/live-session — HTMX partial endpoint (NEW)
- Returns HTML card that auto-refreshes every 5 seconds
- Shows: Project name, Start time, Tool count, Error count
- Dynamic tool breakdown bar chart (top 6 tools)
- Files touched display (last 5 files as badges)
- Recent errors list (last 2 error snippets)
- Pulsing green indicator (CSS animation)
- Uses in-memory _live_session state, updated via /api/session/start webhook
```

**Impact**: Home page now has **real-time visibility** into active sessions. Previously static historical view.

---

### SESSIONS PAGE (`/sessions`)

| Feature | OLD | NEW | Status |
|---------|-----|-----|--------|
| Session list query | Fetches 50 sessions | Fetches 50 sessions | ✅ SAME |
| Session ID display | 8-char hex ID | Same | ✅ SAME |
| Project name | Extracted from path | Same | ✅ SAME |
| Token count | tokens_in + tokens_out | Same | ✅ SAME |
| Analysis status badge | ✓ or … symbol | Same | ✅ SAME |
| Type badge | Color-coded session type | Color-coded session type | ✅ SAME |
| Click to detail | href to /sessions/<id> | href to /sessions/<id> | ✅ SAME |
| **DB Columns fetched** | session_type, workflow_stage | (removed, not in new schema) | ⚠️ SCHEMA CHANGE |

**Behavioral Change**:
- OLD: Fetched `i.session_type, i.workflow_stage` from insights table (these columns may not exist in new schema)
- NEW: Simplified to core columns only
- Session list rendering is visually identical, but filters differently upstream

---

### SESSION DETAIL PAGE (`/sessions/<session_id>`)

#### MASSIVE REDUCTION: 9 → 4 Cards (-56%)

| OLD Cards | Approx Content | NEW Cards | Approx Content | Verdict |
|-----------|-----------------|-----------|-----------------|---------|
| **Playbook** | JSON metadata | — | REMOVED | ❌ GONE |
| **Architectural Decisions** | Extracted decisions list | — | REMOVED | ❌ GONE |
| **Effective Prompts** | Prompt templates | — | REMOVED | ❌ GONE |
| **Anti-Patterns** | Pitfalls found | — | REMOVED | ❌ GONE |
| **CLAUDE.md Rule Suggestions** | Rules as divs | **CLAUDE.md Rule Suggestion** | Same | ✅ SIMPLIFIED |
| **Tools Used** | Tool usage bar chart | — | REMOVED | ❌ GONE |
| **Knowledge Domains** | Domain tags | — | REMOVED | ❌ GONE |
| **Files Touched** | List of paths | — | REMOVED | ❌ GONE |
| **Reusable Patterns** | Pattern list | — | REMOVED | ❌ GONE |
| — | — | **Bugs Found** | Bug severity list | 🆕 NEW |
| — | — | **Optimizations** | Optimization suggestions | 🆕 NEW |
| — | — | **Themes** | Extracted themes | 🆕 NEW |

**Analysis**:
- **-5 cards removed**: All the rich metadata (decisions, tools, files, patterns, domains, prompts, anti-patterns) are gone
- **+3 cards added**: Bugs, Optimizations, Themes — but these appear to be NEW extraction types from the analyzer
- **Root cause**: The `insights` table schema changed. Old version extracted: `playbook, effective_prompts, anti_patterns, knowledge_domains, reusable_patterns`. These columns likely don't exist in current insights table.
- **What this means**: The old dashboard required a much richer analysis output from the LLM. The new one is simpler, targeting a leaner extraction model.

#### Session Detail Performance Impact
- **Old**: 140 lines of code to render 9 cards with complex data structures
- **New**: 98 lines of code to render 4 cards with simpler data
- **Page load time**: Likely faster (less data to fetch, less rendering)
- **User value**: Significantly reduced context per session (no playbook, no decisions, no tools overview)

---

### BUGS PAGE (`/bugs`)

| Feature | OLD | NEW | Status |
|----------|-----|-----|--------|
| Bug query | SELECT bugs FROM insights | SELECT bugs FROM insights | ✅ SAME |
| Severity sorting | High → Medium → Low | High → Medium → Low | ✅ SAME |
| Severity colors | CSS classes (bug-high, bug-med, bug-low) | Same | ✅ SAME |
| Bug card rendering | Title + severity styling | Same | ✅ SAME |
| Bug list | Variable number per severity | Same | ✅ SAME |
| **Empty state** | "No bugs found" | "No bugs found" | ✅ SAME |
| **Code changes** | -34 lines → +48 lines | +14 lines total | ⚠️ LONGER CODE |

**What's different**:
- Function is now slightly longer despite similar feature set
- Likely added better error handling or different query structure
- Functionally equivalent from user perspective

---

### LEARNINGS PAGE (`/learnings`)

#### MODERATE REDUCTION: 6 → 4 Sections (-33%)

| OLD Sections | Content | NEW Sections | Content | Verdict |
|--------------|---------|--------------|---------|---------|
| **CLAUDE.md Rules** | Distilled rules list | **CLAUDE.md Rules** | Same | ✅ SAME |
| **Effective Prompts** | Prompt templates | — | REMOVED | ❌ GONE |
| **Anti-Patterns to Avoid** | Common pitfalls | — | REMOVED | ❌ GONE |
| **Playbooks** | Structured methodology | — | REMOVED | ❌ GONE |
| **Reusable Patterns** | Recurring patterns | **Patterns** | Pattern count from git scan | ⚠️ DIFFERENT |
| **Knowledge Domains** | Domain tags | **Architectural Decisions** | Decisions list | 🆕 NEW |
| — | — | **Optimizations** | Optimization list | 🆕 NEW |

**Analysis**:
- **Removed**: Effective Prompts, Anti-Patterns, Playbooks — all rich methodology knowledge
- **Replaced**: "Reusable Patterns" (LLM extraction) → "Patterns (from git scan)" (deterministic code patterns)
- **Added**: Architectural Decisions, Optimizations — new extraction types
- **Shift in paradigm**: From LLM-extracted methodology → deterministic code scanning + selective LLM analysis

#### Learnings Page Code Impact
- **Old**: 177 lines, complex aggregation of 6 data sources
- **New**: 157 lines, -20 lines (-11%)
- **Simpler data model**: Fewer columns to query and aggregate

---

### SETTINGS PAGE (`/settings`)

#### Mode-Specific Rendering (CONDITIONAL)

| Feature | OLD | NEW | Status |
|---------|-----|-----|--------|
| **IDE Detection** | N/A | NEW: `_is_ide_provided_llm()` | 🆕 NEW |
| **IDE Banner** | Missing | NEW: LLM provided by IDE notice | 🆕 NEW |
| **BYOK Mode** | Full settings form | Hidden when IDE is detected | ⚠️ CONDITIONAL |
| **Kiro/Cursor Mode** | N/A | NEW: Minimal settings (read-only) | 🆕 NEW |

#### IDE-Provided LLM Branch (NEW)
```
When KERNORA_IDE env var is set to "kiro" or "cursor":
- Dashboard port (read-only display)
- Database path (read-only display)
- Config path (read-only display)
- "How It Works" card explaining the local-first architecture
- "MCP Tools (16)" card with expanded command reference
```

**16 MCP Commands listed**:
1. `nora stats` — sessions, tokens, costs, model usage
2. `nora search <query>` — find sessions by keyword
3. `nora session <id>` — session detail
4. `nora patterns` — recurring patterns
5. `nora decisions` — architectural decisions
6. `nora bugs` — past bugs and fixes
7. `nora skills` — team playbook
8. `nora scan <path>` — import git repo
9. `nora pe-review <focus>` — principal engineer code review
10. `nora coe <issue>` — root-cause investigation
11. `nora coe product <issue>` — product/UX COE
12. `nora retro` — engineering retrospective
13. `nora scope <task>` — task validation
14. `nora sofac` — software factory health
15. `nora inventory` — feature inventory
16. `nora help` — full reference

#### BYOK Mode (When IDE is NOT detected)

| Feature | OLD | NEW | Status |
|---------|-----|-----|--------|
| Model provider select | radio button (anthropic/ollama) | Same | ✅ SAME |
| S3 Config section | Form inputs (bucket, region, keys) | Same | ✅ SAME |
| Swarm Cloud section | "Enterprise Swarm Cloud" card | Same | ✅ SAME |
| Director Mode toggle | NEW checkbox field | ⚠️ ADDED |
| Managed toggle button | NEW "Provision Organization Cloud" button | ⚠️ ADDED |
| Form POST handling | Rewrites config.toml natively | Same | ✅ SAME |

**New BYOK Features**:
- `director_mode` configuration option (boolean)
- Managed swarm provisioning button
- Type switching: `type = 'byok_s3'` ↔ `type = 'kernora_managed'`

---

### BUG/REGRESSION ANALYSIS

#### What REGRESSED (Existed Before, Now Worse/Broken)

1. **Session Detail Metadata** — SEVERE REGRESSION
   - OLD showed: Tools used, Files touched, Decisions, Patterns, Prompts, Anti-patterns
   - NEW shows: Bugs, Optimizations, Themes (different extraction entirely)
   - **Impact**: Users lose visibility into session metadata (which files were touched, what tools were used)
   - **Root Cause**: DB schema changed; old insights columns don't exist
   - **Severity**: 🔴 HIGH — Major feature loss

2. **Learnings Page Richness** — MODERATE REGRESSION
   - OLD aggregated 6 distinct knowledge types across 30 sessions
   - NEW aggregates 4 types (and some are different)
   - **Impact**: Less comprehensive methodology extraction
   - **Severity**: 🟡 MEDIUM — Information loss but page still functional

3. **Playbook Visibility** — REMOVED
   - OLD had dedicated "Playbook" card on session detail
   - NEW has no equivalent
   - **Impact**: Can't see extracted methodology per session
   - **Severity**: 🔴 HIGH — Entire feature gone

#### What IMPROVED (Better in New Version)

1. **Live Session Tracking** — BRAND NEW
   - Active session monitoring with 5-second auto-refresh
   - Real-time tool count, error count, files touched
   - Tool breakdown visualization (bar chart)
   - **Impact**: Visibility into what's happening RIGHT NOW
   - **Value**: 🟢 HIGH — New capability

2. **Code Efficiency** — MINOR IMPROVEMENT
   - Dashboard code is leaner (-20 lines on learnings page)
   - Fewer DB columns to fetch
   - **Impact**: Likely faster page loads
   - **Value**: 🟢 LOW — Marginal improvement

3. **IDE Integration** — MAJOR NEW FEATURE
   - Conditional settings UI for Kiro/Cursor
   - Explains MCP tools inline
   - Read-only mode when IDE is managing LLM
   - **Impact**: Better UX for Kiro/Cursor users
   - **Value**: 🟢 HIGH — Improved onboarding/UX

4. **Swarm Cloud Configuration** — ENHANCED
   - Added director_mode option
   - Added managed provisioning button
   - **Impact**: Better cloud orchestration support
   - **Value**: 🟢 MEDIUM — New enterprise feature

---

## DATABASE SCHEMA IMPACT

### OLD Schema (Implied from dashboard.py 229055d)

Insights table columns:
```
- skill_opportunity
- session_type
- workflow_stage
- summary
- claude_md_rules
- playbook
- effective_prompts
- anti_patterns
- knowledge_domains
- reusable_patterns
- bugs
- session_id
```

### NEW Schema (Implied from current dashboard.py)

Insights table columns (reduced):
```
- skill_opportunity
- summary
- bugs
- session_id
```

New separate tables:
```
- patterns (COUNT queries)
- decisions (COUNT queries)
```

**Migration Impact**: If a user upgrades from old to new without DB migration, they will:
1. See empty/zero counts for Patterns and Decisions
2. See reduced session detail information
3. See much simpler learnings page
4. Lose historical playbooks, prompts, anti-patterns, tools metadata

**This is a BREAKING CHANGE** unless there's a migration script to populate the new `patterns` and `decisions` tables from the old data.

---

## NEW API ROUTES

### `/api/session/start` (NEW)

```
POST /api/session/start
Payload: { session_id, project }
Response: { ok: bool }
Purpose: Webhook to signal active session start
Side Effect: Initializes _live_session in-memory state
```

**Use**: Called when agent spawns (hooks integration)

### `/api/live-session` (NEW)

```
GET /api/live-session
Response: HTML partial (div with HTMX attributes)
Purpose: Render live session card for homepage
HTMX: hx-trigger="every 5s", hx-swap="outerHTML"
```

**Use**: Auto-refreshing session monitor on homepage

### `/api/session/start` POST Handler (MODIFIED)

- NEW webhook integration for session start events
- Populates _live_session state with session metadata
- Resets error counters and file lists
- Threads-safe with _live_lock

---

## VISUAL/STYLING CHANGES

### CSS (NO CHANGES)

Both versions use identical CSS:
- Same color palette (teal, blue, amber, red, gray)
- Same grid layout (.kpi-row)
- Same card styling (.card, .rule)
- Same typography hierarchy

### NEW CSS Animations

```css
@keyframes pulse {
  0%, 100% { opacity: 1 }
  50% { opacity: 0.3 }
}
```

**Used for**: Live session indicator dot (pulsing green circle)

### Layout Additions (Live Session Card)

```
- Gradient background: linear-gradient(135deg, #0a1a12, #071510)
- 3-column grid for Project/Started/Tools
- Tool breakdown bar chart visualization
- File badge wrap layout
- Error list with overflow ellipsis
```

**Visual Impact**: Homepage is now more "alive" with real-time indicators

---

## FUNCTIONALITY MATRIX

| Feature Category | Old | New | Delta | Verdict |
|-----------------|-----|-----|-------|---------|
| Home KPIs | 6 cards | 6 cards | 0 | ✅ STABLE |
| Session list | Table | Table | 0 | ✅ STABLE |
| Session detail | 9 cards | 4 cards | -5 | 🔴 REGRESSION |
| Bugs view | Full list | Full list | 0 | ✅ STABLE |
| Learnings | 6 sections | 4 sections | -2 | 🟡 REGRESSION |
| Settings | Full form | IDE-aware form | +1 | 🟢 IMPROVEMENT |
| Live tracking | None | HTMX auto-refresh | +1 | 🟢 NEW |
| API routes | 8 | 10 | +2 | 🟢 GROWTH |
| Lines of code | 1523 | 1618 | +95 | 🟡 GROWTH |

---

## SUMMARY OF GAPS

### Features in OLD but MISSING from CURRENT (❌ Removed)

1. ✅ **Playbook Card** (session detail) — Rich methodology extraction
2. ✅ **Architectural Decisions Card** (session detail) — System design notes
3. ✅ **Effective Prompts Card** (session detail) — Useful prompt templates
4. ✅ **Anti-Patterns Card** (session detail) — Common pitfalls
5. ✅ **Tools Used Card** (session detail) — Bar chart of tool usage
6. ✅ **Knowledge Domains Card** (session detail) — Domain tags
7. ✅ **Files Touched Card** (session detail) — List of modified files
8. ✅ **Reusable Patterns Card** (session detail) — Pattern recommendations
9. ✅ **Effective Prompts Section** (learnings) — Prompt templates
10. ✅ **Anti-Patterns Section** (learnings) — Pitfalls to avoid
11. ✅ **Playbooks Section** (learnings) — Team methodology
12. ✅ **Knowledge Domains Section** (learnings) — Domain taxonomy

**Total Removed**: 12 major UI elements
**Severity**: 🔴 HIGH — Significant feature loss for detailed session analysis

### Features in CURRENT but NOT in OLD (🆕 New)

1. 🆕 **Live Session Card** (homepage) — Real-time session monitoring
   - Tool breakdown visualization
   - File tracking
   - Error display
   - 5-second auto-refresh via HTMX

2. 🆕 **IDE Detection & Conditional UI** (settings)
   - Kiro/Cursor mode (minimal settings)
   - BYOK mode (full settings)
   - MCP command reference (16 tools)

3. 🆕 **Patterns Section** (learnings) — Git-scanned patterns
   - Deterministic, not LLM-extracted

4. 🆕 **Architectural Decisions Section** (learnings)
   - NEW extraction type (not in old learnings)

5. 🆕 **Optimizations Card** (session detail) — Optimization suggestions
   - NEW extraction type

6. 🆕 **Themes Card** (session detail) — Extracted themes
   - NEW extraction type

7. 🆕 **API Routes**:
   - `/api/session/start` — Session start webhook
   - `/api/live-session` — Live session HTML partial

8. 🆕 **Swarm Cloud Features** (settings)
   - Director mode toggle
   - Managed provisioning button

**Total New**: 8 major features
**Severity**: 🟢 MEDIUM-HIGH — Good additions but don't replace lost functionality

### Features that REGRESSED (Worse but Not Gone)

1. ⚠️ **Session Detail Density** — Reduced from 9 cards to 4
   - Lost rich metadata per session
   - But new cards (Bugs, Optimizations) added
   - Net result: Different data, not more/less

2. ⚠️ **Learnings Aggregation** — Reduced from 6 to 4 sections
   - Lost prompt/pattern/anti-pattern methodology
   - Gained patterns from git scan
   - Net result: Simpler but less comprehensive

3. ⚠️ **DB Schema Compatibility** — Breaking change
   - Old columns (playbook, effective_prompts, etc.) no longer queried
   - Requires migration to populate new tables (patterns, decisions)

### Features that IMPROVED

1. ✅ **Real-Time Visibility** — Live session monitoring is new/better
2. ✅ **IDE UX** — Conditional settings for Kiro/Cursor users
3. ✅ **Code Efficiency** — Leaner codebase (-20 lines on learnings)
4. ✅ **Enterprise Cloud** — New swarm orchestration features

---

## CONCLUSION

The current dashboard is **NOT** a simple UI refresh. It's a **restructuring around a different data model**:

- **Old Model**: Rich LLM extraction (playbooks, prompts, patterns, decisions, anti-patterns, domains)
- **New Model**: Simpler deterministic + selective LLM extraction (bugs, optimizations, themes, patterns from git)

**What This Means**:

| User Type | Impact |
|-----------|--------|
| **Kiro/Cursor user** | 🟢 BETTER — IDE mode, MCP tools visible, cleaner UX |
| **BYOK Anthropic user** | 🟡 MIXED — Live session tracking is great, but lost session metadata |
| **Power user wanting methodology** | 🔴 WORSE — Lost playbooks, prompts, anti-patterns, architectural decisions |
| **Enterprise with Swarm Cloud** | 🟢 BETTER — New provisioning options, director mode |

**Migration Risk**: If deploying to users with old `echo.db`, the new dashboard will show empty/zero counts for patterns and decisions until those tables are populated. Session detail pages will show reduced information.

**Recommendation**:
1. Add a DB migration script to either (a) populate new tables from old data or (b) handle missing columns gracefully
2. Add a migration notice to the dashboard ("Reindexing. Some features coming online...")
3. Document the schema change in release notes
