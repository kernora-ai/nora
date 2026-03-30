#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
"""
Nora MCP Server — exposes session intelligence to Claude Code and Claude Desktop.

Run standalone:  python3 nora_mcp.py
Run via Claude:  Configured in ~/.claude/settings.json mcpServers
Run via Desktop: Configured in claude_desktop_config.json

Tools (11):
  nora_search              — full-text search across patterns, decisions, bugs, insights
  nora_patterns            — list effective patterns, optionally filtered by project
  nora_decisions           — list architectural decisions
  nora_bugs                — list known bugs with severity and fix code
  nora_stats               — dashboard stats (sessions, insights, patterns, bugs)
  nora_session             — get details for a specific session
  nora_scope_validation    — validate planned execution scope before multi-file edits
  nora_skills              — fetch distilled methodology from past sessions
  nora_dashboard           — full intelligence dashboard inline (KPIs, patterns, decisions, bugs)
  nora_analyze_pending     — get next unanalyzed session with Phase 1 data + analysis prompt
  nora_store_analysis      — store agent-generated analysis (Phase 2 via Kiro's built-in model)

SECURITY: Read-only access to local echo.db except for analysis storage (nora_store_analysis).
          No network calls beyond MCP stdio. No API keys required — uses Kiro's built-in model.
"""

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


# Configuration
DB_PATH = Path.home() / ".kernora" / "echo.db"
SPOOL_DIR = Path.home() / ".kernora" / "spool"
STEERING_DIR = Path.home() / ".kiro" / "steering"
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
                Tool(
                    name="nora_dashboard",
                    description=(
                        "Full Nora intelligence dashboard: KPIs, top patterns, recent decisions, "
                        "open bugs, recent sessions, and knowledge domains — all in one view. "
                        "Use this when the user says 'show dashboard', 'Nora status', or "
                        "'what has Nora learned'."
                    ),
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="nora_analyze_pending",
                    description=(
                        "Check for unanalyzed sessions and return one for analysis. "
                        "Returns Phase 1 metadata + condensed transcript + analysis prompt. "
                        "After reading the output, generate the analysis and call "
                        "nora_store_analysis with your findings. "
                        "Call this when steering says 'pending sessions' or on 'nora analyze'."
                    ),
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="nora_store_analysis",
                    description=(
                        "Store your analysis of a coding session. Call this AFTER reading "
                        "the output of nora_analyze_pending and generating your analysis. "
                        "Pass the session_id and your analysis as a JSON object."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The session ID from nora_analyze_pending.",
                            },
                            "analysis": {
                                "type": "object",
                                "description": "Your analysis JSON with: session_type, workflow_stage, summary, themes, bugs, optimizations, playbook, architectural_decisions, effective_prompts, anti_patterns, claude_md_rules, knowledge_domains, reusable_patterns, prompt_quality, prompt_avg_words, repetition_count.",
                            },
                        },
                        "required": ["session_id", "analysis"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
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
                elif name == "nora_dashboard":
                    result = self._dashboard()
                elif name == "nora_analyze_pending":
                    result = self._analyze_pending()
                elif name == "nora_store_analysis":
                    result = self._store_analysis(
                        arguments["session_id"],
                        arguments["analysis"],
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
        conn = sqlite3.connect(str(DB_PATH), timeout=DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Search ───────────────────────────────────────────────────────────────

    def _search(self, query: str) -> str:
        """Search across patterns, decisions, bugs, insights via FTS5."""
        if not query or not query.strip():
            return "Please provide a search query."
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

    def _patterns(self, project: Optional[str] = None, min_effectiveness: float = 0) -> str:
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

    def _decisions(self, project: Optional[str] = None) -> str:
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

    def _bugs(self, status: str = "open", severity: Optional[str] = None) -> str:
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

    def _scope_validation(self, intent: str, files: List[str]) -> str:
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

    def _load_skills(self, limit: int = 10) -> List[str]:
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

    def _load_top_bugs(self, limit: int = 5) -> List[dict]:
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
            all_bugs: List[dict] = []
            for r in rows:
                try:
                    all_bugs.extend(json.loads(r[0]))
                except Exception:
                    pass
            # Deduplicate by title
            seen: Dict[str, dict] = {}
            for b in all_bugs:
                title = b.get("title", "")
                if title and title not in seen:
                    seen[title] = b
            return list(seen.values())[:limit]
        except Exception:
            return []

    # ── Agent-as-Analyzer: Phase 2 via Kiro's built-in model ──────────────

    def _analyze_pending(self) -> str:
        """
        Find an unanalyzed session and return Phase 1 metadata + condensed
        transcript + analysis prompt. The agent (using Kiro's built-in model)
        does the LLM reasoning and then calls nora_store_analysis.

        Sources (checked in order):
          1. Spool directory (~/.kernora/spool/) — sessions captured but not yet
             ingested by the daemon (e.g., daemon was offline)
          2. Database — sessions ingested but not yet analyzed (analyzed=0)
        """
        # ── Import analyzer functions (Phase 1 is pure Python, zero deps) ──
        try:
            analyzer_path = Path.home() / ".kernora" / "app" / "analyzer.py"
            if not analyzer_path.exists():
                # Fallback: maybe running from repo checkout
                analyzer_path = Path(__file__).parent / "analyzer.py"
            if not analyzer_path.exists():
                return (
                    "Analyzer module not found. Run install.sh to set up Nora, "
                    "or ensure ~/.kernora/app/analyzer.py exists."
                )

            # Dynamic import from the known path
            import importlib.util
            spec = importlib.util.spec_from_file_location("analyzer", str(analyzer_path))
            if spec is None or spec.loader is None:
                return "Failed to load analyzer module."
            analyzer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(analyzer)  # type: ignore[union-attr]

            phase1_extract = analyzer.phase1_extract
            condense_transcript = analyzer.condense_transcript
            format_metadata = analyzer._format_metadata_for_prompt
            PROMPT = analyzer.PROMPT
        except Exception as e:
            return f"Failed to load analyzer: {e}"

        # ── Source 1: Check spool directory for pending session files ──
        session_id = ""
        turns = []  # type: List[Dict[str, Any]]
        project = ""
        spool_file = None  # type: Optional[Path]

        if SPOOL_DIR.exists():
            spool_files = sorted(SPOOL_DIR.glob("kiro_*.json"), key=lambda f: f.name)
            for sf in spool_files:
                try:
                    payload = json.loads(sf.read_text())
                    sid = payload.get("session_id", "")
                    t = payload.get("turns", [])
                    if sid and len(t) >= 3:  # need at least a few turns
                        session_id = sid
                        turns = t
                        project = payload.get("project", "")
                        spool_file = sf
                        break
                except (json.JSONDecodeError, OSError):
                    continue

        # ── Source 2: Check DB for unanalyzed sessions ──
        if not turns:
            try:
                conn = self._connect_db()
                row = conn.execute(
                    "SELECT id, project, turns_json FROM sessions "
                    "WHERE analyzed = 0 ORDER BY inserted_at LIMIT 1"
                ).fetchone()
                conn.close()

                if row:
                    session_id = row[0]
                    project = row[1] or ""
                    try:
                        turns = json.loads(row[2]) if row[2] else []
                    except json.JSONDecodeError:
                        turns = []
            except Exception:
                pass

        if not turns or not session_id:
            return (
                "No pending sessions to analyze. "
                "Complete a coding session in Kiro first — the stop hook "
                "captures the transcript automatically."
            )

        # ── Run Phase 1 (deterministic, zero cost) ──
        phase1 = phase1_extract(turns)
        metadata = format_metadata(phase1)
        transcript = condense_transcript(phase1, max_tokens=8000)

        # ── Build the prompt for the agent ──
        analysis_prompt = PROMPT.format(
            metadata=metadata,
            transcript=transcript,
        )

        # ── Return structured output ──
        output = (
            f"SESSION READY FOR ANALYSIS\n"
            f"==========================\n"
            f"Session ID: {session_id}\n"
            f"Project: {project}\n"
            f"Turns: {len(turns)}\n"
            f"Files touched: {len(phase1.get('files_touched', []))}\n"
            f"Tools used: {len(phase1.get('tools_used', {}))}\n"
            f"User prompts: {phase1.get('user_turn_count', 0)}\n"
            f"Errors detected: {len(phase1.get('error_sequences', []))}\n\n"
            f"INSTRUCTIONS:\n"
            f"Read the analysis prompt below. Generate the JSON analysis.\n"
            f"Then call nora_store_analysis with session_id=\"{session_id}\" "
            f"and your analysis JSON.\n\n"
            f"{'=' * 60}\n"
            f"{analysis_prompt}\n"
        )

        return output

    def _store_analysis(self, session_id: str, analysis: Any) -> str:
        """
        Store the agent's analysis of a session. Called AFTER the agent reads
        the output of nora_analyze_pending and generates the analysis JSON.

        Steps:
          1. Validate the analysis has required fields
          2. If session was from spool, ingest it into DB first
          3. Call db.mark_analyzed() to store insights
          4. Remove the spool file if applicable
          5. Trigger steering file regeneration
        """
        if not session_id:
            return "Error: session_id is required."

        # Handle case where analysis is passed as string (some agents serialize)
        if isinstance(analysis, str):
            try:
                analysis = json.loads(analysis)
            except json.JSONDecodeError:
                return "Error: analysis must be valid JSON."

        if not isinstance(analysis, dict):
            return "Error: analysis must be a JSON object."

        # ── Validate minimum required fields ──
        required = ["session_type", "summary"]
        missing = [f for f in required if not analysis.get(f)]
        if missing:
            return f"Error: analysis is missing required fields: {', '.join(missing)}"

        # ── If session came from spool, ingest into DB first ──
        spool_file = None  # type: Optional[Path]
        if SPOOL_DIR.exists():
            for sf in SPOOL_DIR.glob("kiro_*.json"):
                try:
                    payload = json.loads(sf.read_text())
                    if payload.get("session_id") == session_id:
                        spool_file = sf
                        # Ingest into DB
                        try:
                            db_path = Path.home() / ".kernora" / "app" / "db.py"
                            if not db_path.exists():
                                db_path = Path(__file__).parent / "db.py"

                            import importlib.util
                            spec = importlib.util.spec_from_file_location("db", str(db_path))
                            if spec and spec.loader:
                                db_mod = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(db_mod)  # type: ignore[union-attr]
                                db_mod.store_session(payload)
                        except Exception as e:
                            return f"Error ingesting spool session: {e}"
                        break
                except (json.JSONDecodeError, OSError):
                    continue

        # ── Merge Phase 1 data into analysis (tools, files, commands) ──
        # The agent provides semantic fields; we add deterministic fields
        try:
            conn = self._connect_db()
            row = conn.execute(
                "SELECT turns_json FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            conn.close()

            if row and row[0]:
                try:
                    turns = json.loads(row[0])
                    # Import phase1_extract
                    analyzer_path = Path.home() / ".kernora" / "app" / "analyzer.py"
                    if not analyzer_path.exists():
                        analyzer_path = Path(__file__).parent / "analyzer.py"

                    import importlib.util
                    spec = importlib.util.spec_from_file_location("analyzer", str(analyzer_path))
                    if spec and spec.loader:
                        analyzer = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(analyzer)  # type: ignore[union-attr]
                        phase1 = analyzer.phase1_extract(turns)
                        # Inject Phase 1 deterministic data
                        analysis.setdefault("tools_used", phase1.get("tools_used", {}))
                        analysis.setdefault("files_touched", phase1.get("files_touched", []))
                        analysis.setdefault("commands_run", phase1.get("commands_run", []))
                except (json.JSONDecodeError, Exception):
                    pass
        except Exception:
            pass

        # ── Store in DB via mark_analyzed ──
        try:
            db_path = Path.home() / ".kernora" / "app" / "db.py"
            if not db_path.exists():
                db_path = Path(__file__).parent / "db.py"

            import importlib.util
            spec = importlib.util.spec_from_file_location("db", str(db_path))
            if spec is None or spec.loader is None:
                return "Error: db module not found."
            db_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(db_mod)  # type: ignore[union-attr]
            db_mod.mark_analyzed(session_id, analysis)
        except Exception as e:
            return f"Error storing analysis: {e}"

        # ── Remove spool file ──
        if spool_file and spool_file.exists():
            try:
                spool_file.unlink()
            except OSError:
                pass

        # ── Trigger steering regeneration ──
        self._trigger_steering_regen()

        # ── Summary ──
        stype = analysis.get("session_type", "unknown")
        summary = analysis.get("summary", "")[:150]
        themes = analysis.get("themes", [])
        bugs = analysis.get("bugs", [])
        decisions = analysis.get("architectural_decisions", [])

        return (
            f"Analysis stored for session {session_id[:12]}.\n\n"
            f"Type: {stype}\n"
            f"Summary: {summary}\n"
            f"Themes: {len(themes)} | Bugs: {len(bugs)} | Decisions: {len(decisions)}\n\n"
            f"Steering files will regenerate with the new intelligence.\n"
            f"Run nora_analyze_pending again to process more sessions."
        )

    def _trigger_steering_regen(self):
        """Trigger steering file regeneration in the background."""
        venv_python = Path.home() / ".kernora" / "venv" / "bin" / "python3"
        # Check both possible locations
        writer_path = Path.home() / ".kiro" / "hooks" / "steering_writer.py"
        if not writer_path.exists():
            writer_path = Path.home() / ".kernora" / "app" / "steering_writer.py"
        if venv_python.exists() and writer_path.exists():
            try:
                subprocess.Popen(
                    [str(venv_python), str(writer_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    # ── Dashboard (rich in-IDE view) ──────────────────────────────────────

    def _dashboard(self) -> str:
        """Full intelligence dashboard — replaces localhost:2742 for in-IDE use."""
        try:
            conn = self._connect_db()
            c = conn.cursor()

            # ── KPIs ──
            sessions = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            analyzed = c.execute("SELECT COUNT(*) FROM sessions WHERE analyzed = 1").fetchone()[0]
            patterns = c.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
            decisions = c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
            open_bugs = c.execute("SELECT COUNT(*) FROM reported_bugs WHERE status = 'open'").fetchone()[0]
            resolved = c.execute("SELECT COUNT(*) FROM reported_bugs WHERE status = 'resolved'").fetchone()[0]
            tokens = c.execute("SELECT COALESCE(SUM(tokens_in + tokens_out), 0) FROM sessions").fetchone()[0]

            out = "# Nora Intelligence Dashboard\n\n"
            out += f"**Sessions:** {sessions} captured, {analyzed} analyzed\n"
            out += f"**Patterns:** {patterns} | **Decisions:** {decisions}\n"
            out += f"**Bugs:** {open_bugs} open, {resolved} resolved\n"
            out += f"**Tokens processed:** {tokens:,}\n"

            # ── KIQ Score (Knowledge Intelligence Quotient) ──
            kiq = min(100, patterns * 2 + decisions * 3 + resolved * 5 + analyzed * 1)
            out += f"**KIQ Score:** {kiq}/100\n\n"

            # ── Top 5 patterns ──
            rows = c.execute(
                "SELECT pattern, effectiveness, domains FROM patterns "
                "ORDER BY effectiveness DESC LIMIT 5"
            ).fetchall()
            if rows:
                out += "## Top Patterns\n\n"
                for r in rows:
                    eff = f"{float(r[1]):.0%}" if r[1] else "—"
                    domains = r[2] or ""
                    out += f"- **{r[0]}** ({eff}) {f'[{domains}]' if domains else ''}\n"
                out += "\n"

            # ── Recent decisions ──
            rows = c.execute(
                "SELECT decision, rationale FROM decisions "
                "ORDER BY created_at DESC LIMIT 3"
            ).fetchall()
            if rows:
                out += "## Recent Decisions\n\n"
                for r in rows:
                    rationale = (r[1] or "")[:100]
                    out += f"- **{r[0]}** — {rationale}\n"
                out += "\n"

            # ── Open bugs ──
            rows = c.execute(
                "SELECT title, severity, fix_code FROM reported_bugs "
                "WHERE status = 'open' ORDER BY "
                "CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 "
                "WHEN 'medium' THEN 3 ELSE 4 END LIMIT 5"
            ).fetchall()
            if rows:
                out += "## Open Bugs\n\n"
                for r in rows:
                    fix = (r[2] or "no fix yet")[:80]
                    out += f"- [{r[1]}] **{r[0]}** — Fix: {fix}\n"
                out += "\n"

            # ── Recent sessions ──
            rows = c.execute(
                "SELECT s.id, s.project, s.ended_at, s.analyzed, "
                "COALESCE(i.session_type, 'pending'), COALESCE(i.summary, '') "
                "FROM sessions s LEFT JOIN insights i ON s.id = i.session_id "
                "ORDER BY s.ended_at DESC LIMIT 5"
            ).fetchall()
            if rows:
                out += "## Recent Sessions\n\n"
                for r in rows:
                    proj = (r[1] or "").split("/")[-1] or "unknown"
                    status = "analyzed" if r[3] else "pending"
                    stype = r[4] or ""
                    summary = (r[5] or "")[:100]
                    out += f"- **{proj}** [{stype}] ({status}) — {summary}\n"
                out += "\n"

            # ── Knowledge domains ──
            rows = c.execute(
                "SELECT knowledge_domains FROM insights "
                "WHERE knowledge_domains != '[]' AND knowledge_domains IS NOT NULL "
                "ORDER BY analyzed_at DESC LIMIT 10"
            ).fetchall()
            if rows:
                all_domains = set()
                for r in rows:
                    try:
                        domains = json.loads(r[0])
                        all_domains.update(d.lower() for d in domains if isinstance(d, str))
                    except (json.JSONDecodeError, TypeError):
                        pass
                if all_domains:
                    out += f"## Knowledge Domains\n\n{', '.join(sorted(all_domains))}\n\n"

            conn.close()

            if sessions == 0:
                out += "\n---\n*No sessions yet. Code normally — Nora captures and learns automatically.*\n"

            return out

        except FileNotFoundError as e:
            return str(e)
        except Exception as e:
            return f"Dashboard error: {str(e)}"

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
