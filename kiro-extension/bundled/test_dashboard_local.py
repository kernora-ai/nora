# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
import sys
import os
import sqlite3
import pytest
import tempfile
from hypothesis import given, settings, strategies as st, HealthCheck

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dashboard import app, probe_local_llm

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        started_at TEXT,
        ended_at TEXT,
        project TEXT,
        model TEXT,
        tokens_in INTEGER,
        tokens_out INTEGER,
        turns_json TEXT,
        analyzed INTEGER DEFAULT 0,
        ide_llm_failed INTEGER DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE insights (
        session_id TEXT PRIMARY KEY,
        themes TEXT,
        bugs INTEGER,
        prompt_quality REAL,
        prompt_avg_words INTEGER,
        repetition_count INTEGER,
        skill_opportunity TEXT,
        summary TEXT,
        token_cost INTEGER,
        analysis_source TEXT,
        model_used TEXT
    )""")
    conn.commit()
    conn.close()
    
    yield path
    os.remove(path)

@pytest.fixture
def dashboard_client(temp_db, monkeypatch):
    import dashboard
    from pathlib import Path
    dashboard.DB = Path(temp_db)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_health_endpoint_local_llm(dashboard_client, monkeypatch):
    def mock_probe_local():
        return {"ok": True, "provider": "local", "model": "mlx-qwen2.5-coder-3b", "port": 2745, "reason": "test"}
    monkeypatch.setattr("dashboard.probe_local_llm", mock_probe_local)
    
    resp = dashboard_client.get("/health")
    data = resp.get_json()
    assert "local_llm" in data
    assert data["local_llm"]["available"] is True
    assert data["local_llm"]["model"] == "mlx-qwen2.5-coder-3b"

@given(
    model_used=st.sampled_from(["local/apple-foundationmodels", "local/mlx-qwen2.5-coder-3b", "cloud/claude", ""]),
)
@settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_session_detail_local_badges(temp_db, dashboard_client, model_used):
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT OR REPLACE INTO sessions (id, analyzed) VALUES ('demo_sess', 1)")
    conn.execute("INSERT OR REPLACE INTO insights (session_id, model_used, analysis_source) VALUES ('demo_sess', ?, 'local')", (model_used,))
    conn.commit()
    conn.close()
    
    resp = dashboard_client.get("/sessions/demo_sess")
    html = resp.data.decode("utf-8")
    
    if "foundationmodels" in model_used:
        assert "Powered by Apple Intelligence" in html
        assert "#1D9E75" in html
    elif "mlx" in model_used:
        assert "Powered by MLX-LM" in html
        assert "#BA7517" in html
    else:
        assert "Powered by " not in html
