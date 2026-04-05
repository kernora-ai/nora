import unittest
from unittest.mock import patch, MagicMock
from io import BytesIO
import json
import urllib.error

# Assuming analyzer.py is the target module
from analyzer import probe_local_llm, analyze_local, _validate_local_result, LocalLLMError

class TestProbeLocalLLM(unittest.TestCase):

    @patch('urllib.request.urlopen')
    def test_both_servers_available(self, mock_urlopen):
        # Setup mock to return success for 2744
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({"model": "apple-foundationmodels"}).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        result = probe_local_llm()
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["port"], 2744)

    @patch('urllib.request.urlopen')
    def test_only_2745_available(self, mock_urlopen):
        # Side effect: first call (2744) fails, second call (2745) succeeds
        def urlopen_side_effect(url, timeout=1.0):
            if "2744" in url:
                raise urllib.error.URLError("Connection refused")
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.read.return_value = json.dumps({"model": "mlx-qwen2.5"}).encode('utf-8')
            mock_response.__enter__.return_value = mock_response
            return mock_response
            
        mock_urlopen.side_effect = urlopen_side_effect
        
        result = probe_local_llm()
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["port"], 2745)

    @patch('urllib.request.urlopen')
    def test_neither_available(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        
        result = probe_local_llm()
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["port"], 0)


class TestAnalyzeLocal(unittest.TestCase):

    @patch('urllib.request.urlopen')
    def test_successful_analysis(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": "{\"prompt_quality\": 0.9, \"summary\": \"Tested local analysis.\"}"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50}
        }).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        # analyze_local(chunk, port)
        res = analyze_local("Test prompt", 2744)
        self.assertIn("result", res)
        self.assertEqual(res["result"]["prompt_quality"], 0.9)
        self.assertEqual(res["result"]["summary"], "Tested local analysis.")

    @patch('urllib.request.urlopen')
    def test_server_error(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.read.return_value = b'Internal Server Error'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        with self.assertRaises(LocalLLMError):
            analyze_local("Test prompt", 2744)

    @patch('urllib.request.urlopen')
    def test_timeout(self, mock_urlopen):
        # We also need to catch timeout error which is an instance of URLError
        mock_urlopen.side_effect = urllib.error.URLError("Timeout")
        
        with self.assertRaises(LocalLLMError):
            analyze_local("Test prompt", 2744)


class TestValidateLocalResult(unittest.TestCase):

    def test_prompt_quality_clamping(self):
        # 1.5 -> 1.0
        res1 = _validate_local_result({"prompt_quality": 1.5})
        self.assertEqual(res1["prompt_quality"], 1.0)
        
        # -0.3 -> 0.0
        res2 = _validate_local_result({"prompt_quality": -0.3})
        self.assertEqual(res2["prompt_quality"], 0.0)
        
        # 0.7 -> 0.7
        res3 = _validate_local_result({"prompt_quality": 0.7})
        self.assertEqual(res3["prompt_quality"], 0.7)

    def test_missing_fields_filled_with_defaults(self):
        res = _validate_local_result({})
        self.assertEqual(res["prompt_quality"], 0.0)
        self.assertEqual(res["themes"], [])
        self.assertEqual(res["bugs"], [])
        self.assertEqual(res["optimizations"], [])
        self.assertEqual(res["summary"], "")
        self.assertEqual(res["session_type"], "")
        self.assertEqual(res["model_used"], "local/unknown")

    def test_invalid_severity_defaults_to_medium(self):
        # For themes
        res_theme = _validate_local_result({
            "themes": [{"severity": "critical"}]
        })
        self.assertEqual(res_theme["themes"][0]["severity"], "medium")
        
        # For optimizations
        res_opt = _validate_local_result({
            "optimizations": [{"impact": "unprecedented"}]
        })
        self.assertEqual(res_opt["optimizations"][0]["impact"], "medium")

if __name__ == '__main__':
    unittest.main()
