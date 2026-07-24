#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
"""
kernora_injection.py — record + aggregate injection events ($50-5, #48).

Every time Nora surfaces context into a session (PULSE hotspots,
patterns, decisions, factbook content) we want to know:
  "Injected 40×, accepted 12× → precision 30%."

This module owns:
  - record(source, snippet, file_refs, session_id=None, project=None, fact_id=None)
    — append a row to injection_events
  - mark_accepted(event_id, reason)  — bit-flip once the classifier decides
  - mark_rejected(event_id, reason)
  - precision_by_source(days=30) → {source: {count, accepted, precision}}
  - recent_injections(limit=50) → rows for dashboard

Acceptance detection (v0.1 heuristic):
  After a session ends, a post-session classifier walks session_insights
  + file edits; an injection is "accepted" if any file listed in
  file_refs_json was edited or read within the same session. Otherwise
  flagged "rejected" on session end. This module exposes the flip API;
  the classifier itself is wired in as a separate follow-up hook.

The record() surface is defensive — failures (DB missing, etc.) NEVER
break the hook path. A missing injection_events table is a no-op.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

DB_PATH = Path.home() / ".kernora" / "echo.db"

VALID_SOURCES = (
    "pulse.hotspots",
    "pulse.co_change",
    "pulse.doc_change",
    "patterns.topN",
    "decisions.recent",
    "bugs.recent",
    "factbook.inject",
    "onboard.hint",
    "pretool.guardrail",
    "other",
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection | None:
    """Open echo.db without raising if the file is absent (hook-safe)."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=3.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


# ─── Record ──────────────────────────────────────────────────────────────────


def record(
    source: str,
    snippet: str,
    file_refs: Iterable[str] | None = None,
    *,
    session_id: str | None = None,
    project: str | None = None,
    fact_id: int | None = None,
) -> int | None:
    """Log one injection event. Returns the inserted row's id, or None on failure.

    Never raises — injection tracking must not break the surfacing path.
    """
    if source not in VALID_SOURCES:
        # Accept but tag as 'other' so we don't drop the event
        source = "other"

    conn = _connect()
    if conn is None:
        return None
    try:
        # Table may not exist on older installs; migration 0004 adds it
        cur = conn.execute(
            "INSERT INTO injection_events "
            "(ts, session_id, project, source, fact_id, snippet, file_refs_json, "
            " accepted, acceptance_signal, classified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
            (
                _iso_now(),
                session_id,
                project,
                source,
                fact_id,
                (snippet or "")[:400],
                json.dumps(list(file_refs or [])),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def mark_accepted(event_id: int, reason: str = "") -> bool:
    return _mark(event_id, accepted=1, reason=reason)


def mark_rejected(event_id: int, reason: str = "") -> bool:
    return _mark(event_id, accepted=0, reason=reason)


def _mark(event_id: int, *, accepted: int, reason: str) -> bool:
    conn = _connect()
    if conn is None:
        return False
    try:
        cur = conn.execute(
            "UPDATE injection_events "
            "SET accepted = ?, acceptance_signal = ?, classified_at = ? "
            "WHERE id = ?",
            (accepted, reason[:200], _iso_now(), event_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


# ─── Aggregate ───────────────────────────────────────────────────────────────


def precision_by_source(days: int = 30) -> dict[str, dict]:
    """Per-source {count, accepted, rejected, unclassified, precision}.

    precision = accepted / (accepted + rejected); NaN-safe when denom is 0.
    Unclassified rows are not counted in the denominator so precision only
    reflects events where a decision exists.
    """
    conn = _connect()
    if conn is None:
        return {}
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = conn.execute(
            "SELECT source, "
            "       COUNT(*) AS total, "
            "       SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) AS accepted, "
            "       SUM(CASE WHEN accepted = 0 THEN 1 ELSE 0 END) AS rejected, "
            "       SUM(CASE WHEN accepted IS NULL THEN 1 ELSE 0 END) AS unclassified "
            "FROM injection_events WHERE ts >= ? "
            "GROUP BY source",
            (since,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()

    out: dict[str, dict] = {}
    for r in rows:
        acc = int(r["accepted"] or 0)
        rej = int(r["rejected"] or 0)
        denom = acc + rej
        precision = (acc / denom) if denom > 0 else None
        out[r["source"]] = {
            "total": int(r["total"]),
            "accepted": acc,
            "rejected": rej,
            "unclassified": int(r["unclassified"] or 0),
            "precision": precision,
        }
    return out


def recent_injections(limit: int = 50) -> list[dict]:
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, ts, session_id, project, source, fact_id, snippet, "
            "       file_refs_json, accepted, acceptance_signal, classified_at "
            "FROM injection_events ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ─── Acceptance classifier (v0.1 heuristic) ──────────────────────────────────


def classify_session(session_id: str, edited_files: Iterable[str]) -> int:
    """Classify all unclassified injections for `session_id`.

    Accepted iff one of the injection's file_refs intersects edited_files.
    Rejected otherwise. Returns the number of rows classified.
    """
    conn = _connect()
    if conn is None:
        return 0
    edited = {str(p) for p in edited_files}
    try:
        rows = conn.execute(
            "SELECT id, file_refs_json FROM injection_events "
            "WHERE session_id = ? AND accepted IS NULL",
            (session_id,),
        ).fetchall()
        updated = 0
        for r in rows:
            try:
                refs = json.loads(r["file_refs_json"] or "[]")
            except (json.JSONDecodeError, TypeError):
                refs = []
            intersect = [f for f in refs if f in edited]
            if intersect:
                reason = f"edited {len(intersect)} referenced file(s)"
                _mark_inline(conn, r["id"], accepted=1, reason=reason)
            else:
                _mark_inline(conn, r["id"], accepted=0,
                             reason="no referenced files touched")
            updated += 1
        conn.commit()
        return updated
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _mark_inline(conn: sqlite3.Connection, event_id: int, *, accepted: int, reason: str) -> None:
    conn.execute(
        "UPDATE injection_events "
        "SET accepted = ?, acceptance_signal = ?, classified_at = ? "
        "WHERE id = ?",
        (accepted, reason[:200], _iso_now(), event_id),
    )


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _fmt_precision(p: float | None) -> str:
    return f"{p*100:.0f}%" if isinstance(p, float) else "—"


def _cmd_stats(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="kernora precision stats")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    stats = precision_by_source(days=args.days)
    if args.json:
        print(json.dumps(stats, indent=2))
        return 0

    if not stats:
        print(f"No injection events in last {args.days}d "
              "(or migration 0004 not applied).")
        return 0

    print(f"Injection precision · last {args.days}d")
    print(f"  {'source':<22} {'total':>6} {'acc':>5} {'rej':>5} {'??':>5} {'prec':>6}")
    print(f"  {'-'*22} {'-'*6} {'-'*5} {'-'*5} {'-'*5} {'-'*6}")
    total_acc = 0
    total_rej = 0
    for src in sorted(stats.keys()):
        d = stats[src]
        total_acc += d["accepted"]
        total_rej += d["rejected"]
        print(f"  {src:<22} {d['total']:>6} {d['accepted']:>5} "
              f"{d['rejected']:>5} {d['unclassified']:>5} "
              f"{_fmt_precision(d['precision']):>6}")
    overall = total_acc / (total_acc + total_rej) if (total_acc + total_rej) else None
    print()
    print(f"  Overall precision: {_fmt_precision(overall)} "
          f"(acc={total_acc}, rej={total_rej})")
    return 0


def _cmd_recent(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="kernora precision recent")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rows = recent_injections(limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No injection events recorded yet.")
        return 0
    print(f"Recent injections (last {len(rows)}):")
    for r in rows:
        status = "✓" if r["accepted"] == 1 else "✗" if r["accepted"] == 0 else "?"
        snippet = (r["snippet"] or "").replace("\n", " ")[:70]
        print(f"  {status}  {r['ts'][:19]}  {r['source']:<20}  {snippet}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    sub = argv[0]
    if sub == "stats":
        return _cmd_stats(argv[1:])
    if sub == "recent":
        return _cmd_recent(argv[1:])
    print(f"unknown subcommand: {sub}", file=sys.stderr)
    print("supported: stats, recent", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
