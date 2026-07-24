#!/usr/bin/env python3
# Kernora — PULSE (Persistent Unified Lifecycle Signal Engine)
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
#
# PULSE is Nora's peripheral nervous system — always sensing changes in your
# codebase and surfacing signals to DREAM, Agents, and context injection.
#
# Replaces the old KAIROS JSON-file approach with DB-persisted signals,
# richer git analysis (diffs, co-change detection), doc change tracking,
# and direct integration with DREAM consolidation and session context.
#
# Signal types:
#   - commit      : New commits detected in watched repos
#   - hotspot     : Files with high churn (edited frequently across checks)
#   - co_change   : Files that always change together (architectural coupling)
#   - doc_change  : Strategy/design docs modified (roadmap shifts, ADR updates)
#   - ci_signal   : Build/deploy events (future: webhook integration)
#
# Run: Embedded in daemon.py as pulse_loop() — 5-minute polling interval.
# API: pulse.scan_repos(), pulse.get_signals(), pulse.get_hotspots()

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# A-ISO fix (2026-07-18): honor KERNORA_HOME — pulse_loop() is embedded in
# daemon.py's main() as an unconditional daemon thread (t_pulse, started on
# every daemon boot), and dashboard.py also does an on-demand `import pulse`.
# Without this, an isolated daemon/dashboard instance's pulse thread reads/
# writes commit-signal + hotspot state into the operator's REAL ~/.kernora.
HOME = Path(os.environ.get("KERNORA_HOME") or (Path.home() / ".kernora"))
DB_PATH = HOME / "echo.db"
PULSE_STATE_FILE = HOME / "pulse_state.json"
PULSE_LOG = HOME / "logs" / "pulse.log"

# Ensure log directory
(HOME / "logs").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(PULSE_LOG),
    level=logging.INFO,
    format="%(asctime)s [PULSE] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pulse")


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_pulse_tables(conn: sqlite3.Connection):
    """Create pulse_signals table if it doesn't exist. Idempotent."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pulse_signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_type TEXT NOT NULL,
            repo        TEXT NOT NULL,
            file_path   TEXT,
            detail      TEXT,
            severity    TEXT DEFAULT 'info',
            metadata    TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pulse_signals_type
            ON pulse_signals(signal_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_pulse_signals_repo
            ON pulse_signals(repo, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_pulse_signals_file
            ON pulse_signals(file_path, created_at DESC);
    """)
    conn.commit()


def store_signal(conn: sqlite3.Connection, signal_type: str, repo: str,
                 file_path: str | None = None, detail: str = "",
                 severity: str = "info", metadata: dict | None = None):
    """Persist a PULSE signal to the database."""
    conn.execute("""
        INSERT INTO pulse_signals (signal_type, repo, file_path, detail, severity, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        signal_type,
        repo,
        file_path,
        detail,
        severity,
        json.dumps(metadata) if metadata else None,
    ))
    conn.commit()


# ── State management ─────────────────────────────────────────────────────────

def load_state() -> dict:
    """Load PULSE state (git heads, churn counts, last scan times)."""
    if PULSE_STATE_FILE.exists():
        try:
            return json.loads(PULSE_STATE_FILE.read_text())
        except Exception:
            pass
    return {"git_heads": {}, "churn": {}, "last_full_scan": None, "scan_count": 0}


def save_state(state: dict):
    """Persist PULSE state to disk."""
    try:
        PULSE_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except Exception as e:
        log.warning(f"Failed to save state: {e}")


# ── Repo discovery ───────────────────────────────────────────────────────────

def get_watched_repos() -> list[Path]:
    """Find git repos to watch — ~/code/ and known project paths."""
    repos = []
    code_dir = Path.home() / "code"
    if code_dir.exists():
        for child in sorted(code_dir.iterdir()):
            if child.is_dir() and (child / ".git").exists():
                repos.append(child)
    return repos[:10]  # Cap at 10 repos


# ── Git analysis ─────────────────────────────────────────────────────────────

def get_git_head(repo_path: Path) -> str | None:
    """Get current HEAD commit hash for a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(repo_path), capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_recent_commits(repo_path: Path, since_hash: str | None = None,
                       max_count: int = 20) -> list[dict]:
    """Get recent commits with file lists. If since_hash, only new commits."""
    try:
        cmd = ["git", "log", "--format=%H|%h|%s|%ai|%an", "--name-only",
               f"--max-count={max_count}"]
        if since_hash:
            cmd.append(f"{since_hash}..HEAD")

        result = subprocess.run(
            cmd, cwd=str(repo_path), capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []

        commits = []
        current = None
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                if current:
                    commits.append(current)
                    current = None
                continue
            if "|" in line and line.count("|") >= 4:
                parts = line.split("|", 4)
                current = {
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "message": parts[2],
                    "date": parts[3],
                    "author": parts[4],
                    "files": [],
                }
            elif current:
                current["files"].append(line.strip())

        if current:
            commits.append(current)
        return commits

    except Exception as e:
        log.warning(f"Failed to get commits for {repo_path.name}: {e}")
        return []


def detect_co_changes(repo_path: Path, lookback_days: int = 30,
                      min_co_occurrence: int = 3) -> list[dict]:
    """
    Detect files that frequently change together — signals architectural coupling.
    Uses git log to find files that appear in the same commits.
    """
    try:
        since = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        result = subprocess.run(
            ["git", "log", "--format=%H", "--name-only", f"--since={since}"],
            cwd=str(repo_path), capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []

        # Parse commits and their file sets
        commit_files: list[set[str]] = []
        current_files: set[str] = set()
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                if current_files:
                    commit_files.append(current_files)
                    current_files = set()
            elif len(line) == 40:  # Full hash
                if current_files:
                    commit_files.append(current_files)
                current_files = set()
            else:
                # Skip test files, configs, and docs for coupling analysis
                if not any(x in line for x in ["test", "spec", ".md", ".json", ".lock"]):
                    current_files.add(line)
        if current_files:
            commit_files.append(current_files)

        # Count co-occurrences
        co_change: dict[tuple[str, str], int] = defaultdict(int)
        for files in commit_files:
            sorted_files = sorted(files)
            for i, f1 in enumerate(sorted_files):
                for f2 in sorted_files[i + 1:]:
                    co_change[(f1, f2)] += 1

        # Filter and return pairs above threshold
        couples = []
        for (f1, f2), count in co_change.items():
            if count >= min_co_occurrence:
                couples.append({
                    "file_a": f1,
                    "file_b": f2,
                    "co_changes": count,
                })

        return sorted(couples, key=lambda x: x["co_changes"], reverse=True)[:10]

    except Exception as e:
        log.warning(f"Co-change detection failed for {repo_path.name}: {e}")
        return []


# ── File churn detection ─────────────────────────────────────────────────────

def detect_hotspot_churn(repos: list[Path], state: dict,
                         churn_threshold: int = 3) -> tuple[list[dict], dict]:
    """
    Detect files being edited frequently — potential architectural instability.
    Returns (hotspots, updated_churn_state).
    """
    churn_state = state.get("churn", {})
    hotspots = []

    source_patterns = ["*.py", "*.ts", "*.tsx", "*.swift", "*.js", "*.jsx",
                       "*.go", "*.rs", "*.java", "*.rb"]
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv",
                 "dist", "build", ".next", "target"}

    for repo in repos:
        repo_key = str(repo)
        repo_churn = churn_state.get(repo_key, {})

        for pattern in source_patterns:
            try:
                for f in list(repo.rglob(pattern))[:100]:
                    # Skip excluded directories
                    if any(d in f.parts for d in skip_dirs):
                        continue
                    try:
                        mtime = f.stat().st_mtime
                        rel_path = str(f.relative_to(repo))
                        prev = repo_churn.get(rel_path, {"mtime": 0, "count": 0})
                        if mtime > prev["mtime"]:
                            prev["count"] = prev.get("count", 0) + 1
                        prev["mtime"] = mtime
                        repo_churn[rel_path] = prev

                        if prev["count"] >= churn_threshold:
                            hotspots.append({
                                "repo": repo.name,
                                "file": rel_path,
                                "churn": prev["count"],
                            })
                    except (OSError, PermissionError):
                        pass
            except Exception:
                pass

        churn_state[repo_key] = repo_churn

    # Return top 10 hotspots sorted by churn
    hotspots = sorted(hotspots, key=lambda x: x["churn"], reverse=True)[:10]
    return hotspots, churn_state


# ── Document change detection ────────────────────────────────────────────────

DOC_PATTERNS = [
    "*.md", "PRFAQ*", "PRD*", "ADR-*", "TENETS*", "ROADMAP*",
    "ARCHITECTURE*", "CHANGELOG*", "CONTRIBUTING*",
]

DOC_DIRS = ["docs", "doc", "design", "rfcs", "adrs", "specs"]


def detect_doc_changes(repos: list[Path], state: dict) -> tuple[list[dict], dict]:
    """
    Detect changes to strategy/design documents — signals roadmap shifts,
    new ADRs, updated product intent.
    """
    doc_state = state.get("doc_mtimes", {})
    changes = []

    for repo in repos:
        repo_key = str(repo)
        repo_docs = doc_state.get(repo_key, {})

        # Scan doc directories + root-level docs
        scan_dirs = [repo]
        for d in DOC_DIRS:
            doc_dir = repo / d
            if doc_dir.exists():
                scan_dirs.append(doc_dir)

        for scan_dir in scan_dirs:
            for pattern in DOC_PATTERNS:
                try:
                    for f in scan_dir.glob(pattern):
                        if not f.is_file():
                            continue
                        try:
                            mtime = f.stat().st_mtime
                            rel_path = str(f.relative_to(repo))
                            prev_mtime = repo_docs.get(rel_path, 0)
                            if mtime > prev_mtime:
                                if prev_mtime > 0:  # Only report if not first scan
                                    changes.append({
                                        "repo": repo.name,
                                        "file": rel_path,
                                        "type": _classify_doc(rel_path),
                                    })
                                repo_docs[rel_path] = mtime
                        except (OSError, PermissionError):
                            pass
                except Exception:
                    pass

        doc_state[repo_key] = repo_docs

    return changes, doc_state


def _classify_doc(path: str) -> str:
    """Classify a document by type based on its name."""
    lower = path.lower()
    if "prfaq" in lower:
        return "product_intent"
    elif "prd" in lower or "roadmap" in lower:
        return "roadmap"
    elif "adr" in lower or "decision" in lower:
        return "architecture_decision"
    elif "tenet" in lower:
        return "tenets"
    elif "architecture" in lower:
        return "architecture"
    elif "changelog" in lower:
        return "release"
    elif "contributing" in lower:
        return "contributor_guide"
    elif "strategy" in lower or "vision" in lower:
        return "strategy"
    return "documentation"


# ── Git velocity metrics ─────────────────────────────────────────────────────

def compute_velocity(repo_path: Path, days: int = 7) -> dict:
    """
    Compute git velocity metrics for a repo over the given window.
    Returns commit count, files changed, insertions, deletions, active authors.
    """
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # Commit count + authors
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--format=%an"],
            cwd=str(repo_path), capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {}

        authors = result.stdout.strip().split("\n") if result.stdout.strip() else []
        commit_count = len(authors)
        unique_authors = len(set(authors))

        # Diffstat
        result2 = subprocess.run(
            ["git", "diff", "--stat", f"--since={since}", "HEAD"],
            cwd=str(repo_path), capture_output=True, text=True, timeout=10,
        )

        # Shortlog for files changed
        result3 = subprocess.run(
            ["git", "log", f"--since={since}", "--format=", "--name-only"],
            cwd=str(repo_path), capture_output=True, text=True, timeout=10,
        )
        files_touched = set()
        if result3.returncode == 0:
            for line in result3.stdout.strip().split("\n"):
                if line.strip():
                    files_touched.add(line.strip())

        return {
            "commits": commit_count,
            "authors": unique_authors,
            "files_changed": len(files_touched),
            "window_days": days,
        }

    except Exception as e:
        log.warning(f"Velocity computation failed for {repo_path.name}: {e}")
        return {}


# ── Main scan function ───────────────────────────────────────────────────────

def scan_repos(force: bool = False) -> dict:
    """
    Full PULSE scan cycle. Called by daemon every 5 minutes.
    Returns scan summary.
    """
    state = load_state()
    repos = get_watched_repos()

    if not repos:
        return {"status": "no_repos", "repos_found": 0}

    conn = get_conn()
    ensure_pulse_tables(conn)

    summary = {
        "repos_scanned": len(repos),
        "new_commits": 0,
        "hotspots": 0,
        "co_changes": 0,
        "doc_changes": 0,
        "timestamp": datetime.now().isoformat(),
    }

    git_heads = state.get("git_heads", {})

    # ── Phase 1: Detect new commits ──────────────────────────────────────────
    for repo in repos:
        repo_key = str(repo)
        current_head = get_git_head(repo)
        if current_head is None:
            continue

        prev_head = git_heads.get(repo_key)
        if prev_head is None:
            # First scan — record baseline
            git_heads[repo_key] = current_head
            continue

        if prev_head != current_head:
            # New commits since last check
            new_commits = get_recent_commits(repo, since_hash=prev_head)
            for commit in new_commits:
                store_signal(
                    conn, "commit", repo.name,
                    detail=commit.get("message", "")[:200],
                    metadata={
                        "hash": commit.get("short_hash"),
                        "author": commit.get("author"),
                        "files": commit.get("files", [])[:20],
                        "file_count": len(commit.get("files", [])),
                    },
                )
                summary["new_commits"] += 1
            git_heads[repo_key] = current_head
            log.info(f"PULSE: {len(new_commits)} new commit(s) in {repo.name}")

    state["git_heads"] = git_heads

    # ── Phase 2: Detect hotspot churn ────────────────────────────────────────
    # Run every 6th scan (~30 min) to avoid noise
    scan_count = state.get("scan_count", 0) + 1
    state["scan_count"] = scan_count

    if scan_count % 6 == 0 or force:
        hotspots, churn_state = detect_hotspot_churn(repos, state)
        state["churn"] = churn_state
        for h in hotspots:
            store_signal(
                conn, "hotspot", h["repo"],
                file_path=h["file"],
                detail=f"High-churn file: {h['file']} ({h['churn']} edits)",
                severity="warning" if h["churn"] >= 5 else "info",
                metadata={"churn_count": h["churn"]},
            )
            summary["hotspots"] += 1
        if hotspots:
            log.info(f"PULSE: {len(hotspots)} hotspot(s) detected")

    # ── Phase 3: Detect doc changes ──────────────────────────────────────────
    if scan_count % 6 == 0 or force:
        doc_changes, doc_state = detect_doc_changes(repos, state)
        state["doc_mtimes"] = doc_state
        for dc in doc_changes:
            store_signal(
                conn, "doc_change", dc["repo"],
                file_path=dc["file"],
                detail=f"Document updated: {dc['file']} ({dc['type']})",
                severity="info",
                metadata={"doc_type": dc["type"]},
            )
            summary["doc_changes"] += 1
        if doc_changes:
            log.info(f"PULSE: {len(doc_changes)} doc change(s) detected")

    # ── Phase 4: Detect co-change patterns ───────────────────────────────────
    # Run once per hour (every 12th scan)
    if scan_count % 12 == 0 or force:
        for repo in repos:
            couples = detect_co_changes(repo)
            for c in couples:
                store_signal(
                    conn, "co_change", repo.name,
                    file_path=c["file_a"],
                    detail=f"{c['file_a']} ↔ {c['file_b']} (co-changed {c['co_changes']}×)",
                    severity="info",
                    metadata={
                        "file_a": c["file_a"],
                        "file_b": c["file_b"],
                        "co_changes": c["co_changes"],
                    },
                )
                summary["co_changes"] += 1

    conn.close()
    save_state(state)
    return summary


# ── Query API (used by dashboard, DREAM, context injection) ──────────────────

def get_signals(signal_type: str | None = None, repo: str | None = None,
                limit: int = 50, hours: int = 168) -> list[dict]:
    """Get recent PULSE signals, optionally filtered by type and repo."""
    conn = get_conn()
    ensure_pulse_tables(conn)

    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    conditions = ["created_at > ?"]
    params: list = [since]

    if signal_type:
        conditions.append("signal_type = ?")
        params.append(signal_type)
    if repo:
        conditions.append("repo = ?")
        params.append(repo)

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT * FROM pulse_signals WHERE {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def detect_current_repo() -> str | None:
    """Return the basename of the git repo containing $CWD, or None.

    $50-1 (#44): every PULSE / co-change / doc-signal query defaults to this
    repo so a session in ~/code/JWM doesn't surface hotspots from ~/code/kernora.
    Matches the format pulse_signals.repo is stored in (Path.name of the
    scanned repo root).
    """
    import os
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", os.getcwd(), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            top = (result.stdout or "").strip()
            if top:
                from pathlib import Path as _Path
                return _Path(top).name or None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    # Fallback: use basename of cwd
    try:
        from pathlib import Path as _Path
        return _Path(os.getcwd()).name or None
    except Exception:
        return None


def get_hotspots(
    hours: int = 168,
    limit: int = 10,
    repo: str | None = None,
) -> list[dict]:
    """Get current hotspot files — most-churned files in the time window.

    $50-1 (#44): if `repo` is provided, results are filtered to that repo
    (matches pulse_signals.repo). Callers that want all repos pass repo="*"
    explicitly; passing None auto-scopes to detect_current_repo().
    """
    conn = get_conn()
    ensure_pulse_tables(conn)

    since = (datetime.now() - timedelta(hours=hours)).isoformat()

    scope_repo: str | None = None
    if repo == "*":
        scope_repo = None
    elif repo:
        scope_repo = repo
    else:
        scope_repo = detect_current_repo()

    if scope_repo:
        rows = conn.execute("""
            SELECT file_path, repo, COUNT(*) as signal_count,
                   MAX(json_extract(metadata, '$.churn_count')) as max_churn,
                   MAX(created_at) as last_seen
            FROM pulse_signals
            WHERE signal_type = 'hotspot' AND created_at > ?
              AND file_path IS NOT NULL
              AND repo = ?
            GROUP BY file_path, repo
            ORDER BY signal_count DESC, max_churn DESC
            LIMIT ?
        """, (since, scope_repo, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT file_path, repo, COUNT(*) as signal_count,
                   MAX(json_extract(metadata, '$.churn_count')) as max_churn,
                   MAX(created_at) as last_seen
            FROM pulse_signals
            WHERE signal_type = 'hotspot' AND created_at > ?
              AND file_path IS NOT NULL
            GROUP BY file_path, repo
            ORDER BY signal_count DESC, max_churn DESC
            LIMIT ?
        """, (since, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_velocity_summary(hours: int = 168) -> dict:
    """Get commit velocity from PULSE signals over a time window."""
    conn = get_conn()
    ensure_pulse_tables(conn)

    since = (datetime.now() - timedelta(hours=hours)).isoformat()

    # Total commits
    commit_count = conn.execute(
        "SELECT COUNT(*) FROM pulse_signals WHERE signal_type='commit' AND created_at > ?",
        (since,),
    ).fetchone()[0]

    # Commits by repo
    by_repo = conn.execute("""
        SELECT repo, COUNT(*) as commits
        FROM pulse_signals
        WHERE signal_type = 'commit' AND created_at > ?
        GROUP BY repo ORDER BY commits DESC
    """, (since,)).fetchall()

    # Unique authors
    author_rows = conn.execute("""
        SELECT DISTINCT json_extract(metadata, '$.author') as author
        FROM pulse_signals
        WHERE signal_type = 'commit' AND created_at > ?
          AND json_extract(metadata, '$.author') IS NOT NULL
    """, (since,)).fetchall()

    # Doc changes
    doc_count = conn.execute(
        "SELECT COUNT(*) FROM pulse_signals WHERE signal_type='doc_change' AND created_at > ?",
        (since,),
    ).fetchone()[0]

    conn.close()

    return {
        "commits": commit_count,
        "by_repo": {r["repo"]: r["commits"] for r in by_repo},
        "unique_authors": len(author_rows),
        "doc_changes": doc_count,
        "window_hours": hours,
    }


def get_co_changes(repo: str | None = None, limit: int = 10) -> list[dict]:
    """Get detected co-change pairs — architecturally coupled files."""
    conn = get_conn()
    ensure_pulse_tables(conn)

    if repo:
        rows = conn.execute("""
            SELECT DISTINCT
                json_extract(metadata, '$.file_a') as file_a,
                json_extract(metadata, '$.file_b') as file_b,
                json_extract(metadata, '$.co_changes') as co_changes,
                repo
            FROM pulse_signals
            WHERE signal_type = 'co_change' AND repo = ?
            ORDER BY co_changes DESC LIMIT ?
        """, (repo, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT DISTINCT
                json_extract(metadata, '$.file_a') as file_a,
                json_extract(metadata, '$.file_b') as file_b,
                json_extract(metadata, '$.co_changes') as co_changes,
                repo
            FROM pulse_signals
            WHERE signal_type = 'co_change'
            ORDER BY co_changes DESC LIMIT ?
        """, (limit,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ── PULSE context for injection (used by nora_context.py) ────────────────────

def get_pulse_context(
    file_paths: list[str] | None = None,
    repo: str | None = None,
    *,
    session_id: str | None = None,
) -> str:
    """Generate a PULSE context string for injection into sessions.

    $50-1 (#44): auto-scopes to the current repo via detect_current_repo()
    when `repo` is None. Pass `repo="*"` to opt into cross-repo view.

    $50-5 (#48): each emitted section is logged to injection_events via
    kernora_injection.record() so the precision metric can later classify
    whether this context was useful. Logging is best-effort; failures never
    break the hook path.
    """
    lines = []
    scope_repo = repo if repo == "*" else (repo or detect_current_repo())

    # Lazy import so pulse.py works on installs missing the module.
    try:
        import kernora_injection as _ki
    except ImportError:
        _ki = None

    # Hotspot warnings
    hotspots = get_hotspots(hours=168, limit=5, repo=scope_repo)
    if hotspots:
        block_lines = ["⚡ PULSE — Active Hotspots (high-churn files):"]
        refs: list[str] = []
        for h in hotspots:
            churn = h.get("max_churn", "?")
            block_lines.append(f"  🔥 {h['file_path']} ({h['repo']}) — {churn} edits")
            if h.get("file_path"):
                refs.append(h["file_path"])
        block_lines.append("  → Approach these files carefully; they're in active flux.")
        block_lines.append("")
        lines.extend(block_lines)
        if _ki is not None:
            _ki.record(
                "pulse.hotspots",
                "\n".join(block_lines),
                file_refs=refs,
                session_id=session_id,
                project=scope_repo,
            )

    # Co-change warnings for touched files
    if file_paths:
        co_changes = get_co_changes(limit=20, repo=scope_repo)
        relevant = []
        for cc in co_changes:
            if cc["file_a"] in file_paths or cc["file_b"] in file_paths:
                relevant.append(cc)
        if relevant:
            block_lines = ["⚡ PULSE — Co-Change Warnings:"]
            refs = []
            for cc in relevant[:3]:
                block_lines.append(
                    f"  🔗 {cc['file_a']} ↔ {cc['file_b']} "
                    f"(co-changed {cc['co_changes']}× in last 30 days)"
                )
                refs.extend([cc["file_a"], cc["file_b"]])
            block_lines.append(
                "  → These files are architecturally coupled; changes to one may require changes to the other."
            )
            block_lines.append("")
            lines.extend(block_lines)
            if _ki is not None:
                _ki.record(
                    "pulse.co_change",
                    "\n".join(block_lines),
                    file_refs=refs,
                    session_id=session_id,
                    project=scope_repo,
                )

    # Recent doc changes
    doc_signals = get_signals(signal_type="doc_change", limit=3, hours=48, repo=scope_repo)
    if doc_signals:
        block_lines = ["⚡ PULSE — Recent Document Changes:"]
        refs = []
        for ds in doc_signals:
            block_lines.append(f"  📄 {ds.get('file_path', '?')} ({ds['repo']})")
            if ds.get("file_path"):
                refs.append(ds["file_path"])
        block_lines.append("")
        lines.extend(block_lines)
        if _ki is not None:
            _ki.record(
                "pulse.doc_change",
                "\n".join(block_lines),
                file_refs=refs,
                session_id=session_id,
                project=scope_repo,
            )

    return "\n".join(lines)


# ── PULSE data for DREAM (used by dream.py) ─────────────────────────────────

def get_dream_input(hours: int = 24) -> dict:
    """
    Package PULSE signals for DREAM consolidation.
    Returns hotspot files, velocity, and doc changes from the last cycle.
    """
    return {
        "hotspots": get_hotspots(hours=hours, limit=10),
        "velocity": get_velocity_summary(hours=hours),
        "doc_changes": get_signals(signal_type="doc_change", limit=10, hours=hours),
        "co_changes": get_co_changes(limit=10),
        "commit_count": get_velocity_summary(hours=hours).get("commits", 0),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """CLI entry point for manual PULSE scan."""
    import sys

    force = "--force" in sys.argv or "-f" in sys.argv
    json_mode = "--json" in sys.argv

    print("[PULSE] Scanning watched repos...")
    summary = scan_repos(force=force)

    if json_mode:
        print(json.dumps(summary, indent=2))
    else:
        print(f"[PULSE] Repos scanned: {summary['repos_scanned']}")
        print(f"[PULSE] New commits:   {summary['new_commits']}")
        print(f"[PULSE] Hotspots:      {summary['hotspots']}")
        print(f"[PULSE] Co-changes:    {summary['co_changes']}")
        print(f"[PULSE] Doc changes:   {summary['doc_changes']}")

        # Show current hotspots
        hotspots = get_hotspots(limit=5)
        if hotspots:
            print("\n[PULSE] Current Hotspots:")
            for h in hotspots:
                print(f"  🔥 {h['file_path']} ({h['repo']}) — churn: {h.get('max_churn', '?')}")

        # Show velocity
        vel = get_velocity_summary(hours=168)
        if vel.get("commits"):
            print(f"\n[PULSE] 7-Day Velocity: {vel['commits']} commits, "
                  f"{vel['unique_authors']} authors, {vel['doc_changes']} doc changes")

    print("[PULSE] Done.")


if __name__ == "__main__":
    main()
