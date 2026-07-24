#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""
Kernora — Knowledge Packs (v2 Schema)
First-class, versioned intelligence artifacts with dependencies, pinning,
scan_sources tracking, freshness scoring, and PULSE integration.

Architecture:
  AI Work Sessions ──► Nora Analysis ──► Knowledge Packs ──► AI Sessions
                                                     └──► Share / Export
  PULSE signals  ──► KP Freshness ──► needs_refresh detection
  nora init      ──► scan_sources  ──► provenance tracking

Pack Types:
  project   Per-project briefing (Jivant, Kernora, Vidafolio)
  person    Cross-project founder OS (Mihir Founder OS)
  domain    Technology/domain expertise (React, iOS, PostgreSQL)
  playbook  Business process (Fundraising, Sales, Hiring)
  onboard   New team member guide (last 90 days)
  digest    Weekly founder digest (last 7 days)

Versioning: semver (MAJOR.MINOR.PATCH)
  PATCH — new patterns/learnings added
  MINOR — new section added (decisions, processes)
  MAJOR — scope or type change

v2 Schema Additions (Apr 2026):
  dependencies   JSON — required/recommended tools, skills, KPs
  pin_state      pinned | unpinned (default) — freeze version for stability
  scan_sources   JSON — files/dirs that seeded this KP (provenance)
  refresh_state  current | stale | needs_refresh — PULSE-driven freshness
  confidence     REAL 0.0–1.0 — how well-supported is this KP
  provenance     JSON — generation method, source sessions, nora_init run

DB Tables: knowledge_packs, knowledge_pack_versions
"""
from __future__ import annotations

import hashlib
import html as _html_mod
import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# PACK TYPES
# ═══════════════════════════════════════════════════════════════════════════════

PACK_TYPES = {
    "project":  {"label": "Project Pack",   "color": "#1D9E75", "icon": "⬡"},
    "person":   {"label": "Person Pack",    "color": "#378ADD", "icon": "◉"},
    "domain":   {"label": "Domain Pack",    "color": "#9B59B6", "icon": "◈"},
    "playbook": {"label": "Playbook Pack",  "color": "#E67E22", "icon": "▶"},
    "onboard":  {"label": "Onboard Pack",   "color": "#BA7517", "icon": "◎"},
    "digest":   {"label": "Weekly Digest",  "color": "#1ABC9C", "icon": "◇"},
}


# ═══════════════════════════════════════════════════════════════════════════════
# DB SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_kp_tables(conn: sqlite3.Connection) -> None:
    """Ensure knowledge_packs and knowledge_pack_versions tables exist.
    Includes v2 schema: dependencies, pin_state, scan_sources, refresh_state,
    confidence, provenance."""
    # Phase 1: create tables (no v2-column indices yet — they may not exist on old DBs)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS knowledge_packs (
        id             TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        pack_type      TEXT NOT NULL DEFAULT 'project',
        scope          TEXT NOT NULL,
        version        TEXT NOT NULL DEFAULT '1.0.0',
        version_hash   TEXT,
        content_json   TEXT,
        summary        TEXT,
        token_budget   INTEGER DEFAULT 2000,
        injection_md   TEXT,
        share_token    TEXT UNIQUE,
        is_public      INTEGER DEFAULT 0,
        tags           TEXT DEFAULT '[]',
        created_at     TEXT DEFAULT (datetime('now')),
        updated_at     TEXT DEFAULT (datetime('now')),
        published_at   TEXT,
        -- v2 schema (Apr 2026)
        dependencies   TEXT DEFAULT '{}',
        pin_state      TEXT DEFAULT 'unpinned',
        scan_sources   TEXT DEFAULT '[]',
        refresh_state  TEXT DEFAULT 'current',
        confidence     REAL DEFAULT 0.5,
        provenance     TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS knowledge_pack_versions (
        id           TEXT PRIMARY KEY,
        pack_id      TEXT NOT NULL,
        version      TEXT NOT NULL,
        version_hash TEXT,
        content_json TEXT,
        diff_summary TEXT,
        created_at   TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_kp_scope_type ON knowledge_packs(scope, pack_type);
    CREATE INDEX IF NOT EXISTS idx_kpv_pack_id   ON knowledge_pack_versions(pack_id);
    """)

    # Phase 2: v2 migration — add columns to existing tables that lack them.
    # Must run BEFORE creating indices that reference these columns.
    V2_KP_COLS = [
        ("dependencies",  "TEXT DEFAULT '{}'"),
        ("pin_state",     "TEXT DEFAULT 'unpinned'"),
        ("scan_sources",  "TEXT DEFAULT '[]'"),
        ("refresh_state", "TEXT DEFAULT 'current'"),
        ("confidence",    "REAL DEFAULT 0.5"),
        ("provenance",    "TEXT DEFAULT '{}'"),
    ]
    existing = {r[1] for r in conn.execute("PRAGMA table_info(knowledge_packs)").fetchall()}
    for col, col_type in V2_KP_COLS:
        if col not in existing:
            conn.execute(f"ALTER TABLE knowledge_packs ADD COLUMN {col} {col_type}")
    conn.commit()

    # Phase 3: v2 indices (safe now — columns guaranteed to exist)
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_kp_refresh ON knowledge_packs(refresh_state);
    CREATE INDEX IF NOT EXISTS idx_kp_pin     ON knowledge_packs(pin_state);
    """)


# ═══════════════════════════════════════════════════════════════════════════════
# DEPENDENCY TYPES
# ═══════════════════════════════════════════════════════════════════════════════

# Dependencies JSON schema:
# {
#   "required": {
#     "tools":  ["mcp_server_name", ...],       # MCP servers this KP expects
#     "skills": ["skill_name", ...],             # Skills the KP relies on
#     "kps":    ["pack_id_or_name", ...]         # Other KPs (e.g. domain:react)
#   },
#   "recommended": {
#     "tools":  [...],
#     "skills": [...],
#     "kps":    [...]
#   }
# }

EMPTY_DEPS = {"required": {"tools": [], "skills": [], "kps": []},
              "recommended": {"tools": [], "skills": [], "kps": []}}

# Provenance JSON schema:
# {
#   "method":       "nora_init" | "dream" | "manual" | "session_end",
#   "source_sessions": ["session_id", ...],
#   "nora_init_run": "2026-04-08T...",
#   "scan_summary":  {"files": 154, "sloc": 47000, "commits": 92},
#   "generated_at":  "ISO timestamp"
# }

# Refresh states:
#   "current"       — no PULSE hotspots overlap with scan_sources
#   "stale"         — PULSE detected churn in scan_sources files
#   "needs_refresh" — stale + confidence dropped below threshold


# ═══════════════════════════════════════════════════════════════════════════════
# PIN / UNPIN
# ═══════════════════════════════════════════════════════════════════════════════

def pin_pack(conn: sqlite3.Connection, pack_id: str, version: Optional[str] = None) -> dict:
    """
    Pin a Knowledge Pack at its current version (or a specific version).
    Pinned packs are NOT refreshed by DREAM or session-end micro-DREAM.

    The frozen version is recorded inside the pack's `provenance` JSON
    under `pinned_version` so downstream tooling can see exactly what
    was frozen (and when).

    Use case: stable baseline for team onboarding, production KPs.
    """
    ensure_kp_tables(conn)
    row = conn.execute(
        "SELECT id, version, pin_state, provenance FROM knowledge_packs WHERE id = ?",
        (pack_id,)
    ).fetchone()
    if not row:
        return {"error": f"Pack {pack_id} not found"}

    pin_version = version or row[1]
    # Merge pinned_version into existing provenance
    try:
        prov = json.loads(row[3] or "{}")
    except Exception:
        prov = {}
    if not isinstance(prov, dict):
        prov = {}
    prov["pinned_version"] = pin_version
    prov["pinned_at"] = datetime.utcnow().isoformat()

    conn.execute("""
        UPDATE knowledge_packs
        SET pin_state = 'pinned', provenance = ?, updated_at = datetime('now')
        WHERE id = ?
    """, (json.dumps(prov), pack_id))
    conn.commit()
    return {"id": pack_id, "pin_state": "pinned", "pinned_version": pin_version}


def unpin_pack(conn: sqlite3.Connection, pack_id: str) -> dict:
    """
    Unpin a Knowledge Pack so it resumes DREAM/session-end refreshes.
    """
    ensure_kp_tables(conn)
    row = conn.execute(
        "SELECT id, pin_state FROM knowledge_packs WHERE id = ?",
        (pack_id,)
    ).fetchone()
    if not row:
        return {"error": f"Pack {pack_id} not found"}

    conn.execute("""
        UPDATE knowledge_packs
        SET pin_state = 'unpinned', updated_at = datetime('now')
        WHERE id = ?
    """, (pack_id,))
    conn.commit()
    return {"id": pack_id, "pin_state": "unpinned"}


def is_pinned(conn: sqlite3.Connection, pack_id: str) -> bool:
    """Check if a pack is pinned."""
    row = conn.execute(
        "SELECT pin_state FROM knowledge_packs WHERE id = ?",
        (pack_id,)
    ).fetchone()
    return (row[0] if row else "unpinned") == "pinned"


# ═══════════════════════════════════════════════════════════════════════════════
# DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════

def set_dependencies(conn: sqlite3.Connection, pack_id: str,
                     deps: dict) -> dict:
    """
    Set dependencies for a Knowledge Pack.
    deps format: {"required": {"tools": [...], "skills": [...], "kps": [...]},
                  "recommended": {"tools": [...], "skills": [...], "kps": [...]}}
    """
    ensure_kp_tables(conn)
    # Normalize
    normalized = {"required": {}, "recommended": {}}
    for level in ("required", "recommended"):
        src = deps.get(level, {})
        for kind in ("tools", "skills", "kps"):
            normalized[level][kind] = list(set(src.get(kind, [])))

    conn.execute("""
        UPDATE knowledge_packs
        SET dependencies = ?, updated_at = datetime('now')
        WHERE id = ?
    """, (json.dumps(normalized), pack_id))
    conn.commit()
    return normalized


def get_dependencies(conn: sqlite3.Connection, pack_id: str) -> dict:
    """Get dependencies for a pack."""
    row = conn.execute(
        "SELECT dependencies FROM knowledge_packs WHERE id = ?",
        (pack_id,)
    ).fetchone()
    if not row or not row[0]:
        return dict(EMPTY_DEPS)
    try:
        return json.loads(row[0])
    except Exception:
        return dict(EMPTY_DEPS)


def check_dependencies(conn: sqlite3.Connection, pack_id: str) -> dict:
    """
    Check which dependencies are satisfied.
    Returns: {"satisfied": [...], "missing": [...], "status": "ok" | "missing_required"}
    """
    deps = get_dependencies(conn, pack_id)
    satisfied = []
    missing = []

    # Check required KPs exist
    for kp_ref in deps.get("required", {}).get("kps", []):
        row = conn.execute(
            "SELECT id FROM knowledge_packs WHERE id = ? OR name LIKE ?",
            (kp_ref, f"%{kp_ref}%")
        ).fetchone()
        if row:
            satisfied.append({"type": "kp", "ref": kp_ref, "level": "required"})
        else:
            missing.append({"type": "kp", "ref": kp_ref, "level": "required"})

    # Check recommended KPs
    for kp_ref in deps.get("recommended", {}).get("kps", []):
        row = conn.execute(
            "SELECT id FROM knowledge_packs WHERE id = ? OR name LIKE ?",
            (kp_ref, f"%{kp_ref}%")
        ).fetchone()
        if row:
            satisfied.append({"type": "kp", "ref": kp_ref, "level": "recommended"})
        else:
            missing.append({"type": "kp", "ref": kp_ref, "level": "recommended"})

    # Tools and skills are external — just report them
    for level in ("required", "recommended"):
        for kind in ("tools", "skills"):
            for ref in deps.get(level, {}).get(kind, []):
                # Can't verify tools/skills at DB level — flag as info
                satisfied.append({"type": kind[:-1], "ref": ref, "level": level,
                                  "note": "external — verify at runtime"})

    has_missing_required = any(m["level"] == "required" for m in missing)
    return {
        "satisfied": satisfied,
        "missing": missing,
        "status": "missing_required" if has_missing_required else "ok",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SCAN SOURCES & PROVENANCE
# ═══════════════════════════════════════════════════════════════════════════════

def set_scan_sources(conn: sqlite3.Connection, pack_id: str,
                     sources: list[str]) -> None:
    """
    Record which files/directories were scanned to generate this KP.
    Used by PULSE to detect when source files change → mark KP stale.
    """
    conn.execute("""
        UPDATE knowledge_packs
        SET scan_sources = ?, updated_at = datetime('now')
        WHERE id = ?
    """, (json.dumps(sources), pack_id))
    conn.commit()


def set_provenance(conn: sqlite3.Connection, pack_id: str,
                   provenance: dict) -> None:
    """Record how this KP was generated (method, sessions, nora_init run, etc.)."""
    conn.execute("""
        UPDATE knowledge_packs
        SET provenance = ?, updated_at = datetime('now')
        WHERE id = ?
    """, (json.dumps(provenance), pack_id))
    conn.commit()


def set_confidence(conn: sqlite3.Connection, pack_id: str,
                   confidence: float) -> None:
    """Set KP confidence score (0.0–1.0)."""
    clamped = max(0.0, min(1.0, confidence))
    conn.execute("""
        UPDATE knowledge_packs
        SET confidence = ?, updated_at = datetime('now')
        WHERE id = ?
    """, (clamped, pack_id))
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# PULSE-DRIVEN FRESHNESS
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_freshness(conn: sqlite3.Connection, pack_id: str,
                       hotspot_files: Optional[list[str]] = None) -> dict:
    """
    Evaluate a KP's freshness by comparing its scan_sources against
    PULSE hotspot files. If overlap detected, mark as stale/needs_refresh.

    hotspot_files: if None, will query PULSE directly.
    Returns: {"refresh_state": ..., "confidence": ..., "overlap": [...]}
    """
    row = conn.execute("""
        SELECT scan_sources, refresh_state, confidence, pin_state
        FROM knowledge_packs WHERE id = ?
    """, (pack_id,)).fetchone()
    if not row:
        return {"error": f"Pack {pack_id} not found"}

    # Pinned packs stay current regardless
    if row[3] == "pinned":
        return {"refresh_state": "current", "confidence": row[2],
                "overlap": [], "pinned": True}

    sources = []
    try:
        sources = json.loads(row[0] or "[]")
    except Exception:
        pass

    if not sources:
        # No scan_sources recorded — can't evaluate freshness
        return {"refresh_state": row[1], "confidence": row[2], "overlap": [],
                "note": "no scan_sources recorded"}

    # Get hotspot files from PULSE if not provided
    if hotspot_files is None:
        try:
            import pulse
            hotspots = pulse.get_hotspots(limit=50)
            hotspot_files = [h.get("file_path", "") for h in hotspots]
        except Exception:
            hotspot_files = []

    # Normalize paths for comparison (strip leading ~/ or absolute prefixes)
    def _normalize(p: str) -> str:
        p = str(p).replace("\\", "/")
        # Strip common prefixes
        for prefix in ("~/code/", "/Users/", "/home/"):
            if p.startswith(prefix):
                p = p[len(prefix):]
                break
        return p.rstrip("/")

    source_set = {_normalize(s) for s in sources if s}
    overlap = []
    for hf in hotspot_files:
        norm_hf = _normalize(hf)
        if not norm_hf:
            continue
        # Check if hotspot file is inside any scan_source directory.
        # Use path-boundary-aware matching to avoid false positives
        # like "kernora" matching "kernora-backup/foo.py".
        for src in source_set:
            if not src:
                continue
            if norm_hf == src or norm_hf.startswith(src + "/"):
                overlap.append(hf)
                break

    # Determine new state
    old_state = row[1] or "current"
    old_confidence = row[2] or 0.5

    if overlap:
        overlap_ratio = len(overlap) / max(len(hotspot_files), 1)
        if overlap_ratio > 0.3 or len(overlap) >= 5:
            new_state = "needs_refresh"
            confidence_penalty = 0.2
        else:
            new_state = "stale"
            confidence_penalty = 0.1

        new_confidence = max(0.1, old_confidence - confidence_penalty)
    else:
        new_state = "current"
        new_confidence = min(1.0, old_confidence + 0.02)  # Slow confidence recovery

    # Update DB
    conn.execute("""
        UPDATE knowledge_packs
        SET refresh_state = ?, confidence = ?, updated_at = datetime('now')
        WHERE id = ?
    """, (new_state, round(new_confidence, 3), pack_id))
    conn.commit()

    return {
        "refresh_state": new_state,
        "confidence": round(new_confidence, 3),
        "overlap": overlap,
        "overlap_count": len(overlap),
    }


def evaluate_all_freshness(conn: sqlite3.Connection) -> list[dict]:
    """
    Evaluate freshness for ALL unpinned KPs. Called by DREAM nightly.
    Returns list of KPs that changed state.
    """
    ensure_kp_tables(conn)

    # Get all hotspot files once
    hotspot_files = []
    try:
        import pulse
        hotspots = pulse.get_hotspots(limit=100)
        hotspot_files = [h.get("file_path", "") for h in hotspots]
    except Exception:
        pass

    rows = conn.execute("""
        SELECT id FROM knowledge_packs
        WHERE pin_state = 'unpinned'
    """).fetchall()

    changed = []
    for row in rows:
        pack_id = row[0]
        old_row = conn.execute(
            "SELECT refresh_state FROM knowledge_packs WHERE id = ?",
            (pack_id,)
        ).fetchone()
        old_state = old_row[0] if old_row else "current"

        result = evaluate_freshness(conn, pack_id, hotspot_files=hotspot_files)
        if result.get("refresh_state") != old_state:
            changed.append({"id": pack_id, "old": old_state,
                            "new": result["refresh_state"],
                            "overlap": result.get("overlap_count", 0)})

    return changed


# ═══════════════════════════════════════════════════════════════════════════════
# INTELLIGENCE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def _pull_project_intel(conn: sqlite3.Connection, project: str, since_days: int = 9999) -> dict:
    """Pull all intelligence for a project from the DB."""
    since = (datetime.utcnow() - timedelta(days=since_days)).isoformat()

    stats_row = conn.execute("""
        SELECT COUNT(*) as sessions,
               MIN(started_at) as first_session,
               MAX(started_at) as last_session,
               SUM(tokens_in + tokens_out) as total_tokens
        FROM sessions WHERE project = ? AND started_at > ?
    """, (project, since)).fetchone()

    sessions      = stats_row[0] if stats_row else 0
    first_session = (stats_row[1] or "")[:10]
    last_session  = (stats_row[2] or "")[:10]
    total_tokens  = stats_row[3] or 0

    # Patterns
    pattern_rows = conn.execute("""
        SELECT COALESCE(p.name, p.pattern), p.effectiveness, p.domains, p.context
        FROM patterns p
        JOIN sessions s ON s.id = p.session_id
        WHERE s.project = ?
        ORDER BY p.effectiveness DESC LIMIT 40
    """, (project,)).fetchall()

    patterns, antipatterns = [], []
    for r in pattern_rows:
        text = r[0] or ""
        if not text or len(text) < 5:
            continue
        item = {"text": text, "effectiveness": r[1] or 0,
                "domains": r[2] or "", "context": r[3] or ""}
        if text.upper().startswith("NEVER") or text.lower().startswith("avoid"):
            antipatterns.append(item)
        else:
            patterns.append(item)

    # Decisions
    decision_rows = conn.execute("""
        SELECT decision, rationale, alternatives, context, created_at
        FROM decisions
        WHERE project = ? AND created_at > ?
        ORDER BY created_at DESC LIMIT 30
    """, (project, since)).fetchall()
    decisions = [
        {"decision": r[0], "rationale": r[1] or "",
         "alternatives": r[2] or "", "context": r[3] or "", "date": (r[4] or "")[:10]}
        for r in decision_rows if r[0]
    ]

    # Bugs
    bug_rows = conn.execute("""
        SELECT title, severity, status, error_signature, created_at
        FROM reported_bugs WHERE status != 'resolved'
        ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                               WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC LIMIT 20
    """).fetchall()
    bugs = [{"title": r[0], "severity": r[1] or "medium",
             "status": r[2] or "open", "date": (r[4] or "")[:10]}
            for r in bug_rows if r[0]]

    # Intelligence from information_maps
    tenets, learnings, processes, tool_candidates = [], [], [], []
    open_questions, key_discussions = [], []
    eng_intel: dict[str, list] = {}
    people: dict[str, dict]  = {}
    technologies: dict[str, dict] = {}
    products: dict[str, dict] = {}
    domain_counts: dict[str, int] = {}

    imap_rows = conn.execute("""
        SELECT i.information_map
        FROM insights i JOIN sessions s ON s.id = i.session_id
        WHERE s.project = ? AND i.information_map IS NOT NULL
          AND i.information_map NOT IN ('', '{}')
          AND s.started_at > ?
        ORDER BY i.id DESC LIMIT 200
    """, (project, since)).fetchall()

    for row in imap_rows:
        try:
            imap = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            if not isinstance(imap, dict):
                continue
        except Exception:
            continue

        # Domain — extracted from information_map JSON
        dc = imap.get("domain_classification") or {}
        dom = dc.get("primary", "") if isinstance(dc, dict) else str(dc)
        if dom:
            d = str(dom).split("/")[0].strip().lower()
            domain_counts[d] = domain_counts.get(d, 0) + 1

        pi = imap.get("product_intelligence") or {}
        for t in pi.get("tenets") or []:
            text = t.get("tenet") or t.get("text") or (t if isinstance(t, str) else "")
            if text and len(str(text)) > 10:
                tenets.append({"text": str(text), "product": t.get("product", "") if isinstance(t, dict) else ""})

        for l in imap.get("learnings") or []:
            text = ((l.get("insight") or l.get("learning") or l.get("text") or "")
                    if isinstance(l, dict) else str(l))
            if text and len(text) > 10:
                learnings.append({"text": text, "domain": l.get("domain", "") if isinstance(l, dict) else ""})

        pri = imap.get("process_intelligence") or {}
        for p in pri.get("processes_defined") or []:
            name = (p.get("name") or p.get("process") or "") if isinstance(p, dict) else str(p)
            if name and len(name) > 5:
                processes.append({"name": name, "steps": p.get("steps", "") if isinstance(p, dict) else "",
                                  "complexity": p.get("complexity", "moderate") if isinstance(p, dict) else "moderate"})

        for tc in pri.get("tool_skill_candidates") or []:
            name = (tc.get("name") or tc.get("tool") or "") if isinstance(tc, dict) else str(tc)
            if name and len(name) > 5:
                tool_candidates.append({"name": name,
                                        "rationale": tc.get("rationale") or tc.get("description", "") if isinstance(tc, dict) else "",
                                        "complexity": tc.get("complexity", "moderate") if isinstance(tc, dict) else "moderate"})

        for kd in imap.get("key_discussions") or []:
            text = (kd.get("topic") or kd.get("decision") or kd.get("conclusion") or "") if isinstance(kd, dict) else str(kd)
            if text and len(text) > 10:
                key_discussions.append({"text": text, "status": kd.get("status", "") if isinstance(kd, dict) else ""})

        for q in imap.get("open_questions") or []:
            q_text = q if isinstance(q, str) else q.get("question", "") if isinstance(q, dict) else ""
            if q_text and len(q_text) > 5:
                open_questions.append(q_text)

        ei = imap.get("engineering_intelligence") or {}
        for k in ("system_design", "tech_debt", "performance_targets", "infrastructure",
                  "testing_practices", "deployment_practices"):
            for item in (ei.get(k) or []):
                item_str = str(item) if not isinstance(item, dict) else (item.get("description") or item.get("issue") or str(item))
                if item_str and len(item_str) > 5:
                    eng_intel.setdefault(k, []).append(item_str[:200])

        for e in imap.get("entities") or []:
            if not isinstance(e, dict):
                continue
            t = e.get("type", "")
            n = e.get("name", "") or e.get("entity", "")
            if not n:
                continue
            if t == "person":
                people.setdefault(n, {"name": n, "count": 0})["count"] += 1
            elif t in ("technology", "framework", "language", "tool", "library"):
                technologies.setdefault(n, {"name": n, "type": t, "count": 0})["count"] += 1
            elif t in ("product", "feature", "service"):
                products.setdefault(n, {"name": n, "count": 0})["count"] += 1

    def _dedupe(items, key_fn):
        seen, out = set(), []
        for item in items:
            k = str(key_fn(item))[:60].strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(item)
        return out

    tenets         = _dedupe(tenets,         lambda x: x["text"])
    learnings      = _dedupe(learnings,      lambda x: x["text"])
    processes      = _dedupe(processes,      lambda x: x["name"])
    tool_candidates= _dedupe(tool_candidates, lambda x: x["name"])
    key_discussions= _dedupe(key_discussions, lambda x: x["text"])

    top_domain = max(domain_counts, key=domain_counts.get) if domain_counts else "engineering"

    return {
        "project":        project,
        "sessions":       sessions,
        "first_session":  first_session,
        "last_session":   last_session,
        "total_tokens":   total_tokens,
        "top_domain":     top_domain,
        "domain_counts":  domain_counts,
        "patterns":       patterns,
        "antipatterns":   antipatterns,
        "decisions":      decisions,
        "bugs":           bugs,
        "tenets":         tenets[:20],
        "learnings":      learnings[:30],
        "processes":      processes[:15],
        "tool_candidates":tool_candidates[:15],
        "open_questions": open_questions[:15],
        "key_discussions":key_discussions[:20],
        "people":         sorted(people.values(),       key=lambda x: x["count"],  reverse=True)[:10],
        "technologies":   sorted(technologies.values(), key=lambda x: x["count"],  reverse=True)[:15],
        "products":       sorted(products.values(),     key=lambda x: x["count"],  reverse=True)[:10],
        "eng_intel":      {k: v[:8] for k, v in eng_intel.items()},
    }


def _pull_person_intel(conn: sqlite3.Connection, person_name: str = "Mihir",
                       since_days: int = 9999) -> dict:
    """Pull cross-project intelligence for a person (founder OS)."""
    since = (datetime.utcnow() - timedelta(days=since_days)).isoformat()

    # Get all projects
    project_rows = conn.execute("""
        SELECT project, COUNT(*) as cnt, MAX(started_at)
        FROM sessions WHERE project != '' AND started_at > ?
        GROUP BY project ORDER BY cnt DESC
    """, (since,)).fetchall()
    projects = [r[0] for r in project_rows]

    # Aggregate cross-project intelligence
    all_intel = {"project": f"@{person_name}", "sessions": 0,
                 "first_session": "", "last_session": "", "total_tokens": 0,
                 "top_domain": "engineering", "domain_counts": {},
                 "patterns": [], "antipatterns": [], "decisions": [],
                 "bugs": [], "tenets": [], "learnings": [], "processes": [],
                 "tool_candidates": [], "open_questions": [], "key_discussions": [],
                 "people": [], "technologies": [], "products": [], "eng_intel": {},
                 "projects": [{"name": Path(r[0]).name, "sessions": r[1],
                               "last_seen": (r[2] or "")[:10]} for r in project_rows]}

    # Stats
    stats = conn.execute("""
        SELECT COUNT(*), MIN(started_at), MAX(started_at), SUM(tokens_in + tokens_out)
        FROM sessions WHERE started_at > ?
    """, (since,)).fetchone()
    if stats:
        all_intel["sessions"]      = stats[0] or 0
        all_intel["first_session"] = (stats[1] or "")[:10]
        all_intel["last_session"]  = (stats[2] or "")[:10]
        all_intel["total_tokens"]  = stats[3] or 0

    # Merge intel from top 8 projects
    seen_texts: set[str] = set()
    for proj in projects[:8]:
        intel = _pull_project_intel(conn, proj, since_days)
        for key in ("patterns", "antipatterns", "decisions", "tenets",
                    "learnings", "processes", "tool_candidates"):
            for item in intel.get(key, []):
                text = item.get("text") or item.get("decision") or item.get("name") or ""
                sig  = text[:50].lower()
                if sig and sig not in seen_texts:
                    seen_texts.add(sig)
                    all_intel[key].append(item)
        # Merge domain counts
        for d, c in intel.get("domain_counts", {}).items():
            all_intel["domain_counts"][d] = all_intel["domain_counts"].get(d, 0) + c
        # Merge technologies
        for t in intel.get("technologies", []):
            all_intel["technologies"].append(t)

    # Pick top domain
    if all_intel["domain_counts"]:
        all_intel["top_domain"] = max(all_intel["domain_counts"],
                                      key=all_intel["domain_counts"].get)
    # Dedupe technologies
    seen_tech: set[str] = set()
    all_intel["technologies"] = [
        t for t in all_intel["technologies"]
        if t["name"] not in seen_tech and not seen_tech.add(t["name"])
    ][:20]

    return all_intel


# ═══════════════════════════════════════════════════════════════════════════════
# VERSIONING
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_pack_hash(content: dict) -> str:
    """SHA-256 of pack content for change detection."""
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _bump_version(current: str, bump: str = "patch") -> str:
    """Bump semver string: patch / minor / major."""
    try:
        parts = [int(x) for x in str(current).split(".")]
        while len(parts) < 3:
            parts.append(0)
        if bump == "major":
            return f"{parts[0]+1}.0.0"
        elif bump == "minor":
            return f"{parts[0]}.{parts[1]+1}.0"
        else:
            return f"{parts[0]}.{parts[1]}.{parts[2]+1}"
    except Exception:
        return "1.0.0"


def _diff_summary(old_content: dict, new_content: dict) -> str:
    """Generate a human-readable diff summary between pack versions."""
    parts = []
    for key in ("patterns", "antipatterns", "decisions", "learnings",
                "tenets", "processes", "tool_candidates"):
        old_n = len(old_content.get(key, []))
        new_n = len(new_content.get(key, []))
        delta = new_n - old_n
        if delta != 0:
            sign = "+" if delta > 0 else ""
            parts.append(f"{sign}{delta} {key}")
    return ", ".join(parts) if parts else "minor updates"


# ═══════════════════════════════════════════════════════════════════════════════
# INJECTION MD (AI-native, <500 tokens)
# ═══════════════════════════════════════════════════════════════════════════════

def render_injection_md(
    intel: dict,
    pack_type: str = "project",
    *,
    include_meta_rules: bool = False,
    meta_rules_version: str = "1.1",
) -> str:
    """
    Render a compact CLAUDE.md injection block for this factbook.
    Target: <500 tokens base. Delivers maximum signal with minimum context pollution.
    Hierarchy: Rules → Anti-patterns → Decisions → Key tech stack

    When include_meta_rules=True, append the Living Factbook v1.1 lifecycle
    meta-rules block at the tail (raw XML for Claude; adds ~3.8K tokens).
    Callers on the factbook-inject path pass include_meta_rules=True; the
    default is False to preserve the 500-token base-case target.
    """
    lines = []
    scope = intel.get("project", "")
    base  = scope.split("/")[-1] if "/" in scope else scope

    lines.append(f"## Factbook: {base}")
    lines.append(f"_Type: {pack_type} · Version injected by Kernora_")
    lines.append("")

    # Rules (top 5 patterns — highest signal)
    patterns = intel.get("patterns", [])[:5]
    if patterns:
        lines.append("### Rules (always apply)")
        for p in patterns:
            lines.append(f"- {p['text']}")
        lines.append("")

    # Anti-patterns (top 3 — prevent regressions)
    antipatterns = intel.get("antipatterns", [])[:3]
    if antipatterns:
        lines.append("### Never Do")
        for p in antipatterns:
            lines.append(f"- NEVER: {p['text']}")
        lines.append("")

    # Architecture decisions (top 3)
    decisions = intel.get("decisions", [])[:3]
    if decisions:
        lines.append("### Architecture Decisions")
        for d in decisions:
            rationale = d.get("rationale", "")[:80]
            suffix = f" ({rationale})" if rationale else ""
            lines.append(f"- {d['decision']}{suffix}")
        lines.append("")

    # Tech stack (compact pill list)
    techs = intel.get("technologies", [])[:10]
    if techs:
        stack = ", ".join(t["name"] for t in techs)
        lines.append(f"### Tech Stack\n{stack}")
        lines.append("")

    # Open questions (top 3 — keep AI aware of unresolved items)
    oq = intel.get("open_questions", [])[:3]
    if oq:
        lines.append("### Open Questions")
        for q in oq:
            lines.append(f"- {q}")
        lines.append("")

    lines.append(f"_To load the full factbook: ask Nora or visit /factbook/{scope}_")

    body = "\n".join(lines)

    if include_meta_rules:
        try:
            from meta_rules import render as _render_meta_rules
            body = body + "\n\n---\n\n" + _render_meta_rules("claude", version=meta_rules_version)
        except Exception as e:
            # Non-fatal: factbook content still ships without meta-rules.
            # Log via stderr; do NOT leak internal error strings into the
            # emitted markdown (user would see garbage in CLAUDE.md).
            import sys as _sys
            print(
                f"[knowledge_pack] meta-rules skipped: {type(e).__name__}: {e}",
                file=_sys.stderr,
            )

    return body


# ═══════════════════════════════════════════════════════════════════════════════
# PACK GENERATION & VERSIONING
# ═══════════════════════════════════════════════════════════════════════════════

def _pack_id(pack_type: str, scope: str) -> str:
    """Deterministic pack ID from type + scope."""
    sig = f"{pack_type}:{scope}"
    return hashlib.sha256(sig.encode()).hexdigest()[:20]


def generate_or_refresh_pack(conn: sqlite3.Connection,
                              pack_type: str,
                              scope: str,
                              since_days: int = 9999,
                              force_bump: Optional[str] = None,
                              scan_sources: Optional[list[str]] = None,
                              provenance: Optional[dict] = None,
                              dependencies: Optional[dict] = None) -> dict:
    """
    Generate a Knowledge Pack or refresh it if content has changed.
    Returns the pack row dict.

    pack_type: project | person | domain | playbook | onboard | digest
    scope:     project path for 'project', person name for 'person', etc.
    force_bump: 'patch' | 'minor' | 'major' — force a version bump

    v2 params:
    scan_sources:  list of files/dirs that seeded this KP
    provenance:    how this KP was generated (method, sessions, etc.)
    dependencies:  required/recommended tools, skills, KPs
    """
    ensure_kp_tables(conn)

    # Check if existing pack is pinned — skip refresh
    pid = _pack_id(pack_type, scope)
    existing = conn.execute(
        "SELECT id, version, version_hash, content_json, pin_state FROM knowledge_packs WHERE id = ?",
        (pid,)
    ).fetchone()

    if existing and existing[4] == "pinned" and not force_bump:
        # Pinned — do not refresh. Return as-is.
        return _pack_as_dict(conn, pid)

    # Pull intelligence
    if pack_type == "person":
        intel = _pull_person_intel(conn, scope, since_days)
        name  = f"{scope} · Founder OS"
    elif pack_type in ("onboard", "digest"):
        days  = 90 if pack_type == "onboard" else 7
        intel = _pull_project_intel(conn, scope, days)
        label = PACK_TYPES[pack_type]["label"]
        name  = f"{Path(scope).name} · {label}"
    else:
        intel = _pull_project_intel(conn, scope, since_days)
        name  = f"{Path(scope).name} · {PACK_TYPES.get(pack_type,{}).get('label','Pack')}"

    # Render injection_md
    injection_md = render_injection_md(intel, pack_type)

    # Content hash
    content_hash = _compute_pack_hash(intel)

    now = datetime.utcnow().isoformat()

    # v2 defaults
    deps_json = json.dumps(dependencies or EMPTY_DEPS)
    sources_json = json.dumps(scan_sources or [])
    prov_json = json.dumps(provenance or {"method": "dream", "generated_at": now})

    if existing is None:
        # New pack — v1.0.0
        version = "1.0.0"

        # Calculate initial confidence from intel density (audit fix 2026-04-24:
        # prior formula `0.3 + n*0.05 + n*0.05 + n*0.02` clamps to 1.0 once
        # sessions > ~35, so every real project showed 100% confidence.
        # New: each component is capped *before* sum so dense projects don't
        # over-saturate; max remains 1.0 but the gradient is meaningful.)
        n_patterns  = len(intel.get("patterns", []))
        n_decisions = len(intel.get("decisions", []))
        n_sessions  = intel.get("sessions", 0)
        confidence  = round(min(1.0,
                                0.3
                                + min(0.25, n_patterns  * 0.025)   # pattern density: 10 → 0.25
                                + min(0.25, n_decisions * 0.04)    # decision density: 7 → 0.25
                                + min(0.20, n_sessions  * 0.004)), # session density: 50 → 0.20
                           3)

        conn.execute("""
            INSERT INTO knowledge_packs
                (id, name, pack_type, scope, version, version_hash, content_json,
                 summary, injection_md, tags, created_at, updated_at,
                 dependencies, scan_sources, provenance, confidence, refresh_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, 'current')
        """, (pid, name, pack_type, scope, version, content_hash,
              json.dumps(intel), _build_summary(intel, pack_type),
              injection_md, json.dumps([pack_type]), now, now,
              deps_json, sources_json, prov_json, confidence))
        _save_version(conn, pid, version, content_hash, intel, "Initial generation")
        conn.commit()
    else:
        old_version  = existing[1]
        old_hash_val = existing[2]
        old_content  = {}
        try:
            old_content = json.loads(existing[3] or "{}")
        except Exception:
            pass

        if content_hash == old_hash_val and not force_bump:
            # No change — update v2 metadata if caller provided new values
            updates: list[str] = []
            params: list = []
            if scan_sources is not None:
                updates.append("scan_sources = ?")
                params.append(sources_json)
            if provenance is not None:
                updates.append("provenance = ?")
                params.append(prov_json)
            if dependencies is not None:
                updates.append("dependencies = ?")
                params.append(deps_json)
            if updates:
                params.append(pid)
                conn.execute(
                    f"UPDATE knowledge_packs SET {', '.join(updates)}, "
                    f"updated_at = datetime('now') WHERE id = ?",
                    params
                )
                conn.commit()
            return _pack_as_dict(conn, pid)

        # Version bump
        if force_bump:
            bump = force_bump
        else:
            new_sections = sum(1 for k in ("decisions", "processes", "tenets")
                               if len(intel.get(k,[])) > len(old_content.get(k,[])))
            bump = "minor" if new_sections >= 2 else "patch"

        new_version = _bump_version(old_version, bump)
        diff_sum    = _diff_summary(old_content, intel)

        # Recalculate confidence on refresh — same per-component cap as
        # initial generation (audit fix 2026-04-24).
        n_patterns  = len(intel.get("patterns", []))
        n_decisions = len(intel.get("decisions", []))
        n_sessions  = intel.get("sessions", 0)
        confidence  = round(min(1.0,
                                0.3
                                + min(0.25, n_patterns  * 0.025)
                                + min(0.25, n_decisions * 0.04)
                                + min(0.20, n_sessions  * 0.004)),
                           3)

        # Core fields always updated on a version bump.
        set_parts = [
            "version=?", "version_hash=?", "content_json=?", "summary=?",
            "injection_md=?", "name=?", "updated_at=?",
            "refresh_state='current'", "confidence=?",
        ]
        core_params: list = [
            new_version, content_hash, json.dumps(intel),
            _build_summary(intel, pack_type), injection_md, name, now,
            confidence,
        ]
        # v2 fields — only update when caller explicitly supplied them,
        # otherwise preserve prior values (don't clobber with defaults).
        if dependencies is not None:
            set_parts.append("dependencies=?")
            core_params.append(deps_json)
        if scan_sources is not None:
            set_parts.append("scan_sources=?")
            core_params.append(sources_json)
        if provenance is not None:
            set_parts.append("provenance=?")
            core_params.append(prov_json)
        core_params.append(pid)
        conn.execute(
            f"UPDATE knowledge_packs SET {', '.join(set_parts)} WHERE id=?",
            core_params,
        )
        _save_version(conn, pid, new_version, content_hash, intel, diff_sum)
        conn.commit()

    return _pack_as_dict(conn, pid)


def _save_version(conn: sqlite3.Connection, pack_id: str, version: str,
                  content_hash: str, content: dict, diff_summary: str) -> None:
    """Save a version snapshot."""
    vid = f"{pack_id}:{version}:{content_hash}"
    # Only insert if not already there
    existing = conn.execute("SELECT id FROM knowledge_pack_versions WHERE id=?", (vid,)).fetchone()
    if not existing:
        conn.execute("""
            INSERT INTO knowledge_pack_versions (id, pack_id, version, version_hash, content_json, diff_summary)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (vid, pack_id, version, content_hash, json.dumps(content), diff_summary))


def _pack_as_dict(conn: sqlite3.Connection, pack_id: str) -> dict:
    """Fetch a pack row as a dict (includes v2 fields)."""
    row = conn.execute("""
        SELECT id, name, pack_type, scope, version, version_hash, summary,
               injection_md, share_token, is_public, tags, created_at, updated_at,
               dependencies, pin_state, scan_sources, refresh_state, confidence, provenance
        FROM knowledge_packs WHERE id=?
    """, (pack_id,)).fetchone()
    if not row:
        return {}
    keys = ("id", "name", "pack_type", "scope", "version", "version_hash", "summary",
            "injection_md", "share_token", "is_public", "tags", "created_at", "updated_at",
            "dependencies", "pin_state", "scan_sources", "refresh_state", "confidence",
            "provenance")
    d = dict(zip(keys, row))
    # Parse JSON fields for convenience
    _defaults = {"dependencies": "{}", "scan_sources": "[]", "provenance": "{}"}
    for jf, default_json in _defaults.items():
        raw = d.get(jf) or default_json
        try:
            d[jf] = json.loads(raw)
        except Exception:
            d[jf] = json.loads(default_json)
    return d


def _build_summary(intel: dict, pack_type: str) -> str:
    """Build a 2-line summary for a pack."""
    n_patterns  = len(intel.get("patterns", []))
    n_decisions = len(intel.get("decisions", []))
    n_learnings = len(intel.get("learnings", []))
    n_sessions  = intel.get("sessions", 0)
    scope       = intel.get("project", "")
    base        = scope.split("/")[-1] if "/" in scope else scope
    return (f"{n_sessions} sessions · {n_patterns} patterns · "
            f"{n_decisions} decisions · {n_learnings} learnings. "
            f"Top domain: {intel.get('top_domain', 'engineering')}.")


# ═══════════════════════════════════════════════════════════════════════════════
# SHARING
# ═══════════════════════════════════════════════════════════════════════════════

def publish_pack(conn: sqlite3.Connection, pack_id: str) -> str:
    """Make a pack publicly shareable. Returns share token."""
    ensure_kp_tables(conn)
    row = conn.execute("SELECT share_token FROM knowledge_packs WHERE id=?",
                       (pack_id,)).fetchone()
    if not row:
        return ""
    token = row[0]
    if not token:
        token = secrets.token_urlsafe(16)
        conn.execute("""
            UPDATE knowledge_packs SET share_token=?, is_public=1, published_at=datetime('now')
            WHERE id=?
        """, (token, pack_id))
        conn.commit()
    return token


def get_pack_by_share_token(conn: sqlite3.Connection, token: str) -> dict:
    """Retrieve a public pack by its share token."""
    ensure_kp_tables(conn)
    row = conn.execute("""
        SELECT id, name, pack_type, scope, version, content_json, summary
        FROM knowledge_packs WHERE share_token=? AND is_public=1
    """, (token,)).fetchone()
    if not row:
        return {}
    intel = {}
    try:
        intel = json.loads(row[5] or "{}")
    except Exception:
        pass
    return {"id": row[0], "name": row[1], "pack_type": row[2], "scope": row[3],
            "version": row[4], "intel": intel, "summary": row[6]}


def get_pack_by_id(conn: sqlite3.Connection, pack_id: str) -> dict:
    """Return full pack dict (including parsed content_json) for a given pack id."""
    ensure_kp_tables(conn)
    row = conn.execute("""
        SELECT id, name, pack_type, scope, version, content_json, summary,
               pin_state, refresh_state, confidence
        FROM knowledge_packs WHERE id=?
    """, (pack_id,)).fetchone()
    if not row:
        return {}
    intel: dict = {}
    try:
        intel = json.loads(row[5] or "{}")
    except Exception:
        pass
    return {
        "id": row[0], "name": row[1], "pack_type": row[2], "scope": row[3],
        "version": row[4], "intel": intel, "summary": row[6],
        "pin_state": row[7] or "unpinned",
        "refresh_state": row[8] or "current",
        "confidence": row[9] or 0.5,
    }


# Sections that users may hand-edit in the dashboard
_EDITABLE_SECTIONS = (
    "patterns", "antipatterns", "decisions", "bugs",
    "learnings", "open_questions", "processes", "tenets",
)


def save_pack_edits(conn: sqlite3.Connection, pack_id: str,
                    name: str, summary: str,
                    sections: dict) -> dict:
    """
    Persist manual edits to a pack.

    sections: dict of section_name -> list[str]  (e.g. {"patterns": [...], ...})

    Returns updated pack dict. Bumps patch version and marks refresh_state='current'.
    Does NOT overwrite sections not present in `sections` (safe partial update).
    """
    ensure_kp_tables(conn)
    row = conn.execute(
        "SELECT version, content_json FROM knowledge_packs WHERE id=?",
        (pack_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Pack {pack_id} not found")

    old_version = row[0] or "1.0.0"
    old_intel: dict = {}
    try:
        old_intel = json.loads(row[1] or "{}")
    except Exception:
        pass

    # Merge edited sections into existing intel (partial update)
    new_intel = dict(old_intel)
    for section, items in sections.items():
        if section in _EDITABLE_SECTIONS:
            # Deduplicate while preserving order; strip blank lines
            cleaned = [s.strip() for s in items if s.strip()]
            seen: set = set()
            new_intel[section] = [s for s in cleaned
                                   if not (s in seen or seen.add(s))]  # type: ignore[func-returns-value]

    content_json = json.dumps(new_intel, ensure_ascii=False)
    new_hash = _compute_pack_hash(new_intel)

    # Bump patch version
    parts = old_version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except (ValueError, IndexError):
        parts = ["1", "0", "1"]
    new_version = ".".join(parts)

    now = datetime.utcnow().isoformat()
    name = name.strip() or None  # keep original if blank

    # Write version snapshot
    import uuid as _uuid
    conn.execute("""
        INSERT INTO knowledge_pack_versions (id, pack_id, version, version_hash, content_json, diff_summary)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (_uuid.uuid4().hex, pack_id, new_version, new_hash, content_json, "manual edit via dashboard"))

    # Update main row
    update_cols = [
        "version=?", "version_hash=?", "content_json=?",
        "refresh_state='current'", "updated_at=?",
    ]
    params: list = [new_version, new_hash, content_json, now]
    if summary is not None:
        update_cols.append("summary=?")
        params.append(summary.strip())
    if name:
        update_cols.append("name=?")
        params.append(name)
    params.append(pack_id)
    conn.execute(f"UPDATE knowledge_packs SET {', '.join(update_cols)} WHERE id=?", params)
    conn.commit()

    return get_pack_by_id(conn, pack_id)


def export_kp_file(conn: sqlite3.Connection, pack_id: str) -> dict:
    """Export a pack as a .kp JSON structure (portable, importable). v2 format."""
    row = conn.execute("""
        SELECT id, name, pack_type, scope, version, version_hash,
               content_json, summary, injection_md, tags,
               dependencies, pin_state, scan_sources, refresh_state,
               confidence, provenance
        FROM knowledge_packs WHERE id=?
    """, (pack_id,)).fetchone()
    if not row:
        return {}
    intel = {}
    try:
        intel = json.loads(row[6] or "{}")
    except Exception:
        pass

    # Version history
    versions = conn.execute("""
        SELECT version, diff_summary, created_at
        FROM knowledge_pack_versions WHERE pack_id=?
        ORDER BY created_at DESC LIMIT 20
    """, (pack_id,)).fetchall()

    # Parse v2 JSON fields
    def _jparse(val, default):
        try:
            return json.loads(val or json.dumps(default))
        except Exception:
            return default

    return {
        "kp_format": "2.0",
        "id": row[0], "name": row[1], "pack_type": row[2], "scope": row[3],
        "version": row[4], "version_hash": row[5],
        "summary": row[7],
        "injection_md": row[8],
        "tags": _jparse(row[9], []),
        "exported_at": datetime.utcnow().isoformat(),
        "version_history": [{"version": v[0], "diff": v[1], "date": v[2][:10]}
                            for v in versions],
        "content": intel,
        # v2 fields
        "dependencies": _jparse(row[10], EMPTY_DEPS),
        "pin_state": row[11] or "unpinned",
        "scan_sources": _jparse(row[12], []),
        "refresh_state": row[13] or "current",
        "confidence": row[14] or 0.5,
        "provenance": _jparse(row[15], {}),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LIST & QUERY
# ═══════════════════════════════════════════════════════════════════════════════

def list_packs(conn: sqlite3.Connection) -> list[dict]:
    """List all packs with version info + v2 fields, sorted by updated_at desc."""
    ensure_kp_tables(conn)
    rows = conn.execute("""
        SELECT id, name, pack_type, scope, version, summary, is_public,
               share_token, updated_at, pin_state, refresh_state, confidence
        FROM knowledge_packs ORDER BY updated_at DESC
    """).fetchall()
    return [
        {"id": r[0], "name": r[1], "pack_type": r[2], "scope": r[3],
         "version": r[4], "summary": r[5], "is_public": bool(r[6]),
         "share_token": r[7], "updated_at": (r[8] or "")[:10],
         "pin_state": r[9] or "unpinned",
         "refresh_state": r[10] or "current",
         "confidence": r[11] or 0.5}
        for r in rows
    ]


def get_pack_versions(conn: sqlite3.Connection, pack_id: str) -> list[dict]:
    """Get version history for a pack."""
    rows = conn.execute("""
        SELECT version, version_hash, diff_summary, created_at
        FROM knowledge_pack_versions WHERE pack_id=?
        ORDER BY created_at DESC
    """, (pack_id,)).fetchall()
    return [{"version": r[0], "hash": r[1], "diff": r[2], "date": (r[3] or "")[:10]}
            for r in rows]


def get_all_projects(conn: sqlite3.Connection) -> list[dict]:
    """Get all projects for the pack selector UI."""
    rows = conn.execute("""
        SELECT project, COUNT(*) as c, MAX(started_at) as last_seen
        FROM sessions WHERE project != ''
        GROUP BY project ORDER BY last_seen DESC
    """).fetchall()
    return [{"project": r[0], "sessions": r[1], "last_seen": (r[2] or "")[:10]}
            for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# RENDERER
# ═══════════════════════════════════════════════════════════════════════════════

def render_knowledge_pack(intel: dict, mode: str = "full",
                          pack_meta: Optional[dict] = None) -> str:
    """Render a knowledge pack as styled dashboard HTML."""

    project   = intel.get("project", "")
    base_name = project.split("/")[-1] if "/" in project else project
    now       = datetime.utcnow().strftime("%b %d, %Y")

    def _esc(s): return _html_mod.escape(str(s or ""))

    def _section(title, color, content):
        if not content.strip():
            return ""
        return f"""
<div class="kp-section" style="margin-bottom:1.5rem;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:.6rem;
              padding-bottom:.4rem;border-bottom:1px solid #111820;">
    <span style="width:3px;height:14px;background:{color};border-radius:2px;display:inline-block;"></span>
    <h3 style="margin:0;font-size:.85rem;color:#dce8f5;font-weight:600;">{title}</h3>
  </div>
  {content}
</div>"""

    def _pill(text, color="#378ADD"):
        return (f'<span style="font-size:.62rem;padding:2px 8px;border-radius:10px;'
                f'background:{color}20;border:1px solid {color};color:{color};'
                f'margin:2px;display:inline-block;">{_esc(text)}</span>')

    def _item(text, sub="", color="#dce8f5"):
        sub_html = (f'<div style="color:#6a8aaa;font-size:.68rem;margin-top:1px;">'
                    f'{_esc(sub)}</div>') if sub else ""
        return (f'<div style="padding:4px 0;border-bottom:1px solid #0a0d12;">'
                f'<div style="color:{color};font-size:.75rem;">{_esc(text)}</div>'
                f'{sub_html}</div>')

    # ── Version badge ──
    version_str = ""
    share_btn   = ""
    if pack_meta:
        v   = pack_meta.get("version", "")
        pid = pack_meta.get("id", "")
        pt  = pack_meta.get("pack_type", "project")
        pt_info = PACK_TYPES.get(pt, {})
        pt_color = pt_info.get("color", "#888")
        pt_label = pt_info.get("label", "Pack")
        if v:
            version_str = (f'<span style="font-size:.6rem;padding:2px 8px;border-radius:8px;'
                           f'background:{pt_color}15;border:1px solid {pt_color}40;'
                           f'color:{pt_color};margin-left:.5rem;">v{v}</span>')
        if pid:
            share_btn = (f'<a href="/api/knowledge-pack/share/{pid}" target="_blank" '
                         f'style="font-size:.65rem;color:var(--teal);text-decoration:none;'
                         f'padding:2px 8px;border:1px solid rgba(29,158,117,0.3);'
                         f'border-radius:6px;">Share ↗</a>&nbsp;'
                         f'<a href="/api/knowledge-pack/export/{pid}" target="_blank"'
                         f' style="font-size:.65rem;color:#6a8aaa;text-decoration:none;'
                         f'padding:2px 8px;border:1px solid #1a2535;border-radius:6px;">.kp ↓</a>')
        if pack_meta.get("share_token"):
            token = pack_meta["share_token"]
            share_btn += (f'&nbsp;<span style="font-size:.6rem;color:#4a6a8a;">'
                          f'🔗 /kp/{token}</span>')

    # ── Header ──
    domain_badge = _pill(intel.get("top_domain", ""), "#E67E22")
    header = f"""
<div style="display:flex;justify-content:space-between;align-items:flex-start;
     margin-bottom:1.5rem;padding-bottom:1rem;border-bottom:2px solid #111820;">
  <div>
    <div style="display:flex;align-items:center;gap:8px;">
      <h2 style="margin:0;font-size:1.3rem;color:#fff;">{_esc(base_name)}</h2>
      {version_str}
    </div>
    <div style="font-size:.7rem;color:#6a8aaa;font-family:monospace;margin-top:2px;">{_esc(project)}</div>
    <div style="margin-top:6px;">{domain_badge}</div>
  </div>
  <div style="text-align:right;font-size:.7rem;color:#555;">
    <div style="margin-bottom:.35rem;">{share_btn}</div>
    <div>Generated {now}</div>
    <div style="margin-top:4px;">{intel['sessions']} sessions</div>
    <div>{intel['first_session']} → {intel['last_session']}</div>
  </div>
</div>"""

    content_parts = [header]

    # ── Mode: onboard — curated 5-min Day-1 view ──
    # Audit fix 2026-04-24: previously aliased to `full` (label lie). Now a
    # real onboarding view: top 5 patterns + top 3 decisions + project tenets +
    # getting-started callout. Always-fits-one-screen if intel is non-empty.
    if mode == "onboard":
        content_parts.append(
            '<div style="background:rgba(207,121,92,0.06);border-left:3px solid var(--coral,#CF795C);'
            'padding:14px 18px;margin-bottom:1.5rem;border-radius:0 8px 8px 0;">'
            '<div style="font-size:.75rem;font-weight:600;color:var(--coral,#CF795C);'
            'text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;">Getting started</div>'
            '<div style="font-size:.85rem;color:#dce8f5;line-height:1.5;">'
            f'5-minute orientation to <strong>{_esc(base_name)}</strong>. The most-cited '
            'patterns and the decisions that anchor them. For the full library use the <strong>Full</strong> '
            'mode; for a weekly digest use <strong>Digest</strong>.'
            '</div></div>'
        )
        if intel.get("patterns"):
            items = "".join(_item(p["text"], p.get("domains", ""))
                            for p in intel["patterns"][:5])
            content_parts.append(_section("Top 5 patterns to know", "#1D9E75", items))
        if intel.get("decisions"):
            items = "".join(
                _item(d["decision"], f'{d["date"]} · {d["rationale"][:80]}')
                for d in intel["decisions"][:3])
            content_parts.append(_section("Anchor decisions", "#378ADD", items))
        if intel.get("tenets"):
            items = "".join(_item(t["text"]) for t in intel["tenets"][:3])
            content_parts.append(_section("Product tenets", "#9B59B6", items))
        if intel.get("antipatterns"):
            items = "".join(_item(p["text"], "", "#D85A30")
                            for p in intel["antipatterns"][:3])
            content_parts.append(_section("⚠ First things to avoid", "#D85A30", items))
        # Footer CTA
        content_parts.append(
            '<div style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid #111820;'
            'font-size:.75rem;color:#6a8aaa;">'
            'Next: open the <strong>Full</strong> view for the complete library, '
            'or <code>kernora scan .</code> to seed more facts from git history.'
            '</div>'
        )
        return "".join(content_parts)

    # ── Mode: full ──
    if mode == "full":
        if intel.get("patterns"):
            items = "".join(_item(p["text"], p.get("domains", ""))
                            for p in intel["patterns"][:10])
            content_parts.append(_section("Best Practices", "#1D9E75", items))

        if intel.get("antipatterns"):
            items = "".join(_item(p["text"], "", "#D85A30")
                            for p in intel["antipatterns"][:8])
            content_parts.append(_section("⚠ Anti-Patterns (NEVER do)", "#D85A30", items))

        if intel.get("decisions"):
            items = "".join(
                _item(d["decision"], f'{d["date"]} · {d["rationale"][:80]}')
                for d in intel["decisions"][:8])
            content_parts.append(_section("Architecture Decisions", "#378ADD", items))

        if intel.get("processes"):
            items = "".join(_item(p["name"], p.get("steps", "")[:100])
                            for p in intel["processes"][:8])
            content_parts.append(_section("Defined Processes", "#BA7517", items))

        if intel.get("tenets"):
            items = "".join(_item(t["text"]) for t in intel["tenets"][:8])
            content_parts.append(_section("Product Tenets", "#9B59B6", items))

        if intel.get("learnings"):
            items = "".join(_item(l["text"], l.get("domain", ""))
                            for l in intel["learnings"][:10])
            content_parts.append(_section("Compounding Learnings", "#1ABC9C", items))

        if intel.get("technologies"):
            pills = "".join(_pill(t["name"], "#378ADD")
                            for t in intel["technologies"][:15])
            content_parts.append(_section("Tech Stack", "#378ADD",
                f'<div style="display:flex;flex-wrap:wrap;gap:4px;">{pills}</div>'))

        ei = intel.get("eng_intel", {})
        ei_items = []
        for label, key in [("System Design", "system_design"), ("Tech Debt", "tech_debt"),
                            ("Performance", "performance_targets"),
                            ("Infrastructure", "infrastructure")]:
            for it in (ei.get(key) or [])[:3]:
                if it:
                    ei_items.append(_item(str(it)[:120], label))
        if ei_items:
            content_parts.append(_section("Engineering Intelligence", "#555",
                                          "".join(ei_items)))

        if intel.get("tool_candidates"):
            items = "".join(
                _item(tc["name"], f'{tc["complexity"]} · {tc["rationale"][:80]}')
                for tc in intel["tool_candidates"][:8])
            content_parts.append(_section("Automation Opportunities", "#1D9E75", items))

        if intel.get("open_questions"):
            items = "".join(_item(q, "", "#BA7517")
                            for q in intel["open_questions"][:6])
            content_parts.append(_section("Open Questions", "#BA7517", items))

    # ── Mode: vc ──
    elif mode == "vc":
        if intel.get("tenets"):
            items = "".join(
                f'<div style="padding:6px 0;border-bottom:1px solid #0a0d12;'
                f'color:#dce8f5;font-size:.8rem;">"{_esc(t["text"])}"</div>'
                for t in intel["tenets"][:5])
            content_parts.append(_section("Product Principles", "#9B59B6", items))

        if intel.get("technologies"):
            pills = "".join(_pill(t["name"], "#378ADD")
                            for t in intel["technologies"][:12])
            content_parts.append(_section("Tech Stack", "#378ADD",
                f'<div style="display:flex;flex-wrap:wrap;gap:4px;">{pills}</div>'))

        if intel.get("key_discussions"):
            items = "".join(_item(kd["text"], kd.get("status", ""))
                            for kd in intel["key_discussions"][:8])
            content_parts.append(_section("Strategic Discussions", "#E67E22", items))

        if intel.get("decisions"):
            items = "".join(
                _item(d["decision"], d["rationale"][:80])
                for d in intel["decisions"][:5])
            content_parts.append(_section("Architecture Decisions", "#378ADD", items))

        if intel.get("open_questions"):
            items = "".join(_item(q, "", "#BA7517")
                            for q in intel["open_questions"][:5])
            content_parts.append(_section("Open Questions", "#BA7517", items))

    # ── Mode: digest ──
    elif mode == "digest":
        if intel.get("decisions"):
            items = "".join(
                _item(d["decision"], d.get("rationale", "")[:80])
                for d in intel["decisions"][:6])
            content_parts.append(_section("Decisions This Week", "#378ADD", items))
        if intel.get("learnings"):
            items = "".join(_item(l["text"])
                            for l in intel["learnings"][:6])
            content_parts.append(_section("New Learnings", "#1ABC9C", items))
        if intel.get("bugs"):
            sev_colors = {"critical": "#C0392B", "high": "#D85A30",
                          "medium": "#BA7517", "low": "#6a8aaa"}
            items = "".join(
                _item(b["title"], b["severity"],
                      sev_colors.get(b["severity"], "#888"))
                for b in intel["bugs"][:5])
            content_parts.append(_section("Open Bugs", "#D85A30", items))

    return "".join(content_parts)


def render_version_history_html(versions: list[dict]) -> str:
    """Render pack version history as HTML."""
    if not versions:
        return '<div style="color:#4a6a8a;font-size:.75rem;">No version history yet.</div>'
    rows = []
    for v in versions:
        ver   = _html_mod.escape(v.get("version", ""))
        diff  = _html_mod.escape(v.get("diff", ""))
        date  = _html_mod.escape(v.get("date", ""))
        h     = v.get("hash", "")[:8]
        rows.append(
            f'<div style="display:flex;align-items:center;gap:.75rem;padding:.4rem 0;'
            f'border-bottom:1px solid #0a0d12;font-size:.72rem;">'
            f'<span style="color:var(--teal);font-weight:600;min-width:50px;">v{ver}</span>'
            f'<span style="color:#4a6a8a;min-width:70px;">{date}</span>'
            f'<span style="color:#dce8f5;flex:1">{diff}</span>'
            f'<span style="color:#2e4460;font-family:monospace;font-size:.6rem;">{h}</span>'
            f'</div>'
        )
    return "".join(rows)
