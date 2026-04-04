#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""
Notification layer.
Chain: macOS osascript → Linux notify-send → Discord webhook → stderr.
Never raises. Never crashes the daemon.

Config (optional, ~/.kernora/config.toml):
  [notifications]
  method = "auto"  # "auto" | "macos" | "linux" | "discord" | "none"
  discord_webhook = ""
"""
import json
import os
import subprocess
import sys


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


def _try_macos(title: str, body: str) -> bool:
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{_escape(body[:200])}" '
            f'with title "{_escape(title)}" subtitle "Kernora"'
        ], check=True, capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _try_linux(title: str, body: str) -> bool:
    try:
        subprocess.run(
            ["notify-send", title, body[:200]],
            check=True, capture_output=True, timeout=5
        )
        return True
    except Exception:
        return False


def _try_discord(title: str, body: str) -> bool:
    webhook = os.environ.get("KERNORA_DISCORD_WEBHOOK", "")
    if not webhook:
        try:
            import sys
            if sys.version_info >= (3, 11):
                import tomllib
            else:
                try:
                    import tomllib
                except ImportError:
                    try:
                        import tomli as tomllib  # type: ignore
                    except ImportError:
                        return False
            from pathlib import Path
            p = Path.home() / ".kernora" / "config.toml"
            if p.exists():
                with open(p, "rb") as f:
                    cfg = tomllib.load(f)
                webhook = cfg.get("notifications", {}).get("discord_webhook", "")
        except Exception:
            pass
    if not webhook:
        return False
    try:
        import urllib.request
        payload = json.dumps({"content": f"**{title}**\n{body[:500]}"}).encode()
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def notify(title: str, body: str):
    """Send notification via best available method. Never raises."""
    method = os.environ.get("KERNORA_NOTIFY", "auto").lower()
    if method == "none":
        return
    if method in ("auto", "macos"):
        if _try_macos(title, body):
            return
    if method in ("auto", "linux"):
        if _try_linux(title, body):
            return
    if method in ("auto", "discord"):
        if _try_discord(title, body):
            return
    print(f"[kernora] {title}: {body}", file=sys.stderr)
