# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""Append-only JSONL log writers — engagement events + factbook audit.

Lite mode writes here instead of SQLite. Companion mode writes BOTH
(SQLite + JSONL) — JSONL is the durable, portable, git-frienlyish archive
that survives DB resets and migrates with the home dir.

Atomic append via flock on a sidecar lockfile (lf002) — same primitive as
vocabulary.save_vocabulary at vocabulary.py:95-138. Direct file open + write
is FORBIDDEN (lf105) — concurrent +nora calls would interleave bytes mid-line.

File layout under ~/.kernora/:
  engagement_events.jsonl     — one line per +nora hook fire (success/abstain)
  engagement_events.jsonl.lock — sidecar lockfile (zero-byte)
  engagement_events.jsonl.1..5 — rotated archives (50 MB each, KEEP_ROTATIONS=5)
  factbook_audit.jsonl        — one line per add/update/delete/retire/undo
  injection_events.jsonl      — one line per context-injection event, across
                                 EVERY injection channel (session-start
                                 patterns, prompt-submit ambient/legacy
                                 recall, f371 public-portable trigger).
                                 {ts, channel, project, repo_root, trigger,
                                 fact_ids}. Foundation for the
                                 shown-vs-rediscovered effectiveness signal
                                 (R7) and the forensic trail for
                                 cross-project contamination bugs (field
                                 report, Jivant iOS, 2026-07-19).

Read helpers (read_engagement / read_audit / read_injection_events) skip
malformed lines so a single bad write never bricks the reader.
"""
from __future__ import annotations
import contextlib
import fcntl
import json
import os
import time
from pathlib import Path

KERNORA_HOME = Path(os.environ.get("KERNORA_HOME") or (Path.home() / ".kernora"))
ENGAGEMENT_PATH = KERNORA_HOME / "engagement_events.jsonl"
AUDIT_PATH = KERNORA_HOME / "factbook_audit.jsonl"
INJECTION_PATH = KERNORA_HOME / "injection_events.jsonl"

MAX_BYTES = 50 * 1024 * 1024  # 50 MB → rotate
KEEP_ROTATIONS = 5


def _resolve_paths() -> tuple[Path, Path]:
    """Re-read KERNORA_HOME each call so tests overriding the env var are honored."""
    home = Path(os.environ.get("KERNORA_HOME") or (Path.home() / ".kernora"))
    return (home / "engagement_events.jsonl", home / "factbook_audit.jsonl")


def _resolve_injection_path() -> Path:
    """Re-read KERNORA_HOME each call so tests overriding the env var are honored."""
    home = Path(os.environ.get("KERNORA_HOME") or (Path.home() / ".kernora"))
    return home / "injection_events.jsonl"


def _append(path: Path, record: dict) -> None:
    """Atomic append-one-line-of-JSON via flock on a sidecar lockfile (lf002, lf105)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lockfile = Path(str(path) + ".lock")
    fd = os.open(str(lockfile), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        # Rotate if too big — checked under the same lock so two writers don't
        # both rename the file.
        if path.exists() and path.stat().st_size >= MAX_BYTES:
            _rotate(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _rotate(path: Path) -> None:
    """Rotate path → path.1, path.1 → path.2, etc. KEEP_ROTATIONS deep."""
    # Walk highest → lowest so we never overwrite a file we still need.
    for i in range(KEEP_ROTATIONS - 1, 0, -1):
        src = Path(str(path) + f".{i}")
        dst = Path(str(path) + f".{i + 1}")
        if src.exists():
            src.rename(dst)
    # Now shift the live file to .1
    if path.exists():
        path.rename(Path(str(path) + ".1"))
    # Trim oldest beyond KEEP_ROTATIONS — the rotation above already moved
    # path.{KEEP_ROTATIONS} → path.{KEEP_ROTATIONS+1}; delete that overflow.
    too_old = Path(str(path) + f".{KEEP_ROTATIONS + 1}")
    if too_old.exists():
        too_old.unlink()


def append_engagement(*, fact_ids, outcome, latency_ms,
                      tokens_added: int = 0, project_hash: str = "") -> None:
    """One JSONL line per +nora hook fire.

    fact_ids: list of fact rowids actually injected (empty on abstain/timeout/error)
    outcome: 'accepted' | 'abstained' | 'timeout' | 'dropped_all_pii' |
             'pii_scanner_unavailable' | 'error' | <other string from caller>
    latency_ms: end-to-end retrieval latency (int)
    tokens_added: rough token count (chars / 4) of the injected payload
    project_hash: SHA256-truncated canonical project key (no path leakage)
    """
    eng_path, _ = _resolve_paths()
    _append(eng_path, {
        "ts":           int(time.time()),
        "fact_ids":     list(fact_ids or []),
        "outcome":      outcome,
        "latency_ms":   int(latency_ms or 0),
        "tokens_added": int(tokens_added or 0),
        "project_hash": project_hash or "",
    })


def append_audit(*, op: str, fact_id, before=None, after=None,
                 source: str = "cli", reason: str = "") -> None:
    """One JSONL line per factbook write.

    op: 'add' | 'update' | 'delete' | 'retire' | 'undo' (or other verbs)
    fact_id: int or str — whatever identifies the fact in the source store
    before / after: optional dicts capturing the change (truncated by caller)
    source: where the write originated ('cli' | 'mcp' | 'dashboard' | ...)
    reason: free-text justification, truncated to 300 chars
    """
    _, aud_path = _resolve_paths()
    _append(aud_path, {
        "ts":      int(time.time()),
        "op":      op,
        "fact_id": fact_id,
        "before":  before,
        "after":   after,
        "source":  source,
        "reason":  (reason[:300] if reason else ""),
    })


def append_injection_event(*, channel: str, project: str = "", repo_root: str = "",
                           trigger: str = "", fact_ids=None) -> None:
    """One JSONL line per context-injection event, across EVERY injection
    channel — not just the +nora engagement flow that append_engagement
    covers. Added 2026-07-19 (field report, Jivant iOS): the prior state was
    hook_events recording only a bare count ("Injected N patterns", no ids)
    for the legacy recall path, and f371 injections not logged at all —
    which meant a cross-project contamination bug (kernora facts injected
    into an unrelated repo) left no forensic trail.

    channel:    caller label, e.g. 'session_start' | 'promptsubmit_ambient'
                | 'promptsubmit_plus_nora' | 'promptsubmit_legacy' | 'f371'
    project:    canonical_project() value for the active session, if resolved
    repo_root:  cwd the hook ran in (raw, not canonicalized — for forensic
                diffing between sibling checkouts sharing a project name)
    trigger:    short reason the injection fired (trigger phrase / query)
    fact_ids:   list of fact/factlet rowids actually shown to the user
    """
    _append(_resolve_injection_path(), {
        "ts":        int(time.time()),
        "channel":   channel,
        "project":   project or "",
        "repo_root": repo_root or "",
        "trigger":   (trigger or "")[:200],
        "fact_ids":  list(fact_ids or []),
    })


def read_injection_events(since_days: int = 7) -> list[dict]:
    """Return list of injection-event records from the last `since_days`
    days. Malformed lines silently skipped (lf302 — defensive read)."""
    path = _resolve_injection_path()
    if not path.exists():
        return []
    cutoff = int(time.time() - since_days * 86400)
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("ts", 0) >= cutoff:
            out.append(r)
    return out


def read_engagement(since_days: int = 7) -> list[dict]:
    """Return list of engagement records from the last `since_days` days.
    Malformed lines silently skipped (lf302 — defensive read)."""
    eng_path, _ = _resolve_paths()
    if not eng_path.exists():
        return []
    cutoff = int(time.time() - since_days * 86400)
    out = []
    for line in eng_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("ts", 0) >= cutoff:
            out.append(r)
    return out


def read_audit(since_days: int = 30) -> list[dict]:
    """Return list of audit records from the last `since_days` days."""
    _, aud_path = _resolve_paths()
    if not aud_path.exists():
        return []
    cutoff = int(time.time() - since_days * 86400)
    out = []
    for line in aud_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("ts", 0) >= cutoff:
            out.append(r)
    return out
