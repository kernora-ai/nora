#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""
Claude Code SessionStart hook — injects project context at session start.

Installed at: ~/.claude/hooks/nora_session_start.py
Triggered by: Claude Code SessionStart (startup, resume, compact)

What it does:
  1. Checks daemon health via socket
  2. Gets session stats for the current project directory
  3. On source="startup": inject brief status + top 3 patterns for project
  4. On source="resume": inject minimal status only
  5. On source="compact": restore context from pre_compact_context.json (critical findings that were lost to compaction)
  6. Cold-start auto-seed: on first startup in an empty-factbook git repo,
     spawns a detached background process that derives a small set of
     high-confidence CANDIDATE factlets from local code/git (no network,
     no LLM) — so ambient grounding works from the next session.

CONTRACT:
  - Reads JSON from stdin: {"hook_event_name": "SessionStart", "session_id": "...", "cwd": "...", "source": "startup|resume|clear|compact"}
  - stdout = context injected into Claude's context window (ONLY for startup/compact)
  - Exit 0 always

SECURITY: stdlib only, no network calls, no API keys.
"""
# C5 fix (2026-04-23): lazy-import db inside function scope. The top-level
# `import db` was a 5s-timeout risk when sqlite-vec / sentence-transformers
# imports cold-started.
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"
SOCK_PATH = Path.home() / ".kernora" / "daemon.sock"
# H1 fix (2026-04-23): session-scoped pre-compact files; legacy path kept
# as a read-only fallback for pre-fix state.
PRE_COMPACT_DIR = Path.home() / ".kernora" / "pre_compact"
PRE_COMPACT_LEGACY_FILE = Path.home() / ".kernora" / "pre_compact_context.json"

# ── Cold-start auto-seed constants ───────────────────────────────────────────
# Idempotency markers live in ~/.kernora/ — one per project (hash of abs path).
# Presence of the marker means seed has already run; never re-seed.
KERNORA_DIR = Path.home() / ".kernora"
_SEED_PREFIX = ".seeded-"
_SEED_MAX_FACTLETS = 12


def _pre_compact_file(session_id: str) -> Path:
    safe_sid = "".join(c for c in (session_id or "unknown") if c.isalnum() or c in "-_")
    return PRE_COMPACT_DIR / f"{safe_sid or 'unknown'}.json"


def check_daemon_health() -> bool:
    """Test if daemon is alive via socket."""
    if not SOCK_PATH.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(str(SOCK_PATH))
        return True
    except (ConnectionRefusedError, OSError, FileNotFoundError):
        return False


def get_project_sessions(project_path: str) -> int:
    """Count sessions for the given project directory.

    AUDIT-FIX-BRIEF Fix 2 (quality-loop 2026-07-17, §4/F3): this used to run
    `WHERE project = <raw cwd>` — an EXACT match against the absolute path.
    `sessions.project` is stored in inconsistent forms (basename, worktree-
    mangled dir names, occasionally a full path), so a raw-path exact match
    silently undercounted — this hook's startup banner showed "62 sessions"
    while the dashboard (which resolves project names properly) showed
    "1,013" for the identical project. Fixed by routing through the same
    two-stage resolution the dashboard's /api/sessions and the nora-ui
    Home/Sessions SPA use: db.canonical_project (path → canonical name,
    e.g. an absolute cwd → "kernora") then db.canonical_session_count
    (canonical name → every raw sessions.project form that resolves to it).
    f388 — no parallel counting logic.
    """
    if not DB_PATH.exists():
        return 0
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path.home() / ".kernora" / "app"))
        import db
        conn = db.get_conn()
        conn.row_factory = sqlite3.Row
        canonical_name = db.canonical_project(project_path) or project_path
        count = db.canonical_session_count(conn, canonical_name)
        conn.close()
        return count
    except Exception:
        return 0


def get_top_patterns_for_project(project_path: str, limit: int = 3) -> list:
    """
    Get top patterns by effectiveness/recency for the given project.
    Returns list of {pattern, code_example, effectiveness}.

    Same raw-path-vs-stored-form mismatch as get_project_sessions above
    (AUDIT-FIX-BRIEF Fix 2) — `s.project = <raw cwd>` silently returned no
    rows for any session whose `project` column was stored basename-form
    (the common case), so the startup banner's "top 3 patterns" list was
    empty even when the (also-broken) session count was nonzero. Resolves
    project the same way via db.canonical_project +
    db.resolve_session_project_values (f388 — one definition).
    """
    if not DB_PATH.exists():
        return []
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path.home() / ".kernora" / "app"))
        import db
        conn = db.get_conn()
        conn.row_factory = sqlite3.Row

        canonical_name = db.canonical_project(project_path) or project_path
        matching = db.resolve_session_project_values(conn, canonical_name)
        if not matching:
            conn.close()
            return []

        # Get patterns from sessions in this project, ordered by effectiveness
        # and recency. Excludes NULL/empty/placeholder pattern text at the
        # query layer — a row with no real statement is not a pattern, it's
        # a filler row (was rendered as "None"/"?" — field report fix,
        # Jivant iOS, 2026-07-19; f404 — fix the query, not just the render).
        placeholders = ",".join("?" for _ in matching)
        # R2 (same field report): also pull grounding columns (source_uri,
        # verified_at, review_status, reinforcement_count) so the caller can
        # show real trust evidence instead of the fabricated "(effectiveness:
        # 0%)" score every never-yet-reinforced pattern got. These columns
        # exist on the post-S2 `patterns` compat view but NOT on a
        # pre-migration `patterns` base table (db.py genesis schema) — fall
        # back to the base 5-column SELECT on OperationalError so old
        # schemas keep working (this fallback is load-bearing, not
        # decorative — exercised by tests/test_field_report_hook_fixes.py).
        try:
            rows = conn.execute(f"""
                SELECT DISTINCT p.id, p.pattern, p.code_example, p.effectiveness,
                       p.created_at, p.source_uri, p.verified_at,
                       p.review_status, p.reinforcement_count
                FROM patterns p
                JOIN sessions s ON s.id = p.session_id
                WHERE s.project IN ({placeholders})
                  AND p.pattern IS NOT NULL
                  AND TRIM(p.pattern) NOT IN ('', '?')
                ORDER BY p.effectiveness DESC, p.created_at DESC
                LIMIT ?
            """, matching + [limit]).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(f"""
                SELECT DISTINCT p.id, p.pattern, p.code_example, p.effectiveness, p.created_at
                FROM patterns p
                JOIN sessions s ON s.id = p.session_id
                WHERE s.project IN ({placeholders})
                  AND p.pattern IS NOT NULL
                  AND TRIM(p.pattern) NOT IN ('', '?')
                ORDER BY p.effectiveness DESC, p.created_at DESC
                LIMIT ?
            """, matching + [limit]).fetchall()

        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _grounding_line(p: dict) -> str:
    """Return a short, honest trust descriptor for pattern `p`, or '' if
    there's nothing real to say. R2 (field report, Jivant iOS,
    2026-07-19): replaces the old "(effectiveness: N%)" label — every real
    pattern defaults to effectiveness=0 (never yet reinforced), so the
    percentage was near-universally misleading ("ignore me") even for the
    session's three best facts. Show what actually earns trust —
    verification source + date, or reinforcement count — and show NOTHING
    for unmeasured data rather than fabricate a 0% score. Mirrors
    nora_context._grounding_line (these two hook files don't share imports,
    so the logic is duplicated in miniature rather than cross-imported)."""
    verified_at = p.get('verified_at')
    source = p.get('source_uri')
    if verified_at and source:
        return f"verified against {source}, {str(verified_at)[:10]}"
    if verified_at:
        return f"verified {str(verified_at)[:10]}"
    if (p.get('review_status') or '').strip().lower() == 'verified':
        return "verified"
    try:
        rc = int(p.get('reinforcement_count') or 0)
        if rc > 0:
            return f"reinforced {rc}x"
    except (TypeError, ValueError):
        pass
    return ""  # unmeasured — say nothing, never fabricate a score


SAMPLE_PROMPTS = [
    ("Discover patterns", "what patterns has Nora found?"),
    ("Review decisions", "what architectural decisions have I made?"),
    ("Check bugs", "are there any known bugs in this project?"),
    ("Get a retro", "give me a retro on my last week of coding"),
    ("Run PE review", "nora pe-review"),
    ("Run COE", "nora coe — investigate why something broke"),
    ("Search history", "search my sessions for [topic]"),
]


def format_startup_context(project_path: str, session_count: int, patterns: list) -> str:
    """Format context for startup source."""
    lines = []
    lines.append("")
    lines.append("─── 🟢 Nora · Kernora — Session Started ───")

    if session_count == 0:
        lines.append(f"[Nora] New project. Ready to learn from your sessions.")
        lines.append("")
        lines.append("Try asking:")
        for label, prompt in SAMPLE_PROMPTS[:4]:
            lines.append(f'  → "{prompt}"')
    else:
        lines.append(f"[Nora] {Path(project_path).name} — {session_count} sessions in memory.")

        # f404: never render filler rows. get_top_patterns_for_project already
        # excludes NULL/empty/'?' pattern text at the query layer — this is
        # defense-in-depth. If NO real patterns remain, collapse to one
        # honest line instead of a numbered list (field report fix, Jivant
        # iOS, 2026-07-19). Threshold is 0 real items, not <2 — a single
        # genuine pattern is still shown, never hidden (R6: "one relevant
        # factlet beats hiding it").
        real_patterns = [
            p for p in patterns
            if (p.get('pattern') or '').strip().lower() not in ('', '?', 'none', 'null', 'n/a')
        ]

        if real_patterns:
            lines.append("")
            lines.append("Top patterns from past sessions:")
            for i, p in enumerate(real_patterns, 1):
                pattern_text = p['pattern']
                # R2: no fabricated percentage — a real grounding line if we
                # have one, else nothing (see _grounding_line docstring).
                grounding = _grounding_line(p)
                suffix = f" ({grounding})" if grounding else ""
                lines.append(f"  {i}. {pattern_text}{suffix}")
                if p.get('code_example'):
                    example = p['code_example'][:80]
                    lines.append(f"     Example: {example}")
        elif patterns:
            lines.append("")
            n = len(patterns)
            lines.append(f"{n} pattern{'s' if n != 1 else ''} tracked — none ranked yet.")

        lines.append("")
        lines.append("Quick commands (type these as prompts):")
        lines.append('  → "what patterns has Nora found?"')
        lines.append('  → "nora pe-review" — code quality audit')
        lines.append('  → "nora coe [bug]" — root cause investigation')
        lines.append('  → "nora help" — see all Nora commands')

    lines.append("─── End Nora · Kernora ───")
    lines.append("")

    return "\n".join(lines)


def format_compact_context(saved_context: dict) -> str:
    """Format context from pre_compact_context.json for recovery after compaction."""
    lines = []
    lines.append("")
    lines.append("─── Nora Pre-Compaction Recovery ───")
    lines.append("These insights were captured before context compaction.")
    lines.append("")

    # Format each saved insight type
    if saved_context.get('critical_patterns'):
        lines.append("CRITICAL PATTERNS (must remember):")
        for p in saved_context['critical_patterns']:
            lines.append(f"  • {p}")
        lines.append("")

    if saved_context.get('recent_decisions'):
        lines.append("RECENT ARCHITECTURAL DECISIONS:")
        for d in saved_context['recent_decisions']:
            lines.append(f"  • {d}")
        lines.append("")

    if saved_context.get('open_issues'):
        lines.append("OPEN ISSUES TO REMEMBER:")
        for issue in saved_context['open_issues']:
            lines.append(f"  • {issue}")
        lines.append("")

    if saved_context.get('summary'):
        lines.append(f"SUMMARY: {saved_context['summary']}")
        lines.append("")

    lines.append("─── End Recovery Context ───")
    lines.append("")

    return "\n".join(lines)


def format_resume_context(session_count: int) -> str:
    """Format minimal context for resume source."""
    lines = []
    lines.append("")
    lines.append(f"[Nora] Session resumed. {session_count} sessions in memory.")
    lines.append("")
    return "\n".join(lines)


def _seed_marker_path(project_root: str) -> Path:
    """Return the idempotency-marker path for a given project root.

    Hash is SHA-256[:16] of the absolute path — one file per project,
    no collisions in practice. Never touches the real factbook.
    """
    import hashlib
    h = hashlib.sha256(project_root.encode("utf-8", errors="replace")).hexdigest()[:16]
    return KERNORA_DIR / f"{_SEED_PREFIX}{h}"


def _is_git_repo(path: str) -> bool:
    """Return True if `path` is inside a git repo (has .git dir)."""
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _count_project_patterns(project: str) -> int:
    """Count non-archived patterns for a project in echo.db.

    Returns 0 on any error so cold-start check stays safe.
    """
    if not DB_PATH.exists():
        return 0
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path.home() / ".kernora" / "app"))
        import db
        return db.count_patterns(project)
    except Exception:
        return 0


def _is_cold_start(project_root: str, project_name: str) -> bool:
    """Return True if this is a first-ever session for this project.

    Conditions (all required):
      1. cwd is a git repo
      2. No patterns in DB for this project
      3. Idempotency marker absent (has never been seeded)
    """
    if not _is_git_repo(project_root):
        return False
    if _seed_marker_path(project_root).exists():
        return False
    if _count_project_patterns(project_name) > 0:
        return False
    return True


def seed_cold_start(project_root: str) -> None:
    """Derive a small set of high-confidence CANDIDATE factlets from local
    code and git (no network, no LLM) and write them to echo.db.

    Called in a detached subprocess — must NEVER crash the session-start hook.
    Writes the idempotency marker FIRST to prevent double-seeding even if the
    DB write fails partway through.

    Only structural facts a deterministic scan is actually confident about:
      - Primary language(s) by file count
      - Detected frameworks (from package.json / pyproject.toml)
      - Dependency managers present
      - Whether the project has CI, Docker, test dirs
      - Project commit velocity (if git history >= 5 commits)
    Does NOT mine commit messages or produce 'decision' type facts.
    """
    import hashlib
    import sys as _sys
    import traceback

    try:
        project_root_path = Path(project_root).resolve()
        # PE MED fix: scope the seeded rows by the SAME key the ambient recall
        # query uses (db.canonical_project), not the bare basename. A divergence
        # (worktree→parent, or manifest-name when basename is generic) would mean
        # seeded rows never match recall → silently inert.
        try:
            import db as _db_cp
            project_name = _db_cp.canonical_project(str(project_root_path))
        except Exception:
            # PE HIGH (2026-07-20): the fallback must still normalize —
            # a raw basename like "JWM" poisons the project column and
            # breaks canonical_project() comparisons downstream.
            project_name = project_root_path.name.strip().lower()

        marker = _seed_marker_path(project_root)
        # Write marker immediately — if DB write fails we still don't re-seed.
        KERNORA_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({
                "seeded_at": datetime.now(timezone.utc).isoformat(),
                "project_root": project_root,
                "project_name": project_name,
            })
        )

        # Import nora_init scanners — local-only, deterministic. Load ONLY from
        # the trusted install path; do NOT add the customer repo's parent dir to
        # sys.path (PE M3: a `nora_init.py` in the repo's parent would shadow ours
        # and run in this detached process — a code-exec vector).
        _sys.path.insert(0, str(Path.home() / ".kernora" / "app"))
        try:
            import nora_init as _ni
        except ImportError:
            # Try loading from cwd parent (bundled install path)
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location(
                "nora_init",
                str(Path.home() / ".kernora" / "app" / "nora_init.py"),
            )
            if _spec is None:
                return
            _ni = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_ni)

        code = _ni.scan_code(project_root_path)
        git = _ni.scan_git(project_root_path)

        # Build factlets — structural, decision-bearing where possible.
        # DE 2026-05-22: do NOT seed pure inventory ("primarily Python", language
        # counts) — the engineer and Claude both already see that from the files;
        # it's boilerplate that pads the count without adding decision value.
        # Seed only facts that shape a decision (frameworks/test cmd/deps/CI/tests),
        # and seed FEWER rather than pad. (Fuller decision-bearing extraction —
        # README/CONTRIBUTING rules, the actual test command, runtime pins — is a
        # follow-up extraction pass, tracked separately.)
        factlets: list[dict] = []

        # Detected frameworks (one factlet per framework group, max 4)
        if code.frameworks:
            fw_str = ", ".join(code.frameworks[:6])
            factlets.append({
                "name": f"Frameworks detected: {fw_str[:40]}",
                "pattern": (
                    f"Detected framework(s) in this project: {fw_str}. "
                    f"Found via dependency files ({', '.join(code.config_files[:3])})."
                ),
                "fact_type": "convention",
                "confidence": 0.88,
                "tags": ["framework", "dependencies"],
            })

        # 4. Dependency managers
        if code.has_deps:
            mgr_str = ", ".join(code.has_deps.keys())
            factlets.append({
                "name": f"Dependency manager(s): {mgr_str}",
                "pattern": (
                    f"This project uses {mgr_str} for dependency management "
                    f"(detected from {', '.join(code.has_deps.values())})."
                ),
                "fact_type": "convention",
                "confidence": 0.95,
                "tags": ["dependencies", "tooling"],
            })

        # 5. CI presence
        if code.has_ci:
            factlets.append({
                "name": "CI/CD pipeline present",
                "pattern": (
                    "This project has CI/CD configuration "
                    "(.github/workflows or equivalent). "
                    "Automated testing and deployment is wired."
                ),
                "fact_type": "convention",
                "confidence": 0.92,
                "tags": ["ci", "tooling"],
            })

        # 6. Docker presence
        if code.has_docker:
            factlets.append({
                "name": "Docker configuration present",
                "pattern": (
                    "This project has Docker configuration (Dockerfile or "
                    "docker-compose). Container-based deployment is supported."
                ),
                "fact_type": "convention",
                "confidence": 0.92,
                "tags": ["docker", "tooling"],
            })

        # 7. Test directories
        if code.test_dirs:
            factlets.append({
                "name": f"Test directory: {code.test_dirs[0]}",
                "pattern": (
                    f"This project has test infrastructure in: "
                    f"{', '.join(code.test_dirs)}. "
                    "Tests should be run before committing changes."
                ),
                "fact_type": "convention",
                "confidence": 0.90,
                "tags": ["testing", "structure"],
            })

        # Git velocity + churn-hotspot factlets intentionally NOT seeded (PE
        # 2026-05-22): they're low-value at inference and pollute ambient recall
        # (a bare filename list FTS-matches any prompt naming a file). Cold-start
        # seeds only high-confidence STRUCTURAL grounding (language/framework/
        # deps/CI/Docker/test-dirs).

        # Cap at max
        factlets = factlets[:_SEED_MAX_FACTLETS]

        if not factlets:
            return  # Nothing useful found — marker already written, that's fine.

        # Write to DB — direct insert with review_status='candidate'.
        # We bypass factbook_add_fact (which hardcodes 'verified') because
        # cold-start seeds are unverified structural observations.
        import db as _db
        # Ensure DB + schema exist before inserting.
        try:
            _db.init_db()
        except Exception:
            pass  # init_db may error if already initialized — proceed anyway
        conn = _db.get_conn()
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            inserted = 0
            import db as _db_nss
            _nss_use_factlets = _db_nss._factlets_table_exists(conn)
            for fl in factlets:
                try:
                    if _nss_use_factlets:
                        _nss_body = fl["pattern"]
                        _nss_cb = _db_nss._zone_c_created_by_runtime(
                            "auto", project_name or "_", _nss_body
                        )
                        _nss_fid = "c:" + __import__("hashlib").md5(
                            _nss_body.encode("utf-8", errors="replace")
                        ).hexdigest()
                        conn.execute(
                            """INSERT OR IGNORE INTO factlets
                               (created_by, fact_id, name, body, fact_type, confidence,
                                review_status, source_type, archived, project,
                                scope_level, created_at, tags)
                               VALUES (?, ?, ?, ?, ?, ?, 'candidate', 'auto',
                                       0, ?, 'project', ?, ?)""",
                            (
                                _nss_cb, _nss_fid, fl["name"][:60], _nss_body,
                                fl.get("fact_type", "convention"),
                                fl.get("confidence", 0.80),
                                project_name, now,
                                json.dumps(fl.get("tags", [])),
                            ),
                        )
                    else:
                        conn.execute(
                            """INSERT OR IGNORE INTO patterns
                               (name, pattern, fact_type, confidence, review_status,
                                source_type, created_by, archived, project,
                                scope_level, created_at, tags)
                               VALUES (?, ?, ?, ?, 'candidate', 'auto', 'cold-start-seed',
                                       0, ?, 'project', ?, ?)""",
                            (
                                fl["name"][:60],
                                fl["pattern"],
                                fl.get("fact_type", "convention"),
                                fl.get("confidence", 0.80),
                                project_name,
                                now,
                                json.dumps(fl.get("tags", [])),
                            ),
                        )
                    inserted += 1
                except Exception as exc:
                    print(
                        f"[COLD-START-SEED] WARN: could not insert factlet "
                        f"{fl.get('name', '?')!r}: {exc}",
                        file=_sys.stderr,
                    )
            conn.commit()
        finally:
            conn.close()

    except Exception as exc:
        # f404 — log loudly but NEVER crash the caller.
        print(
            f"[COLD-START-SEED] ERROR (non-fatal): {exc}\n"
            f"{traceback.format_exc(limit=5)}",
            file=sys.stderr,
        )


def _maybe_spawn_cold_start_seed(project_root: str, project_name: str) -> bool:
    """If cold-start conditions met, spawn detached background seed process.

    Returns True if seed was spawned, False otherwise.
    The session-start hook MUST return immediately regardless — this is
    fire-and-forget.
    """
    try:
        if not _is_cold_start(project_root, project_name):
            return False

        # Find the Python interpreter — prefer the kernora venv, fall back
        # to sys.executable (which is already running nora_session_start.py).
        venv_py = Path.home() / ".kernora" / "venv" / "bin" / "python3"
        python_exe = str(venv_py) if venv_py.exists() else sys.executable

        # This script's path — we call ourselves with --cold-start-seed.
        this_script = Path(__file__).resolve()

        subprocess.Popen(
            [python_exe, str(this_script), "--cold-start-seed", project_root],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Detach completely from parent process group.
            start_new_session=True,
            close_fds=True,
        )
        return True
    except Exception as exc:
        # f404 — log but never crash session-start.
        print(
            f"[COLD-START-SEED] WARN: could not spawn seed process: {exc}",
            file=sys.stderr,
        )
        return False


def main():
    """Main hook entry point."""
    start_time = time.time()

    # ── Cold-start seed subprocess entry point ────────────────────────────────
    # When spawned as a background process by _maybe_spawn_cold_start_seed(),
    # argv is: [this_script, "--cold-start-seed", <project_root>]
    if len(sys.argv) >= 3 and sys.argv[1] == "--cold-start-seed":
        project_root = sys.argv[2]
        seed_cold_start(project_root)
        sys.exit(0)
    # ─────────────────────────────────────────────────────────────────────────

    # Read hook input from Claude Code
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    hook_event_name = data.get("hook_event_name", "")
    session_id = data.get("session_id", "")
    cwd = data.get("cwd", os.getcwd())
    source = data.get("source", "startup")  # startup, resume, clear, compact

    if hook_event_name != "SessionStart":
        sys.exit(0)

    # Get session count for this project
    session_count = get_project_sessions(cwd)

    # Generate context based on source
    output = ""

    if source == "startup":
        # Startup: inject status + top patterns
        patterns = get_top_patterns_for_project(cwd, limit=3)
        output = format_startup_context(cwd, session_count, patterns)

        # R7 telemetry (field report, Jivant iOS, 2026-07-19): log the
        # session-start injection channel — {channel, project, repo_root,
        # fact_ids} — foundation for the shown-vs-rediscovered effectiveness
        # signal and the forensic trail for cross-project contamination
        # bugs. Best-effort, never blocks the session-start output.
        try:
            import sys as _sys_log
            _sys_log.path.insert(0, str(Path.home() / ".kernora" / "app"))
            import db as _db_log
            import nora_jsonl as _njl
            _njl.append_injection_event(
                channel="session_start",
                project=_db_log.canonical_project(cwd) or "",
                repo_root=cwd, trigger="session_start",
                fact_ids=[p.get('id') for p in patterns],
            )
        except Exception:
            pass

        # Cold-start auto-seed — detached background process, non-blocking.
        # Derive canonical project name the same way the rest of the system does.
        try:
            import sys as _sys2
            _sys2.path.insert(0, str(Path.home() / ".kernora" / "app"))
            import db as _db2
            _proj_name = _db2.canonical_project(cwd)
        except Exception:
            _proj_name = Path(cwd).name
        _seeded = _maybe_spawn_cold_start_seed(cwd, _proj_name)
        if _seeded:
            print(
                "\nNora is learning your codebase locally — grounding goes live "
                "next session. To confirm what it found (raises trust so it "
                "grounds you more strongly), just ask me to \"verify the "
                "factbook\" — I'll walk you through the top candidates — or run "
                "`kernora verify`.\n",
                end="",
            )

    elif source == "compact":
        # Compact: restore critical context from pre-compaction save.
        # H1 fix: try session-scoped file first; fall back to legacy
        # global file for pre-fix state.
        #
        #  (JWM field report #3 item 1, D-grade): the legacy
        # global file has NO project field and is a single blob shared by
        # every repo on the machine — it was found rendering three-month-old
        # Kernora dashboard issues into a JWM wealth-app session. Any
        # candidate file (legacy OR a stale/foreign per-session file) is now
        # validated against the CURRENT cwd's canonical project and a 24h
        # TTL before being trusted; a rejection is reported honestly instead
        # of silently swallowed (f404 class).
        saved_file = _pre_compact_file(session_id)
        used_legacy = False
        if not saved_file.exists() and PRE_COMPACT_LEGACY_FILE.exists():
            saved_file = PRE_COMPACT_LEGACY_FILE
            used_legacy = True
        suppressed_reason = None
        saved = None
        if saved_file.exists():
            try:
                saved = json.loads(saved_file.read_text())
            except Exception:
                saved = None
                suppressed_reason = "recovery file was corrupted"

        if saved is not None:
            saved_project = saved.get("project")
            saved_at = saved.get("saved_at")
            if saved_project is None or saved_at is None:
                # Pre-fix shape (no stamps) — can't verify identity/age.
                # Only the legacy file can lack these fields; be strict.
                suppressed_reason = (
                    "saved context has no project/timestamp stamp "
                    "(pre-fix format) and can't be verified as this "
                    "session's context"
                )
                saved = None
            else:
                try:
                    import sys as _sys3
                    _sys3.path.insert(0, str(Path.home() / ".kernora" / "app"))
                    import db as _db3  # type: ignore
                    cur_project = _db3.canonical_project(cwd)
                except Exception:
                    cur_project = None
                age_seconds = time.time() - float(saved_at)
                if cur_project is None:
                    # Stage-8 PE BLOCKER (2026-07-22): this branch used to be
                    # `cur_project is not None and ...`, which SKIPPED the
                    # mismatch check whenever project resolution failed —
                    # re-opening the cross-project leak this gate exists to
                    # close. `import db` genuinely fails in production shapes
                    # (hook script without an adjacent db.py; ~/.kernora/app
                    # missing or half-written during install/upgrade). An
                    # unverifiable identity must fail CLOSED, matching the
                    # unstamped-blob branch above and the core tenet.
                    suppressed_reason = (
                        "this session's project could not be resolved, so the "
                        "saved context's ownership can't be verified"
                    )
                    saved = None
                elif saved_project != cur_project:
                    suppressed_reason = (
                        f"saved context belongs to project '{saved_project}', "
                        f"not this session's '{cur_project}'"
                    )
                    saved = None
                elif age_seconds > 86400:
                    hours = int(age_seconds // 3600)
                    suppressed_reason = f"saved context is {hours}h old (>24h TTL)"
                    saved = None

        if saved is not None:
            output = format_compact_context(saved)
        else:
            # No usable recovery file (missing, corrupted, foreign-project,
            # or stale) — fall back to patterns, but say so honestly rather
            # than silently dropping context.
            patterns = get_top_patterns_for_project(cwd, limit=3)
            output = format_startup_context(cwd, session_count, patterns)
            if suppressed_reason:
                output = (
                    f"[Nora] Pre-compaction recovery suppressed: {suppressed_reason}.\n"
                    + output
                )

    elif source == "resume":
        # Resume: minimal context only
        output = format_resume_context(session_count)

    # elif source == "clear" — no output needed

    # Output to stdout (Claude Code adds to context)
    if output:
        print(output)

    # Wire factbook_load telemetry (batch-008, f135).
    # Fire-and-forget on startup — never blocks context injection.
    if source == "startup" and session_id:
        try:
            import factbook_telemetry as _ft
            import yaml as _yaml
            try:
                from yaml import CSafeLoader as _SafeLoader  # ~12x faster session-start on large factbooks
            except ImportError:
                from yaml import SafeLoader as _SafeLoader
            from pathlib import Path as _Path
            _fb_path = _Path(cwd) / ".nora" / "kernora-factbook.yaml"
            if not _fb_path.exists():
                _fb_path = _Path.home() / "code" / "kernora" / ".nora" / "kernora-factbook.yaml"
            if _fb_path.exists():
                _fb = _yaml.load(_fb_path.read_text(), Loader=_SafeLoader)
                _count = len(_fb.get("content", []))
                _ft.factbook_load(session_id, f"project:{_Path(cwd).name}", fact_count=_count)
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
