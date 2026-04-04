#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
from __future__ import annotations  # PEP 563: str|None works on Python 3.9+

"""
Dashboard server — Flask + HTMX.
Usage: python dashboard.py
Opens: http://localhost:2742

Design: server-side HTML, HTMX for partial updates.
No npm. No build step. No node_modules.
Reads from: ~/.kernora/echo.db (SQLite)
"""
import html
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

from flask import Flask, request, redirect, jsonify

# tomllib compat
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            tomllib = None  # type: ignore

try:
    import telemetry as _telemetry
except ImportError:
    _telemetry = None  # type: ignore

app = Flask(__name__)
DB  = Path.home() / ".kernora" / "echo.db"
CFG = Path.home() / ".kernora" / "config.toml"

# ── Live session tracking (in-memory, resets on restart) ────────────────────
_live_session = {
    "active": False,
    "session_id": "",
    "project": "",
    "started_at": "",
    "tool_count": 0,
    "error_count": 0,
    "files_touched": [],       # list of unique file paths
    "tools_used": {},          # tool_name -> count
    "recent_errors": [],       # last 3 error snippets
    "last_event_at": "",
    "last_mini_analysis": 0,   # tool_count at last mini-analysis
}
_live_lock = threading.Lock()

CSS = """
<style>
:root{
  --teal:#1D9E75; --blue:#378ADD; --amber:#BA7517; --red:#D85A30; --gray:#888780;
  --success:var(--teal); --warning:var(--amber); --danger:var(--red); --info:var(--blue);
  --bg-dark: #07090d; --card-bg: rgba(20, 25, 35, 0.5); --border-subtle: rgba(255,255,255,0.05);
}
*{box-sizing:border-box}
body {
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  background: radial-gradient(circle at 50% 0%, #111826 0%, var(--bg-dark) 100%);
  background-attachment: fixed;
  color: #dce8f5; margin: 0; padding: 0; line-height: 1.5;
}
code { font-family: ui-monospace, monospace; }
.kpi-val { font-family: ui-monospace, monospace; }

@keyframes fadeIn { from {opacity: 0; transform: translateY(10px);} to {opacity: 1; transform: translateY(0);} }
.content { padding: 1.5rem 2rem; max-width: 1400px; margin: 0 auto; animation: fadeIn 0.5s cubic-bezier(0.2, 0.8, 0.2, 1) forwards; }

.topbar {
  display: flex; align-items: center; justify-content: space-between; padding: .75rem 2rem;
  background: rgba(11, 15, 26, 0.7); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border-subtle); position: sticky; top: 0; z-index: 100;
}
.logo { font-size: 1.1rem; font-weight: 700; color: #fff; letter-spacing: -0.02em; }
.logo span { color: #00bcd4; font-weight: 500; }
.badge-byok {
  background: rgba(7, 21, 15, 0.5); border: 1px solid rgba(29, 158, 117, 0.3); color: var(--teal);
  font-size: .65rem; font-weight: 600; padding: 2px 8px; border-radius: 20px; margin-left: 10px; text-transform: uppercase;
}
nav {
  display: flex; gap: 4px; padding: .5rem 2rem; border-bottom: 1px solid var(--border-subtle);
  background: rgba(7, 9, 13, 0.6); backdrop-filter: blur(10px);
}
nav a {
  color: #8ba4be; font-size: .8rem; font-weight: 500; padding: .5rem 1rem; text-decoration: none;
  border-radius: 6px; transition: all 0.2s ease;
}
nav a:hover { color: #fff; background: rgba(255,255,255,0.03); }
nav a.active { color: #fff; background: rgba(29, 158, 117, 0.15); box-shadow: inset 0 0 0 1px rgba(29,158,117,0.2); }

.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
.kpi {
  background: var(--card-bg); backdrop-filter: blur(12px); border: 1px solid var(--border-subtle);
  border-radius: 12px; padding: 1.25rem; transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.kpi:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.4); border-color: rgba(255,255,255,0.1); }
.kpi-label { font-size: .7rem; color: #8ba4be; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; margin-bottom: .5rem; }
.kpi-value { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.02em; }

table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: .8rem; }
th { text-align: left; font-size: .7rem; color: #8ba4be; font-weight: 600; padding: .75rem 1rem; border-bottom: 1px solid var(--border-subtle); text-transform: uppercase; letter-spacing: 0.05em; }
td { padding: .75rem 1rem; border-bottom: 1px solid rgba(255,255,255,0.02); vertical-align: middle; transition: background 0.2s; }
tr:hover td { background: rgba(255,255,255,0.015); }

.bug-high { color: var(--red); } .bug-med { color: var(--amber); } .bug-low { color: var(--teal); }
.card {
  background: var(--card-bg); backdrop-filter: blur(12px); border: 1px solid var(--border-subtle);
  border-radius: 12px; padding: 1.25rem; margin-bottom: 1rem; font-size: .85rem;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1); transition: transform 0.2s ease, border-color 0.2s ease;
}
.card:hover { border-color: rgba(255,255,255,0.1); }
.rule {
  background: rgba(7, 21, 16, 0.4); border-left: 2px solid var(--teal); padding: .75rem 1rem;
  margin: .5rem 0; font-size: .8rem; border-radius: 0 6px 6px 0;
}
.setting-row { display: flex; align-items: center; justify-content: space-between; padding: .75rem 0; border-bottom: 1px solid var(--border-subtle); font-size: .85rem; }
.privacy { background: rgba(7, 21, 16, 0.4); border: 1px solid rgba(29, 158, 117, 0.3); border-radius: 8px; padding: 1rem; margin-top: 1rem; font-size: .8rem; color: var(--teal); }

select, input[type=text] {
  background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.1); color: #fff;
  border-radius: 6px; padding: 6px 12px; font-family: inherit; font-size: .85rem; transition: border-color 0.2s;
}
select:focus, input[type=text]:focus { outline: none; border-color: var(--blue); }

.btn { display: inline-block; background: var(--teal); color: #fff; padding: 8px 16px; border-radius: 6px; font-size: .8rem; font-weight: 500; text-decoration: none; border: none; cursor: pointer; transition: background 0.2s; }
.btn:hover { background: #168a65; }
.btn-secondary {
  display: inline-block; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1);
  color: #dce8f5; padding: 6px 14px; border-radius: 6px; font-size: .8rem; font-weight: 500; text-decoration: none; cursor: pointer; transition: all 0.2s;
}
.btn-secondary:hover { border-color: var(--teal); background: rgba(29, 158, 117, 0.1); color: #fff; }

h3 { margin: 0 0 .75rem; font-size: .9rem; color: #fff; font-weight: 600; letter-spacing: -0.01em; }

/* Leverage Visuals */
.leverage-display { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 2rem 1rem; position: relative; }
.leverage-number { font-size: 80px; font-weight: 800; color: var(--teal); font-family: ui-monospace, monospace; line-height: 1; text-shadow: 0 0 40px rgba(29,158,117,0.3); }
.leverage-label { font-size: 20px; color: #fff; font-weight: 600; margin-top: 12px; }
.leverage-sub { font-size: 13px; color: #8ba4be; margin-top: 6px; }

footer { text-align: center; padding: 32px 0 48px; border-top: 1px solid var(--border-subtle); margin-top: 64px; font-size: 13px; color: #6a8aaa; }
footer a { color: #8ba4be; text-decoration: none; transition: color 0.2s; }
footer a:hover { color: #fff; }

.status-pill {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.05); border-radius: 20px; font-size: 0.7rem; color: #a1b0c0; text-decoration: none;
  transition: all 0.2s ease; cursor: pointer;
}
.status-pill:hover { background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.2); color: #fff; }

/* Ghosted UI */
.ghosted { opacity: 0.3; filter: blur(2px) grayscale(50%); pointer-events: none; user-select: none; }
.empty-cta-overlay {
  position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  background: rgba(14, 19, 24, 0.85); backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.1);
  padding: 2rem; border-radius: 12px; text-align: center; box-shadow: 0 16px 40px rgba(0,0,0,0.5);
  width: 80%; max-width: 400px; z-index: 10;
}
</style>
"""

HTMX = '<script src="https://cdnjs.cloudflare.com/ajax/libs/htmx/1.9.12/htmx.min.js"></script>'

# ── Persona configuration (engineering, product, ...) ────────────────────────
PERSONA_CONFIG = {
    "engineering": {
        "kpi_labels": ["Sessions", "Patterns", "Bugs", "Prompt Quality"],
        "language": {"bugs": "Bugs", "learnings": "Knowledge", "sessions": "Activity"},
        "sort_key": "effectiveness",
    },
    "product": {
        "kpi_labels": ["Decisions", "Outcomes", "Velocity", "Knowledge"],
        "language": {"bugs": "Issues", "learnings": "Knowledge", "sessions": "Activity"},
        "sort_key": "recency",
    },
}


def get_persona() -> str:
    """Read persona from config.toml, default to engineering."""
    if CFG.exists() and tomllib is not None:
        try:
            with open(CFG, "rb") as f:
                cfg = tomllib.load(f)
            return cfg.get("dashboard", {}).get("persona", "engineering")
        except Exception:
            pass
    return "engineering"


def get_conn():
    c = sqlite3.connect(DB, check_same_thread=False, timeout=15.0)
    c.row_factory = sqlite3.Row
    try:
        c.execute("SELECT 1 FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        import db
        db.init_db()
    return c


def load_cfg() -> dict:
    if CFG.exists() and tomllib is not None:
        with open(CFG, "rb") as f:
            return tomllib.load(f)
    return {"model": {"provider": "anthropic"}, "mode": {"type": "byok"}}


# ── LLM reachability probe ────────────────────────────────────────────────────
_llm_status_cache: dict = {"ok": None, "provider": "", "model": "", "reason": "", "ts": 0}
_llm_status_lock = threading.Lock()
_ide_heartbeat_cache: dict = {"ts": 0, "ok": False, "model": "", "reason": "Awaiting IDE connection"}
_ide_heartbeat_lock = threading.Lock()
_LLM_CACHE_TTL = 30  # seconds


def _http_get(url: str, headers: dict, timeout: int = 5) -> int:
    """Return HTTP status code, or 0 on connection error."""
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _is_ide_provided_llm() -> bool:
    """Return True when the host IDE provides its own LLM (e.g. Kiro, Cursor, VS Code)."""
    ide = os.environ.get("KERNORA_IDE", "").lower()
    if not ide and os.environ.get("ANTIGRAVITY_AGENT"):
        ide = "antigravity"
    return ide in ("kiro", "cursor", "vscode", "antigravity")



def _get_ide_name(default="IDE") -> str:
    ide = os.environ.get("KERNORA_IDE", "").lower()
    if not ide and os.environ.get("ANTIGRAVITY_AGENT"):
        ide = "antigravity"
    if "antigravity" in ide:
        return "Antigravity"
    if ide == "vscode":
        return "VS Code"
    return ide.capitalize() if ide else default

def probe_llm() -> dict:
    """
    Lightweight LLM reachability check. Returns:
      {"ok": bool, "provider": str, "model": str, "reason": str}
    Uses cached result within _LLM_CACHE_TTL seconds.

    When running inside Kiro, the IDE provides its own LLM — skip BYOK probing.
    """
    # IDEs like Kiro, Cursor, and VS Code provide their own LLM, but they must
    # actively heartbeat via /api/ide/heartbeat to prove they are connected and responsive.
    ide = os.environ.get("KERNORA_IDE", "").lower()
    if not ide and os.environ.get("ANTIGRAVITY_AGENT"):
        ide = "antigravity"
    if ide in ("kiro", "cursor", "vscode", "antigravity"):
        with _ide_heartbeat_lock:
            ts = _ide_heartbeat_cache["ts"]
            ok = _ide_heartbeat_cache["ok"]
            model = _ide_heartbeat_cache["model"]
            reason = _ide_heartbeat_cache["reason"]

        ide_name = "Antigravity" if "antigravity" in ide else ("VS Code" if ide == "vscode" else ide.capitalize())
        mod_fallback = "Gemini 3.1 Pro (High)" if "antigravity" in ide else "provided by IDE"
        
        # If no heartbeat seen in 60s, it's disconnected or not responding
        if time.time() - ts > 60:
            return {"ok": False, "provider": "ide", "model": "unknown", 
                    "reason": f"{ide_name} extension disconnected (no heartbeat)"}
        
        # Fallback unknown model to Gemini
        actual_model = model
        if not actual_model or actual_model.lower() == "unknown":
            actual_model = mod_fallback

        return {"ok": ok, "provider": "ide", "model": actual_model,
                "reason": reason}

    with _llm_status_lock:
        if time.time() - _llm_status_cache["ts"] < _LLM_CACHE_TTL and _llm_status_cache["ok"] is not None:
            return dict(_llm_status_cache)

    cfg = load_cfg()
    provider_pref = cfg.get("model", {}).get("provider", "auto")
    result = {"ok": False, "provider": provider_pref, "model": "", "reason": "No providers available"}

    def check_anthropic():
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key: return False, "anthropic", "", "ANTHROPIC_API_KEY not set"
        st = _http_get("https://api.anthropic.com/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"})
        if st == 200: return True, "anthropic", "claude-haiku-4-5-20251001", "reachable"
        return False, "anthropic", "", f"HTTP {st}"

    def check_bedrock():
        try:
            import boto3  # type: ignore
            boto3.session.Session().get_credentials()
            return True, "bedrock", "amazon.nova-lite-v1:0", "AWS credentials found"
        except Exception as e:
            return False, "bedrock", "", f"AWS credentials missing: {e}"

    def check_openai():
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key: return False, "openai", "", "OPENAI_API_KEY not set"
        st = _http_get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
        if st == 200: return True, "openai", "gpt-4o-mini", "reachable"
        return False, "openai", "", f"HTTP {st}"

    def check_google():
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key: return False, "google", "", "GEMINI_API_KEY not set"
        st = _http_get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", {})
        if st == 200: return True, "google", "gemini-2.5-pro", "reachable"
        return False, "google", "", f"HTTP {st}"

    def check_ollama():
        st = _http_get("http://localhost:11434/api/tags", {})
        if st == 200: return True, "ollama", cfg.get("ollama", {}).get("model", "llama3.2:3b"), "Ollama running"
        if st == 0: return False, "ollama", "", "Ollama not running (localhost:11434 unreachable)"
        return False, "ollama", "", f"HTTP {st}"

    def check_grok():
        key = os.environ.get("XAI_API_KEY", "")
        if not key: return False, "grok", "", "XAI_API_KEY not set"
        st = _http_get("https://api.x.ai/v1/models", {"Authorization": f"Bearer {key}"})
        if st == 200: return True, "grok", "grok-beta", "reachable"
        return False, "grok", "", f"HTTP {st}"

    checks = {
        "anthropic": check_anthropic,
        "bedrock": check_bedrock,
        "openai": check_openai,
        "google": check_google,
        "ollama": check_ollama,
        "grok": check_grok,
    }

    try:
        if provider_pref != "auto":
            if provider_pref in checks:
                ok, p, m, r = checks[provider_pref]()
                result = {"ok": ok, "provider": p, "model": m, "reason": r}
            else:
                result = {"ok": False, "provider": provider_pref, "model": "", "reason": f"Unknown provider: {provider_pref}"}
        else:
            # Fallback sequence: Anthropic -> Bedrock -> OpenAI -> Google -> Ollama
            for p in ["anthropic", "bedrock", "openai", "google", "ollama"]:
                ok, prov, mod, reason = checks[p]()
                if ok:
                    result = {"ok": True, "provider": prov, "model": mod, "reason": reason}
                    break
            else:
                result = {"ok": False, "provider": "auto", "model": "", "reason": "No API keys configured or local models running"}

    except Exception as e:
        result = {"ok": False, "provider": provider_pref, "model": "", "reason": f"probe error: {e}"}

    with _llm_status_lock:
        _llm_status_cache.update(result)
        _llm_status_cache["ts"] = time.time()
    return result


def nav(active: str) -> str:
    nav_items = [
        ("Home", "/"),
        ("Activity", "/sessions"),
        ("Issues", "/bugs"),
        ("Knowledge", "/learnings"),
        ("Memory", "/memory"),
        ("Decisions", "/decisions"),
        ("Coach", "/coach"),
        ("Settings", "/settings"),
    ]
    links = nav_items
    items = "".join(
        f'<a href="{url}" hx-get="{url}" hx-target="body" hx-push-url="true" class="{"active" if name == active else ""}">{name}</a>'
        for name, url in links
    )
    return f"<nav>{items}</nav>"


def shell(title: str, content: str, active: str) -> str:
    c = load_cfg()
    mode = c.get("mode", {}).get("type", "byok")
    llm = probe_llm()
    
    # Adjust badge for IDE-provided LLM environments (since Dashboard aggregates data, it operates universally)
    if llm.get("provider") == "ide":
        ide_name = _get_ide_name("IDE")
        if ide_name == "Antigravity":
            badge_text = llm.get("model", "Gemini 3.1 Pro")
            badge = f'<span class="badge-byok" style="border-color:#378ADD;color:#378ADD" title="Server spawned by {ide_name}">{badge_text}</span>'
            logo_text = "◎ kernora<span>.ai</span> "
        else:
            badge = f'<span class="badge-byok" style="border-color:#378ADD;color:#378ADD" title="Server spawned by {ide_name}">{ide_name}</span>'
            logo_text = "&#9678; kernora<span>.ai</span> "
        mode_label = "AI Work Intelligence · Central"
    else:
        badge = '<span class="badge-byok" title="Bring Your Own Key">BYOK</span>' if mode == "byok" else ""
        mode_label = f"AI Work Intelligence · Central"
        logo_text = "&#9678; kernora<span>.ai</span> "
        
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Kernora — {title}</title>
{CSS}{HTMX}</head><body>
<div class="topbar">
  <span class="logo">{logo_text}{badge}</span>
  <span style="font-size:.7rem;color:#8ba4be;display:flex;align-items:center;gap:16px;">
    {mode_label}
    <select style="font-size:.7rem;background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.1);color:#dce8f5;padding:2px 6px;border-radius:4px;">
      <option value="engineering" selected>Persona: Engineering</option>
      <option value="product">Persona: Product</option>
    </select>
  </span>
</div>
{nav(active)}
{_status_bar_html()}
<div class="content">{content}</div>
<footer style="text-align:center;padding:24px 0 32px;border-top:1px solid var(--border);margin-top:48px;">
  <span style="color:var(--muted);font-size:12px;">
    Built with ❤️ by Kernora
    &nbsp;·&nbsp; <a href="mailto:hello@kernora.ai?subject=Nora feedback" style="color:var(--muted);">Send feedback</a>
    &nbsp;·&nbsp; <a href="https://github.com/kernora-ai/kernora/issues/new" target="_blank" style="color:var(--muted);">Request a feature</a>
  </span>
</footer>
</body></html>"""


def time_ago(dt_str: str) -> str:
    """Convert ISO datetime string to human-readable time-ago format."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(dt_str)
        diff = datetime.utcnow() - dt
        if diff.days > 7:
            return dt.strftime("%b %d")
        if diff.days >= 1:
            return f"{diff.days}d ago"
        h = diff.seconds // 3600
        if h >= 1:
            return f"{h}h ago"
        m = diff.seconds // 60
        return f"{m}m ago" if m >= 1 else "just now"
    except Exception:
        return dt_str or ""


@app.route("/welcome")
def welcome():
    """Welcome page — OOBE onboarding flow for fresh installs."""
    content = """
<div style="max-width:560px;margin:0 auto;padding:8px 0 40px;">
  <div style="height:4px;background:var(--teal);margin:-24px -24px 40px;border-radius:4px 4px 0 0;"></div>

  <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
    <span style="font-size:28px;font-weight:800;color:var(--teal);">Nora</span>
    <span style="font-size:13px;color:var(--muted);padding-top:4px;">by Kernora</span>
  </div>
  <p style="font-size:18px;font-weight:600;color:var(--fg);margin-bottom:32px;">
    Your AI sessions are now being tracked.
  </p>

  <div style="border-top:1px solid var(--border);padding-top:28px;margin-bottom:28px;">
    <p style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:20px;">
      Three steps to unlock Nora's full value
    </p>

    <div style="display:flex;flex-direction:column;gap:20px;">
      <div style="display:flex;gap:16px;align-items:flex-start;">
        <div style="min-width:32px;height:32px;border-radius:50%;background:var(--teal);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;color:white;">1</div>
        <div>
          <p style="font-weight:600;color:var(--fg);margin-bottom:4px;">Run <code style="background:var(--surface);padding:2px 6px;border-radius:4px;font-size:13px;">nora onboard</code> in your AI chat</p>
          <p style="font-size:13px;color:var(--muted);">Nora scans your project and gives itself context about your codebase. Takes 10 seconds.</p>
        </div>
      </div>

      <div style="display:flex;gap:16px;align-items:flex-start;">
        <div style="min-width:32px;height:32px;border-radius:50%;background:var(--teal);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;color:white;">2</div>
        <div>
          <p style="font-weight:600;color:var(--fg);margin-bottom:4px;">Start a session</p>
          <p style="font-size:13px;color:var(--muted);">Ask your AI assistant anything. Nora hooks in automatically — nothing to configure.</p>
        </div>
      </div>

      <div style="display:flex;gap:16px;align-items:flex-start;">
        <div style="min-width:32px;height:32px;border-radius:50%;background:var(--teal);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:14px;color:white;">3</div>
        <div>
          <p style="font-weight:600;color:var(--fg);margin-bottom:4px;">Come back after your first session</p>
          <p style="font-size:13px;color:var(--muted);">Nora will have your AI leverage score, captured patterns, and your first coaching tip.</p>
        </div>
      </div>
    </div>
  </div>

  <div style="border-top:1px solid var(--border);padding-top:24px;display:flex;gap:12px;flex-wrap:wrap;">
    <a href="/settings" class="btn" style="text-decoration:none;">Configure API key →</a>
    <a href="/" class="btn-secondary" style="text-decoration:none;">Go to Dashboard</a>
  </div>
</div>
"""
    return shell("Welcome", content, "Welcome")


@app.route("/")
def index():
    """Home page — value-first KPIs and compounding metrics."""
    db = get_conn()
    if not db:
        empty = """
<div style="text-align:center;padding:60px 24px;">
  <div style="font-size:40px;margin-bottom:16px;">🧠</div>
  <h2 style="font-size:18px;font-weight:700;color:var(--fg);margin-bottom:8px;">No sessions yet</h2>
  <p style="color:var(--muted);font-size:14px;max-width:360px;margin:0 auto 24px;">
    Start a session in your AI assistant. Nora is already listening — your first session will appear here automatically.
  </p>
  <a href="/welcome" class="btn" style="text-decoration:none;">View setup guide →</a>
</div>"""
        return shell("Home", empty, "Home")

    # TASK 6.1 — Value-first KPIs
    try:
        session_count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        pattern_count = db.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        bug_fix_count = db.execute("SELECT COUNT(*) FROM reported_bugs WHERE fix_code != ''").fetchone()[0]
        injections = db.execute("SELECT COUNT(*) FROM nora_metrics WHERE event_type = 'impression' AND created_at > datetime('now', '-7 days')").fetchone()[0]

        quality_row = db.execute("SELECT AVG(prompt_quality) as avg_q FROM insights WHERE prompt_quality > 0").fetchone()
        avg_quality = quality_row[0] or 0.0
        insights_count = db.execute("SELECT COUNT(*) FROM insights").fetchone()[0]

        # AI Leverage
        if insights_count < 3:
            leverage = "—"
            leverage_label = "—"
            leverage_color = "#6a8aaa"
        else:
            leverage = round(1.0 + (avg_quality * 4.0), 1)
            if leverage >= 4.0:
                leverage_label = "Excellent"
                leverage_color = "#1D9E75"
            elif leverage >= 3.0:
                leverage_label = "Strong"
                leverage_color = "#378ADD"
            elif leverage >= 2.0:
                leverage_label = "Developing"
                leverage_color = "#BA7517"
            else:
                leverage_label = "Early Stage"
                leverage_color = "#D85A30"
    except Exception:
        session_count = pattern_count = bug_fix_count = 0
        avg_quality = 0.0
        leverage = "—"
        leverage_label = "—"
        leverage_color = "#6a8aaa"

    kpis = f"""
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;">
      <div class="kpi-row" style="margin-bottom:0;flex:1;">
        <div class="kpi" style="background: linear-gradient(135deg, rgba(255,255,255,0.02) 0%, rgba(20,25,35,0.5) 100%); cursor:pointer" hx-get="/sessions" hx-target="body" hx-push-url="true">
          <div class="kpi-label">Sessions</div>
          <div class="kpi-value">{session_count:,}</div>
        </div>
        <div class="kpi" style="background: linear-gradient(135deg, rgba(29, 158, 117, 0.08) 0%, rgba(20,25,35,0.5) 100%); border-color: rgba(29, 158, 117, 0.2); cursor:pointer" hx-get="/learnings" hx-target="body" hx-push-url="true">
          <div class="kpi-label">Patterns</div>
          <div class="kpi-value" style="color:var(--teal)">{pattern_count:,}</div>
        </div>
        <div class="kpi" style="background: linear-gradient(135deg, rgba(216, 90, 48, 0.08) 0%, rgba(20,25,35,0.5) 100%); border-color: rgba(216, 90, 48, 0.2); cursor:pointer" hx-get="/bugs" hx-target="body" hx-push-url="true">
          <div class="kpi-label">Bugs Fixed</div>
          <div class="kpi-value" style="color:var(--red)">{bug_fix_count:,}</div>
        </div>
        <div class="kpi" title="Context injected passively in last 7 days" style="background: linear-gradient(135deg, rgba(186, 117, 23, 0.08) 0%, rgba(20,25,35,0.5) 100%); border-color: rgba(186, 117, 23, 0.2); cursor:pointer" hx-get="/memory" hx-target="body" hx-push-url="true">
          <div class="kpi-label">Injections</div>
          <div class="kpi-value" style="color:var(--amber)">{injections:,}</div>
        </div>
        <div class="kpi" title="Measures 10x capability over standard AI usage" style="background: linear-gradient(135deg, rgba(55, 138, 221, 0.08) 0%, rgba(20,25,35,0.5) 100%); border-color: rgba(55, 138, 221, 0.2); cursor:pointer" hx-get="/coach" hx-target="body" hx-push-url="true">
          <div class="kpi-label">AI Leverage</div>
          <div class="kpi-value" style="color:{leverage_color}">{leverage + 'x' if leverage != '—' else leverage}</div>
        </div>
      </div>
      <div style="padding-left:1.25rem;">
        <a href="/report/export" target="_blank" class="btn-secondary">Export Report →</a>
      </div>
    </div>
    """

    # TASK 6.2 — Intelligence Compounding
    try:
        weekly_patterns = db.execute(
            "SELECT COUNT(*) FROM patterns WHERE created_at > datetime('now', '-7 days')"
        ).fetchone()[0]
    except Exception:
        weekly_patterns = 0

    monthly_patterns = pattern_count / 4.3 if pattern_count > 0 else 0  # rough weekly average
    weekly_rate = weekly_patterns if weekly_patterns > 0 else 1
    projected_6mo = int(weekly_rate * 26)

    compounding = f"""
    <div class="card" style="border-left:3px solid var(--info); margin-bottom:1.25rem;">
      <h3>Intelligence Compounding</h3>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-bottom:1rem;font-size:.8rem;">
        <div>
          <div style="color:#6a8aaa;font-size:.65rem;text-transform:uppercase;margin-bottom:.25rem;">Patterns/Week</div>
          <div style="font-size:1.25rem;color:var(--teal);font-weight:500">{weekly_rate:.1f}</div>
        </div>
        <div>
          <div style="color:#6a8aaa;font-size:.65rem;text-transform:uppercase;margin-bottom:.25rem;">6-Mo Projection</div>
          <div style="font-size:1.25rem;color:var(--blue);font-weight:500">{projected_6mo:,}</div>
        </div>
        <div>
          <div style="color:#6a8aaa;font-size:.65rem;text-transform:uppercase;margin-bottom:.25rem;">Current Stock</div>
          <div style="font-size:1.25rem;color:var(--amber);font-weight:500">{pattern_count:,}</div>
        </div>
      </div>
    </div>
    """

    # TASK 6.3 — Two-column layout (Quick Wins left, Recent Activity right)
    try:
        top_patterns = db.execute(
            "SELECT id, name, effectiveness FROM patterns ORDER BY effectiveness DESC LIMIT 5"
        ).fetchall()
    except Exception:
        top_patterns = []

    quick_wins = "<div class='card'><h3>Quick Wins</h3>"
    if top_patterns:
        for p in top_patterns:
            eff = p[2] or 0
            eff_color = "#1D9E75" if eff > 0.8 else "#BA7517" if eff > 0.5 else "#D85A30"
            name = p[1] or "Unnamed Pattern"
            quick_wins += f"<div style='padding:.5rem 0;border-bottom:1px solid #111820;'>"
            quick_wins += f"<span style='color:#dce8f5;font-size:.8rem'>{html.escape(name[:50])}</span> "
            quick_wins += f"<span style='color:{eff_color};font-size:.7rem'>⭐ {eff:.2f}</span>"
            quick_wins += f"</div>"
    else:
        quick_wins += "<p style='color:#2e4460;font-size:.8rem'>No patterns yet.</p>"
    quick_wins += "</div>"

    try:
        recent_sessions = db.execute(
            "SELECT s.id, s.project, s.ended_at, "
            "(SELECT COUNT(*) FROM reported_bugs r WHERE r.session_id = s.id) as bugs "
            "FROM sessions s ORDER BY s.ended_at DESC LIMIT 5"
        ).fetchall()
    except Exception:
        recent_sessions = []

    recent_activity = "<div class='card'><h3>Recent Activity</h3>"
    if recent_sessions:
        for s in recent_sessions:
            ago = time_ago(s[2] or "")
            proj = html.escape(Path(s[1] or "?").name)
            bug_count = s[3] or 0
            if bug_count == 0:
                dot = '<span style="color:var(--teal);font-size:.8rem" title="0 bugs">●</span>'
            elif bug_count <= 2:
                dot = '<span style="color:var(--amber);font-size:.8rem" title="1-2 bugs">●</span>'
            else:
                dot = '<span style="color:var(--red);font-size:.8rem" title="3+ bugs">●</span>'
                
            recent_activity += f"<div style='padding:.5rem 0;border-bottom:1px solid #111820;display:flex;align-items:center;gap:8px;'>"
            recent_activity += f"{dot}"
            recent_activity += f"<span style='color:#dce8f5;font-size:.8rem'>{proj}</span> "
            recent_activity += f"<span style='color:#6a8aaa;font-size:.7rem'>{ago}</span>"
            recent_activity += f"</div>"
    else:
        recent_activity += "<p style='color:#2e4460;font-size:.8rem'>No sessions yet.</p>"
    recent_activity += "</div>"

    two_col = f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.25rem;margin-bottom:1.25rem;">
      {quick_wins}
      {recent_activity}
    </div>
    """

    db.close()
    return shell("Home", kpis + compounding + two_col, "Home")


@app.route("/sessions")
def sessions():
    """Activity page — list of sessions with time-ago formatting and outcome dots."""
    db = get_conn()
    if not db:
        empty = """
<div style="text-align:center;padding:60px 24px;">
  <div style="font-size:40px;margin-bottom:16px;">⚡</div>
  <h2 style="font-size:18px;font-weight:700;color:var(--fg);margin-bottom:8px;">No sessions recorded yet</h2>
  <p style="color:var(--muted);font-size:14px;max-width:360px;margin:0 auto;">
    Each AI conversation you have gets captured here. Complete your first session to see it.
  </p>
</div>"""
        return shell("Activity", empty, "Activity")
    # Query only columns that exist in the schema (db.py).
    rows = db.execute(
        "SELECT s.id, s.project, s.started_at, s.ended_at, s.tokens_in, s.tokens_out, "
        "s.model, s.analyzed, i.summary, "
        "(SELECT COUNT(*) FROM reported_bugs r WHERE r.session_id = s.id) as bugs "
        "FROM sessions s LEFT JOIN insights i ON i.session_id=s.id "
        "ORDER BY s.inserted_at DESC LIMIT 50"
    ).fetchall()
    db.close()

    def _source_badge(model, analyzed):
        """Badge based on session source (model column) + analysis state."""
        if model == "git-scan":
            return '<span style="font-size:.6rem;padding:1px 6px;border-radius:10px;border:1px solid #BA7517;color:#BA7517">git scan</span>'
        if model == "kiro-cli":
            return '<span style="font-size:.6rem;padding:1px 6px;border-radius:10px;border:1px solid #9B59B6;color:#9B59B6">kiro-cli</span>'
        if analyzed:
            return '<span style="font-size:.6rem;padding:1px 6px;border-radius:10px;border:1px solid #1D9E75;color:#1D9E75">analyzed</span>'
        return '<span style="font-size:.6rem;padding:1px 6px;border-radius:10px;border:1px solid #2e4460;color:#6a8aaa">pending</span>'

    def _outcome_dot(r):
        """Return outcome dot: green=0 bugs, amber=1-2 bugs, red=3+ bugs."""
        bug_count = r['bugs'] or 0
        if bug_count == 0:
            return '<span style="color:var(--teal);font-weight:bold" title="0 bugs">●</span>'
        elif bug_count <= 2:
            return '<span style="color:var(--amber);font-weight:bold" title="1-2 bugs">●</span>'
        else:
            return '<span style="color:var(--red);font-weight:bold" title="3+ bugs">●</span>'

    trs_parts = []
    for r in rows:
        sid = str(r['id'])
        proj = html.escape(Path(r['project'] or '?').name)
        # TASK 8.2 — Use time_ago helper instead of raw datetime
        ended = time_ago(r['ended_at'] or r['started_at'] or "")
        tok = (r['tokens_in'] or 0) + (r['tokens_out'] or 0)
        tok_str = f"{tok:,}" if tok > 0 else '<span style="color:#2e4460">—</span>'
        badge = _source_badge(r['model'], r['analyzed'])
        outcome = _outcome_dot(r)
        summ = html.escape(str(r['summary'] or '')[:80])
        if not summ and r['model'] == 'git-scan':
            summ = '<span style="color:#2e4460">from git history</span>'
        elif not summ:
            summ = '<span style="color:#2e4460">awaiting analysis</span>'
        trs_parts.append(
            f"<tr><td>{outcome}</td><td><a href='/sessions/{sid}' style='color:#378ADD;text-decoration:none'>{html.escape(sid[:8])}</a></td>"
            f"<td>{proj}</td><td>{ended}</td><td>{tok_str}</td><td>{badge}</td>"
            f"<td style='color:#6a8aaa;font-size:.7rem'>{summ}</td></tr>"
        )
    trs = "".join(trs_parts)
    content = f"""<table>
    <tr><th></th><th>ID</th><th>Project</th><th>When</th><th>Tokens</th><th>Source</th><th>Summary</th></tr>
    {trs or "<tr><td colspan='7' style='color:#2e4460'>No sessions yet. Run <code>nora scan &lt;path&gt;</code> to seed from git history.</td></tr>"}
    </table>"""
    return shell("Activity", content, "Activity")


@app.route("/sessions/<session_id>")
def session_detail(session_id):
    db = get_conn()
    if not db:
        empty = """
<div style="text-align:center;padding:60px 24px;">
  <div style="font-size:40px;margin-bottom:16px;">⚡</div>
  <h2 style="font-size:18px;font-weight:700;color:var(--fg);margin-bottom:8px;">No sessions recorded yet</h2>
  <p style="color:var(--muted);font-size:14px;max-width:360px;margin:0 auto;">
    Each AI conversation you have gets captured here. Complete your first session to see it.
  </p>
</div>"""
        return shell("Session", empty, "Sessions")
    s = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    i = db.execute("SELECT * FROM insights WHERE session_id = ?", (session_id,)).fetchone()
    db.close()
    if not s:
        return shell("Session", "<p style='color:#D85A30'>Session not found.</p>", "Sessions")

    def _json_list(val, fallback="[]"):
        try:
            return json.loads(val or fallback)
        except Exception:
            return []

    def _json_dict(val):
        try:
            return json.loads(val or "{}")
        except Exception:
            return {}

    # Convert sqlite3.Row to dict for safe .get() access
    i_dict = dict(i) if i else None

    cards = []
    if i_dict:
        # Header card — only use columns that exist in insights schema
        quality = i_dict.get('prompt_quality') or 0
        summary = i_dict.get('summary') or ''
        cards.append(f"""<div class="card" style="border-left:3px solid var(--teal)">
            <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;">
                <span style="color:#6a8aaa;font-size:.7rem">Quality: {quality:.1f}/1.0</span>
                <span style="color:#6a8aaa;font-size:.7rem">Avg prompt words: {i_dict.get('prompt_avg_words') or 0}</span>
                <span style="color:#6a8aaa;font-size:.7rem">Repetitions: {i_dict.get('repetition_count') or 0}</span>
            </div>
            <p style="color:#a1b0c0;margin:.5rem 0 0;font-size:.85rem">{html.escape(summary)}</p>
        </div>""")

        # Bugs from this session's insight
        bugs = _json_list(i_dict.get("bugs"))
        if bugs:
            items = "".join(
                f'<div style="border-left:2px solid var(--red);padding:.5rem .75rem;margin:.4rem 0;border-radius:0 4px 4px 0;">'
                f'<div style="color:#D85A30;font-size:.8rem">{html.escape(str(b.get("title","")))}</div>'
                f'<div style="color:#6a8aaa;font-size:.7rem">{html.escape(str(b.get("file","")))} — {html.escape(str(b.get("fix","")))}</div></div>'
                for b in bugs if isinstance(b, dict)
            )
            cards.append(f'<div class="card"><h3>Bugs Found</h3>{items}</div>')

        # Optimizations
        opts = _json_list(i_dict.get("optimizations"))
        if opts:
            items = "".join(
                f'<div class="card" style="border-left:2px solid var(--teal);font-size:.75rem">'
                f'<div style="color:#dce8f5">{html.escape(str(o.get("title","")))}</div>'
                f'<div style="color:#6a8aaa;font-size:.65rem;margin-top:2px">{html.escape(str(o.get("suggestion","")))}</div></div>'
                for o in opts if isinstance(o, dict)
            )
            cards.append(f'<div class="card"><h3>Optimizations</h3>{items}</div>')

        # Themes
        themes = _json_list(i_dict.get("themes"))
        if themes:
            tags = " ".join(
                f'<span style="font-size:.65rem;padding:2px 8px;border-radius:10px;border:1px solid #378ADD;color:#378ADD;margin:2px">'
                f'{html.escape(str(t.get("label","") if isinstance(t, dict) else t))}</span>'
                for t in themes
            )
            cards.append(f'<div class="card"><h3>Themes</h3><div style="display:flex;flex-wrap:wrap;gap:4px">{tags}</div></div>')

        # Skill opportunity (CLAUDE.md rule)
        skill_opp = i_dict.get("skill_opportunity") or ""
        if skill_opp:
            cards.append(f'<div class="card"><h3>CLAUDE.md Rule Suggestion</h3>'
                         f'<div class="rule">{html.escape(skill_opp)}</div></div>')

    else:
        if s['model'] == 'git-scan':
            cards.append('<div class="card" style="color:#6a8aaa">Session seeded from git history. Run the daemon with LLM credentials to analyze.</div>')
        else:
            cards.append('<div class="card" style="color:#2e4460">Not yet analyzed.</div>')

    # Session metadata
    i_ref = i_dict or {}
    badge_bg = "#1D9E75" if i_ref.get("analysis_source") == "ide" else "#378ADD"
    badge_txt = "Kiro LLM" if i_ref.get("analysis_source") == "ide" else "BYOK"
    source_badge = f"<span style='background: {badge_bg}20; border: 1px solid {badge_bg}; color: {badge_bg}; padding: 2px 6px; border-radius: 4px; font-size: 0.65rem; margin-left: 8px;'>{badge_txt} Analysis</span>"

    cards.append(f"""<div class="card" style="color:#8ba4be;font-size:.7rem;border:1px solid #111820">
        <h3 style="margin-top:0; color:#dce8f5;">Session Meta {source_badge}</h3>
        <div>Session: {html.escape(session_id)}</div>
        <div>Project: {html.escape(s['project'] or '?')}</div>
        <div>Model: {html.escape(s['model'] or '?')}</div>
        <div>Tokens: {(s['tokens_in'] or 0) + (s['tokens_out'] or 0):,}</div>
        <div>Ended: {s['ended_at'] or '?'}</div>
    </div>""")

    back = '<a href="/sessions" style="color:#378ADD;font-size:.75rem;text-decoration:none">&larr; All sessions</a>'
    content = back + "\n".join(cards)
    db.close()
    return shell(f"Session {session_id[:8]}", content, "Sessions")


@app.route("/api/bugs/<bug_id>/resolve", methods=["POST"])
def resolve_bug(bug_id):
    db = get_conn()
    if not db:
        return "No database", 500
    try:
        db.execute("UPDATE reported_bugs SET status = 'resolved' WHERE id = ?", (bug_id,))
        db.commit()
    except Exception as e:
        return str(e), 500
    finally:
        db.close()
    return redirect("/bugs")

@app.route("/bugs")
def bugs():
    db = get_conn()
    if not db:
        empty = """
<div style="text-align:center;padding:60px 24px;">
  <div style="font-size:40px;margin-bottom:16px;">✅</div>
  <h2 style="font-size:18px;font-weight:700;color:var(--fg);margin-bottom:8px;">No bugs tracked yet</h2>
  <p style="color:var(--muted);font-size:14px;max-width:360px;margin:0 auto;">
    Nora captures bugs and fixes from your sessions. Complete a debugging session to start tracking.
  </p>
</div>"""
        return shell("Bugs", empty, "Bugs")

    show_resolved = request.args.get("show_resolved") == "1"
    status_filter = "" if show_resolved else "WHERE status = 'open'"
    
    all_bugs = []
    try:
        rb_rows = db.execute(
            f"SELECT id, title, severity, status, fix_code, file_path, session_id FROM reported_bugs {status_filter} ORDER BY id DESC LIMIT 100"
        ).fetchall()
        for r in rb_rows:
            all_bugs.append({
                "id": r["id"], "title": r["title"], "severity": r["severity"] or "medium",
                "file": r["file_path"] or "?", "fix": r["fix_code"] or "",
                "session": (r["session_id"] or "")[:8],
                "status": r["status"]
            })
    except Exception:
        pass
    db.close()
    
    toggle_url = "?show_resolved=0" if show_resolved else "?show_resolved=1"
    toggle_text = "Hide resolved" if show_resolved else "Show resolved"
    header = f"""
    <div style="display:flex; justify-content:flex-end; margin-bottom: 1rem;">
        <a href="/bugs{toggle_url}" hx-get="/bugs{toggle_url}" hx-target="body" hx-push-url="true" style="color:#6a8aaa; font-size:0.8rem; text-decoration:none;">{toggle_text}</a>
    </div>
    """

    if not all_bugs:
        return shell("Bugs", header + "<p style='color:#2e4460'>No bugs found yet. Run <code>nora scan &lt;path&gt;</code> or complete a coding session.</p>", "Bugs")
    high = [b for b in all_bugs if b.get("severity") == "high"]
    med  = [b for b in all_bugs if b.get("severity") == "medium"]
    low  = [b for b in all_bugs if b.get("severity") == "low"]
    cards = ""
    for sev, bs, css in [("High", high, "bug-high"), ("Medium", med, "bug-med"), ("Low", low, "bug-low")]:
        if bs:
            cards += f"<h3>{sev} severity</h3>"
        for b in bs:
            if b.get('status') == 'open':
                resolve_btn = f"""<button hx-post="/api/bugs/{b['id']}/resolve" hx-target="body" hx-push-url="true" class="btn-primary" style="padding: 4px 8px; font-size: 11px;">Mark Resolved</button>"""
            else:
                resolve_btn = """<span style="color:#1D9E75; font-size:11px;">Resolved ✓</span>"""

            cards += f"""<div class="card">
              <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                  <div class="{css}" style="font-weight:500;margin-bottom:.25rem">{html.escape(b.get('title',''))}</div>
                  {resolve_btn}
              </div>
              <div style="color:#6a8aaa;font-size:.7rem">{html.escape(b.get('file',''))} &middot; session {b.get('session','')}</div>
              <div style="color:#aaa;margin-top:.25rem">{html.escape(b.get('fix',''))}</div>
            </div>"""
    return shell("Bugs", header + cards, "Bugs")


@app.route("/learnings")
def learnings():
    """Knowledge page (renamed from Learnings) — Best Practices, Playbooks, Anti-patterns."""
    db = get_conn()
    if not db:
        empty = """
<div style="position:relative; min-height: 60vh;">
  <div class="ghosted" style="pointer-events:none;">
    <h3>Best Practices</h3>
    <div class="card" style="border-left:3px solid var(--success);margin-bottom:.5rem;">
      <div style="color:#dce8f5;font-weight:500;margin-bottom:.25rem">Avoid deeply nested ternary operators in JSX</div>
      <div style="color:#6a8aaa;font-size:.7rem">█████████░ 0.95</div>
    </div>
    <div class="card" style="border-left:3px solid var(--warning);margin-bottom:.5rem;">
      <div style="color:#dce8f5;font-weight:500;margin-bottom:.25rem">Abstract redundant API calls into hooks</div>
      <div style="color:#6a8aaa;font-size:.7rem">██████░░░░ 0.65</div>
    </div>
    <h3 style="margin-top:1.5rem">Playbooks</h3>
    <div class="rule" style="border-color:var(--info);margin-bottom:.5rem">Extract magic strings to constants files (Rule #4)</div>
  </div>
  <div class="empty-cta-overlay">
    <div style="font-size:40px;margin-bottom:16px;">📚</div>
    <h2 style="font-size:18px;font-weight:700;color:#fff;margin-bottom:8px;">No patterns extracted yet</h2>
    <p style="color:#8ba4be;font-size:13px;line-height:1.5;margin-bottom:24px;">
      Nora builds your institutional knowledge quietly in the background as you code.
    </p>
    <p style="color:#6a8aaa;font-size:12px;">
      Run <code style="background:rgba(255,255,255,0.1);padding:3px 6px;border-radius:4px;">nora scan .</code> to seed knowledge from your git history.
    </p>
  </div>
</div>"""
        return shell("Knowledge", empty, "Knowledge")

    def _jl(val):
        try:
            return json.loads(val or "[]")
        except Exception:
            return []

    # Domain filter (via query param)
    domain_filter = request.args.get("domain", "")

    # TASK 7.1(a) — Best Practices (patterns by effectiveness)
    best_practices = ""
    try:
        pat_rows = db.execute(
            "SELECT id, COALESCE(name, pattern) AS name, effectiveness FROM patterns ORDER BY effectiveness DESC LIMIT 20"
        ).fetchall()
        for p in pat_rows:
            eff = float(p[2] or 0)
            if eff > 0.8:
                bar_color = "var(--success)"
            elif eff > 0.5:
                bar_color = "var(--warning)"
            else:
                bar_color = "var(--danger)"
            bar = "\u2588" * int(eff * 10) + "\u2591" * (10 - int(eff * 10))
            best_practices += f'<div class="card" style="border-left:3px solid {bar_color};margin-bottom:.5rem;">'
            best_practices += f'<div style="color:#dce8f5;font-weight:500;margin-bottom:.25rem">{html.escape(p[1][:60])}</div>'
            best_practices += f'<div style="color:#6a8aaa;font-size:.7rem">{bar} {eff:.2f}</div>'
            best_practices += f'</div>'
    except Exception:
        pass

    # TASK 7.1(b) — Playbooks (from insights.skill_opportunity)
    playbooks = ""
    try:
        pb_rows = db.execute(
            "SELECT DISTINCT skill_opportunity FROM insights WHERE skill_opportunity IS NOT NULL AND skill_opportunity != '' "
            "ORDER BY id DESC LIMIT 15"
        ).fetchall()
        for pb in pb_rows:
            playbooks += f'<div class="rule" style="border-color:var(--info);margin-bottom:.5rem">{html.escape(pb[0][:100])}</div>'
    except Exception:
        pass

    # TASK 7.1(c) — Mistakes to Avoid (anti-patterns from insights)
    mistakes = ""
    try:
        anti_rows = db.execute(
            "SELECT summary FROM insights WHERE summary LIKE '%mistake%' OR summary LIKE '%pitfall%' "
            "ORDER BY id DESC LIMIT 10"
        ).fetchall()
        for anti in anti_rows:
            mistakes += f'<div class="rule" style="border-color:var(--danger);margin-bottom:.5rem">{html.escape(anti[0][:100])}</div>'
    except Exception:
        pass

    db.close()

    content = f"""
    <h3>Best Practices</h3>
    {best_practices or "<p style='color:#2e4460'>No patterns yet.</p>"}

    <h3 style="margin-top:1rem">Playbooks</h3>
    {playbooks or "<p style='color:#2e4460'>No playbooks yet.</p>"}

    <h3 style="margin-top:1rem">Mistakes to Avoid</h3>
    {mistakes or "<p style='color:#2e4460'>No anti-patterns captured yet.</p>"}
    """
    return shell("Knowledge", content, "Knowledge")


@app.route("/memory")
def memory():
    """Memory page — What Nora injects, components, timeline of events."""
    db = get_conn()
    if not db:
        empty = """
<div style="position:relative; min-height: 60vh;">
  <div class="ghosted" style="pointer-events:none;">
    <div class="card" style="border-left:3px solid var(--teal);margin-bottom:1rem;">
      <h3 style="color:#dce8f5;margin-top:0">What Nora Injects</h3>
      <div class="card" style="border-left:3px solid var(--info);">Identified that you prefer early returns and strict null checks. Adding rule.</div>
    </div>
    <h3>Memory Components</h3>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin-bottom:1rem;">
      <div class="card"><div class="kpi-label">Sessions</div><div class="kpi-value">24</div></div>
      <div class="card"><div class="kpi-label">Patterns</div><div class="kpi-value" style="color:var(--teal)">7</div></div>
      <div class="card"><div class="kpi-label">Hotspots</div><div class="kpi-value" style="color:var(--red)">3</div></div>
    </div>
  </div>
  <div class="empty-cta-overlay">
    <div style="font-size:40px;margin-bottom:16px;">💾</div>
    <h2 style="font-size:18px;font-weight:700;color:#fff;margin-bottom:8px;">Your Memory is Blank</h2>
    <p style="color:#8ba4be;font-size:13px;line-height:1.5;margin-bottom:24px;">
      Nora automatically injects your past patterns and decisions into every new AI session context.
    </p>
    <a href="/" class="btn">Learn how to start a session</a>
  </div>
</div>"""
        return shell("Memory", empty, "Memory")

    # TASK 7.2 — What Nora Injects
    latest_insight = ""
    try:
        insight = db.execute(
            "SELECT summary FROM insights ORDER BY analyzed_at DESC LIMIT 1"
        ).fetchone()
        if insight and insight[0]:
            latest_insight = f"<div class='card' style='border-left:3px solid var(--info);'>{html.escape(insight[0][:200])}</div>"
    except Exception:
        pass

    top_patterns = ""
    try:
        pat_rows = db.execute(
            "SELECT name FROM patterns ORDER BY effectiveness DESC LIMIT 3"
        ).fetchall()
        for p in pat_rows:
            top_patterns += f"<li style='color:#dce8f5;padding:.25rem 0'>{html.escape(p[0])}</li>"
    except Exception:
        pass

    what_nora_injects = f"""
    <div class='card' style='border-left:3px solid var(--teal);margin-bottom:1rem;'>
      <h3 style='color:#dce8f5;margin-top:0'>What Nora Injects</h3>
      {latest_insight or "<p style='color:#2e4460'>No insights yet.</p>"}
      <p style='color:#6a8aaa;font-size:.75rem;margin-top:.5rem'>Top patterns:</p>
      <ul style='margin:.25rem 0;padding-left:1rem;'>{top_patterns or "<li style='color:#2e4460'>None yet.</li>"}</ul>
    </div>
    """

    # TASK 7.2 — Memory Components (4 cards)
    try:
        session_count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        pattern_count = db.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        bug_count = db.execute("SELECT COUNT(*) FROM reported_bugs").fetchone()[0]

        quality = db.execute("SELECT AVG(prompt_quality) FROM insights WHERE prompt_quality > 0").fetchone()[0] or 0
    except Exception:
        session_count = pattern_count = bug_count = 0
        quality = 0

    components = f"""
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin-bottom:1rem;">
      <a href="/sessions" hx-get="/sessions" hx-target="body" hx-push-url="true" class="card" style="text-decoration:none;cursor:pointer;display:block;"><div class="kpi-label">Sessions</div><div class="kpi-value">{session_count:,}</div></a>
      <a href="/learnings" hx-get="/learnings" hx-target="body" hx-push-url="true" class="card" style="text-decoration:none;cursor:pointer;display:block;"><div class="kpi-label">Patterns</div><div class="kpi-value" style="color:var(--teal)">{pattern_count:,}</div></a>
      <a href="/bugs" hx-get="/bugs" hx-target="body" hx-push-url="true" class="card" style="text-decoration:none;cursor:pointer;display:block;"><div class="kpi-label">Hotspots</div><div class="kpi-value" style="color:var(--red)">{bug_count:,}</div></a>
      <div class="card"><div class="kpi-label">Quality</div><div class="kpi-value" style="color:var(--blue)">{quality:.2f}</div></div>
    </div>
    """

    # TASK 7.2 — Injection Feed Timeline
    injections_feed = ""
    try:
        events = db.execute(
            "SELECT result_type, keywords, latency_ms, created_at FROM nora_metrics WHERE event_type = 'impression' ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        for e in events:
            evt_type = html.escape(e[0] or "")
            keywords = html.escape(e[1] or "[]")[0:60]
            lat = round(e[2] or 0)
            ts = time_ago(e[3] or "")
            injections_feed += f"<div style='padding:.5rem 0;border-bottom:1px solid #111820;font-size:.75rem;display:flex;gap:.5rem; justify-content:space-between;'>"
            injections_feed += f"<div><span style='color:var(--amber)'>●</span> <span style='color:#dce8f5'>Injected {evt_type}</span> <span style='color:#6a8aaa'>for {keywords}</span></div>"
            injections_feed += f"<div style='color:#555'>{lat}ms · {ts}</div></div>"
    except Exception:
        pass

    # TASK 8.2 & 8.3 & 8.4 — Steering File Viewer
    try:
        patterns_f = Path.home() / ".kiro" / "steering" / "kernora-patterns.md"
        if patterns_f.exists():
            import time
            mtime = patterns_f.stat().st_mtime
            age_h = (time.time() - mtime) / 3600
            fresh_color = "var(--amber)" if age_h > 24 else "var(--teal)"
            fresh_label = f"Stale (>24h)" if age_h > 24 else "Fresh"
            
            content_str = patterns_f.read_text()
            item_count = content_str.count("\\n## ") + content_str.count("\\n### ")
            preview = html.escape("\\n".join(content_str.split("\\n")[:10]))
            
            steering_viewer = f"""
            <div class='card' style='border-left:3px solid {fresh_color};margin-bottom:1rem;'>
              <div style="display:flex; justify-content:space-between;">
                <h3 style='color:#dce8f5;margin-top:0;font-size:1rem'>Steering File</h3>
                <div style="display:flex; align-items:center; gap:8px;">
                  <span style='color:{fresh_color}; font-size:.75rem; font-weight:600'>{fresh_label}</span>
                  <button hx-post="/api/steering/regenerate" hx-target="this" class="btn-primary" style="padding: 4px 8px; font-size:11px;">Regenerate Now</button>
                </div>
              </div>
              <div style='color:#6a8aaa;font-size:.75rem;margin-bottom:.5rem;'>{item_count} items generated into memory via steering_writer</div>
              <pre style='font-size:.65rem; color:#8ba4be; background:#07090d; padding:8px; border-radius:4px;'>{preview}...</pre>
            </div>
            """
        else:
            steering_viewer = "<p style='color:#6a8aaa'>No steering file found in ~/.kiro/steering/ yet.</p>"
    except Exception as e:
        steering_viewer = f"<p style='color:var(--red)'>Error loading steering file: {e}</p>"

    # Original Hook Events Timeline
    timeline = ""
    try:
        events = db.execute(
            "SELECT event_type, file_path, created_at FROM hook_events ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        for e in events:
            evt_type = html.escape(e[0] or "")
            file_path = html.escape(Path(e[1] or "").name)
            ts = time_ago(e[2] or "")
            timeline += f"<div style='padding:.5rem 0;border-bottom:1px solid #111820;font-size:.75rem;display:flex;gap:.5rem;'>"
            timeline += f"<span style='color:var(--info)'>●</span><span style='color:#dce8f5'>{evt_type}</span> "
            timeline += f"<span style='color:#6a8aaa'>{file_path}</span><span style='color:#555'>{ts}</span></div>"
    except Exception:
        pass

    content = f"""
    {what_nora_injects}
    <h3>Memory Components</h3>
    {components}
    {steering_viewer}
    
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;">
        <div>
            <h3>Injection Feed</h3>
            <div class='card' style='font-size:.75rem;max-height:400px;overflow-y:auto;'>
            {injections_feed or "<p style='color:#2e4460'>No injections yet.</p>"}
            </div>
        </div>
        <div>
            <h3>Hook Event Log</h3>
            <div class='card' style='font-size:.75rem;max-height:400px;overflow-y:auto;'>
            {timeline or "<p style='color:#2e4460'>No events yet.</p>"}
            </div>
        </div>
    </div>
    """

    db.close()
    return shell("Memory", content, "Memory")


@app.route("/decisions")
def decisions():
    """Decisions page — Architectural decisions with search."""
    db = get_conn()
    if not db:
        empty = """
<div style="position:relative; min-height: 60vh;">
  <div class="ghosted" style="pointer-events:none;">
    <div style="margin-bottom:1rem;">
      <input type="text" placeholder="Search decisions..." style="width:100%;padding:.5rem;">
    </div>
    <div class="card" style="border-left:3px solid var(--info);">
      <div style="color:#dce8f5;font-weight:500;margin-bottom:.25rem">Use Zustand instead of Redux for state management</div>
      <div style="color:#6a8aaa;font-size:.7rem;margin-bottom:.25rem">Simpler API, less boilerplate, better TS support for our small components.</div>
      <div style="color:#555;font-size:.65rem">App.tsx · 2d ago</div>
    </div>
    <div class="card" style="border-left:3px solid var(--info);">
      <div style="color:#dce8f5;font-weight:500;margin-bottom:.25rem">Migrate to Postgres JSONB for flexible schema</div>
      <div style="color:#6a8aaa;font-size:.7rem;margin-bottom:.25rem">Avoids constant migrations for user tags while maintaining strict constraints on core schema.</div>
      <div style="color:#555;font-size:.65rem">schema.prisma · 5d ago</div>
    </div>
  </div>
  <div class="empty-cta-overlay">
    <div style="font-size:40px;margin-bottom:16px;">🧭</div>
    <h2 style="font-size:18px;font-weight:700;color:#fff;margin-bottom:8px;">No Decisions Logged</h2>
    <p style="color:#8ba4be;font-size:13px;line-height:1.5;">
      Architectural decisions and rationale discussed during AI sessions will appear here automatically, searchable for your entire team.
    </p>
  </div>
</div>"""
        return shell("Decisions", empty, "Decisions")

    # TASK 7.3 — Search
    search_q = request.args.get("q", "")
    try:
        if search_q:
            dec_rows = db.execute(
                "SELECT id, decision, rationale, alternatives, COALESCE(files, '') AS files, COALESCE(context, '') AS context, created_at FROM decisions "
                "WHERE decision LIKE ? OR rationale LIKE ? ORDER BY created_at DESC LIMIT 50",
                (f"%{search_q}%", f"%{search_q}%")
            ).fetchall()
        else:
            dec_rows = db.execute(
                "SELECT id, decision, rationale, alternatives, COALESCE(files, '') AS files, COALESCE(context, '') AS context, created_at FROM decisions "
                "ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
    except Exception:
        dec_rows = []

    search_box = f"""
    <div style="margin-bottom:1rem;">
      <input type="text" placeholder="Search decisions..."
             hx-get="/decisions" hx-target="body" hx-trigger="keyup changed delay:300ms"
             name="q" value="{html.escape(search_q)}"
             style="width:100%;padding:.5rem;font-size:.8rem">
    </div>
    """

    decisions_list = ""
    for d in dec_rows:
        decision = html.escape(d[1] or "")
        rationale = html.escape(d[2][:100] if d[2] else "")
        files = html.escape(d[4] or "")
        ts = time_ago(d[5] or "")
        decisions_list += f"""
        <div class="card" style="border-left:3px solid var(--info);">
          <div style="color:#dce8f5;font-weight:500;margin-bottom:.25rem">{decision}</div>
          <div style="color:#6a8aaa;font-size:.7rem;margin-bottom:.25rem">{rationale}</div>
          <div style="color:#555;font-size:.65rem">{files} · {ts}</div>
        </div>
        """

    content = f"""
    {search_box}
    <div id="decisions-list">
    {decisions_list or "<p style='color:#2e4460'>No decisions yet.</p>"}
    </div>
    """

    db.close()
    return shell("Decisions", content, "Decisions")


def _telemetry_settings_html() -> str:
    """Render the telemetry transparency + opt-out section for Settings page."""
    if not _telemetry:
        return ""

    enabled = _telemetry.is_telemetry_enabled()
    checked = "checked" if enabled else ""
    payload = _telemetry.build_payload()
    payload_json = json.dumps(payload, indent=2)

    status_color = "#1D9E75" if enabled else "#D85A30"
    status_text = "Active — one anonymous ping per day" if enabled else "Disabled — no data sent"

    return f"""
    <div class="card" style="margin-top:1.5rem;border-left:3px solid {status_color}">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3 style="color:#dce8f5;margin:0">Anonymous Telemetry</h3>
        <form method="POST" action="/settings/telemetry" style="margin:0">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
            <input type="checkbox" name="telemetry_enabled" value="on" {checked}
                   onchange="this.form.submit()"
                   style="width:16px;height:16px;accent-color:#1D9E75">
            <span style="font-size:.7rem;color:#6a8aaa">{'Enabled' if enabled else 'Disabled'}</span>
          </label>
        </form>
      </div>
      <p style="font-size:.7rem;color:{status_color};margin:6px 0 0">{status_text}</p>
      <p style="font-size:.7rem;color:#6a8aaa;margin:8px 0 0;line-height:1.5">
        Helps us understand how many people use Kernora and which IDEs they prefer.
        No filenames, no code, no API keys, no IP logging server-side.
      </p>

      <details style="margin-top:12px">
        <summary style="font-size:.7rem;color:#378ADD;cursor:pointer;user-select:none">
          Show exact payload sent &darr;
        </summary>
        <pre style="margin:8px 0 0;padding:10px;background:#07090d;border:1px solid #1e2d45;
                    border-radius:4px;font-size:.65rem;color:#8ba4be;overflow-x:auto;
                    line-height:1.6;white-space:pre-wrap">{html.escape(payload_json)}</pre>
        <div style="font-size:.6rem;color:#6a8aaa;margin-top:6px;line-height:1.5">
          <strong style="color:#dce8f5">machine_id</strong> — SHA256 hash of hostname+username (not reversible)<br>
          <strong style="color:#dce8f5">ide</strong> — which IDE you're using<br>
          <strong style="color:#dce8f5">version</strong> — extension version<br>
          <strong style="color:#dce8f5">os</strong> — operating system<br>
          <strong style="color:#dce8f5">session_count</strong> — how many sessions in your local DB<br>
          <strong style="color:#dce8f5">analyzed_count</strong> — how many got LLM analysis<br>
          <strong style="color:#dce8f5">rules_count</strong> — distilled rules count<br>
          <strong style="color:#dce8f5">playbooks_count</strong> — captured playbooks count<br>
          <strong style="color:#dce8f5">has_s3</strong> — is S3 backup configured (boolean)<br>
          <strong style="color:#dce8f5">has_cloud_sync</strong> — is cloud sync active (boolean)<br>
          <strong style="color:#dce8f5">sessions_last_7d</strong> — sessions in past week<br>
          <strong style="color:#dce8f5">first_seen_days</strong> — days since first session<br>
          <strong style="color:#dce8f5">days_active</strong> — distinct days with activity<br>
          <strong style="color:#dce8f5">first_rule_days</strong> — days from install to first rule (-1 = none yet)<br>
          <strong style="color:#dce8f5">mcp_tools_used</strong> — which tools you use (names only, no content)
        </div>
      </details>
    </div>"""


@app.route("/coach")
def coach():
    """Coach page — Effectiveness score, anti-patterns, sessions analysis, tips."""
    db = get_conn()
    if not db:
        return shell("Coach", """
        <div class="card" style="border-left:3px solid var(--info);text-align:center;">
          <p style="color:#a1b0c0;margin:1rem 0;">Nora will start tracking your prompt quality once you complete your first AI session.</p>
          <p style="color:#6a8aaa;font-size:.75rem">Install the extension and start coding!</p>
          <br><a href="/welcome" style="color:var(--teal);font-size:13px;">View setup guide →</a>
        </div>
        """, "Coach")

    # TASK 8.1 — Section 1: Your AI Effectiveness Score (now AI Leverage)
    try:
        stats = db.execute(
            "SELECT AVG(prompt_quality), COUNT(*), AVG(prompt_avg_words), SUM(repetition_count), SUM(tokens_estimated) "
            "FROM insights WHERE analyzed_at > datetime('now', '-30 days')"
        ).fetchone()
        avg_quality = stats[0] or 0
        session_count_30d = stats[1] or 0
        avg_words = stats[2] or 0
        total_reps = stats[3] or 0
        total_tokens = stats[4] or 0

        insights_count = db.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
        
        # AI Leverage
        if insights_count < 3:
            leverage = 0
            leverage_disp = "—"
            leverage_lbl = "—"
            leverage_color = "#6a8aaa"
        else:
            leverage_val = round(1.0 + (avg_quality * 4.0), 1)
            leverage = leverage_val
            leverage_disp = str(leverage_val)
            if leverage_val >= 4.0:
                leverage_lbl = "Excellent"
                leverage_color = "#1D9E75"
            elif leverage_val >= 3.0:
                leverage_lbl = "Strong"
                leverage_color = "#378ADD"
            elif leverage_val >= 2.0:
                leverage_lbl = "Developing"
                leverage_color = "#BA7517"
            else:
                leverage_lbl = "Early Stage"
                leverage_color = "#D85A30"

        # Sparkline: map quality values to Unicode blocks
        daily_quality = db.execute(
            "SELECT AVG(prompt_quality) FROM insights WHERE analyzed_at > datetime('now', '-30 days') "
            "GROUP BY date(analyzed_at) ORDER BY date(analyzed_at)"
        ).fetchall()
        sparkline = ""
        if daily_quality:
            for q_row in daily_quality[-7:]:  # last 7 days
                q = q_row[0] or 0
                blocks = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
                idx = min(7, int(q * 8))
                sparkline += blocks[idx]

        # Token cost estimation
        tokens_k = int(total_tokens / 1000)
        cost_est = round(total_tokens * 0.000003, 2)

    except Exception:
        avg_quality = session_count_30d = avg_words = total_reps = total_tokens = 0
        leverage = 0
        leverage_disp = "—"
        leverage_lbl = "—"
        leverage_color = "#6a8aaa"
        sparkline = ""
        tokens_k = 0
        cost_est = 0

    progress = min(100, max(0, int((leverage / 5.0) * 100)))
    circumference = 2 * 3.14159 * 90
    offset = circumference - (progress / 100) * circumference

    section1 = f"""
    <div class="card" style="border-top:1px solid rgba(255,255,255,0.1); border-left:4px solid {leverage_color}; margin-bottom:1.5rem; background: radial-gradient(circle at 100% 0%, rgba(29,158,117,0.05) 0%, rgba(20,25,35,0.6) 100%);">
      <h3 style="color:#dce8f5;margin-top:0">Your AI Effectiveness Score</h3>
      
      <div class="leverage-display">
        <div style="position:relative; width: 220px; height: 220px; display: flex; align-items: center; justify-content: center; margin: 0 auto;">
          <svg width="220" height="220" viewBox="0 0 240 240" style="transform: rotate(-90deg); filter: drop-shadow(0 0 12px {leverage_color}40);">
            <circle cx="120" cy="120" r="90" fill="none" stroke="rgba(255,255,255,0.05)" stroke-width="12"></circle>
            <circle cx="120" cy="120" r="90" fill="none" stroke="{leverage_color}" stroke-width="12" stroke-linecap="round" stroke-dasharray="{circumference}" stroke-dashoffset="{offset}" style="animation: dash 1.5s cubic-bezier(0.4, 0, 0.2, 1) forwards;"></circle>
          </svg>
          <style>@keyframes dash {{ from {{ stroke-dashoffset: {circumference}; }} to {{ stroke-dashoffset: {offset}; }} }}</style>
          <div style="position:absolute; text-align:center;">
            <div class="leverage-number" style="color:{leverage_color}; text-shadow:none;">{leverage_disp}</div>
            <div style="font-size:14px; color:#fff; font-weight:700; letter-spacing:0.05em; margin-top:4px;">{leverage_lbl}</div>
          </div>
        </div>
        <div class="leverage-sub" style="margin-top:16px;">AI Leverage — value generated per token vs. baseline</div>
      </div>
      
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.5rem;margin:1.5rem 0;padding-top:1.5rem;border-top:1px solid rgba(255,255,255,0.05);font-size:.8rem;">
        <div style="text-align:center"><div class="kpi-label">Quality</div><div class="kpi-value" style="color:var(--info)">{avg_quality:.2f}</div></div>
        <div style="text-align:center"><div class="kpi-label">30-Day Sessions</div><div class="kpi-value" style="color:var(--teal)">{session_count_30d:,}</div></div>
        <div style="text-align:center"><div class="kpi-label">Token Usage</div><div class="kpi-value" style="color:var(--amber)">~{tokens_k}k</div></div>
      </div>
      <div style="font-size:.75rem;color:#8ba4be;text-align:center;background:rgba(0,0,0,0.2);padding:8px;border-radius:6px;">Trend: <span style="color:var(--teal);font-size:14px;">{sparkline or '—'}</span> &nbsp;&nbsp;·&nbsp;&nbsp; Est. spend: <strong style="color:#dce8f5">${cost_est}</strong></div>
    </div>
    """

    # TASK 8.1 — Section 2: Your Anti-Patterns
    anti_patterns_config = {
        "vague_request": "Vague requests",
        "missing_context": "Missing context",
        "no_file_reference": "No file references",
        "repeated_instruction": "Repeated instructions",
        "no_error_message": "No error message",
        "too_broad": "Too broad",
    }
    anti_pattern_tips = {
        "vague_request": "Be specific about what you want changed",
        "missing_context": "Include file path and line number",
        "no_file_reference": "Tell the AI which files to look at",
        "repeated_instruction": "Say it once, clearly",
        "no_error_message": "Paste the actual error verbatim",
        "too_broad": "Break big asks into focused steps",
    }

    anti_patterns_agg = {}
    try:
        ap_rows = db.execute(
            "SELECT prompt_antipatterns FROM insights WHERE analyzed_at > datetime('now', '-30 days') "
            "AND prompt_antipatterns IS NOT NULL AND prompt_antipatterns != '[]'"
        ).fetchall()
        for r in ap_rows:
            try:
                ap_list = json.loads(r[0])
                for ap in ap_list:
                    if ap in anti_patterns_agg:
                        anti_patterns_agg[ap] += 1
                    else:
                        anti_patterns_agg[ap] = 1
            except Exception:
                pass
    except Exception:
        pass

    section2 = "<div class='card' style='border-left:3px solid var(--warning);margin-bottom:1rem;'><h3 style='color:#dce8f5;margin-top:0'>Your Anti-Patterns</h3>"
    if anti_patterns_agg:
        sorted_patterns = sorted(anti_patterns_agg.items(), key=lambda x: x[1], reverse=True)[:5]
        for pattern, count in sorted_patterns:
            label = anti_patterns_config.get(pattern, pattern)
            tip = anti_pattern_tips.get(pattern, "")
            section2 += f"""<div style="border:1px solid #BA7517;border-radius:4px;padding:.5rem;margin:.5rem 0;">
              <div style="color:var(--warning);font-weight:500;font-size:.8rem">{label} ({count})</div>
              <div style="color:#6a8aaa;font-size:.7rem;margin-top:.25rem">{tip}</div>
            </div>"""
    else:
        section2 += "<p style='color:#2e4460'>No anti-patterns detected yet. Keep coding!</p>"
    section2 += "</div>"

    # TASK 8.1 — Section 3: Learn From Your Sessions
    section3 = "<div class='card' style='border-left:3px solid var(--success);margin-bottom:1rem;'><h3 style='color:#dce8f5;margin-top:0'>Learn From Your Sessions</h3>"
    try:
        coaching_rows = db.execute(
            "SELECT prompt_coaching, prompt_quality FROM insights WHERE prompt_coaching IS NOT NULL "
            "AND prompt_coaching != '{}' ORDER BY prompt_quality ASC LIMIT 5"
        ).fetchall()
        if coaching_rows:
            for coaching_json, quality in coaching_rows:
                try:
                    coaching = json.loads(coaching_json) if isinstance(coaching_json, str) else coaching_json
                    weak = coaching.get("weak_prompt", "")
                    strong = coaching.get("strong_prompt", "")
                    why = coaching.get("why_better", "")
                    if weak and strong:
                        section3 += f"""<div style="border:1px solid var(--success);border-radius:4px;padding:.5rem;margin:.5rem 0;font-size:.75rem">
                          <div style="color:#6a8aaa;margin-bottom:.25rem"><strong>Weak:</strong> {html.escape(weak[:80])}</div>
                          <div style="color:var(--success);margin-bottom:.25rem"><strong>Strong:</strong> {html.escape(strong[:80])}</div>
                          <div style="color:#aaa"><strong>Why:</strong> {html.escape(why[:80])}</div>
                        </div>"""
                except Exception:
                    pass
        else:
            section3 += "<p style='color:#2e4460'>No coaching examples yet.</p>"
    except Exception:
        section3 += "<p style='color:#2e4460'>No coaching examples yet.</p>"
    section3 += "</div>"

    # TASK 8.1 — Section 4: Tips for Your Leverage Level
    if leverage < 2.6:
        tips_tips = [
            "Include the file path and line number when discussing code. This alone adds +0.8x leverage.",
            "Paste error messages verbatim. Specify the output format you want.",
        ]
    elif leverage < 3.3:
        tips_tips = [
            "Paste error messages verbatim. Specify the output format you want. Target: 3.3x+",
            "Give the AI your mental model before asking for a solution.",
        ]
    elif leverage < 4.0:
        tips_tips = [
            "Give the AI your mental model before asking for a solution. Specify constraints upfront.",
            "When retrying, say what you already tried.",
        ]
    elif leverage < 4.5:
        tips_tips = [
            "Reference specific function names. Give context from your last attempt when retrying.",
            "Ask for explanations, not just code.",
        ]
    else:
        tips_tips = [
            "Top tier. Your prompts are specific, contextual, and well-structured.",
            "Keep shipping — you've mastered AI collaboration.",
        ]

    section4 = f"""<div class='card' style='border-left:3px solid var(--blue);'>
      <h3 style='color:#dce8f5;margin-top:0'>Tips for {leverage_lbl} Leverage ({leverage}x)</h3>
      <ul style='margin:0;padding-left:1rem;color:#a1b0c0;font-size:.8rem;line-height:1.6'>
    """
    for tip in tips_tips:
        section4 += f"<li>{tip}</li>"
    section4 += "</ul></div>"

    # TASK 9.2 — MCP Usage Chart in Coach Tab
    mcp_html = "<div class='card' style='border-left:3px solid var(--amber);margin-bottom:1rem;'><h3 style='color:#dce8f5;margin-top:0'>MCP Tool Usage</h3>"
    try:
        mcp_rows = db.execute(
            "SELECT keywords, COUNT(*) FROM nora_metrics WHERE event_type = 'mcp_call' GROUP BY keywords ORDER BY COUNT(*) DESC LIMIT 10"
        ).fetchall()
        if mcp_rows:
            for tool, count in mcp_rows:
                tool_name = json.loads(tool) if tool.startswith('"') else str(tool).strip("\"'[]")
                mcp_html += f"<div style='display:flex; justify-content:space-between; font-size:0.75rem; padding: 4px 0; border-bottom:1px solid #1e2d45;'>"
                mcp_html += f"  <span style='color:var(--amber)'>{html.escape(tool_name)}</span>"
                mcp_html += f"  <span style='color:#6a8aaa'>{count} calls</span>"
                mcp_html += "</div>"
        else:
            mcp_html += "<p style='color:#2e4460; font-size:0.75rem'>No tools tracked yet.</p>"
    except Exception:
        pass
    mcp_html += "</div>"
    
    db.close()

    content = section1 + section2 + section3 + mcp_html + section4
    return shell("Coach", content, "Coach")


@app.route("/report/export")
def report_export():
    """Export investment report as print-ready HTML."""
    conn = get_conn()
    try:
        # Fetch stats for 30-day window
        stats = conn.execute("""
            SELECT COUNT(*) as sessions,
                   AVG(prompt_quality) as avg_q,
                   SUM(tokens_estimated) as tokens
            FROM insights WHERE analyzed_at > datetime('now', '-30 days')
        """).fetchone()
        patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        bugs = conn.execute("SELECT COUNT(*) FROM reported_bugs WHERE fix_code != ''").fetchone()[0]
        top_patterns = conn.execute(
            "SELECT pattern, effectiveness FROM patterns ORDER BY effectiveness DESC LIMIT 5"
        ).fetchall()
    except Exception:
        stats = None
        patterns = 0
        bugs = 0
        top_patterns = []
    finally:
        conn.close()

    avg_q = stats["avg_q"] or 0 if stats else 0
    sessions = stats["sessions"] or 0 if stats else 0
    tokens = stats["tokens"] or 0 if stats else 0
    leverage = round(1.5 + (avg_q * 3.5), 1)
    leverage_lbl = ("Excellent" if leverage >= 4.5 else "Strong" if leverage >= 4.0
                    else "Developing" if leverage >= 3.3 else "Early Stage")
    tokens_k = int(tokens / 1000)
    cost_est = round(tokens * 0.000003, 2)

    from datetime import datetime
    period = datetime.utcnow().strftime("%B %Y")

    # Build top patterns HTML
    patterns_html = ""
    for p in top_patterns:
        eff = p["effectiveness"] or 0
        bar_w = int(eff * 100)
        patterns_html += f"""
        <tr>
          <td>{html.escape(str(p["pattern"]))}</td>
          <td><div style="background:#1d9e75;height:8px;width:{bar_w}%;border-radius:4px;"></div></td>
          <td style="color:#1d9e75;font-weight:700;">{eff:.0%}</td>
        </tr>"""

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AI Investment Report — {period}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #1a1a2e; background: #fff; }}
  @media print {{
    body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .no-print {{ display: none; }}
  }}
  .header {{ background: #1d9e75; color: white; padding: 40px 48px; }}
  .header-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .logo {{ font-size: 13px; font-weight: 600; opacity: 0.85; letter-spacing: 0.05em; }}
  .report-title {{ font-size: 13px; opacity: 0.75; margin-top: 4px; }}
  .developer {{ font-size: 32px; font-weight: 800; margin-top: 24px; }}
  .period {{ font-size: 14px; opacity: 0.8; margin-top: 4px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; padding: 40px 48px 0; }}
  .kpi {{ border: 1px solid #eee; border-radius: 10px; padding: 24px; }}
  .kpi-val {{ font-size: 40px; font-weight: 800; color: #1d9e75; font-variant-numeric: tabular-nums; }}
  .kpi-label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 6px; }}
  .leverage-section {{ margin: 32px 48px; background: #f7fdf9; border: 1px solid #c8eedc; border-radius: 10px; padding: 32px; display: flex; align-items: center; gap: 32px; }}
  .leverage-num {{ font-size: 80px; font-weight: 800; color: #1d9e75; line-height: 1; font-variant-numeric: tabular-nums; }}
  .leverage-info h2 {{ font-size: 20px; font-weight: 700; }}
  .leverage-info p {{ font-size: 14px; color: #555; margin-top: 8px; }}
  .section {{ margin: 0 48px 32px; }}
  .section h3 {{ font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: #888; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ padding: 10px 0; border-bottom: 1px solid #f0f0f0; font-size: 14px; }}
  td:last-child {{ text-align: right; width: 60px; }}
  td:nth-child(2) {{ padding: 0 16px; }}
  .footer {{ margin: 32px 48px 48px; padding-top: 24px; border-top: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }}
  .footer-left {{ font-size: 12px; color: #aaa; }}
  .footer-cta {{ font-size: 13px; font-weight: 600; color: #1d9e75; }}
  .print-btn {{ position: fixed; bottom: 24px; right: 24px; background: #1d9e75; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; box-shadow: 0 4px 12px rgba(29,158,117,.3); }}
</style>
</head>
<body>
<div class="header">
  <div class="header-top">
    <div>
      <div class="logo">NORA BY KERNORA</div>
      <div class="report-title">AI Investment Report</div>
    </div>
  </div>
  <div class="developer">Developer AI Report</div>
  <div class="period">{period}</div>
</div>

<div class="kpis">
  <div class="kpi"><div class="kpi-val">{sessions}</div><div class="kpi-label">AI Sessions</div></div>
  <div class="kpi"><div class="kpi-val">{patterns}</div><div class="kpi-label">Patterns Captured</div></div>
  <div class="kpi"><div class="kpi-val">{bugs}</div><div class="kpi-label">Bugs Prevented</div></div>
  <div class="kpi"><div class="kpi-val">~{tokens_k}k</div><div class="kpi-label">Tokens Used</div></div>
</div>

<div class="leverage-section">
  <div class="leverage-num">{leverage}x</div>
  <div class="leverage-info">
    <h2>AI Leverage — {leverage_lbl}</h2>
    <p>Generating <strong>{leverage}x</strong> more value per token than the unoptimized baseline.</p>
    <p style="margin-top:8px;color:#aaa;font-size:13px;">Estimated spend: ~${cost_est} this month ({tokens_k}k tokens)</p>
  </div>
</div>

<div class="section">
  <h3>Top Knowledge Patterns</h3>
  <table>{patterns_html or '<tr><td colspan="3" style="color:#aaa;padding:20px 0;">No patterns captured yet — start using Nora to build your knowledge base.</td></tr>'}</table>
</div>

<div class="footer">
  <div class="footer-left">Generated by Nora · kernora.ai · {period}</div>
  <div class="footer-cta">Get Nora for your team → kernora.ai/teams</div>
</div>

<button class="print-btn no-print" onclick="window.print()">Export as PDF</button>
</body>
</html>"""

    return report_html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/settings", methods=["GET", "POST"])
def settings():
    c = load_cfg()
    if request.method == "POST":
        new_provider = request.form.get("provider", c.get("model", {}).get("provider", "anthropic"))
        s3_bucket = request.form.get("s3_bucket", "")
        s3_region = request.form.get("s3_region", "")
        is_managed = request.form.get("is_managed", "false")
        director_mode = request.form.get("director_mode", "false")

        text = CFG.read_text() if CFG.exists() else ""
        text = re.sub(r'provider\s*=\s*"[^"]*"', f'provider = "{new_provider}"', text)

        # Update S3 bucket and region (no credential handling)
        if "[swarm]" not in text:
            text += f"\n\n[swarm]\ntype = 'byok_s3'\nbucket = '{s3_bucket}'\nregion = '{s3_region}'\ndirector_mode = {director_mode}\n"
        else:
            text = re.sub(r'bucket\s*=\s*"[^"]*"', f'bucket = "{s3_bucket}"', text)
            text = re.sub(r'region\s*=\s*"[^"]*"', f'region = "{s3_region}"', text)
            text = re.sub(r'director_mode\s*=\s*(true|false)', f'director_mode = {director_mode}', text)

        # Provisioning mode update
        if is_managed == "true":
            if "type = 'byok_s3'" in text:
                text = text.replace("type = 'byok_s3'", "type = 'kernora_managed'")

        CFG.write_text(text)
        os.chmod(CFG, 0o600)
        return redirect("/settings")

    mode     = c.get("mode", {}).get("type", "byok")
    provider = c.get("model", {}).get("provider", "anthropic")
    port     = c.get("dashboard", {}).get("port", 2742)
    
    swarm_cfg = c.get("swarm", {})
    bucket = swarm_cfg.get("bucket", "")
    region = swarm_cfg.get("region", "")
    d_mode = "checked" if str(swarm_cfg.get("director_mode", "false")).lower() == "true" else ""

    # Tiered model detection
    try:
        from analyzer import select_models, MODELS
        model_info = select_models(c)
        deep_id, deep_cap, deep_name = model_info["deep"]
        classify_id, classify_cap, classify_name = model_info["classify"]
        model_warnings = model_info.get("warnings", [])
    except Exception:
        deep_name, deep_cap = "unknown", 0
        classify_name, classify_cap = "unknown", 0
        model_warnings = ["Could not load model selector"]

    cap_color = {5: "#1D9E75", 4: "#378ADD", 3: "#BA7517", 2: "#D85A30", 1: "#D85A30"}

    # TASK 7.3: Injection Latency Alert
    try:
        db = get_conn()
        latency_row = db.execute("SELECT AVG(latency_ms) FROM nora_metrics WHERE event_type = 'impression' AND latency_ms > 0").fetchone()
        avg_latency = round(latency_row[0] or 0)
        db.close()
    except Exception:
        avg_latency = 0
    
    latency_alert = ""
    if avg_latency > 3000:
        latency_alert = f"<div class='privacy' style='margin-bottom:1rem;border-color:var(--amber);color:var(--amber);'>&#9888; Warning: Context injection latency is high ({avg_latency}ms avg). Hook execution should be &lt;500ms to preserve UX.</div>"

    ide_banner = ""
    if _is_ide_provided_llm():
        ide_name = _get_ide_name("IDE")
        ide_banner = f"""
    <div class="privacy" style="margin-bottom:1rem;border-color:#378ADD;color:#378ADD;">
      &#9432; LLM provided by {ide_name} &mdash; no API key required.<br>
      <span style="font-size:.65rem;color:#6a8aaa;">
        The provider/model settings below are used only for standalone Kernora analysis
        (e.g. <code>nora analyze</code> from the CLI). {ide_name} manages its own model
        for inline completions and chat.
      </span>
    </div>"""

    is_ide = _is_ide_provided_llm()
    ide_name = _get_ide_name("IDE") if is_ide else ""

    if is_ide:
        # ── Kiro / Cursor mode: clean, minimal settings ──────────────────
        content = f"""
    {ide_banner}
    {latency_alert}
    <div class="setting-row">
      <span>Dashboard port</span><span>{port}</span>
    </div>
    <div class="setting-row">
      <span>Database</span><span style="color:var(--teal)">~/.kernora/echo.db</span>
    </div>
    <div class="setting-row">
      <span>Config</span><span style="color:#6a8aaa">~/.kernora/config.toml</span>
    </div>

    <div class="card" style="margin-top:1.5rem;border-left:3px solid #378ADD">
      <h3 style="color:#dce8f5;margin-bottom:.5rem">How It Works</h3>
      <p style="font-size:.75rem;color:#8ba4be;line-height:1.6;margin:0">
        Kernora watches your coding sessions and extracts patterns, decisions, and bugs
        into a local <code>echo.db</code> database. Run <code>nora scan</code> on any repo
        to import its full git history. On your next session, that intelligence is injected
        into {ide_name}'s AI context automatically via steering files.
      </p>
      <p style="font-size:.75rem;color:#8ba4be;line-height:1.6;margin:.75rem 0 0">
        {ide_name} provides the LLM. Kernora uses it for semantic analysis.
        No API key needed. No data leaves your machine.
      </p>
    </div>

    <div class="card" style="margin-top:1rem;border-left:3px solid var(--teal)">
      <h3 style="color:#dce8f5;margin-bottom:.5rem">MCP Tools (16)</h3>
      <p style="font-size:.75rem;color:#8ba4be;line-height:1.5;margin:0 0 .5rem">
        Say these in {ide_name}'s chat &mdash; Nora handles the rest:
      </p>

      <p style="font-size:.65rem;color:#6a8aaa;margin:.75rem 0 .25rem;text-transform:uppercase;letter-spacing:.5px">Explore your history</p>
      <div style="font-size:.7rem;color:#dce8f5;font-family:monospace;line-height:1.9">
        <code>nora stats</code> &mdash; sessions, tokens, costs, model usage over time<br>
        <code>nora search &lt;query&gt;</code> &mdash; find past sessions by keyword<br>
        <code>nora session &lt;id&gt;</code> &mdash; full detail on a specific session
      </div>

      <p style="font-size:.65rem;color:#6a8aaa;margin:.75rem 0 .25rem;text-transform:uppercase;letter-spacing:.5px">Learn from your codebase</p>
      <div style="font-size:.7rem;color:#dce8f5;font-family:monospace;line-height:1.9">
        <code>nora patterns</code> &mdash; recurring engineering patterns across sessions<br>
        <code>nora decisions</code> &mdash; architectural decisions with rationale<br>
        <code>nora bugs</code> &mdash; past bugs and how they were fixed<br>
        <code>nora skills</code> &mdash; team playbook: rules, bug patterns, methodology<br>
        <code>nora scan &lt;path&gt;</code> &mdash; import a git repo's full history
      </div>

      <p style="font-size:.65rem;color:#6a8aaa;margin:.75rem 0 .25rem;text-transform:uppercase;letter-spacing:.5px">Quality &amp; reviews</p>
      <div style="font-size:.7rem;color:#dce8f5;font-family:monospace;line-height:1.9">
        <code>nora pe-review &lt;focus&gt;</code> &mdash; principal engineer code review<br>
        <code>nora coe &lt;issue&gt;</code> &mdash; technical root-cause investigation (5 Whys)<br>
        <code>nora coe product &lt;issue&gt;</code> &mdash; product/UX COE<br>
        <code>nora retro</code> &mdash; engineering retrospective with metrics<br>
        <code>nora scope &lt;task&gt;</code> &mdash; validate a task against project history
      </div>

      <p style="font-size:.65rem;color:#6a8aaa;margin:.75rem 0 .25rem;text-transform:uppercase;letter-spacing:.5px">Factory operations</p>
      <div style="font-size:.7rem;color:#dce8f5;font-family:monospace;line-height:1.9">
        <code>nora sofac</code> &mdash; software factory health: shipped, pending, build status<br>
        <code>nora inventory</code> &mdash; feature inventory: what exists, what's missing
      </div>

      <p style="font-size:.65rem;color:#6a8aaa;margin:.75rem 0 .25rem;text-transform:uppercase;letter-spacing:.5px">Help</p>
      <div style="font-size:.7rem;color:#dce8f5;font-family:monospace;line-height:1.9">
        <code>nora help</code> &mdash; full tool reference with examples
      </div>
    </div>

    <div class="card" style="margin-top:1rem; border: 1px solid #1e2d45;">
      <h3 style="color:#dce8f5; margin-bottom: 0.25rem;">Cloud Sync <span style="font-size:.6rem;color:#6a8aaa;font-weight:normal">(optional)</span></h3>
      <p style="font-size:.7rem; color:#6a8aaa; margin:4px 0 0;">
        Configure cloud sync via environment variables — see documentation.
      </p>
    </div>

    {_telemetry_settings_html()}
"""
    else:
        # ── VS Code / BYOK mode: full settings with provider, models, swarm ─
        content = f"""
    <div class="setting-row">
      <span>Mode</span><span style="color:var(--teal)">{mode}</span>
    </div>
    <div class="setting-row">
      <span>Dashboard port</span><span>{port}</span>
    </div>
    <div class="setting-row">
      <span>Provider</span>
      <form method="POST" style="display:inline">
        <select name="provider" onchange="this.form.submit()">
          {''.join(f'<option value="{p}" {"selected" if p==provider else ""}>{p}</option>'
                   for p in ["auto","anthropic","google","openai","bedrock","grok","ollama"])}
        </select>
      </form>
    </div>

    <div class="card" style="margin-top:1rem;border-left:3px solid var(--teal)">
      <h3 style="color:#dce8f5">Tiered Model Selection</h3>
      <p style="font-size:.7rem;color:#6a8aaa;margin:0 0 .75rem">
        Kernora auto-selects two models: a DEEP model for playbooks, decisions, and patterns,
        and a CLASSIFY model for session type, themes, and bugs.
      </p>
      <div style="display:flex;gap:20px;flex-wrap:wrap">
        <div style="flex:1;min-width:200px">
          <div style="font-size:.65rem;color:#6a8aaa;text-transform:uppercase;letter-spacing:.06em">Deep Extraction</div>
          <div style="font-size:.9rem;font-weight:500;color:#dce8f5;margin:4px 0">{html.escape(deep_name)}</div>
          <div style="font-size:.7rem;color:{cap_color.get(deep_cap, '#888')}">Capability {deep_cap}/5</div>
        </div>
        <div style="flex:1;min-width:200px">
          <div style="font-size:.65rem;color:#6a8aaa;text-transform:uppercase;letter-spacing:.06em">Classification</div>
          <div style="font-size:.9rem;font-weight:500;color:#dce8f5;margin:4px 0">{html.escape(classify_name)}</div>
          <div style="font-size:.7rem;color:{cap_color.get(classify_cap, '#888')}">Capability {classify_cap}/5</div>
        </div>
      </div>
      {''.join(f'<div style="margin-top:.5rem;font-size:.7rem;color:#D85A30;border-left:2px solid #D85A30;padding-left:8px">{html.escape(w)}</div>' for w in model_warnings)}
    </div>

    <div class="card" style="margin-top:1.5rem; border: 1px solid #1e2d45;">
      <h3 style="color:#dce8f5; border-bottom: 1px solid #1e2d45; padding-bottom: 0.5rem; margin-bottom: 0;">Enterprise Swarm Cloud</h3>
      <p style="font-size: 0.75rem; color: #6a8aaa; margin-top: 8px;">Synchronize your local SOTA methodologies across your entire engineering team instantly.</p>

      <form method="POST" style="margin-top: 1rem;">
        <input type="hidden" name="provider" value="{provider}">

        <label style="font-size:0.75rem; color:#6a8aaa; display:block; margin-top:10px;">AWS IAM Configuration (BYOK)</label>
        <div style="font-size:0.65rem; color:#888780; margin-bottom: 10px;">AWS credentials must be configured via environment variables or AWS CLI. Do not enter credentials here.</div>
        <div style="display: flex; gap: 10px; margin-bottom: 10px;">
          <input type="text" name="s3_bucket" value="{bucket}" placeholder="enterprise-swarm-bucket" style="width:50%;">
          <input type="text" name="s3_region" value="{region}" placeholder="us-east-1" style="width:50%;">
        </div>

        <div style="margin: 15px 0; border-top: 1px dotted #1e2d45; padding-top: 15px;">
           <label style="font-size:0.75rem; color:#6a8aaa; display:block;">Or use Kernora Managed Infrastructure</label>
           <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 8px;">
             <span style="font-size:0.65rem; color:#888780;">Zero Setup. 100% Encrypted SLA. Automatically eject data to your AWS bucket anytime.</span>
             <button type="button" onclick="document.getElementById('managed_toggle').value='true'; this.form.submit()" style="color:#1D9E75; border-color:#1D9E75;">Provision Organization Cloud</button>
             <input type="hidden" id="managed_toggle" name="is_managed" value="false">
           </div>
        </div>

        <div style="margin: 15px 0; border-top: 1px dotted #1e2d45; padding-top: 15px; display:flex; align-items:center; gap:8px;">
           <input type="checkbox" name="director_mode" value="true" {d_mode}>
           <span style="font-size:0.75rem; color:#dce8f5;">Enable Director Hub View (Global Network Analytics)</span>
        </div>

        <button type="submit" style="width:100%; margin-top:10px; background:#1e2d45; color:white;">Save Swarm Protocol Config</button>
      </form>
    </div>

    {_telemetry_settings_html()}
"""
    danger_zone = f"""
    <div class="card" style="margin-top:1.5rem; border: 1px solid rgba(224, 92, 92, 0.4); background: rgba(224, 92, 92, 0.05);">
      <h3 style="color:#e05c5c; border-bottom: 1px solid rgba(224,92,92,0.2); padding-bottom: 0.5rem; margin-bottom: 0;">Danger Zone</h3>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:1rem;">
        <div>
          <div style="color:#dce8f5; font-weight:500; font-size:.8rem;">Clear Local Database</div>
          <div style="font-size:0.75rem; color:#6a8aaa; margin-top:4px;">Permanently delete all sessions, patterns, and decisions.</div>
        </div>
        <form method="POST" action="/settings/nuke" onsubmit="return confirm('WARNING: Are you sure you want to permanently delete all local Kernora data?');">
          <button type="submit" style="background:rgba(224, 92, 92, 0.1); color:#e05c5c; border:1px solid #e05c5c; padding:6px 12px; border-radius:4px; font-weight:600; cursor:pointer; font-size:.7rem;">Nuke Database</button>
        </form>
      </div>
    </div>
    """
    
    privacy_text = "&#9678; All data local" if is_ide else "&#9678; BYOK mode"
    content += danger_zone + f"""
    <div class="privacy">
      {privacy_text} &mdash; zero bytes sent to Kernora.<br>
      Your sessions, your machine. Kernora provides execution code only.
    </div>"""

    return shell("Settings", content, "Settings")

@app.route("/settings/nuke", methods=["POST"])
def nuke_database():
    db = get_conn()
    if db:
        tables = ["sessions", "patterns", "reported_bugs", "insights", "playbooks"]
        for t in tables:
            try:
                db.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        db.commit()
        db.close()
    return redirect("/")


@app.route("/settings/telemetry", methods=["POST"])
def toggle_telemetry():
    enabled = request.form.get("telemetry_enabled", "off") == "on"
    if _telemetry:
        _telemetry.set_telemetry_enabled(enabled)
    return redirect("/settings")


@app.route("/api/telemetry-payload")
def telemetry_payload_api():
    """Returns the exact JSON payload so the Settings page can display it."""
    if _telemetry:
        return json.dumps(_telemetry.build_payload(), indent=2)
    return json.dumps({"error": "telemetry module not loaded"})


@app.route("/api/ide/heartbeat", methods=["POST"])
def ide_heartbeat():
    data = request.json or {}
    with _ide_heartbeat_lock:
        _ide_heartbeat_cache["ts"] = time.time()
        _ide_heartbeat_cache["ok"] = data.get("ok", False)
        _ide_heartbeat_cache["model"] = data.get("model", "")
        _ide_heartbeat_cache["reason"] = data.get("reason", "Verified")
    return jsonify({"status": "received"})


@app.route("/api/status-bar")
def status_bar_api():
    return _status_bar_html()


@app.route("/api/llm-status")
def llm_status_api():
    """Lightweight LLM reachability probe — called by HTMX every 30s."""
    s = probe_llm()
    if request.headers.get("HX-Request"):
        # Return the topbar fragment for HTMX swap
        return _llm_status_html(s)
    return s  # JSON for programmatic callers


def _dot(ok: bool | None) -> str:
    color = "#1D9E75" if ok else ("#e05c5c" if ok is False else "#7a8a9e")
    return f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};flex-shrink:0;"></span>'


def _llm_status_html(s: dict) -> str:
    color = "#1D9E75" if s["ok"] else "#e05c5c"
    # IDE-provided LLM gets a distinct label
    if s.get("provider") == "ide":
        label = f"LLM · {s['model']}" if s.get("model") and s.get("model") != "provided by IDE" else "LLM · provided by IDE"
    else:
        label = "LLM reachable" if s["ok"] else "LLM unreachable"
    dot = f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};margin-right:4px;vertical-align:middle;"></span>'
    tip = html.escape(f'{s["provider"]} · {s["model"] or "?"} · {s["reason"]}')
    # IDE-provided: no need to poll — LLM availability is managed externally
    hx_attrs = '' if s.get("provider") == "ide" else 'hx-get="/api/llm-status" hx-trigger="every 30s" hx-swap="outerHTML" '
    return (
        f'<span id="llm-status" title="{tip}" '
        f'{hx_attrs}'
        f'style="font-size:.65rem;color:{color};cursor:default;">'
        f'{dot}{label}</span>'
    )


def _status_bar_html() -> str:
    """Full status bar fragment shown in the dashboard content area."""
    llm = probe_llm()

    # Daemon: check if the Unix socket is alive
    daemon_sock = Path.home() / ".kernora" / "daemon.sock"
    daemon_ok = daemon_sock.exists()
    daemon_label = "Daemon running" if daemon_ok else "Daemon offline"
    daemon_tip = str(daemon_sock) if daemon_ok else f"Socket not found at {daemon_sock}"

    # DB: can we open echo.db?
    db_path = Path.home() / ".kernora" / "echo.db"
    db_ok = False
    db_sessions = 0
    db_label = "DB offline"
    if db_path.exists():
        try:
            c = sqlite3.connect(str(db_path), timeout=2)
            db_sessions = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            c.close()
            db_ok = True
            db_label = f"DB · {db_sessions:,} sessions"
        except Exception:
            db_label = "DB error"

    if llm["ok"] and daemon_ok and db_ok:
        return ""  # Completely invisible when healthy!

    # Only show if something is actively broken
    items = ""
    if not llm["ok"]:
        items += f"""
          <a href="/settings" hx-get="/settings" hx-target="body" hx-push-url="true" class="status-pill" style="border-color:#e05c5c;">
            {_dot(False)}
            <span style="color:#e05c5c;font-weight:500;">LLM Offline</span>
            <span style="color:#8ba4be;">(Check Settings)</span>
          </a>"""
    if not (daemon_ok and db_ok):
        items += f"""
          <a href="/settings" hx-get="/settings" hx-target="body" hx-push-url="true" class="status-pill" style="border-color:#e05c5c;">
            {_dot(False)}
            <span style="color:#e05c5c;font-weight:500;">Daemon/DB Offline</span>
          </a>"""


    return f"""<div id="status-bar"
      hx-get="/api/status-bar" hx-trigger="every 30s" hx-swap="outerHTML"
      style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;
             padding:8px 32px;background:rgba(224,92,92,0.05);border-bottom:1px solid rgba(224,92,92,0.2);
             font-family:ui-sans-serif,system-ui,sans-serif;">
      {items}
    </div>"""


@app.route("/health")
def health():
    db = get_conn()
    if not db:
        return {"status": "ok", "sessions": 0, "analyzed": 0, "llm_reachable": None}
    total    = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    analyzed = db.execute("SELECT COUNT(*) FROM sessions WHERE analyzed=1").fetchone()[0]
    db.close()
    s = probe_llm()
    return {
        "status": "ok",
        "sessions": total,
        "analyzed": analyzed,
        "llm_reachable": s["ok"],
        "llm_provider": s["provider"],
        "llm_reason": s["reason"],
        "engine": {
            "session_scan_interval_sec": 60,
            "analysis_trigger": "immediate (on new session)",
            "analysis_fallback_sec": 600,
            "steering_regen": "after each analysis",
            "telemetry_interval_hrs": 6,
        },
    }


# ── Live session tracking endpoints ──────────────────────────────────────────

@app.route("/api/session/start", methods=["POST"])
def api_session_start():
    """Receive session start notification from agentSpawn hook."""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        from datetime import datetime as _dt
        with _live_lock:
            _live_session["active"] = True
            _live_session["session_id"] = payload.get("session_id", "")
            _live_session["project"] = payload.get("project", "")
            _live_session["started_at"] = _dt.now().strftime("%H:%M:%S")
            _live_session["tool_count"] = 0
            _live_session["error_count"] = 0
            _live_session["files_touched"] = []
            _live_session["tools_used"] = {}
            _live_session["recent_errors"] = []
            _live_session["last_event_at"] = ""
            _live_session["last_mini_analysis"] = 0
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500


@app.route("/api/live-session")
def api_live_session_html():
    """Return HTMX partial: live session card for the Overview page."""
    with _live_lock:
        if not _live_session["active"]:
            # Check for stale session (no events in 5 min = session probably ended)
            return '<div id="live-session" hx-get="/api/live-session" hx-trigger="every 5s" hx-swap="outerHTML"></div>'

        s = dict(_live_session)  # snapshot under lock

    proj = Path(s["project"]).name if s["project"] else "unknown"
    dur = s["started_at"]

    # Tool breakdown
    tool_bars = ""
    for tname, cnt in sorted(s["tools_used"].items(), key=lambda x: -x[1])[:6]:
        w = min(cnt * 12, 180)
        tool_bars += (
            f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0">'
            f'<span style="min-width:100px;font-size:.65rem;color:#dce8f5">{html.escape(tname)}</span>'
            f'<div style="background:#1D9E75;height:8px;border-radius:3px;width:{w}px"></div>'
            f'<span style="font-size:.6rem;color:#6a8aaa">{cnt}</span></div>'
        )

    # Files touched (last 5)
    files_html = ""
    for fp in s["files_touched"][-5:]:
        fname = Path(fp).name if fp else "?"
        files_html += f'<span style="background:#1a2a3a;padding:2px 6px;border-radius:3px;font-size:.6rem;color:#7fb8e0;margin:2px">{html.escape(fname)}</span>'

    # Recent errors
    errors_html = ""
    if s["recent_errors"]:
        for err in s["recent_errors"][-2:]:
            errors_html += f'<div style="font-size:.6rem;color:#e74c3c;margin:2px 0;font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%">{html.escape(err[:100])}</div>'

    return f'''<div id="live-session" hx-get="/api/live-session" hx-trigger="every 5s" hx-swap="outerHTML"
     style="border-left:3px solid #1D9E75; background:linear-gradient(135deg, #0a1a12, #071510); padding:14px; border-radius:6px; margin-bottom:16px; position:relative; overflow:hidden;">
  <div style="position:absolute;top:10px;right:12px;width:8px;height:8px;border-radius:50%;background:#1D9E75;animation:pulse 2s infinite"></div>
  <h3 style="margin:0 0 8px 0;color:#1D9E75;font-size:.9rem">&#9679; Live Session</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px">
    <div><span style="font-size:.6rem;color:#6a8aaa">Project</span><br><span style="font-size:.75rem;color:#dce8f5">{html.escape(proj)}</span></div>
    <div><span style="font-size:.6rem;color:#6a8aaa">Started</span><br><span style="font-size:.75rem;color:#dce8f5">{dur}</span></div>
    <div><span style="font-size:.6rem;color:#6a8aaa">Tools / Errors</span><br><span style="font-size:.75rem;color:#dce8f5">{s["tool_count"]}</span> <span style="font-size:.65rem;color:{"#e74c3c" if s["error_count"] else "#6a8aaa"}">({s["error_count"]} errors)</span></div>
  </div>
  {f'<div style="margin-bottom:8px">{tool_bars}</div>' if tool_bars else ""}
  {f'<div style="margin-bottom:6px;display:flex;flex-wrap:wrap;gap:2px">{files_html}</div>' if files_html else ""}
  {f'<div style="margin-top:6px;border-top:1px solid #1a2a3a;padding-top:6px">{errors_html}</div>' if errors_html else ""}
</div>
<style>@keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:0.3 }} }}</style>'''


# ── HTTP session capture — works for ALL IDEs (Kiro, Cursor, VS Code) ─────
# This is the primary session ingestion endpoint. Hooks should try HTTP POST
# here first, then fall back to Unix socket, then spool to disk.

@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    """Gracefully terminate the Flask process over HTTP."""
    _daemon_log("Received shutdown request via HTTP.")
    import os, signal
    # Send SIGTERM to self to cleanly exit the development server
    os.kill(os.getpid(), signal.SIGTERM)
    return {"ok": True, "message": "Shutting down"}


@app.route("/api/session/end", methods=["POST"])
def api_session_end():
    """Receive a session payload over HTTP from any IDE hook.

    Expected JSON body (same format as the Unix socket payload):
    {
        "session_id": "abc123",
        "project": "/path/to/project",
        "started_at": "2026-03-30T10:00:00Z",
        "ended_at": "2026-03-30T10:30:00Z",
        "tokens_in": 1200,
        "tokens_out": 800,
        "model": "claude-sonnet-4-6",
        "turns": [...]
    }

    Returns: {"ok": true} on success, {"ok": false, "error": "..."} on failure.
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return {"ok": False, "error": "invalid JSON"}, 400

        session_id = payload.get("session_id", "")
        if not session_id:
            return {"ok": False, "error": "missing session_id"}, 400

        from db import store_session
        store_session(payload)

        sid = session_id[:8]
        tok = payload.get("tokens_in", 0) + payload.get("tokens_out", 0)
        _daemon_log(f"[HTTP] stored session {sid} ({tok} tokens)")

        # Clear live session
        with _live_lock:
            _live_session["active"] = False

        # Trigger analysis immediately in background
        threading.Thread(target=_run_analysis, daemon=True).start()

        return {"ok": True, "session_id": session_id}
    except Exception as e:
        _daemon_log(f"[HTTP] session end error: {e}")
        return {"ok": False, "error": str(e)}, 500

@app.route("/api/hook/event", methods=["POST"])
def api_hook_event():
    db = get_conn()
    if not db:
        return jsonify({"error": "No database"}), 500
    try:
        data = request.json or {}
        event_type = data.get("event_type", "unknown")
        session_id = data.get("session_id", "")
        file_path = data.get("file_path", "")
        detail = data.get("detail", "")
        
        db.execute(
            "INSERT INTO hook_events (event_type, session_id, file_path, detail) VALUES (?, ?, ?, ?)",
            (event_type, session_id, file_path, detail)
        )
        db.commit()
    except Exception as e:
        _daemon_log(f"[Dashboard] Error logging hook event: {e}")
    finally:
        db.close()
    return jsonify({"ok": True})


@app.route("/api/steering/regenerate", methods=["POST"])
def api_steering_regenerate():
    try:
        venv_python = Path.home() / ".kernora" / "venv" / "bin" / "python3"
        writer_path = Path.home() / ".kernora" / "app" / "steering_writer.py"
        if venv_python.exists() and writer_path.exists():
            import subprocess
            subprocess.Popen([str(venv_python), str(writer_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return """<div style="color:var(--teal); font-size:12px;">Regeneration started...</div>"""
    except Exception as e:
        return str(e), 500

@app.route("/api/analyze/ide", methods=["POST"])
def api_analyze_ide():
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return {"ok": False, "error": "invalid JSON"}, 400

        session_id = payload.get("session_id", "")
        raw_result = payload.get("result", "")
        
        # Strip markdown ```json block if the LLM wrapped it
        if "```json" in raw_result:
            raw_result = raw_result.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_result:
            raw_result = raw_result.split("```")[1].split("```")[0].strip()
            
        insight = json.loads(raw_result)
        
        from db import mark_analyzed
        mark_analyzed(session_id, insight, analysis_source='ide')
        _daemon_log(f"[IDE Bridge] session {session_id} successfully mapped via vscode.lm")
        
        return {"ok": True}
    except Exception as e:
        _daemon_log(f"[IDE Bridge] parsing error: {e}")
        return {"ok": False, "error": str(e)}, 500


@app.route("/api/tool/event", methods=["POST"])
def api_tool_event():
    """Receive tool usage events from Kiro postToolUse hooks over HTTP.

    Expected JSON body:
    {
        "tool_name": "write_file",
        "success": true,
        "file_path": "/path/to/file.py",  (optional)
        "error_snippet": "Error: ..."      (optional, on failure)
    }

    Updates live session state for real-time dashboard display.
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return {"ok": False, "error": "invalid JSON"}, 400

        tool_name = payload.get("tool_name", "unknown")
        success = payload.get("success", True)
        file_path = payload.get("file_path", "")
        error_snippet = payload.get("error_snippet", "")

        # Store in nora_metrics DB
        db = get_conn()
        if db:
            try:
                db.execute(
                    "INSERT INTO nora_metrics (event_type, result_type, keywords, created_at) "
                    "VALUES ('tool_use', ?, ?, datetime('now'))",
                    (tool_name, json.dumps({"success": success, "file": file_path})),
                )
                db.commit()
            except Exception:
                pass
            finally:
                db.close()

        # Update live session state
        from datetime import datetime as _dt
        with _live_lock:
            # Auto-start live session if not started (agentSpawn might not have fired)
            if not _live_session["active"]:
                _live_session["active"] = True
                _live_session["started_at"] = _dt.now().strftime("%H:%M:%S")

            _live_session["tool_count"] += 1
            _live_session["last_event_at"] = _dt.now().strftime("%H:%M:%S")

            # Track tool usage
            _live_session["tools_used"][tool_name] = _live_session["tools_used"].get(tool_name, 0) + 1

            # Track files
            if file_path and file_path not in _live_session["files_touched"]:
                _live_session["files_touched"].append(file_path)

            # Track errors
            if not success:
                _live_session["error_count"] += 1
                if error_snippet:
                    _live_session["recent_errors"].append(error_snippet)
                    _live_session["recent_errors"] = _live_session["recent_errors"][-3:]

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500


# ── Merged daemon: socket listener + spool replay + analysis loop ──────────
# Previously in daemon.py — now runs as daemon threads inside the dashboard
# process. One process = one install = always works.

import socket as _socket

_SOCK = Path.home() / ".kernora" / "daemon.sock"
_SPOOL = Path.home() / ".kernora" / "spool"


def _daemon_log(msg: str):
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _replay_spool():
    """Replay any spooled session JSON files into echo.db."""
    if not _SPOOL.exists():
        return
    count = 0
    for f in sorted(_SPOOL.glob("*.json")):
        try:
            payload = json.loads(f.read_text())
            from db import store_session
            store_session(payload)
            f.unlink()
            count += 1
        except Exception as e:
            _daemon_log(f"spool error {f.name}: {e}")
    if count:
        _daemon_log(f"replayed {count} spooled session(s)")


def _socket_server():
    """Listen on Unix socket for incoming session payloads from hooks."""
    _SOCK.unlink(missing_ok=True)  # Clean up stale socket
    try:
        with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as srv:
            srv.bind(str(_SOCK))
            _SOCK.chmod(0o600)
            srv.listen(5)
            _daemon_log(f"socket listening at {_SOCK}")
            while True:
                conn, _ = srv.accept()
                with conn:
                    data = b""
                    while chunk := conn.recv(4096):
                        data += chunk
                    if data:
                        try:
                            payload = json.loads(data.decode().strip())
                            from db import store_session
                            store_session(payload)
                            sid = payload.get("session_id", "?")[:8]
                            tok = payload.get("tokens_in", 0) + payload.get("tokens_out", 0)
                            _daemon_log(f"stored session {sid} ({tok} tokens)")
                        except Exception as e:
                            _daemon_log(f"session parse error: {e}")
    except Exception as e:
        _daemon_log(f"socket server error: {e}")


def _kiro_session_scanner():
    """Every 5 min: scan for Kiro-generated files as evidence of sessions.

    Kiro doesn't fire Claude Code's Stop hook, so sessions never reach echo.db.
    This scanner looks for Nora-generated .md files (nora-decisions.md,
    nora-patterns.md, nora-antipatterns.md) created/modified since last scan.
    Each new modification = one session.
    """
    import hashlib
    from datetime import datetime as _dt, timezone as _tz

    SCAN_INTERVAL = 60  # 1 minute — lightweight file stat, costs nothing
    NORA_FILES = ["kernora-decisions.md", "kernora-patterns.md", "kernora-antipatterns.md",
                   "nora-decisions.md", "nora-patterns.md", "nora-antipatterns.md"]  # scan both old+new names
    seen_mtimes: dict[str, float] = {}  # path → last seen mtime

    _daemon_log("Kiro session scanner started (60s interval)")

    while True:
        time.sleep(SCAN_INTERVAL)
        try:
            # Scan all recently opened workspaces by checking common project locations
            # Also check the most recently active workspace via DB
            projects_to_scan: set[str] = set()

            db = get_conn()
            if db:
                try:
                    rows = db.execute(
                        "SELECT DISTINCT project FROM sessions ORDER BY inserted_at DESC LIMIT 10"
                    ).fetchall()
                    for r in rows:
                        if r[0]:
                            projects_to_scan.add(r[0])
                except Exception:
                    pass
                finally:
                    db.close()

            # Also scan home directory common code folders
            home = Path.home()
            for code_dir in ["code", "projects", "dev", "workspace", "repos"]:
                p = home / code_dir
                if p.is_dir():
                    for child in p.iterdir():
                        if child.is_dir() and not child.name.startswith("."):
                            projects_to_scan.add(str(child))

            new_sessions = 0
            for project in projects_to_scan:
                project_path = Path(project)
                if not project_path.is_dir():
                    continue

                for fname in NORA_FILES:
                    fpath = project_path / fname
                    if not fpath.exists():
                        continue

                    mtime = fpath.stat().st_mtime
                    key = str(fpath)

                    if key in seen_mtimes and seen_mtimes[key] >= mtime:
                        continue  # No change since last scan

                    seen_mtimes[key] = mtime

                    # Skip if this is the first scan (don't backfill old files)
                    if key not in seen_mtimes and len(seen_mtimes) > len(NORA_FILES) * 2:
                        # Not first scan — this is a genuine new modification
                        pass

                    # Create a session from this file modification
                    mod_time = _dt.fromtimestamp(mtime, tz=_tz.utc)
                    session_id = hashlib.sha256(
                        f"kiro-{project}-{fname}-{mtime}".encode()
                    ).hexdigest()[:16]

                    # Read file to estimate content size
                    try:
                        content = fpath.read_text()
                        word_count = len(content.split())
                    except Exception:
                        word_count = 0

                    payload = {
                        "session_id": f"kiro-{session_id}",
                        "project": project,
                        "started_at": (mod_time.replace(second=0, microsecond=0)).isoformat(),
                        "ended_at": mod_time.isoformat(),
                        "tokens_in": word_count * 2,   # rough estimate
                        "tokens_out": word_count * 3,
                        "model": "kiro-agent",
                        "turns": [],
                    }

                    try:
                        from db import store_session
                        store_session(payload)
                        new_sessions += 1
                    except Exception as e:
                        _daemon_log(f"kiro scanner store error: {e}")

            if new_sessions:
                _daemon_log(f"kiro scanner: created {new_sessions} session(s) from file changes")
                # Trigger analysis immediately — don't wait for the hourly loop
                _run_analysis()

        except Exception as e:
            _daemon_log(f"kiro scanner error: {e}")


def _run_analysis():
    """Run analysis on unanalyzed sessions. Called by scanner or analysis loop."""
    try:
        from db import get_unanalyzed, mark_analyzed, get_jobs_for_session, delete_jobs_for_session
        from analyzer import analyze, queue_ide_jobs, finalize_ide_analysis
        sessions = get_unanalyzed(limit=50)
        if not sessions:
            return
            
        is_ide_mode = _is_ide_provided_llm()
        if is_ide_mode:
            _daemon_log(f"found {len(sessions)} session(s) — using IDE proxy for inference")
        else:
            _daemon_log(f"analyzing {len(sessions)} session(s) via BYOK keys...")
            
        for session in sessions:
            try:
                sid = session["id"]
                if is_ide_mode:
                    jobs = get_jobs_for_session(sid)
                    if not jobs:
                        queue_ide_jobs(session)
                        _daemon_log(f"queued new IDE inference jobs for {sid[:8]}")
                        continue
                    
                    all_done = all(j["status"] in ("completed", "error") for j in jobs)
                    if not all_done:
                        continue # Still processing in IDE
                        
                    result = finalize_ide_analysis(session, jobs)
                    delete_jobs_for_session(sid)
                else:
                    result = analyze(session)
                mark_analyzed(session["id"], result, analysis_source='byok')
                model = result.get("model_used", "?")
                bugs = len(result.get("bugs", []))
                _daemon_log(f"analyzed {session['id'][:8]}: {bugs} bugs [{model}]")
            except Exception as e:
                _daemon_log(f"analysis failed for {session['id'][:8]}: {e}")
        # Regenerate steering files after analysis
        try:
            from steering_writer import generate_all
            generate_all()
        except Exception as e:
            _daemon_log(f"steering generation error: {e}")
    except ImportError:
        pass  # analyzer not available — skip silently
    except Exception as e:
        _daemon_log(f"analysis error: {e}")


def _analysis_loop():
    """Periodic fallback: catch sessions missed by event-driven triggers."""
    _daemon_log("analysis loop started (10-min fallback)")
    while True:
        time.sleep(600)  # 10 minutes — fallback only, scanner triggers immediately
        _run_analysis()


if __name__ == "__main__":
    c = load_cfg()
    port = c.get("dashboard", {}).get("port", 2742)

    # Initialize database
    try:
        from db import init_db
        init_db()
    except Exception:
        pass

    # Anonymous telemetry — one ping per day, opt-out via config.toml
    if _telemetry:
        _telemetry.maybe_ping()

    # Start daemon threads (previously separate daemon.py process)
    t_spool = threading.Thread(target=_replay_spool, daemon=True)
    t_socket = threading.Thread(target=_socket_server, daemon=True)
    t_analysis = threading.Thread(target=_analysis_loop, daemon=True)
    t_kiro_scan = threading.Thread(target=_kiro_session_scanner, daemon=True)
    # t_spool.start() # Disabled to let Native MLX Bridge (extension.ts) handle spool
    t_socket.start()
    t_analysis.start()
    t_kiro_scan.start()

    _daemon_log(f"dashboard + daemon at http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
