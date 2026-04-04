# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyzer import probe_local_llm, LocalLLMError, _validate_local_result

class MockResponse:
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status = status_code

    def read(self):
        return json.dumps(self.json_data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

def test_probe_local_llm_both_available():
    def mock_urlopen(url, *args, **kwargs):
        if ":2744/health" in url:
            return MockResponse({"ok": True}, 200)
        elif ":2745/health" in url:
            return MockResponse({"ok": True}, 200)
        raise Exception("Unknown URL")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        res = probe_local_llm()
        assert res["ok"] is True
        assert res["port"] == 2744
        assert res["model"] == "apple-foundationmodels"

def test_probe_local_llm_mlx_only():
    def mock_urlopen(url, *args, **kwargs):
        if ":2744/health" in url:
            raise Exception("Connection Refused")
        elif ":2745/health" in url:
            return MockResponse({"ok": True}, 200)
        raise Exception("Unknown URL")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        res = probe_local_llm()
        assert res["ok"] is True
        assert res["port"] == 2745
        assert res["model"] == "mlx-qwen2.5-coder-3b"

def test_probe_local_llm_neither():
    def mock_urlopen(url, *args, **kwargs):
        raise Exception("Connection Refused")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        res = probe_local_llm()
        assert res["ok"] is False
        assert res["port"] == 0

def test_validate_local_result_fixes_bad_data():
    bad_data = {
        "prompt_quality": 5.5,
        "themes": [{"severity": "extreme"}],
        "bugs": None,
        "optimizations": [{"impact": "massive"}],
        "summary": 123
    }
    fixed = _validate_local_result(bad_data)
    assert fixed["prompt_quality"] == 1.0 # Clamped 0-1
    assert fixed["themes"][0]["severity"] == "medium"
    assert fixed["bugs"] == []
    assert fixed["optimizations"][0]["impact"] == "medium"
    assert fixed["summary"] == ""
    assert fixed["model_used"] == "local/unknown"
