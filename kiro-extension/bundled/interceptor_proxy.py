#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/kernora/blob/main/LICENSE
"""
Local LLM Proxy Interceptor — Phase 2 feature.
Runs on localhost:2743 only (never exposed to the network).
IDEs/agents set their API base URL to http://localhost:2743/v1

Intercepts /v1/chat/completions, validates scope, injects skills,
then forwards approved requests to the real upstream LLM via LiteLLM.

Scope classification uses a real LLM call (Haiku) rather than naive
keyword matching, keeping false-positive rate low.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Localhost only — never bind to 0.0.0.0
HOST = "127.0.0.1"
PORT = 2743

# Upstream target from config (user's own key stays in their env)
UPSTREAM_MODEL = os.environ.get("KERNORA_PROXY_MODEL", "anthropic/claude-haiku-4-5-20251001")

# Prompts that are vague OR monolithic get intercepted
# We use a small LLM call to classify rather than word-count heuristics
CLASSIFIER_PROMPT = """You are a scope classifier for an AI coding agent safety system.

Given a developer's prompt, classify it as one of:
- APPROVED: clear, specific, well-scoped
- VAGUE: too ambiguous to execute without risk (fewer than 2 concrete details)
- MONOLITHIC: attempts to change too many things at once (>5 files or systems implied)

Return ONLY valid JSON: {{"verdict": "APPROVED"|"VAGUE"|"MONOLITHIC", "reason": "one sentence"}}

Prompt to classify:
{prompt}"""


def classify_prompt(prompt: str) -> dict:
    """Use a cheap LLM call to classify scope. Falls back to APPROVED on error."""
    try:
        from litellm import completion
        resp = completion(
            model=UPSTREAM_MODEL,
            messages=[{"role": "user", "content": CLASSIFIER_PROMPT.format(prompt=prompt[:1000])}],
            response_format={"type": "json_object"},
            timeout=10,
            max_tokens=100,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        # On any error (no key, network, etc.) — pass through to avoid blocking the user
        return {"verdict": "APPROVED", "reason": "classifier unavailable — passed through"}


def load_org_skills() -> str:
    """Pull the top 5 distilled skills from the local insights DB."""
    try:
        import sqlite3
        db_path = Path.home() / ".kernora" / "echo.db"
        if not db_path.exists():
            return ""
        conn = sqlite3.connect(db_path, timeout=5)
        rows = conn.execute(
            "SELECT skill_opportunity FROM insights "
            "WHERE skill_opportunity IS NOT NULL AND skill_opportunity != '' "
            "ORDER BY id DESC LIMIT 5"
        ).fetchall()
        conn.close()
        return "\n".join(f"- {r[0]}" for r in rows)
    except Exception:
        return ""


class KernoraProxy(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress default access log; we do our own
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "http://localhost")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            payload = json.loads(post_data.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        messages = payload.get("messages", [])
        last_prompt = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            ""
        )

        # Classify scope
        result = classify_prompt(last_prompt)
        verdict = result.get("verdict", "APPROVED")
        reason = result.get("reason", "")

        if verdict == "MONOLITHIC":
            self._send_synthetic(
                "**[Kernora — Scope Alert]**\n\n"
                f"⚠️ {reason}\n\n"
                "This prompt implies a broad change that typically increases hallucination risk. "
                "**Recommended:** Break this into 2–3 focused batches. "
                "Start with the smallest independently testable piece. "
                "Type the first batch when ready."
            )
            print(f"[proxy] BLOCKED monolithic prompt ({len(last_prompt.split())} words)")
            return

        if verdict == "VAGUE":
            skills = load_org_skills()
            skills_block = (
                f"\n\n**Your team's methodology:**\n{skills}"
                if skills else ""
            )
            self._send_synthetic(
                "**[Kernora — Clarity Check]**\n\n"
                f"⚠️ {reason}\n\n"
                f"Add more context: which file, what behavior, what outcome?{skills_block}"
            )
            print(f"[proxy] HELD vague prompt for clarification")
            return

        # Inject team skills into the system message before forwarding
        skills = load_org_skills()
        if skills:
            system_injection = (
                f"# Team Engineering Methodology (Kernora)\n"
                f"Apply these patterns where relevant:\n{skills}"
            )
            # Prepend to existing system message, or insert one
            has_system = any(m.get("role") == "system" for m in messages)
            if has_system:
                for m in messages:
                    if m.get("role") == "system":
                        m["content"] = system_injection + "\n\n" + m["content"]
                        break
            else:
                messages.insert(0, {"role": "system", "content": system_injection})
            payload["messages"] = messages

        # Forward to upstream
        try:
            from litellm import completion
            model = payload.pop("model", UPSTREAM_MODEL)
            resp = completion(model=model, **payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(resp.model_dump_json().encode())
            print(f"[proxy] forwarded → {model}")
        except Exception as e:
            self._send_synthetic(f"[Kernora proxy error] {e}")

    def _send_synthetic(self, text: str):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.end_headers()
        resp = {
            "id": "kernora-proxy",
            "object": "chat.completion",
            "created": 0,
            "model": "kernora-interceptor",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        }
        self.wfile.write(json.dumps(resp).encode())


def run_server():
    server = HTTPServer((HOST, PORT), KernoraProxy)
    print(f"[kernora] proxy interceptor on http://{HOST}:{PORT} (localhost only)")
    print(f"[kernora] upstream model: {UPSTREAM_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
