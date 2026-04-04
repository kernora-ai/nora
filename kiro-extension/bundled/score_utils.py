# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
import json
from datetime import date, timedelta

def _compute_injection_hit_rate(db, since_expr="datetime('now', '-30 days')", until_expr="datetime('now')", project_filter=None) -> float:
    """V1 proxy: ratio of injections where next prompt contains injected keywords."""
    query = f"""
        SELECT nm.keywords, s.turns_json
        FROM nora_metrics nm
        JOIN sessions s ON nm.session_id = s.id
        WHERE nm.event_type = 'impression'
          AND nm.created_at > {since_expr}
          AND nm.created_at <= {until_expr}
          AND nm.session_id IS NOT NULL
          AND nm.keywords IS NOT NULL
    """
    if project_filter is not None:
        query += " AND s.project = ?"
        rows = db.execute(query, (project_filter,)).fetchall()
    else:
        rows = db.execute(query).fetchall()
    
    if not rows:
        return 0.0
    
    hits = 0
    for kw_json, turns_json in rows:
        try:
            keywords = json.loads(kw_json) if isinstance(kw_json, str) else []
            turns = json.loads(turns_json) if isinstance(turns_json, str) else []
            for turn in turns:
                role = turn.get("role", "")
                if role == "human":
                    msg = turn.get("message", {})
                    content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
                    content_lower = content.lower()
                    if any(kw.lower() in content_lower for kw in keywords if kw):
                        hits += 1
                        break
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue
    
    return hits / len(rows)

def compute_leverage(db, since_expr="datetime('now', '-30 days')", until_expr="datetime('now')", project_filter=None) -> dict:
    """Compute AI Leverage Score and all sub-metrics."""
    if project_filter is not None:
        session_count = db.execute(f"""
            SELECT COUNT(i.session_id) FROM insights i
            JOIN sessions s ON i.session_id = s.id
            WHERE i.analyzed_at > {since_expr}
              AND i.analyzed_at <= {until_expr}
              AND s.project = ?
        """, (project_filter,)).fetchone()[0]
    else:
        session_count = db.execute(f"""
            SELECT COUNT(*) FROM insights 
            WHERE analyzed_at > {since_expr}
              AND analyzed_at <= {until_expr}
        """).fetchone()[0]
    
    if session_count < 3:
        return {
            "score": None, "label": "Not enough data", "label_color": "#6a8aaa",
            "sub_metrics": {}, "enough_data": False,
        }
    
    if project_filter is not None:
        pq_row = db.execute(f"""
            SELECT AVG(i.prompt_quality) FROM insights i
            JOIN sessions s ON i.session_id = s.id
            WHERE i.analyzed_at > {since_expr}
              AND i.analyzed_at <= {until_expr} 
              AND i.prompt_quality > 0
              AND s.project = ?
        """, (project_filter,)).fetchone()
    else:
        pq_row = db.execute(f"""
            SELECT AVG(prompt_quality) FROM insights 
            WHERE analyzed_at > {since_expr}
              AND analyzed_at <= {until_expr} 
              AND prompt_quality > 0
        """).fetchone()
    prompt_quality = pq_row[0] if pq_row and pq_row[0] else 0.0
    
    injection_hit_rate = _compute_injection_hit_rate(db, since_expr, until_expr, project_filter)
    
    if project_filter is not None:
        dar_row = db.execute(f"""
            SELECT CAST(SUM(CASE WHEN dt.delta_type = 'accepted' THEN 1 ELSE 0 END) AS REAL)
                   / NULLIF(COUNT(*), 0)
            FROM decision_traces dt
            JOIN sessions s ON dt.session_id = s.id
            WHERE dt.created_at > {since_expr}
              AND dt.created_at <= {until_expr}
              AND s.project = ?
        """, (project_filter,)).fetchone()
    else:
        dar_row = db.execute(f"""
            SELECT CAST(SUM(CASE WHEN delta_type = 'accepted' THEN 1 ELSE 0 END) AS REAL)
                   / NULLIF(COUNT(*), 0)
            FROM decision_traces
            WHERE created_at > {since_expr}
              AND created_at <= {until_expr}
        """).fetchone()
    decision_acceptance_rate = dar_row[0] if dar_row and dar_row[0] else 0.0
    
    if project_filter is not None:
        par_row = db.execute(f"""
            SELECT CAST(COUNT(DISTINCT p.session_id) AS REAL)
                   / NULLIF((SELECT COUNT(*) FROM sessions WHERE ended_at > {since_expr} AND ended_at <= {until_expr} AND project = ?), 0)
            FROM patterns p
            JOIN sessions s ON p.session_id = s.id
            WHERE s.ended_at > {since_expr}
              AND s.ended_at <= {until_expr}
              AND s.project = ?
        """, (project_filter, project_filter)).fetchone()
    else:
        par_row = db.execute(f"""
            SELECT CAST(COUNT(DISTINCT p.session_id) AS REAL)
                   / NULLIF((SELECT COUNT(*) FROM sessions WHERE ended_at > {since_expr} AND ended_at <= {until_expr}), 0)
            FROM patterns p
            JOIN sessions s ON p.session_id = s.id
            WHERE s.ended_at > {since_expr}
              AND s.ended_at <= {until_expr}
        """).fetchone()
    pattern_accumulation_rate = par_row[0] if par_row and par_row[0] else 0.0
    
    prompt_quality = max(0.0, min(1.0, prompt_quality))
    injection_hit_rate = max(0.0, min(1.0, injection_hit_rate))
    decision_acceptance_rate = max(0.0, min(1.0, decision_acceptance_rate))
    pattern_accumulation_rate = max(0.0, min(1.0, pattern_accumulation_rate))
    
    composite = (
        prompt_quality * 0.4
        + injection_hit_rate * 0.3
        + decision_acceptance_rate * 0.2
        + pattern_accumulation_rate * 0.1
    )
    
    score = round(1.0 + (composite * 4.0), 1)
    label, color = _leverage_label(score)
    
    return {
        "score": score,
        "label": label,
        "label_color": color,
        "enough_data": True,
        "sub_metrics": {
            "prompt_quality": round(prompt_quality, 3),
            "injection_hit_rate": round(injection_hit_rate, 3),
            "decision_acceptance_rate": round(decision_acceptance_rate, 3),
            "pattern_accumulation_rate": round(pattern_accumulation_rate, 3),
        },
    }

def _leverage_label(score: float) -> tuple[str, str]:
    """Return (label, hex_color) for a leverage score."""
    if score >= 4.0:
        return ("Excellent", "#1D9E75")
    elif score >= 3.0:
        return ("Strong", "#378ADD")
    elif score >= 2.0:
        return ("Developing", "#BA7517")
    else:
        return ("Early", "#D85A30")

def get_leverage_history(db, project_filter=None) -> list[dict]:
    results = []
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    for i in range(8):
        start = monday - timedelta(weeks=i)
        end = start + timedelta(weeks=1)
        lev = compute_leverage(db, f"'{start.isoformat()}'", f"'{end.isoformat()}'", project_filter)
        if lev["enough_data"]:
            results.append({"week_start": start.isoformat(), "score": lev["score"]})
    results.reverse()
    return results

