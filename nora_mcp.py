#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
from __future__ import annotations  # PEP 563: str|None works on Python 3.9+
import db
"""
Nora MCP Server — exposes session intelligence to Claude Code and Claude Desktop.

Run standalone:  python3 nora_mcp.py
Run via Claude:  Configured in ~/.claude/settings.json mcpServers
Run via Desktop: Configured in claude_desktop_config.json

Tools:
  nora_search              — full-text search across patterns, decisions, bugs, insights
  nora_context_for_task    — task-scoped intelligence lookup (patterns/decisions/bugs, intent-weighted)
  nora_factbook_view       — read the project factbook (facts, layers, supersession chains)
  nora_factbook            — factbook lifecycle: create/update/delete/commit a factbook doc
  nora_factbook_inject     — render factbook facts for injection into an agent prompt/steering file
  nora_factbook_verify     — mark a factbook fact verified (citation-traceable)
  nora_generate            — emit steering files (.cursorrules, .github/copilot-instructions.md, etc.)
  nora_roi                 — return-on-intelligence report (engagement + leverage signal)
  nora_claude_memory       — bridge to Claude Code project memory (~/.claude/projects/<p>/memory/MEMORY.md)
  nora_pe_review           — multi-lens PE review prompt (static; no daemon dependency)
  nora_factbook_promote    — promote a pending/candidate fact into the live factbook
  nora_provenance          — per-fact citation/provenance lookup

SECURITY: Read-only access to local echo.db.
          No network calls beyond MCP stdio.
"""

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import steering_writer

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent



PE_REVIEW_LENSES = {
    "se_correctness": {
        "title": "SOFTWARE ENGINEERING (correctness, security, hygiene)",
        "rubric": (
            "**CRITICAL** — Security, data integrity, compliance: hardcoded secrets, "
            "SQL injection / path traversal / XSS, unvalidated input in sensitive paths, "
            "missing auth/authz checks.\n"
            "**HIGH** — Correctness + error handling: async without try/catch, silent "
            "failure swallowing, race conditions, missing input validation on public APIs.\n"
            "**MEDIUM** — Performance, accessibility, UX: N+1 queries, unbounded loops, "
            "missing loading/error states, accessibility violations.\n"
            "**LOW** — Style, naming, dead code, duplicate type definitions, missing docs."
        ),
    },
    "ai_usability": {
        "title": "AI / LLM USABILITY (would an LLM caller succeed)",
        "rubric": (
            "Evaluate from the LLM CALLER's perspective:\n"
            "  • Discoverability — can the LLM tell what each tool does in 1 sentence? "
            "Is the verb + intent front-loaded, not buried in jargon?\n"
            "  • Selection clarity — when intent maps to multiple tools, is there ONE "
            "obvious pick? Surface confusion pairs.\n"
            "  • Argument unambiguity — for action-routed tools (action=enum), is each "
            "action's required-fields contract explicit?\n"
            "  • Error recovery — does the error message tell the LLM how to recover, "
            "with an example call?\n"
            "  • Description budget — any tool description bloated past its information value?"
        ),
    },
    "ai_data_science": {
        "title": "AI DATA SCIENCE (eval methodology + measurement)",
        "rubric": (
            "Scrutinize the empirical claims behind the change:\n"
            "  • Is each ship-decision rule preregistered, with a falsifiable bar?\n"
            "  • Sample size — n=1 trials are smoke tests, not benchmarks. Is the "
            "evidence base statistically defensible?\n"
            "  • Construct validity — does the metric measure the user-facing question, "
            "or a proxy that's easy to compute (e.g. dispatch latency vs. LLM pick rate)?\n"
            "  • Telemetry continuity — do renames break historical metrics? Is there a "
            "migration mapping?\n"
            "  • Closed-loop measurement — is there infrastructure to detect regressions "
            "post-ship, or are we shipping unfalsifiable claims?"
        ),
    },
    "ux_usability": {
        "title": "UI/UX + USABILITY (the human reading the output)",
        "rubric": (
            "Evaluate from a real human typing commands and reading output:\n"
            "  • Are CLI commands discoverable + their flags self-explanatory?\n"
            "  • Do error messages name the user's next step, or just complain-and-die?\n"
            "  • Is internal taxonomy (persona tags, alias notes, batch numbers) leaking "
            "into customer-facing copy?\n"
            "  • Is there a dashboard surface for any feature added — or is it CLI-only?\n"
            "  • Restart instructions — do they actually work for the user's specific "
            "MCP client (Claude Code / Cursor / Kiro behave differently)?\n"
            "  • Are role names + menu labels written in user language, not jargon?"
        ),
    },
    "mcp_agent": {
        "title": "MCP STANDARDS + AI AGENT ERGONOMICS",
        "rubric": (
            "Evaluate spec compliance + autonomous-agent usability:\n"
            "  • Does the server emit `notifications/tools/list_changed` when the "
            "served list mutates (persona/mode change)?\n"
            "  • Does inputSchema enforce conditional required fields (e.g. via "
            "JSON-Schema oneOf for action-routed tools)?\n"
            "  • Are stateful workflow handoffs structured (e.g. structuredContent "
            "with named fields like panel_id) or opaque JSON-in-text?\n"
            "  • Do error responses set isError:true, or do agents have to keyword-match "
            "'Error:' to distinguish failure from result?\n"
            "  • Are tool descriptions ≤1024 chars (some clients truncate)?\n"
            "  • Mid-session env changes — would the agent's KERNORA_PERSONA flip "
            "actually take effect, or is it frozen at server launch?"
        ),
    },
    "tenets_alignment": {
        "title": "TENETS ALIGNMENT (product, technical, architectural)",
        "rubric": (
            "Cross-check the change against the project's stated tenets:\n"
            "  • Read CLAUDE.md (Build Constraint, Living Factbook v1.1, Mode 1/2 split).\n"
            "  • Read .nora/kernora-factbook.yaml (Core Tenets, Engineering Rules).\n"
            "  • Read .nora/lite-mode-factbook.yaml (lf### constraints across reuse, "
            "invariant, anti_pattern, test_discipline, docs_discipline, operational).\n"
            "  • Read docs/MCP-TOOL-SURFACE-ASSESSMENT-APR-25-2026.md §3 (T1-T10 tool tenets).\n"
            "  • For each tenet, classify the change as: ALIGNED / DRIFT (violates) / "
            "AMBIGUOUS (tenet doesn't clearly apply) / MISSED (tenet not consulted).\n"
            "  • If the change supersedes an empirically-derived prior decision (lf###), "
            "explicitly retire the old fact with new evidence; never let two contradictory "
            "facts coexist in the factbook.\n"
            "  • Verify customer-emitted artifacts (steering files in .cursorrules / "
            ".copilot-instructions.md / .kiro/steering/) still resolve correctly."
        ),
    },
}

PE_REVIEW_PROCESS = (
    "1. Discovery — scan codebase structure, identify changed files (git diff).\n"
    "2. Per-lens audit — produce a separate findings block per lens. Use the "
    "BLOCKER / HIGH / MEDIUM / LOW severity scale within each lens.\n"
    "3. Cross-lens synthesis — list contradictions where one lens says ship and "
    "another says don't.\n"
    "4. Unified verdict — SHIP / FIX-THEN-SHIP / REVERT, with the smallest set "
    "of patches needed before merge.\n"
    "5. Report — every finding cites file:line. Every recommendation has an "
    "estimated minutes-to-fix."
)



def _load_bridge_threshold() -> float:
    """Read [bridge] min_confidence from ~/.kernora/config.toml; default 0.85."""
    try:
        import tomllib
        cfg_path = Path.home() / ".kernora" / "config.toml"
        if not cfg_path.exists():
            return 0.85
        with cfg_path.open("rb") as f:
            cfg = tomllib.load(f)
        val = cfg.get("bridge", {}).get("min_confidence", 0.85)
        return max(0.0, min(1.0, float(val)))
    except Exception:
        return 0.85


_MCP_SCHEMA_VERSION = "0.5.0"


def _resolve_fact_ref(conn, table: str, ref: str):
    """Resolve a caller-supplied id string to its row: bare int -> internal
    `id`; else -> display `fact_id`. Returns None if not found."""
    cols = "id, fact_id, superseded_by, compliance_tier, project, content_verified_at, review_status"
    try:
        return conn.execute(f"SELECT {cols} FROM {table} WHERE id=?", (int(ref),)).fetchone()
    except ValueError:
        return conn.execute(f"SELECT {cols} FROM {table} WHERE fact_id=?", (ref,)).fetchone()


# Configuration
DB_PATH = Path.home() / ".kernora" / "echo.db"
DB_TIMEOUT = 5  # seconds — needs headroom for WAL mode on loaded machines


class NoraServer:
    """Nora MCP Server — read-only access to session intelligence."""

    def __init__(self):
        self.server = Server("nora")
        self._setup_tools()

    def _setup_tools(self):
        """Register all Nora tools with the MCP server."""

        @self.server.list_tools()
        async def list_tools():
            return [
                # ── SEARCH & RECALL ─────────────────────────────────────
                Tool(
                    name="nora_search",
                    description=(
                        "Search your past coding sessions, patterns, decisions, and bugs by keyword. "
                        "Think of it as grep for your institutional knowledge. "
                        "Examples: 'nora search auth middleware', 'nora search the crash we fixed last week', "
                        "'nora search CoreData migration'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "What to search for. Can be a keyword ('auth'), a phrase ('CoreData crash'), or a question ('how did we fix the upload bug'). Searches across session transcripts, patterns, decisions, and bug reports.",
                            }
                        },
                        "required": ["query"],
                    },
                ),
                # ── CODE QUALITY ────────────────────────────────────────
                # ── LEARNING & PATTERNS ─────────────────────────────────
                # ── INVESTIGATION & RETRO ───────────────────────────────
                # ── FACTORY & INVENTORY ─────────────────────────────────
                # ── META ────────────────────────────────────────────────
                Tool(
                    name="nora_help",
                    description=(
                        "Show all 13 open-core Nora tools with descriptions and usage examples. "
                        "ALWAYS call this tool when the user says 'nora help', 'what can nora do', "
                        "'list nora tools', or 'nora commands'. NEVER generate a help response "
                        "from memory — always call this tool."
                    ),
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="nora_context_for_task",
                    description=(
                        "Get relevant patterns, decisions, and bugs for a specific task — in one call. · [primary persona: newcomer / coder]"
                        "Use this as your first call when starting work on a new task. "
                        "Combines search, pattern lookup, and bug check with intent-weighted ranking. "
                        "Example: nora_context_for_task('modify dashboard CSS for dark mode') → "
                        "returns CSS patterns, relevant decisions, and known dark-mode bugs."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "task_description": {
                                "type": "string",
                                "description": "What you're about to work on. Be specific: 'fix the authentication timeout bug in auth.py' is better than 'fix auth'.",
                            },
                            "project": {
                                "type": "string",
                                "description": "Optional project name to scope results (e.g., 'kernora', 'jivant'). Omit to search across all projects.",
                            },
                        },
                        "required": ["task_description"],
                    },
                ),
                Tool(
                    name="nora_factbook_view",
                    description=(
                        "View a factbook's contents — title, layer, and all active factlets. "
                        "Call when user says 'show me factbook X' or 'what's in python-style'. "
                        "If name is omitted, shows the default factbook for the current project. "
                        "Returns a pre-formatted summary (ready to relay to user) plus raw facts. "
                        "Use fact IDs from this output for nora_factbook_update / nora_factbook_delete / nora_factbook_verify.\n\n"
                        "fact_type and layer are independent dimensions: fact_type describes knowledge maturity; "
                        "layer describes organizational scope. Do not infer one from the other.\n\n"
                        "include_superseded: Set to True only when the caller needs audit history, compliance review, "
                        "or supersession-chain understanding (e.g., 'why did this decision change?', "
                        "'what was the previous policy?', 'show me the full ADR history'). "
                        "Default False returns canonical only — correct for grounding. "
                        "Setting True in a grounding context will confuse the model with stale facts.\n\n"
                        "Layer selection guidance (7-rule heuristic R1-R7, §17.6 P-06): "
                        "(R1) current git repo conventions → Codebase. "
                        "(R2) time-bounded delivery work → Project. "
                        "(R3) team agreements → Team. "
                        "(R4) company-wide policy → Company. "
                        "(R5) personal knowledge → Individual. "
                        "(R6) registry-published vertical knowledge → Domain-Pack. "
                        "(R7) uncertain — omit layer (resolver logs [F404-LAYER-RESOLVED]).\n\n"
                        "Each factlet shows a FactSignal trust read (1-5) and a staleness label. "
                        "When grounding an answer: prefer trust HIGH (4-5) factlets; if you cite a "
                        "trust LOW (1-2) or stale factlet, add an explicit caveat naming its age "
                        "(e.g. 'last confirmed 96 days ago — verify before relying'); never cite a "
                        "factlet marked '⊛ superseded by fXXX' — cite the named successor instead."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Factbook name or kp_id. Optional — if omitted, uses default factbook for current project.",
                            },
                            "layer": {
                                "type": "string",
                                "enum": ["Individual", "Codebase", "Project", "Program", "Product", "Service", "Team", "Division", "Company", "Domain-Pack"],
                                "description": "Filter to factbooks at this organizational layer.",
                            },
                            "kp_id": {
                                "type": "string",
                                "description": "Explicit kp_id to view (overrides name lookup).",
                            },
                            "include_superseded": {
                                "type": "boolean",
                                "description": "Include superseded factlets. Default False (canonical only). Only set True for audit/history queries.",
                                "default": False,
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="nora_factbook",
                    description=(
                        "Lifecycle operations on a named factbook artifact (the YAML at "
                        ".nora/<name>.yaml). Replaces nora_factbook_create / _update / _delete / _commit. "
                        "Actions: create (bootstrap a new named factbook) · update (partial edit "
                        "of a fact's whitelisted fields) · delete (archive a single fact OR an "
                        "entire factbook) · commit (explicit git checkpoint, optionally push) · "
                        "provenance (return PROV-O lineage for a fact: sources, supersession, "
                        "confidence trajectory, decision-trace events). "
                        "Adds, reads, and verifies stay as separate tools (nora_factbook_add / "
                        "_view / _verify) per Tenet T3 (CRUD where blast radius differs). "
                        "nora_provenance is a top-level alias for action='provenance' (alias-retention "
                        "pattern per kernora factlet — discoverability without surface bloat)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["create", "update", "delete", "commit", "provenance"],
                            },
                            "name": {"type": "string",
                                     "description": "Factbook name (create/delete/commit)."},
                            "title": {"type": "string",
                                      "description": "(create) Display title."},
                            "scope": {"type": "string",
                                      "description": "(create) personal | project | team."},
                            "fact_id": {"type": "integer",
                                        "description": "(update/delete) Fact ID (integer)."},
                            "id": {"type": "string",
                                   "description": "(provenance) Fact ID — accepts 'f765', '765', or integer."},
                            "fields": {"type": "object",
                                       "description": "(update) Whitelisted fields to set."},
                            "reason": {"type": "string",
                                       "description": "(update) Why."},
                            "push": {"type": "boolean",
                                     "description": "(commit) Push to remote."},
                            "remote": {"type": "string",
                                       "description": "(commit) git remote name."},
                            "branch": {"type": "string",
                                       "description": "(commit) git branch name."},
                            "project": {"type": "string",
                                        "description": "(provenance) Optional project filter for decision_traces."},
                        },
                        "required": ["action"],
                    },
                ),
                Tool(
                    name="nora_factbook_inject",
                    description=(
                        "Deploy pending factbook changes to steering files immediately. "
                        "Regenerates CLAUDE.md, .cursorrules, .kiro/rules.md with latest facts. "
                        "Call after batch edits to deploy without waiting for nightly Dreamer (2 AM). "
                        "If name is omitted, injects default factbook for the current project. "
                        "Respects layer_precedence order — higher-authority layers win conflicts. "
                        "Response includes layer_resolved block when default-layer resolver was invoked. "
                        "T8b inject-time quality gate: factlets below min_compliance_tier are flagged "
                        "with quality_flag='below_min_tier' but still included. "
                        "Set require_verified=True to exclude unverified factlets (logged as "
                        "[T8B-INJECT-UNVERIFIED-EXCLUDED id=<id>]).\n\n"
                        "Layer selection guidance (7-rule heuristic R1-R7, §17.6 P-06): "
                        "(R1) current git repo conventions → Codebase. "
                        "(R2) time-bounded delivery work → Project. "
                        "(R3) team agreements → Team. "
                        "(R4) company-wide policy → Company. "
                        "(R5) personal knowledge → Individual. "
                        "(R6) registry-published vertical knowledge → Domain-Pack. "
                        "(R7) uncertain — omit layer (resolver logs [F404-LAYER-RESOLVED])."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Factbook name or kp_id. Optional — if omitted, uses default factbook for current project.",
                            },
                            "layer": {
                                "type": "string",
                                "enum": ["Individual", "Codebase", "Project", "Program", "Product", "Service", "Team", "Division", "Company", "Domain-Pack"],
                                "description": "Inject from factbooks at this layer. Omit to inject from all accessible layers ordered by precedence.",
                            },
                            "kp_id": {
                                "type": "string",
                                "description": "Explicit kp_id to inject from (overrides name lookup).",
                            },
                            "min_compliance_tier": {
                                "type": "string",
                                "enum": ["standard", "audit_required", "non_overridable"],
                                "description": "T8b advisory gate: factlets below this tier are flagged but included. Default 'standard'.",
                                "default": "standard",
                            },
                            "require_verified": {
                                "type": "boolean",
                                "description": "T8b: if True, exclude unverified factlets (verified_at IS NULL). Logged per f404.",
                                "default": False,
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="nora_factbook_verify",
                    description=(
                        "SPRINT 2: Verify a fact using Opus 4.7 reasoning (effort='xhigh') — an AI "
                        "re-assessment, distinct from nora_factbook_confirm (a human-relay log). "
                        "Uses LiteLLM to assess factuality, confidence, and source quality. On a "
                        "valid verdict this raises review_status to 'verified' (band 3, "
                        "'auto-verified') — it never reaches the top human-verified band; only the "
                        "`kernora verify` CLI wizard does that. Returns verified_confidence (may "
                        "differ from claimed), issues found, and reasoning. Call this to validate a "
                        "fact before deployment or to audit existing facts. If name is omitted, uses "
                        "the default factbook for the current project."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Factbook name or kp_id. Optional — if omitted, uses default factbook for current project.",
                            },
                            "fact_id": {
                                "type": "integer",
                                "description": "REQUIRED: Fact ID to verify (shown in nora_factbook_view output).",
                            },
                        },
                        "required": ["fact_id"],
                    },
                ),
                Tool(
                    name="nora_generate",
                    description=(
                        "Emit AI context files for THIS project — the in-chat equivalent "
                        "of `kernora generate` at the shell. Writes CLAUDE.md, .cursorrules, "
                        ".kiro/steering/, .github/copilot-instructions.md using the latest "
                        "factbook. Safe to re-run (idempotent; atomic writes). Typical trigger: "
                        "the user says `nora generate` or `generate steering files`. "
                        "Pass preview=true to see what WOULD be written (with a diff summary) "
                        "WITHOUT modifying any files — recommended on the first run against "
                        "an existing rich CLAUDE.md so the user can confirm before committing."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "preview": {
                                "type": "boolean",
                                "description": "If true, return the proposed content + diff summary without writing. Default false.",
                                "default": False,
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="nora_roi",
                    description=(
                        "Return-on-Intelligence report graded by the CURRENT session LLM "
                        "on THIS project. Default mode (in-session, format=human): assembles "
                        "a SLIM evidence block + render template — YOU fill the template inline "
                        "producing customer-facing markdown (verdict-first, comparative-anchored, "
                        "citation-summarized, CTA at end). No raw rubric dump. "
                        "format=json → full rubric back-compat (power users / --save). "
                        "format=both → human render + collapsed JSON <details>. "
                        "For multi-vendor benchmark runs pass panel=true (uses LiteLLM + vendor "
                        "API keys). For a specific non-session model use model='<vendor/slug>' "
                        "with external=true. Examples: 'nora roi', "
                        "'run roi on this project', 'would paying $50/mo for Nora be worth it'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "format": {
                                "type": "string",
                                "enum": ["human", "json", "both"],
                                "default": "human",
                                "description": (
                                    "human=customer-facing markdown (default); "
                                    "json=machine-grade JSON for --save (back-compat); "
                                    "both=human render + collapsed JSON details"
                                ),
                            },
                            "model": {
                                "type": "string",
                                "description": "Explicit model override (LiteLLM slug, e.g. 'anthropic/claude-opus-4-7'). Forces external API path.",
                            },
                            "panel": {
                                "type": "boolean",
                                "description": "Multi-vendor: one flagship per vendor whose *_API_KEY is set. Uses LiteLLM (external API). Default: false.",
                                "default": False,
                            },
                            "external": {
                                "type": "boolean",
                                "description": "Force external LiteLLM call even without model/panel. Default: false (use in-session).",
                                "default": False,
                            },
                            "dry_run": {
                                "type": "boolean",
                                "description": "Assemble + return the full prompt without any LLM call (free, useful for inspection).",
                                "default": False,
                            },
                            "directory": {
                                "type": "string",
                                "description": "Project root to grade. Default: current working directory.",
                                "default": ".",
                            },
                        },
                    },
                ),
                Tool(
                    name="nora_claude_memory",
                    description=(
                        "Export your Nora intelligence (patterns, anti-patterns, commit conventions, project context) "
                        "as a formatted block optimized for Claude's Memory feature. "
                        "Source priority: .nora/<factbook>.yaml if present (Lite-friendly) + ~/.kernora/echo.db (Companion supplement). "
                        "Pass write=true to sync the block to Anthropic's native memory: writes a sibling file "
                        "`nora-intelligence.md` next to MEMORY.md (with Nora markers internally for idempotent re-sync) "
                        "AND adds an index entry to MEMORY.md respecting whichever format it uses (## Entries + ### [link] "
                        "OR flat bulleted list — auto-detected). Refuses to write if MEMORY.md format is unrecognized to "
                        "avoid corrupting user content. Default write=false returns the block for copy-paste. "
                        "Examples: 'nora claude memory', 'sync Nora to Claude memory', 'export my factbook to Anthropic memory'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "max_chars": {
                                "type": "integer",
                                "description": "Max characters for output (Claude memory has limits). Default 3500.",
                                "default": 3500,
                            },
                            "write": {
                                "type": "boolean",
                                "description": "If true, write a sibling nora-intelligence.md file + add an index entry to MEMORY.md (idempotent; respects existing format). Default false (copy-paste path).",
                                "default": False,
                            },
                        },
                    },
                ),
                Tool(
                    name="nora_pe_review",
                    description=(
                        "Why use this instead of asking the LLM 'review my code': returns a "
                        "structured 6-lens review BRIEF that the IDE LLM then executes — "
                        "lenses include AI/MCP-spec correctness and tenet-alignment "
                        "perspectives a generic 'code review' prompt would miss. "
                        "Lenses: se_correctness (CRITICAL/HIGH/MEDIUM/LOW security + correctness), "
                        "ai_usability (would an LLM caller succeed), "
                        "ai_data_science (eval methodology + sample size + construct validity), "
                        "ux_usability (human-facing CLI/dashboard/error messages), "
                        "mcp_agent (MCP spec compliance + autonomous-agent ergonomics), "
                        "tenets_alignment (drift checks against CLAUDE.md + factbook + customer artifacts). "
                        "Each lens produces BLOCKER/HIGH/MEDIUM/LOW; the LLM synthesizes a "
                        "unified verdict (SHIP / FIX-THEN-SHIP / REVERT). "
                        "Examples: 'nora pe review' (all 6, full project), "
                        "'nora pe review src/auth/' (all 6, scoped), "
                        "'nora pe review lenses=[ai_usability,mcp_agent]' (subset)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "focus": {
                                "type": "string",
                                "description": "Optional focus area. Can be a directory ('src/auth/'), a file ('server.ts'), a recent diff ('the last commit'), or a concern ('just check error handling'). If omitted, audits the full project.",
                            },
                            "lenses": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": [
                                        "se_correctness",
                                        "ai_usability",
                                        "ai_data_science",
                                        "ux_usability",
                                        "mcp_agent",
                                        "tenets_alignment",
                                    ],
                                },
                                "description": "Optional subset of lenses to run. Omit to run all 6. Use a subset when scoping to a specific concern (e.g. ['mcp_agent'] for MCP-spec compliance only).",
                            },
                        },
                    },
                ),
                Tool(
                    name="nora_factbook_promote",
                    description=(
                        "Vet pending facts (3-reviewer panel) and promote passers to a factbook. "
                        "Replaces nora_pe_panel (which conflated PE-review with factbook governance). "
                        "Actions: list (show pending queue) · review (start panel on fact_ids — pass kp_id "
                        "for the target factbook, defaults to project's factbook) · submit (one reviewer's "
                        "scores+vetoes, ×3) · finalize (aggregate verdicts AND auto-promote passing facts to "
                        "the factbook via factbook_add_fact's canonical write path) · accept (single-fact "
                        "promote, skips panel) · reject (archive without promoting) · "
                        "supersede (mark a factlet as superseded by a newer one; REQUIRES supersedes_id parameter). "
                        "lf204: zero internal LLM calls — IDE LLM runs reviewer prompts. "
                        "Auto-promote uses panel_kind='promote' discriminator + kp_id threading "
                        "(PE-review B1 + H4 fix 2026-04-25).\n\n"
                        "PER-ACTION REQUIREMENTS:\n"
                        "action='list'      → no extra fields\n"
                        "action='review'    → also pass fact_ids (array of integers)\n"
                        "action='submit'    → also pass panel_id + role + scores\n"
                        "action='finalize'  → also pass panel_id\n"
                        "action='accept'    → also pass fact_id\n"
                        "action='reject'    → also pass fact_id\n"
                        "action='supersede' → REQUIRED: fact_id (new factlet) + supersedes_id (factlet "
                        "being superseded), both f### YAML ids in the canonical project factbook (a "
                        "bare integer is auto-prefixed with 'f'). Writes atomically via "
                        "nora_bridge.yaml_supersede — the f389 chokepoint. "
                        "Returns [F404-PROMOTE-MISSING-SUPERSEDES-ID] if supersedes_id absent, "
                        "[F404-SUPERSEDE-MISSING-FACT-ID] if fact_id absent."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["list", "review", "submit", "finalize", "accept", "reject", "supersede"],
                                "description": "Stage of the workflow. See per-action requirements in description.",
                            },
                            "fact_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "(action=review) Pending fact IDs to vet.",
                            },
                            "fact_id": {
                                "type": ["integer", "string"],
                                "description": "(action=accept|reject) Integer pending-queue id. (action=supersede) f### YAML id of the NEW/superseding factlet (a bare integer is auto-prefixed with 'f').",
                            },
                            "supersedes_id": {
                                "type": ["integer", "string"],
                                "description": "(action=supersede) REQUIRED: f### YAML id of the factlet being superseded by fact_id (a bare integer is auto-prefixed with 'f').",
                            },
                            "kp_id": {
                                "type": "string",
                                "description": "(action=review|accept|supersede) Target factbook kp_id. Auto-detected from cwd if omitted.",
                            },
                            "panel_override": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "(action=review) Optional explicit reviewer roles.",
                            },
                            "session_type": {
                                "type": "string",
                                "description": "(action=review) Optional domain hint.",
                            },
                            "panel_id": {
                                "type": "string",
                                "description": "(action=submit|finalize) panel_id from review.",
                            },
                            "role": {
                                "type": "string",
                                "description": "(action=submit) reviewer role.",
                            },
                            "scores": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "(action=submit) 0-3 scores parallel to fact_ids.",
                            },
                            "vetoes": {
                                "type": "array",
                                "items": {"type": "object"},
                                "description": "(action=submit) [{index, reason}] vetoes.",
                            },
                            "edited_text": {
                                "type": "string",
                                "description": "(action=accept) Optional edited fact text.",
                            },
                            "override_veto": {
                                "type": "boolean",
                                "description": "(action=accept) Override a veto on a pending fact.",
                            },
                            "reason": {
                                "type": "string",
                                "description": "(action=reject|supersede) Why rejecting/superseding.",
                            },
                            "project_root": {
                                "type": "string",
                                "description": "(action=supersede) Absolute path to the project whose .nora/ factbook is affected. Defaults to the current working directory.",
                            },
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    name="nora_provenance",
                    description=(
                        "Alias of nora_factbook(action='provenance', id=...). Returns the "
                        "PROV-O lineage for a fact: sources, supersession history, confidence "
                        "trajectory, downstream consumers (decision_traces). Prefer "
                        "nora_factbook(action='provenance', id='f###'); this alias is retained "
                        "for discoverability and per the kernora alias-retention pattern."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string",
                                   "description": "Fact ID — 'f765', '765', or integer."},
                            "project": {"type": "string",
                                        "description": "Optional project filter for decision_traces."},
                        },
                        "required": ["id"],
                    },
                ),
                Tool(
                    name="nora_factbook_add",
                    description=(
                        "Appends one new fact to the CANONICAL project YAML factbook "
                        "(.nora/<project>-factbook.yaml) — the same file nora_factbook_view/"
                        "nora_search read. Writes through the f389 chokepoint "
                        "(nora_bridge.yaml_add_fact): atomic write, auto-assigned f### id, "
                        "verify-block validation. Call this when the user says 'add to the "
                        "factbook: <fact>' or 'nora, remember this'. "
                        "REQUIRED: statement must be verifiable and specific (10-2000 chars). "
                        "Auto-detects the project from the current working directory; a "
                        ".nora/ directory must already exist there. Sourceless adds are "
                        "accepted but flagged needs_source=true in the response (a factlet "
                        "with no source is an opinion, not a decision)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "statement": {
                                "type": "string",
                                "description": "The fact text — verifiable, specific, 10-2000 chars.",
                            },
                            "category": {
                                "type": "string",
                                "description": "Fact category (e.g. pattern, decision, gotcha, convention). Default 'pattern'.",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "0.0-1.0. Default 0.7.",
                            },
                            "sources": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Citations (file paths, URLs, note:// refs). Omitting this flags the fact needs_source.",
                            },
                            "project_root": {
                                "type": "string",
                                "description": "Absolute path to the project whose .nora/ factbook receives the fact. Defaults to the current working directory.",
                            },
                        },
                        "required": ["statement"],
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    name="nora_factbook_reverse",
                    description=(
                        "Retires one fact and creates its replacement in the CANONICAL "
                        "project YAML factbook, in one call. Use when a prior decision was "
                        "wrong or has changed: 'that's no longer true, it's actually X now'. "
                        "old_ref may be an explicit f### id, or free text matched against "
                        "existing statements — an ambiguous match (0 or 2+ hits) is REFUSED "
                        "with candidates listed, never guessed. On refusal, re-call with an "
                        "explicit f### id. Writes through the same f389 chokepoint as "
                        "nora_factbook_add (create) + nora_factbook_promote(action='supersede') "
                        "(link) — two YAML writes, not one; if the create succeeds but the "
                        "link fails, the response reports both ids so the supersede can be "
                        "retried manually via nora_factbook_promote."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "old_ref": {
                                "type": "string",
                                "description": "f### id, or a distinctive substring of the fact being replaced.",
                            },
                            "new_statement": {
                                "type": "string",
                                "description": "The replacement fact text (10-2000 chars).",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Why the old fact is being superseded. Default 'superseded'.",
                            },
                            "project_root": {
                                "type": "string",
                                "description": "Absolute path to the project whose .nora/ factbook is affected. Defaults to the current working directory.",
                            },
                        },
                        "required": ["old_ref", "new_statement"],
                        "additionalProperties": False,
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Route tool calls to handlers."""
            try:
                try:
                    conn = db.get_conn()
                    conn.execute(
                        "INSERT INTO nora_metrics (event_type, result_type, keywords) VALUES (?, ?, ?)",
                        ("mcp_call", "tool", name)
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

                if name == "nora_search":
                    result = self._search(arguments["query"])
                elif name == "nora_help":
                    result = self._help()
                elif name == "nora_context_for_task":
                    result = self._context_for_task(
                        arguments["task_description"], arguments.get("project")
                    )
                elif name == "nora_factbook_view":
                    result = await self._factbook_view(
                        name=arguments.get("name"), layer=arguments.get("layer"),
                        kp_id_explicit=arguments.get("kp_id"),
                        include_superseded=bool(arguments.get("include_superseded", False)),
                    )
                elif name == "nora_factbook":
                    result = self._factbook_lifecycle(
                        action=arguments.get("action", "").strip(),
                        **{k: v for k, v in arguments.items() if k != "action"},
                    )
                elif name == "nora_factbook_inject":
                    result = self._factbook_inject(
                        name=arguments.get("name"), layer=arguments.get("layer"),
                        kp_id_explicit=arguments.get("kp_id"),
                        min_compliance_tier=arguments.get("min_compliance_tier", "standard"),
                        require_verified=bool(arguments.get("require_verified", False)),
                    )
                elif name == "nora_factbook_verify":
                    result = self._factbook_verify(
                        name=arguments.get("name"), fact_id=arguments.get("fact_id"),
                    )
                elif name == "nora_generate":
                    result = self._generate(preview=bool(arguments.get("preview", False)))
                elif name == "nora_roi":
                    result = self._roi(
                        model=arguments.get("model"), panel=bool(arguments.get("panel", False)),
                        dry_run=bool(arguments.get("dry_run", False)),
                        directory=arguments.get("directory", "."),
                        external=bool(arguments.get("external", False)),
                    )
                elif name == "nora_claude_memory":
                    result = self._claude_memory_export(
                        max_chars=int(arguments.get("max_chars", 3500)),
                        write=bool(arguments.get("write", False)),
                    )
                elif name == "nora_pe_review":
                    result = self._skill_pe_review(
                        focus=arguments.get("focus"), lenses=arguments.get("lenses"),
                    )
                elif name == "nora_factbook_promote":
                    result = self._factbook_promote(
                        action=arguments.get("action", "").strip(),
                        **{k: v for k, v in arguments.items() if k != "action"},
                    )
                elif name == "nora_provenance":
                    result = self._factbook_provenance(
                        fact_id_raw=arguments.get("id"), project=arguments.get("project"),
                    )
                elif name == "nora_factbook_add":
                    if not arguments.get("statement"):
                        result = "Error: nora_factbook_add requires 'statement'."
                    else:
                        result = self._factbook_add(
                            statement=arguments["statement"],
                            category=arguments.get("category", "pattern"),
                            confidence=float(arguments.get("confidence", 0.7)),
                            sources=arguments.get("sources"),
                            project_root=arguments.get("project_root"),
                        )
                elif name == "nora_factbook_reverse":
                    if not arguments.get("old_ref") or not arguments.get("new_statement"):
                        result = "Error: nora_factbook_reverse requires 'old_ref' and 'new_statement'."
                    else:
                        result = self._factbook_reverse(
                            old_ref=arguments["old_ref"],
                            new_statement=arguments["new_statement"],
                            reason=arguments.get("reason"),
                            project_root=arguments.get("project_root"),
                        )
                else:
                    result = f"Unknown tool: {name}"

                return [TextContent(type="text", text=result)]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {str(e)}")]

    def _connect_db(self) -> sqlite3.Connection:
        """Connect to echo.db with error handling."""
        if not DB_PATH.exists():
            raise FileNotFoundError(
                f"Nora database not found at {DB_PATH}. "
                "Complete a few Claude Code sessions first, or run: python3 db.py"
            )
        conn = db.get_conn()
        conn.row_factory = sqlite3.Row
        return conn


    _INTENT_WEIGHTS = {
        "debug":    {"pattern": 1.0, "decision": 0.5, "bug": 2.0},
        "refactor": {"pattern": 1.5, "decision": 2.0, "bug": 0.5},
        "review":   {"pattern": 1.0, "decision": 1.5, "bug": 1.5},
        "optimize": {"pattern": 2.0, "decision": 1.0, "bug": 0.3},
        "general":  {"pattern": 1.0, "decision": 1.0, "bug": 1.0},
    }

    # ── Search ───────────────────────────────────────────────────────────────

    def _search(self, query: str) -> str:
        """Search across patterns, decisions, bugs, insights via FTS5."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            results = {"patterns": [], "decisions": [], "bugs": [], "insights": []}

            # Try FTS5, fall back to LIKE
            for fts_table, source_table, fields, category in [
                ("fts_patterns", "patterns", ["pattern", "effectiveness", "context"], "patterns"),
                ("fts_decisions", "decisions", ["decision", "rationale"], "decisions"),
                ("fts_bugs", "reported_bugs", ["title", "severity", "fix_code"], "bugs"),
                ("fts_insights", "insights", ["summary", "themes"], "insights"),
            ]:
                try:
                    cursor.execute(
                        f"SELECT {', '.join(fields)} FROM {fts_table} WHERE {fts_table} MATCH ? LIMIT 5",
                        (query,),
                    )
                    for row in cursor.fetchall():
                        results[category].append(dict(zip(fields, row)))
                except sqlite3.OperationalError:
                    # FTS5 not available, fall back to LIKE
                    like_col = fields[0]
                    cursor.execute(
                        f"SELECT {', '.join(fields)} FROM {source_table} WHERE {like_col} LIKE ? LIMIT 5",
                        (f"%{query}%",),
                    )
                    for row in cursor.fetchall():
                        results[category].append(dict(zip(fields, row)))

            conn.close()

            # Format results
            total = sum(len(v) for v in results.values())
            if total == 0:
                return f"No results found for '{query}'. Try a different query."

            output = f"Search Results for '{query}':\n\n"
            for category in ["patterns", "decisions", "bugs", "insights"]:
                if results[category]:
                    output += f"\n{category.upper()} ({len(results[category])}):\n"
                    for item in results[category]:
                        output += f"  - {item}\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Search error: {str(e)}"

    # ── Patterns ─────────────────────────────────────────────────────────────

    def _dashboard(self) -> str:
        return "Dashboard live at http://localhost:2742"

    def _help(self) -> str:
        """Canonical list of all open-core Nora tools — guaranteed complete."""
        import os
        ide = os.environ.get("KERNORA_IDE", "").lower()
        if not ide and os.environ.get("ANTIGRAVITY_AGENT"):
            ide = "antigravity"

        if "antigravity" in ide:
            header = "◎ kernora.ai Antigravity and LLM configured to Gemini 3.1 Pro (High) as it is for the Antigravity IDE default selected"
        else:
            header = "🟢 Nora · Kernora — Open-Core Tools (13)"

        return f"""{header}

━━━ SEARCH & RECALL ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nora search <query>
    Grep for your institutional knowledge. Searches sessions, patterns,
    decisions, and bugs.
    Examples: "nora search auth middleware"
              "nora search the crash we fixed last week"

  nora session <id>
    Drill into a specific session — full transcript, bugs found,
    patterns extracted, quality score. Get the ID from search or stats.
    Example:  "nora session a1b2c3d4"

  nora stats
    Dashboard overview: sessions scanned, patterns found, bugs tracked,
    tokens spent, LLM analysis status. Quick health check.

━━━ CODE SAFETY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nora bugs [status] [severity]
    All known bugs — from git history, session analysis, manual reports.
    Examples: "nora bugs"           (open bugs)
              "nora bugs resolved"  (fixed, with fix code)
              "nora bugs high"      (only high severity)

  nora scope <intent>
    Safety check before large changes. Warns if touching >6 files or
    attempting a big-bang rewrite. Injects relevant patterns from history.

━━━ LEARNING & PATTERNS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nora patterns [project]
    Effective coding patterns learned from your sessions, with
    effectiveness scores.

  nora decisions [project]
    Architectural decisions recorded across your projects — the choice,
    rationale, and alternatives considered.

  nora skills
    Your team playbook — engineering rules + known bug patterns distilled
    from your best sessions.

━━━ INVESTIGATION & RETRO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nora retro [days]
    Engineering retrospective with real git data: velocity, code quality
    signals, bug ratio, hotspot files, wins and risks.
    Examples: "nora retro"     (last 7 days)
              "nora retro 30"  (last month)

━━━ COACH & ONBOARD ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nora coach [days]
    Prompt-quality signals (sessions analyzed, avg quality, repetitions)
    plus tips on improving your prompts.

  nora onboard [dir]
    First-run codebase tour. Identifies language, framework, key files,
    test coverage, and recent git activity.

━━━ INVENTORY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nora inventory [dir]
    Feature inventory — categorizes screens/pages/endpoints as
    SHIP / POLISH / WIRE / BLOCKER / GATE / NEW.

━━━ META ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  nora help
    This list. Also try: "what can nora do" or "nora commands"

━━━ QUICK START ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Just installed?     → nora onboard
  Start of day        → nora stats
  Sprint end          → nora retro
  Before release      → nora inventory
  Learning from work  → nora patterns, nora skills
  Want to improve?    → nora coach
"""

    async def run(self):
        """Start the MCP server on stdio."""
        # mcp SDK 1.26+: stdio_server() takes no server arg;
        # create_initialization_options() replaces create_initialization_state()
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream, write_stream,
                self.server.create_initialization_options()
            )


    def _context_for_task(self, task_description: str, project: str = None) -> str:
        """Smart context retrieval: given a task description, return the most relevant
        patterns, decisions, and gotchas in a single call.

        Uses hybrid BM25 + semantic search (batch-036). Intent weights apply ONCE
        on fused scores — compute_rank() is NOT called here (PE H2 fix: prevents
        double-weighting that previously suppressed pattern scores to ×0.5 on debug queries).
        """
        try:
            conn = self._connect_db()

            # v0.1.3-A: mtime-staleness check — reindex YAML if newer than DB.
            # NO new search legs added; existing 4 hybrid_search calls already
            # cover patterns/decisions/bugs once YAML facts land in those tables.
            try:
                from nora_context import _check_and_reindex_yaml_if_stale as _yaml_check
                _project_root = getattr(self, '_project_root', None) or \
                    str(getattr(self, '_cwd', None) or '')
                if _project_root:
                    _yaml_check(conn, _project_root)
            except Exception:
                pass  # Never let staleness check break search

            intent = self._detect_task_intent(task_description)
            weights = self._INTENT_WEIGHTS.get(intent, self._INTENT_WEIGHTS["general"])

            from nora_context import extract_keywords, hybrid_search
            from db import get_ab_group as _get_ab_group
            keywords = extract_keywords(task_description)
            _session_id_ab = getattr(self, '_current_session_id', '') or ''
            _ab_group = _get_ab_group(_session_id_ab)

            # Hybrid search per type: BM25 + semantic combined.
            # Semantic fires even with empty keywords (semantic is the only path then).
            # A/B group controls semantic path (batch-040).
            patterns_h = hybrid_search(conn, "fts_patterns", "patterns",
                                       keywords, task_description, project, 5,
                                       ab_group=_ab_group)
            decisions_h = hybrid_search(conn, "fts_decisions", "decisions",
                                        keywords, task_description, project, 3,
                                        ab_group=_ab_group)
            bugs_h = hybrid_search(conn, "fts_bugs", "reported_bugs",
                                   keywords, task_description, project, 3,
                                   ab_group=_ab_group)

            # Tier 1 implicit feedback: record every retrieval event (batch-044)
            _session_id = getattr(self, '_current_session_id', '') or ''
            try:
                from db import record_retrieval as _rec
                _type_pairs = [
                    (patterns_h, 'pattern'), (decisions_h, 'decision'), (bugs_h, 'bug')
                ]
                for _hits, _ftype in _type_pairs:
                    _re_q = self._re_queried_check(conn, _session_id, _ftype)
                    for _rank, _r in enumerate(_hits):
                        _fid = _r.get('data', {}).get('id')
                        if _fid is not None:
                            _row_id = _rec(conn, _session_id, _fid, _ftype,
                                           project, _r.get('fused_score', 0.0), _rank)
                            if _re_q and _row_id:
                                try:
                                    conn.execute(
                                        "UPDATE context_retrievals SET re_queried=1 WHERE id=?",
                                        (_row_id,)
                                    )
                                    conn.commit()
                                except Exception:
                                    pass
            except Exception:
                pass  # citation write must never block context retrieval

            # Apply intent weights ONCE on fused_score (PE H2: no compute_rank double-weight)
            all_results = []
            for r in patterns_h:
                all_results.append(("pattern", r['data'], r['fused_score'] * weights["pattern"]))
            for r in decisions_h:
                all_results.append(("decision", r['data'], r['fused_score'] * weights["decision"]))
            for r in bugs_h:
                all_results.append(("bug", r['data'], r['fused_score'] * weights["bug"]))

            # Fallback: if hybrid returns nothing (no embeddings, no keywords), return hint
            if not any(patterns_h or decisions_h or bugs_h):
                conn.close()
                return f"No relevant intelligence found for: {task_description}"

            all_results.sort(key=lambda x: x[2], reverse=True)
            top = all_results[:8]

            lines = [f"Nora Context for: {task_description[:80]}", ""]
            for item_type, item, score in top:
                if item_type == "pattern":
                    conf = item.get("confidence", 0) or 0
                    lines.append(f"[Pattern] {item.get('pattern', '?')} (confidence: {conf:.0%})")
                    if item.get("code_example"):
                        lines.append(f"  Example: {item['code_example'][:120]}")
                elif item_type == "decision":
                    lines.append(f"[Decision] {item.get('decision', '?')}")
                    if item.get("rationale"):
                        lines.append(f"  Why: {item['rationale'][:120]}")
                elif item_type == "bug":
                    lines.append(f"[Bug] [{item.get('severity', '?')}] {item.get('title', '?')}")
                    if item.get("fix_code"):
                        lines.append(f"  Fix: {item['fix_code'][:120]}")
                lines.append("")

            conn.close()
            return "\n".join(lines)

        except Exception as e:
            return f"Context retrieval error: {str(e)}"

    def _detect_task_intent(self, task_description: str) -> str:
        """Detect task intent from description. Returns: debug|refactor|review|optimize|general."""
        desc = task_description.lower()
        intent_keywords = {
            "debug":    ["bug", "fix", "error", "crash", "broken", "failing",
                         "traceback", "exception", "debug"],
            "refactor": ["refactor", "restructure", "reorganize", "clean up",
                         "simplify", "extract", "rename", "migrate"],
            "review":   ["review", "audit", "check", "verify", "validate",
                         "inspect", "assess"],
            "optimize": ["optimize", "performance", "speed", "slow", "memory",
                         "cache", "efficient"],
        }
        for intent, keywords in intent_keywords.items():
            if any(kw in desc for kw in keywords):
                return intent
        return "general"

    def _factbook_promote(self, action: str, **kwargs) -> str:
        """Action router for nora_factbook_promote.
        Routes to existing impl methods; adds kp_id threading + auto-promote
        verdict reporting per PE B1 + H4 + H5 fixes.
        """
        if action == "list":
            # Maps to existing _capture_pending — list pending facts
            return self._capture_pending(batch_id=kwargs.get("batch_id"))
        if action == "review":
            # Start a panel with panel_kind="promote" + kp_id threading
            kp_id = kwargs.get("kp_id")
            if not kp_id:
                # Try to infer from current project (mirrors _factbook_add fallback)
                project = self._infer_project_from_cwd()
                if project:
                    kp_id, _ = self._get_default_factbook_for_project(project)
            if not kp_id:
                return json.dumps({
                    "error": "kp_id_required",
                    "hint": "Pass kp_id explicitly or run from a project directory with a default factbook.",
                })
            return self._pe_review_start(
                fact_ids=kwargs.get("fact_ids", []),
                panel_override=kwargs.get("panel_override"),
                session_type=kwargs.get("session_type"),
                panel_kind="promote",
                kp_id=kp_id,
            )
        if action == "submit":
            return self._pe_review_submit(
                panel_id=kwargs["panel_id"],
                role=kwargs["role"],
                scores=kwargs.get("scores", []),
                vetoes=kwargs.get("vetoes"),
            )
        if action == "finalize":
            # Auto-promote happens INSIDE _pe_review_finalize when
            # panel_kind == "promote" (from the start event in JSONL).
            return self._pe_review_finalize(panel_id=kwargs["panel_id"])
        if action == "accept":
            # Direct single-fact promote (skips panel review).
            kp_id = kwargs.get("kp_id")
            if not kp_id:
                project = self._infer_project_from_cwd()
                if project:
                    kp_id, _ = self._get_default_factbook_for_project(project)
            if not kp_id:
                return json.dumps({"error": "kp_id_required"})
            res = self._promote_pending_to_factbook(
                pending_id=int(kwargs["fact_id"]),
                kp_id=kp_id,
                edited_text=kwargs.get("edited_text"),
                override_veto=bool(kwargs.get("override_veto", False)),
                created_by="user_accept",
            )
            return json.dumps(res, indent=2)
        if action == "reject":
            return self._capture_reject(
                pending_id=int(kwargs["fact_id"]),
                reason=kwargs.get("reason", ""),
            )
        if action == "supersede":
            # §17.4 P-04 + Stage-3: supersede action with supersedes_id + reason.
            return self._factbook_supersede(
                fact_id=kwargs.get("fact_id"),
                supersedes_id=kwargs.get("supersedes_id"),
                kp_id=kwargs.get("kp_id"),
                reason=kwargs.get("reason"),
                project_root=kwargs.get("project_root"),
            )
        return (f"Error: nora_factbook_promote requires action='list' | "
                f"'review' | 'submit' | 'finalize' | 'accept' | 'reject' | 'supersede'; "
                f"got {action!r}.")

    def _skill_pe_review(self, focus: str | None = None,
                         lenses: list | None = None) -> str:
        """Multi-lens Principal Engineer review.

        Builds the prompt by composing PE_REVIEW_LENSES (single source of
        truth, also used by nora_context.py's hook teaser via import).
        Customer's IDE LLM runs each requested lens (lf204: zero internal
        LLM calls).
        """
        all_lens_keys = list(PE_REVIEW_LENSES.keys())
        lenses = lenses or all_lens_keys
        invalid = [L for L in lenses if L not in PE_REVIEW_LENSES]
        if invalid:
            return (f"Error: unknown lens(es) {invalid}. Valid lenses: "
                    f"{all_lens_keys}. "
                    f"Example: nora_pe_review(lenses=['ai_usability','mcp_agent']).")

        sections = ["🟢 Nora · Kernora: Multi-Lens PE Review", "",
                    "Run a Principal Engineer review using the lens(es) below. "
                    "Each lens has a distinct evaluation rubric — produce a "
                    "separate findings block per lens (BLOCKER / HIGH / MEDIUM "
                    "/ LOW), then a unified verdict at the end.", ""]

        for i, key in enumerate(lenses, 1):
            lens = PE_REVIEW_LENSES[key]
            sections.append(f"─── Lens {i}: {lens['title']} ───")
            sections.append(lens["rubric"])
            sections.append("")

        sections.append("─── PROCESS ────────────────────────────────────────────")
        sections.append(PE_REVIEW_PROCESS)

        if focus:
            sections.append(f"\nFOCUS AREA: {focus}")
        else:
            sections.append("\nScope: full project diff if a recent branch / commit is "
                            "the trigger; otherwise full codebase. Start with Discovery.")

        if lenses != all_lens_keys:
            sections.append(f"\nLENSES SELECTED: {', '.join(lenses)} "
                            f"({len(lenses)}/{len(all_lens_keys)})")

        return "\n".join(sections)

    def _roi(
        self,
        model: str | None = None,
        panel: bool = False,
        dry_run: bool = False,
        directory: str = ".",
        external: bool = False,
        in_session: bool | None = None,
        format: str | None = None,
    ) -> str:
        """MCP handler for `nora roi`.

        Default behaviour (#60): return the assembled prompt to the caller's
        session LLM for in-session grading. No LiteLLM, no external API, no
        rate limit. The session model (Claude Code's active model, Cursor's
        active model, Kiro's, etc.) reads the prompt and produces the JSON
        grade inline — the correct UX for MCP invocation.

        panel=True OR external=True OR explicit model= → use LiteLLM
        (external API call path). Used for multi-vendor benchmark runs
        that genuinely need a different vendor than the current session.

        dry_run=True (#59): returns the full prompt body without LLM call.

        format: 'human' (default) — slim render template for customer-facing output
                'json'  — full rubric back-compat (legacy JSON schema)
                'both'  — human render + collapsed <details> JSON request
        """
        import os
        from pathlib import Path as _Path

        # LD#16: backward-compat stderr warning when caller didn't pass format
        _format_explicit = format is not None
        if not _format_explicit:
            print(
                "[Nora] format defaulted to 'human'; pass format='json' for legacy shape "
                "(deprecation in 60 days — removed 2026-06-25)",
                file=sys.stderr,
            )
            format = "human"

        # Validate format
        VALID_FORMATS = ("human", "json", "both")
        if format not in VALID_FORMATS:
            return f"[Nora] format must be one of: human, json, both (got: '{format}')"

        try:
            for p in ("/Users/mihirchoudhary/code/kernora",
                      os.path.expanduser("~/.kernora/app")):
                if os.path.isdir(p) and p not in sys.path:
                    sys.path.insert(0, p)
            import kernora_roi as kr
        except ImportError as e:
            return f"[Nora] kernora_roi unavailable: {e}"

        project_root = os.path.abspath(os.path.expanduser(directory))
        if not os.path.isdir(project_root):
            return f"[Nora] directory not found: {project_root}"

        # Decide in-session vs external. Default = in-session (no LiteLLM).
        use_in_session = (
            in_session if in_session is not None
            else not (panel or external or model)
        )

        if panel:
            flagships = {
                "anthropic": "anthropic/claude-opus-4-7",
                "openai":    "openai/gpt-4.1",
                "google":    "gemini/gemini-2.5-pro",
                "xai":       "xai/grok-4-1-fast-reasoning",
            }
            models = []
            for vendor, flagship in flagships.items():
                env_key, _ = kr.VENDOR_MAP.get(vendor, ("", []))
                if env_key and os.environ.get(env_key):
                    models.append(flagship)
            if not models:
                return "[Nora] no vendor API keys detected in environment."
        else:
            models = [kr.detect_active_model(model)]

        # ── In-session path (default) ────────────────────────────────────
        if use_in_session and not panel:
            m = models[0]

            # format=json → back-compat: return the full rubric prompt (LD#12)
            if format == "json":
                try:
                    r = kr.grade(m, project_root=project_root, in_session=True)
                except Exception as e:
                    return f"[Nora] prompt assembly failed: {type(e).__name__}: {str(e)[:200]}"
                prompt_body = r.get("prompt", "(prompt unavailable)")
                if dry_run:
                    return prompt_body
                return (
                    f"# Nora ROI — `{os.path.basename(project_root)}` (in-session)\n\n"
                    "**Grading mode: in-session / format=json.** Read the prompt, "
                    "produce the structured JSON grade per the schema.\n\n"
                    f"_Prompt version: roi@v0.1.2 · length: {len(prompt_body):,} chars · "
                    "no external API call was made._\n\n"
                    "---\n\n"
                    f"{prompt_body}\n\n"
                    "---\n\n"
                    "_Output format reminder: respond with ONE JSON object matching "
                    "the schema in the prompt. All values, confidences, and line "
                    "items should be grounded in the evidence above._"
                )

            # format=human or format=both → slim render-template path (LD#1, LD#3)
            project_name = os.path.basename(project_root)
            project_lower = project_name.lower()
            _root_path = _Path(project_root)

            # Pre-compute competitive anchor (LD#4)
            try:
                competitive_anchor_block = kr._collect_competitive_anchor()
            except Exception as e:
                competitive_anchor_block = f"(competitive anchor unavailable: {e})"

            # Pre-compute known issues in Python (LD#13)
            try:
                known_issues = kr._collect_known_issues(project_lower, _root_path)
            except Exception as e:
                known_issues = []

            # Build known_issues block text
            if known_issues:
                ki_lines = []
                for ki in known_issues:
                    ki_lines.append(
                        f"  - id={ki.get('id','?')} severity={ki.get('severity','?')}: "
                        f"{ki.get('message','?')} | fix: {ki.get('fix_hint','?')}"
                    )
                known_issues_block = "\n".join(ki_lines)
            else:
                known_issues_block = "(none detected)"

            # Gather evidence (reuse existing kr helpers for facts + steering + commits)
            try:
                facts_rows, facts_block = kr._collect_facts(project_lower, topn=10)
            except Exception:
                facts_block = "(facts unavailable)"
            try:
                steering_block = kr._collect_steering_block()
            except Exception:
                steering_block = "(steering unavailable)"
            try:
                commits = kr._recent_commits(_root_path, n=5)
                commits_block = "\n".join(f"  {c}" for c in commits) or "(no commits)"
            except Exception:
                commits_block = "(commits unavailable)"
            try:
                signal_quality = kr._collect_signal_quality(project_lower)
            except Exception:
                signal_quality = "(signal quality unavailable)"
            try:
                claude_verdict, claude_signals = kr._detect_claude_md_provenance(_root_path)
            except Exception:
                claude_verdict, claude_signals = "unknown", ""
            try:
                kp_id, vhash, n_facts = kr._collect_factbook_meta(project_lower)
                # H3 fix (LAUNCH-LOOP L3 walk1, 2026-07-19): pass project, not
                # kp_id — _count_sessions_for_factbook now delegates to
                # db.canonical_session_count(conn, project), the same
                # resolver dashboard/nora_session_start.py use, instead of
                # the broken kp_id-name-guess that silently returned 0.
                session_count = kr._count_sessions_for_factbook(project_lower)
                factbook_age_days = kr._factbook_age_days(kp_id)
            except Exception:
                kp_id = vhash = ""
                n_facts = None
                session_count = factbook_age_days = 0
            # AUDIT-FIX-BRIEF Fix 2 (quality-loop 2026-07-17, §4/F3): n_facts
            # used to be silently 0 on any exception here AND, separately,
            # kr._collect_factbook_meta used to read a stale one-time JSON
            # snapshot (facts_total=9 from 2026-05-30, never refreshed) — the
            # combination is the audit's "ROI 'Facts in DB: 9'" finding.
            # _collect_factbook_meta now queries the live canonical count and
            # returns None (never a fabricated number) on failure; render
            # that honestly instead of interpolating None/0 into the
            # LLM-facing grading prompt (a bare 0 would read as "empty
            # factbook" — a materially false claim, not a neutral default).
            n_facts_label = str(n_facts) if n_facts is not None else (
                "unavailable (count query failed — see server log)"
            )

            # Build the SLIM in-session prompt (LD#1, LD#6, target ≤5K chars)
            slim_prompt = f"""# ROI grading task — {project_name}

You are grading whether Nora is worth $50/mo for THIS project.
Output the rendered markdown ONLY (no JSON, no preamble, no
explanation outside the rendered content). Render the structure
inside <render-template>...</render-template> exactly — drop the
fence tags, fill the {{placeholders}} with your computed values.

## Evidence

Project: {project_name} | Stack: {kr._detect_stack(_root_path)} | Commit: {kr._git_head(_root_path)}
CLAUDE.md provenance: {claude_verdict} ({claude_signals[:120] if claude_signals else 'n/a'})
Sessions recorded: {session_count} (total sessions for this project — a DIFFERENT count from any "sessions grounded" figure shown elsewhere, which counts only sessions where a factlet citation was accepted) | Factbook age: {factbook_age_days}d | Facts in DB: {n_facts_label}
Privacy: zero-network invariant enforced by kernora_network_audit

Top facts (DB ranker):
{facts_block or "(none)"}

Steering files emitted:
{chr(10).join((steering_block or "(none)").splitlines()[:5])}

Recent commits:
{commits_block}

Signal quality: {signal_quality[:150] if len(signal_quality) > 150 else signal_quality}

## Pricing context (versioned, last_verified-checked — do NOT use as adversarial)

{competitive_anchor_block}

NOTE: Nora COMPLEMENTS Claude Code, Cursor, Copilot, Kiro, and
Claude.ai web — it is not a substitute. Render the "How Nora plugs in"
section, NOT a "vs alternatives" section.

## Known issues (Python-detected, do NOT redetect)

{known_issues_block}

## Grading rules — confidence-weighted (operator-rev 2026-04-27)

For each line item, assign:
  - dollars_per_year (raw)
  - confidence (0.0-1.0)
The WEIGHTED contribution = dollars × confidence (expected value).

VERDICT decision tree (uses WEIGHTED Day-1, NOT raw):
- weighted_day_1 >= $600/yr → YES, verdict_verb="pay $50/mo"
- (weighted_day_1 + 0.5 × weighted_day_30_plus) >= $600 → MAYBE,
  verdict_verb="wait — Day-1 below ask, see Day-30+ trajectory"
- Otherwise → NO, verdict_verb="skip"

LINE ITEMS:
- Every item MUST cite: fact_id / steering file / commit /
  catalog item / "always-on feature"
- Day-1 items: PE review, privacy audit, CLAUDE.md gen, hotspot
  warnings, drift detection, function anchors, +nora hook,
  steering emit
- Day-30+ items: corpus value, injection precision metrics,
  effectiveness ranking
- Each row MUST include `Computation` column with formula
- Items based on assumptions (not directly observable) prefix
  the computation with `{{ASSUMED}}` token

AGGREGATION INVARIANT:
- Per-row Weighted $ = Raw $ × Conf
- Day-1 weighted subtotal = Σ(Day-1 line items' Weighted $)
- Day-30+ weighted subtotal = Σ(Day-30+ line items' Weighted $)
- Verdict gate uses WEIGHTED Day-1 ≥ ask
- ALSO show raw subtotals for transparency

CITATIONS:
- Cite <= 5 fact IDs
- Each cited fact gets: {{fact_id}} — {{one-line summary}} (re-query: nora_search("{{topic}}"))

OUTPUT BUDGET: <=6,500 chars.

## Render template

<render-template>
# 💰 ROI for {project_name} — **{{VERDICT}}** · {{VERDICT_VERB}}

**Day-1 confidence-weighted value: ${{weighted_day_1}}/yr** ({{pct_of_ask}}% of the $600/yr ask).
Raw Day-1: ${{raw_day_1}}/yr. Overall confidence: {{overall_conf}}%.

## How Nora plugs in (we enable, not replace)

| Your AI tool | What Nora adds | How it shows up |
|---|---|---|
| **Claude Code** | MCP tools (nora_search, nora_factbook_view, nora_pe_review, ...) + +nora hook context surfacing | {{one observed example from this session}} |
| **Cursor / Copilot / Kiro** | Steering files Nora emits + living-factbook v1.1 auto-refresh | {{N}} files / ~{{KB}}KB injected at session-start |
| **Claude.ai web** | Memory bridge — exports project facts as MEMORY.md sibling | `kernora memory export` produces portable JSON |

Nora is the **factbook + rituals layer** under your AI tool of choice. None of these tools maintain a project-specific, version-pinned, citation-traceable factbook on their own. Nora does, and feeds it back in.

## Where the value comes from (Day-1, no history needed)

All numbers computed; assumptions marked `{{ASSUMED}}` with rationale in notes section.

| # | Source | Raw $/yr | Conf | Weighted $/yr | Computation |
|---|---|---:|---:|---:|---|
| 1 | {{label}} | ${{raw}} | {{c}}% | **${{weighted}}** | `{{formula}}` |
| | **Day-1 subtotal** | **${{raw_d1}}** | — | **${{weighted_d1}}** | |

## Future upside (after ~30 sessions)

| # | Source | Raw $/yr | Conf | Weighted $/yr | Computation |
|---|---|---:|---:|---:|---|
| {{n}} | {{label}} | ${{raw}} | {{c}}% | **${{weighted}}** | `{{formula}}` |
| | **Day-30+ subtotal** | **${{raw_d30}}** | — | **${{weighted_d30}}** | |

## How the numbers add up (math, not vibes)

- `Sum(raw $)` = ${{raw_total}}/yr
- `Sum(raw × conf)` = **${{weighted_total}}/yr** ← honest expected-value
- `Day-1 weighted (${{weighted_d1}}) {{≥|<}} Annualized ask ($600)` → verdict = {{VERDICT}}
- Overall confidence = ${{weighted_total}} / ${{raw_total}} = **{{overall_conf}}%**

## Concrete tasks I priced (sample)

| Task | Without Nora | With Nora | Savings |
|---|---|---|---|
| {{commit msg}} | {{tokens, time}} | {{tokens, time}} | **{{Δ}}** |

Token-rate assumption: Claude Sonnet $3/M input, $15/M output, 80/20 split.

## Known issue
{{render this section ONLY if known_issues block above is non-empty.
 If empty, omit the heading and table entirely.}}

| Issue | Severity | Fix path |
|---|---|---|
| {{issue.message}} | {{issue.severity}} | {{issue.fix_hint}} |

## What would change the verdict

- Push to YES with high confidence (>70%): {{one specific action}}
- Push to NO: {{one specific failure mode}}

## Notes on assumptions (transparency)

`{{ASSUMED}}` items in the table above are educated guesses, not measured data.
List each here with rationale + sensitivity (e.g. "for HIPAA projects 5-10× higher; for personal $0").

---

**Citations** — {{N}} facts grounded the grade
- {{fact_id}} — {{one-line summary}} (re-query: `nora_search("{{topic}}")`)

**Save**: `kernora roi --save docs/roi/$(date +%F).md`
**Compare**: http://localhost:2742/roi-vs-native
</render-template>"""

            if dry_run:
                # Explicit ask for the raw grading prompt (used by the
                # caller's own session LLM, or by kernora_roi's callers that
                # already know they want to grade). Keep verbatim.
                return slim_prompt

            if format == "both":
                return (
                    slim_prompt
                    + "\n\n---\n\n"
                    "After rendering the markdown above, also output the full "
                    "structured JSON grade in a collapsed details block:\n\n"
                    "<details><summary>JSON grade (machine-readable)</summary>\n\n"
                    "```json\n"
                    "{your full JSON grade here per roi@v0.1 schema}\n"
                    "```\n\n"
                    "</details>"
                )

            # format=human (default), dry_run=False — M1 fix (LAUNCH-LOOP L3
            # walk1/walk2 2026-07-19): this used to hand back the ~6.5-8K
            # char fill-me-in grading TEMPLATE as the primary payload for
            # any caller that doesn't happen to be an LLM able to render
            # <render-template>...</render-template> itself (e.g. a script
            # or a non-compliant MCP client). Nora cannot compute a
            # confidence-weighted dollar verdict without an LLM reasoning
            # pass — so return the honest, already-computed numeric
            # evidence directly (no fill-me-in blanks) plus a pointer to
            # get the full LLM-graded verdict, instead of dumping the
            # template as if it were an answer.
            top_fact_lines = [
                ln for ln in (facts_block or "").splitlines() if ln.strip()
            ][:5]
            summary_lines = [
                f"# Nora ROI — `{project_name}` (evidence summary, no LLM call)",
                "",
                f"_Full confidence-weighted $ grade requires an LLM reasoning pass "
                f"over this evidence — not run by default. To get it: "
                f"`nora_roi(dry_run=True)` and have your session model render the "
                f"result, or run `kernora roi` at the shell._",
                "",
                "## What's known numerically",
                "",
                f"- Sessions recorded: **{session_count}**",
                f"- Facts in factbook: **{n_facts_label}**",
                f"- Factbook age: **{factbook_age_days}d**",
                f"- Known issues detected: **{len(known_issues)}**"
                + (f" ({known_issues_block.splitlines()[0]}...)" if known_issues else ""),
                f"- CLAUDE.md provenance: {claude_verdict}",
                f"- Signal quality: {signal_quality[:150] if signal_quality else '(unavailable)'}",
                "",
                "## Top grounded facts",
                "",
                *(top_fact_lines or ["(none)"]),
                "",
                "## Recent commits",
                "",
                commits_block,
                "",
                "---",
                "",
                "**To run the full grade:** `nora_roi(dry_run=True)` (assembles the "
                "grading prompt for your session model) or `kernora roi` at the "
                "shell (LiteLLM external grade).",
            ]
            return "\n".join(summary_lines)

        # ── External / panel path (LiteLLM) ──────────────────────────────
        out_lines = [f"# Nora ROI — `{os.path.basename(project_root)}`", ""]
        reports = []
        for m in models:
            try:
                r = kr.grade(m, project_root=project_root, dry_run=dry_run)
            except Exception as e:
                out_lines.append(f"## {m} — ERROR: {type(e).__name__}: {str(e)[:200]}")
                out_lines.append("")
                continue
            if dry_run:
                prompt_body = r.get("prompt", "")
                out_lines.append(f"## {m} — [dry-run] prompt body ({len(prompt_body):,} chars)")
                out_lines.append("")
                out_lines.append("```")
                out_lines.append(prompt_body)
                out_lines.append("```")
                out_lines.append("")
                continue
            kr.save_report(r)
            reports.append(r)
            # panel / external: use render_markdown (existing path) per LD#7
            if format in ("human", "both"):
                out_lines.append(kr.render_markdown(r))
                if format == "both":
                    out_lines.append(
                        "<details><summary>JSON grade</summary>\n\n"
                        f"```json\n{json.dumps(r, indent=2, default=str)}\n```\n\n"
                        "</details>"
                    )
            else:
                verdict = (r.get("verdict") or "?").upper()
                saving = r.get("annualized_savings_usd", 0) or 0
                conf = (r.get("confidence_overall", 0) or 0) * 100
                out_lines.append(f"## {m}")
                out_lines.append(f"- **Verdict:** {verdict}")
                out_lines.append(f"- Annual savings: ${saving:,.0f}")
                out_lines.append(f"- Confidence: {conf:.0f}%")
                gaps = r.get("gaps") or []
                if gaps:
                    out_lines.append(f"- Gaps: {'; '.join(str(g) for g in gaps[:3])}")
                cited = r.get("cited_facts") or []
                if cited:
                    out_lines.append(f"- Cited facts: {', '.join(str(x) for x in cited[:5])}")
                prose = r.get("honest_prose") or ""
                if prose:
                    out_lines.append(f"- Verdict prose: {prose[:300]}")
            out_lines.append("")

        if panel and len(reports) > 1:
            yes = sum(1 for r in reports if r.get("verdict") == "yes")
            maybe = sum(1 for r in reports if r.get("verdict") == "maybe")
            no = sum(1 for r in reports if r.get("verdict") == "no")
            mean_s = sum(r.get("annualized_savings_usd", 0) or 0 for r in reports) / len(reports)
            out_lines.insert(1, f"_{len(reports)} models · consensus: {yes} yes / {maybe} maybe / {no} no · mean ${mean_s:,.0f}/yr_")
            out_lines.insert(2, "")

        return "\n".join(out_lines)

    def _claude_memory_export(self, max_chars: int = 3500,
                              write: bool = False) -> str:
        """Build the Claude Memory block via memory_bridge (single source of
        truth, P2 redesign 2026-04-25). Reads from .nora/<factbook>.yaml
        when present (Lite-friendly) and/or from echo.db (Companion).

        write=True writes the block into Anthropic's MEMORY.md between
        nora:memory:auto-start markers, preserving user content outside.
        Default write=False keeps the legacy copy-paste UX.
        """
        try:
            from memory_bridge import (
                build_memory_block as _build,
                find_factbook_for_cwd as _find_fb,
                write_to_sibling_entry as _write_sib,
                ensure_indexed_in_memory_md as _idx_md,
                DEFAULT_ENTRY_NAME as _DEFAULT_ENTRY,
            )
        except ImportError as e:
            return f"memory_bridge module unavailable: {e}"

        # Lite-friendly: prefer .nora/<factbook>.yaml in cwd
        factbook_path = _find_fb()
        # Companion fallback: echo.db
        try:
            db_conn = self._connect_db()
        except Exception:
            db_conn = None

        try:
            res = _build(factbook_path=factbook_path, db_conn=db_conn,
                         max_chars=max_chars,
                         min_confidence=_load_bridge_threshold())
        finally:
            if db_conn is not None:
                try:
                    db_conn.close()
                except Exception:
                    pass

        output = res["text"]
        chars = res["chars"]
        source = res["source"]

        if write:
            project_root = Path.cwd()
            # BATCH-008 (2026-04-26): write to sibling file (not MEMORY.md
            # itself — Anthropic's MEMORY.md is an index file). Also ensure
            # the sibling is indexed in MEMORY.md so Claude discovers it.
            sib = _write_sib(text=output, project_root=project_root)
            idx = _idx_md(_DEFAULT_ENTRY, project_root) if sib["ok"] else None
            if sib["ok"] and idx and idx["ok"]:
                return (
                    f"🟢 Nora · Kernora: Memory bridge synced "
                    f"({sib['sibling_action']} sibling, {idx['index_action']} index)\n\n"
                    f"Sibling: {sib['sibling_path']}\n"
                    f"Index format detected: {idx['format']}\n"
                    f"Source: {source} · {chars} chars · {res['n_sections']} sections\n\n"
                    f"---\n\n{output}\n\n---\n"
                )
            err_reason = (sib.get("reason") or
                          (idx.get("reason") if idx else "unknown"))
            return (
                f"⚠️ Memory export built but sync had issues: {err_reason}\n"
                f"Sibling: {sib.get('sibling_path', 'n/a')}\n"
                f"Source: {source} · {chars} chars\n\n"
                f"---\n\n{output}\n\n---\n"
            )
        return (
            f"🟢 Nora · Kernora: Claude Memory Export\n\n"
            f"Copy the block below and paste it into a Claude conversation with:\n"
            f"\"Remember this about my engineering work\"\n\n"
            f"Source: {source} · {res['n_sections']} sections · pass write=True to write directly to MEMORY.md\n\n"
            f"---\n\n{output}\n\n---\n\n"
            f"({chars} chars — Claude Memory supports up to ~4000 chars)"
        )

    async def _factbook_lifecycle(self, action: str, **kwargs):
        """Action router for nora_factbook(action=create|update|delete|commit|provenance).
        Each action routes to its existing impl method — single source of truth.

        schema_version: "0.5.0" is prepended to all responses (§10.6).
        source_citation fields are available via nora_factbook_view for factlet rows.
        """
        _schema_prefix = f"schema_version: {_MCP_SCHEMA_VERSION}\n"
        if action == "create":
            return self._factbook_create(
                name=kwargs.get("name", ""),
                title=kwargs.get("title"),
                scope=kwargs.get("scope", "personal"),
            )
        if action == "update":
            return self._factbook_update(
                fact_id=int(kwargs["fact_id"]),
                fields=kwargs.get("fields", {}) or {},
                reason=kwargs.get("reason", "user-edit"),
            )
        if action == "delete":
            return await self._factbook_delete(
                name=kwargs.get("name"),
                fact_id=kwargs.get("fact_id"),
            )
        if action == "commit":
            return await self._factbook_commit(
                name=kwargs.get("name"),
                push=bool(kwargs.get("push", False)),
                remote=kwargs.get("remote", "origin"),
                branch=kwargs.get("branch"),
            )
        if action == "provenance":
            # Per founder Q2 (2026-05-11, kernora:CLAUDE-CODE-EVALUATION §12):
            # folded provenance lookup into nora_factbook + alias nora_provenance.
            # Accepts id as '', '765', or integer 765.
            return self._factbook_provenance(
                fact_id_raw=kwargs.get("id") or kwargs.get("fact_id"),
                project=kwargs.get("project"),
            )
        return (f"Error: nora_factbook requires action='create' | 'update' | "
                f"'delete' | 'commit' | 'provenance'; got {action!r}.")

    async def _factbook_create(self, name: str, description: str, scope: str) -> str:
        """Handler for nora_factbook_create."""
        try:
            from db import factbook_create
            from factbook_git import write_and_commit_async, ensure_git_repo

            ensure_git_repo()
            result = factbook_create(name=name, description=description, scope=scope)
            kp_id = result["kp_id"]

            # Async git commit (PE review B3 fix)
            conn = self._connect_db()
            try:
                commit = await write_and_commit_async(
                    conn, kp_id, "create", {"name": name, "scope": scope}
                )
            finally:
                conn.close()

            return (
                f"Factbook created: \"{name}\"\n"
                f"  ID: {kp_id}  (use this in subsequent calls)\n"
                f"  Scope: {scope}\n"
                f"{self._format_kp_git_note(commit)}\n"
                f"Add facts with: nora_factbook_add(name=\"{kp_id}\", fact=\"...\")"
            )
        except Exception as e:
            return f"Error creating factbook: {e}"

    def _factbook_update(self, fact_id: int, fields: dict, reason: str) -> str:
        """Handler for nora_factbook_update — partial whitelist update + JSONL audit.

        Thin wrapper over db.factbook_update_fact. Sole MCP entrypoint for
        editing a fact (the legacy nora_factbook_edit tool was deleted
        2026-04-25 as a true duplicate).
        """
        try:
            from db import factbook_update_fact
            res = factbook_update_fact(
                fact_id=fact_id,
                fields=fields or {},
                reason=reason or "",
                source="mcp",
            )
            if not res.get("ok"):
                return f"Update failed: {res.get('reason', 'unknown')}"
            applied = ", ".join(f"{k}={v!r}" for k, v in (fields or {}).items())
            return (
                f"Updated fact {fact_id}: {applied}\n"
                f"  Audit logged to factbook_audit.jsonl\n"
                f"  Reason: {reason or '(none)'}"
            )
        except Exception as e:
            return f"Error updating fact {fact_id}: {e}"

    async def _factbook_delete(self, name: str | None, fact_id: int | None) -> str:
        """Handler for nora_factbook_delete. Auto-detects default if name omitted."""
        try:
            from db import factbook_delete
            from factbook_git import write_and_commit_async

            # ─── Smart name resolution: auto-detect project if name not provided ───
            if not name:
                project = self._infer_project_from_cwd()
                if project:
                    name, _ = self._get_default_factbook_for_project(project)
                else:
                    return "No factbook name provided and could not infer project."

            kp_id = self._resolve_factbook_name(name)
            if kp_id is None:
                return f"Factbook not found: {name!r}"

            result = factbook_delete(kp_id=kp_id, fact_id=fact_id)

            conn = self._connect_db()
            try:
                if result["archived_factbook"]:
                    # File already moved to .archive/ by factbook_delete
                    commit_note = "Git: archived (file moved to .archive/)"
                else:
                    commit = await write_and_commit_async(
                        conn, kp_id, "delete-fact", {"fact_id": fact_id}
                    )
                    commit_note = self._format_kp_git_note(commit, indent="").strip()
            finally:
                conn.close()

            if result["archived_factbook"]:
                return (
                    f"Factbook \"{name}\" archived.\n"
                    f"  {result['archived_facts']} facts preserved with archived=1\n"
                    f"  {commit_note}"
                )
            else:
                return (
                    f"Fact {fact_id} archived from \"{name}\".\n"
                    f"  {commit_note}"
                )
        except Exception as e:
            return f"Error deleting: {e}"

    async def _factbook_commit(
        self, name: str | None, message: str, push: bool, remote: str, branch: str
    ) -> str:
        """Handler for nora_factbook_commit. Auto-detects default if name omitted."""
        try:
            from db import factbook_upsert_remote
            from factbook_git import write_and_commit_async

            # ─── Smart name resolution: auto-detect project if name not provided ───
            if not name:
                project = self._infer_project_from_cwd()
                if project:
                    name, _ = self._get_default_factbook_for_project(project)
                else:
                    return "No factbook name provided and could not infer project."

            kp_id = self._resolve_factbook_name(name)
            if kp_id is None:
                return f"Factbook not found: {name!r}"

            # Store remote if provided
            if remote:
                factbook_upsert_remote(kp_id, remote, branch)

            conn = self._connect_db()
            try:
                commit = await write_and_commit_async(
                    conn, kp_id, message or "checkpoint",
                    {"branch": branch, "push": push},
                    push=push
                )
            finally:
                conn.close()

            if commit == "nothing-to-commit":
                return f"Nothing to commit for \"{name}\" — factbook is already up to date."

            pushed_note = ""
            if push:
                pushed_note = f"\n  Pushed to {remote or 'origin'}/{branch}"

            return (
                f"Committed factbook \"{name}\".\n"
                f"  Commit: {commit}\n"
                f"  Message: {message or 'checkpoint'}"
                f"{pushed_note}"
            )
        except Exception as e:
            return f"Error committing factbook: {e}"

    def _factbook_provenance(self, fact_id_raw, project=None) -> str:
        """Return PROV-O lineage for a fact: sources, supersession history,
        confidence, decision-trace events. Mirrors the universal-gap demo
        from kernora:CLAUDE-CODE-EVALUATION-MAY-11-2026 §12.2.

        fact_id_raw can be: 'f765', '765', or integer 765. Normalizes to
        the 'f###' string form used in kernora-factbook.yaml.

        Returns markdown-formatted text suitable for direct rendering in
        a chat/CLI surface.
        """
        if fact_id_raw is None or fact_id_raw == "":
            return "Error: nora_provenance / nora_factbook(action='provenance') requires id."

        # Normalize id form: accept '', '765', 765, '    '.
        #
        # R-3 (launch-loop L3 CSAT): a bare int here used to be treated as a
        # literal 'fNNN' suffix (765 -> ""), but HTTP /api/inspector/prov
        # (and _resolve_fact_ref, the dual-shape resolver used elsewhere in
        # this file — nora_mcp.py:698) treat a bare int as the internal DB
        # row id, resolving e.g. 4064 -> . Same fact, two id keyspaces
        # across the two surfaces a doc-producer is told to use. Reuse
        # _resolve_fact_ref's dual-shape lookup so a bare int is looked up
        # against the DB first (internal id -> display fact_id); an explicit
        # 'fNNN' string is passed straight through unchanged.
        raw = str(fact_id_raw).strip().lower()
        if raw.startswith("f"):
            fact_id = raw
        else:
            fact_id = f"f{raw}"  # fallback if DB resolution below can't run/find it
            try:
                _conn = self._connect_db()
                try:
                    from db import _factlets_table_exists as _fte_prov
                    _tbl = "factlets" if _fte_prov(_conn) else "patterns"
                    _row = _resolve_fact_ref(_conn, _tbl, raw)
                    if _row is not None and _row["fact_id"]:
                        fact_id = str(_row["fact_id"]).strip().lower()
                finally:
                    _conn.close()
            except Exception:
                pass  # fall back to the f-prefix guess; YAML lookup below will 404 cleanly

        # Locate factbook YAML. Walk up from cwd to find .nora/kernora-factbook.yaml.
        from pathlib import Path as _Path
        cwd = _Path.cwd().resolve()
        yaml_path = None
        for parent in (cwd,) + tuple(cwd.parents):
            candidate = parent / ".nora" / "kernora-factbook.yaml"
            if candidate.exists():
                yaml_path = candidate
                break
        if yaml_path is None:
            return f"Error: no .nora/kernora-factbook.yaml found from {cwd} upward. Provenance requires a factbook."

        # Find the fact entry. Use line-scan over the YAML (avoids loading
        # the whole 5K-line file into a YAML parser for one fact).
        try:
            text = yaml_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"Error reading factbook YAML: {exc}"

        # Each fact starts with "- id: f###" at column 0 in this factbook
        # (verified empirically against .nora/kernora-factbook.yaml format).
        # Fields are 2-space indented under the fact entry.
        import re as _re
        # Capture from "- id: <fact_id>" up to next "- id: f" (column 0) or end.
        pattern = _re.compile(
            rf"(^- id: {_re.escape(fact_id)}\b.*?)(?=^- id: f|\Z)",
            _re.DOTALL | _re.IGNORECASE | _re.MULTILINE,
        )
        m = pattern.search(text)
        if not m:
            return (
                f"Fact {fact_id} not found in {yaml_path}.\n"
                f"Try `nora_factbook(action='view')` to list available facts."
            )
        fact_block = m.group(1)

        # Extract key fields with simple line-scan (the YAML format is consistent:
        # fields at 2-space indent under the entry).
        def _field(name: str) -> str | None:
            mm = _re.search(rf"^  {_re.escape(name)}:\s*(.+)$", fact_block, _re.MULTILINE)
            return mm.group(1).strip() if mm else None

        # Multi-line YAML list extractor for fields like `sources:` whose
        # value is a YAML list at 4-space indent under the 2-space-indented
        # field header (e.g.,
        #     sources:
        #       - CLAUDE.md:23
        #       - (internal doc)
        # ).
        def _list_field(name: str) -> list[str]:
            mm = _re.search(
                rf"^  {_re.escape(name)}:\s*\n((?:  -\s*.+\n?)+)",
                fact_block,
                _re.MULTILINE,
            )
            if not mm:
                return []
            items: list[str] = []
            for line in mm.group(1).splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    items.append(stripped[2:].strip())
            return items

        statement = _field("statement") or _field("text") or "(no statement)"
        confidence = _field("confidence")
        scope = _field("scope")
        learning_type = _field("learning_type") or _field("kind") or _field("factlet_type")
        added_at = _field("added_at") or _field("created_at")
        last_revised = _field("last_revised") or _field("amended_at")
        supersedes = _field("supersedes")
        superseded_by = _field("superseded_by")
        archived = _field("archived") or _field("archived_at")
        archived_reason = _field("archived_reason")
        sources_list = _list_field("sources")
        sources_scalar = _field("citation")  # alternate field name

        # Query decision_traces for this fact's downstream consumption events.
        trace_count = 0
        recent_traces: list[dict] = []
        try:
            import db as _db
            conn = _db.get_conn()
            try:
                cur = conn.cursor()
                args: list = [fact_id]
                where = "fact_id = ?"
                if project:
                    where += " AND project = ?"
                    args.append(project)
                cur.execute(
                    f"SELECT COUNT(*) FROM decision_traces WHERE {where}",
                    args,
                )
                trace_count = int(cur.fetchone()[0] or 0)
                cur.execute(
                    f"SELECT trace_type, project, occurred_at, confidence, signal_source, "
                    f"delta_type FROM decision_traces WHERE {where} "
                    f"ORDER BY occurred_at DESC LIMIT 5",
                    args,
                )
                for row in cur.fetchall():
                    recent_traces.append({
                        "trace_type": row[0],
                        "project": row[1],
                        "occurred_at": row[2],
                        "confidence": row[3],
                        "signal_source": row[4],
                        "delta_type": row[5],
                    })
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as exc:
            #  fallback: log and continue with empty traces. Provenance
            # still returns the YAML-side data; trace section just shows N/A.
            import sys as _sys
            print(
                f"[F404-FALLBACK] _factbook_provenance: decision_traces query failed: {exc}",
                file=_sys.stderr,
            )

        # Format output as markdown.
        lines: list[str] = []
        lines.append(f"# Provenance — {fact_id}")
        lines.append("")
        lines.append(f"**Statement:** {statement}")
        lines.append("")
        meta_parts = []
        if confidence:
            meta_parts.append(f"confidence: **{confidence}**")
        if scope:
            meta_parts.append(f"scope: {scope}")
        if learning_type:
            meta_parts.append(f"type: {learning_type}")
        if meta_parts:
            lines.append("  ·  ".join(meta_parts))
            lines.append("")

        if added_at or last_revised or archived:
            lines.append("## Lifecycle")
            if added_at:
                lines.append(f"- Added: {added_at}")
            if last_revised:
                lines.append(f"- Last revised: {last_revised}")
            if archived:
                arch_line = f"- ⚠️ Archived: {archived}"
                if archived_reason:
                    arch_line += f" — {archived_reason}"
                lines.append(arch_line)
            lines.append("")

        if supersedes or superseded_by:
            lines.append("## Supersession history")
            if supersedes:
                lines.append(f"- Supersedes: {supersedes}")
            if superseded_by:
                lines.append(f"- Superseded by: {superseded_by}")
            lines.append("")

        if sources_list or sources_scalar:
            lines.append("## Sources")
            for s in sources_list:
                lines.append(f"- {s}")
            if sources_scalar:
                lines.append(f"- {sources_scalar}")
            lines.append("")

        lines.append("## Decision-trace events (downstream consumption)")
        if trace_count == 0:
            lines.append(
                "_No decision-trace events recorded for this fact yet._ "
                "Events accumulate when the fact is cited in a session, "
                "applied to a code change, or overridden by an operator."
            )
        else:
            lines.append(f"**Total events:** {trace_count}")
            lines.append("")
            lines.append("**Recent (last 5):**")
            for t in recent_traces:
                bits = [f"`{t['trace_type']}`"]
                if t.get("delta_type"):
                    bits.append(f"delta: `{t['delta_type']}`")
                if t.get("project"):
                    bits.append(f"project: {t['project']}")
                if t.get("occurred_at"):
                    bits.append(f"at: {t['occurred_at']}")
                if t.get("confidence") is not None:
                    bits.append(f"conf: {t['confidence']}")
                lines.append(f"- " + " · ".join(bits))
        lines.append("")

        lines.append(f"_Source: `{yaml_path}` + decision_traces table._")
        return "\n".join(lines)

    # ── Lite YAML bridge — shared subprocess helper ─────────────────────────
    # nora_bridge.py's yaml_add_fact reads stdin directly (it's built to be
    # driven as a one-shot subprocess by the dashboard too — see nora_bridge
    # module docstring) so it cannot be called in-process; every caller here
    # goes through this one helper (f388 — one invocation shape, not
    # re-implemented per tool).
    def _bridge_script_path(self) -> "Path | None":
        _here = Path(__file__).resolve().parent
        candidates = [
            _here / "nora-desktop" / "scripts" / "nora_bridge.py",
            _here / "nora_bridge.py",
            Path.home() / ".kernora" / "app" / "nora_bridge.py",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _bridge_call(self, args: list, stdin_json: dict | None = None) -> dict:
        """Invoke nora_bridge.py <args> as a subprocess, optionally piping
        stdin_json, and return the parsed JSON payload. Never raises —
        subprocess/parse failures come back as {"ok": False, "error": ...}
        so callers can report them without a try/except at every call site.
        """
        import subprocess as _sp
        import sys as _sys

        bridge_script = self._bridge_script_path()
        if bridge_script is None:
            return {"ok": False, "error": "nora_bridge.py not found (Lite install is incomplete)"}

        py = _sys.executable
        cmd = [py, str(bridge_script), *args]
        try:
            proc = _sp.run(
                cmd,
                input=(json.dumps(stdin_json) if stdin_json is not None else None),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as e:
            return {"ok": False, "error": f"bridge subprocess failed: {e}"}

        try:
            payload = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": f"bridge returned non-JSON output (exit {proc.returncode}): "
                         f"{proc.stdout[:300]!r} stderr={proc.stderr[:300]!r}",
            }
        if not isinstance(payload, dict):
            return {"ok": False, "error": f"bridge returned non-object JSON: {payload!r}"}
        if "ok" not in payload and "error" in payload:
            payload["ok"] = False
        return payload

    def _factbook_add(
        self,
        statement: str,
        category: str = "pattern",
        confidence: float = 0.7,
        sources: list | None = None,
        project_root: str | None = None,
    ) -> str:
        """Handler for nora_factbook_add — appends to the CANONICAL project
        YAML factbook via nora_bridge.yaml_add_fact (the f389 chokepoint).

        NOTE on Lite vs private semantics: the private nora_factbook_add
        writes to a separate DB-resident kp_factbook side store
        (~/.kernora/factbooks/<kp_id>.json) and explicitly does NOT touch
        the canonical YAML — see the private tool's own description
        ("Does NOT write to the canonical project YAML factbook; see
        f591"). Lite has no kp_factbook/membership/compliance-tier
        infrastructure to port (Team+ surface), so this tool instead
        writes directly to the canonical YAML factbook — the same file
        nora_factbook_view and nora_search already read in Lite. This is a
        deliberate, documented behavior divergence, not a bug.
        """
        root = Path(project_root).expanduser().resolve() if project_root else Path.cwd()
        if not (root / ".nora").is_dir():
            return f"Error: no .nora/ directory at {root} — run `kernora init` (or create one) first."

        fact = {
            "statement": statement,
            "category": category or "pattern",
            "confidence": confidence,
            "review_status": "candidate",
            "origination": "nora_factbook_add",
        }
        if sources:
            fact["sources"] = sources

        result = self._bridge_call(["yaml_add_fact", str(root)], stdin_json=fact)
        if not result.get("ok"):
            return f"Error adding fact: {result.get('error', 'unknown bridge error')}"

        note = ""
        if result.get("needs_source"):
            note = "\n  (no source provided — recorded as unsourced/low-trust; a factlet with no source is an opinion)"
        return (
            f"Added fact {result['fact_id']} to {result['path']}\n"
            f"  [{category}] {statement[:80]}{'...' if len(statement) > 80 else ''}"
            f"{note}"
        )

    def _factbook_reverse(
        self,
        old_ref: str,
        new_statement: str,
        reason: str | None = None,
        project_root: str | None = None,
    ) -> str:
        """Handler for nora_factbook_reverse — retires one fact and creates
        its replacement in the canonical YAML factbook, in one call.

        Simplified Lite version of the private multi-shape resolver (which
        also searches a DB fact-store Lite doesn't vendor — see
        RESYNC-AUDIT.md). old_ref resolution here is YAML-only:
          - matches ^f\\d+$               → treated as an explicit fact id
          - anything else                 → case-insensitive substring
                                             match against every live
                                             (non-superseded) fact's
                                             `statement` field
        0 matches or 2+ matches ALWAYS refuses and lists candidates — never
        guesses (tenet: fail closed on ambiguity).

        Two separate YAML writes (create, then link) — not one atomic
        transaction. If create succeeds but the link (supersede) fails,
        the response reports BOTH ids so the link can be retried via
        nora_factbook_promote(action='supersede', fact_id=..., supersedes_id=...)
        rather than silently leaving an unlinked orphan.
        """
        root = Path(project_root).expanduser().resolve() if project_root else Path.cwd()
        if not (root / ".nora").is_dir():
            return f"Error: no .nora/ directory at {root} — run `kernora init` (or create one) first."

        ref = (old_ref or "").strip()
        old_id: str | None = None

        bridge_script = self._bridge_script_path()
        if bridge_script is None:
            return "Error: nora_bridge.py not found (Lite install is incomplete)."
        _bridge_dir = str(bridge_script.parent)
        if _bridge_dir not in sys.path:
            sys.path.insert(0, _bridge_dir)
        try:
            from nora_bridge import _load_factbook_yaml as _bridge_load  # type: ignore
        except Exception as e:
            return f"Error: nora_bridge.py unavailable ({e})."

        if re.match(r"^f\d+$", ref):
            old_id = ref
            try:
                _y, _p, _doc = _bridge_load(root)
                _fact = None
                for _entry in (_doc.get("content") or []):
                    if isinstance(_entry, dict) and _entry.get("id") == ref:
                        _fact = _entry
                        break
                if _fact is None:
                    return f"Error: [F404-REVERSE-ID-NOT-FOUND] no factlet with id={ref!r} in {_p}."
            except Exception as e:
                return f"Error resolving {ref!r}: {e}"
        else:
            try:
                _y, _p, _doc = _bridge_load(root)
            except Exception as e:
                return f"Error reading factbook: {e}"
            needle = ref.lower()
            hits = []
            for _entry in (_doc.get("content") or []):
                if not isinstance(_entry, dict):
                    continue
                if _entry.get("superseded_by"):
                    continue  # already-dead facts are not reverse-able targets
                stmt = str(_entry.get("statement") or "")
                if needle in stmt.lower():
                    hits.append(_entry)
            if len(hits) == 0:
                return (
                    f"Error: [F404-REVERSE-NO-MATCH] no live factlet's statement contains "
                    f"{old_ref!r}. Try nora_search({old_ref!r}) to find the fact id first."
                )
            if len(hits) >= 2:
                candidates = "\n".join(
                    f"  - {h.get('id')}: {str(h.get('statement') or '')[:100]}"
                    for h in hits
                )
                return (
                    f"Error: [AMBIGUOUS-REVERSE-MATCH] {len(hits)} live factlets matched "
                    f"{old_ref!r} — re-call with an explicit id:\n{candidates}"
                )
            old_id = hits[0].get("id")

        if not old_id:
            return "Error: could not resolve old_ref to a fact id."

        _reason = reason or "superseded"
        new_fact = {
            "statement": new_statement,
            "category": "pattern",
            "confidence": 0.7,
            "review_status": "candidate",
            "origination": "nora_factbook_reverse",
        }
        create_result = self._bridge_call(["yaml_add_fact", str(root)], stdin_json=new_fact)
        if not create_result.get("ok"):
            return f"Error: [F404-REVERSE-CREATE-FAILED] {create_result.get('error', 'unknown bridge error')}"
        new_id = create_result["fact_id"]

        link_result = self._bridge_call([
            "yaml_supersede", str(root), old_id, new_id, "--reason", _reason,
        ])
        if not link_result.get("ok"):
            return (
                f"Created {new_id} but FAILED to link it as the replacement for {old_id}: "
                f"{link_result.get('error', 'unknown bridge error')}\n"
                f"Retry the link with: nora_factbook_promote(action='supersede', "
                f"fact_id={new_id!r}, supersedes_id={old_id!r})"
            )

        return (
            f"Reversed {old_id} → {new_id} in {link_result.get('path', create_result.get('path'))}\n"
            f"  Old: superseded_by={new_id}, valid_until={link_result.get('valid_until')}\n"
            f"  New: {new_statement[:80]}{'...' if len(new_statement) > 80 else ''}"
        )

    def _factbook_supersede(
        self,
        fact_id=None,
        supersedes_id=None,
        kp_id: str | None = None,
        reason: str | None = None,
        project_root: str | None = None,
    ) -> str:
        """Handler for nora_factbook_promote(action='supersede') — Lite YAML
        version. Simplified from the private DB-bitemporal implementation
        (which also updates compliance_tier/audit_log/kp_factbooks rows —
        Team+ surface Lite doesn't vendor, see RESYNC-AUDIT.md): both ids
        here are f### YAML fact ids (or bare integers, auto-prefixed with
        'f'), and the write goes straight to nora_bridge.yaml_supersede —
        the same verb nora_factbook_reverse's link step uses (f388 — one
        supersede impl, not duplicated between the two call sites).
        """
        if supersedes_id is None:
            return json.dumps({
                "error": "[F404-PROMOTE-MISSING-SUPERSEDES-ID]",
                "message": "action='supersede' requires supersedes_id (the factlet being superseded).",
            })
        if fact_id is None:
            return json.dumps({
                "error": "[F404-SUPERSEDE-MISSING-FACT-ID]",
                "message": "action='supersede' requires fact_id (the new/superseding factlet).",
            })

        def _as_fid(v) -> str:
            s = str(v).strip()
            if s.startswith("f"):
                return s
            try:
                return f"f{int(s):03d}"  # match yaml_add_fact's 3-digit padding convention
            except ValueError:
                return f"f{s}"

        old_id = _as_fid(supersedes_id)
        new_id = _as_fid(fact_id)
        root = Path(project_root).expanduser().resolve() if project_root else Path.cwd()

        result = self._bridge_call([
            "yaml_supersede", str(root), old_id, new_id,
            "--reason", reason or "superseded",
        ])
        if not result.get("ok"):
            return json.dumps({"error": "[SUPERSEDE-YAML-WRITE-FAILED]", "message": result.get("error"),
                                "old_id": old_id, "new_id": new_id})
        return json.dumps({
            "superseded": {"fact_id": old_id, "valid_until": result.get("valid_until")},
            "superseder": {"fact_id": new_id, "valid_from": result.get("valid_from")},
            "reason": reason or "superseded",
            "path": result.get("path"),
            "action": "supersede",
            "status": "ok",
        })

    async def _factbook_verify(self, name: str | None, fact_id: int | None) -> str:
        """SPRINT 2: Handler for nora_factbook_verify. Uses Opus 4.7 reasoning (effort='xhigh')."""
        try:
            from db import get_conn, factbook_get

            if fact_id is None:
                return "fact_id is required for verification"

            # ─── Smart name resolution: auto-detect project if name not provided ───
            if not name:
                project = self._infer_project_from_cwd()
                if project:
                    name, _ = self._get_default_factbook_for_project(project)
                else:
                    return "No factbook name provided and could not infer project."

            kp_id = self._resolve_factbook_name(name)
            if kp_id is None:
                return f"Factbook not found: {name!r}"

            # Get factbook and find the specific fact
            fb = factbook_get(kp_id)
            if not fb:
                return f"Factbook not found: {kp_id}"

            fact = None
            for f in fb.get("facts", []):
                if f.get("id") == fact_id:
                    fact = f
                    break

            if not fact:
                return f"Fact {fact_id} not found in factbook {name!r}"

            # Verify using Opus 4.7
            from analyzer import verify_fact

            # arc ③ (2026-07-04): pass the fact's REAL sources — verifying
            # against "(no sources)" was the source-blind half of the 
            # fail-open pair. Factbook facts carry sources/source/source_uri
            # depending on vintage; accept any.
            _v_sources = fact.get("sources") or []
            if not _v_sources:
                _v_sources = [s for s in (fact.get("source"), fact.get("source_uri"),
                                          fact.get("source_ref")) if s]
            verification = verify_fact(
                {
                    "statement": fact.get("statement"),
                    "confidence": fact.get("confidence", 0.85),
                    "fact_type": fact.get("type", "pattern"),
                    "sources": _v_sources,
                },
                verify_sources=False,
            )

            # arc ③: verifier unavailable → NO stamp, NO DB write. Stamping
            # content_verified_at on a skipped check would mint a fake
            # human-verification (the exact  class this arc closes).
            if verification.get("skipped"):
                return ("⚠️ Verifier unavailable (LiteLLM not installed) — fact "
                        f"{fact_id} remains UNVERIFIED (fail-closed). Nothing was stamped.")

            # A model-REJECTED fact (is_valid False, not skipped) must NOT be
            # recorded as human-verified: null its verified_confidence and skip the
            # content-verify stamp, mirroring the DREAM write-back (dreamer.py) so a
            # rejected fact can never ride the trust bar or clear the promotion gate.
            # QL 2026-07-08 — / fail-closed on the trust surface. (is_valid
            # was previously read only AFTER this write, so the write ignored it.)
            is_valid = bool(verification.get("is_valid", False))
            _stored_conf = verification.get("confidence") if is_valid else None

            # Store verification results in database
            conn = get_conn()
            try:
                from db import _factlets_table_exists as _fte_pe
                _pe_tbl = "factlets" if _fte_pe(conn) else "patterns"
                # Post-S2: factlets has no factbook_id in WHERE (row is uniquely identified by id).
                # Pre-S2: patterns used factbook_id scope for safety; keep it there.
                if _pe_tbl == "factlets":
                    conn.execute(
                        f"""UPDATE factlets
                           SET verified_confidence=?, verification_issues=?, verification_reasoning=?, verified_at=?
                           WHERE id=?""",
                        (
                            _stored_conf,  # NULL when the model rejected the fact
                            json.dumps(verification.get("issues", [])),
                            verification.get("reasoning", ""),
                            verification.get("verified_at"),
                            fact_id,
                        ),
                    )
                else:
                    conn.execute(
                        """UPDATE patterns
                           SET verified_confidence=?, verification_issues=?, verification_reasoning=?, verified_at=?
                           WHERE id=? AND factbook_id=?""",
                        (
                            _stored_conf,  # NULL when the model rejected the fact
                            json.dumps(verification.get("issues", [])),
                            verification.get("reasoning", ""),
                            verification.get("verified_at"),
                            fact_id,
                            kp_id,
                        ),
                    )
                conn.commit()
                #  (Jul-17 audit F2) — this handler is an LLM-judge
                # MACHINE path (verify_fact() above calls out to an LLM). It MUST
                # NOT stamp content_verified_at — that is the TOP human trust band
                # and is reserved for a genuine out-of-band operator action
                # (the `kernora verify` CLI wizard, gated on a real TTY at the
                # db.stamp_content_verified_at chokepoint). The correct ceiling
                # for a machine verdict is band 3 ("auto-verified"), reached via
                # review_status='verified' alone — FactSignal scoring reads
                # content_verified_at OR review_status, not verified_at, so
                # review_status is the write that actually matters here. ONLY
                # when the model validated the fact (fail-closed on reject,
                # mirroring the QL-2026-07-08 guard above).
                if is_valid:
                    if _pe_tbl == "factlets":
                        conn.execute(
                            "UPDATE factlets SET review_status='verified' WHERE id=?",
                            (fact_id,),
                        )
                    else:
                        conn.execute(
                            "UPDATE patterns SET review_status='verified' WHERE id=? AND factbook_id=?",
                            (fact_id, kp_id),
                        )
                    conn.commit()
            finally:
                conn.close()

            # Format response — is_valid defaults FALSE (arc ③, : an
            # absent verdict is not a pass).
            is_valid = verification.get("is_valid", False)
            verified_conf = verification.get("confidence", 0.0)
            claimed_conf = fact.get("confidence", 0.85)
            issues = verification.get("issues", [])
            reasoning = verification.get("reasoning", "")

            status_icon = "✅" if is_valid else "⚠️"
            conf_diff = f" (claimed: {claimed_conf})" if abs(verified_conf - claimed_conf) > 0.1 else ""

            return (
                f"{status_icon} Fact {fact_id} Verification Complete\n"
                f"  Verified Confidence: {verified_conf:.2f}{conf_diff}\n"
                f"  Valid: {'Yes' if is_valid else 'No'}\n"
                f"  Issues: {len(issues)}\n"
                + (f"  Issues Found:\n" + "\n".join(f"    - {issue}" for issue in issues) + "\n" if issues else "")
                + f"  Reasoning: {reasoning[:200]}...\n"
                + f"  Stored in DB for audit trail"
            )
        except Exception as e:
            return f"Error verifying fact: {e}"

    async def _factbook_view(
        self,
        name: str | None = None,
        layer: str | None = None,
        kp_id_explicit: str | None = None,
        include_superseded: bool = False,
    ) -> str:
        """Handler for nora_factbook_view. Returns formatted summary + raw facts. Auto-detects default if name omitted.
        §17.6 P-06: layer filter + include_superseded guidance applied.
        §17.2 P-02: parameterized queries only.
        """
        try:
            import db as _db
            from factbook_git import format_facts_summary

            # ─── Resolve kp_id: explicit > name lookup > project inference ───
            # §17.6 P-06: kp_id_explicit bypasses name-resolution entirely.
            # §17.2 P-02: all SQL uses ? placeholders — no f-string interpolation.
            resolved_kp_id: str | None = None
            layer_resolved_block: str | None = None

            if kp_id_explicit:
                resolved_kp_id = kp_id_explicit
            elif name:
                resolved_kp_id = self._resolve_factbook_name(name)
            else:
                # Step 0: .nora/kp-context pin (mirrors _search Step 0 and
                # db._resolve_default_layer Step 1).  Lets a fresh `claude`
                # session in a pinned project dir (e.g. the demo dir) resolve
                # the pinned kp directly instead of falling through to the
                # generic *-learnings default — without this, `nora_factbook_view`
                # with no kp_id resolved the wrong (default) kp and denied.
                try:
                    import os as _os_kpc
                    _kp_ctx = (
                        __import__("pathlib").Path(_os_kpc.getcwd()) / ".nora" / "kp-context"
                    )
                    if _kp_ctx.exists():
                        _pinned = _kp_ctx.read_text().strip()
                        if _pinned:
                            resolved_kp_id = _pinned
                except Exception:
                    pass  # [F404-VIEW-KP-CONTEXT] .nora/kp-context read failed; falling through
                # Auto-detect from cwd (only if no pin)
                if resolved_kp_id is None:
                    project = self._infer_project_from_cwd()
                    if project:
                        # MED fix (launch-loop L3 walk2, 2026-07-19): try the
                        # project's REAL factbook kp_id (read from its YAML's
                        # top-level `id:`) BEFORE the name-convention guess
                        # below — the guess resolves to whatever
                        # "{project}-learnings" kp_factbooks row happens to
                        # exist (an auto-created near-empty bucket, or on
                        # this walk's live repro a DIFFERENT private pack
                        # entirely -> READ-DENIED on the owner's own
                        # machine), not the project's actual grounding
                        # corpus. See db.resolve_project_factbook_kp_id
                        # docstring for the full root-cause writeup (same
                        # class as the B2 nora_search fix).
                        try:
                            resolved_kp_id = _db.resolve_project_factbook_kp_id(project)
                        except Exception:
                            resolved_kp_id = None  # [F404-VIEW-YAML-KPID] fall through to name-convention guess
                        if resolved_kp_id is None:
                            name, _ = self._get_default_factbook_for_project(project)
                            if name:
                                resolved_kp_id = self._resolve_factbook_name(name)
                if resolved_kp_id is None:
                    # Layer resolver fallback: use _resolve_default_layer
                    try:
                        import os
                        cwd = os.getcwd()
                        lyr, lyr_reason = _db._resolve_default_layer(cwd)
                        layer_resolved_block = (
                            f"[F404-LAYER-RESOLVED] layer={lyr!r} "
                            f"reason={lyr_reason!r} — no factbook specified; "
                            f"listing available factbooks."
                        )
                    except Exception:
                        pass  # [F404-VIEW-LAYER-RESOLVER] _resolve_default_layer failed; continuing without layer signal
                    conn = self._connect_db()
                    try:
                        rows = conn.execute(
                            "SELECT kp_id, title FROM kp_factbooks WHERE archived = 0 "
                            "ORDER BY updated_at DESC LIMIT 10"
                        ).fetchall()
                    finally:
                        conn.close()
                    available = "\n".join(
                        f"  • {r['kp_id']} — {r['title']}" for r in rows
                    ) or "  (none yet)"
                    # §17b.17: layer_resolved as structured JSON key, not text-prepend.
                    _lr_structured = None
                    if layer_resolved_block:
                        try:
                            import os as _os_lr
                            _lyr_lr, _src_lr = _db._resolve_default_layer(_os_lr.getcwd())
                            _lr_structured = {"layer": _lyr_lr, "source": _src_lr, "signal": "[F404-LAYER-RESOLVED]"}
                        except Exception:
                            _lr_structured = {"raw": layer_resolved_block}
                    return json.dumps({
                        "error": "no_factbook_specified",
                        "message": "No factbook name provided and could not infer project.",
                        "available_factbooks": [{"kp_id": r["kp_id"], "title": r["title"]} for r in rows],
                        "layer_resolved": _lr_structured,
                    })

            if resolved_kp_id is None:
                conn = self._connect_db()
                try:
                    rows = conn.execute(
                        "SELECT kp_id, title FROM kp_factbooks WHERE archived = 0 "
                        "ORDER BY updated_at DESC LIMIT 10"
                    ).fetchall()
                finally:
                    conn.close()
                available = "\n".join(
                    f"  • {r['kp_id']} — {r['title']}" for r in rows
                ) or "  (none yet)"
                return f"Factbook not found: {name!r}\n\nAvailable factbooks:\n{available}"

            # §17b.1 B-α: read-path authorization check (T6 privacy invariant).
            import getpass as _getpass_view
            try:
                from db import _check_read_access as _cra_view
                _view_conn = self._connect_db()
                try:
                    _view_caller = _getpass_view.getuser()
                    _view_allowed, _view_reason = _cra_view(_view_conn, resolved_kp_id, _view_caller)
                finally:
                    _view_conn.close()
                if not _view_allowed:
                    return json.dumps({
                        "error": "unauthorized",
                        "kp_id": resolved_kp_id,
                        "reason": _view_reason,
                    })
            except Exception as _cra_view_exc:
                # [F404-VIEW-AUTH-IMPORT] auth check raised; failing CLOSED per T6 privacy invariant.
                import sys as _sys_cra_view
                print(f"[F404-VIEW-AUTH-IMPORT] _check_read_access raised {type(_cra_view_exc).__name__}: {_cra_view_exc}", file=_sys_cra_view.stderr)
                return json.dumps({"error": "unauthorized", "kp_id": resolved_kp_id, "reason": "auth_check_failed"})

            # ─── Fetch factbook metadata ─────────────────────────────────────
            conn = self._connect_db()
            try:
                # Build layer filter for kp_factbooks if layer param given.
                # §17.6 P-06: layer restricts which layer-tagged factlets are shown.
                # Schema-drift compat: db.py Migration 1 renamed kp_factbooks.scope
                # -> layer_type.  Select whichever column the live schema has so
                # this read path works on both pre- and post-migration DBs (the
                # un-migrated `scope` SELECT here was a hard failure on any DB that
                # had run Migration 1).
                _kpf_cols = {r[1] for r in conn.execute("PRAGMA table_info(kp_factbooks)").fetchall()}
                _scope_col = "scope" if "scope" in _kpf_cols else (
                    "layer_type" if "layer_type" in _kpf_cols else None
                )
                _scope_select = f"{_scope_col} AS scope, " if _scope_col else ""
                fb_row = conn.execute(
                    f"SELECT kp_id, title, {_scope_select}kp_type, git_remote, git_branch, "
                    "       created_at, updated_at "
                    "FROM kp_factbooks WHERE kp_id = ? AND archived = 0",
                    (resolved_kp_id,),
                ).fetchone()
                if fb_row is None:
                    return f"Factbook not found: {resolved_kp_id!r}"
                fb = dict(fb_row)

                # ─── Build facts query with §17.6 P-06 filters ──────────────
                # CV-1 BLOCKER (ADJ-1): WHERE superseded_by IS NULL unless
                # include_superseded=True.
                # §17.2 P-02: parameterized queries only.
                params_list: list = [resolved_kp_id]
                supers_clause = "" if include_superseded else " AND (superseded_by IS NULL OR compliance_tier='non_overridable')"
                layer_clause = ""
                if layer:
                    layer_clause = " AND scope_level = ?"
                    params_list.append(layer)

                facts_rows = conn.execute(
                    "SELECT id, name, pattern, fact_type, confidence, review_status, "
                    "       source_type, created_by, created_at, tags, "
                    "       validation_status, validated_at, verified_confidence, "
                    "       verification_issues, verified_at, content_verified_at, "
                    "       effectiveness, reinforcement_count, "
                    "       superseded_by, scope_level, compliance_tier "
                    "FROM patterns WHERE factbook_id = ? AND archived = 0"
                    + supers_clause + layer_clause
                    + " ORDER BY created_at ASC LIMIT 1000",
                    params_list,
                ).fetchall()
            finally:
                conn.close()

            import json as _json
            import re as _re_view
            facts = []
            for f in facts_rows:
                fd = dict(f)
                try:
                    fd["tags"] = _json.loads(fd.get("tags") or "[]")
                except Exception:
                    fd["tags"] = []
                facts.append(fd)

            # Rich FactSignal summary: per fact, a verification-freshness trust
            # read rendered as glyph bar (primary strength channel, WCAG 1.4.1)
            # + emoji dot (color channel that survives a markdown/chat surface
            # where ANSI does not) + staleness + supersession marker. A bare
            # fNNN name is an internal label, not a statement, so the body is
            # shown (customer-facing rule: never surface bare fXXX).
            # NOTE (public-resync 2026-07-19): the private build renders a
            # 5-bar FactSignal glyph meter here. That scoring subsystem is not
            # vendored in this pass — simplified to a plain verified/confidence
            # line so the tool still functions without dragging in unaudited
            # content.
            _summary_lines = []
            for _i, fd in enumerate(facts, 1):
                _verified = "verified" if fd.get("content_verified_at") else "unverified"
                _ft = fd.get("fact_type") or "convention"
                try:
                    _cf = float(fd.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    _cf = 0.0
                _sup = ""
                if fd.get("superseded_by"):
                    _sup = f" · ⊛ superseded by {fd['superseded_by']}"
                _nm = (fd.get("name") or "").strip()
                _body = fd.get("pattern", "") if _re_view.fullmatch(r"f\d+", _nm) else (_nm or fd.get("pattern", ""))
                _summary_lines.append(
                    f"{_i}. {_ft} · {_verified} "
                    f"· conf {_cf:.2f}{_sup}\n   {_body}"
                )
            summary = "\n".join(_summary_lines) if _summary_lines else "No facts yet."

            layer_note = f" · Layer: {layer}" if layer else ""
            superseded_note = " (incl. superseded)" if include_superseded else ""
            header = (
                f"Factbook: {fb['title']}\n"
                f"  ID: {resolved_kp_id} · Scope: {fb.get('scope', 'personal')}"
                f"{layer_note} · {len(facts)} fact(s){superseded_note}"
            )
            header += f"\n  Updated: {fb.get('updated_at', 'unknown')[:10]}"

            schema_header = f"schema_version: {_MCP_SCHEMA_VERSION}\n"
            # §17b.17: layer_resolved as structured JSON key, not text-prepend.
            _lr_final = None
            if layer_resolved_block:
                try:
                    import os as _os_lr2
                    _lyr_f, _src_f = _db._resolve_default_layer(_os_lr2.getcwd())
                    _lr_final = {"layer": _lyr_f, "source": _src_f, "signal": "[F404-LAYER-RESOLVED]"}
                except Exception:
                    _lr_final = {"raw": layer_resolved_block}
            return json.dumps({
                "schema_version": _MCP_SCHEMA_VERSION,
                "header": header,
                "summary": summary,
                "layer_resolved": _lr_final,
                "kp_id": resolved_kp_id,
                "fact_count": len(facts),
            })
        except Exception as e:
            return f"Error viewing factbook: {e}"

    async def _factbook_inject(
        self,
        name: str | None,
        layer: str | None = None,
        kp_id_explicit: str | None = None,
        min_compliance_tier: str = "standard",
        require_verified: bool = False,
    ) -> str:
        """Handler for nora_factbook_inject. Deploy pending facts to steering files immediately.
        §17.19 P-19: returns layer_resolved block when resolver was invoked.
        §17.24 P-24: T8b advisory quality gate (min_compliance_tier, require_verified).
        """
        import sys as _sys
        _layer_resolved = None
        try:
            # ─── Smart name resolution: auto-detect project if name not provided ───
            if kp_id_explicit:
                kp_id = kp_id_explicit
                name = kp_id_explicit
            elif not name:
                project = self._infer_project_from_cwd()
                if project:
                    name, kp_id = self._get_default_factbook_for_project(project)
                else:
                    # Use default-layer resolver and log [F404-LAYER-RESOLVED]
                    try:
                        from db import _resolve_default_layer
                        _layer, _source = _resolve_default_layer(
                            getattr(self, '_project_root', None)
                        )
                        _layer_resolved = {"layer": _layer, "source": _source, "signal": "[F404-LAYER-RESOLVED]"}
                    except Exception:
                        pass  # [F404-INJECT-LAYER-RESOLVER] _resolve_default_layer failed; layer_resolved will be null
                    return json.dumps({
                        "error": "no_factbook_name",
                        "message": "No factbook name provided and could not infer project.",
                        "layer_resolved": _layer_resolved,
                    })
            else:
                kp_id = self._resolve_factbook_name(name)
                if kp_id is None:
                    return f"Factbook not found: {name!r}"

            # §17b.8 T8b advisory quality gate: filter pending facts by
            # min_compliance_tier + require_verified before counting.
            # Compliance tier ordering: standard < audit_required < non_overridable.
            _TIER_ORDER = {"standard": 0, "audit_required": 1, "non_overridable": 2}
            _min_tier_rank = _TIER_ORDER.get(min_compliance_tier, 0)

            # Count pending facts (pre-filter total)
            conn = self._connect_db()
            try:
                total_pending_rows = conn.execute(
                    "SELECT id, compliance_tier, review_status FROM patterns "
                    "WHERE factbook_id = ? AND archived = 0 AND deployment_status = 'pending'",
                    (kp_id,)
                ).fetchall()
            finally:
                conn.close()

            total_pending = len(total_pending_rows)
            # Apply T8b filters
            filtered_ids = []
            for _row in total_pending_rows:
                _row_tier = _row[1] if len(_row) > 1 else "standard"
                _row_status = _row[2] if len(_row) > 2 else ""
                _row_tier_rank = _TIER_ORDER.get(_row_tier or "standard", 0)
                if _row_tier_rank < _min_tier_rank:
                    continue  # below minimum compliance tier
                if require_verified and _row_status != "verified":
                    continue  # require_verified=True but fact not yet verified
                filtered_ids.append(_row[0])

            pending = len(filtered_ids)
            filtered_count = total_pending - pending

            if total_pending == 0:
                return json.dumps({
                    "status": "already_deployed",
                    "message": f"✓ All facts in \"{name}\" are already deployed.",
                    "filtered_count": 0,
                    "layer_resolved": _layer_resolved,
                })

            if pending == 0:
                return json.dumps({
                    "status": "filtered_all",
                    "message": (
                        f"All {total_pending} pending fact(s) in \"{name}\" were filtered out by "
                        f"T8b quality gate (min_compliance_tier={min_compliance_tier!r}, "
                        f"require_verified={require_verified})."
                    ),
                    "filtered_count": filtered_count,
                    "total_pending": total_pending,
                    "layer_resolved": _layer_resolved,
                })

            # Inject via API (call steering_writer)
            try:
                from steering_writer import generate_all

                conn = self._connect_db()
                try:
                    generate_all()

                    # Mark qualifying facts as deployed (filtered_ids only)
                    if filtered_ids:
                        from db import _factlets_table_exists as _fte_dep
                        _dep_tbl = "factlets" if _fte_dep(conn) else "patterns"
                        _placeholders = ",".join("?" * len(filtered_ids))
                        conn.execute(
                            f"UPDATE {_dep_tbl} SET deployment_status = 'deployed' "
                            f"WHERE id IN ({_placeholders}) AND deployment_status = 'pending'",
                            filtered_ids,
                        )
                    conn.commit()
                finally:
                    conn.close()

                # §17b.9: emit layer_resolved in inject success branch
                return json.dumps({
                    "status": "deployed",
                    "message": (
                        f"✓ Deployed {pending} fact(s) from \"{name}\": "
                        f"CLAUDE.md · .cursorrules · .kiro/rules.md updated."
                    ),
                    "deployed_count": pending,
                    "filtered_count": filtered_count,
                    "layer_resolved": _layer_resolved,
                })
            except ImportError:
                return json.dumps({
                    "status": "deferred",
                    "message": (
                        f"⚠️ steering_writer not available, but {pending} facts will be deployed at next cycle."
                    ),
                    "deployed_count": pending,
                    "filtered_count": filtered_count,
                    "layer_resolved": _layer_resolved,
                })

        except Exception as e:
            return f"Error injecting factbook: {e}"

    def _generate(self, preview: bool = False) -> str:
        """Handler for nora_generate — in-chat equivalent of `kernora generate`.

        v2.2.10: `preview=True` runs the full computation, returns the
        proposed CLAUDE.md content + a diff summary, but DOES NOT write
        to disk. Added after the v2.2.9 JWM incident where hand-authored
        schema docs were destroyed by an over-aggressive orphan strip.
        Preview-first is now the recommended UX for any run against an
        existing rich CLAUDE.md.

        BUG-A (v2.2.2): Users type `nora generate` in Claude Code / Cursor /
        Kiro chat. MCP routes it here. We call steering_writer.generate_all
        directly (same code path as the CLI) and report the file list.

        Rationale for a separate tool (vs routing to nora_factbook_inject):
          - `factbook_inject` is the internal technical handle, not what
            humans type.
          - `nora generate` matches the `kernora generate` shell verb 1:1,
            so users don't have to learn two names.
          - Gives us a clean hook to report shell-equivalent output.
        """
        try:
            from pathlib import Path as _P
            import importlib
            import steering_writer
            importlib.reload(steering_writer)  # pick up hot edits during dev

            # BUG-H (v2.2.3): scope to cwd, not the git-root walk-up. Lets a
            # subproject (VidafolioiOS inside jivant-master) emit to its
            # own CLAUDE.md scoped to its own session namespace.
            cwd = _P.cwd().resolve()

            # v2.2.10: preview mode — run the generator in dry-run form,
            # showing what WOULD be added without touching disk.
            if preview:
                return self._generate_preview(cwd)

            files = steering_writer.generate_all(project_root=cwd)

            if not files:
                return (
                    "`nora generate` completed but produced no files. "
                    "Check `~/.kernora/logs/` for details or run "
                    "`kernora generate` at the shell to surface errors."
                )

            # Partition into repo-scoped vs global steering for a tidy report.
            git_root = steering_writer._find_git_repo_root(cwd)
            repo_dirs = {cwd, git_root}
            repo_files = [f for f in files if any(d in _P(f).parents or _P(f) == d / f.name for d in repo_dirs)]
            global_files = [f for f in files if f not in repo_files]

            # BUG-L (v2.2.7): surface the CLAUDE.md enhance receipt as a
            # proposal-style summary Claude can reason over. The marker
            # contract means we can write-first safely — user content
            # outside the markers is structurally untouchable.
            receipt = getattr(files, "claude_md_receipt", {}) or {}
            state = receipt.get("state", "unknown")
            state_blurb = {
                "created":     "Created CLAUDE.md (file was absent).",
                "enhanced":    "Enhanced existing CLAUDE.md (Nora block appended; "
                               "your pre-existing content preserved as-is).",
                "re-enhanced": "Re-enhanced existing CLAUDE.md (Nora's marker block "
                               "replaced; everything outside the markers preserved).",
                "unknown":     "CLAUDE.md write reported no state.",
                "error":       f"CLAUDE.md write FAILED: {receipt.get('error', 'unknown')}",
            }.get(state, state)

            lines = [f"🟢 Nora · Kernora — enhanced AI context for `{cwd.name}`"]
            lines.append("")
            lines.append(state_blurb)
            lines.append("")

            # Quantified proposal Claude can reason over.
            if receipt.get("state") in ("created", "enhanced", "re-enhanced"):
                lines.append("**Nora's contribution (inside `<!-- nora:auto-start -->` markers):**")
                lines.append(f"  • Verified facts surfaced: {receipt.get('new_facts', 0)}")
                lines.append(f"  • Verified decisions surfaced: {receipt.get('new_decisions', 0)}")
                lines.append(f"  • Nora block size: {receipt.get('nora_bytes', 0)} bytes")
                if receipt.get("preserved_bytes", 0) > 0:
                    lines.append(
                        f"  • Preserved outside markers: "
                        f"{receipt.get('preserved_bytes', 0)} bytes (your content)"
                    )
                lines.append("")

            lines.append("**Files touched:**")
            for f in repo_files:
                lines.append(f"  • {f}")
            if global_files:
                lines.append("")
                lines.append("**Global steering (user-wide, also updated):**")
                for f in global_files:
                    lines.append(f"  • {f}")
            lines.append("")

            # Close with a Claude-addressed note that frames the consent model.
            lines.append(
                "**Does this help?** If any of Nora's surfaced patterns/decisions "
                "are noise for your current task, call `nora_revise` with a drop-"
                "list and reason — Nora will regenerate without them and log the "
                "rejection so future emits get smarter. Shell equivalent for a "
                "fresh run: `kernora generate`."
            )
            if state == "created":
                lines.append("")
                lines.append(
                    "_This file was absent, so Nora emitted a stack-detected "
                    "skeleton above the markers. For real structural detail "
                    "(build/test commands, architecture) run `/init` in Claude "
                    "Code, then re-run `nora generate` to re-enhance._"
                )
            if receipt.get("new_facts", 0) == 0 and state != "created":
                lines.append("")
                lines.append(
                    f"_Nora has no verified facts yet for `{cwd.name}`. "
                    f"Run `nora scan {cwd} 200` to seed from git history, "
                    f"then re-run `nora generate` to populate verified signal._"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"nora generate error: {e}"

    def _generate_preview(self, cwd) -> str:
        """v2.2.10: dry-run CLAUDE.md proposal. No writes.

        Computes what the full generator would write, reads the current
        CLAUDE.md (if any), shows: (a) the Nora block Nora proposes,
        (b) how much user content would be preserved outside markers,
        (c) any orphan-header cleanup that would happen, (d) a SAFETY
        WARNING if the operation would shrink user content > 50%
        (indicating likely content destruction).

        User sees everything before committing. If the report looks
        wrong, they simply don't call `nora_generate` without
        `preview=true`.
        """
        from pathlib import Path as _P
        try:
            import claude_md_gen
            import db as _db_mod
        except Exception as e:
            return f"nora generate preview error: {e}"

        claude_md = cwd / "CLAUDE.md"
        existing = claude_md.read_text(encoding="utf-8", errors="replace") if claude_md.exists() else ""

        # Resolve project scope + pull intelligence (same path as real run).
        canonical = _db_mod.canonicalize_project(str(cwd))
        conn = _db_mod.get_conn()
        try:
            intel = claude_md_gen.pull_intelligence(conn, project=str(cwd))
            index = claude_md_gen._build_index(conn, project=str(cwd))
        finally:
            conn.close()

        nora_content = claude_md_gen.generate_claude_md(
            intel, project_name=cwd.name, token_budget=1200, index=index,
        )
        nora_block = f"{claude_md_gen.NORA_MARKER_START}\n{nora_content}\n{claude_md_gen.NORA_MARKER_END}\n"

        had_markers = claude_md_gen.NORA_MARKER_START in existing
        had_file = bool(existing.strip())
        would_proposed = (
            claude_md_gen.splice_nora_block(existing, nora_block)
            if had_file
            else (claude_md_gen._detect_stack_scaffold(cwd).rstrip() + "\n\n" + nora_block)
        )

        # Compute user-territory bytes before vs after.
        def _user_bytes(text: str) -> int:
            s = text.find(claude_md_gen.NORA_MARKER_START)
            e = text.find(claude_md_gen.NORA_MARKER_END)
            if s < 0 or e < s:
                return len(text.strip())
            return len(text[:s].strip()) + len(text[e + len(claude_md_gen.NORA_MARKER_END):].strip())

        before_user_bytes = _user_bytes(existing)
        after_user_bytes = _user_bytes(would_proposed)

        # v2.2.11: distinguish orphan-cleanup shrink from user content
        # loss. If existing has a Nora-signature orphan header outside
        # the marker block, some of the "shrink" is intentional cleanup,
        # not lost user work.
        orphan_bytes = 0
        try:
            orphan_match = claude_md_gen._NORA_ORPHAN_HEADER_RE.search(existing)
            if orphan_match:
                orphan_bytes = len(orphan_match.group(0))
        except Exception:
            pass

        shrink_ratio = 0.0
        if before_user_bytes > 0:
            shrink_ratio = 1.0 - (after_user_bytes / before_user_bytes)

        # Genuine content loss (not explained by orphan cleanup).
        genuine_loss_bytes = max(
            0, (before_user_bytes - after_user_bytes) - orphan_bytes
        )
        destructive = (
            before_user_bytes >= 500
            and genuine_loss_bytes > before_user_bytes * 0.5
        )

        lines = [f"🟢 Nora · Kernora — `nora generate` PREVIEW for `{cwd.name}`"]
        lines.append("(no files modified)")
        lines.append("")

        if not had_file:
            lines.append("**State:** CLAUDE.md is absent — would be CREATED")
        elif had_markers:
            lines.append("**State:** CLAUDE.md has Nora marker block — would RE-ENHANCE "
                         "(replace content inside markers, preserve everything outside)")
        else:
            lines.append("**State:** CLAUDE.md exists WITHOUT Nora markers — would APPEND "
                         "Nora block at bottom; narrow-strip any orphan `# Nora Intelligence "
                         "Injection` header line.")

        lines.append("")
        lines.append("**Proposed changes:**")
        lines.append(f"  • Nora block to add: {len(nora_block)} bytes ({len(nora_block.splitlines())} lines)")
        lines.append(f"  • Verified facts to surface: {len(intel.get('verified_patterns', []) or [])}")
        lines.append(f"  • Verified decisions to surface: {len(intel.get('verified_decisions', []) or [])}")
        lines.append(f"  • User content bytes before: {before_user_bytes}")
        lines.append(f"  • User content bytes after:  {after_user_bytes}")
        if before_user_bytes > 0:
            total_delta = after_user_bytes - before_user_bytes
            if orphan_bytes > 0 and total_delta < 0:
                lines.append(
                    f"  • Net change to user content: {total_delta:+d} bytes "
                    f"({shrink_ratio*100:+.1f}%) — **intentional orphan cleanup** "
                    f"({orphan_bytes} bytes of stale `# Nora Intelligence Injection` "
                    f"header + subtitle removed). Genuine user content loss: "
                    f"{genuine_loss_bytes} bytes."
                )
            elif total_delta < 0:
                lines.append(
                    f"  • ⚠ Net change to user content: {total_delta:+d} bytes "
                    f"({shrink_ratio*100:+.1f}%) — no orphan header detected; this "
                    f"is genuine content loss. Review below carefully before "
                    f"committing."
                )
            else:
                lines.append(
                    f"  • Net change to user content: {total_delta:+d} bytes "
                    f"({shrink_ratio*100:+.1f}% — no loss)"
                )
        lines.append("")

        if destructive:
            lines.append(
                "🛑 **SAFETY ABORT** — this write would destroy more than 50% "
                "of your user content. Nora would **refuse to write** even "
                "without preview mode. Likely cause: your CLAUDE.md starts with "
                "`# Nora Intelligence Injection` but everything below is hand-"
                "authored content that looks like an orphan to Nora's heuristic. "
                "Options:"
            )
            lines.append("  1. Remove the `# Nora Intelligence Injection` header line manually, then re-run preview.")
            lines.append("  2. Add `<!-- nora:auto-start -->` / `<!-- nora:auto-end -->` markers yourself around a small placeholder section — Nora will then splice cleanly.")
            lines.append("  3. Accept the partial write by confirming manually (no auto-bypass).")
            lines.append("")

        # Show a preview of the proposed content (first 30 lines + last 20).
        proposed_lines = would_proposed.splitlines()
        if len(proposed_lines) > 50:
            preview_text = "\n".join(
                proposed_lines[:30] + ["...", f"[{len(proposed_lines) - 50} lines omitted]", "..."] + proposed_lines[-20:]
            )
        else:
            preview_text = would_proposed
        lines.append("**Proposed file content (preview):**")
        lines.append("```markdown")
        lines.append(preview_text)
        lines.append("```")
        lines.append("")

        lines.append(
            "_To commit this proposal, call `nora_generate` again without `preview=true`. "
            "Nora will write atomically (tempfile + os.replace); your existing CLAUDE.md "
            "is never truncated in place. If the SAFETY ABORT fired, the non-preview "
            "call will also refuse to write._"
        )
        return "\n".join(lines)

    def _re_queried_check(self, conn, session_id: str, fact_type: str) -> bool:
        """Return True if this session already queried this fact_type within the last 5 min.

        Negative signal for Thompson Sampling: re-querying the same type quickly
        means the first retrieval wasn't helpful. Tier 1 implicit feedback (batch-044).
        """
        if not session_id:
            return False
        try:
            row = conn.execute("""
                SELECT COUNT(*) FROM context_retrievals
                WHERE session_id = ? AND fact_type = ?
                  AND created_at >= datetime('now', '-5 minutes')
            """, (session_id, fact_type)).fetchone()
            return (row[0] if row else 0) > 0
        except Exception:
            return False

    def _resolve_factbook_name(self, name: str) -> str | None:
        """Given a display name or kp_id, return the kp_id. Returns None if not found.
        Auto-slugifies spaces so 'python style' → looks up 'Python Style' by title.
        AI review W2 fix: echoes resolved slug back in all responses."""
        try:
            from factbook_git import validate_kp_id
            from db import factbook_find_by_name

            # If it's already a valid kp_id slug, use it directly
            if validate_kp_id(name):
                conn = self._connect_db()
                try:
                    row = conn.execute(
                        "SELECT kp_id FROM kp_factbooks WHERE kp_id = ? AND archived = 0",
                        (name,)
                    ).fetchone()
                    if row:
                        return row["kp_id"]
                finally:
                    conn.close()

            # Otherwise look up by display title
            result = factbook_find_by_name(name)
            return result["kp_id"] if result else None
        except Exception:
            return None

    def _get_default_factbook_for_project(self, project: str) -> tuple[str, str]:
        """Get or create default factbook for a project. Returns (name, kp_id)."""
        from db import factbook_create

        default_name = f"{project}-learnings"

        # Check if exists
        kp_id = self._resolve_factbook_name(default_name)
        if kp_id:
            return default_name, kp_id  # Reuse existing

        # Create new default factbook
        created = factbook_create(
            name=default_name,
            scope="project",
            description=f"Engineering learnings from {project} sessions"
        )
        return default_name, created['kp_id']

    def _infer_project_from_cwd(self) -> str | None:
        """Detect the current project from cwd via db.canonical_project — THE
        single source of truth (basename-first, CoE 2026-04-23).

        DUP-fix 2026-06-01: this previously reimplemented resolution git-remote-FIRST,
        contradicting canonical_project's basename-first contract. For any repo whose
        GitHub name != local dir name, facts written under canonical_project's name
        (at store_session) were invisible to retrieval scoped via this reader's
        remote-name — a grounding-scope mismatch. Delegating fixes it; the common
        case (dir name == repo name) is unchanged.
        """
        import os
        try:
            from db import canonical_project
            return canonical_project(os.getcwd()) or None
        except Exception:
            return None

    def _format_kp_git_note(commit: str, indent: str = "  ") -> str:
        """Format the git-commit line for factbook-kp operations.

        write_and_commit_async commits to ~/.kernora/factbooks/ — a SEPARATE
        git repo from the project repo.  The SHA printed here is valid only in
        that repo; running `git cat-file -t <sha>` in the project repo will
        return 'not a valid object name' — that is expected, NOT a bug.

        Three return cases from write_and_commit_async:
          - 7+ hex chars  → real short SHA in the kp-factbooks repo
          - "nothing-to-commit" → no change (idempotent double-call)
          - "committed"    → git commit landed but SHA regex missed; warn
        """
        import re as _re
        _SHA_RE = _re.compile(r'^[0-9a-f]{7,}$')
        if _SHA_RE.match(commit):
            return (
                f"{indent}Git (kp-factbooks repo): committed ({commit})\n"
                f"{indent}  Note: this SHA lives in ~/.kernora/factbooks/.git, "
                f"not the project repo.\n"
            )
        elif commit == "nothing-to-commit":
            return f"{indent}Git: no change to commit (factbook already up to date)\n"
        else:
            # Sentinel "committed" or any unexpected string — commit landed but
            # SHA was not captured; log loudly per  (no silent success strings).
            return (
                f"{indent}Git (kp-factbooks repo): commit landed but SHA not captured "
                f"(got {commit!r}). DB write succeeded.\n"
            )

    def _pe_state_path() -> Path:
        """Path to ~/.kernora/pe_panels.jsonl, honoring KERNORA_HOME for tests."""
        home = Path(os.environ.get("KERNORA_HOME") or (Path.home() / ".kernora"))
        return home / "pe_panels.jsonl"

    def _pe_review_start(self, fact_ids: list, panel_override: list | None = None,
                         session_type: str | None = None,
                         panel_kind: str = "audit",
                         kp_id: str | None = None) -> str:
        """nora_pe_review_start: build per-role prompts + persist start event.

        Reuses capture.DOMAIN_PANEL_MAP, capture.pick_pe_panel, and
        capture._REVIEWER_PROMPT (lf003). All LLM work runs in the IDE (lf204)
        — Nora only returns prompts and aggregates results.

        panel_kind: "audit" (default; reads from patterns table — used by
        legacy callers AND nora_factbook_audit) or "promote" (reads from
        pending_facts — used by nora_factbook_promote(action='review')).
        Default is "audit" for backward compat with pre-2026-04-25 callers
        that always passed patterns IDs. Per PE round-2 B1-α fix.
        kp_id: factbook target for auto-promote when panel_kind="promote";
        threaded through to finalize via the start event in pe_panels.jsonl.
        """
        try:
            from capture import (
                pick_pe_panel as _pick,
                _REVIEWER_PROMPT as _PROMPT,
                DOMAIN_PANEL_MAP as _DPM,
            )
        except Exception as e:
            return json.dumps({"error": f"capture_unavailable:{e}"})

        if not isinstance(fact_ids, list) or not fact_ids:
            return json.dumps({"error": "no_fact_ids"})

        # Load fact text from patterns table.
        facts: list[dict] = []
        try:
            from db import get_conn  # type: ignore
            conn = get_conn()
        except Exception as e:
            return json.dumps({"error": f"db_unavailable:{e}"})
        if conn is None:
            return json.dumps({"error": "db_unavailable"})
        # PE round-2 BLOCKER B1-α fix: route the SELECT by panel_kind.
        # audit-path (default; legacy + nora_factbook_audit): fact_ids come
        # from patterns.id (already promoted active facts).
        # promote-path (nora_factbook_promote(action="review")): fact_ids
        # come from pending_facts.id (capture queue).
        # Reading the wrong table silently returns no_facts_found.
        if (panel_kind or "audit") == "promote":
            select_sql = ("SELECT id, fact_text, fact_type FROM pending_facts "
                          "WHERE id=? AND status='pending'")
        else:
            select_sql = "SELECT id, pattern, fact_type FROM patterns WHERE id=?"
        missing_ids: list = []
        try:
            for fid in fact_ids:
                try:
                    row = conn.execute(select_sql, (int(fid),)).fetchone()
                except Exception:
                    row = None
                if row:
                    facts.append({
                        "id": row[0],
                        "fact_text": row[1] or "",
                        "fact_type": row[2] or "pattern",
                    })
                else:
                    missing_ids.append(int(fid))
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if not facts:
            return json.dumps({
                "error": "no_facts_found",
                "fact_ids": list(fact_ids),
                "panel_kind": panel_kind or "audit",
                "table_consulted": "pending_facts" if (panel_kind or "audit") == "promote" else "patterns",
            })

        # Pick panel — explicit override wins; else session_type → DOMAIN_PANEL_MAP.
        if panel_override and isinstance(panel_override, list) and len(panel_override) == 3:
            panel = tuple(str(r) for r in panel_override)
        else:
            panel = _pick(session_type)

        panel_id = os.urandom(8).hex()
        # Build per-role prompts using the same template Dreamer uses.
        facts_compact = [
            {"text": f["fact_text"], "type": f["fact_type"]} for f in facts
        ]
        prompts: dict[str, str] = {}
        for role in panel:
            try:
                prompts[role] = _PROMPT.format(
                    role=role,
                    facts_json=json.dumps(facts_compact, indent=2),
                )
            except Exception as e:
                prompts[role] = f"[prompt-render-error:{e}]"

        # Persist start event via nora_jsonl._append (lf002 / lf105).
        try:
            from nora_jsonl import _append as _jsonl_append
            _jsonl_append(self._pe_state_path(), {
                "event":      "start",
                "panel_id":   panel_id,
                "panel":      list(panel),
                "fact_ids":   [f["id"] for f in facts],
                "session_type": session_type or "",
                "panel_kind": panel_kind or "audit",
                "kp_id":      kp_id or "",
                "ts":         int(time.time()),
            })
        except Exception as e:
            return json.dumps({"error": f"jsonl_append_failed:{e}"})

        return json.dumps({
            "panel_id":   panel_id,
            "panel":      list(panel),
            "prompts":    prompts,
            "n_facts":    len(facts),
            "fact_ids":   [f["id"] for f in facts],
            "panel_kind": panel_kind or "audit",
            "kp_id":      kp_id or "",
        })

    def _pe_review_submit(self, panel_id: str, role: str,
                          scores: list, vetoes: list | None = None) -> str:
        """nora_pe_review_submit: append one reviewer's scores + vetoes."""
        if not panel_id or not role:
            return json.dumps({"error": "panel_id_and_role_required"})
        if not isinstance(scores, list):
            return json.dumps({"error": "scores_not_list"})
        # Coerce scores to ints; tolerate strings.
        try:
            scores_i = [int(s) for s in scores]
        except Exception:
            return json.dumps({"error": "scores_not_int"})
        v = vetoes if isinstance(vetoes, list) else []
        try:
            from nora_jsonl import _append as _jsonl_append
            _jsonl_append(self._pe_state_path(), {
                "event":    "submit",
                "panel_id": panel_id,
                "role":     str(role),
                "scores":   scores_i,
                "vetoes":   v,
                "ts":       int(time.time()),
            })
        except Exception as e:
            return json.dumps({"error": f"jsonl_append_failed:{e}"})
        return json.dumps({
            "ok":               True,
            "panel_id":         panel_id,
            "role":             role,
            "received_scores":  len(scores_i),
            "received_vetoes":  len(v),
        })

    def _pe_review_finalize(self, panel_id: str) -> str:
        """nora_pe_review_finalize: aggregate + apply pass-rule from run_pe_panel.

        Pass-rule (mirrored from capture.run_pe_panel lines ~214-225): every
        reviewer scored >= 1 AND no veto fired for that fact. Vetoed facts
        cannot pass.
        """
        if not panel_id:
            return json.dumps({"error": "panel_id_required"})
        path = self._pe_state_path()
        if not path.exists():
            return json.dumps({"error": "no_panel_state"})

        panel_state: dict | None = None
        subs: dict[str, dict] = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("panel_id") != panel_id:
                    continue
                if r.get("event") == "start":
                    panel_state = r
                elif r.get("event") == "submit":
                    subs[str(r.get("role"))] = r  # last-write-wins
        except Exception as e:
            return json.dumps({"error": f"jsonl_read_failed:{e}"})

        if not panel_state:
            return json.dumps({"error": "panel_not_found", "panel_id": panel_id})

        panel = list(panel_state.get("panel") or [])
        fact_ids = list(panel_state.get("fact_ids") or [])
        missing = [r for r in panel if r not in subs]
        if missing:
            return json.dumps({
                "error":    "incomplete",
                "panel_id": panel_id,
                "missing":  missing,
            })

        per_fact = []
        for i, fid in enumerate(fact_ids):
            scores = {}
            for role in panel:
                role_scores = subs[role].get("scores") or []
                scores[role] = int(role_scores[i]) if i < len(role_scores) else 1
            vetoes = []
            for role in panel:
                for v in (subs[role].get("vetoes") or []):
                    if isinstance(v, dict) and int(v.get("index", -1)) == i:
                        vetoes.append({
                            "reviewer": role,
                            "reason":   str(v.get("reason", ""))[:200],
                        })
            passed = all(s >= 1 for s in scores.values()) and not vetoes
            per_fact.append({
                "fact_id": fid,
                "scores":  scores,
                "vetoes":  vetoes,
                "passed":  passed,
            })

        # Auto-promote-on-finalize (PE round-3 H4 + B1 fix 2026-04-25):
        # Only fire when panel_kind=="promote" — audit-context finalize must
        # NOT promote (those facts are already active; promoting would
        # double-stamp). The auto-promote uses _promote_pending_to_factbook
        # which routes through factbook_add_fact (correct factbook_id stamping)
        # rather than capture.accept_pending (which sets factbook_id NULL and
        # would silently miss nora_factbook_view).
        panel_kind = panel_state.get("panel_kind") or "audit"
        kp_id = panel_state.get("kp_id") or None
        auto_promoted: list[int] = []
        auto_promote_errors: list[dict] = []
        # Stage-4: track pending_id → promoted factlet_id for emit step below.
        _promote_fact_id_map: dict[int, int | None] = {}
        if panel_kind == "promote" and kp_id:
            for entry in per_fact:
                if not entry.get("passed"):
                    continue
                pending_id = int(entry["fact_id"])
                res = self._promote_pending_to_factbook(
                    pending_id=pending_id, kp_id=kp_id,
                    created_by="auto_promote_after_panel",
                )
                if res.get("ok"):
                    auto_promoted.append(pending_id)
                    _promote_fact_id_map[pending_id] = res.get("fact_id")
                else:
                    auto_promote_errors.append({
                        "pending_id": pending_id,
                        "reason": res.get("reason", "unknown"),
                    })

        # Stage-4 verifier-corpus tap (§10-M9): emit AFTER auto-promote block,
        # for ALL panel_kind (promote AND audit), best-effort.
        try:
            from db import _emit_verification_label as _vl_pe, get_conn as _vl_pe_gc
            _vl_pe_conn = _vl_pe_gc()
            try:
                for _pf_entry in per_fact:
                    try:
                        _pf_raw_event = json.dumps({
                            "scores": _pf_entry.get("scores"),
                            "vetoes": _pf_entry.get("vetoes"),
                            "passed": _pf_entry.get("passed"),
                        })
                        _pf_passed = bool(_pf_entry.get("passed"))
                        _pf_verdict = "verified" if _pf_passed else "rejected"
                        _pf_label = "entails" if _pf_passed else "contradicts"
                        # For promote panels, prefer the factlet id from the promote result.
                        _pf_pending_id = int(_pf_entry["fact_id"])
                        if panel_kind == "promote":
                            _pf_factlet_id = _promote_fact_id_map.get(_pf_pending_id, _pf_pending_id)
                        else:
                            _pf_factlet_id = _pf_pending_id
                        _vl_pe(
                            _vl_pe_conn,
                            fact_id=_pf_factlet_id,
                            factlet_body=None,
                            verdict=_pf_verdict,
                            label=_pf_label,
                            label_source="pe_panel_gold",
                            confidence=0.95,
                            event_source="pe_review_finalize",
                            raw_event=_pf_raw_event,
                        )
                    except Exception as _pf_e:
                        print(
                            f"[kernora] verification_label emit failed (best-effort, not blocking): "
                            f"pe_review_finalize entry={_pf_entry.get('fact_id')}: {_pf_e}"
                        )
                _vl_pe_conn.commit()
            finally:
                _vl_pe_conn.close()
        except Exception as _vl_pe_outer_e:
            print(
                f"[kernora] verification_label emit failed (best-effort, not blocking): "
                f"pe_review_finalize panel_id={panel_id}: {_vl_pe_outer_e}"
            )

        result = {
            "panel_id":   panel_id,
            "panel":      panel,
            "panel_kind": panel_kind,
            "per_fact":   per_fact,
        }
        if panel_kind == "promote":
            result["auto_promoted"] = auto_promoted
            result["auto_promote_errors"] = auto_promote_errors
        return json.dumps(result)

    def _promote_pending_to_factbook(self, pending_id: int, kp_id: str,
                                      edited_text: str | None = None,
                                      override_veto: bool = False,
                                      created_by: str = "auto_promote") -> dict:
        """Promote one pending fact into a NAMED factbook via the canonical
        factbook_add_fact write path (correct factbook_id stamping). Per
        PE round-3 BLOCKER B1 fix 2026-04-25.

        Why this exists: capture.accept_pending writes to patterns with
        factbook_id=NULL, which means nora_factbook_view (filters by
        factbook_id) would never see auto-promoted facts. This adapter
        bridges the pending → factbook write path correctly.

        Returns {ok: bool, fact_id: int|None, reason: str}.
        """
        if not kp_id:
            return {"ok": False, "fact_id": None, "reason": "kp_id_required"}
        try:
            from db import get_conn, factbook_add_fact
            import sqlite3 as _sql
        except Exception as e:
            return {"ok": False, "fact_id": None, "reason": f"import_err:{e}"}
        conn = get_conn()
        if conn is None:
            return {"ok": False, "fact_id": None, "reason": "db_unavailable"}
        try:
            conn.row_factory = _sql.Row
            row = conn.execute(
                "SELECT id, fact_text, fact_type, confidence, project, session_id, "
                "pe_vetoes, status FROM pending_facts WHERE id = ?",
                (pending_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "fact_id": None, "reason": "pending_not_found"}
            if row["status"] != "pending":
                return {"ok": False, "fact_id": None,
                        "reason": f"already_reviewed:{row['status']}"}
            is_vetoed = bool(row["pe_vetoes"]) and row["pe_vetoes"] != "[]"
            if is_vetoed and not override_veto:
                return {"ok": False, "fact_id": None,
                        "reason": "vetoed_facts_need_explicit_override"}
            text = (edited_text or row["fact_text"] or "").strip()
            if len(text) < 10:
                return {"ok": False, "fact_id": None, "reason": "text_too_short"}
            # Canonical factbook write — stamps factbook_id correctly.
            try:
                add_res = factbook_add_fact(
                    kp_id=kp_id,
                    fact_text=text,
                    fact_type=(row["fact_type"] or "pattern"),
                    confidence=float(row["confidence"] or 0.7),
                    session_id=row["session_id"],
                    created_by=created_by,
                )
            except ValueError as ve:
                return {"ok": False, "fact_id": None,
                        "reason": f"validation_failed:{ve}"}
            new_fact_id = add_res.get("fact_id") if isinstance(add_res, dict) else None
            # Mark the pending row accepted so it doesn't show up in
            # capture_pending again.
            try:
                conn.execute(
                    "UPDATE pending_facts SET status = 'approved' WHERE id = ?",
                    (pending_id,),
                )
                conn.commit()
            except Exception:
                pass
            return {"ok": True, "fact_id": new_fact_id, "reason": "promoted",
                    "kp_id": kp_id}
        except Exception as e:
            return {"ok": False, "fact_id": None, "reason": f"db_err:{e}"}
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _capture_pending(self, batch_id: str | None = None) -> str:
        """List the pending review queue."""
        import json as _j
        from pathlib import Path as _P
        try:
            import sys as _s
            _s.path.insert(0, str(_P.home() / ".kernora" / "app"))
            import capture as _cap  # type: ignore
        except Exception as e:
            return f"capture module unavailable: {e}"
        rows = _cap.list_pending(limit=50, batch_id=batch_id)
        return _j.dumps({"count": len(rows), "items": rows}, indent=2, default=str)

    def _capture_reject(self, pending_id: int, reason: str = "") -> str:
        import json as _j
        from pathlib import Path as _P
        try:
            import sys as _s
            _s.path.insert(0, str(_P.home() / ".kernora" / "app"))
            import capture as _cap  # type: ignore
        except Exception as e:
            return f"capture module unavailable: {e}"
        res = _cap.reject_pending(pending_id, reason=reason)
        return _j.dumps(res, indent=2)

    def _retire_fact(self, fact_id: int, reason: str = "user",
                     replaced_by_fact_id: int | None = None,
                     note: str = "") -> str:
        import json as _j
        from pathlib import Path as _P
        try:
            import sys as _s
            _s.path.insert(0, str(_P.home() / ".kernora" / "app"))
            import capture as _cap  # type: ignore
        except Exception as e:
            return f"capture module unavailable: {e}"
        res = _cap.retire_fact(fact_id, reason=reason, triggered_by="user",
                                 replaced_by_fact_id=replaced_by_fact_id, note=note)
        return _j.dumps(res, indent=2)


def main():
    """Entry point."""
    import asyncio

    server = NoraServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
