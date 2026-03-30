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
            token_cost       INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS patterns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT REFERENCES sessions(id),
            pattern     TEXT,
            code_example TEXT DEFAULT '',
            domains     TEXT DEFAULT '',
            context     TEXT DEFAULT '',
            effectiveness REAL DEFAULT 0.7,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT REFERENCES sessions(id),
            decision    TEXT,
            context     TEXT DEFAULT '',
            rationale   TEXT DEFAULT '',
            alternatives TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reported_bugs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT REFERENCES sessions(id),
            title           TEXT,
            file_path       TEXT DEFAULT '',
            error_signature TEXT DEFAULT '',
            fix_code        TEXT DEFAULT '',
            severity        TEXT DEFAULT 'medium',
            status          TEXT DEFAULT 'open',
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_analyzed
            ON sessions(analyzed, inserted_at);
        CREATE INDEX IF NOT EXISTS idx_insights_session
            ON insights(session_id);
        CREATE INDEX IF NOT EXISTS idx_patterns_session
            ON patterns(session_id);
        CREATE INDEX IF NOT EXISTS idx_decisions_session
            ON decisions(session_id);
        CREATE INDEX IF NOT EXISTS idx_bugs_session
            ON reported_bugs(session_id);
    """)

    # -- FTS5 indexes for context search --
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_patterns USING fts5(
            pattern, code_example, domains, context,
            content='patterns', content_rowid='id'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_decisions USING fts5(
            decision, context, rationale, alternatives,
            content='decisions', content_rowid='id'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_bugs USING fts5(
            title, file_path, error_signature, fix_code,
            content='reported_bugs', content_rowid='id'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_insights USING fts5(
            summary, themes, playbook, anti_patterns, project_rules,
            knowledge_domains, reusable_patterns,
            content='insights', content_rowid='id'
        );
        CREATE TABLE IF NOT EXISTS nora_metrics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT NOT NULL,
            prompt_hash TEXT,
            result_type TEXT,
            result_id   INTEGER,
            rank        REAL,
            keywords    TEXT,
            latency_ms  REAL,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_nora_metrics_type
            ON nora_metrics(event_type, created_at);
    """)

    # ── v2 schema: deep extraction columns (additive — never drops existing) ─────
    _add_columns(conn, "insights", {
        "session_type":            "TEXT DEFAULT ''",
        "playbook":                "TEXT DEFAULT ''",
        "architectural_decisions": "TEXT DEFAULT '[]'",
        "effective_prompts":       "TEXT DEFAULT '[]'",
        "anti_patterns":           "TEXT DEFAULT '[]'",
        "project_rules":         "TEXT DEFAULT '[]'",
        "knowledge_domains":       "TEXT DEFAULT '[]'",
        "tools_used":              "TEXT DEFAULT '{}'",
        "files_touched":           "TEXT DEFAULT '[]'",
        "commands_run":            "TEXT DEFAULT '[]'",
        "reusable_patterns":       "TEXT DEFAULT '[]'",
        "workflow_stage":          "TEXT DEFAULT ''",
    })

    conn.commit()
    conn.close()
    print(f"[nora] DB initialized at {DB_PATH}")


def _add_columns(conn: sqlite3.Connection, table: str, columns: dict):
    """Idempotently add columns — skips if they already exist."""
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, typedef in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            print(f"[nora] added column {table}.{col}")


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


def mark_analyzed(session_id: str, insight: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO insights
            (session_id, analyzed_at, themes, bugs, optimizations,
             prompt_quality, prompt_avg_words, repetition_count,
             skill_opportunity, summary, token_cost,
             session_type, playbook, architectural_decisions,
             effective_prompts, anti_patterns, project_rules,
             knowledge_domains, tools_used, files_touched,
             commands_run, reusable_patterns, workflow_stage)
        VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        # ── v2 deep extraction fields ──
        insight.get("session_type", ""),
        insight.get("playbook", ""),
        json.dumps(insight.get("architectural_decisions", [])),
        json.dumps(insight.get("effective_prompts", [])),
        json.dumps(insight.get("anti_patterns", [])),
        json.dumps(insight.get("project_rules", [])),
        json.dumps(insight.get("knowledge_domains", [])),
        json.dumps(insight.get("tools_used", {})),
        json.dumps(insight.get("files_touched", [])),
        json.dumps(insight.get("commands_run", [])),
        json.dumps(insight.get("reusable_patterns", [])),
        insight.get("workflow_stage", ""),
    ))
    conn.execute(
        "UPDATE sessions SET analyzed = 1 WHERE id = ?", (session_id,)
    )
    conn.commit()
    conn.close()


def get_session(session_id: str) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


if __name__ == "__main__":
    init_db()
