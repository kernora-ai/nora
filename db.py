#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
import json
import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".kernora" / "echo.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        -- Core session storage
        CREATE TABLE IF NOT EXISTS sessions (
            id           TEXT PRIMARY KEY,
            project      TEXT,
            started_at   TEXT,
            ended_at     TEXT,
            tokens_in    INTEGER DEFAULT 0,
            tokens_out   INTEGER DEFAULT 0,
            model        TEXT,
            turns_json   TEXT,
            analyzed     INTEGER DEFAULT 0,
            inserted_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS insights (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id       TEXT REFERENCES sessions(id),
            analyzed_at      TEXT,
            themes           TEXT,
            bugs             TEXT,
            optimizations    TEXT,
            prompt_quality   REAL DEFAULT 0,
            prompt_avg_words INTEGER DEFAULT 0,
            repetition_count INTEGER DEFAULT 0,
            skill_opportunity TEXT,
            summary          TEXT,
            token_cost       INTEGER DEFAULT 0,
            prompt_coaching         TEXT,
            prompt_antipatterns     TEXT,
            tokens_estimated        INTEGER DEFAULT 0,
            session_type            TEXT,
            playbook                TEXT,
            architectural_decisions TEXT,
            anti_patterns           TEXT,
            claude_md_rules         TEXT,
            knowledge_domains       TEXT,
            reusable_patterns       TEXT,
            files_touched           TEXT,
            tools_used              TEXT,
            agent_workflow_rules    TEXT,
            analysis_source         TEXT DEFAULT 'byok'
        );

        -- Intelligence tables (populated by analysis daemon, queried by MCP tools)
        CREATE TABLE IF NOT EXISTS patterns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT,
            pattern         TEXT NOT NULL,
            code_example    TEXT,
            effectiveness   REAL DEFAULT 0,
            domains         TEXT,
            context         TEXT,
            session_id      TEXT REFERENCES sessions(id),
            created_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(pattern)
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            decision        TEXT NOT NULL,
            rationale       TEXT,
            alternatives    TEXT,
            files           TEXT,
            context         TEXT,
            project         TEXT,
            session_id      TEXT REFERENCES sessions(id),
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reported_bugs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT NOT NULL,
            severity        TEXT DEFAULT 'medium',
            error_signature TEXT DEFAULT '',
            file_path       TEXT,
            status          TEXT DEFAULT 'open',
            fix_code        TEXT,
            session_id      TEXT REFERENCES sessions(id),
            created_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(title)
        );
        CREATE TABLE IF NOT EXISTS inference_jobs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT REFERENCES sessions(id),
            prompt          TEXT NOT NULL,
            response        TEXT,
            status          TEXT DEFAULT 'pending',
            error           TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS hook_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,
            session_id  TEXT,
            file_path   TEXT,
            detail      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS nora_metrics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,
            prompt_hash TEXT,
            result_type TEXT,
            result_id   INTEGER,
            rank        INTEGER,
            keywords    TEXT,
            latency_ms  REAL,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS insight_patterns (
            session_id  TEXT REFERENCES sessions(id),
            pattern_id  INTEGER REFERENCES patterns(id),
            UNIQUE(session_id, pattern_id)
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_sessions_analyzed
            ON sessions(analyzed, inserted_at);
        CREATE INDEX IF NOT EXISTS idx_insights_session
            ON insights(session_id);
        CREATE INDEX IF NOT EXISTS idx_patterns_effectiveness
            ON patterns(effectiveness DESC);
        CREATE INDEX IF NOT EXISTS idx_decisions_project
            ON decisions(project);
        CREATE INDEX IF NOT EXISTS idx_bugs_status
            ON reported_bugs(status);
        CREATE INDEX IF NOT EXISTS idx_hook_events_created
            ON hook_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_nora_metrics_type
            ON nora_metrics(event_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_insight_patterns 
            ON insight_patterns(pattern_id);
    """)

    # Migrations
    NEW_INSIGHT_COLS = [
        ("prompt_coaching",         "TEXT"),
        ("prompt_antipatterns",     "TEXT"),
        ("tokens_estimated",        "INTEGER DEFAULT 0"),
        ("session_type",            "TEXT"),
        ("playbook",                "TEXT"),
        ("architectural_decisions", "TEXT"),
        ("anti_patterns",           "TEXT"),
        ("claude_md_rules",         "TEXT"),
        ("knowledge_domains",       "TEXT"),
        ("reusable_patterns",       "TEXT"),
        ("files_touched",           "TEXT"),
        ("tools_used",              "TEXT"),
        ("agent_workflow_rules",    "TEXT"),
        ("analysis_source",         "TEXT DEFAULT 'byok'"),
    ]
    def _add_cols(tbl, cols):
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        for col, col_type in cols:
            if col not in existing:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_type}")

    _add_cols("insights", NEW_INSIGHT_COLS)
            
    OTHER_MIGRATIONS = [
        ("patterns", "name", "TEXT"),
        ("patterns", "code_example", "TEXT"),
        ("decisions", "files", "TEXT"),
        ("decisions", "context", "TEXT"),
        ("reported_bugs", "error_signature", "TEXT DEFAULT ''"),
    ]
    from collections import defaultdict
    other = defaultdict(list)
    for t, c, ct in OTHER_MIGRATIONS:
        other[t].append((c, ct))
    for t, cols in other.items():
        _add_cols(t, cols)
        
    conn.commit()
    conn.close()
    print(f"[kernora] DB initialized at {DB_PATH}")


def store_session(payload: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO sessions
            (id, project, started_at, ended_at,
             tokens_in, tokens_out, model, turns_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payload.get("session_id", ""),
        payload.get("project", ""),
        payload.get("started_at", ""),
        payload.get("ended_at", ""),
        payload.get("tokens_in", 0),
        payload.get("tokens_out", 0),
        payload.get("model", ""),
        json.dumps(payload.get("turns", [])),
    ))
    conn.commit()
    conn.close()


def get_unanalyzed(limit: int = 20) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions WHERE analyzed = 0 ORDER BY inserted_at LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_analyzed(session_id: str, insight: dict, analysis_source: str = 'byok'):
    conn = get_conn()
    with conn:
        conn.execute("""
            INSERT INTO insights
                (session_id, analyzed_at, themes, bugs, optimizations,
                 prompt_quality, prompt_avg_words, repetition_count,
                 skill_opportunity, summary, token_cost,
                 prompt_coaching, prompt_antipatterns, tokens_estimated,
                 session_type, playbook, architectural_decisions,
                 anti_patterns, claude_md_rules, knowledge_domains,
                 reusable_patterns, files_touched, tools_used, agent_workflow_rules, analysis_source)
            VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
        session_id,
        json.dumps(insight.get("themes", [])),
        json.dumps(insight.get("bugs", [])),
        json.dumps(insight.get("optimizations", [])),
        insight.get("prompt_quality", 0),
        insight.get("prompt_avg_words", 0),
        insight.get("repetition_count", 0),
        insight.get("skill_opportunity", ""),
        insight.get("summary", ""),
        insight.get("token_cost", 0),
        insight.get("prompt_coaching", ""),
        json.dumps(insight.get("prompt_antipatterns", [])),
        insight.get("tokens_estimated", 0),
        insight.get("session_type", ""),
        insight.get("playbook", ""),
        json.dumps(insight.get("architectural_decisions", [])),
        json.dumps(insight.get("anti_patterns", [])),
        json.dumps(insight.get("claude_md_rules", [])),
        json.dumps(insight.get("knowledge_domains", [])),
        json.dumps(insight.get("reusable_patterns", [])),
        json.dumps(insight.get("files_touched", [])),
        json.dumps(insight.get("tools_used", [])),
        json.dumps(insight.get("agent_workflow_rules", [])),
        analysis_source
    ))
    
        for p in insight.get("reusable_patterns", []):
            if not isinstance(p, dict): continue
            conn.execute("""
                INSERT OR IGNORE INTO patterns (name, pattern, code_example, domains, context, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (p.get("name"), p.get("pattern"), p.get("code_example"), json.dumps(p.get("domains", [])), p.get("context"), session_id))
        
            p_row = conn.execute("SELECT id FROM patterns WHERE pattern = ?", (p.get("pattern"),)).fetchone()
            if p_row:
                conn.execute("INSERT OR IGNORE INTO insight_patterns (session_id, pattern_id) VALUES (?, ?)", (session_id, p_row[0]))

        for d in insight.get("architectural_decisions", []):
            if not isinstance(d, dict): continue
            conn.execute("""
                INSERT INTO decisions (decision, rationale, alternatives, files, context, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (d.get("decision"), d.get("rationale"), json.dumps(d.get("alternatives", [])), json.dumps(d.get("files", [])), d.get("context"), session_id))

        for b in insight.get("bugs", []):
            if not isinstance(b, dict): continue
            conn.execute("""
                INSERT OR IGNORE INTO reported_bugs (title, severity, error_signature, file_path, fix_code, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (b.get("title"), b.get("severity", "medium"), b.get("error_signature", ""), b.get("file_path"), b.get("fix_code"), session_id))

        conn.execute("UPDATE sessions SET analyzed = 1 WHERE id = ?", (session_id,))
        conn.commit()
    conn.close()


def _calculate_effectiveness(conn, pattern_id: int, total_sessions: int, pattern_text: str) -> float:
    if total_sessions <= 0: return 0.0
    inj = conn.execute("SELECT COUNT(*) FROM nora_metrics WHERE event_type = 'impression' AND result_type = 'pattern' AND result_id = ?", (pattern_id,)).fetchone()[0]
    freq_row = conn.execute("SELECT COUNT(*) FROM insight_patterns WHERE pattern_id = ?", (pattern_id,)).fetchone()
    freq = float(freq_row[0]) / total_sessions if freq_row and freq_row[0] is not None else 0.0
    return round((inj * 0.6) + (freq * 0.4), 2)


def get_session(session_id: str) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


# ── Inference Job Queue (IDE integration) ──

def queue_inference_job(session_id: str, prompt: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO inference_jobs (session_id, prompt) VALUES (?, ?)",
        (session_id, prompt)
    )
    conn.commit()
    conn.close()


def get_pending_job() -> dict:
    """"Returns the oldest pending job and atomically marks it as processing."""
    conn = get_conn()
    # Step 1: SELECT
    job_row = conn.execute("""
        SELECT * FROM inference_jobs 
        WHERE status = 'pending' OR (status = 'processing' AND updated_at < datetime('now', '-10 minutes')) 
        ORDER BY id ASC LIMIT 1
    """).fetchone()
    
    if not job_row:
        conn.close()
        return {}
        
    # Step 2: UPDATE (only if row found)
    job_id = job_row["id"]
    cursor = conn.execute("""
        UPDATE inference_jobs 
        SET status = 'processing', updated_at = datetime('now') 
        WHERE id = ? AND (status = 'pending' OR status = 'processing')
    """, (job_id,))
    
    if cursor.rowcount == 0:
        conn.close()
        return {}
    
    conn.commit()
    conn.close()
    return dict(job_row)


def complete_job(job_id: int, response: str):
    conn = get_conn()
    conn.execute(
        "UPDATE inference_jobs SET status = 'completed', response = ?, updated_at = datetime('now') WHERE id = ?",
        (response, job_id)
    )
    conn.commit()
    conn.close()


def fail_job(job_id: int, error: str):
    conn = get_conn()
    conn.execute(
        "UPDATE inference_jobs SET status = 'error', error = ?, updated_at = datetime('now') WHERE id = ?",
        (error, job_id)
    )
    conn.commit()
    conn.close()


def get_jobs_for_session(session_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM inference_jobs WHERE session_id = ? ORDER BY id ASC",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_jobs_for_session(session_id: str):
    conn = get_conn()
    conn.execute("DELETE FROM inference_jobs WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
