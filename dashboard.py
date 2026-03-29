#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
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

from flask import Flask, request, redirect

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

app = Flask(__name__)
DB  = Path.home() / ".kernora" / "echo.db"
CFG = Path.home() / ".kernora" / "config.toml"

CSS = """
<style>
:root{--teal:#1D9E75;--blue:#378ADD;--amber:#BA7517;--red:#D85A30;--gray:#888780}
*{box-sizing:border-box}
body{font-family:ui-monospace,monospace;background:#07090d;color:#dce8f5;margin:0;padding:0}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:.75rem 1.5rem;
        border-bottom:1px solid #1e2d45;background:#0b0f1a}
.logo{font-size:1rem;font-weight:600;color:#dce8f5}.logo span{color:#00bcd4}
.badge-byok{background:#07150f;border:1px solid #1D9E75;color:#1D9E75;
            font-size:.7rem;padding:2px 8px;border-radius:20px;margin-left:8px}
nav{display:flex;gap:0;padding:.5rem 1.5rem;border-bottom:1px solid #1e2d45}
nav a{color:#6a8aaa;font-size:.75rem;padding:.4rem .8rem;text-decoration:none;
      border-bottom:2px solid transparent}
nav a.active{color:#dce8f5;border-bottom-color:#dce8f5}
.content{padding:1.25rem 1.5rem}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.625rem;margin-bottom:1.25rem}
.kpi{background:#0e1318;border-radius:8px;padding:.75rem 1rem}
.kpi-label{font-size:.65rem;color:#6a8aaa;letter-spacing:.06em;text-transform:uppercase;margin-bottom:.25rem}
.kpi-value{font-size:1.375rem;font-weight:500}
table{width:100%;border-collapse:collapse;font-size:.75rem}
th{text-align:left;font-size:.65rem;color:#6a8aaa;padding:0 0 .5rem;border-bottom:1px solid #1e2d45}
td{padding:.5rem 0;border-bottom:1px solid #111820;vertical-align:middle}
.bug-high{color:#D85A30}.bug-med{color:#BA7517}.bug-low{color:#1D9E75}
.card{background:#0e1318;border-radius:8px;padding:1rem;margin-bottom:.75rem;font-size:.8rem}
.rule{background:#071510;border-left:2px solid #1D9E75;padding:.5rem .75rem;margin:.4rem 0;
      font-size:.75rem;border-radius:0 4px 4px 0}
.setting-row{display:flex;align-items:center;justify-content:space-between;
             padding:.625rem 0;border-bottom:1px solid #111820;font-size:.8rem}
.privacy{background:#071510;border:1px solid #1D9E75;border-radius:6px;
         padding:.625rem 1rem;margin-top:.75rem;font-size:.75rem;color:#1D9E75}
select,input[type=text]{background:#111820;border:1px solid #1e2d45;color:#dce8f5;
                         border-radius:4px;padding:3px 8px;font-family:inherit;font-size:.8rem}
button{background:transparent;border:1px solid #1e2d45;color:#6a8aaa;padding:4px 12px;
       border-radius:4px;cursor:pointer;font-family:inherit;font-size:.75rem}
button:hover{border-color:#378ADD;color:#378ADD}
h3{margin:0 0 .5rem;font-size:.8rem;color:#6a8aaa;font-weight:500}
</style>
"""

HTMX = '<script src="https://cdnjs.cloudflare.com/ajax/libs/htmx/1.9.12/htmx.min.js"></script>'


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


def probe_llm() -> dict:
    """
    Lightweight LLM reachability check. Returns:
      {"ok": bool, "provider": str, "model": str, "reason": str}
    Uses cached result within _LLM_CACHE_TTL seconds.
    """
    with _llm_status_lock:
        if time.time() - _llm_status_cache["ts"] < _LLM_CACHE_TTL and _llm_status_cache["ok"] is not None:
            return dict(_llm_status_cache)

    cfg = load_cfg()
    provider = cfg.get("model", {}).get("provider", "anthropic")
    ok = False
    reason = ""
    model = ""

    try:
        if provider == "anthropic" or provider == "auto":
            key = os.environ.get("ANTHROPIC_API_KEY", "")
            model = "claude-haiku-4-5-20251001"
            if not key:
                reason = "ANTHROPIC_API_KEY not set"
            else:
                status = _http_get(
                    "https://api.anthropic.com/v1/models",
                    {"x-api-key": key, "anthropic-version": "2023-06-01"},
                )
                if status == 200:
                    ok = True
                    reason = "reachable"
                elif status == 401:
                    reason = "invalid API key (401)"
                elif status == 0:
                    reason = "network unreachable"
                else:
                    reason = f"HTTP {status}"

        elif provider == "ollama":
            model = cfg.get("ollama", {}).get("model", "llama3.2:3b")
            status = _http_get("http://localhost:11434/api/tags", {})
            if status == 200:
                ok = True
                reason = "Ollama running"
            elif status == 0:
                reason = "Ollama not running (localhost:11434 unreachable)"
            else:
                reason = f"Ollama HTTP {status}"

        elif provider == "openai":
            key = os.environ.get("OPENAI_API_KEY", "")
            model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
            if not key:
                reason = "OPENAI_API_KEY not set"
            else:
                status = _http_get(
                    "https://api.openai.com/v1/models",
                    {"Authorization": f"Bearer {key}"},
                )
                ok = status == 200
                reason = "reachable" if ok else ("invalid key (401)" if status == 401 else f"HTTP {status}")

        elif provider == "google":
            key = os.environ.get("GEMINI_API_KEY", "")
            model = cfg.get("google", {}).get("model", "gemini-2.5-pro")
            if not key:
                reason = "GEMINI_API_KEY not set"
            else:
                status = _http_get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                    {},
                )
                ok = status == 200
                reason = "reachable" if ok else (f"HTTP {status}")

        elif provider == "bedrock":
            model = cfg.get("bedrock", {}).get("model", "amazon.nova-lite-v1:0")
            try:
                import boto3  # type: ignore
                boto3.session.Session().get_credentials()
                ok = True
                reason = "AWS credentials found"
            except Exception as e:
                reason = f"AWS credentials missing: {e}"

        elif provider == "grok":
            key = os.environ.get("XAI_API_KEY", "")
            model = cfg.get("grok", {}).get("model", "grok-beta")
            if not key:
                reason = "XAI_API_KEY not set"
            else:
                status = _http_get(
                    "https://api.x.ai/v1/models",
                    {"Authorization": f"Bearer {key}"},
                )
                ok = status == 200
                reason = "reachable" if ok else f"HTTP {status}"

        else:
            reason = f"Unknown provider: {provider}"

    except Exception as e:
        reason = f"probe error: {e}"

    result = {"ok": ok, "provider": provider, "model": model, "reason": reason}
    with _llm_status_lock:
        _llm_status_cache.update(result)
        _llm_status_cache["ts"] = time.time()
    return result


def nav(active: str) -> str:
    links = [("Overview", "/"), ("Sessions", "/sessions"),
             ("Bugs", "/bugs"), ("Learnings", "/learnings"),
             ("Settings", "/settings")]
    items = "".join(
        f'<a href="{url}" hx-get="{url}" hx-target="body" hx-push-url="true" class="{"active" if name == active else ""}">{name}</a>'
        for name, url in links
    )
    return f"<nav>{items}</nav>"


def shell(title: str, content: str, active: str) -> str:
    c = load_cfg()
    mode = c.get("mode", {}).get("type", "byok")
    badge = '<span class="badge-byok">BYOK</span>' if mode == "byok" else ""
    llm = probe_llm()
    llm_dot = _llm_status_html(llm)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Kernora — {title}</title>
{CSS}{HTMX}</head><body>
<div class="topbar">
  <span class="logo">&#9678; kernora<span>.ai</span>{badge}</span>
  <span style="font-size:.7rem;color:#2e4460;display:flex;align-items:center;gap:16px;">
    AI Work Intelligence &middot; {mode} mode
    &nbsp;&nbsp;{llm_dot}
  </span>
</div>
{nav(active)}
{_status_bar_html()}
<div class="content">{content}</div>
</body></html>"""


@app.route("/")
def index():
    db = get_conn()
    if not db:
        return shell("Overview", "<p style='color:#2e4460'>No data yet. Run a Claude Code session.</p>", "Overview")
    total    = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    analyzed = db.execute("SELECT COUNT(*) FROM sessions WHERE analyzed=1").fetchone()[0]
    tokens   = db.execute("SELECT COALESCE(SUM(tokens_in+tokens_out),0) FROM sessions").fetchone()[0]
    bug_rows = db.execute("SELECT bugs FROM insights WHERE bugs IS NOT NULL").fetchall()
    total_bugs = sum(
        len(json.loads(r["bugs"])) for r in bug_rows
        if r["bugs"] and r["bugs"] != "[]"
    )
    # Deep extraction metrics
    try:
        insight_rows = db.execute(
            "SELECT skill_opportunity, session_type, claude_md_rules, "
            "playbook, effective_prompts, anti_patterns, knowledge_domains "
            "FROM insights WHERE summary IS NOT NULL AND summary != '' AND summary != 'Empty session.'"
        ).fetchall()
    except Exception:
        insight_rows = []

    nora_rules = 0
    playbook_count = 0
    session_types = {}
    all_domains = set()
    for r in insight_rows:
        if r["skill_opportunity"]:
            nora_rules += 1
        try:
            rules = json.loads(r["claude_md_rules"] or "[]")
            nora_rules += len([x for x in rules if x])
        except Exception:
            pass
        if r["playbook"] and len(r["playbook"]) > 10:
            playbook_count += 1
        st = r["session_type"] or "unknown"
        session_types[st] = session_types.get(st, 0) + 1
        try:
            for d in json.loads(r["knowledge_domains"] or "[]"):
                if isinstance(d, str):
                    all_domains.add(d)
        except Exception:
            pass

    kpis = f"""
    <div class="card" style="border-left: 3px solid var(--amber); background: #071510; margin-bottom: 20px; padding: 16px;">
        <h2 style="margin: 0 0 8px 0; color: #dce8f5; font-size: 1.1rem;">Kernora Deep Intelligence</h2>
        <p style="margin: 0; font-size: 0.8rem; color: #a1b0c0; line-height: 1.5;">
            Two-phase extraction: deterministic metadata (tools, files, commands) + LLM semantic analysis (decisions, patterns, playbooks). All data local to <code>echo.db</code>.
        </p>
    </div>

    <div class="kpi-row" style="margin-bottom: 20px;">
      <div class="kpi"><div class="kpi-label">Total Sessions</div>
        <div class="kpi-value">{total:,}</div></div>
      <div class="kpi"><div class="kpi-label">Total Tokens Tracked</div>
        <div class="kpi-value" style="color:var(--blue)">{tokens:,}</div></div>
      <div class="kpi"><div class="kpi-label">Analyzed Sessions</div>
        <div class="kpi-value" style="color:var(--teal)">{analyzed:,}</div></div>
      <div class="kpi"><div class="kpi-label">Rules Distilled</div>
        <div class="kpi-value" style="color:var(--amber)">{nora_rules:,}</div></div>
      <div class="kpi"><div class="kpi-label">Playbooks Captured</div>
        <div class="kpi-value" style="color:#9B59B6">{playbook_count:,}</div></div>
      <div class="kpi"><div class="kpi-label">Knowledge Domains</div>
        <div class="kpi-value" style="color:#378ADD">{len(all_domains):,}</div></div>
    </div>
    """

    # Session type breakdown
    if session_types:
        type_bars = "".join(
            f'<div style="display:flex;align-items:center;gap:8px;margin:3px 0">'
            f'<span style="min-width:180px;font-size:.7rem;color:#dce8f5">{html.escape(st)}</span>'
            f'<div style="background:#1D9E75;height:10px;border-radius:4px;width:{min(count*30, 200)}px"></div>'
            f'<span style="font-size:.65rem;color:#6a8aaa">{count}</span></div>'
            for st, count in sorted(session_types.items(), key=lambda x: -x[1])
        )
        kpis += f'<div class="card" style="margin-bottom:20px"><h3>Session Types</h3>{type_bars}</div>'

    # Top rules
    top_rules = []
    for r in insight_rows:
        if r["skill_opportunity"]:
            top_rules.append(r["skill_opportunity"])
        try:
            for rule in json.loads(r["claude_md_rules"] or "[]"):
                if isinstance(rule, str) and rule.strip():
                    top_rules.append(rule.strip())
        except Exception:
            pass
    if top_rules:
        kpis += "<div class='card' style='margin-bottom: 20px;'><h3>Latest Distilled Rules</h3>"
        for rule in top_rules[-5:]:
            kpis += f'<div class="rule">{html.escape(rule)}</div>'
        kpis += "</div>"
    else:
        kpis += "<div class='card' style='margin-bottom: 20px; border-left: 3px solid #334; background: #0b0f1a;'><p style='color:#7a8a9e; margin:0;'><em>No rules distilled yet. Analyze sessions to build your corporate methodology.</em></p></div>"
    recent = db.execute(
        "SELECT id, project, ended_at, tokens_in+tokens_out as tok, analyzed FROM sessions "
        "ORDER BY inserted_at DESC LIMIT 5"
    ).fetchall()
    rows = "".join(
        f"<tr><td>{html.escape(str(r['id'])[:8])}</td><td>{html.escape(Path(r['project'] or '?').name)}</td>"
        f"<td>{(r['ended_at'] or '')[:16]}</td>"
        f"<td>{r['tok']:,}</td>"
        f"<td>{'&#10003;' if r['analyzed'] else '&hellip;'}</td></tr>"
        for r in recent
    )
    table = f"""<h3>Recent sessions</h3>
    <table><tr><th>ID</th><th>Project</th><th>Ended</th><th>Tokens</th><th>Analyzed</th></tr>
    {rows}</table>""" if rows else "<p style='color:#2e4460'>No sessions yet.</p>"
    db.close()
    return shell("Overview", kpis + table, "Overview")


@app.route("/sessions")
def sessions():
    db = get_conn()
    if not db:
        return shell("Sessions", "<p style='color:#2e4460'>No data.</p>", "Sessions")
    rows = db.execute(
        "SELECT s.id, s.project, s.ended_at, s.tokens_in, s.tokens_out, s.model, s.analyzed, "
        "i.summary, i.session_type, i.workflow_stage FROM sessions s LEFT JOIN insights i ON i.session_id=s.id "
        "ORDER BY s.inserted_at DESC LIMIT 50"
    ).fetchall()
    db.close()

    def _type_badge(st):
        colors = {"feature_build": "#1D9E75", "debugging": "#D85A30", "refactoring": "#BA7517",
                  "infrastructure": "#378ADD", "research": "#9B59B6", "deployment": "#2ECC71",
                  "review": "#6a8aaa", "multi_agent_coordination": "#E74C3C",
                  "skill_creation": "#F39C12", "configuration": "#378ADD", "exploration": "#9B59B6"}
        c = colors.get(st or "", "#2e4460")
        return f'<span style="font-size:.6rem;padding:1px 6px;border-radius:10px;border:1px solid {c};color:{c}">{html.escape(st or "—")}</span>'

    trs_parts = []
    for r in rows:
        sid = str(r['id'])
        proj = html.escape(Path(r['project'] or '?').name)
        ended = (r['ended_at'] or '')[:16]
        tok = (r['tokens_in'] or 0) + (r['tokens_out'] or 0)
        badge = _type_badge(r['session_type'])
        summ = html.escape(str(r['summary'] or '')[:80])
        trs_parts.append(
            f"<tr><td><a href='/sessions/{sid}' style='color:#378ADD;text-decoration:none'>{html.escape(sid[:8])}</a></td>"
            f"<td>{proj}</td><td>{ended}</td><td>{tok:,}</td><td>{badge}</td>"
            f"<td style='color:#6a8aaa;font-size:.7rem'>{summ}</td></tr>"
        )
    trs = "".join(trs_parts)
    content = f"""<table>
    <tr><th>ID</th><th>Project</th><th>Ended</th><th>Tokens</th><th>Type</th><th>Summary</th></tr>
    {trs or "<tr><td colspan='6' style='color:#2e4460'>No sessions yet.</td></tr>"}
    </table>"""
    return shell("Sessions", content, "Sessions")


@app.route("/sessions/<session_id>")
def session_detail(session_id):
    db = get_conn()
    if not db:
        return shell("Session", "<p style='color:#2e4460'>No data.</p>", "Sessions")
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

    cards = []
    if i:
        # Header card
        cards.append(f"""<div class="card" style="border-left:3px solid var(--teal)">
            <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;">
                <span style="font-size:1rem;font-weight:600">{html.escape(i['session_type'] or 'Unknown type')}</span>
                <span style="color:#6a8aaa;font-size:.75rem">{html.escape(i['workflow_stage'] or '')}</span>
                <span style="color:#6a8aaa;font-size:.7rem">Quality: {i['prompt_quality'] or 0:.1f}/1.0</span>
            </div>
            <p style="color:#a1b0c0;margin:.5rem 0 0;font-size:.85rem">{html.escape(i['summary'] or '')}</p>
        </div>""")

        # Playbook
        playbook = i.get("playbook") or ""
        if playbook:
            cards.append(f"""<div class="card"><h3>Playbook</h3>
                <pre style="color:#a1b0c0;font-size:.75rem;white-space:pre-wrap;margin:0">{html.escape(playbook)}</pre>
            </div>""")

        # Architectural decisions
        decisions = _json_list(i.get("architectural_decisions"))
        if decisions:
            items = "".join(
                f'<div style="margin-bottom:.5rem"><div style="color:#dce8f5;font-size:.8rem">{html.escape(str(d.get("decision","")))}</div>'
                f'<div style="color:#6a8aaa;font-size:.7rem">Context: {html.escape(str(d.get("context","")))}</div></div>'
                for d in decisions if isinstance(d, dict)
            )
            cards.append(f'<div class="card"><h3>Architectural Decisions</h3>{items}</div>')

        # Effective prompts
        prompts = _json_list(i.get("effective_prompts"))
        if prompts:
            items = "".join(
                f'<div class="rule" style="margin-bottom:.5rem">'
                f'<div style="color:#dce8f5;font-size:.75rem">{html.escape(str(p.get("prompt",""))[:200])}</div>'
                f'<div style="color:#6a8aaa;font-size:.65rem;margin-top:2px">{html.escape(str(p.get("why_effective","")))}</div></div>'
                for p in prompts if isinstance(p, dict)
            )
            cards.append(f'<div class="card"><h3>Effective Prompts</h3>{items}</div>')

        # Anti-patterns
        anti = _json_list(i.get("anti_patterns"))
        if anti:
            items = "".join(
                f'<div style="border-left:2px solid var(--red);padding:.5rem .75rem;margin:.4rem 0;border-radius:0 4px 4px 0;">'
                f'<div style="color:#D85A30;font-size:.8rem">{html.escape(str(a.get("pattern","")))}</div>'
                f'<div style="color:#6a8aaa;font-size:.7rem">Fix: {html.escape(str(a.get("fix","")))}</div></div>'
                for a in anti if isinstance(a, dict)
            )
            cards.append(f'<div class="card"><h3>Anti-Patterns</h3>{items}</div>')

        # CLAUDE.md rules
        rules = _json_list(i.get("claude_md_rules"))
        if rules:
            items = "".join(f'<div class="rule">{html.escape(str(r))}</div>' for r in rules if r)
            cards.append(f'<div class="card"><h3>CLAUDE.md Rule Suggestions</h3>{items}</div>')

        # Tools used
        tools = _json_dict(i.get("tools_used"))
        if tools:
            bars = "".join(
                f'<div style="display:flex;align-items:center;gap:8px;margin:2px 0">'
                f'<span style="min-width:100px;font-size:.7rem;color:#dce8f5">{html.escape(str(name))}</span>'
                f'<div style="background:#1D9E75;height:8px;border-radius:4px;width:{min(count*3, 200)}px"></div>'
                f'<span style="font-size:.65rem;color:#6a8aaa">{count}</span></div>'
                for name, count in sorted(tools.items(), key=lambda x: -x[1])[:15]
            )
            cards.append(f'<div class="card"><h3>Tools Used</h3>{bars}</div>')

        # Knowledge domains
        domains = _json_list(i.get("knowledge_domains"))
        if domains:
            tags = " ".join(
                f'<span style="font-size:.65rem;padding:2px 8px;border-radius:10px;border:1px solid #378ADD;color:#378ADD;margin:2px">{html.escape(str(d))}</span>'
                for d in domains
            )
            cards.append(f'<div class="card"><h3>Knowledge Domains</h3><div style="display:flex;flex-wrap:wrap;gap:4px">{tags}</div></div>')

        # Files touched
        files = _json_list(i.get("files_touched"))
        if files:
            file_list = "".join(
                f'<div style="font-size:.7rem;color:#6a8aaa;padding:1px 0">{html.escape(str(f))}</div>'
                for f in files[:25]
            )
            more = f'<div style="color:#2e4460;font-size:.65rem">... and {len(files)-25} more</div>' if len(files) > 25 else ""
            cards.append(f'<div class="card"><h3>Files Touched ({len(files)})</h3>{file_list}{more}</div>')

        # Reusable patterns
        patterns = _json_list(i.get("reusable_patterns"))
        if patterns:
            items = "".join(
                f'<div class="rule" style="border-color:var(--blue)">'
                f'<div style="color:#dce8f5;font-size:.75rem">{html.escape(str(p.get("pattern","") if isinstance(p, dict) else p))}</div>'
                f'{"<div style=color:#6a8aaa;font-size:.65rem>" + html.escape(str(p.get("context",""))) + "</div>" if isinstance(p, dict) and p.get("context") else ""}'
                f'</div>'
                for p in patterns
            )
            cards.append(f'<div class="card"><h3>Reusable Patterns</h3>{items}</div>')

    else:
        cards.append('<div class="card" style="color:#2e4460">Not yet analyzed.</div>')

    # Session metadata
    cards.append(f"""<div class="card" style="color:#6a8aaa;font-size:.7rem">
        <div>Session: {html.escape(session_id)}</div>
        <div>Project: {html.escape(s['project'] or '?')}</div>
        <div>Model: {html.escape(s['model'] or '?')}</div>
        <div>Tokens: {(s['tokens_in'] or 0) + (s['tokens_out'] or 0):,}</div>
        <div>Ended: {s['ended_at'] or '?'}</div>
    </div>""")

    back = '<a href="/sessions" style="color:#378ADD;font-size:.75rem;text-decoration:none">&larr; All sessions</a>'
    content = back + "\n".join(cards)
    return shell(f"Session {session_id[:8]}", content, "Sessions")


@app.route("/bugs")
def bugs():
    db = get_conn()
    if not db:
        return shell("Bugs", "<p style='color:#2e4460'>No data.</p>", "Bugs")
    rows = db.execute("SELECT bugs, session_id FROM insights WHERE bugs IS NOT NULL").fetchall()
    db.close()
    all_bugs = []
    for r in rows:
        try:
            bs = json.loads(r["bugs"])
            for b in bs:
                b["session"] = r["session_id"][:8]
                all_bugs.append(b)
        except Exception:
            pass
    if not all_bugs:
        return shell("Bugs", "<p style='color:#2e4460'>No bugs found yet. Run a session and wait for analysis.</p>", "Bugs")
    high = [b for b in all_bugs if b.get("severity") == "high"]
    med  = [b for b in all_bugs if b.get("severity") == "medium"]
    low  = [b for b in all_bugs if b.get("severity") == "low"]
    cards = ""
    for sev, bs, css in [("High", high, "bug-high"), ("Medium", med, "bug-med"), ("Low", low, "bug-low")]:
        if bs:
            cards += f"<h3>{sev} severity</h3>"
        for b in bs:
            cards += f"""<div class="card">
              <div class="{css}" style="font-weight:500;margin-bottom:.25rem">{b.get('title','')}</div>
              <div style="color:#6a8aaa;font-size:.7rem">{b.get('file','')} &middot; session {b.get('session','')}</div>
              <div style="color:#aaa;margin-top:.25rem">{b.get('fix','')}</div>
            </div>"""
    return shell("Bugs", cards or "<p style='color:#2e4460'>No bugs.</p>", "Bugs")


@app.route("/learnings")
def learnings():
    db = get_conn()
    if not db:
        return shell("Learnings", "<p style='color:#2e4460'>No data.</p>", "Learnings")
    rows = db.execute(
        "SELECT skill_opportunity, summary, session_id, session_type, "
        "claude_md_rules, effective_prompts, anti_patterns, playbook, "
        "reusable_patterns, knowledge_domains FROM insights "
        "ORDER BY id DESC LIMIT 30"
    ).fetchall()
    db.close()

    def _jl(val):
        try:
            return json.loads(val or "[]")
        except Exception:
            return []

    # ── Aggregate CLAUDE.md rules across all sessions ──
    all_rules = []
    for r in rows:
        rules = _jl(r["claude_md_rules"])
        for rule in rules:
            if isinstance(rule, str) and rule.strip():
                all_rules.append(rule.strip())
        if r["skill_opportunity"] and r["skill_opportunity"] not in all_rules:
            all_rules.append(r["skill_opportunity"])

    rules_html = "".join(f'<div class="rule">{html.escape(r)}</div>' for r in all_rules[:15])

    # ── Aggregate effective prompts ──
    all_prompts = []
    for r in rows:
        for p in _jl(r["effective_prompts"]):
            if isinstance(p, dict) and p.get("prompt"):
                all_prompts.append(p)
    prompts_html = "".join(
        f'<div class="card" style="border-left:2px solid var(--teal);font-size:.75rem">'
        f'<div style="color:#dce8f5">{html.escape(str(p["prompt"])[:200])}</div>'
        f'<div style="color:#6a8aaa;font-size:.65rem;margin-top:2px">{html.escape(str(p.get("why_effective","")))}</div></div>'
        for p in all_prompts[:10]
    )

    # ── Aggregate anti-patterns ──
    all_anti = []
    for r in rows:
        for a in _jl(r["anti_patterns"]):
            if isinstance(a, dict) and a.get("pattern"):
                all_anti.append(a)
    anti_html = "".join(
        f'<div class="card" style="border-left:2px solid var(--red);font-size:.75rem">'
        f'<div style="color:#D85A30">{html.escape(str(a["pattern"]))}</div>'
        f'<div style="color:#6a8aaa;font-size:.65rem">Fix: {html.escape(str(a.get("fix","")))}</div></div>'
        for a in all_anti[:10]
    )

    # ── Aggregate playbooks ──
    playbooks_html = ""
    for r in rows:
        pb = r.get("playbook") or ""
        if pb and len(pb) > 10:
            playbooks_html += (
                f'<div class="card" style="font-size:.75rem">'
                f'<div style="color:#378ADD;font-size:.65rem;margin-bottom:4px">{html.escape(r["session_type"] or "session")} — {html.escape(str(r["session_id"])[:8])}</div>'
                f'<pre style="color:#a1b0c0;white-space:pre-wrap;margin:0;font-size:.7rem">{html.escape(pb)}</pre></div>'
            )

    # ── Aggregate reusable patterns ──
    all_patterns = []
    for r in rows:
        for p in _jl(r["reusable_patterns"]):
            if isinstance(p, dict) and p.get("pattern"):
                all_patterns.append(p)
    patterns_html = "".join(
        f'<div class="rule" style="border-color:var(--blue)">'
        f'<div style="color:#dce8f5;font-size:.75rem">{html.escape(str(p["pattern"]))}</div>'
        f'<div style="color:#6a8aaa;font-size:.65rem">{html.escape(str(p.get("context","")))}</div></div>'
        for p in all_patterns[:10]
    )

    # ── Knowledge domain cloud ──
    domain_counts = {}
    for r in rows:
        for d in _jl(r["knowledge_domains"]):
            if isinstance(d, str):
                domain_counts[d] = domain_counts.get(d, 0) + 1
    sorted_domains = sorted(domain_counts.items(), key=lambda x: -x[1])
    domain_html = " ".join(
        f'<span style="font-size:{min(0.6 + count * 0.08, 1.2):.2f}rem;padding:2px 8px;border-radius:10px;'
        f'border:1px solid #378ADD;color:#378ADD;margin:2px;display:inline-block">{html.escape(d)} ({count})</span>'
        for d, count in sorted_domains[:25]
    )

    content = f"""
    <h3>CLAUDE.md Rules ({len(all_rules)} distilled)</h3>
    {rules_html or "<p style='color:#2e4460'>No rules yet.</p>"}

    <h3 style="margin-top:1rem">Effective Prompts</h3>
    {prompts_html or "<p style='color:#2e4460'>No effective prompts captured yet.</p>"}

    <h3 style="margin-top:1rem">Anti-Patterns to Avoid</h3>
    {anti_html or "<p style='color:#2e4460'>No anti-patterns detected yet.</p>"}

    <h3 style="margin-top:1rem">Playbooks</h3>
    {playbooks_html or "<p style='color:#2e4460'>No playbooks extracted yet.</p>"}

    <h3 style="margin-top:1rem">Reusable Patterns</h3>
    {patterns_html or "<p style='color:#2e4460'>No reusable patterns yet.</p>"}

    <h3 style="margin-top:1rem">Knowledge Domains</h3>
    <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:.5rem">
    {domain_html or "<p style='color:#2e4460'>No domains yet.</p>"}
    </div>"""
    return shell("Learnings", content, "Learnings")


@app.route("/settings", methods=["GET", "POST"])
def settings():
    c = load_cfg()
    if request.method == "POST":
        new_provider = request.form.get("provider", c.get("model", {}).get("provider", "anthropic"))
        
        # Telemetry Swarm Cloud Payload
        s3_bucket = request.form.get("s3_bucket", "")
        s3_region = request.form.get("s3_region", "")
        aws_access = request.form.get("aws_access", "")
        aws_secret = request.form.get("aws_secret", "")
        is_managed = request.form.get("is_managed", "false")
        director_mode = request.form.get("director_mode", "false")
        
        text = CFG.read_text() if CFG.exists() else ""
        text = re.sub(r'provider\s*=\s*"[^"]*"', f'provider = "{new_provider}"', text)
        
        # Matrix to robustly write S3 values natively into the local TOML configurations
        if "[swarm]" not in text:
            text += f"\n\n[swarm]\ntype = 'byok_s3'\nbucket = '{s3_bucket}'\nregion = '{s3_region}'\ndirector_mode = {director_mode}\n\n[aws]\naccess_key = '{aws_access}'\nsecret_key = '{aws_secret}'\n"
        else:
            text = re.sub(r'bucket\s*=\s*"[^"]*"', f'bucket = "{s3_bucket}"', text)
            text = re.sub(r'region\s*=\s*"[^"]*"', f'region = "{s3_region}"', text)
            text = re.sub(r'director_mode\s*=\s*(true|false)', f'director_mode = {director_mode}', text)
            text = re.sub(r'access_key\s*=\s*"[^"]*"', f'access_key = "{aws_access}"', text)
            text = re.sub(r'secret_key\s*=\s*"[^"]*"', f'secret_key = "{aws_secret}"', text)

        # Simulate Provisioning SLA logic natively
        if is_managed == "true":
            if "type = 'byok_s3'" in text:
                text = text.replace("type = 'byok_s3'", "type = 'kernora_managed'")
            
        CFG.write_text(text)
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
        <div style="font-size:0.65rem; color:#888780; margin-bottom: 6px;">How to generate securely: AWS Console &rarr; IAM &rarr; Users &rarr; Create Access Key.</div>
        <div style="display: flex; gap: 10px; margin-bottom: 10px;">
          <input type="text" name="aws_access" placeholder="Access Key ID" style="width:50%;">
          <input type="password" name="aws_secret" placeholder="Secret Access Key" style="width:50%; background:#111820; border:1px solid #1e2d45; color:#dce8f5; border-radius:4px; padding:3px 8px;">
        </div>
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

    <div class="privacy">
      &#9678; BYOK mode &mdash; zero bytes sent to Kernora.<br>
      Your transcripts, your secret keys, your machine. Kernora provides execution code only.
    </div>"""
    return shell("Settings", content, "Settings")


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
    label = "LLM reachable" if s["ok"] else "LLM unreachable"
    dot = f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};margin-right:4px;vertical-align:middle;"></span>'
    tip = html.escape(f'{s["provider"]} · {s["model"] or "?"} · {s["reason"]}')
    return (
        f'<span id="llm-status" title="{tip}" '
        f'hx-get="/api/llm-status" hx-trigger="every 30s" hx-swap="outerHTML" '
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

    llm_color = "#1D9E75" if llm["ok"] else "#e05c5c"
    llm_label = f'{llm["provider"]} · {llm["model"] or "?"}'
    llm_reason = html.escape(llm["reason"])

    item_style = "display:flex;align-items:center;gap:6px;font-size:.7rem;"

    items = f"""
      <div style="{item_style}" title="{html.escape(llm_label + ' · ' + llm['reason'])}">
        {_dot(llm["ok"])}
        <span style="color:{'#dce8f5' if llm['ok'] else '#e05c5c'};">LLM</span>
        <span style="color:#7a8a9e;">{html.escape(llm_label)}</span>
        <span style="color:{'#1D9E75' if llm['ok'] else '#e05c5c'};font-size:.65rem;">({llm_reason})</span>
      </div>
      <span style="color:#1e2d45;">|</span>
      <div style="{item_style}" title="{html.escape(daemon_tip)}">
        {_dot(daemon_ok)}
        <span style="color:{'#dce8f5' if daemon_ok else '#e05c5c'};">{daemon_label}</span>
      </div>
      <span style="color:#1e2d45;">|</span>
      <div style="{item_style}" title="{html.escape(str(db_path))}">
        {_dot(db_ok)}
        <span style="color:{'#dce8f5' if db_ok else '#e05c5c'};">{db_label}</span>
      </div>
      <span style="color:#1e2d45;">|</span>
      <div style="{item_style}">
        {_dot(True)}
        <span style="color:#7a8a9e;">Dashboard · localhost:2742</span>
      </div>
    """

    return f"""<div id="status-bar"
      hx-get="/api/status-bar" hx-trigger="every 30s" hx-swap="outerHTML"
      style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;
             padding:7px 18px;background:#050c14;border-bottom:1px solid #0f1e2e;
             font-family:monospace;">
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
    return {"status": "ok", "sessions": total, "analyzed": analyzed,
            "llm_reachable": s["ok"], "llm_provider": s["provider"], "llm_reason": s["reason"]}


if __name__ == "__main__":
    c = load_cfg()
    port = c.get("dashboard", {}).get("port", 2742)
    print(f"[kernora] dashboard at http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
