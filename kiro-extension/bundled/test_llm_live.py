"""
LIVE integration tests — requires running servers. Not for CI.
"""
import os
import json
import time
import urllib.request
import urllib.error
import sqlite3
import uuid

import pytest

import dashboard
import analyzer
from db import get_conn

def _check_server_running(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.0)
        return True
    except Exception:
        return False

def _ping_health(port: int) -> dict:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        with urllib.request.urlopen(req, timeout=5.0) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        pytest.skip(f"server at port {port} not running / connection refused. {e}")
    except Exception as e:
        pytest.skip(f"server at port {port} failed health probe: {e}")

def _post_analyze(port: int, transcript: str) -> tuple[dict, float]:
    try:
        data = json.dumps({"transcript": transcript}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/analyze",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=40.0) as r:
            d = json.loads(r.read())
        t1 = time.time()
        return d, (t1 - t0)
    except urllib.error.URLError:
        pytest.skip(f"server at port {port} not running; connection refused")
    except urllib.error.HTTPError as e:
        pytest.fail(f"HTTP error on port {port}: {e}")
    except Exception as e:
        pytest.fail(f"analyze on port {port} failed: {e}")

def test_local_llm_foundationmodels_health():
    data = _ping_health(2744)
    assert data.get("ok") is True
    assert data.get("model") == "apple-foundationmodels"
    assert data.get("context_window") == 4096

def test_local_llm_foundationmodels_analyze():
    data, duration = _post_analyze(2744, "user: Fix the JWT token validation\\nassistant: I'll check the expiry logic")
    assert "prompt_quality" in data
    assert isinstance(data["prompt_quality"], (float, int))
    assert "themes" in data
    assert isinstance(data["themes"], list)
    assert "summary" in data
    assert isinstance(data["summary"], str)
    assert duration < 30.0

def test_local_llm_mlx_health():
    data = _ping_health(2745)
    assert data.get("ok") is True
    assert "Qwen" in data.get("model", "")

def test_local_llm_mlx_analyze():
    data, duration = _post_analyze(2745, "user: Fix the JWT token validation\\nassistant: I'll check the expiry logic")
    assert "prompt_quality" in data
    assert isinstance(data["prompt_quality"], (float, int))
    assert "themes" in data
    assert isinstance(data["themes"], list)
    assert "summary" in data
    assert isinstance(data["summary"], str)
    assert duration < 30.0

def test_probe_local_llm_live():
    res = analyzer.probe_local_llm()
    server_runs = _check_server_running(2744) or _check_server_running(2745)
    if server_runs:
        assert res.get("ok") is True
        assert bool(res.get("model"))
    else:
        assert res.get("ok") is False

def test_ide_llm_detection():
    ide = os.environ.get("KERNORA_IDE")
    print("\\n--- IDE LLM Detection Status ---")
    if ide:
        print(f"KERNORA_IDE detected: {ide}")
    else:
        print("KERNORA_IDE not set in environment.")
    
    with dashboard._ide_heartbeat_lock:
        cache = dashboard._ide_heartbeat_cache
    
    print(f"IDE Heartbeat Cache: {cache}")
    if time.time() - cache["ts"] < 60 and cache["ok"]:
        print("IDE LLM is Reachable and healthy")
    else:
        print("IDE LLM is currently Unreachable (no recent heartbeat)")
    print("--------------------------------")

def test_full_analysis_pipeline_live():
    # Setup test DB access
    db = get_conn()
    sid = "live-test-" + str(uuid.uuid4())[:8]
    
    # Check if we should skip
    local_ok = analyzer.probe_local_llm().get("ok")
    cloud_ok = dashboard.probe_llm().get("ok")
    with dashboard._ide_heartbeat_lock:
        ide_ok = (time.time() - dashboard._ide_heartbeat_cache["ts"] < 60) and dashboard._ide_heartbeat_cache["ok"]
    
    if not any([local_ok, cloud_ok, ide_ok]):
        pytest.skip("No LLM available (no local server, API key, or IDE loop) -> skipping full analysis")
        
    db.execute("INSERT INTO sessions (id, project, started_at) VALUES (?, ?, datetime('now'))", (sid, "live-test-project"))
    db.execute("INSERT INTO turns (session_id, user_msg, assistant_msg) VALUES (?, ?, ?)", 
               (sid, "Create a fast sorting algorithm", "I suggest quicksort here is the implementation..."))
    db.commit()
    
    # Run pipeline manually
    try:
        dashboard._run_analysis()
        
        row = db.execute("SELECT analyzed, model FROM sessions WHERE id = ?", (sid,)).fetchone()
        assert row["analyzed"] == 1
        assert row["model"] != ""
        
        insights = db.execute("SELECT * FROM insights WHERE session_id = ?", (sid,)).fetchone()
        assert insights is not None
    finally:
        # cleanup
        db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        db.execute("DELETE FROM turns WHERE session_id = ?", (sid,))
        db.execute("DELETE FROM insights WHERE session_id = ?", (sid,))
        db.commit()
