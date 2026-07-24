#!/usr/bin/env python3
"""Lite subset of the Nora factbook write bridge.

This is a REDACTED vendor of the private nora_bridge.py — see
RESYNC-AUDIT.md's "Redaction classes applied — nora_bridge.py" table for the
line-by-line accounting. It ships only the verb closure two Lite MCP tools
need:

  yaml_add_fact   — append one new fact to the project's YAML factbook
                    (id auto-assignment, verify-block validation, atomic
                    write). Called by nora_factbook_add and by the create
                    step of nora_factbook_reverse.
  yaml_supersede  — atomically mark one fact superseded and link its
                    replacement, in a single YAML write. Called by
                    nora_factbook_promote(action="supersede") and by the
                    supersede step of nora_factbook_reverse.

Both are the f389 write-through chokepoint: every YAML mutation in this
file goes through _save_factbook_yaml_atomic, and nowhere else.

Excluded on purpose (see RESYNC-AUDIT.md):
  - Cloud/R2 sync enqueueing, Team-tier compliance-tier gating, and the
    kernora_mode provider-selection import — all Team+/Enterprise surface,
    not part of the Lite (Free) product.
  - The private DB write-through reindex (imports a private-only module,
    nora_context.reindex_factbook_from_yaml, that Lite does not vendor).
    Lite's factbook is YAML-only; there is no SQLite fact-store to keep in
    sync, so this step is dropped rather than shipped as a silently-failing
    import attempt.
  - Every other private bridge verb (search, pending_*, cascade_*, scan_repo,
    extract, forget_*, decision_trace, yaml_promote/retire/unretire/
    set_edges/edit_field, yaml_import_kp) — not needed by any Lite MCP tool
    today. Add them here only when a Lite tool actually calls them (f388 —
    one impl, added when it has a real caller, not speculatively).

Returns JSON to stdout. Exit 0 on success, 1 on error (with JSON error body).
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ─── RMW serialization ──────────────────────────────────────────────────────
# An advisory fcntl.flock held across the full read-modify-write cycle so two
# concurrent bridge invocations against the same factbook can't interleave
# and lose an update. Re-entrant per (thread, nora_dir); released on every
# exit path (see _rmw_verb).
_RMW_LOCK_HANDLES: dict = {}  # (thread_id, str(nora_dir)) -> [fh, refcount]


def _rmw_key(nora_dir):
    import threading
    return (threading.get_ident(), str(nora_dir))


def _acquire_rmw_lock(nora_dir):
    import fcntl
    key = _rmw_key(nora_dir)
    ent = _RMW_LOCK_HANDLES.get(key)
    if ent is not None:            # re-entrant: this THREAD already holds it
        ent[1] += 1
        return
    lock_path = nora_dir / ".factbook.rmw.lock"
    fh = open(lock_path, "a+")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    _RMW_LOCK_HANDLES[key] = [fh, 1]


def _rmw_lock_depth(nora_dir) -> int:
    ent = _RMW_LOCK_HANDLES.get(_rmw_key(nora_dir))
    return ent[1] if ent else 0


def _release_rmw_lock(nora_dir) -> None:
    import fcntl
    key = _rmw_key(nora_dir)
    ent = _RMW_LOCK_HANDLES.get(key)
    if ent is None:                # idempotent: nothing held by this thread → no-op
        return
    ent[1] -= 1
    if ent[1] > 0:
        return
    _RMW_LOCK_HANDLES.pop(key, None)
    try:
        fcntl.flock(ent[0].fileno(), fcntl.LOCK_UN)
        ent[0].close()
    except OSError:
        pass  # process exit releases anyway


def _rmw_verb(fn):
    """Guarantee lock release on EVERY exit path of a mutating verb.

    The verb acquires via _load_factbook_yaml(for_write=True); the happy
    path releases inside _save_factbook_yaml_atomic. This wrapper balances
    the refcount back to its entry value on early returns and exceptions,
    so a failed verb can never leave the process holding the RMW lock.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(project_root, *args, **kwargs):
        nora = Path(project_root) / ".nora"
        depth_before = _rmw_lock_depth(nora)
        try:
            return fn(project_root, *args, **kwargs)
        finally:
            for _ in range(_rmw_lock_depth(nora) - depth_before):
                _release_rmw_lock(nora)

    return wrapper


def _load_factbook_yaml(project_root: Path, for_write: bool = False):
    """Returns (yaml_obj, factbook_path, doc) — doc is a CommentedMap that
    preserves comments, ordering, and multi-line string style on round-trip.

    for_write=True acquires the cross-process RMW lock (released by
    _save_factbook_yaml_atomic). Every mutating caller MUST pass it.
    """
    from ruamel.yaml import YAML

    nora = project_root / ".nora"
    if not nora.is_dir():
        raise FileNotFoundError(f"no .nora/ in {project_root}")
    if for_write:
        _acquire_rmw_lock(nora)
    candidates = sorted(
        [p for p in nora.glob("*-factbook.yaml") if "lite-mode" not in p.name],
        key=lambda p: len(p.name),
    )
    if not candidates:
        raise FileNotFoundError(f"no *-factbook.yaml in {nora}")
    # Picker logic: prefer the file whose stem matches the project root dir
    # name; else the shortest non-empty (non-tombstone) candidate.
    dir_name = project_root.name
    preferred = nora / f"{dir_name}-factbook.yaml"
    if preferred.exists():
        fb_path = preferred
    else:
        import yaml as _pyyaml  # safe_load is fine for the tombstone check
        fb_path = candidates[0]
        for cand in candidates:
            try:
                with cand.open("r") as _f:
                    _doc = _pyyaml.safe_load(_f)
                if _doc and _doc.get("content"):
                    fb_path = cand
                    break
            except Exception:
                pass

    yaml = YAML(typ="rt")  # round-trip mode preserves comments + formatting
    yaml.preserve_quotes = True
    # Convention is mapping=2, sequence=2, offset=0 (outdented-dash style) —
    # NOT the ruamel default, which would corrupt the factbook on re-emit.
    yaml.indent(mapping=2, sequence=2, offset=0)
    yaml.width = 4096  # avoid unwanted line wrapping
    with fb_path.open("r") as f:
        doc = yaml.load(f)
    return yaml, fb_path, doc


def _save_factbook_yaml_atomic(yaml, path: Path, doc) -> None:
    """Atomic write: dump to .tmp in same directory, then os.replace.

    Lite has no SQLite fact-store to reindex and no cloud-sync queue to
    enqueue — the YAML file IS the factbook. Releases the RMW lock on every
    exit path (success or failure).
    """
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(doc, f)
        os.replace(tmp_name, path)
    except Exception:
        try: os.unlink(tmp_name)
        except OSError: pass
        raise
    finally:
        _release_rmw_lock(path.parent)


def _find_fact(doc, fact_id: str):
    """Returns (index, fact_node) or (-1, None) if not found.
    fact_id is the YAML f-number like 'f001' (string).
    """
    content = doc.get("content")
    if not content:
        return -1, None
    for i, f in enumerate(content):
        if isinstance(f, dict) and f.get("id") == fact_id:
            return i, f
    return -1, None


# ── verify-block validation (single impl; called by yaml_add_fact only in
# this Lite subset) ──────────────────────────────────────────────────────
_VERIFY_KINDS = frozenset({"assertion", "test_ref", "examples"})


def _validate_verify_block(verify: object) -> None:
    """Shape-only validation of a `verify` block. Raises ValueError (fail
    loud, never coerce) on any violation. Does NOT parse assertion grammar.
    """
    if not isinstance(verify, dict):
        raise ValueError("verify must be a mapping/object")
    kind = verify.get("kind")
    if kind not in _VERIFY_KINDS:
        raise ValueError(
            f"verify.kind must be one of {sorted(_VERIFY_KINDS)}, got {kind!r}"
        )
    oracle_keys = {k for k in ("assertion", "test_ref", "examples") if k in verify}
    if not oracle_keys:
        raise ValueError(
            f"verify.kind={kind!r} but no oracle sub-key (assertion/test_ref/examples) present"
        )
    if len(oracle_keys) > 1:
        raise ValueError(
            f"verify block has multiple oracle sub-keys {sorted(oracle_keys)} — exactly one allowed"
        )
    present_key = next(iter(oracle_keys))
    if present_key != kind:
        raise ValueError(
            f"verify.kind={kind!r} but oracle sub-key is {present_key!r} — must match"
        )
    if "boundary" in verify and not isinstance(verify["boundary"], list):
        raise ValueError("verify.boundary must be a list of strings")


@_rmw_verb
def yaml_add_fact(project_root: Path) -> dict:
    """Append a new fact to the project's factbook YAML; sourced from stdin JSON.

    The f389 chokepoint entry for Lite. stdin JSON MUST be canonical schema
    (`id`, `statement`, `category`, `scope_level`, `confidence`,
    `review_status`, `origination`); missing optional fields get safe
    defaults; missing required fields return ok=False.

    32 KB stdin cap.
    """
    raw = sys.stdin.read(32 * 1024 + 1)  # +1 to detect overflow
    if len(raw) > 32 * 1024:
        return {"ok": False, "error": "fact JSON exceeds 32 KB cap"}
    try:
        fact = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"stdin JSON parse failed: {e}"}
    if not isinstance(fact, dict):
        return {"ok": False, "error": "stdin must be a JSON object"}
    if not fact.get("statement"):
        return {"ok": False, "error": "fact requires 'statement' field"}

    yaml, fb_path, doc = _load_factbook_yaml(project_root, for_write=True)

    # Auto-assign id when stdin omits it (or sends "auto"). Scan content[]
    # for max fNNN, return max+1 with 3-digit padding.
    fact_id = fact.get("id")
    if not fact_id or fact_id == "auto":
        existing = doc.get("content", []) or []
        max_n = 0
        for entry in existing:
            if not isinstance(entry, dict):
                continue
            m = re.match(r"^f(\d+)$", str(entry.get("id", "")))
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
        fact["id"] = f"f{max_n + 1:03d}"

    # Reject duplicate fact_id — the f### namespace is append-only via this verb.
    existing_idx, _existing = _find_fact(doc, fact["id"])
    if existing_idx >= 0:
        return {"ok": False, "error": f"fact_id {fact['id']} already exists in {fb_path}"}

    # Whitelist canonical fields — refuse foreign keys to keep the schema clean.
    canonical = {
        "id":            fact["id"],
        "statement":     fact["statement"],
        "category":      fact.get("category", "pattern"),
        "scope_level":   fact.get("scope_level", "project"),
        "confidence":    float(fact.get("confidence", 0.7)),
        "review_status": fact.get("review_status", "candidate"),
        "origination":   fact.get("origination", "mcp"),
    }
    for _opt_field in ("verify", "applies_to", "rationale", "alternatives", "attribution", "sources"):
        if _opt_field in fact:
            canonical[_opt_field] = fact[_opt_field]
    if "verify" in canonical:
        try:
            _validate_verify_block(canonical["verify"])
        except ValueError as _ve:
            return {"ok": False, "error": f"verify block invalid: {_ve}"}

    # "A factlet with no source is an opinion" — WARN, never reject: this is
    # the only manual-add path Lite has, and a hard reject with no UI source
    # field would break it outright.
    _srcs_raw = canonical.get("sources")
    if isinstance(_srcs_raw, str):
        _has_sources = bool(_srcs_raw.strip())
    elif isinstance(_srcs_raw, list):
        _has_sources = any(str(_s).strip() for _s in _srcs_raw)
    else:
        _has_sources = False
    _needs_source = not _has_sources
    if _needs_source:
        print(
            f"[SOURCELESS-ADD] yaml_add_fact: fact_id={fact['id']!r} "
            f"project_root={project_root} has no 'sources' — will render as "
            f"unsourced/low-trust downstream.",
            file=sys.stderr,
        )
    doc.setdefault("content", []).append(canonical)
    _save_factbook_yaml_atomic(yaml, fb_path, doc)
    _res = {"ok": True, "fact_id": fact["id"], "path": str(fb_path)}
    if _needs_source:
        _res["needs_source"] = True
    return _res


@_rmw_verb
def yaml_supersede(
    project_root: Path,
    old_id: str,
    new_id: str,
    reason: str = "superseded",
    valid_until: str | None = None,
    valid_from: str | None = None,
) -> dict:
    """Atomically supersede old_id with new_id in the YAML factbook.

    Single atomic write for BOTH nodes via ONE _save_factbook_yaml_atomic
    call — one os.replace, no half-supersession window.

    Mutations applied in-memory before the single save:
      old fact: superseded_by=new_id, valid_until=valid_until (or now),
                retire_reason=reason
      new fact: supersedes=old_id, valid_from=valid_from (or now)

    Returns:
      {"ok": True, "old_id": ..., "new_id": ..., "path": ...}
      {"ok": False, "error": ..., "which": "old"|"new"|"both"}
    """
    now_iso = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    vu = valid_until or now_iso
    vf = valid_from or now_iso

    yaml, fb_path, doc = _load_factbook_yaml(project_root, for_write=True)

    _, old_fact = _find_fact(doc, old_id)
    _, new_fact = _find_fact(doc, new_id)

    missing = []
    if old_fact is None:
        missing.append("old")
    if new_fact is None:
        missing.append("new")
    if missing:
        which = "both" if len(missing) == 2 else missing[0]
        ids_str = old_id if which == "old" else (new_id if which == "new" else f"{old_id},{new_id}")
        return {
            "ok": False,
            "error": f"fact_id not found in {fb_path}: {ids_str}",
            "which": which,
        }

    old_fact["superseded_by"] = new_id
    old_fact["valid_until"] = vu
    old_fact["retire_reason"] = reason

    new_fact["supersedes"] = old_id
    if new_fact.get("valid_from") is None:
        new_fact["valid_from"] = vf

    _save_factbook_yaml_atomic(yaml, fb_path, doc)

    return {
        "ok": True,
        "old_id": old_id,
        "new_id": new_id,
        "valid_until": vu,
        "valid_from": new_fact["valid_from"],
        "path": str(fb_path),
    }


def main() -> int:
    p = argparse.ArgumentParser(prog="nora_bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("yaml_add_fact",
                           help="Append a new fact to the YAML factbook (canonical schema via stdin JSON, 32 KB cap)")
    p_add.add_argument("project_root")

    p_sup = sub.add_parser("yaml_supersede",
                           help="Atomically supersede old_id with new_id in the YAML factbook")
    p_sup.add_argument("project_root")
    p_sup.add_argument("old_id", help="fact_id of the fact being superseded")
    p_sup.add_argument("new_id", help="fact_id of the superseding fact")
    p_sup.add_argument("--reason", default="superseded",
                       help="Retire reason written to the old fact's retire_reason field")
    p_sup.add_argument("--valid-until", default=None,
                       help="Timestamp to close old interval (default: now)")
    p_sup.add_argument("--valid-from", default=None,
                       help="Timestamp to open new interval (default: now)")

    args = p.parse_args()

    try:
        if args.cmd == "yaml_add_fact":
            payload = yaml_add_fact(Path(args.project_root))
        elif args.cmd == "yaml_supersede":
            payload = yaml_supersede(
                Path(args.project_root),
                old_id=args.old_id,
                new_id=args.new_id,
                reason=args.reason,
                valid_until=getattr(args, "valid_until", None),
                valid_from=getattr(args, "valid_from", None),
            )
        else:
            payload = {"error": f"unknown command: {args.cmd}"}
            print(json.dumps(payload))
            return 1
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return 1

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
