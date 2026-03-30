#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
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

SECURITY: Read-only access to local echo.db. No writes (except nora_metrics for scope validation).
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
DB_TIMEOUT = 2  # seconds


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
                Tool(
                    name="nora_search",
                    description="Search past sessions by keyword. Returns matches across patterns, decisions, bugs, insights.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (e.g., 'auth middleware', 'CoreData crash')",
                            }
                        },
                        "required": ["query"],
                    },
                ),
                Tool(
                    name="nora_patterns",
                    description="List effective coding patterns from past sessions, optionally filtered by project.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Project path (optional, e.g., '/Users/you/my-project')",
                            },
                            "min_effectiveness": {
                                "type": "number",
                                "description": "Minimum effectiveness score 0-1 (optional, default 0)",
                            },
                        },
                    },
                ),
                Tool(
                    name="nora_decisions",
                    description="List architectural decisions recorded across sessions.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Project path (optional)",
                            }
                        },
                    },
                ),
                Tool(
                    name="nora_bugs",
                    description="List known bugs with severity, file path, and fix code.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["open", "resolved", "all"],
                                "description": "Bug status filter (default: 'open')",
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "high", "medium", "low"],
                                "description": "Severity filter (optional)",
                            },
                        },
                    },
                ),
                Tool(
                    name="nora_stats",
                    description="Get Nora dashboard stats: session count, insights, patterns, bugs, total tokens.",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="nora_session",
                    description="Get full details for a specific session by ID.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID (e.g., 'abc123def456')",
                            }
                        },
                        "required": ["session_id"],
                    },
                ),
                Tool(
                    name="nora_scope_validation",
                    description=(
                        "Validate that the planned execution scope is focused and safe. "
                        "Call this before any multi-file edit or architectural change."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "intent": {
                                "type": "string",
                                "description": "The exact user request — do not paraphrase.",
                            },
                            "files_to_touch": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Files you plan to modify.",
                            },
                        },
                        "required": ["intent"],
                    },
                ),
                Tool(
                    name="nora_skills",
                    description=(
                        "Fetch the methodology distilled from this team's highest-quality "
                        "AI coding sessions. Use these patterns when implementing solutions."
                    ),
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Route tool calls to handlers."""
            try:
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
        conn = sqlite3.connect(str(DB_PATH), timeout=DB_TIMEOUT)
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
            conn = sqlite3.connect(str(DB_PATH), timeout=DB_TIMEOUT)
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
            conn = sqlite3.connect(str(DB_PATH), timeout=DB_TIMEOUT)
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

    async def run(self):
        """Start the MCP server on stdio."""
        async with stdio_server(self.server) as (read_stream, write_stream):
            await self.server.run(
                read_stream, write_stream, self.server.create_initialization_state()
            )


def main():
    """Entry point."""
    import asyncio

    server = NoraServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
