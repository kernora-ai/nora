# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""
Kernora factbook telemetry.

Lightweight, fire-and-forget citation tracking. Call from anywhere:

    import factbook_telemetry as ft
    ft.factlet_cite(['f097', 'f099'], source='analyzer', session_id=sid)
    ft.factbook_load(session_id, 'project:kernora', factlet_count=81)

All writes are async — caller never blocks. If the queue is full, the
citation is silently dropped (warn to stderr). A background daemon thread
is started on first import; nothing else required.
"""
import hashlib
import queue
import re
import sys
import threading
from datetime import date, datetime, timezone
from typing import Optional, Union

_Q: queue.Queue = queue.Queue(maxsize=1000)
_started = False
_lock    = threading.Lock()

# FIELD-FIX (2026-07-23, usage-report audit; REVISED same day per founder
# correction): factlet_citations was found polluted by MANUAL-PROBE hook
# runs — f093 had 15 citations across 15 DISTINCT session_ids under
# manual-probe-shaped prefixes ('ambient-iso-...', 'verify-...',
# 'repro-...', etc.), which is exactly the DISTINCT-session_id count the
# fast-track promote-on-cite threshold (db.promote_fast_track_citations)
# reads — so a fact could FALSELY promote to 'reinforced' purely from
# test traffic, never from a real user session.
#
# IMPORTANT — 'agent-*' is NOT in this exclusion set. Original draft of
# this fix excluded 'agent-*' from RECORDING too; founder caught that as
# over-broad: 'agent-*' session_ids are REAL subagents doing real
# grounding work, and their citations are legitimate cross-agent-relay
# signal that MUST be recorded. Only manual-probe prefixes (the founder's
# own ad-hoc test/audit session_ids) are excluded here. The DISTINCT-
# session multi-count risk from parallel subagent fan-out is handled
# separately, at the PROMOTION count in db.py (see db._AGENT_SESSION_ID_RE
# and _is_synthetic_session_id there) — NOT by refusing to record.
_MANUAL_PROBE_SESSION_ID_RE = re.compile(
    r"^(ambient-iso-|verify-|repro-|rv-|walkcheck|demo-|probe-)"
    r"|test",
    re.IGNORECASE,
)


def _is_synthetic_session_id(session_id: Optional[str]) -> bool:
    """True if `session_id` looks like a MANUAL-PROBE hook run (the
    founder's own ad-hoc test/audit session_ids) rather than a real
    session. Deliberately does NOT match 'agent-*' — real subagents must
    be recorded (see module comment above for the founder correction).
    """
    if not session_id:
        return False
    try:
        return bool(_MANUAL_PROBE_SESSION_ID_RE.search(session_id))
    except Exception:
        return False

# ── Background writer ────────────────────────────────────────────────────────

def _writer():
    """Drain _Q and persist rows to echo.db. Runs in daemon thread."""
    while True:
        item = _Q.get()
        if item is None:
            break
        try:
            _flush(item)
        except Exception as e:
            print(f"[factbook_telemetry] write error: {e}", file=sys.stderr)
        finally:
            _Q.task_done()


def _ensure_started():
    global _started
    with _lock:
        if not _started:
            t = threading.Thread(target=_writer, daemon=True, name="factbook-telemetry-writer")
            t.start()
            _started = True


def _flush(item: dict):
    from db import get_conn
    kind = item["kind"]
    conn = get_conn()
    try:
        if kind == "cite":
            conn.execute(
                """INSERT OR IGNORE INTO factlet_citations
                     (factlet_id, source, session_id, parent_session_id, context_hash, cited_at)
                   VALUES (:factlet_id, :source, :session_id, :parent_session_id, :context_hash, :cited_at)""",
                item,
            )
        elif kind == "load":
            conn.execute(
                """INSERT OR IGNORE INTO factbook_loads
                     (session_id, scope, factlet_count, loaded_at)
                   VALUES (:session_id, :scope, :factlet_count, :loaded_at)""",
                item,
            )
        conn.commit()
    finally:
        conn.close()


# ── Public API ────────────────────────────────────────────────────────────────

def fact_cite(
    ids: Union[str, list],
    source: str,
    session_id: Optional[str] = None,
    parent_session_id: Optional[str] = None,
) -> None:
    """Record one citation per fact id. Fire-and-forget, never blocks.

    Dedup key: sha256(fact_id | source | session_id | date).
    One cite per fact per source per session per day is stored.

    Args:
        ids: single fact id or list of ids, e.g. 'f097' or ['f097', 'f099']
        source: caller label — 'batch:<name>' | 'pe_review' | 'coe' |
                'hook:pretool' | 'hook:posttool' | 'analyzer' | 'human'
        session_id: optional — set when call is within a tracked session
        parent_session_id: optional — the user session that dispatched a
            subagent ('agent-*' session_id), so db.promote_fast_track_
            citations can eventually collapse the subagent's citation
            toward its parent instead of excluding it entirely (kernora
            f399 migration 0039). NOT populated by any call site in this
            repo today — searched 2026-07-23: the only place a parent
            session id is available is the SubagentStop hook payload
            (nora_subagent_stop.py:139, `data.get("parent_session_id")`),
            which the Claude Code harness delivers to that hook's stdin,
            not to this module's in-process callers (analyzer.py,
            nora_context.py, brief_builder.py, nora_mcp.py — none of
            which have access to the dispatching session id at their
            call sites). Left as an explicit opt-in parameter, defaulting
            to None/NULL, so a future caller that DOES have the value
            (e.g. a dispatch wrapper passed it explicitly) can populate
            it without another schema change.
    """
    # FIELD-FIX (2026-07-23): a MANUAL-PROBE hook run must NOT write a real
    # citation — see _MANUAL_PROBE_SESSION_ID_RE above. Real 'agent-*'
    # subagent sessions ARE recorded here (founder correction); their
    # multi-count risk toward fast-track promotion is handled at
    # db.promote_fast_track_citations, not by refusing to record.
    if _is_synthetic_session_id(session_id):
        return
    _ensure_started()
    if isinstance(ids, str):
        ids = [ids]
    today = date.today().isoformat()
    ts    = datetime.now(timezone.utc).isoformat()
    for fid in ids:
        fid = fid.strip()
        if not fid:
            continue
        ctx_hash = hashlib.sha256(
            f"{fid}|{source}|{session_id or ''}|{today}".encode()
        ).hexdigest()[:16]
        row = {
            "kind":       "cite",
            "factlet_id": fid,   # DB column name kept for compat
            "source":     source,
            "session_id": session_id,
            "parent_session_id": parent_session_id,
            "context_hash": ctx_hash,
            "cited_at":   ts,
        }
        try:
            _Q.put_nowait(row)
        except queue.Full:
            print(f"[factbook_telemetry] queue full — dropping citation for {fid}", file=sys.stderr)


def factbook_load(
    session_id: str,
    scope: str,
    fact_count: int = 0,
    factlet_count: int = 0,  # backward-compat alias — remove in future batch
) -> None:
    """Record a factbook load event (idempotent per session+scope).

    Args:
        session_id:  the session that loaded the factbook
        scope:       e.g. 'project:kernora' or 'global'
        fact_count:  number of facts in the factbook at load time
    """
    _ensure_started()
    _count = fact_count or factlet_count  # accept either name
    row = {
        "kind":          "load",
        "session_id":    session_id,
        "scope":         scope,
        "factlet_count": _count,   # DB column name kept for compat
        "loaded_at":     datetime.now(timezone.utc).isoformat(),
    }
    try:
        _Q.put_nowait(row)
    except queue.Full:
        print(f"[factbook_telemetry] queue full — dropping factbook_load for {session_id}", file=sys.stderr)


def factbook_stats(window_days: int = 7) -> dict:
    """Compute dashboard headline metrics.

    Returns a dict with coverage, cost delta, top factlets, and
    dead-weight candidates (zero citations in window).
    """
    from db import get_conn
    conn = get_conn()
    try:
        wc = f"datetime('now', '-{window_days} days')"

        total_sessions = conn.execute(
            f"SELECT COUNT(*) FROM sessions WHERE ended_at > {wc}"
        ).fetchone()[0]

        loaded_sessions = conn.execute(
            f"SELECT COUNT(DISTINCT session_id) FROM factbook_loads WHERE loaded_at > {wc}"
        ).fetchone()[0]

        coverage_pct = round(loaded_sessions / total_sessions * 100, 1) if total_sessions > 0 else 0.0

        def _avg_cost(loaded: bool) -> Optional[float]:
            op = "IN" if loaded else "NOT IN"
            row = conn.execute(f"""
                SELECT AVG(ku.cost_usd)
                  FROM kernora_usage ku
                  JOIN sessions s ON s.id = ku.session_id
                 WHERE s.ended_at > {wc}
                   AND ku.session_id {op} (
                       SELECT session_id FROM factbook_loads WHERE loaded_at > {wc}
                   )
            """).fetchone()[0]
            return round(row, 6) if row is not None else None

        avg_cost_loaded   = _avg_cost(True)
        avg_cost_baseline = _avg_cost(False)
        if avg_cost_loaded is not None and avg_cost_baseline is not None and avg_cost_baseline > 0:
            cost_delta_pct = round((avg_cost_loaded - avg_cost_baseline) / avg_cost_baseline * 100, 1)
        else:
            cost_delta_pct = None

        top_factlets = [
            [r[0], r[1]]
            for r in conn.execute(f"""
                SELECT factlet_id, COUNT(*) AS n
                  FROM factlet_citations
                 WHERE cited_at > {wc}
                 GROUP BY factlet_id
                 ORDER BY n DESC
                 LIMIT 20
            """).fetchall()
        ]

        # Dead weight: facts with zero citations in window
        all_ids: list = []
        try:
            import yaml
            from pathlib import Path
            fb_path = Path(__file__).parent / ".nora" / "kernora-factbook.yaml"
            if fb_path.exists():
                fb = yaml.safe_load(fb_path.read_text())
                all_ids = [f["id"] for f in fb.get("content", [])]
        except Exception:
            pass

        cited_in_window = {r[0] for r in conn.execute(
            f"SELECT DISTINCT factlet_id FROM factlet_citations WHERE cited_at > {wc}"
        ).fetchall()}
        dead_weight = [fid for fid in all_ids if fid not in cited_in_window]

        h = hallucination_rate(conn, window_days=window_days)
        return {
            "window_days":                window_days,
            "total_sessions":             total_sessions,
            "sessions_with_factbook_load": loaded_sessions,
            "coverage_pct":               coverage_pct,
            "avg_cost_loaded":            avg_cost_loaded,
            "avg_cost_baseline":          avg_cost_baseline,
            "cost_delta_pct":             cost_delta_pct,
            "top_facts":                  top_factlets,   # renamed key
            "top_factlets":               top_factlets,   # backward-compat alias
            "dead_weight":                dead_weight,
            "hallucination_rate":         h["rate"],
            "hallucination_reduction":    h["reduction"],
            "hallucination_contradictions": h["contradictions"],
            "hallucination_total_loads":  h["total_loads"],
        }
    finally:
        conn.close()


# backward-compat alias — remove in future batch
factlet_cite = fact_cite


def hallucination_rate(conn=None, window_days: int = 30) -> dict:
    """Compute hallucination rate as contradictions per factbook load.

    Args:
        conn:         optional existing SQLite connection; if None, opens its own.
        window_days:  look-back window in days.

    Returns:
        dict with keys: rate (float), reduction (float), contradictions (int), total_loads (int)
    """
    _own_conn = conn is None
    if _own_conn:
        from db import get_conn
        conn = get_conn()
    try:
        w = f"datetime('now', '-{window_days} days')"
        total_loads = conn.execute(
            f"SELECT COUNT(*) FROM factbook_loads WHERE loaded_at > {w}"
        ).fetchone()[0]

        contradictions = conn.execute(
            f"SELECT COUNT(*) FROM hallucination_events WHERE detected_at > {w}"
        ).fetchone()[0]

        # Baseline: same window but prior period
        w2 = f"datetime('now', '-{window_days * 2} days')"
        prior_loads = conn.execute(
            f"SELECT COUNT(*) FROM factbook_loads WHERE loaded_at > {w2} AND loaded_at <= {w}"
        ).fetchone()[0]
        prior_contradictions = conn.execute(
            f"SELECT COUNT(*) FROM hallucination_events WHERE detected_at > {w2} AND detected_at <= {w}"
        ).fetchone()[0]

        rate = round((contradictions / max(total_loads, 1)) * 100, 1)
        prior_rate = (prior_contradictions / max(prior_loads, 1)) * 100
        reduction = round(prior_rate - rate, 1) if prior_loads > 0 else 0.0

        return {
            "rate":          rate,
            "reduction":     reduction,
            "contradictions": contradictions,
            "total_loads":   total_loads,
        }
    finally:
        if _own_conn:
            conn.close()
