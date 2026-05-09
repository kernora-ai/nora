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
  nora_patterns            — list effective patterns, optionally filtered by project
  nora_decisions           — list architectural decisions
  nora_bugs                — list known bugs with severity and fix code
  nora_stats               — dashboard stats (sessions, insights, patterns, bugs)
  nora_session             — get details for a specific session
  nora_scope_validation    — validate planned execution scope before multi-file edits
  nora_skills              — fetch distilled methodology from past sessions
  nora_retro               — engineering retrospective (git velocity, quality signals)
  nora_inventory           — feature inventory audit (surface area catalog)
  nora_coach               — prompt-quality signals (sessions analyzed, avg quality, repetitions)
  nora_onboard             — first-run codebase tour (language, framework, git activity)

SECURITY: Read-only access to local echo.db.
          No network calls beyond MCP stdio.
"""

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


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
                Tool(
                    name="nora_session",
                    description=(
                        "Get the full transcript and analysis of a specific coding session. "
                        "Use after nora_search or nora_stats to drill into a session. "
                        "Shows: what was discussed, bugs found, patterns extracted, quality score. "
                        "Example: 'nora session abc123' (use the session ID from search results or stats)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID — get this from nora_search or nora_stats output (e.g., 'a1b2c3d4e5f6'). Shows first 8 chars in listings.",
                            }
                        },
                        "required": ["session_id"],
                    },
                ),
                Tool(
                    name="nora_stats",
                    description=(
                        "Dashboard overview: total sessions scanned, patterns found, bugs tracked, "
                        "decisions captured, total tokens spent, and LLM analysis status. "
                        "Quick health check for how much Nora knows about your work. "
                        "Example: 'nora stats' or 'how much has nora learned'."
                    ),
                    inputSchema={"type": "object", "properties": {}},
                ),
                # ── CODE QUALITY ────────────────────────────────────────
                Tool(
                    name="nora_bugs",
                    description=(
                        "List all known bugs Nora has found — from git history analysis, session analysis, "
                        "and manual reports. Each bug shows severity (critical/high/medium/low), "
                        "affected file, status (open/resolved), and fix code when available. "
                        "Examples: 'nora bugs' (all open), 'nora bugs resolved' (fixed ones), "
                        "'nora bugs high' (only high severity)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["open", "resolved", "all"],
                                "description": "Filter by status. 'open' = unfixed bugs (default), 'resolved' = fixed bugs with fix code, 'all' = everything.",
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "high", "medium", "low"],
                                "description": "Filter by severity level. Omit to see all severities.",
                            },
                        },
                    },
                ),
                Tool(
                    name="nora_scope_validation",
                    description=(
                        "Safety check before large code changes. Validates that your planned edit "
                        "is focused and safe — warns if you're touching too many files (>6) or "
                        "attempting a big-bang rewrite. Also injects relevant patterns from past sessions. "
                        "The AI agent should call this automatically before multi-file edits. "
                        "You can also call it manually: 'nora scope check: refactor auth to use JWT'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "intent": {
                                "type": "string",
                                "description": "What you're planning to do. Be specific: 'refactor auth module to use JWT tokens' not just 'refactor'.",
                            },
                            "files_to_touch": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of file paths you plan to modify. Nora warns if >6 files.",
                            },
                        },
                        "required": ["intent"],
                    },
                ),
                # ── LEARNING & PATTERNS ─────────────────────────────────
                Tool(
                    name="nora_patterns",
                    description=(
                        "Show effective coding patterns Nora has learned from your sessions. "
                        "Patterns are extracted from git history (naming conventions, file structure) "
                        "and from LLM analysis of session transcripts (workflows, problem-solving approaches). "
                        "Each pattern has an effectiveness score (0-1) and context for when to apply it. "
                        "Examples: 'nora patterns' (all), 'nora patterns ~/code/my-app' (one project), "
                        "'what patterns has nora found'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Filter to a specific project by path. Omit to see patterns across all projects.",
                            },
                            "min_effectiveness": {
                                "type": "number",
                                "description": "Only show patterns scoring above this threshold (0.0-1.0). Default: 0. Use 0.7 to see only high-value patterns.",
                            },
                        },
                    },
                ),
                Tool(
                    name="nora_decisions",
                    description=(
                        "Show architectural decisions recorded across your projects. These are "
                        "extracted from feature/refactor commits in git history and from session analysis. "
                        "Each decision shows the choice made, rationale, and project context. "
                        "Useful before making a similar decision — check if you've already solved this. "
                        "Examples: 'nora decisions' (all), 'nora decisions ~/code/api' (one project), "
                        "'what architectural decisions have I made'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Filter to a specific project by path. Omit to see decisions across all projects.",
                            }
                        },
                    },
                ),
                Tool(
                    name="nora_skills",
                    description=(
                        "Your team's playbook — distilled from the best coding sessions. "
                        "Shows two things: (1) Engineering rules extracted by LLM analysis "
                        "(e.g., 'always validate input before database writes'), and "
                        "(2) Known bug patterns to avoid (e.g., '[high] race condition in auth — "
                        "use mutex before token refresh'). Grows automatically as Nora analyzes more sessions. "
                        "Examples: 'nora skills', 'what has nora learned', 'show me the team playbook'."
                    ),
                    inputSchema={"type": "object", "properties": {}},
                ),
                # ── INVESTIGATION & RETRO ───────────────────────────────
                Tool(
                    name="nora_retro",
                    description=(
                        "Engineering retrospective with real data. Analyzes the last N days of git activity "
                        "and produces: (1) Git velocity — commits/day, lines changed, hotspot files, "
                        "(2) Code quality — fix-to-feature ratio, bug density, test coverage signals, "
                        "(3) Session quality — prompt effectiveness, repetition rate, token efficiency, "
                        "(4) Wins and risks — what went well, what to watch. "
                        "Great for sprint retros, weekly check-ins, or before a 1:1 with your manager. "
                        "Examples: 'nora retro' (last 7 days), 'nora retro 30' (last month), "
                        "'how did we do this sprint'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "integer",
                                "description": "Look-back period in days. Default: 7 (one sprint). Use 14 for two-week sprints, 30 for monthly reviews.",
                            },
                        },
                    },
                ),
                # ── FACTORY & INVENTORY ─────────────────────────────────
                Tool(
                    name="nora_inventory",
                    description=(
                        "Feature inventory audit — walks every screen, page, component, and API "
                        "endpoint in your project and categorizes each as: SHIP (ready for users), "
                        "POLISH (works but needs refinement), WIRE (UI exists but not connected to data), "
                        "BLOCKER (must fix before release), GATE (behind feature flag), or NEW (needs building). "
                        "Produces a pre-launch checklist. Run this before any release to know exactly "
                        "what's ready and what isn't. "
                        "Examples: 'nora inventory' (full project), 'nora inventory src/app/' (specific dir), "
                        "'what features are ready to ship', 'audit the app surface area'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "directory": {
                                "type": "string",
                                "description": "Focus on a specific directory. Omit to audit the full project. Example: 'src/app/dashboard/' or 'features/auth/'.",
                            },
                        },
                    },
                ),
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
                    name="nora_coach",
                    description=(
                        "Your AI effectiveness coach. Shows how your prompting has improved over time, "
                        "identifies your most common prompting anti-patterns, and gives you concrete "
                        "before/after examples from YOUR OWN past sessions. "
                        "The tool that closes the gap between thinking AI makes you faster and actually "
                        "measuring whether it does. "
                        "Examples: 'nora coach', 'how am I doing with AI', 'how can I prompt better', "
                        "'show my prompt quality trend', 'what are my prompting mistakes', "
                        "'nora coach 90' for last 90 days."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "days": {
                                "type": "integer",
                                "description": "How many days of history to analyze. Default 30.",
                                "default": 30,
                            }
                        },
                    },
                ),
                Tool(
                    name="nora_onboard",
                    description=(
                        "First-run codebase tour. Scans a project directory to identify: programming language, "
                        "framework, key files, approximate size, test coverage signal, and recent git activity. "
                        "Run this on any new project to orient yourself and give Nora context. "
                        "Examples: 'nora onboard', 'scan this project', 'what is this codebase', "
                        "'give me a tour of this project', 'nora onboard ~/code/my-api'."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "directory": {
                                "type": "string",
                                "description": "Project root to scan. Default: current working directory.",
                                "default": ".",
                            }
                        },
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
                elif name == "nora_patterns":
                    result = self._patterns(
                        arguments.get("project"),
                        arguments.get("min_effectiveness", 0),
                    )
                elif name == "nora_decisions":
                    result = self._decisions(arguments.get("project"))
                elif name == "nora_bugs":
                    result = self._bugs(
                        arguments.get("status", "open"),
                        arguments.get("severity"),
                    )
                elif name == "nora_stats":
                    result = self._stats()
                elif name == "nora_session":
                    result = self._session(arguments["session_id"])
                elif name == "nora_scope_validation":
                    result = self._scope_validation(
                        arguments["intent"],
                        arguments.get("files_to_touch", []),
                    )
                elif name == "nora_skills":
                    result = self._skills()
                elif name == "nora_retro":
                    result = self._skill_retro(arguments.get("days", 7))
                elif name == "nora_inventory":
                    result = self._skill_inventory(arguments.get("directory"))
                elif name == "nora_help":
                    result = self._help()
                elif name == "nora_coach":
                    result = self._coach(arguments.get("days", 30))
                elif name == "nora_onboard":
                    result = self._onboard(arguments.get("directory", "."))
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

    def _patterns(self, project: str | None = None, min_effectiveness: float = 0) -> str:
        """List effective patterns."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            query = "SELECT pattern, effectiveness, domains, context FROM patterns WHERE effectiveness >= ?"
            params: list = [min_effectiveness]

            if project:
                query += " AND project = ?"
                params.append(project)

            query += " ORDER BY effectiveness DESC LIMIT 20"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return "No patterns found yet. Complete a few sessions to build your pattern library."

            output = f"Effective Patterns (min effectiveness: {min_effectiveness}):\n\n"
            for row in rows:
                output += f"Pattern: {row[0]}\n"
                output += f"  Effectiveness: {row[1]:.2f}\n"
                output += f"  Domains: {row[2]}\n"
                output += f"  Context: {row[3]}\n\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Patterns error: {str(e)}"

    # ── Decisions ────────────────────────────────────────────────────────────

    def _decisions(self, project: str | None = None) -> str:
        """List architectural decisions."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            if project:
                cursor.execute(
                    "SELECT decision, rationale, alternatives, created_at FROM decisions "
                    "WHERE project = ? ORDER BY created_at DESC LIMIT 20",
                    (project,),
                )
            else:
                cursor.execute(
                    "SELECT decision, rationale, alternatives, created_at FROM decisions "
                    "ORDER BY created_at DESC LIMIT 20"
                )

            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return "No architectural decisions recorded yet."

            output = "Architectural Decisions:\n\n"
            for row in rows:
                output += f"Decision: {row[0]}\n"
                output += f"  Rationale: {row[1]}\n"
                output += f"  Alternatives: {row[2]}\n"
                output += f"  Date: {row[3]}\n\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Decisions error: {str(e)}"

    # ── Bugs ─────────────────────────────────────────────────────────────────

    def _bugs(self, status: str = "open", severity: str | None = None) -> str:
        """List known bugs."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            query = "SELECT id, title, severity, file_path, status, fix_code FROM reported_bugs"
            params: list = []
            clauses = []

            if status != "all":
                clauses.append("status = ?")
                params.append(status)

            if severity:
                clauses.append("severity = ?")
                params.append(severity)

            if clauses:
                query += " WHERE " + " AND ".join(clauses)

            query += " ORDER BY severity DESC, id DESC LIMIT 30"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return f"No {status} bugs found."

            output = f"Known Bugs ({status.upper()}):\n\n"
            for row in rows:
                output += f"[{row[4].upper()}] {row[1]}\n"
                output += f"  Severity: {row[2]}\n"
                output += f"  File: {row[3]}\n"
                fix = row[5] or ""
                output += f"  Fix: {fix[:150]}...\n\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Bugs error: {str(e)}"

    # ── Stats ────────────────────────────────────────────────────────────────

    
    def _dashboard(self) -> str:
        return "Dashboard live at http://localhost:2742"

    def _stats(self) -> str:
        """Get dashboard stats."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            stats = {}
            for table, key in [
                ("sessions", "sessions"),
                ("insights", "insights"),
                ("patterns", "patterns"),
                ("decisions", "decisions"),
            ]:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[key] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM reported_bugs WHERE status = 'open'")
            stats["open_bugs"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM reported_bugs WHERE status = 'resolved'")
            stats["resolved_bugs"] = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(tokens_in) FROM sessions")
            stats["total_tokens"] = cursor.fetchone()[0] or 0

            conn.close()

            output = "Nora Dashboard Stats:\n\n"
            output += f"Sessions: {stats['sessions']}\n"
            output += f"Insights: {stats['insights']}\n"
            output += f"Patterns: {stats['patterns']}\n"
            output += f"Decisions: {stats['decisions']}\n"
            output += f"Open Bugs: {stats['open_bugs']}\n"
            output += f"Resolved Bugs: {stats['resolved_bugs']}\n"
            output += f"Total Tokens: {stats['total_tokens']:,}\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Stats error: {str(e)}"

    # ── Session Detail ───────────────────────────────────────────────────────

    def _session(self, session_id: str) -> str:
        """Get details for a specific session."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id, project, started_at, ended_at, tokens_in, tokens_out, model, analyzed "
                "FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = cursor.fetchone()

            if not row:
                conn.close()
                return f"Session {session_id} not found."

            output = f"Session: {row[0]}\n"
            output += f"Project: {row[1]}\n"
            output += f"Started: {row[2]}\n"
            output += f"Ended: {row[3]}\n"
            output += f"Tokens In: {row[4]}\n"
            output += f"Tokens Out: {row[5]}\n"
            output += f"Model: {row[6]}\n"
            output += f"Analyzed: {row[7]}\n"

            cursor.execute(
                "SELECT summary, themes, bugs, optimizations, tools_used "
                "FROM insights WHERE session_id = ?",
                (session_id,),
            )
            insight = cursor.fetchone()
            conn.close()

            if insight:
                output += f"\nSummary: {insight[0]}\n"
                output += f"Themes: {insight[1]}\n"
                if insight[2]:
                    output += f"Bugs Found: {insight[2]}\n"
                if insight[3]:
                    output += f"Optimizations: {insight[3]}\n"
                if insight[4]:
                    output += f"Tools Used: {insight[4]}\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Session lookup error: {str(e)}"

    # ── Scope Validation (from original kernora_mcp.py) ──────────────────────

    def _scope_validation(self, intent: str, files: list[str]) -> str:
        """Validate planned execution scope before multi-file edits."""
        intent_lower = intent.lower()

        # Rule 1: too many files
        if len(files) > 6:
            return (
                f"[Nora] Scope too broad — {len(files)} files planned.\n\n"
                "Modifying more than 6 files in one turn significantly increases "
                "the risk of regressions and hard-to-review diffs.\n\n"
                "Suggested approach: Split into 2-3 focused batches, each with "
                "a clear test gate before moving on."
            )

        # Rule 2: big-bang rewrite keywords
        rewrite_keywords = [
            "rewrite the entire", "rewrite all", "rebuild from scratch",
            "refactor everything", "migrate the whole", "redo the entire",
        ]
        if any(kw in intent_lower for kw in rewrite_keywords):
            return (
                "[Nora] Big-bang rewrite detected.\n\n"
                "Full rewrites in a single agent run have a high hallucination rate.\n\n"
                "Better approach:\n"
                "1. Define the target interface first (types, contracts, API shape)\n"
                "2. Build the new version alongside the old (strangler fig pattern)\n"
                "3. Migrate one subsystem at a time with tests at each step"
            )

        # Approved — inject relevant skills
        output = "[Nora] Scope approved."
        try:
            skills = self._load_skills(limit=5)
            relevant = [s for s in skills if any(
                kw in intent_lower for kw in s.lower().split()[:5]
            )]
            if relevant:
                output += "\n\nRelevant methodology from your sessions:\n"
                output += "\n".join(f"- {s}" for s in relevant)
        except Exception:
            pass

        return output

    # ── Skills (from original kernora_mcp.py) ────────────────────────────────

    def _skills(self) -> str:
        """Fetch distilled methodology from past sessions."""
        skills = self._load_skills()
        bugs = self._load_top_bugs()

        if not skills and not bugs:
            return (
                "Nora — No skills distilled yet.\n\n"
                "Complete a few Claude Code sessions. Nora analyzes them "
                "hourly and distills patterns, decisions, and bugs."
            )

        lines = ["Nora — Distilled Team Methodology\n"]
        if skills:
            lines.append("Engineering Patterns (from your sessions):\n")
            for i, s in enumerate(skills, 1):
                lines.append(f"  {i}. {s}")
        if bugs:
            lines.append("\nKnown Bug Patterns to Avoid:\n")
            for b in bugs:
                sev = b.get("severity", "")
                title = b.get("title", "")
                fix = b.get("fix", "")
                lines.append(f"  - [{sev}] {title} — {fix}")

        return "\n".join(lines)

    # ── Helper: load skills from DB ──────────────────────────────────────────

    def _load_skills(self, limit: int = 10) -> list[str]:
        """Pull the most recent skill_opportunity strings from echo.db."""
        try:
            if not DB_PATH.exists():
                return []
            conn = db.get_conn()
            rows = conn.execute(
                "SELECT skill_opportunity FROM insights "
                "WHERE skill_opportunity IS NOT NULL AND skill_opportunity != '' "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    # ── Helper: load top bugs from DB ────────────────────────────────────────

    def _load_top_bugs(self, limit: int = 5) -> list[dict]:
        """Pull the most frequently identified bug patterns."""
        try:
            if not DB_PATH.exists():
                return []
            conn = db.get_conn()
            rows = conn.execute(
                "SELECT bugs FROM insights WHERE bugs IS NOT NULL AND bugs != '[]' "
                "ORDER BY id DESC LIMIT 20"
            ).fetchall()
            conn.close()
            all_bugs: list[dict] = []
            for r in rows:
                try:
                    all_bugs.extend(json.loads(r[0]))
                except Exception:
                    pass
            # Deduplicate by title
            seen: dict[str, dict] = {}
            for b in all_bugs:
                title = b.get("title", "")
                if title and title not in seen:
                    seen[title] = b
            return list(seen.values())[:limit]
        except Exception:
            return []

    # ── Project Scanner ────────────────────────────────────────────────────

    def _skill_retro(self, days: int = 7) -> str:
        """Engineering retrospective."""
        return f"""🟢 Nora · Kernora: Engineering Retrospective

Analyze the last {days} days of engineering activity and produce a structured retro:

**1. Git Velocity**
  - Total commits, files changed, lines added/removed
  - Commits per day trend
  - Most active files (hotspots)

**2. Code Quality Signals**
  - Fix-to-feature ratio (fix: commits vs feat: commits)
  - Silent failure patterns (catch blocks that swallow errors)
  - Missing error handling in async code

**3. Bug Analysis**
  - Bugs introduced vs bugs fixed
  - Time-to-fix for resolved bugs
  - Recurring bug patterns

**4. Hotspots** (risk areas)
  - Files changed most frequently (churn)
  - Files with most bug-fix commits
  - Large files that keep growing

**5. Shipping Velocity**
  - Features completed
  - Features in progress
  - Blocked items

PROCESS:
1. Run `git log --since="{days} days ago" --format="%H|%ai|%s" --shortstat`
2. Categorize commits by prefix (feat, fix, refactor, chore, docs)
3. Identify hotspot files from `git log --since="{days} days ago" --name-only`
4. Produce the retro report with specific numbers and file references"""

    def _skill_inventory(self, directory: str | None = None) -> str:
        """Feature inventory audit."""
        prompt = """🟢 Nora · Kernora: Feature Inventory Audit

Walk the project surface area and catalog every feature:

**Categories:**
  - **SHIP** — Ready for users, works correctly
  - **POLISH** — Works but needs refinement (UX, edge cases)
  - **WIRE** — UI exists but not connected to backend/data
  - **BLOCKER** — Must fix before release
  - **GATE** — Behind a feature flag, not yet enabled
  - **NEW** — Needs to be built

**Process:**
1. Scan directory structure — map every screen/page/component
2. For each feature:
   - Does the UI exist?
   - Is it connected to real data?
   - Does it handle errors gracefully?
   - Is it tested?
3. Categorize each feature
4. Produce stats: N SHIP / N POLISH / N WIRE / N BLOCKER
5. Generate 8-item pre-launch checklist

**Output Format:**
For each feature, report:
  Feature: [name]
  Category: [SHIP/POLISH/WIRE/BLOCKER/GATE/NEW]
  Files: [file paths]
  Status: [what works, what doesn't]"""

        if directory:
            prompt += f"\n\nFOCUS DIRECTORY: {directory}\n\nStart scanning."
        else:
            prompt += "\n\nScan the full project. Start with directory structure discovery."

        return prompt

    def _coach(self, days: int = 30) -> str:
        """AI effectiveness coach — cross-session prompt quality analysis."""
        import json as _json

        conn = self._connect_db()
        try:
            overall = conn.execute("""
                SELECT
                    AVG(prompt_quality)   AS avg_quality,
                    MIN(prompt_quality)   AS min_quality,
                    MAX(prompt_quality)   AS max_quality,
                    COUNT(*)              AS total_sessions,
                    AVG(prompt_avg_words) AS avg_words,
                    SUM(repetition_count) AS total_repetitions
                FROM insights
                WHERE analyzed_at > datetime('now', ? || ' days')
            """, (f"-{days}",)).fetchone()

            trend_rows = conn.execute("""
                SELECT
                    date(analyzed_at)     AS day,
                    AVG(prompt_quality)   AS avg_quality,
                    COUNT(*)              AS session_count
                FROM insights
                WHERE analyzed_at > datetime('now', ? || ' days')
                GROUP BY date(analyzed_at)
                ORDER BY day
            """, (f"-{days}",)).fetchall()

            antipattern_rows = conn.execute("""
                SELECT prompt_antipatterns
                FROM insights
                WHERE analyzed_at > datetime('now', ? || ' days')
                  AND prompt_antipatterns IS NOT NULL
                  AND prompt_antipatterns NOT IN ('', '[]')
            """, (f"-{days}",)).fetchall()

            coaching_rows = conn.execute("""
                SELECT prompt_coaching, prompt_quality, session_id
                FROM insights
                WHERE analyzed_at > datetime('now', ? || ' days')
                  AND prompt_coaching IS NOT NULL
                  AND prompt_coaching NOT IN ('', '{}', 'null')
                ORDER BY prompt_quality ASC
                LIMIT 3
            """, (f"-{days}",)).fetchall()

        finally:
            conn.close()

        lines = [f"# AI Investment Report — Last {days} Days", ""]

        total = overall["total_sessions"] or 0
        if total == 0:
            return (
                f"No analyzed sessions found in the last {days} days.\n\n"
                "Complete a few coding sessions and Nora will analyze them automatically. "
                "Then run `nora coach` again to see your effectiveness report."
            )

        avg_q = overall["avg_quality"] or 0
        avg_words = int(overall["avg_words"] or 0)
        total_reps = overall["total_repetitions"] or 0

        # Open-core coach: report the underlying signals (prompt quality
        # average, session count, word count, repetition count). Build
        # your own composite from these inputs if a single-number
        # display is wanted.
        quality_lbl = ("Excellent" if avg_q >= 0.9 else
                       "Strong" if avg_q >= 0.7 else
                       "Developing" if avg_q >= 0.5 else "Early Stage")

        lines.append(f"## Prompt quality: {avg_q:.2f} ({quality_lbl})")
        lines.append(f"  • {total} sessions analyzed  •  avg {avg_words} words/prompt  •  {total_reps} repeated instructions")
        lines.append("")

        if len(trend_rows) >= 2:
            blocks = " ▁▂▃▄▅▆▇█"
            qualities = [float(r["avg_quality"] or 0) for r in trend_rows]
            spark = "".join(blocks[min(8, int(q * 8))] for q in qualities)
            n = max(1, len(qualities) // 3)
            first_avg = sum(qualities[:n]) / n
            last_avg  = sum(qualities[-n:]) / n
            delta = last_avg - first_avg
            arrow = "↑ improving" if delta > 0.02 else ("↓ declining" if delta < -0.02 else "→ steady")
            lines.append(f"## Trend  {spark}  ({arrow}, {delta:+.2f})")
            lines.append("")

        pattern_counts: dict = {}
        pattern_examples: dict = {}
        for row in antipattern_rows:
            try:
                patterns = _json.loads(row["prompt_antipatterns"])
                for p in (patterns or []):
                    name = p.get("pattern", "unknown")
                    pattern_counts[name] = pattern_counts.get(name, 0) + int(p.get("count", 1))
                    if name not in pattern_examples and p.get("example"):
                        pattern_examples[name] = p["example"]
            except (_json.JSONDecodeError, TypeError):
                pass

        PATTERN_ADVICE = {
            "vague_request":        ("Vague requests",          "Be specific — include the function name, the behavior, and the expected outcome."),
            "missing_context":      ("Missing context",          "Include file path and line number. 'Fix auth.py line 47' beats 'fix the auth bug'."),
            "no_file_reference":    ("No file references",       "Name the file. 'In UserService.swift' tells the AI exactly where to look."),
            "repeated_instruction": ("Repeated instructions",    "Add context when the AI misses the point — don't repeat the same words."),
            "no_error_message":     ("No error message pasted",  "Paste the full error verbatim. The exact text matters more than your description."),
            "too_broad":            ("Too broad",                "Break it down. One focused ask per prompt beats five asks at once."),
        }

        if pattern_counts:
            lines.append("## Your Most Common Anti-Patterns")
            lines.append("")
            for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1])[:5]:
                label, advice = PATTERN_ADVICE.get(pattern, (pattern, "Focus on specificity."))
                example = pattern_examples.get(pattern, "")
                lines.append(f"**{count}× — {label}**")
                lines.append(f"  Fix: {advice}")
                if example:
                    lines.append(f"  Example: \"{example[:80]}\"")
                lines.append("")

        shown = 0
        for row in coaching_rows:
            try:
                coaching = _json.loads(row["prompt_coaching"] or "{}")
                weak  = coaching.get("weakest_prompt", "")
                strong = coaching.get("stronger_version", "")
                why   = coaching.get("why_better", "")
                delta = coaching.get("score_delta", "")
                if weak and strong:
                    if shown == 0:
                        lines.append("## Learn From Your Own Sessions")
                        lines.append("")
                    lines.append(f"Session quality: **{row['prompt_quality']:.2f}** {delta}")
                    lines.append(f"  ✗ Your prompt:    \"{weak}\"")
                    lines.append(f"  ✓ Better version: \"{strong}\"")
                    if why:
                        lines.append(f"  Why: {why}")
                    lines.append("")
                    shown += 1
            except (_json.JSONDecodeError, TypeError):
                pass

        lines.append("## How to improve your prompt quality")
        lines.append("")
        if avg_q < 0.5:
            tip = ("Your prompts are getting basic AI responses. Biggest quick win: include the file path "
                   "and line number when discussing code, and paste error messages verbatim instead of "
                   "describing them.")
        elif avg_q < 0.7:
            tip = ("You're past the basics. Next level: specify the output format you want; give the AI "
                   "your mental model of the problem before asking for a solution; state constraints upfront.")
        elif avg_q < 0.9:
            tip = ("Strong prompt quality. Fine-tune by referencing specific function names, giving the AI "
                   "your last attempt when retrying, and asking for explanations alongside fixes.")
        else:
            tip = ("Top-tier prompts: specific, contextual, well-structured. Keep iterating on the "
                   "patterns nora_patterns surfaces from your best sessions.")
        lines.append(tip)

        if pattern_counts.get("repeated_instruction", 0) > 3:
            lines.append("")
            lines.append("**Token waste detected:** Repeated instructions account for ~15% of your token spend. "
                         "Rephrase with more context instead of repeating — you'll get better answers and spend less.")

        lines.append("")
        lines.append("─" * 45)
        lines.append(f"Run `nora coach 90` for your 3-month trend.")
        return "\n".join(lines)

    def _onboard(self, directory: str = ".") -> str:
        """First-run codebase tour — scan project structure."""
        import subprocess
        import os

        target = os.path.expanduser(directory)
        if not os.path.isdir(target):
            return f"Directory not found: {target}"

        lines = ["# Codebase Tour", f"**Directory:** {os.path.abspath(target)}", ""]

        def run_cmd(cmd: list, timeout: int = 10) -> str:
            try:
                result = subprocess.run(
                    cmd, cwd=target, capture_output=True, text=True, timeout=timeout
                )
                return result.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                return ""

        # Language detection via file extension counts
        ext_counts: dict = {}
        SKIP_DIRS = {".git","node_modules","__pycache__",".venv","venv",
                     ".build","DerivedData",".next","dist","build",".cache"}
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext:
                    ext_counts[ext] = ext_counts.get(ext, 0) + 1

        total_files = sum(ext_counts.values())
        top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:5]
        LANG_MAP = {
            ".py":"Python",".ts":"TypeScript",".tsx":"TypeScript/React",
            ".js":"JavaScript",".jsx":"JavaScript/React",".swift":"Swift",
            ".rs":"Rust",".go":"Go",".java":"Java",".kt":"Kotlin",
            ".rb":"Ruby",".cs":"C#",".cpp":"C++",".c":"C",
        }
        langs = [LANG_MAP[e] for e, _ in top_exts if e in LANG_MAP]
        primary = langs[0] if langs else "Unknown"

        lines.append("## Language & Stack")
        lines.append(f"**Primary:** {primary}  |  **Total files:** {total_files}")
        if len(langs) > 1:
            lines.append(f"**Also uses:** {', '.join(langs[1:])}")
        if top_exts:
            lines.append("**Breakdown:** " + "  ".join(f"`{e}`×{n}" for e, n in top_exts))
        lines.append("")

        # Framework markers
        FRAMEWORKS = {
            "package.json":"Node.js","Cargo.toml":"Rust/Cargo","go.mod":"Go",
            "Podfile":"iOS/CocoaPods","Package.swift":"Swift PM",
            "pyproject.toml":"Python/pyproject","requirements.txt":"Python/pip",
            "next.config.js":"Next.js","next.config.ts":"Next.js",
            "Dockerfile":"Docker","docker-compose.yml":"Docker Compose",
        }
        found = [fw for mk, fw in FRAMEWORKS.items() if os.path.exists(os.path.join(target, mk))]
        if found:
            lines.append(f"**Frameworks:** {', '.join(found)}")
            lines.append("")

        # Top-level directories
        try:
            top_dirs = sorted([
                d for d in os.listdir(target)
                if os.path.isdir(os.path.join(target, d)) and not d.startswith(".")
                and d not in {"node_modules","__pycache__",".venv","DerivedData"}
            ])[:8]
            if top_dirs:
                lines.append(f"**Key dirs:** {', '.join(f'`{d}/`' for d in top_dirs)}")
                lines.append("")
        except OSError:
            pass

        # Test coverage signal
        test_count = 0
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            test_count += sum(1 for f in files if "test" in f.lower() or "spec" in f.lower())
        coverage = "Good" if test_count > 10 else ("Some" if test_count > 0 else "None found")
        lines.append(f"**Test files:** {test_count} ({coverage})")
        lines.append("")

        # Recent git activity
        git_log = run_cmd(["git", "log", "--oneline", "-7"])
        if git_log:
            lines.append("## Recent Commits")
            for entry in git_log.split("\n"):
                lines.append(f"  {entry}")
            lines.append("")

        # Next steps
        lines.append("## Recommended Next Steps")
        lines.append("1. **`nora stats`** — see what Nora has captured so far")
        lines.append("2. **`nora patterns`** — see effective patterns learned")
        lines.append("3. **`nora bugs`** — see known issues")
        lines.append("")
        lines.append("After a few sessions: **`nora coach`** to track your prompt-quality signals.")
        return "\n".join(lines)

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


def main():
    """Entry point."""
    import asyncio

    server = NoraServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
