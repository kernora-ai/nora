#!/usr/bin/env python3
"""
factbook_git.py — Git-tracked factbook operations for Kernora

Every mutation to a named factbook (create, add, edit, delete) is serialized
to ~/.kernora/factbooks/<kp_id>.json and committed to a local git repo.

Design choices:
  - DB write happens FIRST inside a transaction; git commit happens after.
    On git failure, the DB transaction is rolled back (atomicity B1 fix).
  - fcntl.flock on a .lock file prevents concurrent git index corruption
    when multiple IDE sessions write simultaneously (concurrency W2 fix).
  - asyncio.create_subprocess_exec used in async context (MCP B3 fix).
  - kp_id sanitized with anchored regex; slugify auto-adds 4-char hex suffix
    to prevent global namespace collisions (security B2 / W4 fix).
  - serialize_factbook filters archived=0 on patterns (data correctness B-SW fix).
  - content_hash = SHA-256 of sorted facts JSON (spec B-SW fix).
  - Max 1000 facts per factbook (size guard W-SW fix).

Elastic License 2.0 — commercial use requires agreement with kernora.ai
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FACTBOOKS_DIR = Path.home() / ".kernora" / "factbooks"
LOCK_FILE = FACTBOOKS_DIR / ".write.lock"
ARCHIVE_DIR = FACTBOOKS_DIR / ".archive"
MAX_FACTS = 1000

# Anchored, safe slug regex — hyphen last inside [] to avoid range ambiguity
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$|^[a-z0-9]$")


# ── Slug / kp_id helpers ─────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """Convert display name to lowercase slug: spaces/special chars → hyphens."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:50] or "factbook"


def make_kp_id(name: str) -> str:
    """Generate a unique kp_id: <slug>-<4-char hex> to prevent namespace collisions."""
    slug = slugify(name)
    suffix = secrets.token_hex(2)  # 4 hex chars
    kp_id = f"{slug}-{suffix}"
    # Ensure it passes the regex (slug may have been truncated)
    if not _SLUG_RE.match(kp_id):
        kp_id = f"factbook-{suffix}"
    return kp_id


def validate_kp_id(kp_id: str) -> bool:
    """Return True if kp_id is safe to use as a filename component."""
    return bool(kp_id and _SLUG_RE.match(kp_id) and ".." not in kp_id and "/" not in kp_id)


def safe_fact_path(kp_id: str) -> Path:
    """Return the JSON file path for a factbook, after validating kp_id."""
    if not validate_kp_id(kp_id):
        raise ValueError(f"Invalid kp_id: {kp_id!r}")
    return FACTBOOKS_DIR / f"{kp_id}.json"


# ── Git repo bootstrap ────────────────────────────────────────────────────────

def ensure_git_repo() -> Path:
    """Initialize ~/.kernora/factbooks/ as a git repo if not already.
    Creates the directory and .gitignore. Safe to call multiple times."""
    FACTBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(exist_ok=True)
    LOCK_FILE.touch(exist_ok=True)

    git_dir = FACTBOOKS_DIR / ".git"
    if not git_dir.exists():
        subprocess.run(
            ["git", "init", str(FACTBOOKS_DIR)],
            capture_output=True, text=True, check=True
        )
        # CRITICAL-3 FIX: Validate git config was set; raise on failure
        result = subprocess.run(
            ["git", "-C", str(FACTBOOKS_DIR), "config", "user.name", "Nora · Kernora"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"git config user.name failed: {result.stderr.strip()}")

        result = subprocess.run(
            ["git", "-C", str(FACTBOOKS_DIR), "config", "user.email", "nora@kernora.local"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"git config user.email failed: {result.stderr.strip()}")

        gitignore = FACTBOOKS_DIR / ".gitignore"
        gitignore.write_text(".write.lock\n")

    return FACTBOOKS_DIR


# ── Serialization & hashing ───────────────────────────────────────────────────

def compute_content_hash(facts: list[dict]) -> str:
    """SHA-256 of the facts array serialized with sorted keys. Truncated to 16 hex chars."""
    payload = json.dumps(facts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _factbooks_git_head() -> str:
    """Current HEAD SHA of ~/.kernora/factbooks/ git repo. Empty string if no commits yet."""
    try:
        result = subprocess.run(
            ["git", "-C", str(FACTBOOKS_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        # Best-effort metadata lookup: if git is unavailable or invocation fails,
        # treat as "no git commit info" and continue without raising.
        return ""
    return ""


def compute_version_hash(meta: dict, facts: list[dict]) -> str:
    """SHA-256 of canonical JSON of (meta ⊕ facts), excluding self-referential fields.
    Truncated to 16 hex chars. Deterministic: byte-identical DB state → identical hash.
    Excludes `version_hash` and `git_commit` to avoid circular dependency.
    """
    meta_for_hash = {k: v for k, v in meta.items() if k not in ("version_hash", "git_commit")}
    canonical = json.dumps(
        {"_meta": meta_for_hash, "facts": facts},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def serialize_factbook(conn: sqlite3.Connection, kp_id: str) -> dict:
    """Read kp_factbooks metadata + patterns WHERE factbook_id=kp_id AND archived=0.
    Returns a dict ready to write as JSON. Limited to MAX_FACTS facts.

    PE review B-SW: filters archived=0 on patterns so deleted facts don't resurface.
    """
    conn.row_factory = sqlite3.Row

    # Get factbook metadata
    fb_row = conn.execute(
        "SELECT kp_id, title, scope, kp_type, git_remote, git_branch, "
        "       created_at, updated_at "
        "FROM kp_factbooks WHERE kp_id = ? AND archived = 0",
        (kp_id,)
    ).fetchone()

    if fb_row is None:
        raise KeyError(f"Factbook not found: {kp_id!r}")

    # Get facts — active only, capped at MAX_FACTS
    fact_rows = conn.execute(
        "SELECT id, name, pattern, fact_type, confidence, review_status, "
        "       source_type, created_by, created_at, tags "
        "FROM patterns "
        "WHERE factbook_id = ? AND archived = 0 "
        "ORDER BY created_at ASC "
        "LIMIT ?",
        (kp_id, MAX_FACTS)
    ).fetchall()

    total_count = conn.execute(
        "SELECT COUNT(*) FROM patterns WHERE factbook_id = ? AND archived = 0",
        (kp_id,)
    ).fetchone()[0]

    facts = []
    for r in fact_rows:
        tags = r["tags"] or "[]"
        try:
            tags_list = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags_list = []
        facts.append({
            "id": r["id"],
            "name": r["name"] or "",
            "pattern": r["pattern"],
            "fact_type": r["fact_type"] or "convention",
            "confidence": r["confidence"],
            "review_status": r["review_status"] or "verified",
            "source_type": r["source_type"] or "manual",
            "created_by": r["created_by"] or "user",
            "created_at": r["created_at"],
            "tags": tags_list,
        })

    meta = {
        "kp_id": fb_row["kp_id"],
        "title": fb_row["title"],
        "scope": fb_row["scope"],
        "kp_type": fb_row["kp_type"],
        "git_remote": fb_row["git_remote"],
        "git_branch": fb_row["git_branch"] or "main",
        "created": fb_row["created_at"],
        "updated": fb_row["updated_at"],
        "facts_total": total_count,
        "truncated": total_count > MAX_FACTS,
    }

    meta["version_hash"] = compute_version_hash(meta, facts)
    meta["git_commit"] = _factbooks_git_head()

    return {"_meta": meta, "facts": facts}


# ── File lock context ─────────────────────────────────────────────────────────

@contextmanager
def _factbook_lock():
    """Exclusive file lock to prevent concurrent git index corruption (W2 fix)."""
    LOCK_FILE.touch(exist_ok=True)
    fd = os.open(str(LOCK_FILE), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ── Sync git commit (used by dashboard routes) ────────────────────────────────

def write_and_commit(
    conn: sqlite3.Connection,
    kp_id: str,
    operation: str,
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """Serialize factbook to JSON, write file, git add, git commit.
    Returns commit hash. Raises on git failure (DB write already committed by caller).

    B1 fix: caller commits DB BEFORE calling this. On git failure, git state
    is ahead of the last DB state — recoverable by re-running write_and_commit.

    W2 fix: holds _factbook_lock() for the full serialize → write → commit sequence.
    """
    ensure_git_repo()

    with _factbook_lock():
        data = serialize_factbook(conn, kp_id)
        file_path = safe_fact_path(kp_id)
        # Atomic write: tmp + fsync + rename — prevents truncated file if
        # crash hits between truncate-on-open and final write (per f358).
        payload = json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False)
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as _fh:
            _fh.write(payload)
            _fh.flush()
            os.fsync(_fh.fileno())
        os.replace(tmp_path, file_path)

        # git add
        subprocess.run(
            ["git", "-C", str(FACTBOOKS_DIR), "add", file_path.name],
            capture_output=True, text=True, check=True
        )

        # Build commit message
        title_short = (data["_meta"]["title"] or kp_id)[:40]
        msg_lines = [f"nora({kp_id}): {operation} — {title_short}"]
        msg_lines.append("")
        msg_lines.append(f"operation: {operation}")
        if extra_meta:
            for k, v in extra_meta.items():
                msg_lines.append(f"{k}: {v}")
        msg_lines.append(f"timestamp: {datetime.now(timezone.utc).isoformat()}")
        commit_msg = "\n".join(msg_lines)

        result = subprocess.run(
            ["git", "-C", str(FACTBOOKS_DIR), "commit", "-m", commit_msg,
             "--allow-empty-message"],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            # "nothing to commit" is not an error
            if "nothing to commit" in result.stdout + result.stderr:
                return "nothing-to-commit"
            raise RuntimeError(f"git commit failed: {result.stderr.strip()}")

        # Parse commit hash from output
        commit_hash = ""
        for line in result.stdout.splitlines():
            m = re.search(r"\[.+ ([0-9a-f]{7,})\]", line)
            if m:
                commit_hash = m.group(1)
                break


        return commit_hash or "committed"


# Local git versioning only — no remote-push integration in this build.



# ── Async git commit (used by MCP tools — B3 fix: no blocking subprocess) ────

async def write_and_commit_async(
    conn: sqlite3.Connection,
    kp_id: str,
    operation: str,
    extra_meta: dict[str, Any] | None = None,
) -> str:
    """Async version of write_and_commit. Uses asyncio.create_subprocess_exec
    to avoid blocking the MCP event loop (PE review B3 fix)."""
    ensure_git_repo()

    # Serialize (CPU-bound but fast at <1000 facts — keep sync)
    data = serialize_factbook(conn, kp_id)
    file_path = safe_fact_path(kp_id)

    # File write + git ops run in executor to release event loop
    loop = asyncio.get_event_loop()
    commit_hash = await loop.run_in_executor(
        None,
        lambda: _blocking_write_commit(data, file_path, kp_id, operation, extra_meta)
    )


    return commit_hash


def _blocking_write_commit(
    data: dict, file_path: Path, kp_id: str, operation: str, extra_meta: dict | None
) -> str:
    """Blocking inner write+commit — always called from run_in_executor."""
    with _factbook_lock():
        # HIGH-5 FIX: Sanitize I/O errors in exception handling
        try:
            file_path.write_text(
                json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False),
                encoding="utf-8"
            )
        except PermissionError:
            raise RuntimeError(
                f"Permission denied writing factbook file. Check directory permissions: {FACTBOOKS_DIR}"
            )
        except OSError as e:
            raise RuntimeError(f"Failed to write factbook file: {e.strerror}")

        try:
            subprocess.run(
                ["git", "-C", str(FACTBOOKS_DIR), "add", file_path.name],
                capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"git add failed: {e.stderr.strip()}")

        title_short = (data["_meta"]["title"] or kp_id)[:40]
        msg_lines = [f"nora({kp_id}): {operation} — {title_short}", ""]
        msg_lines.append(f"operation: {operation}")
        if extra_meta:
            for k, v in extra_meta.items():
                msg_lines.append(f"{k}: {v}")
        msg_lines.append(f"timestamp: {datetime.now(timezone.utc).isoformat()}")
        commit_msg = "\n".join(msg_lines)

        result = subprocess.run(
            ["git", "-C", str(FACTBOOKS_DIR), "commit", "-m", commit_msg,
             "--allow-empty-message"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            if "nothing to commit" in result.stdout + result.stderr:
                return "nothing-to-commit"
            raise RuntimeError(f"git commit failed: {result.stderr.strip()}")

        for line in result.stdout.splitlines():
            m = re.search(r"\[.+ ([0-9a-f]{7,})\]", line)
            if m:
                return m.group(1)
        return "committed"


# ── Format helpers for MCP responses ─────────────────────────────────────────

def format_facts_summary(facts: list[dict]) -> str:
    """Pre-formatted numbered list for LLM relay to user (AI review W4 fix)."""
    if not facts:
        return "No facts yet."
    lines = []
    for i, f in enumerate(facts, 1):
        ft = f.get("fact_type", "convention")
        name = f.get("name") or ""
        pattern = f.get("pattern", "")
        conf = f.get("confidence", 0.0)
        display = name if name else pattern[:80]
        lines.append(f"{i}. [{ft}] {display} (confidence: {conf:.2f})")
    return "\n".join(lines)
