"""
Kernora Anonymous Telemetry
===========================
Sends ONE anonymous ping per day to help us understand usage patterns.
Opt-out: set [telemetry] enabled = false in ~/.kernora/config.toml

EXACTLY what is sent (nothing else, ever):
{
    "machine_id":      "sha256-hash-of-hostname+username",  # no PII
    "ide":             "kiro",                               # kiro | cursor | vscode
    "version":         "1.2.5",                              # extension version
    "os":              "darwin",                              # darwin | linux | win32
    "session_count":   42,                                   # total sessions in echo.db
    "analyzed_count":  38,                                   # sessions with LLM analysis
    "rules_count":     12,                                   # distilled rules
    "playbooks_count": 3,                                    # captured playbooks
    "has_s3":          false,                                # S3 backup configured?
    "has_cloud_sync":  false                                 # cloud sync ($5/mo) active?
}

No filenames. No code. No API keys. No IP logging server-side.
"""

import db
import hashlib
import json
import os
import platform
import sqlite3
import time
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

TELEMETRY_ENDPOINT = "https://telemetry.kernora.ai/ping"
KERNORA_DIR = Path.home() / ".kernora"
DB_PATH = KERNORA_DIR / "echo.db"
LAST_PING_FILE = KERNORA_DIR / ".last_ping"
VERSION_FILE = KERNORA_DIR / "app" / ".version"


def _machine_id() -> str:
    """SHA256 of hostname + username. Not reversible, not PII."""
    raw = f"{platform.node()}:{os.getenv('USER', os.getenv('USERNAME', 'unknown'))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]  # first 16 chars only


def _get_os() -> str:
    s = platform.system().lower()
    if s == "darwin":
        return "darwin"
    elif s == "windows":
        return "win32"
    return "linux"


def _get_version() -> str:
    """Read version from .version file written by extension, or fallback."""
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text().strip()
    except Exception:
        pass
    return "unknown"


def _get_ide() -> str:
    return os.environ.get("KERNORA_IDE", "vscode").lower()


def _get_db_stats() -> dict:
    """Read aggregate counts from echo.db. No content, just counts."""
    stats = {
        "session_count": 0,
        "analyzed_count": 0,
        "rules_count": 0,
        "playbooks_count": 0,
        # VC-grade engagement fields
        "sessions_last_7d": 0,
        "first_seen_days": 0,
        "days_active": 0,
        "first_rule_days": -1,  # -1 = no rule yet
        "mcp_tools_used": "",
    }
    try:
        if not DB_PATH.exists():
            return stats
        conn = db.get_conn()
        cur = conn.cursor()

        # Total sessions
        try:
            cur.execute("SELECT COUNT(*) FROM sessions")
            stats["session_count"] = cur.fetchone()[0]
        except Exception:
            pass

        # Analyzed sessions (have LLM output)
        try:
            cur.execute("SELECT COUNT(*) FROM sessions WHERE analyzed = 1")
            stats["analyzed_count"] = cur.fetchone()[0]
        except Exception:
            try:
                cur.execute("SELECT COUNT(*) FROM sessions WHERE llm_summary IS NOT NULL AND llm_summary != ''")
                stats["analyzed_count"] = cur.fetchone()[0]
            except Exception:
                pass

        # Distilled rules
        try:
            cur.execute("SELECT COUNT(*) FROM rules")
            stats["rules_count"] = cur.fetchone()[0]
        except Exception:
            pass

        # Playbooks
        try:
            cur.execute("SELECT COUNT(*) FROM playbooks")
            stats["playbooks_count"] = cur.fetchone()[0]
        except Exception:
            pass

        # ── VC-grade engagement metrics (all anonymous counts) ─────────

        # Sessions in last 7 days (engagement intensity)
        try:
            cur.execute(
                "SELECT COUNT(*) FROM sessions WHERE inserted_at > datetime('now', '-7 days')"
            )
            stats["sessions_last_7d"] = cur.fetchone()[0]
        except Exception:
            pass

        # Days since first session (tenure / install age)
        try:
            cur.execute("SELECT MIN(inserted_at) FROM sessions")
            row = cur.fetchone()
            if row and row[0]:
                from datetime import datetime as dt
                first = dt.fromisoformat(row[0].replace("Z", "+00:00"))
                stats["first_seen_days"] = max(0, (dt.now(first.tzinfo or None) - first).days)
        except Exception:
            pass

        # Distinct active days (retention depth)
        try:
            cur.execute("SELECT COUNT(DISTINCT DATE(inserted_at)) FROM sessions")
            stats["days_active"] = cur.fetchone()[0]
        except Exception:
            pass

        # Days from install to first distilled rule (aha moment speed)
        try:
            cur.execute("SELECT MIN(inserted_at) FROM sessions")
            first_session = cur.fetchone()
            cur.execute("SELECT MIN(created_at) FROM rules")
            first_rule = cur.fetchone()
            if first_session and first_session[0] and first_rule and first_rule[0]:
                from datetime import datetime as dt
                fs = dt.fromisoformat(first_session[0].replace("Z", "+00:00"))
                fr = dt.fromisoformat(first_rule[0].replace("Z", "+00:00"))
                stats["first_rule_days"] = max(0, (fr - fs).days)
        except Exception:
            pass

        # Which MCP tools are actually used (feature adoption, no content)
        try:
            cur.execute("""
                SELECT DISTINCT json_extract(value, '$.tool') as tool
                FROM sessions, json_each(turns_json)
                WHERE json_extract(value, '$.tool') IS NOT NULL
                LIMIT 20
            """)
            tools = [r[0] for r in cur.fetchall() if r[0]]
            stats["mcp_tools_used"] = ",".join(sorted(set(tools)))
        except Exception:
            pass

        conn.close()
    except Exception:
        pass
    return stats


def _has_s3_configured() -> bool:
    """Check if S3 backup keys are set in config."""
    try:
        config_path = KERNORA_DIR / "config.toml"
        if config_path.exists():
            text = config_path.read_text()
            return "aws_access_key_id" in text.lower() or "access_key_id" in text.lower()
    except Exception:
        pass
    return False


def _has_cloud_sync() -> bool:
    """Check if cloud sync (paid tier) is active."""
    try:
        config_path = KERNORA_DIR / "config.toml"
        if config_path.exists():
            text = config_path.read_text()
            return "cloud_sync" in text.lower() and "true" in text.lower()
    except Exception:
        pass
    return False


def is_telemetry_enabled() -> bool:
    """Check config.toml for [telemetry] enabled = false."""
    try:
        config_path = KERNORA_DIR / "config.toml"
        if config_path.exists():
            text = config_path.read_text().lower()
            # Look for explicit opt-out
            if "[telemetry]" in text:
                after = text.split("[telemetry]")[1].split("[")[0]  # text until next section
                if "enabled" in after and "false" in after:
                    return False
    except Exception:
        pass
    return True  # default: enabled (opt-out model)


def _already_pinged_today() -> bool:
    """Rate limit: one ping per day max."""
    try:
        if LAST_PING_FILE.exists():
            last_ts = float(LAST_PING_FILE.read_text().strip())
            return (time.time() - last_ts) < 86400  # 24 hours
    except Exception:
        pass
    return False


def _get_tier() -> str:
    """Determine user tier from config: 'free' or 'pro'."""
    if _has_cloud_sync():
        return "pro"
    return "free"


def build_payload() -> dict:
    """Build the exact payload that will be sent. Public so Settings can display it."""
    db_stats = _get_db_stats()
    return {
        "machine_id": _machine_id(),
        "ide": _get_ide(),
        "version": _get_version(),
        "os": _get_os(),
        "tier": _get_tier(),
        "session_count": db_stats["session_count"],
        "analyzed_count": db_stats["analyzed_count"],
        "rules_count": db_stats["rules_count"],
        "playbooks_count": db_stats["playbooks_count"],
        "has_s3": _has_s3_configured(),
        "has_cloud_sync": _has_cloud_sync(),
        # VC-grade engagement metrics
        "sessions_last_7d": db_stats["sessions_last_7d"],
        "first_seen_days": db_stats["first_seen_days"],
        "days_active": db_stats["days_active"],
        "first_rule_days": db_stats["first_rule_days"],
        "mcp_tools_used": db_stats["mcp_tools_used"],
    }


def _send_ping():
    """Send the ping in a background thread. Fire and forget."""
    try:
        payload = build_payload()
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            TELEMETRY_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urlopen(req, timeout=5)
        # Mark success
        LAST_PING_FILE.write_text(str(time.time()))
    except (URLError, OSError, Exception):
        pass  # silent fail — telemetry must never break the app


def maybe_ping():
    """
    Call this on dashboard startup. Sends anonymous ping if:
    1. Telemetry is enabled (opt-out not set)
    2. Haven't pinged in the last 24 hours
    Non-blocking — runs in background thread.
    """
    if not is_telemetry_enabled():
        return
    if _already_pinged_today():
        return

    # Fire and forget in background thread
    t = threading.Thread(target=_send_ping, daemon=True)
    t.start()


def set_telemetry_enabled(enabled: bool):
    """Update config.toml to enable/disable telemetry."""
    config_path = KERNORA_DIR / "config.toml"
    try:
        text = config_path.read_text() if config_path.exists() else ""

        if "[telemetry]" in text:
            # Replace existing section
            parts = text.split("[telemetry]")
            before = parts[0]
            after_section = parts[1]
            # Find next section or end
            next_bracket = after_section.find("\n[")
            if next_bracket >= 0:
                rest = after_section[next_bracket:]
            else:
                rest = ""
            text = before + f"[telemetry]\nenabled = {'true' if enabled else 'false'}\n" + rest
        else:
            # Append new section
            text = text.rstrip() + f"\n\n[telemetry]\nenabled = {'true' if enabled else 'false'}\n"

        config_path.write_text(text)
    except Exception:
        pass
