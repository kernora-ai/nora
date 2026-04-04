# Provisional Patent Application — Description of Invention

**Title:** System and Method for Automated Extraction, Scoring, and Decay Modeling of Engineering Intelligence from AI-Assisted Development Sessions

**Applicant:** Kernora, Inc.
**Filing Type:** Provisional Patent Application (USPTO)
**Filing Fee:** $320 (Micro Entity)
**Priority Date Target:** [To be filed]

---

## Field of the Invention

This invention relates to software development tools, and more particularly to systems and methods for automatically capturing, analyzing, scoring, and managing the lifecycle of engineering knowledge produced during AI-assisted software development sessions across multiple AI tools and platforms.

---

## Background of the Invention

Modern software development increasingly relies on AI-assisted coding tools such as large language model (LLM) chat interfaces, AI code editors, and AI-powered integrated development environments. During these sessions, developers make architectural decisions, discover reusable patterns, identify anti-patterns, and establish coding conventions. This engineering intelligence is currently ephemeral — it exists only in session transcripts that are rarely reviewed and quickly become stale.

Existing solutions are limited to raw transcript storage (chat logs), manual documentation (wiki pages, README files), or project-specific instruction files (e.g., CLAUDE.md). None of these approaches automatically extract structured intelligence from sessions, score that intelligence for relevance and novelty, model its decay over time, or correlate insights across multiple AI tools used by the same developer or team.

There is a need for a system that automatically converts raw AI session transcripts into structured, scored, and lifecycle-managed engineering knowledge — a system that treats engineering intelligence as a depreciating asset with measurable value, rather than a static log.

---

## Summary of the Invention

The present invention provides a local-first system and method comprising:

1. **A multi-tool session capture pipeline** using tool-specific adapters ("Claws") that communicate with a central analysis engine ("Nora Engine") via a standardized protocol over a local inter-process communication channel.

2. **An automated intelligence extraction engine** that processes raw session transcripts to identify and classify structured knowledge artifacts including reusable patterns ("Playbooks"), failure modes ("Anti-Patterns"), codifiable conventions ("Rules"), and defects ("Bugs").

3. **A composite intelligence scoring algorithm** ("Knowledge Intelligence Quotient" or "KIQ") that computes a single numeric score representing the engineering intelligence value of individual sessions and aggregated project knowledge bases.

4. **A temporal decay model** ("Intelligence Half-Life") that models the relevance degradation of extracted knowledge artifacts over time based on technology lifecycle characteristics, reinforcement frequency, and domain volatility.

---

## Detailed Description of the Invention

### 1. Multi-Tool Session Capture Pipeline

#### 1.1 Architecture

The system consists of two primary components:

- **Nora Engine**: A locally-executing analysis engine that receives session data, performs intelligence extraction, computes scores, and manages the knowledge lifecycle. The engine persists all data in a local SQLite database and exposes a local HTTP dashboard for visualization.

- **Claws**: Per-tool adapter modules that capture session transcripts from AI development tools and transmit them to the Nora Engine. Each Claw is purpose-built for a specific tool's interface paradigm (CLI plugin, IDE extension, browser extension, desktop app integration).

#### 1.2 Claw Protocol

Claws communicate with the Nora Engine via a standardized JSON protocol transmitted over a Unix domain socket (e.g., `~/.kernora/nora.sock`). The protocol defines a message envelope containing:

```
{
  "protocol_version": "1.0",
  "claw_id": "<tool-identifier>",
  "claw_version": "<semantic-version>",
  "event_type": "session_start | message | session_end | heartbeat",
  "timestamp": "<ISO-8601>",
  "payload": {
    "session_id": "<uuid>",
    "role": "user | assistant | system",
    "content": "<message-text>",
    "metadata": {
      "tool_version": "<string>",
      "model": "<llm-model-identifier>",
      "project_path": "<filesystem-path>",
      "files_touched": ["<path>", ...],
      "tokens_used": { "input": <int>, "output": <int> }
    }
  }
}
```

The protocol is designed for unidirectional data flow (Claw → Engine) with optional acknowledgment responses. All communication occurs over the local socket — no network boundary is crossed. The protocol specification is published to enable third-party Claw development while the analysis engine's scoring algorithms remain proprietary.

#### 1.3 Supported Tool Adapters

The initial implementation includes Claws for:

- **claude-claw**: Captures sessions from Claude Code (CLI), Claude Chat (web), and Claude Desktop (native app) via the Claude plugin architecture.
- **kiro-claw**: VS Code extension for Amazon Kiro, built on a shared VS Code extension infrastructure.
- **vscode-claw**: Shared infrastructure for VS Code-based AI tools, providing common capture capabilities.
- **cursor-claw**: Adapter for Cursor AI editor.
- **cline-claw**: Adapter for Cline AI assistant.

Each Claw handles tool-specific session boundary detection, message extraction, and metadata enrichment before transmitting standardized protocol messages to the engine.

### 2. Automated Intelligence Extraction Engine

#### 2.1 Extraction Pipeline

Upon receiving a completed session transcript, the Nora Engine processes it through a multi-stage extraction pipeline:

**Stage 1 — Segmentation:** The raw transcript is segmented into logical conversation units (problem identification, solution exploration, implementation, verification, retrospection).

**Stage 2 — Classification:** Each segment is classified by content type: architectural decision, implementation pattern, bug discovery, convention establishment, debugging methodology, performance optimization, security consideration, or general discussion.

**Stage 3 — Artifact Extraction:** Classified segments are processed to extract structured knowledge artifacts:

- **Playbooks**: Reusable approaches that demonstrate a successful pattern. Each playbook includes: a descriptive title, the problem context, the approach taken, the outcome, and applicability conditions (when to use this pattern again).

- **Anti-Patterns**: Identified failure modes or suboptimal approaches. Each anti-pattern includes: the mistake description, why it fails, the observable symptoms, and the recommended alternative.

- **Rules**: Conventions specific enough to be codified as machine-readable instructions for future AI sessions. Each rule includes: the rule statement, the rationale, code examples of correct and incorrect usage, and the detection pattern (how to verify compliance).

- **Bugs**: Defects discovered during the session. Each bug includes: the symptom, the root cause, the file(s) affected, the severity assessment, and whether it represents a new discovery or a recurrence of a previously identified issue.

**Stage 4 — Deduplication and Linking:** Extracted artifacts are compared against the existing knowledge base using semantic similarity. Duplicate or near-duplicate artifacts are merged, with the newer extraction updating the timestamp and reinforcement count. Related artifacts across sessions are linked (e.g., an anti-pattern in session A linked to the playbook in session B that resolves it).

#### 2.2 Cross-Tool Correlation

The engine maintains a unified knowledge graph across all Claws. When the same developer uses multiple AI tools (e.g., Claude Code for backend, Cursor for frontend), the engine can detect:

- **Contradictory conventions**: A rule established in one tool that conflicts with a pattern used in another.
- **Recurring anti-patterns**: The same failure mode appearing across different tools, suggesting a systemic knowledge gap rather than a tool-specific issue.
- **Complementary playbooks**: Patterns from different tools that, combined, form a more complete approach.

Cross-tool correlation is performed by maintaining tool-agnostic artifact representations and computing similarity across the full artifact store, regardless of source Claw.

### 3. Knowledge Intelligence Quotient (KIQ) Scoring Algorithm

#### 3.1 Session-Level KIQ

Each analyzed session receives a KIQ score from 0-100, computed from four weighted components:

**Component 1 — Pattern Density (weight: 0.30):** The number of extractable artifacts per unit of session length, normalized against historical baselines. Higher density indicates a more intellectually productive session.

**Component 2 — Novelty Ratio (weight: 0.30):** The proportion of extracted artifacts that are genuinely new (not duplicates or near-duplicates of existing knowledge base entries). A session that produces entirely novel insights scores higher than one that reinforces existing patterns.

**Component 3 — Severity Distribution (weight: 0.20):** For bug-containing sessions, the weighted severity of discovered defects. Critical bugs discovered contribute more to the score than low-severity findings, reflecting their higher impact value.

**Component 4 — Cross-Session Coherence (weight: 0.20):** The degree to which the session's artifacts connect to and reinforce the existing knowledge graph. Isolated, unconnectable insights score lower than those that fill gaps in established pattern clusters.

The weights are configurable per project to reflect different engineering priorities (e.g., a security-focused project may weight severity distribution higher).

#### 3.2 Aggregate KIQ

The project-level or team-level KIQ is computed as a time-weighted aggregate of all session KIQs, where recent sessions contribute more than older ones (governed by the Intelligence Half-Life model described below). The aggregate KIQ represents the current "health" of the project's engineering intelligence base.

#### 3.3 KIQ Delta

The KIQ Delta measures the change in aggregate KIQ over a defined period (typically one week). A positive delta indicates net knowledge accumulation; a negative delta indicates knowledge decay outpacing new extraction. This metric serves as a leading indicator of engineering team learning velocity.

### 4. Intelligence Half-Life Temporal Decay Model

#### 4.1 Concept

Every extracted knowledge artifact is assigned an **Intelligence Half-Life** — the estimated time period after which the artifact retains only 50% of its original relevance weight in KIQ calculations.

The model recognizes that engineering knowledge is not permanent. API conventions change with new SDK versions. Workarounds become unnecessary when bugs are fixed. Performance patterns shift with hardware evolution. Frameworks deprecate features. A knowledge base that doesn't account for this decay will overweight stale patterns and underweight recent discoveries.

#### 4.2 Half-Life Computation

The half-life of an artifact is determined by three factors:

**Factor 1 — Domain Volatility:** Technology domains have characteristic rates of change. Mobile OS APIs (high volatility, ~6 month half-life for version-specific patterns), database query optimization (moderate volatility, ~18 month half-life), fundamental algorithms (low volatility, ~5 year half-life). Domain classification is performed during extraction.

**Factor 2 — Reinforcement Frequency:** Each time a pattern is re-extracted from a new session (or a contradicting pattern is NOT observed despite the opportunity), its half-life extends. Frequently reinforced patterns decay more slowly because repeated observation provides evidence of continued relevance.

**Factor 3 — Explicit Signals:** If a newer session produces an artifact that explicitly supersedes an older one (e.g., "Use the new API instead of the deprecated one"), the older artifact's half-life is immediately reduced to near-zero and it is flagged as superseded.

#### 4.3 Decay Function

The relevance weight of an artifact at time *t* is computed as:

```
W(t) = W₀ × (0.5)^((t - t_last) / H)
```

Where:
- `W₀` is the initial weight (based on artifact quality and session KIQ)
- `t` is the current time
- `t_last` is the timestamp of the most recent reinforcement
- `H` is the computed half-life in days

Artifacts whose weight drops below a configurable threshold (default: 0.05) are marked as "decayed" in the dashboard and excluded from active KIQ calculations, though they remain in the database for historical analysis.

---

## Claims

### Independent Claims

1. A computer-implemented method for extracting engineering intelligence from AI-assisted development sessions, comprising:
   (a) receiving session transcript data from one or more tool-specific adapter modules via a standardized protocol over a local inter-process communication channel;
   (b) processing the transcript through a multi-stage extraction pipeline to produce structured knowledge artifacts classified as playbooks, anti-patterns, rules, or bugs;
   (c) computing a composite intelligence score for each session and for the aggregate knowledge base; and
   (d) applying a temporal decay model to each extracted artifact to model relevance degradation over time.

2. A system for capturing and analyzing engineering intelligence from AI-assisted development sessions, comprising:
   (a) a plurality of tool-specific adapter modules, each configured to capture session transcripts from a specific AI development tool and transmit them via a standardized message protocol;
   (b) a locally-executing analysis engine that receives transmitted session data, extracts structured knowledge artifacts, computes intelligence scores, and manages artifact lifecycle including temporal decay;
   (c) a local data store for persisting extracted artifacts and computed scores; and
   (d) a visualization interface for displaying intelligence scores, artifact inventories, and temporal decay status.

### Dependent Claims

3. The method of claim 1, wherein the composite intelligence score (KIQ) is computed from weighted components including pattern density, novelty ratio, severity distribution, and cross-session coherence.

4. The method of claim 1, wherein the temporal decay model computes an artifact half-life based on domain volatility, reinforcement frequency, and explicit supersession signals.

5. The method of claim 1, further comprising cross-tool correlation that detects contradictory conventions, recurring anti-patterns, and complementary playbooks across artifacts extracted from different AI tools.

6. The system of claim 2, wherein the standardized message protocol uses a JSON envelope transmitted over a Unix domain socket, containing fields for protocol version, tool identifier, event type, timestamp, and a payload comprising session content and metadata.

7. The system of claim 2, wherein the analysis engine performs deduplication of extracted artifacts using semantic similarity comparison against the existing knowledge base, merging duplicates while preserving reinforcement history.

8. The method of claim 1, wherein a KIQ Delta metric is computed over a defined time period to measure net knowledge accumulation or decay.

9. The system of claim 2, wherein the system operates in a local-first architecture with zero data transmission to external servers in a default operating mode, and optional team synchronization to a user-controlled cloud storage bucket in a team operating mode.

10. The method of claim 4, wherein the relevance weight of an artifact at time *t* follows an exponential decay function: W(t) = W₀ × (0.5)^((t - t_last) / H), where W₀ is the initial weight, t_last is the most recent reinforcement timestamp, and H is the computed half-life.

---

## Abstract

A system and method for automatically extracting, scoring, and lifecycle-managing engineering intelligence from AI-assisted software development sessions. Tool-specific adapters ("Claws") capture session transcripts from multiple AI development tools and transmit them to a locally-executing analysis engine ("Nora Engine") via a standardized protocol over a local inter-process communication channel. The engine processes transcripts through a multi-stage extraction pipeline to produce structured knowledge artifacts (playbooks, anti-patterns, rules, bugs), computes a composite Knowledge Intelligence Quotient (KIQ) score for individual sessions and aggregate knowledge bases, performs cross-tool correlation to detect contradictions and recurring patterns, and applies an Intelligence Half-Life temporal decay model to reflect the diminishing relevance of engineering knowledge over time. The system operates in a local-first architecture with zero external data transmission in its default mode.

---

## Filing Notes

**Prior Art Considerations:**
- Session transcript logging (existing in Claude Code, Cursor, etc.) — captures data but does not extract, score, or decay-model structured intelligence.
- CLAUDE.md / .cursorrules files — manually maintained project instructions, not automatically extracted from sessions.
- Code intelligence tools (SonarQube, CodeClimate) — analyze code artifacts, not AI session transcripts.
- Knowledge management systems (Notion, Confluence) — manual documentation, not automated extraction from development sessions.

**Differentiation:**
The core novelty lies in the combination of: (1) multi-tool capture via a standardized local protocol, (2) automated structured extraction from unstructured session transcripts, (3) composite scoring of engineering intelligence value, and (4) temporal decay modeling of knowledge relevance. No existing system combines these four capabilities.

**Recommended Filing Timeline:**
File provisional within 30 days of first public disclosure (website launch / GitHub repo publication). The provisional establishes priority date and provides 12 months to file the full non-provisional application.

**Cost Estimate:**
- Provisional filing (micro entity): $320
- Patent attorney review (optional, recommended): $1,500-3,000
- Non-provisional filing (within 12 months): $1,600 (micro entity) + attorney fees
