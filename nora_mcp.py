#!/usr/bin/env python3
"""
Nora MCP Server — exposes session intelligence to Claude Code and Claude Desktop.

Kernora AI — Session Learning Intelligence
Elastic License 2.0 — https://kernora.ai

Reads from ~/.kernora/echo.db (session metadata, insights, patterns, decisions, bugs).

Run standalone:  python3 nora_mcp.py
Run via Claude:  Configured in ~/.claude/settings.json mcpServers
Run via Desktop: Configured in claude_desktop_config.json

SECURITY: Read-only access to local echo.db. No writes. No network calls beyond MCP stdio.
"""

import json
import os
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
                    description="Search past sessions by keyword. Returns top 5 results across patterns, decisions, bugs, insights.",
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
                    description="List effective patterns, optionally filtered by project.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Project path (optional, e.g., '/path/to/VidafolioiOS')",
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
                    description="List architectural decisions, optionally filtered by project.",
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
                    description="List known bugs with severity and fix code.",
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
                    description="Get Nora dashboard stats (session count, insights, patterns, bugs).",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="nora_session",
                    description="Get details for a specific session.",
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
                else:
                    result = f"Unknown tool: {name}"

                return [TextContent(type="text", text=result)]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {str(e)}")]

    def _connect_db(self) -> sqlite3.Connection:
        """Connect to echo.db with error handling."""
        if not DB_PATH.exists():
            raise FileNotFoundError(
                f"Nora database not found at {DB_PATH}. Run `kernora install` first."
            )
        conn = sqlite3.connect(str(DB_PATH), timeout=DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        return conn

    def _search(self, query: str) -> str:
        """Search across patterns, decisions, bugs, insights via FTS5."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            results = {"patterns": [], "decisions": [], "bugs": [], "insights": []}

            # Try FTS5 on patterns
            try:
                cursor.execute(
                    "SELECT pattern, effectiveness, context FROM fts_patterns WHERE fts_patterns MATCH ? LIMIT 5",
                    (query,),
                )
                for row in cursor.fetchall():
                    results["patterns"].append(
                        {
                            "pattern": row[0],
                            "effectiveness": row[1],
                            "context": row[2],
                        }
                    )
            except sqlite3.OperationalError:
                # FTS5 not available, fall back to LIKE
                cursor.execute(
                    "SELECT pattern, effectiveness, context FROM patterns WHERE pattern LIKE ? LIMIT 5",
                    (f"%{query}%",),
                )
                for row in cursor.fetchall():
                    results["patterns"].append(
                        {
                            "pattern": row[0],
                            "effectiveness": row[1],
                            "context": row[2],
                        }
                    )

            # Try FTS5 on decisions
            try:
                cursor.execute(
                    "SELECT decision, rationale FROM fts_decisions WHERE fts_decisions MATCH ? LIMIT 5",
                    (query,),
                )
                for row in cursor.fetchall():
                    results["decisions"].append(
                        {"decision": row[0], "rationale": row[1]}
                    )
            except sqlite3.OperationalError:
                cursor.execute(
                    "SELECT decision, rationale FROM decisions WHERE decision LIKE ? LIMIT 5",
                    (f"%{query}%",),
                )
                for row in cursor.fetchall():
                    results["decisions"].append(
                        {"decision": row[0], "rationale": row[1]}
                    )

            # Try FTS5 on bugs
            try:
                cursor.execute(
                    "SELECT title, severity, fix_code FROM fts_bugs WHERE fts_bugs MATCH ? LIMIT 5",
                    (query,),
                )
                for row in cursor.fetchall():
                    results["bugs"].append(
                        {"title": row[0], "severity": row[1], "fix": row[2][:100]}
                    )
            except sqlite3.OperationalError:
                cursor.execute(
                    "SELECT title, severity, fix_code FROM reported_bugs WHERE title LIKE ? LIMIT 5",
                    (f"%{query}%",),
                )
                for row in cursor.fetchall():
                    results["bugs"].append(
                        {"title": row[0], "severity": row[1], "fix": row[2][:100]}
                    )

            # Try FTS5 on insights
            try:
                cursor.execute(
                    "SELECT summary, themes FROM fts_insights WHERE fts_insights MATCH ? LIMIT 5",
                    (query,),
                )
                for row in cursor.fetchall():
                    results["insights"].append(
                        {"summary": row[0], "themes": row[1]}
                    )
            except sqlite3.OperationalError:
                cursor.execute(
                    "SELECT summary, themes FROM insights WHERE summary LIKE ? LIMIT 5",
                    (f"%{query}%",),
                )
                for row in cursor.fetchall():
                    results["insights"].append(
                        {"summary": row[0], "themes": row[1]}
                    )

            conn.close()

            # Format results
            output = f"Search Results for '{query}':\n\n"
            total = sum(len(v) for v in results.values())

            if total == 0:
                return "No results found. Try a different query."

            for category in ["patterns", "decisions", "bugs", "insights"]:
                if results[category]:
                    output += f"\n{category.upper()} ({len(results[category])}):\n"
                    for item in results[category]:
                        output += f"  • {item}\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Search error: {str(e)}"

    def _patterns(self, project: str | None = None, min_effectiveness: float = 0) -> str:
        """List effective patterns."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            query = "SELECT pattern, effectiveness, domains, context FROM patterns WHERE effectiveness >= ?"
            params = [min_effectiveness]

            if project:
                query += " AND project = ?"
                params.append(project)

            query += " ORDER BY effectiveness DESC LIMIT 20"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return "No patterns found yet. Complete a few sessions to populate."

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

    def _decisions(self, project: str | None = None) -> str:
        """List architectural decisions."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            query = "SELECT decision, rationale, alternatives, created_at FROM decisions"
            params = []

            if project:
                query += " WHERE project = ?" if hasattr(cursor, "description") else ""
                if project:
                    params.append(project)

            query += " ORDER BY created_at DESC LIMIT 20"
            cursor.execute(query, params)
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

    def _bugs(
        self,
        status: str = "open",
        severity: str | None = None,
    ) -> str:
        """List known bugs."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            query = "SELECT id, title, severity, file_path, status, fix_code FROM reported_bugs"
            params = []

            if status != "all":
                query += " WHERE status = ?"
                params.append(status)

            if severity:
                if params:
                    query += " AND severity = ?"
                else:
                    query += " WHERE severity = ?"
                params.append(severity)

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
                output += f"  Fix: {row[5][:150]}...\n\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Bugs error: {str(e)}"

    def _stats(self) -> str:
        """Get dashboard stats."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            stats = {}

            cursor.execute("SELECT COUNT(*) FROM sessions")
            stats["sessions"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM insights")
            stats["insights"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM patterns")
            stats["patterns"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM decisions")
            stats["decisions"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM reported_bugs WHERE status = 'open'")
            stats["open_bugs"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM reported_bugs WHERE status = 'resolved'")
            stats["resolved_bugs"] = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(tokens_in) FROM sessions")
            total_tokens = cursor.fetchone()[0] or 0
            stats["total_tokens"] = total_tokens

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

    def _session(self, session_id: str) -> str:
        """Get details for a specific session."""
        try:
            conn = self._connect_db()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id, project, started_at, ended_at, tokens_in, tokens_out, model, analyzed FROM sessions WHERE id = ?",
                (session_id,),
            )
            session_row = cursor.fetchone()

            if not session_row:
                return f"Session {session_id} not found."

            cursor.execute(
                "SELECT summary, themes, bugs, optimizations, tools_used FROM insights WHERE session_id = ?",
                (session_id,),
            )
            insight_row = cursor.fetchone()

            conn.close()

            output = f"Session: {session_row[0]}\n"
            output += f"Project: {session_row[1]}\n"
            output += f"Started: {session_row[2]}\n"
            output += f"Ended: {session_row[3]}\n"
            output += f"Tokens In: {session_row[4]}\n"
            output += f"Tokens Out: {session_row[5]}\n"
            output += f"Model: {session_row[6]}\n"
            output += f"Analyzed: {session_row[7]}\n"

            if insight_row:
                output += f"\nSummary: {insight_row[0]}\n"
                output += f"Themes: {insight_row[1]}\n"
                if insight_row[2]:
                    output += f"Bugs Found: {insight_row[2]}\n"
                if insight_row[3]:
                    output += f"Optimizations: {insight_row[3]}\n"
                if insight_row[4]:
                    output += f"Tools Used: {insight_row[4]}\n"

            return output

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Session lookup error: {str(e)}"

    async def run(self):
        """Start the MCP server on stdio."""
        async with stdio_server(self.server) as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream, self.server.create_initialization_state())


def main():
    """Entry point."""
    server = NoraServer()
    import asyncio

    asyncio.run(server.run())


if __name__ == "__main__":
    main()
