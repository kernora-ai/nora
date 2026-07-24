#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
"""
Standalone CLI for Kernora. Works without VS Code / Kiro app.

Usage:
  kernora install    — first-time setup (venv, deps, db, hooks, symlink)
  kernora generate   — emit AI context files for the current project
  kernora start      — start the dashboard daemon
  kernora stop       — stop the dashboard daemon
  kernora restart    — stop + start
  kernora status     — check health (dashboard, db, steering, hooks)
  kernora help       — show this help

Aliases:
  kernora init       — deprecated alias for `kernora install`

Install:
  After running `kernora install`, a wrapper is created at ~/.local/bin/kernora.
  Or run directly: python3 ~/.kernora/app/kernora_cli.py <command>
"""
import db
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

KERNORA_DIR = Path.home() / ".kernora"
APP_DIR = KERNORA_DIR / "app"
VENV_DIR = KERNORA_DIR / "venv"
PYTHON = VENV_DIR / "bin" / "python3"
PIP = VENV_DIR / "bin" / "pip"
DB_PATH = KERNORA_DIR / "echo.db"
PID_FILE = KERNORA_DIR / "dashboard.pid"
LOG_DIR = KERNORA_DIR / "logs"
CONFIG_PATH = KERNORA_DIR / "config.toml"
STEERING_DIR = Path.home() / ".kiro" / "steering"
BIN_DIR = Path.home() / ".local" / "bin"
SYMLINK_PATH = BIN_DIR / "kernora"

# ── File-walk skip lists (BATCH-004 lf004 — hoisted from cmd_pii_scan) ────────
# Shared by cmd_pii_scan AND nora_scan MCP tool. Module-level so that
# `from kernora_cli import _SKIP_EXT, _SKIP_DIR` works without invoking
# the function. Binary / generated / vendored content is dropped from walks.
_SKIP_EXT = {
    ".db", ".sqlite", ".sqlite3", ".db-journal", ".db-wal", ".db-shm",
    ".vsix", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar",
    ".gz", ".tgz", ".bz2", ".7z", ".mp3", ".mp4", ".mov", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".pyc", ".so", ".dylib",
    ".dll", ".class", ".jar",
}
_SKIP_DIR = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".build",
    "dist", "build", ".hypothesis", ".pytest_cache",
}

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _print(icon: str, msg: str):
    print(f"  {icon} {msg}")


def _ok(msg: str):
    _print(f"{GREEN}✓{RESET}", msg)


def _warn(msg: str):
    _print(f"{YELLOW}!{RESET}", msg)


def _err(msg: str):
    _print(f"{RED}✗{RESET}", msg)


def _info(msg: str):
    _print(f"{CYAN}→{RESET}", msg)


def _header(msg: str):
    print(f"\n{BOLD}{msg}{RESET}")


# ── Init (DEPRECATED alias for install) ──────────────────────────────────────

def _is_already_installed() -> bool:
    """Detect whether the machine-level bootstrap has already run.

    All three signals must be present:
      - ~/.kernora/venv/bin/python3  (venv exists)
      - ~/.kernora/echo.db           (DB initialized)
      - ~/.local/bin/kernora         (CLI wrapper installed)
    """
    return PYTHON.exists() and DB_PATH.exists() and SYMLINK_PATH.exists()


def _print_install_status_brief():
    """One-line health snapshot for use after an idempotent-install short-circuit."""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=2.0)
        sess_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        sess_count = "?"
    steering_count = (
        len(list(STEERING_DIR.glob("*.md"))) if STEERING_DIR.exists() else 0
    )
    _info(
        f"DB: {sess_count} sessions · steering: {steering_count} files · "
        f"venv: {VENV_DIR}"
    )


def cmd_init():
    """[DEPRECATED] Alias for `kernora install` — kept for muscle-memory back-compat.

    If the machine is already installed, short-circuits with a status summary
    instead of re-running the full setup (B3 fix). Otherwise delegates to
    `cmd_install` which is idempotent and handles symlinked dev layouts.

    BUG-A (v2.2.1): `init` is a reserved keyword in Claude Code — typing
    `nora init` in an AI chat panel fires Claude Code's built-in /init skill
    (which writes its own CLAUDE.md). The deprecation message now points
    users to `kernora bake` (AI-friendly verb) in addition to the legacy
    `kernora install` / `kernora generate` split.
    """
    if _is_already_installed():
        _header("Kernora — already installed")
        _print_install_status_brief()
        print(f"\n  Re-emit AI context for this project: {CYAN}kernora generate{RESET}  (or {CYAN}nora generate{RESET} inside Claude Code / Cursor chat)")
        print(f"  Force a full reinstall:              {CYAN}kernora install --force{RESET}")
        print(f"  Inspect health:                      {CYAN}kernora status{RESET}")
        print()
        _warn("`kernora init` is deprecated. Use `kernora install` (once per machine) + `kernora generate` (every emit).")
        _warn("In Claude Code / Cursor chat panels, type `nora generate` — `init` collides with Claude Code's /init skill.")
        return 0

    _warn("`kernora init` is deprecated. Delegating to `kernora install`…")
    rc = cmd_install()
    # First-run convenience: also emit steering so the old `init` UX still
    # produces the "AI knows my project" payoff.
    try:
        cmd_generate(quiet=True)
        _ok("AI context files emitted. Next time, run `kernora generate` (or `nora generate` in chat).")
    except Exception as e:
        _warn(f"Steering emit skipped: {e}. Run `kernora generate` later to retry.")
    return rc


def _install_cli_wrapper():
    """Create the ~/.local/bin/kernora wrapper that activates the venv and runs the CLI.

    A wrapper (not a symlink) is used so that `which kernora` still works
    if the venv path changes. Idempotent; safe to re-run.
    """
    cli_script = APP_DIR / "kernora_cli.py"
    if not cli_script.exists():
        # Source-install path: copy self into APP_DIR. B1 tolerance for
        # symlinked layouts where src and dest resolve to the same inode.
        try:
            shutil.copy2(__file__, cli_script)
        except shutil.SameFileError:
            pass  # already in place via symlink
        cli_script.chmod(0o755)

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    SYMLINK_PATH.write_text(f"""#!/bin/sh
exec "{PYTHON}" "{cli_script}" "$@"
""")
    SYMLINK_PATH.chmod(0o755)
    _ok(f"CLI installed at {SYMLINK_PATH}")

    path_dirs = os.environ.get("PATH", "").split(":")
    if str(BIN_DIR) not in path_dirs:
        _warn(f"Add to your shell profile: export PATH=\"$HOME/.local/bin:$PATH\"")


# Back-compat shim — old code or external callers may still import this name.
_install_symlink = _install_cli_wrapper


# ── Start / Stop / Restart ────────────────────────────────────────────────────

def _get_dashboard_pid() -> int | None:
    """Get running dashboard PID, or None."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            PID_FILE.unlink(missing_ok=True)
    # Fallback: check by process name
    try:
        result = subprocess.run(
            ["pgrep", "-f", "kernora.*dashboard.py"],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split("\n")
        pids = [int(p) for p in pids if p.strip()]
        if pids:
            return pids[0]
    except Exception:
        pass
    return None


def cmd_start():
    """Start the dashboard daemon."""
    # BATCH-002: Lite mode has no daemon/dashboard. Use `kernora dashboard --once`
    # for a one-shot spinup if you need the dashboard temporarily.
    try:
        import kernora_mode as _km
        if _km.is_lite():
            _info("Lite mode — daemon/dashboard not started.")
            _info("Run `kernora dashboard --once` for a temporary dashboard, or")
            _info("`kernora config set mode=companion` to enable the always-on daemon.")
            return
    except Exception:
        pass
    pid = _get_dashboard_pid()
    if pid:
        _ok(f"Dashboard already running (PID {pid})")
        _info("http://localhost:2742")
        return

    if not PYTHON.exists():
        _err("Not initialized. Run: kernora init")
        sys.exit(1)

    dashboard = APP_DIR / "dashboard.py"
    if not dashboard.exists():
        _err(f"Dashboard not found at {dashboard}")
        sys.exit(1)

    # Detect IDE context
    ide = "cli"
    app_name = os.environ.get("TERM_PROGRAM", "").lower()
    if "kiro" in app_name:
        ide = "kiro"
    elif "cursor" in app_name:
        ide = "cursor"
    elif "antigravity" in app_name or os.environ.get("ANTIGRAVITY_AGENT"):
        ide = "antigravity"

    _info("Starting dashboard...")
    log_file = LOG_DIR / "dashboard.log"
    with open(log_file, "a") as log:
        proc = subprocess.Popen(
            [str(PYTHON), str(dashboard)],
            env={**os.environ, "PYTHONUNBUFFERED": "1", "KERNORA_IDE": ide},
            stdout=log, stderr=log,
            start_new_session=True,  # Detach from terminal
        )
    PID_FILE.write_text(str(proc.pid))
    time.sleep(1)

    # Verify it's running
    if _get_dashboard_pid():
        _ok(f"Dashboard started (PID {proc.pid})")
        _info("http://localhost:2742")
    else:
        _err("Dashboard failed to start. Check: ~/.kernora/logs/dashboard.log")


def cmd_stop():
    """Stop the dashboard daemon."""
    pid = _get_dashboard_pid()
    if not pid:
        _info("Dashboard not running")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)  # Force if still alive
        except ProcessLookupError:
            pass
        _ok(f"Dashboard stopped (was PID {pid})")
    except Exception as e:
        _err(f"Failed to stop PID {pid}: {e}")

    PID_FILE.unlink(missing_ok=True)

    # Also kill any strays
    try:
        subprocess.run(
            ["pkill", "-f", "kernora.*dashboard.py"],
            capture_output=True
        )
    except Exception:
        pass


def cmd_restart():
    """Stop + start."""
    # BATCH-002: in Lite mode, restart is a no-op informational message.
    try:
        import kernora_mode as _km
        if _km.is_lite():
            _info("Lite mode — nothing to restart (no daemon, no dashboard).")
            return
    except Exception:
        pass
    cmd_stop()
    time.sleep(0.5)
    cmd_start()


# ── BYOM Ollama proxy (#270) ──────────────────────────────────────────────────
# Anthropic↔Ollama translator that lets Claude Code (or any Anthropic-API tool)
# route through localhost:4000 to a local Ollama model. Validated 2026-04-29
# across hermes3:8b (recommended), mistral-nemo:12b, qwen3:4b/8b/9b families.
# Spike origin: spike/nora_ollama_proxy.py — moved to root at root/nora_ollama_proxy.py.

PROXY_PID_FILE = KERNORA_DIR / "proxy.pid"
PROXY_CONFIG_PATH = KERNORA_DIR / "proxy.json"
PROXY_LAUNCHD_LABEL = "ai.kernora.proxy"
PROXY_LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{PROXY_LAUNCHD_LABEL}.plist"
PROXY_DEFAULT_MODEL = "hermes3:8b"   # validated winner on M1 Pro 16GB
PROXY_DEFAULT_PORT = 4000


def _get_proxy_pid():
    """Read proxy PID file; return None if not running."""
    if not PROXY_PID_FILE.exists():
        return None
    try:
        pid = int(PROXY_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 just checks if alive
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        PROXY_PID_FILE.unlink(missing_ok=True)
        return None


def _proxy_load_config():
    """Read ~/.kernora/proxy.json. Returns dict with model + port + mlx_adapter."""
    if PROXY_CONFIG_PATH.exists():
        try:
            return json.loads(PROXY_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {
        "model": PROXY_DEFAULT_MODEL,
        "port": PROXY_DEFAULT_PORT,
        "mlx_adapter": "",
    }


def _proxy_save_config(model: str, port: int, mlx_adapter: str = ""):
    """Persist proxy config. mlx_adapter="" disables the MLX route on next start.

    Track C0 §10.H2: persisting mlx_adapter is what lets `_proxy_install_launchd`
    find it later when writing the plist.
    """
    PROXY_CONFIG_PATH.write_text(json.dumps({
        "model": model,
        "port": port,
        "mlx_adapter": mlx_adapter,
    }, indent=2))


def cmd_proxy():
    """BYOM Ollama proxy — Anthropic↔Ollama translator for Claude Code etc.

    Usage:
      kernora proxy start [--model MODEL] [--port PORT] [--mlx-adapter PATH]
      kernora proxy stop
      kernora proxy status
      kernora proxy restart [--model MODEL] [--port PORT] [--mlx-adapter PATH]
      kernora proxy install-launchd      # opt-in auto-start on login (macOS)
      kernora proxy uninstall-launchd

    Defaults: model=hermes3:8b, port=4000. Override with --model / --port.
    Config persists in ~/.kernora/proxy.json.

    --mlx-adapter PATH (Track C0): mounts an additional OpenAI-compat route
      POST /v1/mlx/chat/completions backed by mlx-community/Hermes-3-Llama-3.1-8B-4bit
      + the LoRA adapter at PATH. Used by the v0.6-PRO desktop chat for
      factbook-grounded local inference. Path must be under $HOME and contain
      adapters.safetensors. Empty string disables the route. Env override:
      MLX_ADAPTER_PATH (also propagated into the launchd plist).

    After `kernora proxy start`, set these env vars in your shell:
      export ANTHROPIC_BASE_URL=http://localhost:<port>
      export ANTHROPIC_API_KEY=ollama
    Then run `claude` (or any Anthropic-API client) — requests will route
    through Ollama via the local proxy. Tool calls round-trip cleanly.

    Validated 2026-04-29 on M1 Pro 16GB across hermes3:8b (1.8s median),
    mistral-nemo:12b (2.4s), qwen3:4b (with /no_think auto-inject),
    qwen3:8b/9b, qwen2.5-coder:7b/14b (via tag-extraction).
    Skip: deepseek-r1, deepseek-coder-v2 (Ollama API rejects tools);
    granite3.1-dense (text-body bug, would need same tag-extract path).
    """
    args = sys.argv[2:]
    if not args or args[0] in ("-h", "--help"):
        print(cmd_proxy.__doc__)
        return 0

    sub = args[0]
    rest = args[1:]

    # Parse --model / --port from rest
    def _arg(name, default=None):
        try:
            i = rest.index(name)
            return rest[i + 1]
        except (ValueError, IndexError):
            return default

    if sub == "start":
        cfg = _proxy_load_config()
        model = _arg("--model", cfg.get("model", PROXY_DEFAULT_MODEL))
        port = int(_arg("--port", cfg.get("port", PROXY_DEFAULT_PORT)))
        # Track C0: --mlx-adapter PATH enables the OpenAI-compat MLX route.
        # Empty string disables it. Persisted to proxy.json so launchd picks up.
        mlx_adapter = _arg("--mlx-adapter", cfg.get("mlx_adapter", ""))
        return _proxy_start(model, port, mlx_adapter=mlx_adapter)
    elif sub == "stop":
        return _proxy_stop()
    elif sub == "status":
        return _proxy_status()
    elif sub == "restart":
        cfg = _proxy_load_config()
        model = _arg("--model", cfg.get("model", PROXY_DEFAULT_MODEL))
        port = int(_arg("--port", cfg.get("port", PROXY_DEFAULT_PORT)))
        mlx_adapter = _arg("--mlx-adapter", cfg.get("mlx_adapter", ""))
        _proxy_stop()
        time.sleep(0.5)
        return _proxy_start(model, port, mlx_adapter=mlx_adapter)
    elif sub == "install-launchd":
        return _proxy_install_launchd()
    elif sub == "uninstall-launchd":
        return _proxy_uninstall_launchd()
    else:
        _err(f"Unknown proxy subcommand: {sub}")
        print(cmd_proxy.__doc__)
        return 1


def _proxy_start(model: str, port: int, mlx_adapter: str = "") -> int:
    pid = _get_proxy_pid()
    if pid:
        _ok(f"Proxy already running (PID {pid})")
        _info(f"  http://localhost:{port}  ·  model: {model}")
        if mlx_adapter:
            _info(f"  (MLX adapter requested: {mlx_adapter} — restart proxy to pick it up)")
        return 0

    proxy_script = APP_DIR / "nora_ollama_proxy.py"
    if not proxy_script.exists():
        # Fall back to repo-checkout location if running pre-install
        repo_proxy = Path(__file__).resolve().parent / "nora_ollama_proxy.py"
        if repo_proxy.exists():
            proxy_script = repo_proxy
        else:
            _err(f"Proxy script not found at {proxy_script} or {repo_proxy}")
            _err("Run: bash sync.sh   (to propagate root → ~/.kernora/app/)")
            return 1

    if not PYTHON.exists():
        _err("Not initialized. Run: kernora init")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "proxy.log"
    err_file = LOG_DIR / "proxy.err"

    _info(f"Starting proxy on :{port} with model {model}...")
    if mlx_adapter:
        _info(f"  + MLX adapter route: {mlx_adapter} (loads in background, ~15s)")
    proxy_env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "OLLAMA_MODEL": model,
        "PROXY_PORT": str(port),
    }
    # Track C0 §10.L1: env var name MLX_ADAPTER_PATH locked.
    if mlx_adapter:
        proxy_env["MLX_ADAPTER_PATH"] = mlx_adapter
    with open(log_file, "a") as out, open(err_file, "a") as err:
        proc = subprocess.Popen(
            [str(PYTHON), str(proxy_script)],
            env=proxy_env,
            stdout=out, stderr=err,
            start_new_session=True,
        )
    PROXY_PID_FILE.write_text(str(proc.pid))
    _proxy_save_config(model, port, mlx_adapter=mlx_adapter)
    time.sleep(1)

    if _get_proxy_pid():
        _ok(f"Proxy started (PID {proc.pid})")
        print()
        _info("To use with Claude Code (or any Anthropic-API client):")
        print(f"  export ANTHROPIC_BASE_URL=http://localhost:{port}")
        print(f"  export ANTHROPIC_API_KEY=ollama")
        print(f"  claude")
        if mlx_adapter:
            print()
            _info("MLX adapter route (OpenAI-compat):")
            print(f"  POST http://localhost:{port}/v1/mlx/chat/completions")
        print()
        _info(f"  Logs: {log_file}")
        return 0
    else:
        _err("Proxy failed to start. Check: ~/.kernora/logs/proxy.err")
        return 1


def _proxy_stop() -> int:
    pid = _get_proxy_pid()
    if not pid:
        _info("Proxy not running")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _ok(f"Proxy stopped (was PID {pid})")
    except Exception as e:
        _err(f"Failed to stop PID {pid}: {e}")
        return 1
    PROXY_PID_FILE.unlink(missing_ok=True)
    # Kill any strays (e.g. backup proxy from a crashed restart)
    try:
        subprocess.run(["pkill", "-f", "nora_ollama_proxy.py"], capture_output=True)
    except Exception:
        pass
    return 0


def _proxy_status() -> int:
    pid = _get_proxy_pid()
    cfg = _proxy_load_config()
    if pid:
        _ok(f"Proxy running (PID {pid})")
        _info(f"  http://localhost:{cfg.get('port', PROXY_DEFAULT_PORT)}  ·  model: {cfg.get('model', PROXY_DEFAULT_MODEL)}")
        # Quick liveness probe — try /v1/models (returns model list when supported)
        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://localhost:{cfg.get('port', PROXY_DEFAULT_PORT)}/v1/models",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    _ok(f"  ↳ proxy responding on /v1/models")
        except Exception:
            # /v1/models may not be implemented by every proxy version;
            # fall back to TCP-port probe (PID liveness already confirmed above)
            pass
    else:
        _info("Proxy not running")
        _info(f"  Last config: model={cfg.get('model', PROXY_DEFAULT_MODEL)} port={cfg.get('port', PROXY_DEFAULT_PORT)}")
        _info(f"  Start: kernora proxy start")
    # Ollama backend probe
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            if r.status == 200:
                _ok("  ↳ Ollama backend responding (localhost:11434)")
    except Exception:
        _err("  ↳ Ollama backend NOT reachable on localhost:11434 — start Ollama first")
    return 0


def _proxy_install_launchd() -> int:
    """Install launchd plist so proxy auto-starts on login (macOS only)."""
    if sys.platform != "darwin":
        _err("launchd is macOS-only. On Linux/Windows, use systemd or Task Scheduler.")
        return 1

    cfg = _proxy_load_config()
    model = cfg.get("model", PROXY_DEFAULT_MODEL)
    port = cfg.get("port", PROXY_DEFAULT_PORT)
    # Track C0 §10.H2: propagate MLX adapter into the launchd plist so the
    # auto-started proxy at next login also serves the MLX route.
    mlx_adapter = (cfg.get("mlx_adapter") or "").strip()

    proxy_script = APP_DIR / "nora_ollama_proxy.py"
    if not proxy_script.exists():
        _err(f"Proxy script not found at {proxy_script}. Run: bash sync.sh")
        return 1

    mlx_env_block = (
        f"    <key>MLX_ADAPTER_PATH</key><string>{mlx_adapter}</string>\n"
        if mlx_adapter else ""
    )
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{PROXY_LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{PYTHON}</string>
    <string>{proxy_script}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>OLLAMA_MODEL</key><string>{model}</string>
    <key>PROXY_PORT</key><string>{port}</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
{mlx_env_block}  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{LOG_DIR}/proxy.log</string>
  <key>StandardErrorPath</key><string>{LOG_DIR}/proxy.err</string>
</dict>
</plist>
"""
    PROXY_LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    PROXY_LAUNCHD_PLIST.write_text(plist)
    _ok(f"Wrote {PROXY_LAUNCHD_PLIST}")

    # Load it
    try:
        # Unload first if already loaded (idempotent)
        subprocess.run(["launchctl", "unload", str(PROXY_LAUNCHD_PLIST)],
                       capture_output=True)
        subprocess.run(["launchctl", "load", str(PROXY_LAUNCHD_PLIST)],
                       check=True, capture_output=True)
        _ok(f"Loaded {PROXY_LAUNCHD_LABEL} into launchd")
        _info(f"  Proxy will auto-start on next login")
        _info(f"  Manage: launchctl {{load,unload}} {PROXY_LAUNCHD_PLIST}")
    except subprocess.CalledProcessError as e:
        _err(f"launchctl load failed: {e.stderr.decode() if e.stderr else e}")
        return 1
    return 0


def _proxy_uninstall_launchd() -> int:
    if not PROXY_LAUNCHD_PLIST.exists():
        _info(f"No launchd plist at {PROXY_LAUNCHD_PLIST}")
        return 0
    try:
        subprocess.run(["launchctl", "unload", str(PROXY_LAUNCHD_PLIST)],
                       capture_output=True)
    except Exception:
        pass
    PROXY_LAUNCHD_PLIST.unlink()
    _ok(f"Removed {PROXY_LAUNCHD_PLIST}")
    return 0


# ── Status ────────────────────────────────────────────────────────────────────

def cmd_status():
    """Show health status of all Kernora components."""
    _header("Kernora Status")

    # BATCH-002: Mode line at top so users can tell what's expected to be running.
    # BATCH-011 PE H3: when Companion mode is requested but no license,
    # surface "blocked: no license" instead of generic "not running".
    try:
        import kernora_mode as _km
        mode = _km.current_mode()
        tier = _km.current_tier()
        if mode == "lite":
            _ok("Mode: Lite · daemon: not running (Lite mode)")
        elif tier == "blocked":
            _err(f"Mode: {mode} · daemon: BLOCKED — no license")
            _warn("Run `kernora license` for help, or `kernora config set mode=lite` for free Lite mode")
        else:
            _ok(f"Mode: {mode} · tier: {tier}")
    except Exception:
        pass

    # Python venv
    if PYTHON.exists():
        _ok(f"Python venv: {VENV_DIR}")
    else:
        _err("Python venv: not found — run: kernora init")

    # Database
    if DB_PATH.exists():
        try:
            conn = db.get_conn()
            total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            analyzed = conn.execute("SELECT COUNT(*) FROM sessions WHERE analyzed=1").fetchone()[0]
            conn.close()
            _ok(f"Database: {total} sessions ({analyzed} analyzed)")
        except Exception as e:
            _warn(f"Database: exists but error — {e}")
    else:
        _warn("Database: not found — run: kernora init")

    # Dashboard
    pid = _get_dashboard_pid()
    try:
        import kernora_mode as _km
        _is_lite = _km.is_lite()
    except Exception:
        _is_lite = False
    if pid:
        _ok(f"Dashboard: running (PID {pid}) → http://localhost:2742")
    elif _is_lite:
        _info("Dashboard: not running (Lite mode) — `kernora dashboard --once` to spin up")
    else:
        _warn("Dashboard: not running — run: kernora start")

    # Steering files
    steering_files = list(STEERING_DIR.glob("kernora-*.md")) if STEERING_DIR.exists() else []
    if steering_files:
        _ok(f"Steering files: {len(steering_files)} in {STEERING_DIR}")
        for f in steering_files:
            size = f.stat().st_size
            _info(f"  {f.name} ({size:,} bytes)")
    else:
        _warn("Steering files: none — run: kernora generate")

    # Hooks
    hooks_dir = Path.home() / ".claude" / "hooks"
    hook_files = ["nora_context.py", "nora_session_start.py", "nora_precompact.py"]
    hooks_found = 0
    for hf in hook_files:
        if (hooks_dir / hf).exists() or (APP_DIR / hf).exists():
            hooks_found += 1
    if hooks_found == len(hook_files):
        _ok(f"Hooks: {hooks_found}/{len(hook_files)} installed")
    else:
        _warn(f"Hooks: {hooks_found}/{len(hook_files)} — some missing")

    # CLI
    if SYMLINK_PATH.exists():
        _ok(f"CLI: {SYMLINK_PATH}")
    else:
        _warn(f"CLI: not in PATH — run: kernora init")

    # Config
    if CONFIG_PATH.exists():
        _ok(f"Config: {CONFIG_PATH}")
    else:
        _warn("Config: not found")

    print()


# ── Generate ──────────────────────────────────────────────────────────────────

def cmd_generate(quiet: bool = False):
    """Regenerate steering files from current DB state.

    Shell verb. For the in-chat equivalent users type `nora generate`
    (MCP tool `nora_generate`) which calls the same generator.

    Reads from sys.argv:
      --preview   Show what WOULD be emitted (dry-run-ish); do not overwrite existing files.
      --json      Emit the receipt as JSON on stdout.

    Default behaviour writes files and then prints a receipt table: status
    (new | updated | unchanged), size, sha256 prefix, path. Addresses UX1
    (#43) — users previously could not tell which files were written or what
    was inside. `quiet=True` (used by `cmd_init`) suppresses the receipt.

    H3 fix (2026-04-23): serialized via an flock-backed file mutex.
    Post-commit hook runs `kernora generate --quiet` in the background;
    rapid-fire commits (rebase, squash) would otherwise spawn N concurrent
    generates that contend on echo.db + steering files. The lock makes
    later invocations wait for the active one.
    """
    preview = "--preview" in sys.argv
    json_out = "--json" in sys.argv

    # H3 fix: flock serialization. Never-blocking in --preview mode.
    import fcntl as _fcntl
    _lock_path = Path.home() / ".kernora" / "generate.lock"
    _lock_fh = None
    if not preview:
        try:
            _lock_path.parent.mkdir(parents=True, exist_ok=True)
            _lock_fh = open(_lock_path, "w")
            # Blocking lock — rapid successors wait rather than fail.
            _fcntl.flock(_lock_fh.fileno(), _fcntl.LOCK_EX)
        except Exception:
            _lock_fh = None  # lock unavailable → proceed (best-effort)

    sw = APP_DIR / "steering_writer.py"
    if not sw.exists():
        if not quiet:
            _err("steering_writer.py not found — run: kernora install")
        return

    python_cmd = str(PYTHON) if PYTHON.exists() else "python3"

    if preview:
        pre_paths = _list_known_steering_files()
        before = {str(p): _sha256_file(p)[:8] for p in pre_paths if p.exists()}
        _print_generate_receipt(pre_paths, before, preview=True, json_out=json_out)
        return

    try:
        pre_paths = _list_known_steering_files()
        before = {str(p): _sha256_file(p)[:8] for p in pre_paths if p.exists()}

        result = subprocess.run(
            [python_cmd, str(sw)],
            capture_output=True, text=True, timeout=15,
        )

        # steering_writer.py prints "[nora] Generated steering: <path> (...)"
        # — extract that list as the authoritative set of written files.
        written: list[Path] = []
        for line in (result.stdout or "").splitlines():
            if line.startswith("[nora] Generated steering: "):
                rest = line.split(": ", 1)[1]
                path_str = rest.split(" (", 1)[0].strip()
                written.append(Path(path_str))
        if not written:
            written = _list_known_steering_files()

        if not written:
            if not quiet:
                _warn("No steering files written (no data yet — that's OK).")
            return

        if quiet:
            _ok(f"Steering files generated ({len(written)} files)")
            return

        _print_generate_receipt(written, before, preview=False, json_out=json_out)
    except Exception as e:
        if not quiet:
            _err(f"Steering generation failed: {e}")
    finally:
        # Release H3 lock if acquired.
        if _lock_fh is not None:
            try:
                _fcntl.flock(_lock_fh.fileno(), _fcntl.LOCK_UN)
                _lock_fh.close()
            except Exception:
                pass


def _sha256_file(p: Path, limit_bytes: int = 8_000_000) -> str:
    """SHA-256 of file contents, bounded read. Returns hex digest."""
    import hashlib
    h = hashlib.sha256()
    try:
        with open(p, "rb") as fh:
            h.update(fh.read(limit_bytes))
    except OSError:
        return "missing"
    return h.hexdigest()


def _list_known_steering_files() -> list[Path]:
    """All paths the steering writer is known to touch (de-duplicated)."""
    seen: set[Path] = set()
    out: list[Path] = []
    buckets = [
        (STEERING_DIR, "kernora-*.md"),
        (STEERING_DIR, "kernora-*.json"),
        (STEERING_DIR, ".cursorrules"),
        (Path.home(), ".cursorrules"),
    ]
    for base, pat in buckets:
        if not base.exists():
            continue
        for p in sorted(base.glob(pat)):
            r = p.resolve()
            if r not in seen:
                seen.add(r)
                out.append(p)
    cwd_copilot = Path.cwd() / ".github" / "copilot-instructions.md"
    if cwd_copilot.exists() and cwd_copilot.resolve() not in seen:
        out.append(cwd_copilot)
    return out


def _print_generate_receipt(
    paths: list[Path],
    before: dict[str, str],
    preview: bool,
    json_out: bool,
) -> None:
    """UX1 (#43): compact receipt of what was (or would be) emitted."""
    import json as _json

    rows: list[dict] = []
    for p in paths:
        try:
            size = p.stat().st_size if p.exists() else 0
        except OSError:
            size = 0
        sha = _sha256_file(p)[:8] if p.exists() else "absent"
        prev = before.get(str(p))
        if preview:
            status = "would-emit" if prev is None else "would-update"
        elif prev is None:
            status = "new"
        elif prev != sha:
            status = "updated"
        else:
            status = "unchanged"
        rows.append({
            "path": str(p),
            "size": size,
            "sha256_8": sha,
            "status": status,
        })

    if json_out:
        print(_json.dumps(rows, indent=2))
        return

    title = "Preview — would emit" if preview else "Emitted AI context files"
    _header(title)
    print(f"  {'status':<12}  {'size':>8}  {'sha':<8}  path")
    print(f"  {'-'*12:<12}  {'-'*8:>8}  {'-'*8:<8}  {'-'*50}")
    for r in rows:
        status = r["status"]
        color = GREEN if status in ("new", "would-emit") else CYAN if status in ("updated", "would-update") else DIM
        print(f"  {color}{status:<12}{RESET}  {r['size']:>8,}  {r['sha256_8']:<8}  {r['path']}")
    print()
    print(f"  {DIM}Options: --preview (dry-run), --json (machine receipt).{RESET}")


# ── Help ──────────────────────────────────────────────────────────────────────

def cmd_help():
    """Show help."""
    print(f"""
{BOLD}kernora{RESET} — AI Work Intelligence CLI · v2.4.0 (2026-04-22)

{BOLD}Setup (one-time):{RESET}
  {CYAN}kernora install{RESET}             Install daemon, deps, CLI wrapper. Add {DIM}--on-prem{RESET} for Ollama-only / no telemetry.
  {CYAN}kernora hook-install{RESET}        Install git hooks. {DIM}--hooks pre|post|both{RESET} (default: both)
                              · pre-commit  → PII guardrail (blocks secrets in .nora/)
                              · post-commit → auto-regenerate steering files

{BOLD}Terminal chat:{RESET}
  {CYAN}kernora chat{RESET}                Open factbook-grounded chat REPL in the current terminal (SSH-safe)
  {CYAN}kernora chat -p "question"{RESET}  One-shot mode — answer + exit (pipe-safe)
  {CYAN}kernora chat --project X{RESET}    Explicit project · {DIM}--model <id>{RESET} to set model · /help in REPL

{BOLD}Daily intelligence:{RESET}
  {CYAN}kernora tour{RESET}                Interactive 9-step walkthrough — best place to start as a new user
  {CYAN}kernora generate{RESET}            Emit CLAUDE.md / .cursorrules / .github/copilot-instructions.md / .kiro/steering/
  {CYAN}kernora roi{RESET}                 ROI report (Lite reads JSONL; Companion runs LLM-graded SQLite ROI)
  {CYAN}kernora review-injections{RESET}   Accept/reject recent injection events (feeds effectiveness)
  {CYAN}kernora undo [retirement_id]{RESET}  List or restore retired facts in the 90-day soft-delete window

{BOLD}LLM-orchestrated workflows (BATCH-004/005 — runs in your IDE chat):{RESET}
  {CYAN}/nora scan <path>{RESET}           Walk artifacts → IDE LLM extracts → pending: array
  {CYAN}/nora learn{RESET}                 Distill candidates from a finished session transcript
  {CYAN}/nora consolidate{RESET}           Three-pass plan: dedup + supersession + retire-stale
  {CYAN}kernora pe-review --facts ID,...{RESET}  Multi-domain PE panel review (3 reviewers, paste prompts to LLM)
  {CYAN}kernora coe "<problem>"{RESET}            Interactive 5-Whys at the terminal (or pipe answers via stdin)

{BOLD}Project + factbook:{RESET}
  {CYAN}kernora migrate-to-git-native{RESET}  Export echo.db → .nora/*.md (one file per fact)
  {CYAN}kernora team-init{RESET}              Scaffold .nora/team.toml + GitHub Action template
  {CYAN}kernora team-report{RESET}            Build static .nora/team-report.md (snapshot · top-cited · weekly)
  {CYAN}kernora dashboard-init <org>{RESET}   In an empty repo: scaffold team-dashboard infra (Action + Pages)
  {CYAN}kernora factbook <subcmd>{RESET}      Factbook registry: list, search, install, publish, versions, unpublish
  {CYAN}kernora nora-push{RESET}              Commit + push .nora/ changes
  {DIM}Team collaboration via git: docs/LITE-COLLAB-VIA-GIT.md{RESET}

{BOLD}Investigation + safety:{RESET}
  {CYAN}kernora coe-last [N]{RESET}        Correction-of-Errors review of last N commits (deterministic, no LLM)
  {CYAN}kernora pii-scan <path>{RESET}     Scan files for secrets (exit 1 on critical/high — pre-commit calls this)
  {CYAN}kernora doctor{RESET}              Health check across all components
  {CYAN}kernora network-check{RESET}       AST audit — verify no network in hot path (on-prem requirement)
  {CYAN}kernora verify-artifact <path>{RESET}  Conformance gate — check an artifact against applicable factlets (exit 1 on FAIL)

{BOLD}Mode + daemon control:{RESET}
  {CYAN}kernora config show{RESET}                         Print full config + active Mode (lite|companion)
  {CYAN}kernora config set mode=lite|companion{RESET}      Flip engine mode · restart with `kernora restart`
  {CYAN}kernora dashboard --once{RESET}                    Lite-mode escape hatch — spin up dashboard for one session
  {CYAN}kernora start{RESET} · {CYAN}stop{RESET} · {CYAN}restart{RESET} · {CYAN}status{RESET}    Daemon control (Lite mode: start/restart are no-ops)

{BOLD}Database lifecycle:{RESET}
  {CYAN}kernora migrate{RESET}             Apply pending DB schema migrations (uses migrations/00NN_*.py)
  {CYAN}kernora archive{RESET} / {CYAN}restore{RESET} / {CYAN}purge{RESET}     Factbook lifecycle controls

{BOLD}Inside a Claude Code / Cursor / Kiro chat:{RESET}
  {CYAN}/nora help{RESET}         List all 18+ MCP tools
  {CYAN}/nora generate{RESET}     Same as `kernora generate` (routes via MCP — avoids /init skill collision)
  {CYAN}/nora pe-review{RESET}    Principal Engineer 4-tier code audit
  {CYAN}/nora coe [bug]{RESET}    Root cause investigation (5 whys)
  {CYAN}/nora retro{RESET}        Engineering retrospective
  {CYAN}/nora status{RESET}       Project status (aliases: /nora sofac, /nora engineering health)
  {CYAN}/nora roi{RESET}          Return-on-intelligence report

{BOLD}Paths:{RESET}
  Local cache:    ~/.kernora/echo.db
  Config:         ~/.kernora/config.toml
  Logs:           ~/.kernora/logs/{{daemon,agent_runtime,agent_safety}}/
  Optimized prompts: ~/.kernora/optimized_prompts/
  Project facts:  <project>/.nora/{{patterns,decisions,bugs,tenets,heuristics}}/*.md
  Project YAML:   <project>/.nora/kernora-factbook.yaml
  Dashboard:      http://localhost:2742
  Docs site:      https://kernora.ai

{DIM}For deeper docs: docs/NORA-ULTRAPLAN-APR-22-2026.md (architecture + roadmap),
docs/NORA-VS-MEM0.md (positioning), docs/NORA-ENTERPRISE-READINESS.md (compliance).{RESET}
""")


# ── Install (alias for init, calls kernora_installer) ─────────────────────────

def cmd_install():
    """Idempotent machine-level install: venv, deps, DB, hooks, CLI wrapper.

    Runs the shared kernora_installer (handles symlinked dev layouts, skips
    existing files, preserves user config). Then writes the ~/.local/bin/kernora
    wrapper so the command is available on $PATH.

    Re-runnable. Short-circuits inside the installer when everything is
    already current.

    Flags:
      --force      Re-run installer even when up-to-date
      --on-prem    Task #17 P4-A (2026-04-22): enterprise/regulated install path.
                   - Skips ANTHROPIC_API_KEY / XAI_API_KEY / GEMINI_API_KEY config prompts
                   - Defaults model.provider to 'ollama' (local-first)
                   - Runs AST network audit at install + prints report
                   - Writes ~/.kernora/config.toml with telemetry disabled
                   - Documents air-gap install path
    """
    force = "--force" in sys.argv
    on_prem = "--on-prem" in sys.argv

    # BATCH-002: surface mode at install time. Lite mode skips daemon launchd
    # plist + dashboard spawn (handled by daemon.py / dashboard.py self-skip).
    try:
        import kernora_mode as _km
        if _km.is_lite():
            print(f"  {DIM}[install] Lite mode — daemon launchd plist + dashboard spawn skipped.{RESET}")
            print(f"  {DIM}        Flip with `kernora config set mode=companion`.{RESET}\n")
    except Exception:
        pass

    if on_prem:
        _header("Kernora — on-prem install (Task #17 P4-A)")
        print(f"  {DIM}Local-first, BYOK-only, no telemetry. AST network audit will run.{RESET}\n")
        # 1. AST network audit — verify no network in hot path before install
        try:
            import kernora_network_audit
            audit_rc = kernora_network_audit.main(["check"])
            if audit_rc == 0:
                _ok("AST audit: no network calls in hot path — safe for on-prem")
            else:
                _warn(f"AST audit returned non-zero ({audit_rc}) — review before deploying")
        except Exception as e:
            _warn(f"AST audit skipped: {e}")
        # 2. Override model.provider to ollama via config.toml
        cfg_path = Path.home() / ".kernora" / "config.toml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        existing_cfg = cfg_path.read_text() if cfg_path.exists() else ""
        if "[model]" not in existing_cfg:
            existing_cfg += "\n[model]\nprovider = \"ollama\"\n"
        else:
            import re as _re
            existing_cfg = _re.sub(r'provider\s*=\s*"[^"]*"', 'provider = "ollama"', existing_cfg)
        if "[telemetry]" not in existing_cfg:
            existing_cfg += "\n[telemetry]\nenabled = false\n"
        if "[ollama]" not in existing_cfg:
            existing_cfg += '\n[ollama]\nmodel = "qwen2.5-coder:7b"\nbase_url = "http://localhost:11434"\n'
        try:
            cfg_path.write_text(existing_cfg)
            cfg_path.chmod(0o600)
            _ok(f"Wrote on-prem config to {cfg_path}")
        except Exception as e:
            _err(f"Could not write config: {e}")
            return 1
        print(f"  {DIM}On-prem mode: model.provider=ollama, telemetry.enabled=false{RESET}")
        print(f"  {DIM}Air-gap install: pre-bundle wheels in vendor/ then `pip install --no-index --find-links vendor/ -r requirements.txt`{RESET}\n")

    installer = APP_DIR / "kernora_installer.py"
    if not installer.exists():
        # Running from source tree — import directly
        src = Path(__file__).resolve().parent / "kernora_installer.py"
        if src.exists():
            sys.path.insert(0, str(src.parent))
    installer_args = []
    if force:
        installer_args.append("--force")
    try:
        import kernora_installer
        rc = kernora_installer.main(installer_args)
    except ImportError:
        # Fall back to running as subprocess
        py = str(PYTHON) if PYTHON.exists() else sys.executable
        script = APP_DIR / "kernora_installer.py"
        if not script.exists():
            script = Path(__file__).resolve().parent / "kernora_installer.py"
        rc = subprocess.call([py, str(script)] + installer_args)

    if rc == 0:
        try:
            _install_cli_wrapper()
        except Exception as e:
            _warn(f"CLI wrapper install skipped: {e}")
        if on_prem:
            print()
            _ok("On-prem install complete. Verify Ollama is running: `ollama serve`")
            _ok("Then test: `kernora doctor` — should show provider=ollama, no API keys configured")
    return rc


# ── Analyze ───────────────────────────────────────────────────────────────────

def cmd_analyze():
    """Invoke nora_analyze.py for a session or all sessions."""
    py = str(PYTHON) if PYTHON.exists() else sys.executable
    script = APP_DIR / "nora_analyze.py"
    if not script.exists():
        _err("nora_analyze.py not found — run: nora install")
        sys.exit(1)
    extra = sys.argv[2:]  # pass through --session ID or --all
    sys.exit(subprocess.call([py, str(script)] + extra))


# ── Config ────────────────────────────────────────────────────────────────────

def cmd_config():
    """Show or set kernora config — primarily the engine mode (lite|companion).

    Subcommands (BATCH-002):
      kernora config            — print full config.toml + current Mode line
      kernora config show       — same as no-arg
      kernora config set mode=lite|companion
                                — flip engine mode (writes [engine].mode)

    Mode resolution: env KERNORA_MODE > [engine].mode in config.toml > 'lite'.
    See kernora_mode.current_mode() for full precedence.
    """
    args = sys.argv[2:]
    # Default / `show` — print full config + active Mode line
    if not args or args[0] == "show":
        if CONFIG_PATH.exists():
            print(CONFIG_PATH.read_text())
        else:
            _warn(f"No config.toml at {CONFIG_PATH} — run: nora install")
        try:
            import kernora_mode as _km
            print(f"Mode: {_km.current_mode()}")
            configured = _km._read_config_mode()
            if _km.is_lite() and configured == "companion":
                print("  (configured: companion · auto-degraded: license/trial expired)")
        except Exception as e:
            _warn(f"could not resolve mode: {e}")
        return 0

    # `set key=value` — only `mode` supported in BATCH-002
    if args[0] == "set" and len(args) >= 2:
        kv = args[1].split("=", 1)
        if len(kv) != 2:
            print(f"{RED}usage:{RESET} kernora config set key=value")
            return 2
        key, val = kv[0].strip(), kv[1].strip()
        if key == "mode":
            if val not in ("lite", "companion"):
                print(f"{RED}error:{RESET} mode must be 'lite' or 'companion'")
                return 2
            try:
                import kernora_mode as _km
                _unlocked = getattr(_km, "is_companion" + "_unlocked", lambda: False)
                if val == "companion" and not _unlocked():
                    print(f"{RED}error:{RESET} companion mode requires a valid license — "
                          "run `kernora license activate <key> --tier pro` to activate.")
                    return 1
            except Exception:
                pass
            # Write [engine].mode = "<val>" — idempotent, preserves other sections.
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            existing = CONFIG_PATH.read_text() if CONFIG_PATH.exists() else ""
            new_block = f'\n[engine]\nmode = "{val}"\n'
            if "[engine]" not in existing:
                updated = (existing.rstrip() + "\n" + new_block).lstrip("\n")
            else:
                # Replace existing mode= under [engine]; minimal regex (no nested
                # tables to worry about — engine.mode is a flat key).
                import re as _re
                # Match [engine] section + everything up to the next [section] or EOF
                pattern = _re.compile(
                    r'(\[engine\]\s*\n)(?:(?:[^\[]*?\n))*?',
                    _re.MULTILINE
                )
                # Simpler approach: split on sections, update [engine] block in place.
                lines = existing.splitlines()
                out_lines = []
                in_engine = False
                mode_written = False
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith("[") and stripped.endswith("]"):
                        # Leaving [engine]? Make sure we wrote a mode line.
                        if in_engine and not mode_written:
                            out_lines.append(f'mode = "{val}"')
                            mode_written = True
                        in_engine = (stripped == "[engine]")
                        out_lines.append(line)
                        continue
                    if in_engine and stripped.startswith("mode") and "=" in stripped:
                        out_lines.append(f'mode = "{val}"')
                        mode_written = True
                        continue
                    out_lines.append(line)
                # File ended while still inside [engine] without a mode line
                if in_engine and not mode_written:
                    out_lines.append(f'mode = "{val}"')
                updated = "\n".join(out_lines).rstrip() + "\n"
            CONFIG_PATH.write_text(updated)
            try:
                CONFIG_PATH.chmod(0o600)
            except Exception:
                pass
            print(f"{GREEN}✓{RESET} mode set to {val} · restart with `kernora restart`")
            return 0
        print(f"{RED}error:{RESET} unknown config key: {key}")
        return 2


def cmd_persona():
    """Show or set the user's persona (drives MCP tool ordering, Stage B 2026-04-25).

    Subcommands:
      kernora persona            — print current persona + menu of options
      kernora persona show       — same as no-arg
      kernora persona set <role> — write [user].persona = "<role>"

    Resolution: env KERNORA_PERSONA > [user].persona in config.toml > 'all'.
    Personas are: all, coder, pm, tpm, founder, team_lead, newcomer.
    """
    args = sys.argv[2:]
    valid = ("all", "coder", "pm", "tpm", "founder", "lead", "explorer")
    aliases = {"team_lead": "lead", "team-lead": "lead",
               "newcomer": "explorer", "first_time_user": "explorer"}
    descriptions = {
        "all":      "show every tool, no foregrounding (default)",
        "coder":    "engineer building/fixing code (search, patterns, decisions, bugs, factbook_add, pe_review, coe)",
        "pm":       "product manager (inventory, coe_product, retro, roi, decisions)",
        "tpm":      "technical PM (status, inventory, decisions, retro, pe_review)",
        "founder":  "solo founder (roi, inventory, coe_product, retro, decisions, onboard)",
        "lead":     "engineering manager / team lead (skills, coach, stats, status, retro)",
        "explorer": "first-time user / discovering Nora (onboard, help, context_for_task, search)",
    }

    # show / no-arg
    if not args or args[0] == "show":
        try:
            import kernora_mode as _km
            current = _km.current_persona()
            print(f"Current persona: {current}")
            print()
            print("Available personas:")
            for name in valid:
                marker = " ← active" if name == current else ""
                print(f"  {name:<10} {descriptions[name]}{marker}")
            print()
            print("Set with:  kernora persona set <role>")
            print("Or env:    export KERNORA_PERSONA=<role>")
        except Exception as e:
            _warn(f"could not resolve persona: {e}")
        return 0

    # set <role>
    if args[0] == "set" and len(args) >= 2:
        role = args[1].strip()
        # Honor legacy role names with a one-time deprecation note
        if role in aliases:
            new = aliases[role]
            print(f"{DIM}note: '{role}' is now '{new}' — using '{new}'.{RESET}")
            role = new
        if role not in valid:
            print(f"{RED}error:{RESET} persona must be one of: {', '.join(valid)}")
            return 2
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = CONFIG_PATH.read_text() if CONFIG_PATH.exists() else ""
        if "[user]" not in existing:
            updated = (existing.rstrip() + f'\n\n[user]\npersona = "{role}"\n').lstrip("\n")
        else:
            lines = existing.splitlines()
            out_lines = []
            in_user = False
            wrote = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    if in_user and not wrote:
                        out_lines.append(f'persona = "{role}"')
                        wrote = True
                    in_user = (stripped == "[user]")
                    out_lines.append(line)
                    continue
                if in_user and stripped.startswith("persona") and "=" in stripped:
                    out_lines.append(f'persona = "{role}"')
                    wrote = True
                    continue
                out_lines.append(line)
            if in_user and not wrote:
                out_lines.append(f'persona = "{role}"')
            updated = "\n".join(out_lines).rstrip() + "\n"
        CONFIG_PATH.write_text(updated)
        try:
            CONFIG_PATH.chmod(0o600)
        except Exception:
            pass
        print(f"{GREEN}✓{RESET} persona set to {role}")
        print(f"{DIM}Tool ordering takes effect on the NEXT list_tools() call from your MCP client.")
        print(f"  • Claude Code: notifications/tools/list_changed fires within ~2s; no manual restart needed")
        print(f"  • Cursor:      Cmd-Shift-P → 'Restart MCP Servers' (≤ 0.45 honors notification)")
        print(f"  • Kiro:        reload IDE; persona-aware ordering applies on reconnect")
        print(f"  • Other:       quit + relaunch the IDE that owns the MCP server.{RESET}")
        return 0

    print(f"{RED}usage:{RESET} kernora persona [show | set <role>]")
    return 2

    print(f"{RED}usage:{RESET} kernora config [show | set mode=lite|companion]")
    return 2


# ── Memory bridge — cross-LLM portability (BATCH-009, 2026-04-26) ──────────
#
# `kernora memory export --to=<target>`   → render factbook in target format
# `kernora memory import --from=<source>` → parse external memory → pending
#
# Plan v2 cuts the original 6-target scope to the 3 commands that don't
# duplicate `kernora generate` (which already emits cursor/kiro/copilot
# steering files at canonical paths). Targets: claude (markdown block) +
# yaml (canonical pass-through). Import: yaml only (other parsers deferred
# per PE round-1 H4 "13-LOC-per-parser unrealistic" finding).

def cmd_memory():
    """Memory bridge: export factbook to / import from another LLM environment.

    Subcommands:
      kernora memory export --to=<claude|yaml> [--out=<path>] [--format=<yaml|json>]
      kernora memory import --from=<yaml> [--in=<path>] [--factbook=<name>]
    """
    args = sys.argv[2:]
    if not args or args[0] in ("-h", "--help", "help"):
        print("usage: kernora memory <export|import> [flags]")
        print("  export --to=claude|yaml [--out=<path>] [--format=yaml|json]")
        print("  import --from=yaml [--in=<path>] [--factbook=<name>]")
        print()
        print("Cross-LLM portability — your factbook works in any LLM, not just Claude.")
        print("Run `kernora memory export --to=claude` to print the markdown block")
        print("(pipe to clipboard or paste into claude.ai Settings → Memory).")
        return 0

    sub = args[0]
    if sub == "export":
        return _cmd_memory_export(args[1:])
    if sub == "import":
        return _cmd_memory_import(args[1:])
    print(f"{RED}error:{RESET} unknown subcommand: {sub}")
    print("usage: kernora memory <export|import> [flags]")
    return 2


def _parse_kv_args(args: list[str]) -> dict:
    """Parse --key=value flags into a dict. Tolerates --key value too."""
    out: dict = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            if "=" in a:
                k, v = a[2:].split("=", 1)
                out[k] = v
            elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                out[a[2:]] = args[i + 1]
                i += 1
            else:
                out[a[2:]] = "true"
        i += 1
    return out


def _cmd_memory_export(args: list[str]) -> int:
    flags = _parse_kv_args(args)
    target = flags.get("to", "").lower()
    out_path = flags.get("out")
    fmt = flags.get("format", "yaml").lower()
    factbook = flags.get("factbook")

    if target not in ("claude", "yaml"):
        print(f"{RED}error:{RESET} --to must be 'claude' or 'yaml'")
        print(f"{DIM}Other targets (cursor/kiro/copilot) are emitted by `kernora generate` at canonical paths.{RESET}")
        return 2

    _add_app_to_path()
    try:
        from memory_bridge import (
            build_memory_block,
            find_factbook_for_cwd,
        )
    except ImportError as e:
        _err(f"memory_bridge unavailable: {e}")
        return 1

    fb_path = find_factbook_for_cwd() if not factbook else None
    if factbook and not fb_path:
        # Try project-rooted .nora/<factbook>.yaml
        candidate = Path.cwd() / ".nora" / f"{factbook}.yaml"
        if candidate.exists():
            fb_path = candidate
    if fb_path is None or not fb_path.exists():
        _err("no factbook found in current project (.nora/*.yaml). "
             "Pass --factbook=<name> or run from a project with a factbook.")
        return 1

    if target == "yaml":
        # Pass-through the canonical YAML
        content = fb_path.read_text()
    else:  # claude
        # Reuse build_memory_block (single source of truth from BATCH-008)
        try:
            res = build_memory_block(factbook_path=fb_path, db_conn=None,
                                     max_chars=10_000)
        except Exception as e:
            _err(f"build_memory_block failed: {e}")
            return 1
        if fmt == "json":
            import json as _j
            content = _j.dumps({
                "version": "1.0", "source": res["source"],
                "chars": res["chars"], "n_sections": res["n_sections"],
                "text": res["text"],
            }, indent=2)
        else:
            content = res["text"]

    if out_path:
        # PE round-2 MEDIUM-2: block writes to system roots; allow anywhere else
        try:
            resolved = Path(out_path).expanduser().resolve()
            BLOCKED_ROOTS = ("/etc/", "/usr/", "/sys/", "/dev/", "/proc/",
                             "/var/db/", "/Library/System/", "/System/",
                             # macOS resolves /etc → /private/etc, etc.
                             "/private/etc/", "/private/usr/", "/private/var/db/")
            if any(str(resolved).startswith(p) for p in BLOCKED_ROOTS):
                _err(f"--out path targets a system directory: {resolved}. "
                     f"Refusing to write outside user-writable areas.")
                return 2
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)
            print(f"{GREEN}✓{RESET} exported to {resolved} "
                  f"({len(content)} chars, target={target}, format={fmt})")
        except Exception as e:
            _err(f"write failed: {e}")
            return 1
    else:
        print(content)
    return 0


def _cmd_memory_import(args: list[str]) -> int:
    flags = _parse_kv_args(args)
    source = flags.get("from", "").lower()
    in_path = flags.get("in")
    factbook = flags.get("factbook")

    if source != "yaml":
        print(f"{RED}error:{RESET} --from must be 'yaml' "
              f"(other sources deferred — see BATCH-009 plan §10.2)")
        return 2

    # Read input
    MAX_INPUT_BYTES = 2_000_000  # PE round-2 MEDIUM-3: stdin cap to prevent OOM
    if in_path:
        try:
            # PE MEDIUM-2: validate input path doesn't escape cwd
            in_resolved = Path(in_path).expanduser().resolve()
            cwd_resolved = Path.cwd().resolve()
            if not str(in_resolved).startswith(str(cwd_resolved)) and not in_resolved.exists():
                _err(f"--in path escapes current directory and doesn't exist: {in_resolved}")
                return 2
            if in_resolved.stat().st_size > MAX_INPUT_BYTES:
                _err(f"--in file is {in_resolved.stat().st_size} bytes, "
                     f"exceeds {MAX_INPUT_BYTES} cap.")
                return 2
            content = in_resolved.read_text()
        except Exception as e:
            _err(f"read failed: {e}")
            return 1
    else:
        content = sys.stdin.read(MAX_INPUT_BYTES + 1)
        if len(content) > MAX_INPUT_BYTES:
            _err(f"stdin input exceeds {MAX_INPUT_BYTES}-byte cap. "
                 f"Use --in=<path> for larger files.")
            return 2

    if not content.strip():
        _err("no input received (use --in=<path> or pipe via stdin)")
        return 2

    try:
        import yaml as _yaml
        src_fb = _yaml.safe_load(content)
    except Exception as e:
        _err(f"YAML parse failed: {e}")
        return 1

    if not isinstance(src_fb, dict) or "content" not in src_fb:
        _err("input doesn't look like a Nora factbook YAML "
             "(missing top-level 'content:' key)")
        return 1

    src_id = src_fb.get("id", "unknown")
    src_facts = src_fb.get("content", []) or []
    if not src_facts:
        print(f"{DIM}source factbook has no facts to import{RESET}")
        return 0

    # Locate target factbook
    _add_app_to_path()
    try:
        from memory_bridge import find_factbook_for_cwd
    except ImportError as e:
        _err(f"memory_bridge unavailable: {e}")
        return 1
    target_path = (Path.cwd() / ".nora" / f"{factbook}.yaml") if factbook else find_factbook_for_cwd()
    if target_path is None or not target_path.exists():
        _err("no target factbook found in current project (.nora/*.yaml). "
             "Pass --factbook=<name> or run from a project with a factbook.")
        return 1

    # Load target, compute next free ID, dedup by normalized text
    try:
        import yaml as _yaml
        target_fb = _yaml.safe_load(target_path.read_text()) or {}
    except Exception as e:
        _err(f"target factbook parse failed: {e}")
        return 1
    target_facts = target_fb.get("content") or []
    target_fb["content"] = target_facts

    # Existing IDs in target (to find next free)
    existing_ids = set()
    existing_texts = set()
    for f in target_facts:
        if not isinstance(f, dict):
            continue
        existing_ids.add(str(f.get("id", "")))
        # Normalize for dedup (basic — full vocab.normalize_for_dedup not available)
        text = (f.get("statement") or f.get("summary") or f.get("name") or "").lower().strip()
        if text:
            existing_texts.add(text[:120])

    def next_free_id() -> str:
        # Pick max(fNNN) + 1
        n = 0
        for sid in existing_ids:
            if sid.startswith("f") and sid[1:].isdigit():
                n = max(n, int(sid[1:]))
        n += 1
        return f"f{n:03d}"

    imported = 0
    skipped_dup = 0
    skipped_ids: list[str] = []  # PE round-2 HIGH-1: log silently-skipped dups
    for src_fact in src_facts:
        if not isinstance(src_fact, dict):
            continue
        text = (src_fact.get("statement") or src_fact.get("summary")
                or src_fact.get("name") or "").lower().strip()[:120]
        if text and text in existing_texts:
            skipped_dup += 1
            skipped_ids.append(str(src_fact.get("id", "?")))
            continue
        # Remap ID + add provenance tags (PE H2 fix)
        new_id = next_free_id()
        new_fact = dict(src_fact)
        original_id = src_fact.get("id", "?")
        new_fact["id"] = new_id
        new_fact["review_status"] = "pending"  # land for review (B2 resolution)
        # Provenance tags
        tags = list(new_fact.get("tags") or [])
        tags.append(f"imported_from_factbook:{src_id}")
        tags.append(f"imported_from_fact:{original_id}")
        new_fact["tags"] = tags
        target_facts.append(new_fact)
        existing_ids.add(new_id)
        if text:
            existing_texts.add(text)
        imported += 1

    # Write target back
    try:
        target_path.write_text(
            _yaml.dump(target_fb, default_flow_style=False, sort_keys=False,
                       allow_unicode=True, width=120)
        )
    except Exception as e:
        _err(f"target write failed: {e}")
        return 1

    print(f"{GREEN}✓{RESET} imported {imported} facts into {target_path.name} "
          f"(skipped {skipped_dup} duplicates by text)")
    if skipped_ids:
        # PE round-2 HIGH-1: surface which source IDs were dropped so the user
        # can audit false-positive dedup (120-char prefix collision).
        print(f"{DIM}Skipped source IDs (first-120-char text matched existing): "
              f"{', '.join(skipped_ids[:20])}"
              f"{' ...' if len(skipped_ids) > 20 else ''}{RESET}")
    print(f"{DIM}All imported facts have review_status='pending'. "
          f"Promote via `nora_factbook_promote(action='list')` to review them.{RESET}")
    return 0


# ── Doctor ────────────────────────────────────────────────────────────────────

def cmd_doctor():
    """Diagnostic check (stub — full implementation in batch-007)."""
    _header("Kernora Doctor")
    _info("Checking Kernora installation …")
    issues = []
    # venv
    if not PYTHON.exists():
        issues.append("venv missing — run: nora install")
    else:
        _ok("venv present")
    # DB
    if not DB_PATH.exists():
        issues.append("echo.db missing — run: nora install")
    else:
        _ok(f"echo.db present ({DB_PATH.stat().st_size // 1024} KB)")
    # Dashboard
    pid = _get_dashboard_pid()
    _ok(f"dashboard running (pid {pid})") if pid else _warn("dashboard not running")
    # Config
    if CONFIG_PATH.exists():
        _ok("config.toml present")
    else:
        issues.append("config.toml missing — run: nora install")
    if issues:
        print()
        for issue in issues:
            _err(issue)
        sys.exit(1)
    else:
        print()
        _ok("All checks passed.")


# ── Main ──────────────────────────────────────────────────────────────────────

# ── Privacy commands (batch-005b) ─────────────────────────────────────────────

def cmd_add_project():
    """Add a project root to the tracking allowlist (nora add-project)."""
    _add_app_to_path()
    try:
        import nora_add_project as _ap
        argv = sys.argv[2:]  # strip "nora add-project"
        return _ap.main(argv)
    except ImportError:
        _err("nora_add_project.py not found — run: nora install")
        return 1


def cmd_list_projects():
    """Show the current tracking allowlist (nora list-projects)."""
    _add_app_to_path()
    try:
        import nora_add_project as _ap
        return _ap.cmd_list()
    except ImportError:
        _err("nora_add_project.py not found — run: nora install")
        return 1


def cmd_forget():
    """Securely purge session data — multi-level delete (nora forget).

    Usage:
      nora forget [--level {project,factlets,factory-reset}]
                  [--name PROJECT_NAME]
                  [--yes]
                  [--keep-keys / --no-keep-keys]
                  [--dry-run]

      -- Legacy (session-level, per original nora_forget.py) --
      nora forget <session-id>
      nora forget --all-unscoped [--dry-run]
      nora forget --before YYYY-MM-DD [--dry-run]

    Levels:
      project       — delete all data for a single project (requires --name, typed-phrase guard)
      factlets      — delete all factlets across all projects; keep sessions
      factory-reset — full wipe + backup (requires typed phrase "DELETE EVERYTHING")
    """
    _add_app_to_path()
    argv = sys.argv[2:]  # strip "nora forget"

    # Detect if this is a multi-level forget call (--level flag present)
    if "--level" in argv:
        return _cmd_forget_multilevel(argv)

    # Legacy path: delegate to nora_forget.py for session-level purge
    try:
        import nora_forget as _nf
        return _nf.main(argv)
    except ImportError:
        _err("nora_forget.py not found — run: nora install")
        return 1


def _cmd_forget_multilevel(argv: list) -> int:
    """Handle multi-level delete: project / factlets / factory-reset."""
    import argparse as _argparse

    _add_app_to_path()

    p = _argparse.ArgumentParser(
        prog="nora forget",
        description="Multi-level data deletion with typed-phrase guards.",
    )
    p.add_argument(
        "--level",
        choices=["project", "factlets", "factory-reset"],
        required=True,
        help="Deletion level: project | factlets | factory-reset",
    )
    p.add_argument(
        "--name",
        metavar="PROJECT",
        help="Project name (required for --level project)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Execute the deletion (without --yes, runs dry-run and shows summary)",
    )
    p.add_argument(
        "--keep-keys",
        dest="keep_keys",
        action="store_true",
        default=True,
        help="Preserve API keys in config.toml during factory-reset (default: ON)",
    )
    p.add_argument(
        "--no-keep-keys",
        dest="keep_keys",
        action="store_false",
        help="Erase API keys in config.toml during factory-reset",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deleted without actually deleting",
    )

    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    dry_run = args.dry_run or not args.yes

    try:
        import forget as _forget
    except ImportError:
        _err("forget.py not found — run: nora install")
        return 1

    # ── L2 — project ────────────────────────────────────────────────────────
    if args.level == "project":
        if not args.name:
            _err("--level project requires --name <project-name>")
            return 1
        if not dry_run:
            # Typed-phrase guard: user must have typed the project name
            # via --yes flag here; the CLI confirms with a prompt.
            try:
                phrase = input(
                    f"Type the project name '{args.name}' to confirm deletion: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                _err("Aborted.")
                return 1
            if phrase != args.name:
                _err(
                    f"Confirmation phrase did not match expected '{args.name}'. Aborted."
                )
                return 1

        result = _forget.forget_project(args.name, dry_run=dry_run)
        _print_forget_result(result, dry_run)
        return 0 if result.get("ok") else 1

    # ── L3 — factlets ────────────────────────────────────────────────────────
    elif args.level == "factlets":
        # §10.9 — use canonical phrase from forget.FORGET_PHRASES (single source of truth)
        _factlets_phrase = _forget.FORGET_PHRASES.get("factlets", "DELETE FACTLETS")
        if not dry_run:
            try:
                phrase = input(
                    f"Type '{_factlets_phrase}' to confirm: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                _err("Aborted.")
                return 1
            if phrase != _factlets_phrase:
                _err(f"Confirmation phrase did not match '{_factlets_phrase}'. Aborted.")
                return 1

        result = _forget.forget_factlets(dry_run=dry_run)
        _print_forget_result(result, dry_run)
        return 0 if result.get("ok") else 1

    # ── L4 — factory-reset ───────────────────────────────────────────────────
    elif args.level == "factory-reset":
        # §10.9 — use canonical phrase from forget.FORGET_PHRASES (single source of truth)
        _factory_phrase = _forget.FORGET_PHRASES.get("factory-reset", "DELETE EVERYTHING")
        if not dry_run:
            try:
                phrase = input(
                    f"Type '{_factory_phrase}' to confirm factory reset: "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                _err("Aborted.")
                return 1
            if phrase != _factory_phrase:
                _err(f"Confirmation phrase did not match '{_factory_phrase}'. Aborted.")
                return 1

        result = _forget.forget_factory(keep_keys=args.keep_keys, dry_run=dry_run)
        _print_forget_result(result, dry_run)
        return 0 if result.get("ok") else 1

    return 0


def _print_forget_result(result: dict, dry_run: bool) -> None:
    """Pretty-print the result of a forget operation."""
    _add_app_to_path()
    try:
        import forget as _forget
        print(_forget.format_summary(result))
    except ImportError:
        if result.get("ok"):
            _ok(result.get("summary", "Done."))
        else:
            _err(result.get("summary", "Unknown error."))


def cmd_pause():
    """Pause Kernora capture globally (nora pause)."""
    _set_paused(True)


def cmd_resume():
    """Resume Kernora capture globally (nora resume)."""
    _set_paused(False)


def _set_paused(paused: bool) -> int:
    """Toggle paused flag in config.toml."""
    _add_app_to_path()
    try:
        import nora_add_project as _ap
        cfg_path = str(CONFIG_PATH)
        privacy = _ap._load_privacy(cfg_path)
        privacy["paused"] = paused
        _ap._write_privacy(cfg_path, privacy)
        state = "PAUSED" if paused else "RESUMED"
        _ok(f"Capture {state}. (Edit ~/.kernora/config.toml to change manually.)")
        return 0
    except ImportError:
        _err("nora_add_project.py not found — run: nora install")
        return 1


def _add_app_to_path():
    """Ensure ~/.kernora/app and repo root are on sys.path."""
    for p in [str(APP_DIR), str(Path(__file__).resolve().parent)]:
        if p not in sys.path:
            sys.path.insert(0, p)


def cmd_version():
    """Print Kernora CLI + DB schema + git version info."""
    version_file = Path(__file__).resolve().parent / ".version"
    cli_ver = "unknown"
    for p in (version_file, APP_DIR / ".version"):
        if p.exists():
            try:
                v = p.read_text().strip()
                if v:
                    cli_ver = v
                    break
            except OSError:
                pass
    db_ver = "n/a"
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=2.0)
            db_ver = str(conn.execute("PRAGMA user_version").fetchone()[0])
            conn.close()
        except sqlite3.Error:
            db_ver = "error"
    commit = "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent),
             "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            commit = (result.stdout or "unknown").strip() or "unknown"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    print(f"Kernora {cli_ver} · DB schema v{db_ver} · commit {commit}")
    return 0


def cmd_migrate():
    """Run pending DB schema migrations (or show status without --apply)."""
    _add_app_to_path()
    try:
        import kernora_migrate
    except ImportError:
        _err("kernora_migrate.py not found — run: kernora install")
        return 1
    return kernora_migrate.main(sys.argv[2:])


def cmd_archive():
    """Archive DB contents to a tar.gz (project-scoped or whole-DB)."""
    _add_app_to_path()
    try:
        import kernora_datalife
    except ImportError:
        _err("kernora_datalife.py not found — run: kernora install")
        return 1
    return kernora_datalife.cmd_archive(sys.argv[2:])


def cmd_purge():
    """Delete project-scoped or whole-DB data (archive-first; requires --yes)."""
    _add_app_to_path()
    try:
        import kernora_datalife
    except ImportError:
        _err("kernora_datalife.py not found — run: kernora install")
        return 1
    return kernora_datalife.cmd_purge(sys.argv[2:])


def cmd_restore():
    """Restore a Kernora archive tar.gz (pre-restore snapshot taken)."""
    _add_app_to_path()
    try:
        import kernora_datalife
    except ImportError:
        _err("kernora_datalife.py not found — run: kernora install")
        return 1
    return kernora_datalife.cmd_restore(sys.argv[2:])


def cmd_anchors():
    """Scan CLAUDE.md + steering for line-refs; suggest function anchors ($50-2)."""
    _add_app_to_path()
    try:
        import kernora_anchors
    except ImportError:
        _err("kernora_anchors.py not found — run: kernora install")
        return 1
    return kernora_anchors.main(sys.argv[2:])


def cmd_drift():
    """Detect new modules in recent commits not mentioned in CLAUDE.md ($50-3)."""
    _add_app_to_path()
    try:
        import kernora_drift
    except ImportError:
        _err("kernora_drift.py not found — run: kernora install")
        return 1
    return kernora_drift.main(sys.argv[2:])


def cmd_precision():
    """Injection precision stats (stats | recent) — $50-5."""
    _add_app_to_path()
    try:
        import kernora_injection
    except ImportError:
        _err("kernora_injection.py not found — run: kernora install")
        return 1
    return kernora_injection.main(sys.argv[2:])


def cmd_recall():
    """Dump everything Nora knows about the current project ($50-10)."""
    _add_app_to_path()
    try:
        import kernora_recall
    except ImportError:
        _err("kernora_recall.py not found — run: kernora install")
        return 1
    return kernora_recall.main(sys.argv[2:])


def cmd_network_check():
    """AST-scan for network imports outside the allowlist ($50-11)."""
    _add_app_to_path()
    try:
        import kernora_network_audit
    except ImportError:
        _err("kernora_network_audit.py not found — run: kernora install")
        return 1
    return kernora_network_audit.main(["check"] + sys.argv[2:])


_POST_COMMIT_HOOK_MARKER = "# kernora-post-commit-hook-v2"
# L3 fix (2026-04-23): dropped `|| true` (unreachable since `( & )` always
# exits 0); L4 fix: use full venv path to kernora so the hook doesn't
# silently fail when the shell's PATH lacks the install dir.
_KERNORA_BIN = str(Path.home() / ".kernora" / "venv" / "bin" / "kernora")
_POST_COMMIT_HOOK_BODY = f"""#!/bin/sh
{_POST_COMMIT_HOOK_MARKER}
# Auto-regenerate Nora steering files after every commit.
# Runs in the background so commits return instantly.
# H3 fix (2026-04-23): `kernora generate` uses an flock mutex, so
# rapid-fire commits (rebase, squash) serialize instead of racing.
# Installed by `kernora hook-install`. Remove via `kernora hook-uninstall`.
( "{_KERNORA_BIN}" generate --quiet >/dev/null 2>&1 & )
"""

# Task #3 P0-C (2026-04-22): pre-commit PII guardrail.
# Blocks commits that include critical/high PII findings in .nora/** files.
# kernora_pii.py exists as a standalone scanner; this hook gates EVERY commit
# through it so secrets cannot land in git. Allowlist via `# kernora-pii-allowlist`
# marker on the line if a finding is intentional (e.g., a regex sample).
_PRE_COMMIT_HOOK_MARKER = "# kernora-pre-commit-hook-v3"
# L4 fix (2026-04-23): full venv path; C6 fix: quote $STAGED per-file via
# a NUL-delimited loop so filenames with spaces don't split into argv.
_PRE_COMMIT_HOOK_BODY = f"""#!/bin/sh
{_PRE_COMMIT_HOOK_MARKER}
# Two-part pre-commit check on staged .nora/** files:
#   1. PII guardrail — blocks on secrets/credentials (15-rule kernora_pii catalog)
#   2. Project boundary — blocks on facts whose `project:` frontmatter does
#      not match the current repo's canonical project name (CoE 2026-04-23)
# Add `# kernora-pii-allowlist` to a line if the PII finding is intentional.
# Installed by `kernora hook-install --hooks pre`. Remove via `kernora hook-uninstall`.
KERNORA_BIN="{_KERNORA_BIN}"
# NUL-delimited staged list (safe for filenames with spaces / newlines)
FILES_NUL=$(git diff --cached --name-only --diff-filter=ACM -z -- '.nora/**' 2>/dev/null)
if [ -n "$FILES_NUL" ]; then
    # Build a temp file with one path per line for xargs -0.
    TMP=$(mktemp) || exit 0
    printf '%s' "$FILES_NUL" > "$TMP"
    if ! xargs -0 -a "$TMP" "$KERNORA_BIN" pii-scan >&2; then
        rm -f "$TMP"
        echo "" >&2
        echo "PII guardrail blocked commit — see findings above." >&2
        echo "Either remove the secret OR add a '# kernora-pii-allowlist' marker to the line." >&2
        exit 1
    fi
    if ! xargs -0 -a "$TMP" "$KERNORA_BIN" project-scope-check >&2; then
        rm -f "$TMP"
        echo "" >&2
        echo "Project-scope boundary blocked commit — see findings above." >&2
        echo "Either move the file to its own project's repo OR fix the 'project:' frontmatter." >&2
        exit 1
    fi
    rm -f "$TMP"
fi
"""


def _current_repo_root():
    """Resolve the git repo root of the CWD via `git rev-parse`."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    return None


def cmd_pe_review() -> int:
    """Thin CLI wrapper around nora_factbook_promote(action='review').
    (Pre-2026-04-25: was nora_pe_review_start, then nora_pe_panel; rehomed
    to factbook domain in the redesign. The helper text below tells users
    which tool to call for the next stages.)

    Prints the per-role prompts to stdout so a user without an MCP-using IDE
    can paste each one into ChatGPT / Claude / Cursor manually, then submit
    scores via subsequent CLI invocations or directly via the MCP tools.

    Usage:
      kernora pe-review --facts 42,43,44              # 3 prompts to stdout
      kernora pe-review --facts 42 --panel sw,ai,ds   # custom 3-reviewer panel
      kernora pe-review --facts 42 --session devops   # explicit DOMAIN_PANEL_MAP key
    """
    import argparse
    parser = argparse.ArgumentParser(prog="kernora pe-review",
        description="Run a multi-domain PE panel on a batch of fact IDs.")
    parser.add_argument("--facts", required=True,
        help="Comma-separated patterns.id values (e.g. 42,43,44).")
    parser.add_argument("--panel",
        help="Optional explicit 3-reviewer panel, e.g. software-engineering,ai,data-science.")
    parser.add_argument("--session",
        help="Optional session_type hint for DOMAIN_PANEL_MAP (e.g. devops, product, vc-prep).")
    args = parser.parse_args(sys.argv[2:])

    try:
        fact_ids = [int(s.strip()) for s in args.facts.split(",") if s.strip()]
    except ValueError:
        _err("--facts must be comma-separated integers")
        return 1
    if not fact_ids:
        _err("--facts must include at least one ID")
        return 1

    panel_override = None
    if args.panel:
        panel_override = [s.strip() for s in args.panel.split(",") if s.strip()]
        if len(panel_override) != 3:
            _err("--panel must list exactly 3 reviewers")
            return 1

    _add_app_to_path()
    try:
        from nora_mcp import NoraServer
    except ImportError as e:
        _err(f"nora_mcp module not available: {e}")
        return 1
    srv = NoraServer()
    raw = srv._pe_review_start(
        fact_ids,
        panel_override=panel_override,
        session_type=args.session,
    )
    import json as _j
    res = _j.loads(raw)
    if "error" in res:
        _err(f"pe-review failed: {res.get('error')}")
        return 1

    panel_id = res["panel_id"]
    panel = res["panel"]
    print(f"\n{BOLD}PE-review panel started{RESET}")
    print(f"  panel_id: {CYAN}{panel_id}{RESET}")
    print(f"  panel:    {', '.join(panel)}")
    print(f"  facts:    {res['n_facts']} ({fact_ids})\n")
    print(f"{DIM}Paste each prompt below into your LLM, then submit scores via "
          f"`nora_factbook_promote(action='submit', panel_id={panel_id!r}, role=..., scores=[...])` "
          f"and finalize with `nora_factbook_promote(action='finalize', panel_id={panel_id!r})`.{RESET}\n")
    for role, prompt in (res.get("prompts") or {}).items():
        print(f"{BOLD}── PROMPT for role: {role} ──{RESET}")
        print(prompt)
        print()
    return 0


def cmd_coe() -> int:
    """BATCH-005: interactive 5-Whys at the terminal.

    Usage:
      kernora coe "<problem statement>"
        — prompts you for each Why answer at the terminal, then prints the
          synthesized root cause + suggested factbook entry.

    Non-interactive (for piping): if stdin is a pipe, reads 5 newline-separated
    answers from stdin in order.
    """
    if len(sys.argv) < 3 or sys.argv[2] in ("-h", "--help"):
        print("Usage: kernora coe \"<problem statement>\"")
        return 1
    problem = " ".join(sys.argv[2:]).strip()
    if not problem:
        _err("problem statement required")
        return 1

    _add_app_to_path()
    try:
        from nora_mcp import NoraServer
    except ImportError as e:
        _err(f"nora_mcp module not available: {e}")
        return 1
    srv = NoraServer()
    import json as _j
    start = _j.loads(srv._coe_start(problem))
    if "error" in start:
        _err(f"coe-start failed: {start.get('error')}")
        return 1
    coe_id = start["coe_id"]
    print(f"\n{BOLD}5-Whys investigation started{RESET}")
    print(f"  coe_id: {CYAN}{coe_id}{RESET}")
    print(f"  problem: {problem}\n")

    # Stdin pipe → batch mode (one answer per line); else interactive.
    answers: list[str] = []
    if not sys.stdin.isatty():
        answers = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
        answers = answers[:5]

    for n in (1, 2, 3, 4, 5):
        if n - 1 < len(answers):
            ans = answers[n - 1]
            print(f"  Why-{n}: {ans}")
        else:
            try:
                ans = input(f"  Why-{n}: ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                _err("aborted")
                return 1
        if not ans:
            _err(f"Why-{n} answer required")
            return 1
        sub = _j.loads(srv._coe_submit(coe_id, n, ans))
        if "error" in sub:
            _err(f"submit failed: {sub.get('error')}")
            return 1

    fin = _j.loads(srv._coe_finalize(coe_id))
    if "error" in fin:
        _err(f"finalize failed: {fin.get('error')}")
        return 1
    print(f"\n{BOLD}Root cause:{RESET} {fin.get('root_cause')}")
    sf = fin.get("suggested_fact") or {}
    print(f"\n{BOLD}Suggested factbook entry:{RESET}")
    print(f"  text:     {sf.get('text')}")
    print(f"  type:     {sf.get('type')}")
    print(f"  evidence: {sf.get('evidence')}")
    print(f"\n{DIM}Promote via: nora_factbook_add(fact={sf.get('text')!r}, "
          f"fact_type={sf.get('type')!r}){RESET}")
    return 0


def cmd_coe_last():
    """v2.3.2: deterministic COE review of the last N commits.

    Solo-dev replacement for the code reviewer you don't have.
    Zero LLM speculation — every flag traces to a deterministic check
    you can audit in kernora_coe.py. Five checks per commit:
      1. Band-aid phrases in commit message
      2. Test adjacency (did you add/touch a test?)
      3. Recurrence (file has prior resolved bugs → whack-a-mole risk)
      4. Touch depth (leaf-only edits may be symptom-patches)
      5. Prior-fix similarity (similar commits recently?)

    Every flag labeled HIGH / MEDIUM / LOW confidence. HIGH → address
    before merge. MEDIUM → worth a second look. LOW → informational.
    """
    n = 3
    # Accept `coe-last 3` or `coe-last --n 3`
    if len(sys.argv) > 2:
        try:
            n = max(1, min(20, int(sys.argv[2])))
        except ValueError:
            pass
    repo = _current_repo_root()
    if repo is None:
        _err("Not inside a git repository.")
        return 1
    try:
        import kernora_coe
    except ImportError as e:
        _err(f"kernora_coe module not available: {e}")
        return 1

    db_path = Path.home() / ".kernora" / "echo.db"
    project = repo.name
    reviews = kernora_coe.review_last_commits(
        repo, n=n, db_path=db_path if db_path.exists() else None, project=project,
    )
    print()
    print(kernora_coe.render_markdown(reviews))
    print()
    # Non-zero exit if any HIGH flag so CI can gate on this.
    high_flags = sum(
        1 for r in reviews for f in r.flags if f.get("confidence") == "HIGH"
    )
    return 1 if high_flags > 0 else 0


# BUG-3 fix (2026-04-23): old markers from prior hook versions. When
# upgrading, strip the old block before installing the new one so users
# don't end up with BOTH versions running.
_OLD_HOOK_MARKERS: dict[str, list[str]] = {
    "pre-commit":  [
        "# kernora-pre-commit-hook-v1",
        "# kernora-pre-commit-hook-v2",
    ],
    "post-commit": [
        "# kernora-post-commit-hook-v1",
    ],
}


def _strip_hook_block(text: str, marker: str) -> str:
    """Remove the Kernora-tagged block for `marker` from `text`.

    Matches from the marker line through the next blank-line-terminated
    block (or EOF). Preserves all other content. Idempotent (returns text
    unchanged if marker not present).
    """
    if marker not in text:
        return text
    import re as _re
    pat = _re.compile(
        r"(?:^#!/bin/sh\s*\n)?"
        r"\s*" + _re.escape(marker) + r".*?"
        r"(?=\n\s*\n|\Z)",
        _re.MULTILINE | _re.DOTALL,
    )
    cleaned = pat.sub("", text).strip()
    return cleaned


def _install_one_hook(hooks_dir: Path, hook_name: str, marker: str, body: str) -> tuple[bool, str]:
    """Idempotent single-hook installer. Returns (installed, status_msg).

    Splices the Kernora-tagged block into the hook file:
      - If hook has our CURRENT marker → no-op (already installed)
      - If hook has any OLD markers (from _OLD_HOOK_MARKERS) → strip them first
      - Otherwise → append our block (preserves other content)
    """
    hook_path = hooks_dir / hook_name
    existing = hook_path.read_text() if hook_path.exists() else ""

    if marker in existing:
        return False, f"already installed at {hook_path}"

    # BUG-3 fix: strip any OLD-version blocks from the same hook before
    # appending the new one. Otherwise the hook file ends up with both
    # and the old block's logic runs alongside the new one.
    upgraded = False
    for old_marker in _OLD_HOOK_MARKERS.get(hook_name, []):
        if old_marker in existing:
            existing = _strip_hook_block(existing, old_marker)
            upgraded = True

    if existing.strip():
        merged = existing.rstrip() + "\n\n" + body
    else:
        merged = body

    try:
        hook_path.write_text(merged)
        # H6 fix (2026-04-23): 0o750 — owner+group only, no world-readable.
        # Hook files live in .git/hooks/ inside the repo; on multi-user
        # machines, 0o755 let any user read (and trigger inspection of)
        # the kernora commands. 0o750 keeps functionality identical for
        # single-user systems while hardening multi-user boxes.
        hook_path.chmod(0o750)
    except OSError as e:
        return False, f"could not write: {e}"
    suffix = " (upgraded from older Kernora hook)" if upgraded else ""
    return True, f"{hook_path}{suffix}"


def cmd_hook_install():
    """Install Kernora git hooks. v2.3.1 (post-commit) + v2.4.0 Task #3 (pre-commit PII).

    Hooks installed:
      post-commit: runs `kernora generate --quiet` in background after commits
      pre-commit:  runs `kernora pii-scan` on staged .nora/** files; blocks on critical/high

    Usage:
      kernora hook-install                # both hooks (default)
      kernora hook-install --hooks pre    # pre-commit only
      kernora hook-install --hooks post   # post-commit only
      kernora hook-install --hooks both   # both (explicit)

    Idempotent — re-running replaces only Kernora-tagged content, preserving
    other hook installations (e.g. husky).
    """
    # Parse --hooks flag (default: both)
    which = "both"
    if "--hooks" in sys.argv:
        idx = sys.argv.index("--hooks")
        if idx + 1 < len(sys.argv):
            which = sys.argv[idx + 1].lower()
    if which not in ("pre", "post", "both"):
        _err(f"Invalid --hooks value: {which}. Use: pre | post | both")
        return 1

    root = _current_repo_root()
    if root is None:
        _err("Not inside a git repository (or `git` not on PATH).")
        return 1
    hooks_dir = root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    _header(f"Kernora — installing hooks ({which})")
    installed_any = False

    if which in ("post", "both"):
        ok, msg = _install_one_hook(hooks_dir, "post-commit",
                                     _POST_COMMIT_HOOK_MARKER, _POST_COMMIT_HOOK_BODY)
        if ok:
            installed_any = True
            _ok(f"post-commit hook installed: {msg}")
            print(f"  Runs: {CYAN}kernora generate --quiet{RESET} after every commit")
        else:
            print(f"  {DIM}post-commit: {msg}{RESET}")

    if which in ("pre", "both"):
        ok, msg = _install_one_hook(hooks_dir, "pre-commit",
                                     _PRE_COMMIT_HOOK_MARKER, _PRE_COMMIT_HOOK_BODY)
        if ok:
            installed_any = True
            _ok(f"pre-commit hook installed: {msg}")
            print(f"  Runs: {CYAN}kernora pii-scan{RESET} on staged .nora/** files")
            print(f"  Blocks commits with critical/high PII findings.")
            print(f"  Allowlist: add {CYAN}# kernora-pii-allowlist{RESET} to a line if intentional.")
        else:
            print(f"  {DIM}pre-commit: {msg}{RESET}")

    print()
    print(f"  Remove: {CYAN}kernora hook-uninstall{RESET}")
    if installed_any:
        print(f"  {DIM}Existing content in hook files (if any) was preserved.{RESET}")
    return 0


def _uninstall_one_hook(hook_path: Path, marker: str) -> tuple[bool, str]:
    """Remove the Kernora-tagged block from a hook. Preserves other content."""
    if not hook_path.exists():
        return False, "no hook file"
    text = hook_path.read_text()
    if marker not in text:
        return False, "no Kernora block"
    import re as _re
    pat = _re.compile(
        r"(?:^#!/bin/sh\s*\n)?"
        r"\s*" + _re.escape(marker) + r".*?"
        r"(?=\n\s*\n|\Z)",
        _re.MULTILINE | _re.DOTALL,
    )
    cleaned = pat.sub("", text).strip()
    if cleaned:
        hook_path.write_text(cleaned + "\n")
        return True, "removed Kernora block, preserved other content"
    else:
        hook_path.unlink()
        return True, "removed entire file (Kernora was the only content)"


def cmd_hook_uninstall():
    """Remove Kernora-tagged blocks from BOTH pre-commit and post-commit hooks.

    Preserves any other user content in the hook files.
    Task #3 P0-C extends to handle pre-commit alongside the original post-commit.
    """
    root = _current_repo_root()
    if root is None:
        _err("Not inside a git repository.")
        return 1
    hooks_dir = root / ".git" / "hooks"

    for hook_name, marker in [
        ("post-commit", _POST_COMMIT_HOOK_MARKER),
        ("pre-commit",  _PRE_COMMIT_HOOK_MARKER),
    ]:
        ok, msg = _uninstall_one_hook(hooks_dir / hook_name, marker)
        if ok:
            _ok(f"{hook_name}: {msg}")
        else:
            print(f"  {DIM}{hook_name}: {msg}{RESET}")
        # BUG-3 fix: also strip any OLD-version blocks the user may still
        # have from earlier Kernora versions — uninstall should be total.
        for old_marker in _OLD_HOOK_MARKERS.get(hook_name, []):
            ok2, msg2 = _uninstall_one_hook(hooks_dir / hook_name, old_marker)
            if ok2:
                _ok(f"{hook_name} ({old_marker[2:]}): {msg2}")
    return 0


def cmd_review_injections():
    """v2.2.14: bulk accept/reject UI for unreviewed injection_events.

    Every ROI report has flagged the same gap: "N injection events, 0
    accept/reject signal." The workflow subtotal stays speculative
    because the grader sees only `??` outcomes. This command lets the
    user walk through unreviewed events grouped by source, see the
    snippet Nora injected, and mark accept/reject in seconds.

    Closes ROI-FINDING1 (#61) for the pragmatic case. Full auto-detect
    via post-tool hooks is v2.3 scope.

    Reads from sys.argv:
      --days N     Only show events from last N days (default 30).
      --source S   Filter to one source (pretool.guardrail / pulse.*).
      --limit N    Max events to review per run (default 20).
    """
    import kernora_injection
    import sqlite3
    from pathlib import Path as _P

    days = 30
    source_filter = None
    limit = 20
    for i, arg in enumerate(sys.argv):
        if arg == "--days" and i + 1 < len(sys.argv):
            try:
                days = int(sys.argv[i + 1])
            except ValueError:
                pass
        elif arg == "--source" and i + 1 < len(sys.argv):
            source_filter = sys.argv[i + 1]
        elif arg == "--limit" and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                pass

    db_path = _P.home() / ".kernora" / "echo.db"
    if not db_path.exists():
        _err("echo.db not found. Run `kernora install` first.")
        return 1

    conn = sqlite3.connect(str(db_path), timeout=5)
    try:
        sql = (
            "SELECT id, ts, source, snippet, file_refs_json "
            "FROM injection_events "
            "WHERE accepted IS NULL "
            "AND ts >= datetime('now', ?) "
        )
        params: list = [f"-{days} days"]
        if source_filter:
            sql += "AND source = ? "
            params.append(source_filter)
        sql += "ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    if not rows:
        print(
            f"\n  {GREEN}No unreviewed injection events in the last {days} days"
            f"{' for source ' + source_filter if source_filter else ''}.{RESET}\n"
        )
        print("  Run `nora roi` — the workflow subtotal should reflect your existing signal.\n")
        return 0

    # Show precision summary upfront so users know the stakes.
    stats = kernora_injection.precision_by_source(days=days)
    _header(f"Nora — review injections (last {days}d)")
    print(
        f"  {len(rows)} unreviewed event{'s' if len(rows) != 1 else ''} "
        f"(showing up to {limit} in this batch).\n"
    )
    if stats:
        print("  Current precision by source:")
        for src, d in sorted(stats.items()):
            p = d.get("precision")
            p_s = f"{p*100:.0f}%" if isinstance(p, float) else "—"
            print(f"    {src:25s}  acc={d['accepted']:3d}  rej={d['rejected']:3d}  ??={d['unclassified']:3d}  precision={p_s}")
        print()
    print("  For each event: `a` accept · `r` reject · `s` skip · `q` quit")
    print("  Accepted = the injected snippet actually helped your work on this task.")
    print("  Rejected = the snippet was wrong/noisy/irrelevant for this task.\n")

    accepted = rejected = skipped = 0
    for idx, row in enumerate(rows, 1):
        event_id, ts, source, snippet, file_refs = row
        print(f"  {BOLD}[{idx}/{len(rows)}]{RESET}  id={event_id}  {DIM}{ts}{RESET}  {CYAN}{source}{RESET}")
        if file_refs:
            try:
                import json as _j
                refs = _j.loads(file_refs)
                if refs:
                    print(f"    Files: {', '.join(str(r)[:60] for r in refs[:3])}")
            except Exception:
                pass
        snip = (snippet or "").strip()
        if snip:
            if len(snip) > 240:
                snip = snip[:240] + "…"
            for line in snip.splitlines()[:6]:
                print(f"    {DIM}│{RESET} {line}")
        try:
            choice = input(f"    [a/r/s/q] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if choice == "q":
            break
        if choice == "a":
            if kernora_injection.mark_accepted(event_id, reason="cli-review"):
                accepted += 1
                print(f"    {GREEN}✓ accepted{RESET}\n")
            else:
                print(f"    {DIM}(mark failed){RESET}\n")
        elif choice == "r":
            if kernora_injection.mark_rejected(event_id, reason="cli-review"):
                rejected += 1
                print(f"    {CYAN}✗ rejected{RESET}\n")
            else:
                print(f"    {DIM}(mark failed){RESET}\n")
        else:
            skipped += 1
            print(f"    {DIM}— skipped{RESET}\n")

    _header("Session summary")
    print(f"  Accepted: {GREEN}{accepted}{RESET}    Rejected: {CYAN}{rejected}{RESET}    Skipped: {DIM}{skipped}{RESET}")
    if accepted + rejected > 0:
        p = accepted / (accepted + rejected)
        print(f"  Session precision: {p*100:.0f}%")
    print()
    print("  Run `nora roi` again to see the workflow subtotal reflect the new signal.")
    print(
        "  Recommended cadence: review the newest 10-20 events once a week — "
        "precision scores stabilize after ~30 classified events per source."
    )
    print()
    return 0


def cmd_ignore_check():
    """Show what `.noraignore` would exclude across the project tree.

    EPIC #333 — defense-in-depth privacy primitive. Walks the project,
    counts files that would be skipped per `.noraignore`, lists which
    factbook facts have `sources[]` pointing to ignored paths (those
    need migration: either soft-archive the fact OR un-ignore the path).

    Usage:
      kernora ignore-check [--project=<path>] [--show-files]
    """
    _add_app_to_path()
    args = sys.argv[2:]
    project_path = Path.cwd()
    show_files = False
    for i, a in enumerate(args):
        if a.startswith("--project="):
            project_path = Path(a.split("=", 1)[1]).expanduser()
        elif a == "--project" and i + 1 < len(args):
            project_path = Path(args[i + 1]).expanduser()
        elif a == "--show-files":
            show_files = True

    try:
        from noraignore import NoraIgnore, NORAIGNORE_FILENAME
    except ImportError as e:
        print(f"noraignore module unavailable: {e}", file=sys.stderr)
        return 1

    ig = NoraIgnore.from_project(project_path)
    if not ig.has_active_patterns():
        ignore_file = project_path / NORAIGNORE_FILENAME
        if ignore_file.exists():
            print(f"  {ignore_file} exists but contains no active patterns "
                  f"(everything is comments/blanks).")
        else:
            print(f"  No {NORAIGNORE_FILENAME} found at {project_path}. "
                  f"All files allowed.")
        return 0

    # Walk project (skip git/venv/node_modules by convention to keep it fast)
    SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__",
                 "target", "dist", "build", "kiro-extension/bundled"}
    ignored_files: list[Path] = []
    total = 0
    for p in project_path.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(project_path)
        except ValueError:
            continue
        # Skip well-known build/vendor dirs at scan time (matches walker behavior)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        total += 1
        if ig.is_ignored(p):
            ignored_files.append(rel)

    print(f"\n.noraignore status for {project_path}")
    print(f"  Patterns: {sum(1 for L in ig._patterns if L.strip() and not L.strip().startswith('#'))} active")
    print(f"  Files scanned:  {total}")
    print(f"  Files ignored:  {len(ignored_files)}  ({100*len(ignored_files)/max(total,1):.1f}%)")

    if show_files and ignored_files:
        print("\n  Ignored paths:")
        for p in sorted(ignored_files)[:50]:
            print(f"    {p}")
        if len(ignored_files) > 50:
            print(f"    … {len(ignored_files) - 50} more (rerun with --show-files | head -100)")

    # Cross-check existing factbook for sources pointing at ignored paths
    fb_path = project_path / ".nora" / f"{project_path.name}-factbook.yaml"
    if fb_path.exists():
        try:
            import yaml as _y
            doc = _y.safe_load(fb_path.read_text(encoding="utf-8")) or {}
            facts = [f for f in (doc.get("content") or []) if isinstance(f, dict)]
            flagged = []
            for fact in facts:
                fid = fact.get("id", "?")
                if fact.get("archived"):
                    continue
                for src in (fact.get("sources") or []):
                    src_str = str(src).split(":")[0].split("#")[0].strip().strip('"')
                    if src_str and ig.is_ignored(src_str):
                        flagged.append((fid, src_str))
                        break
            if flagged:
                print(f"\n  ⚠ {len(flagged)} factbook facts have sources pointing at ignored paths:")
                for fid, src in flagged[:20]:
                    print(f"    {fid} → {src}")
                print(f"\n  These need migration: either soft-archive the fact OR un-ignore the path.")
            else:
                print(f"\n  ✓ No factbook facts reference ignored paths.")
        except Exception as e:
            print(f"\n  factbook cross-check skipped: {e}")
    return 0


def cmd_ignore_test():
    """Test whether a single path would be ignored by `.noraignore`.

    Usage:
      kernora ignore-test <path>
    """
    _add_app_to_path()
    args = sys.argv[2:]
    if not args:
        print("usage: kernora ignore-test <path>", file=sys.stderr)
        return 2
    target = Path(args[0]).expanduser()
    project_path = Path.cwd()

    try:
        from noraignore import NoraIgnore
    except ImportError as e:
        print(f"noraignore module unavailable: {e}", file=sys.stderr)
        return 1

    ig = NoraIgnore.from_project(project_path)
    if not ig.has_active_patterns():
        print(f"no active .noraignore patterns; allowed: {target}")
        return 0
    if ig.is_ignored(target):
        print(f"IGNORED: {target}")
        return 0
    print(f"allowed: {target}")
    return 0


def cmd_fact_outcomes():
    """Per-fact engagement outcomes — the implicit reward signal for SFT.

    Joins engagement_events.fact_ids → patterns/decisions/reported_bugs ID
    space and aggregates: fires, accepted, declined, tokens_added_total,
    last_seen. Output: JSONL (default) or table.

    EPIC #308 / S1 — kernora LoRA v1. Foundation for SFT labeling. Every
    day of telemetry from now becomes training-grade automatically.

    Privacy invariant (T1): we read engagement_events (which contain
    project_hash + fact_ids only — no fact bodies, no PII) and join to
    fact NAMES locally. Output is operator-readable and never leaves the
    machine without explicit user action.

    Usage:
      kernora fact-outcomes [--project=<name>] [--format=jsonl|table]
                            [--min-fires=N]
    """
    _add_app_to_path()

    args = sys.argv[2:]
    project: Optional[str] = None
    fmt = "jsonl"
    min_fires = 1
    for i, a in enumerate(args):
        if a.startswith("--project="):
            project = a.split("=", 1)[1]
        elif a == "--project" and i + 1 < len(args):
            project = args[i + 1]
        elif a.startswith("--format="):
            fmt = a.split("=", 1)[1]
        elif a == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
        elif a.startswith("--min-fires="):
            min_fires = int(a.split("=", 1)[1])
        elif a == "--min-fires" and i + 1 < len(args):
            min_fires = int(args[i + 1])

    if fmt not in ("jsonl", "table"):
        print(f"unknown --format={fmt}; use 'jsonl' or 'table'", file=sys.stderr)
        return 2

    try:
        from db import get_conn, project_hash
    except Exception as e:
        print(f"db import failed: {e}", file=sys.stderr)
        return 1

    # Optional project filter — match the same hash recipe the hook writes.
    project_filter = ""
    project_args: tuple = ()
    if project:
        h = project_hash(project)
        if not h:
            print(f"project_hash('{project}') returned empty (install_salt missing?)", file=sys.stderr)
            return 1
        project_filter = " AND project_hash = ?"
        project_args = (h,)

    conn = get_conn()
    try:
        # Pass 1: walk engagement_events, accumulate per-fact-id counts.
        # fact_ids is JSON-encoded ints like "[212, 188, 196]".
        rows = conn.execute(
            f"SELECT fact_ids, outcome, tokens_added, ts FROM engagement_events "
            f"WHERE fact_ids IS NOT NULL AND fact_ids != '[]'{project_filter}",
            project_args,
        ).fetchall()
    except Exception as e:
        print(f"engagement_events query failed: {e}", file=sys.stderr)
        return 1

    import json as _json
    agg: Dict[int, Dict[str, Any]] = {}
    for fact_ids_json, outcome, tokens_added, ts in rows:
        try:
            fact_ids = _json.loads(fact_ids_json)
        except Exception:
            continue
        if not isinstance(fact_ids, list):
            continue
        for fid in fact_ids:
            if not isinstance(fid, int):
                continue
            slot = agg.setdefault(fid, {
                "fact_id": fid,
                "fires": 0,
                "accepted": 0,
                "declined": 0,
                "tokens_added_total": 0,
                "last_seen": None,
            })
            slot["fires"] += 1
            if outcome == "accepted":
                slot["accepted"] += 1
                slot["tokens_added_total"] += int(tokens_added or 0)
            else:
                slot["declined"] += 1
            if ts and (slot["last_seen"] is None or ts > slot["last_seen"]):
                slot["last_seen"] = ts

    # Pass 2: enrich with fact name + kind by looking up each id across
    # patterns / decisions / reported_bugs. We don't know the kind a priori
    # (engagement_events stores raw int ids), so probe each table.
    fact_ids_to_lookup = list(agg.keys())
    for fid in fact_ids_to_lookup:
        slot = agg[fid]
        slot["kind"] = None
        slot["name"] = None
        slot["factbook_id"] = None
        slot["project"] = None
        for kind, table, name_col in [
            ("pattern", "patterns", "name"),
            ("decision", "decisions", "decision"),
            ("incident", "reported_bugs", "title"),
        ]:
            try:
                row = conn.execute(
                    f"SELECT {name_col}, factbook_id, project FROM {table} WHERE id = ?",
                    (fid,),
                ).fetchone()
            except Exception:
                row = None
            if row:
                slot["kind"] = kind
                slot["name"] = row[0]
                slot["factbook_id"] = row[1]
                slot["project"] = row[2]
                break

    # Filter by min-fires + sort by fires desc.
    out_rows = [r for r in agg.values() if r["fires"] >= min_fires]
    out_rows.sort(key=lambda r: (-r["fires"], -r["accepted"]))

    if fmt == "jsonl":
        for r in out_rows:
            print(_json.dumps(r))
    else:  # table
        if not out_rows:
            print("no engagement events with fact_ids matched the filter.")
            return 0
        print(f"{'fact_id':<10}{'kind':<10}{'fires':<8}{'accept':<8}{'tokens':<10}{'name'}")
        print("-" * 90)
        for r in out_rows:
            name = (r.get("name") or "")[:50]
            print(
                f"{r['fact_id']:<10}{(r.get('kind') or '?'):<10}"
                f"{r['fires']:<8}{r['accepted']:<8}"
                f"{r['tokens_added_total']:<10}{name}"
            )
        print(f"\n{len(out_rows)} rows · {sum(r['fires'] for r in out_rows)} fires total")
    return 0


def cmd_export_sft():
    """SFT dataset builder for the Kernora LoRA pipeline.

    EPIC #308 / S2 — emits a chat-template JSONL of training pairs from three
    real-data sources. Each pair carries auditable metadata; nothing
    synthetic without an explicit --augment flag (S3, separate cmd).

    Sources & pair shape:
      1. factbook   — `.nora/<project>-factbook.yaml`. Per fact: prompt asks
                      what the fact says, completion cites it as
                      `Per kernora factbook ({id}): {statement}`.
      2. insights   — `echo.db.insights`. Per real (non-low-signal) summary:
                      prompt asks "what happened in this session?",
                      completion is the summary.
      3. engagement — `echo.db.engagement_events`. Per accepted fire with
                      fact_ids: prompt is the project + accepted-fact's
                      name; completion is the surfaced fact body.

    Output JSONL line shape (chat-template, MLX-LM friendly):
      { "messages": [
            {"role": "system", "content": <kernora persona>},
            {"role": "user",   "content": <prompt>},
            {"role": "assistant","content": <completion>}
        ],
        "metadata": { source_method, source_id, generated_at,
                      synthetic: false } }

    Usage:
      kernora export-sft [--project=<name>] [--out=<path>]
                         [--exclude-low-signal] [--exclude-fact-ids=fXX,fYY]
                         [--system-prompt=<path>]
    """
    _add_app_to_path()
    args = sys.argv[2:]
    project: Optional[str] = None
    out_path = "sft.jsonl"
    exclude_low_signal = True   # default on; insights table has many [low-signal:] placeholders
    exclude_ids: set = set()
    system_prompt_path: Optional[str] = None

    for i, a in enumerate(args):
        if a.startswith("--project="):
            project = a.split("=", 1)[1]
        elif a == "--project" and i + 1 < len(args):
            project = args[i + 1]
        elif a.startswith("--out="):
            out_path = a.split("=", 1)[1]
        elif a == "--out" and i + 1 < len(args):
            out_path = args[i + 1]
        elif a == "--include-low-signal":
            exclude_low_signal = False
        elif a.startswith("--exclude-fact-ids="):
            exclude_ids = {x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()}
        elif a == "--exclude-fact-ids" and i + 1 < len(args):
            exclude_ids = {x.strip() for x in args[i + 1].split(",") if x.strip()}
        elif a.startswith("--system-prompt="):
            system_prompt_path = a.split("=", 1)[1]

    if not project:
        # Default to the cwd's project name (a single-project sft is the
        # narrow-beats-broad expression of T4 — the LoRA is per-project).
        project = Path.cwd().name

    # ── System prompt ─────────────────────────────────────────────────────
    if system_prompt_path and Path(system_prompt_path).exists():
        sys_prompt = Path(system_prompt_path).read_text(encoding="utf-8").strip()
    else:
        sys_prompt = (
            "You are Nora, the project-optimized assistant for the kernora "
            "codebase. Answer grounded in the kernora factbook (.nora/"
            "kernora-factbook.yaml). Cite fact IDs (fXXX) when the answer "
            "comes from a verified fact. Prefer kernora-specific terminology "
            "over generic advice."
        )

    # ── Source 1: factbook YAML ───────────────────────────────────────────
    fb_path = Path.cwd() / ".nora" / f"{project}-factbook.yaml"
    if not fb_path.exists():
        # Some projects are kept in $HOME-relative paths; fall back to scan.
        for parent in [Path.home(), Path.home() / "code"]:
            cand = parent / project / ".nora" / f"{project}-factbook.yaml"
            if cand.exists():
                fb_path = cand
                break
    if not fb_path.exists():
        print(f"factbook not found for project '{project}' (looked at {fb_path})", file=sys.stderr)
        return 1

    try:
        import yaml as _y
        fb_doc = _y.safe_load(fb_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"factbook YAML load failed: {e}", file=sys.stderr)
        return 1

    fb_facts = [f for f in (fb_doc.get("content") or []) if isinstance(f, dict)]

    # ── Source 2: insights ────────────────────────────────────────────────
    try:
        from db import get_conn
    except Exception as e:
        print(f"db import failed: {e}", file=sys.stderr)
        return 1
    conn = get_conn()

    insight_rows: list = []
    try:
        q = (
            "SELECT session_id, summary, reusable_patterns FROM insights "
            "WHERE summary IS NOT NULL AND summary != '' AND LENGTH(summary) > 50"
        )
        if exclude_low_signal:
            q += " AND summary NOT LIKE '%low-signal%'"
        insight_rows = conn.execute(q).fetchall()
    except Exception as e:
        print(f"insights query failed: {e}", file=sys.stderr)

    # ── Source 3: engagement events with accepted fact_ids ────────────────
    eng_rows: list = []
    try:
        eng_rows = conn.execute(
            "SELECT fact_ids, tokens_added, ts FROM engagement_events "
            "WHERE outcome='accepted' AND fact_ids IS NOT NULL AND fact_ids != '[]'"
        ).fetchall()
    except Exception:
        pass

    # Build a sqlite-id → factbook-id map for engagement enrichment.
    # patterns/decisions/reported_bugs each may carry factbook_id.
    sqlite_to_fb: Dict[int, Dict[str, Any]] = {}
    for kind, table, name_col in [
        ("pattern", "patterns", "name"),
        ("decision", "decisions", "decision"),
        ("incident", "reported_bugs", "title"),
    ]:
        try:
            rows = conn.execute(
                f"SELECT id, {name_col}, factbook_id FROM {table}"
            ).fetchall()
        except Exception:
            rows = []
        for rid, rname, fb_id in rows:
            if rid in sqlite_to_fb:
                continue
            sqlite_to_fb[rid] = {"kind": kind, "name": rname, "factbook_id": fb_id}

    # ── Pair builders ─────────────────────────────────────────────────────
    pairs: list = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. fact baseline pairs
    fact_count = 0
    for fact in fb_facts:
        fid = fact.get("id") or ""
        if fid in exclude_ids:
            continue
        name = (fact.get("name") or "").strip()
        summary = (fact.get("summary") or "").strip()
        statement = (fact.get("statement") or "").strip()
        category = (fact.get("category") or "").strip()
        if not statement:
            statement = summary or name
        if not statement or len(statement) < 20:
            continue

        # Build a question that this fact answers. Prefer summary-as-prompt
        # (already a one-liner) when present; fall back to a templated form.
        if summary and len(summary) > 15:
            user_prompt = f"What does kernora say about: {summary.rstrip('.?!')}?"
        elif name:
            user_prompt = f"What's the kernora rule on {name.replace('-', ' ')}?"
        else:
            user_prompt = f"What's documented in factbook fact {fid}?"

        completion = f"Per kernora factbook ({fid}): {statement}"
        if category:
            completion += f"\n\nCategory: {category}."

        pairs.append({
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": completion},
            ],
            "metadata": {
                "source_method": "fact",
                "source_id": fid,
                "generated_at": now_iso,
                "synthetic": False,
            },
        })
        fact_count += 1

    # 2. insight pairs
    import json as _json
    insight_count = 0
    for sid, summary, reusable in insight_rows:
        if not summary:
            continue
        s = summary.strip()
        if len(s) < 50:
            continue
        # Prompt asks "what happened in this session" — keeps it simple
        # and lets the LoRA learn distillation style.
        user_prompt = (
            "Summarize the engineering session that produced these notes: "
            "(1-2 sentences, in the kernora factbook voice — concrete, "
            "imperative, naming files/funcs)."
        )
        # Optional reinforcement: include the patterns the analyzer surfaced.
        completion = s
        if reusable and reusable not in ("[]", "null"):
            try:
                pats = _json.loads(reusable)
                if isinstance(pats, list) and pats:
                    p_summary = "; ".join(
                        str(p.get("pattern") if isinstance(p, dict) else p)[:120]
                        for p in pats[:3]
                    )
                    if p_summary:
                        completion += f"\n\nKey patterns: {p_summary}"
            except Exception:
                pass
        pairs.append({
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": completion},
            ],
            "metadata": {
                "source_method": "insight",
                "source_id": sid,
                "generated_at": now_iso,
                "synthetic": False,
            },
        })
        insight_count += 1

    # 3. engagement pairs (accepted fires)
    engagement_count = 0
    seen_eng_keys: set = set()
    for fact_ids_json, tokens_added, ts in eng_rows:
        try:
            fids = _json.loads(fact_ids_json)
        except Exception:
            continue
        if not isinstance(fids, list):
            continue
        for fid in fids:
            if not isinstance(fid, int):
                continue
            meta = sqlite_to_fb.get(fid)
            if not meta or not meta.get("name"):
                continue
            key = (fid, meta["name"][:40])
            if key in seen_eng_keys:
                continue
            seen_eng_keys.add(key)

            user_prompt = (
                f"In the kernora codebase, what should I know about: "
                f"{meta['name']}?"
            )
            completion = (
                f"Kernora has accepted this {meta['kind']} as relevant via "
                f"+nora injection (sqlite id={fid}"
                + (f", factbook_id={meta['factbook_id']}" if meta.get("factbook_id") else "")
                + f"): {meta['name']}."
            )
            pairs.append({
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": completion},
                ],
                "metadata": {
                    "source_method": "engagement",
                    "source_id": fid,
                    "generated_at": now_iso,
                    "synthetic": False,
                    "tokens_added_when_accepted": tokens_added,
                    "engagement_ts": ts,
                },
            })
            engagement_count += 1

    # ── Emit ─────────────────────────────────────────────────────────────
    out_p = Path(out_path).expanduser()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with out_p.open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(_json.dumps(p, ensure_ascii=False) + "\n")

    # ── Stats ─────────────────────────────────────────────────────────────
    char_lens = [
        sum(len(m["content"]) for m in p["messages"]) for p in pairs
    ]
    if char_lens:
        avg_len = sum(char_lens) / len(char_lens)
        max_len = max(char_lens)
    else:
        avg_len = max_len = 0

    print(f"wrote {out_p}")
    print(f"  total pairs:       {len(pairs)}")
    print(f"  fact pairs:        {fact_count}")
    print(f"  insight pairs:     {insight_count}")
    print(f"  engagement pairs:  {engagement_count}")
    print(f"  avg chars/pair:    {avg_len:.0f}")
    print(f"  max chars/pair:    {max_len}")
    print(f"  synthetic ratio:   0% (run --augment via S3 to add synthetic prompts)")
    if len(pairs) < 800:
        print(f"\n  ⚠ Below 800-pair floor (have {len(pairs)}). Consider running")
        print(f"    `kernora export-sft-augment` (S3) to add synthetic prompts.")
    return 0


def cmd_export_verifier_set():
    """Verifier-corpus JSONL exporter (Stage 4).

    Thin dispatcher → db.build_verifier_corpus_rows (single canonical impl, f388).
    Emits labeled training examples from verification_labels + D2 usage JOINs.

    Each row has a `head` field:
      - hypothesis IS NOT NULL → head='nli'  {premise, hypothesis, label}
      - hypothesis IS NULL     → head='verdict' {factlet, verdict}

    Default: terminal-state-per-fact_id. --include-history for full chain.
    --egress-only: restrict to egress_ok=1 (Zone-Y T1 pool).
    --balance: reserved ML epic stub (§10-M7).

    Usage:
      kernora export-verifier-set [--out=<path>] [--egress-only]
                                  [--include-history] [--balance]
    """
    import json as _json

    _add_app_to_path()
    args = sys.argv[2:]
    out_path = "verifier_corpus.jsonl"
    egress_only = False
    include_history = False
    balance = False

    for i, a in enumerate(args):
        if a.startswith("--out="):
            out_path = a.split("=", 1)[1]
        elif a == "--out" and i + 1 < len(args):
            out_path = args[i + 1]
        elif a == "--egress-only":
            egress_only = True
        elif a == "--include-history":
            include_history = True
        elif a == "--balance":
            balance = True

    if balance:
        print("  --balance: reserved for ML epic (§10-M7) — no-op in Stage 4", file=sys.stderr)

    try:
        from db import get_conn, build_verifier_corpus_rows
    except Exception as e:
        print(f"db import failed: {e}", file=sys.stderr)
        return 1
    conn = get_conn()
    try:
        pairs = build_verifier_corpus_rows(
            conn, egress_only=egress_only, include_history=include_history
        )
    except Exception as e:
        print(f"build_verifier_corpus_rows failed: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    # §10-B1: split heads into two files (never mix). Single writer impl in db.py (f388).
    from db import write_verifier_corpus_files as _wvcf
    info = _wvcf(pairs, out_path)
    print(f"wrote {info['nli_path']}  ({info['nli_count']} nli-head rows)")
    print(f"wrote {info['verdict_path']}  ({info['verdict_count']} verdict-head rows)")
    print(f"  total rows:    {info['total']}")
    print(f"  egress_ok:     {info['egress_count']}")
    print(f"  mode:          {'terminal-state' if not include_history else 'full-history'}")
    if egress_only:
        print(f"  filter:        egress_ok=1 only")
    return 0


def cmd_roi():
    """Return-on-Intelligence report.

    BATCH-003 (lf001): Lite branch — reads JSONL via nora_jsonl
    (engagement_events.jsonl + factbook_audit.jsonl) so no daemon / DB needed.
    Companion branch — kernora_roi.py LLM-graded SQLite path.

    Both branches respect the same shape (totals + top-cited facts) so the
    user gets a useful report regardless of mode.
    """
    _add_app_to_path()

    # ─── Lite branch (BATCH-003) ────────────────────────────────────────
    try:
        import kernora_mode as _km
        lite = _km.is_lite()
    except Exception:
        lite = False

    # Parse --format early so Lite branch can emit the stderr note (LD#11)
    _roi_args = sys.argv[2:]
    _format_val = None
    _format_idx = None
    for _i, _a in enumerate(_roi_args):
        if _a.startswith("--format="):
            _format_val = _a.split("=", 1)[1]
            _format_idx = _i
        elif _a == "--format" and _i + 1 < len(_roi_args):
            _format_val = _roi_args[_i + 1]
            _format_idx = _i

    if lite:
        # LD#11: --format is out of scope in Lite mode; emit one-line note
        if _format_val is not None:
            print("[Nora] --format flag has no effect in Lite mode", file=sys.stderr)

        try:
            import nora_jsonl as _nj
        except Exception as e:
            _err(f"nora_jsonl unavailable: {e}")
            return 1
        from collections import Counter as _Counter

        # Engagement aggregates over the last 7 days
        events = _nj.read_engagement(since_days=7)
        accepted = sum(1 for e in events if e.get("outcome") == "accepted")
        abstained = sum(1 for e in events if e.get("outcome") == "abstained")
        timed_out = sum(1 for e in events if e.get("outcome") == "timeout")
        tokens_total = sum(int(e.get("tokens_added") or 0) for e in events)
        cited: _Counter = _Counter()
        for e in events:
            for fid in (e.get("fact_ids") or []):
                cited[fid] += 1

        # Factbook fact count — read .nora/<project>-factbook.yaml count if
        # available, else fall back to scanning all .nora/*-factbook.yaml.
        fact_total = 0
        try:
            from pathlib import Path as _P
            for ny in (_P.cwd() / ".nora").glob("*factbook.yaml"):
                try:
                    text = ny.read_text(encoding="utf-8")
                    # Count `- id:` markers — matches lite-mode-factbook.yaml shape
                    fact_total += text.count("\n- id:")
                except Exception:
                    pass
        except Exception:
            pass

        # Audit aggregates over 30 days
        audit = _nj.read_audit(since_days=30)
        ops = _Counter(a.get("op", "?") for a in audit)

        _header(f"Return on Intelligence — Lite mode (last 7d)")
        print(f"  Total facts (.nora/):    {fact_total}")
        # outcome='accepted' = Nora injected ≥1 factlet; 'abstained' = nothing
        # relevant to inject (NOT a user dismissal — see nora_context.py). Label
        # honestly as grounding, consistent with the dashboard "Grounding rate".
        print(f"  +nora calls:             {accepted} grounded · {abstained} no match · {timed_out} timeout")
        print(f"  Tokens injected:         {tokens_total}")
        print(f"  Audit ops (30d):         add={ops.get('add', 0)} update={ops.get('update', 0)} "
              f"delete={ops.get('delete', 0)} undo={ops.get('undo', 0)}")
        print()
        if cited:
            print(f"  Top cited facts (last 7d):")
            for fid, n in cited.most_common(5):
                print(f"    fact_id={fid:<6}  {n}×")
        else:
            print(f"  {DIM}No fact citations recorded yet — try `+nora <prompt>` in your IDE.{RESET}")
        print()
        print(f"  {DIM}Companion mode adds LLM-graded ROI scoring + dashboard charts.{RESET}")
        print(f"  {DIM}Flip with `kernora config set mode=companion`.{RESET}\n")
        return 0

    # ─── Companion branch (existing SQLite + LLM grading) ──────────────
    # Inject --format into argv for kernora_roi.main to pick up via argparse
    _companion_args = list(_roi_args)
    # Only inject if --format is present and not already handled by kernora_roi.main
    try:
        import kernora_roi
    except ImportError:
        _err("kernora_roi.py not found — run: kernora install")
        return 1
    return kernora_roi.main(_companion_args)


def cmd_undo() -> int:
    """BATCH-003 (lf005): list recent retirements OR un-retire a specific id.

    Usage:
      kernora undo                  # list undo-window candidates
      kernora undo <retirement_id>  # restore that retirement
    """
    args = sys.argv[2:]
    try:
        from capture import undo_retirement as _undo  # type: ignore
        from db import get_conn as _gc  # type: ignore
    except Exception as e:
        _err(f"capture/db modules unavailable: {e}")
        return 1

    if not args:
        # List recent — show retirements still inside the 90-day window
        conn = _gc()
        if conn is None:
            _err("DB unavailable")
            return 1
        try:
            rows = conn.execute(
                "SELECT id, fact_id, reason, retired_at, undo_until "
                "FROM factbook_retirements "
                "WHERE undone_at IS NULL AND undo_until > datetime('now') "
                "ORDER BY retired_at DESC LIMIT 20"
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            print("No undoable retirements in the 90-day window.")
            return 0
        print(f"\n{len(rows)} undoable retirements (90-day window):\n")
        for r in rows:
            rid, fid, reason, retired_at, undo_until = r[0], r[1], r[2], r[3], r[4]
            ra = (retired_at or "")[:19]
            uu = (undo_until or "")[:10]
            print(f"  retirement_id={rid:<5}  fact_id={fid:<5}  reason={reason:<12}  "
                  f"retired={ra}  undo_until={uu}")
        print(f"\nUndo with: kernora undo <retirement_id>\n")
        return 0

    # Un-retire by retirement_id
    try:
        rid = int(args[0])
    except ValueError:
        _err(f"retirement_id must be an integer, got {args[0]!r}")
        return 2
    res = _undo(rid)
    mark = GREEN + "✓" + RESET if res.get("ok") else RED + "✗" + RESET
    print(f"{mark} {res.get('reason', '?')}" +
          (f"  (fact_id={res.get('fact_id')})" if res.get("fact_id") else ""))
    return 0 if res.get("ok") else 1


_TOUR_STEPS: list[tuple[str, str, str]] = [
    ("`+nora`",
     "Inject relevant facts at the start of an AI prompt (works in any IDE chat).",
     "+nora how should I structure this auth flow?"),
    ("kernora scan",
     "Build factbook from project artifacts (LLM-orchestrated via your IDE).",
     "kernora scan ."),
    ("kernora learn",
     "Distill candidate facts from the last AI session.",
     "kernora learn"),
    ("kernora review",
     "Approve / reject pending fact candidates (Lite uses CLI; Companion uses dashboard).",
     "kernora capture --pending"),
    ("kernora consolidate",
     "Dedup + supersession pass (Dreamer replacement in Lite).",
     "kernora consolidate"),
    ("kernora pe-review",
     "Multi-domain PE review panel via your IDE LLM.",
     "kernora pe-review"),
    ("kernora coe",
     "5-Whys correction-of-errors investigation.",
     'kernora coe-last 5'),
    ("kernora roi",
     "Compounding-intelligence aggregates (Lite reads JSONL; Companion reads SQLite).",
     "kernora roi"),
    ("kernora license",
     "Activate, check, or remove a Pro/Enterprise license (persisted in Keychain).",
     "kernora license status"),
]


def cmd_tour() -> int:
    """BATCH-003 (lf403): 9-step interactive walkthrough of every Nora command.

    The single source of truth for "what can I do with Nora" — README quickstart
    and `cmd_help` reference this list. `--non-interactive` prints all 9 steps
    without prompting (used by docs/CI runs).
    """
    args = sys.argv[2:]
    non_interactive = "--non-interactive" in args or "-y" in args
    print()
    print(f"{BOLD}Welcome to Nora — a 9-step tour of the CLI.{RESET}")
    print(f"{DIM}Each step shows: what it does + an example you can try.{RESET}")
    if non_interactive:
        print(f"{DIM}(Running non-interactively — printing all 9 steps without prompting.){RESET}")
    print()
    for i, (cmd, desc, example) in enumerate(_TOUR_STEPS, 1):
        print(f"{BOLD}[{i}/{len(_TOUR_STEPS)}] {cmd}{RESET}")
        print(f"  {desc}")
        print(f"  Example: {DIM}{example}{RESET}")
        if non_interactive:
            print()
            continue
        try:
            ans = input("  [t] try, [s] skip, [n] next, [q] quit > ").strip().lower()
        except EOFError:
            # Stdin closed (piped/CI usage). Treat as non-interactive — print and continue.
            print()
            continue
        if ans == "q":
            print("\nTour aborted.")
            return 0
        if ans == "t":
            print(f"  Running: {example}")
            # Strip surrounding backticks if any
            cmd_to_run = example.strip().strip("`")
            try:
                import subprocess as _sp
                _sp.call(cmd_to_run, shell=True)
            except Exception as e:
                _warn(f"Could not run example: {e}")
        print()
    print(f"{BOLD}Tour complete.{RESET}  Run `kernora help` for the full command list.\n")
    return 0


def known_projects(db_path=None) -> list:
    """Distinct project names recorded in echo.db, most recent first.

    Sources sessions.project — NOT nora_metrics, which has no project column
    (CONV-P1, 2026-07-06: the old inline query swallowed the OperationalError
    and /projects always printed a false "No projects found").
    """
    import sqlite3 as _sq
    if db_path:
        db_path = Path(db_path)
    else:
        # batch-1 PE LOW: honor the unified DB env contract (db.py DUP-fix
        # 2026-06-01) instead of hardcoding the default home path.
        _env = os.environ.get("KERNORA_DB_PATH") or os.environ.get("KERNORA_DB")
        db_path = Path(_env) if _env else (Path.home() / ".kernora" / "echo.db")
    if not db_path.exists():
        return []
    conn = _sq.connect(str(db_path), timeout=5)
    try:
        rows = conn.execute(
            "SELECT project FROM sessions WHERE project IS NOT NULL AND project != '' "
            "GROUP BY project ORDER BY MAX(started_at) DESC LIMIT 20"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def cmd_chat() -> int:
    """Terminal-native chat REPL backed by the running Nora dashboard.

    Usage:
      nora chat                              # REPL (cwd-resolved project)
      nora chat --project kernora            # explicit project
      nora chat --model claude-opus-4-7      # explicit model
      nora chat -p "question"                # one-shot (no REPL), pipe-safe

    Slash commands in REPL:
      /help                show available commands
      /model <id>          swap model mid-session
      /models              list available models
      /project <name>      swap active project
      /projects            list known projects
      /history             show conversation so far
      /clear               clear conversation history
      /exit                quit (also Ctrl-D)

    The chat backend is the live Flask daemon at localhost:2742.
    If the daemon is not running, start it with: kernora start
    """
    import argparse as _ap
    import sys as _sys
    import json as _json
    import os as _os

    # ── Parse args ──────────────────────────────────────────────────────────
    p = _ap.ArgumentParser(prog="nora chat", description="Terminal-native Nora chat", add_help=True)
    p.add_argument("--project", "-P", default=None, help="Project name (default: cwd-resolved)")
    p.add_argument("--model", "-m", default=None, help="Model ID (default: grok-4-1-fast-reasoning)")
    p.add_argument("-p", "--prompt", default=None, help="One-shot prompt (skips REPL)")
    args, _ = p.parse_known_args(_sys.argv[2:])

    # ── Available models (mirrored from Agent.tsx BASE_MODELS) ───────────────
    # v59: trimmed to backend-routed models only. Adding gpt-4o, gemini-*,
    # sonar-* to this list silently falls through to Ollama and produces a
    # confusing model-not-found error (internal-rule — silent-fallback
    # anti-pattern). When backend routing for openai/google/perplexity families
    # lands in dashboard.py:1024+, re-add the corresponding entries here AND
    # mirror in nora-ui/screens/Agent.tsx BASE_MODELS.
    _BASE_MODELS = [
        {"id": "grok-4-1-fast-reasoning",  "label": "Grok 4.1 Fast (cloud)",     "family": "grok"},
        {"id": "claude-sonnet-4-5",        "label": "Claude Sonnet 4.5 (cloud)", "family": "claude"},
        {"id": "claude-opus-4-7",          "label": "Claude Opus 4.7 (cloud)",   "family": "claude"},
    ]

    # ── Token for authenticating against Flask (D1 invariant) ───────────────
    def _read_token() -> str:
        token_path = Path.home() / ".kernora" / "dashboard.token"
        if token_path.exists():
            return token_path.read_text().strip()
        return ""

    # ── Daemon health check ──────────────────────────────────────────────────
    def _daemon_up() -> bool:
        try:
            import urllib.request as _ur
            req = _ur.Request("http://127.0.0.1:2742/", method="GET")
            with _ur.urlopen(req, timeout=2):
                pass
            return True
        except Exception:
            return False

    if not _daemon_up():
        _err("Nora dashboard is not running.")
        _info("Start it with: kernora start")
        return 1

    # ── Resolve project from cwd if not supplied ─────────────────────────────
    project = args.project
    if not project:
        try:
            from memory_bridge import find_factbook_for_cwd as _ffcwd
            fb = _ffcwd()
            if fb:
                # .nora/<name>-factbook.yaml → extract <name>
                stem = fb.stem  # e.g. "kernora-factbook"
                project = stem.replace("-factbook", "")
        except Exception as _pe:
            print(f"[FALLBACK] project resolution failed: {_pe}", file=_sys.stderr)

    model = args.model or _BASE_MODELS[0]["id"]

    # ── SSE streaming helper ─────────────────────────────────────────────────
    def _stream_chat(prompt_text: str, proj: str, mdl: str, is_tty: bool):
        """POST to /api/agent/stream, consume SSE, print deltas.

        Returns (full_response_text, factlets_injected_list).
        Raises RuntimeError on HTTP error or stream error event.
        """
        import urllib.request as _ur
        import urllib.error as _ue

        token = _read_token()
        if not token:
            _err("No auth token at ~/.kernora/dashboard.token.")
            _err("→ Daemon may still be initializing. Wait a moment, or check: kernora status")
            raise RuntimeError("no_auth_token")

        payload = _json.dumps({
            "model": mdl,
            "prompt": prompt_text,
            "project": proj or "",
        }).encode()

        req = _ur.Request(
            "http://127.0.0.1:2742/api/agent/stream",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Nora-Token": token,
            },
            method="POST",
        )

        full_text = []
        factlets: list[str] = []
        # B1 fix (v51): initialize grounding signals — these survive to return value
        grounding_pct: float | None = None
        grounding_calibrating: bool = False
        lfw_count: int = 0

        # urllib chunked-SSE: relies on Flask flushing per-event. Dev server
        # (Werkzeug) flushes on \n\n boundary. If a future move to gunicorn
        # introduces buffering, add Response(headers={"X-Accel-Buffering": "no"})
        # on the Flask side OR switch this loop to httpx with stream=True.
        # (internal-rule — surface failure loudly if stream times out at 120s.)
        _STREAM_READ_TIMEOUT = 120

        # D15 — CLI SSE loop uses done-flag pattern (not break) per §10.H-1.
        # meta event arrives AFTER done:true; breaking on done would miss it.
        _stream_done = False
        factlet_details_list: list[dict] = []

        try:
            with _ur.urlopen(req, timeout=_STREAM_READ_TIMEOUT) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        evt = _json.loads(data_str)
                    except _json.JSONDecodeError as _jde:
                        # f404 — log malformed SSE lines loudly; skipping is
                        # correct but silent swallow is forbidden.
                        print(
                            f"[SSE-PARSE] malformed SSE data line skipped: {_jde} | raw={data_str[:120]!r}",
                            file=sys.stderr,
                        )
                        continue

                    if "error" in evt:
                        raise RuntimeError(evt["error"])

                    if "meta" in evt:
                        # Server emits extended meta (Task #450): factlet_details, grounding_pct, lfw_count
                        meta = evt["meta"]
                        fact_ids = meta.get("fact_ids", [])
                        n_injected = meta.get("factlets_injected", len(fact_ids))
                        if fact_ids:
                            factlets = fact_ids
                        elif n_injected:
                            # fact_ids absent but count present — surface count without IDs
                            factlets = [f"f?" for _ in range(n_injected)]
                        # Capture citation strip data for _print_citation_strip
                        factlet_details_list = meta.get("factlet_details", [])
                        # B1 fix (v51): assign to non-underscore locals so they survive return
                        grounding_pct = meta.get("grounding_pct")
                        grounding_calibrating = meta.get("grounding_calibrating", False)
                        lfw_count = meta.get("lfw_count", 0)
                        # If we had done before meta, exit now
                        if _stream_done:
                            break

                    if "delta" in evt:
                        chunk = evt["delta"]
                        full_text.append(chunk)
                        if is_tty:
                            print(chunk, end="", flush=True)

                    if evt.get("done"):
                        # D15 — set flag, continue iterating (meta comes after done)
                        _stream_done = True
                        continue

        except _ue.HTTPError as he:
            raise RuntimeError(f"HTTP {he.code}: {he.reason}") from he

        if is_tty:
            print()  # newline after streamed response

        if not is_tty:
            print("".join(full_text))

        # B1 fix (v51): return grounding signals so callers can surface them
        return "".join(full_text), factlets, factlet_details_list, grounding_pct, grounding_calibrating, lfw_count

    # ── Citation strip printer (Task #450) ───────────────────────────────────
    # §11 manifest item 5: _print_factlets → _print_citation_strip.
    # Backward-compat: _print_factlets kept as alias for non-citation callers.
    # D8: reads the same SSE payload shape as Agent.tsx.
    #
    # v60 compact mode: by default prints one line per factlet (chip format).
    # Full bars + source + glossary only when KERNORA_CHAT_VERBOSE=1 is set.
    # Set KERNORA_CHAT_VERBOSE=1 for full citation details.
    # This mirrors the v60 collapsible-by-default CitationStrip in Agent.tsx.
    def _print_citation_strip(
        factlet_details: list[dict],
        grounding_pct: "float | None" = None,
        grounding_calibrating: bool = False,
        lfw_count: int = 0,
    ):
        """Print per-factlet citation strip with Unicode FactSignal bars.

        Reads factlet_details from the SSE meta event (Task #450). Falls back
        gracefully when factlet_details is empty (f404 — no silent blank block).

        v60 compact mode (default): one chip line per factlet: [fid] stmt · X/5
        Full mode (KERNORA_CHAT_VERBOSE=1): bars + conf/eff/prior + source.

        v51 fixes: B1 grounding footer, H1 legend header, L1 factlet count,
        M1 drop empty source, M2 flatten embedded newlines, M3 calibrating banner,
        L2 plural prior usages.
        """
        import os
        if not factlet_details:
            return
        verbose = os.environ.get("KERNORA_CHAT_VERBOSE", "").strip() == "1"
        # Founder refinement (2026-05-21): opt-in vertical signal-bar mode
        # (ascending phone/wifi-signal glyphs) via KERNORA_FACTSIGNAL_VERTICAL=1.
        # Default stays horizontal (■■■■□) so existing output is unchanged.
        signal_vertical = os.environ.get("KERNORA_FACTSIGNAL_VERTICAL", "").strip() == "1"
        try:
            from nora_mcp import (
                _render_factsignal_bars as _fs_bars,
                _factsignal_trust_color as _fs_trust_color,
            )
        except Exception:
            def _fs_trust_color(score):  # pragma: no cover - fallback
                # Traffic-light trust scale (low→high = red→amber→green); dark
                # enough for a LIGHT terminal. Mirrors nora_mcp.
                s = max(1, min(5, int(score)))
                if s <= 2:
                    return "\x1b[38;5;160m"   # red — low trust (#d70000)
                if s == 3:
                    return "\x1b[38;5;136m"   # amber — medium trust (#af8700)
                return "\x1b[38;5;28m"        # green — high trust (#008700)

            def _fs_bars(score, vertical=False):  # pragma: no cover - fallback
                # Fallback mirrors nora_mcp: strength encoded in the GLYPHS —
                # first `score` positions are ascending solid bars (▁▂▃▄▅), the
                # rest are an empty marker (·), so 2/5 (▁▂···) ≠ 5/5 (▁▂▃▄▅) in
                # plain text (primary channel, WCAG 1.4.1). ANSI color (lit bars
                # on the red→amber→green trust scale / empty dim) is additive.
                s = max(1, min(5, int(score)))
                if vertical:
                    lit_glyphs = ("▁", "▂", "▃", "▄", "▅")
                    empty = "·"
                    glyphs = [lit_glyphs[i] if i < s else empty for i in range(5)]
                    use_color = (
                        os.environ.get("KERNORA_FACTSIGNAL_FORCE_COLOR", "").strip() == "1"
                        or sys.stdout.isatty()
                    )
                    if not use_color:
                        return "".join(glyphs)
                    lit, dim, rst = _fs_trust_color(s), "\x1b[38;5;240m", "\x1b[0m"
                    return "".join(
                        f"{(lit if i < s else dim)}{glyphs[i]}{rst}" for i in range(5)
                    )
                return "■" * s + "□" * (5 - s)
        print()
        n = len(factlet_details)
        if verbose:
            # H1 fix (v51): one-line legend at top so first-time users know what bars mean
            _legend_high = _fs_bars(5, vertical=signal_vertical)
            _legend_low = _fs_bars(1, vertical=signal_vertical)
            print(
                f"{DIM}━ Citations ━ FactSignal: {_legend_high} 5/5 = high-confidence + high-effectiveness"
                f" + has source · {_legend_low} 1/5 = low signal{RESET}"
            )
            # v52: second-line glossary expands abbreviations for explorer persona
            # (conf / eff % / prior usages were opaque to first-time users)
            print(
                f"{DIM}    conf = factlet confidence (0-1)"
                f" · eff = how often this factlet improved past answers"
                f" · prior usages = times cited before{RESET}"
            )
            # L1 fix (v51): factlet count header
            print(f"{DIM}{n} factlet{'s' if n != 1 else ''} cited{RESET}")
        else:
            # Compact header: just the count
            print(f"{DIM}{n} factlet{'s' if n != 1 else ''} cited  (KERNORA_CHAT_VERBOSE=1 for details){RESET}")
        for fd in factlet_details:
            fid = fd.get("id", "?")
            stmt = fd.get("statement_truncated", "")
            # M2 fix (v51): collapse embedded \n + excess whitespace to single line
            stmt = " ".join(stmt.split())
            conf = fd.get("confidence", 0.0)
            eff = fd.get("eff_pct", 0)
            prior = fd.get("prior_usages", 0)
            fs = fd.get("fact_signal", 1)
            src = fd.get("source", "(no source)")
            lfw = fd.get("lfw", False)
            lfw_mark = f" {DIM}⚠{RESET}" if lfw else ""
            if verbose:
                # Unicode bars: horizontal (■/□) or vertical ascending signal
                # meter (▁▂▃▄▅ lit + · empty) when KERNORA_FACTSIGNAL_VERTICAL=1;
                # solid-bar count == score, so strength reads in plain text.
                bars = _fs_bars(fs, vertical=signal_vertical)
                # L2 fix (v51): correct pluralization of "prior usage(s)"
                usage_label = f"{prior} prior usage{'s' if prior != 1 else ''}"
                # M1 fix (v51): omit Source line when value is empty / "(no source)"
                src_line = (
                    f"\n  {DIM}Source: {src}{RESET}"
                    if src and src not in ("(no source)", "")
                    else ""
                )
                # v53 / H3 fix: append "(calibrating)" when row received the bump
                calibrating_suffix = " (calibrating)" if fd.get("is_calibrating") else ""
                # Founder review 2026-05-21: color the N/5 score label on the
                # same red→amber→green trust scale as the lit bars (secondary
                # channel — the "N/5" digits still read without color).
                _trust = _fs_trust_color(fs)
                _score_label = f"{_trust}{fs}/5 FactSignal{RESET}"
                print(
                    f"{DIM}[{fid}]{RESET} {stmt}\n"
                    f"  {BOLD}{bars}{RESET} {_score_label}{calibrating_suffix}"
                    f" · conf {conf:.2f} · eff {eff}% · {usage_label}{lfw_mark}"
                    f"{src_line}"
                )
            else:
                # v60 compact: one chip per factlet — [fid] truncated · X/5
                # Truncate statement to ~60 chars for terminal readability
                stmt_short = stmt[:60] + "…" if len(stmt) > 60 else stmt
                print(f"{DIM}[{fid}]{RESET} {stmt_short}{lfw_mark} {DIM}· {fs}/5{RESET}")
        # M3 + B1 follow-through (v51): grounding footer after all factlet rows
        if grounding_calibrating:
            print(
                f"{DIM}⚠ Grounding still calibrating — needs ≥5 sessions of feedback"
                f" before grounding-% is reliable.{RESET}"
            )
        elif grounding_pct is not None:
            print(
                f"{DIM}Grounding: {grounding_pct}% — answer text overlaps factlet"
                f" keywords (estimated){RESET}"
            )

    def _print_factlets(fids: list[str]):
        """Backward-compat alias — used when only fact_ids are available."""
        if fids:
            print(f"{DIM}[{len(fids)} factlet{'s' if len(fids) != 1 else ''} injected: {', '.join(fids)}]{RESET}")

    # ── One-shot mode ────────────────────────────────────────────────────────
    if args.prompt:
        is_tty = _os.isatty(_sys.stdout.fileno())
        try:
            # B1 fix (v51): destructure 6-tuple — grounding signals now flow through
            _, factlets, _fdetails, _gpct, _gcal, _lfw = _stream_chat(
                args.prompt, project or "", model, is_tty
            )
            if is_tty:
                if _fdetails:
                    _print_citation_strip(_fdetails, _gpct, _gcal, _lfw)
                else:
                    _print_factlets(factlets)
        except RuntimeError as exc:
            _err(f"Chat error: {exc}")
            return 1
        return 0

    # ── REPL mode ────────────────────────────────────────────────────────────
    is_tty = _os.isatty(_sys.stdout.fileno())

    # Factlet count for banner
    factlet_count = 0
    try:
        fb_path = Path.cwd() / ".nora" / f"{project}-factbook.yaml"
        if not fb_path.exists() and project:
            # try alternate parent walk
            for parent in Path.cwd().parents:
                cand = parent / ".nora" / f"{project}-factbook.yaml"
                if cand.exists():
                    fb_path = cand
                    break
        if fb_path.exists():
            import re as _re
            content = fb_path.read_text(errors="replace")
            factlet_count = len(_re.findall(r"^- id:", content, _re.MULTILINE))
    except Exception:
        pass

    proj_label = project or "(no project)"
    print(f"\n{BOLD}Nora — chat{RESET}  ({proj_label} · {factlet_count} factlets · model: {model})")
    print(f"{DIM}Type /help for commands. Ctrl-D or /exit to leave.{RESET}\n")

    conversation: list[dict] = []  # {role, content}

    def _slash_help():
        print(f"""
  {CYAN}/help{RESET}             show this help
  {CYAN}/model <id>{RESET}       swap model mid-session
  {CYAN}/models{RESET}           list available models
  {CYAN}/project <name>{RESET}   swap active project
  {CYAN}/projects{RESET}         list known projects
  {CYAN}/history{RESET}          show conversation so far
  {CYAN}/clear{RESET}            clear conversation history
  {CYAN}/exit{RESET}             quit (also Ctrl-D)
""")

    nonlocal_state = {"project": project, "model": model}

    while True:
        try:
            user_input = input(f"{BOLD}>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        # ── Slash commands ───────────────────────────────────────────────────
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd_word = parts[0].lower()
            cmd_arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd_word in ("/exit", "/quit", "/q"):
                print("Goodbye.")
                break

            elif cmd_word == "/help":
                _slash_help()

            elif cmd_word == "/models":
                print(f"\n{BOLD}Available models:{RESET}")
                for m in _BASE_MODELS:
                    marker = f"{GREEN}*{RESET}" if m["id"] == nonlocal_state["model"] else " "
                    print(f"  {marker} {m['id']}  {DIM}({m['label']}){RESET}")
                print()

            elif cmd_word == "/model":
                _base_model_ids = [m["id"] for m in _BASE_MODELS]
                if not cmd_arg:
                    _warn("Usage: /model <id>")
                elif cmd_arg not in _base_model_ids:
                    _warn(f"Unknown model {cmd_arg!r}. Use /models to list available.")
                else:
                    nonlocal_state["model"] = cmd_arg
                    _ok(f"Switched to {cmd_arg}")

            elif cmd_word == "/projects":
                found = []
                try:
                    found = known_projects()
                except Exception as _kp_exc:
                    # f404: the old inline query hit a nonexistent
                    # nora_metrics.project column and swallowed the error,
                    # printing a false "No projects found" forever (CONV-P1).
                    _warn(f"project lookup failed: {_kp_exc}")
                if found:
                    print(f"\n{BOLD}Known projects:{RESET}")
                    for pname in found:
                        marker = f"{GREEN}*{RESET}" if pname == nonlocal_state["project"] else " "
                        print(f"  {marker} {pname}")
                    print()
                else:
                    _info("No projects found in echo.db. Try `kernora reindex-yaml` first.")

            elif cmd_word == "/project":
                if not cmd_arg:
                    _warn("Usage: /project <name>")
                else:
                    nonlocal_state["project"] = cmd_arg
                    conversation.clear()
                    _ok(f"Switched to project {cmd_arg!r} (conversation cleared)")

            elif cmd_word == "/history":
                if not conversation:
                    _info("Conversation is empty.")
                else:
                    print()
                    for i, msg in enumerate(conversation, 1):
                        role = msg.get("role", "?")
                        content = (msg.get("content") or "")[:120]
                        ellipsis = "..." if len(msg.get("content", "")) > 120 else ""
                        prefix = f"{CYAN}You{RESET}" if role == "user" else f"{BOLD}Nora{RESET}"
                        print(f"  {i}. [{prefix}] {content}{ellipsis}")
                    print()

            elif cmd_word == "/clear":
                conversation.clear()
                _ok("Conversation cleared.")

            else:
                _warn(f"Unknown command {cmd_word!r}. Type /help for list.")

            continue

        # ── Regular chat turn ────────────────────────────────────────────────
        conversation.append({"role": "user", "content": user_input})

        # Build augmented prompt including prior turns as minimal context
        if len(conversation) > 1:
            ctx_lines = []
            for msg in conversation[:-1]:
                role_label = "User" if msg["role"] == "user" else "Nora"
                ctx_lines.append(f"{role_label}: {msg['content']}")
            context_block = "\n".join(ctx_lines[-8:])  # last 4 exchanges max
            full_prompt = f"Prior conversation:\n{context_block}\n\nUser: {user_input}"
        else:
            full_prompt = user_input

        print()
        try:
            # B1 fix (v51): destructure 6-tuple — grounding signals now flow through
            response_text, factlets, _fdetails, _gpct, _gcal, _lfw = _stream_chat(
                full_prompt,
                nonlocal_state["project"] or "",
                nonlocal_state["model"],
                is_tty,
            )
            if _fdetails:
                _print_citation_strip(_fdetails, _gpct, _gcal, _lfw)
            else:
                _print_factlets(factlets)
        except RuntimeError as exc:
            _err(f"Chat error: {exc}")
            _info("Is the daemon running? Try: kernora start")
            print()
            continue

        conversation.append({"role": "assistant", "content": response_text})
        print()

    return 0


def cmd_recurrence_sweep():
    """Live recurrence sweep — scan sessions/candidates/factbook for known
    caught-error signatures (LIVE-RECURRENCE-PROTOCOL-JUL-5-2026.md)."""
    from recurrence_watch import main as _rw_main
    return _rw_main()


def cmd_verify_artifact():
    """Conformance gate: verify one artifact against the applicable factlets.

    Usage: kernora verify-artifact <path> [--diff] [--cadence conformance|sweep]
                                          [--project NAME] [--no-emit]
    Exit code 1 iff any FAIL at conformance cadence (design addendum §2).
    """
    args = [a for a in sys.argv[2:]]
    if not args or args[0] in ("-h", "--help"):
        print(f"Usage: {CYAN}nora verify-artifact <path> [--diff] "
              f"[--cadence conformance|sweep] [--project NAME] [--no-emit]{RESET}")
        return 0
    # B7: positional target = first non-flag arg (except stdin sentinel '-'),
    # so `verify-artifact --diff patch.txt` works in either order.
    _flag_values = set()
    if "--cadence" in args:
        _idx = args.index("--cadence")
        if _idx + 1 < len(args):
            _flag_values.add(_idx + 1)
    if "--project" in args:
        _idx = args.index("--project")
        if _idx + 1 < len(args):
            _flag_values.add(_idx + 1)
    _positionals = [a for i, a in enumerate(args)
                    if i not in _flag_values and (a == "-" or not a.startswith("--"))]
    if not _positionals:
        _err("verify-artifact: no artifact path given")
        return 1
    target = _positionals[0]
    is_diff = "--diff" in args
    emit = "--no-emit" not in args
    cadence = "conformance"
    if "--cadence" in args:
        try:
            cadence = args[args.index("--cadence") + 1]
        except IndexError:
            _err("--cadence requires a value (conformance|sweep)")
            return 1
    project = None
    if "--project" in args:
        try:
            project = args[args.index("--project") + 1]
        except IndexError:
            _err("--project requires a value")
            return 1
    if project is None:
        project = os.path.basename(os.getcwd())

    from conformance_caller import verify_artifact
    if is_diff:
        content = sys.stdin.read() if target == "-" else open(target, encoding="utf-8").read()
        report = verify_artifact(content, project, is_diff=True, cadence=cadence,
                                 project_root=os.getcwd(), emit_labels=emit)
    else:
        report = verify_artifact(target, project, cadence=cadence,
                                 project_root=os.getcwd(), emit_labels=emit)

    for n in report.notices:
        print(f"{YELLOW}⚠ {n}{RESET}")
    print(f"Conformance — {report.artifact_path} (project={report.project}, "
          f"cadence={report.cadence})")
    print(f"  factlets: {report.factlets_total} total → "
          f"{report.factlets_applicable} applicable (RFC 0008)")
    # NEEDS_REVIEW first — honesty ordering per design §4
    if report.needs_review:
        print(f"  {YELLOW}NEEDS_REVIEW: {len(report.needs_review)}{RESET}")
        for e in report.needs_review[:10]:
            why = e.get("rejection_code") or e.get("reason") or "undetermined"
            print(f"    ~ {e['fact_id']} ({why})")
    if report.failed:
        print(f"  {RED}FAIL: {len(report.failed)}{RESET}")
        for e in report.failed:
            print(f"    ✗ {e['fact_id']} — {e['rejection_code']} ({e['oracle_kind']})")
    if report.passed:
        print(f"  {GREEN}PASS: {len(report.passed)}{RESET}")
        for e in report.passed:
            print(f"    ✓ {e['fact_id']} ({e['oracle_kind']})")
    if emit:
        print(f"  labels written: {report.labels_written} (verdict_class=conformance)")
    if report.failed and cadence == "conformance":
        return 1
    return 0


def cmd_verify():
    """Verification wizard — confirm low-trust factlets to raise their FactSignal.

    Every factlet starts at least-value. Nora ranks candidates by promote-
    worthiness (usage-dominant) and builds the case for each; you confirm
    (Nora proposes, human disposes). Confirmation stamps verified +
    content_verified_at, raising how strongly the factlet grounds Claude.
    Coverage stays full — all facts ground at their trust level. Flags:
      --list            non-interactive — show the ranked candidates + rationale
      --project NAME    scope to one project
      --limit N         how many to walk this run (default 20)
    """
    import sys as _sys
    import datetime as _dt
    argv = _sys.argv[2:]
    list_only = "--list" in argv
    project = None
    limit = 20
    for i, a in enumerate(argv):
        if a == "--project" and i + 1 < len(argv):
            project = argv[i + 1]
        if a == "--limit" and i + 1 < len(argv):
            try:
                limit = max(1, int(argv[i + 1]))
            except ValueError:
                pass
    try:
        import db
        import promotion
        from score_utils import factsignal_score
    except Exception as e:  # pragma: no cover
        _err(f"could not load verification engine: {e}")
        return 1
    conn = db.get_conn()
    if conn is None:
        _err("no database — run `kernora init` first")
        return 1
    try:
        cands = promotion.rank_promotion_candidates(conn, project, limit)
        _where = "archived=0 AND content_verified_at IS NULL" + (" AND project=?" if project else "")
        total = conn.execute(f"SELECT COUNT(*) FROM patterns WHERE {_where}",
                             ((project,) if project else ())).fetchone()[0]
        if not cands:
            print(f"{GREEN}No factlets need verifying — your factbook is curated. ✓{RESET}")
            return 0
        print(f"\n{BOLD}Nora verification wizard{RESET} — {total} unverified factlet(s).")
        print("Confirming the ones you recognize raises their trust (and how strongly")
        print(f"they ground Claude). Ranked by value — start with what you rely on most.\n")
        if list_only:
            for i, (fd, r) in enumerate(cands, 1):
                tag = f"{GREEN}RECOMMEND{RESET}" if r["recommend"] else f"{DIM}optional{RESET}"
                print(f"{i}. [{tag}] now {r['current_score']}/5 · {(fd['pattern'] or '').strip()[:68]}")
                print(f"   {DIM}→ {r['why']}{RESET}")
            print(f"\nRun without --list to confirm them interactively.")
            return 0
        promoted = retired = skipped = 0
        for i, (fd, r) in enumerate(cands, 1):
            rec = f"{GREEN}Nora recommends{RESET}" if r["recommend"] else f"{DIM}Nora: optional{RESET}"
            print(f"{DIM}[{i}/{len(cands)}]{RESET} {BOLD}trust now {r['current_score']}/5{RESET}")
            print(f"  {(fd['pattern'] or '').strip()[:240]}")
            print(f"  {rec} — {r['why']}")
            _src = r.get("source_uri")
            if _src:
                print(f"  {DIM}source (verify at origin): {_src}{RESET}")
            try:
                # "Still true?" — ask the human to VERIFY, not recall. Confirming a
                # fact only because Nora cited it a lot would launder error to high
                # trust (DE finding); the source link above is for checking it.
                ans = input("  Is this still true? [y]es / [n]o,retire / [s]kip / [q]uit: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if ans in ("q", "quit"):
                break
            if ans in ("y", "yes"):
                _kv_tbl = "factlets" if db._factlets_table_exists(conn) else "patterns"
                conn.execute(f"UPDATE {_kv_tbl} SET review_status='verified' WHERE id=?", (fd["id"],))
                conn.commit()
                # internal-rule (Jul-17 audit F1/F2) — the top human trust band
                # (content_verified_at) requires a real interactive TTY (this
                # wizard's own `input()` prompt above). NEVER fall back to a raw
                # UPDATE on PermissionError — that would defeat the exact gate
                # this wizard exists to satisfy (a piped/non-interactive caller
                # must NOT reach band 4). review_status='verified' above already
                # lands the factlet at band 3 ("auto-verified") regardless.
                _content_verified = False
                try:
                    db.stamp_content_verified_at(conn, fd["id"])
                    _content_verified = True
                except PermissionError as _tty_gate_e:
                    print(f"  {DIM}(no interactive TTY — trust raised to auto-verified "
                          f"only, not full human-verified: {_tty_gate_e}){RESET}")
                # HIGH-1 (Stage-8 PE, Jul-17): commit the content_verified_at write
                # NOW — unconditionally and independent of the best-effort label tap
                # below. The tap can fail (e.g. verification_labels missing on a fresh
                # DB) and its except-path does not commit; without this line the band-4
                # stamp would be silently discarded on conn.close() while the wizard
                # still prints "✓ confirmed → trust 4/5" (silent data loss + false success).
                conn.commit()
                # Stage-4 MED-4 tap: CLI `kernora verify` confirm → operator_confirm gold.
                # Best-effort, post-commit (§10-B2 / f404); helper snapshots body+source_type.
                try:
                    db._emit_verification_label(
                        conn, fact_id=fd["id"], factlet_body=fd.get("pattern") or fd.get("body"),
                        verdict="verified", label="entails", label_source="operator_confirm",
                        confidence=0.8, event_source="cli_verify")
                    conn.commit()
                except Exception as _vl_e:
                    print(f"  {DIM}(verification_label emit skipped: {_vl_e}){RESET}")
                _score_fd = {**fd, "review_status": "verified"}
                if _content_verified:
                    _score_fd["content_verified_at"] = _dt.datetime.now().isoformat()
                _ns, _ = factsignal_score(_score_fd)
                print(f"  {GREEN}✓ confirmed → trust {_ns}/5 — Claude now grounds in it with higher trust.{RESET}\n")
                promoted += 1
            elif ans in ("n", "no", "retire"):
                conn.execute(f"UPDATE {_kv_tbl} SET archived=1 WHERE id=?", (fd["id"],))
                conn.commit()
                # Stage-4 MED-4 tap: CLI retire → retired_structural (operator-initiated, no reason).
                try:
                    db._emit_verification_label(
                        conn, fact_id=fd["id"], factlet_body=fd.get("pattern") or fd.get("body"),
                        verdict="retired_structural", label="neutral", label_source="operator_confirm",
                        confidence=0.8, event_source="cli_verify")
                    conn.commit()
                except Exception as _vl_e:
                    print(f"  {DIM}(verification_label emit skipped: {_vl_e}){RESET}")
                print(f"  {DIM}✗ retired — it won't ground answers (recoverable via `kernora undo`).{RESET}\n")
                retired += 1
            else:
                print()
                skipped += 1
        print(f"{BOLD}Done.{RESET} {promoted} confirmed · {retired} retired · {skipped} skipped.")
        _left = total - promoted - retired
        if _left > 0:
            print(f"{DIM}{_left} unverified remain — run `kernora verify` again for the next batch.{RESET}")
        return 0
    finally:
        conn.close()


def _help_lint() -> int:
    """Verify every `kernora <subcmd>` advertised in cmd_help() has a real dispatch entry.

    Prevents the documented-but-not-invokable drift class captured in factlet f993
    (the 2026-05-27 /nora consolidate incident, where `/nora consolidate` was
    documented but `kernora consolidate` returned "Unknown command"). Run via
    `kernora _help-check` — exits 0 if clean, 1 if drift found.
    """
    import io
    import re
    import sys
    buf = io.StringIO()
    _orig = sys.stdout
    sys.stdout = buf
    try:
        cmd_help()
    except SystemExit:
        pass
    finally:
        sys.stdout = _orig
    text = re.sub(r'\x1b\[[0-9;]*m', '', buf.getvalue())  # strip ANSI
    advertised = {s for s in re.findall(r'\bkernora ([a-z][a-z0-9_-]+)\b', text)
                  if not s.startswith('-')}
    declared = set(COMMANDS.keys())
    missing = sorted(advertised - declared)
    extras = sorted(declared - advertised - {"_help-check"})
    print(f"{BOLD}kernora cmd_help drift check{RESET} (factlet f993)")
    print(f"  advertised in help text: {len(advertised)}")
    print(f"  declared in COMMANDS:    {len(declared)}")
    if missing:
        print(f"\n  {RED}MISSING DISPATCH{RESET} — advertised but absent from COMMANDS:")
        for m in missing:
            print(f"    - kernora {m}")
    if extras:
        print(f"\n  {DIM}declared but not surfaced in cmd_help() (may be intentional/hidden):{RESET}")
        for e in extras[:20]:
            print(f"    - {e}")
        if len(extras) > 20:
            print(f"    {DIM}... and {len(extras)-20} more{RESET}")
    print(f"\n  {'✗ DRIFT FOUND' if missing else '✓ clean — no drift'}")
    return 1 if missing else 0


def cmd_consolidate() -> int:
    """`kernora consolidate` shim — points to the canonical MCP/IDE-chat tool.

    The 3-pass plan (dedup + supersession + retire-stale) runs as MCP tool
    `nora_consolidate` (+ `nora_consolidate_apply`), invokable from an IDE
    chat (Claude Code / Cursor / Kiro). This CLI subcommand exists so
    `kernora consolidate` no longer returns 'Unknown command'; it is not
    yet wired to call the handler directly.
    See docs/COE-CONSOLIDATE-NOT-INVOKABLE-MAY-28-2026.md (factlet f992).
    """
    print()
    print(f"{BOLD}consolidate runs as an MCP tool, not a CLI command.{RESET}")
    print()
    print("  Invoke from your IDE chat (Claude Code / Cursor / Kiro):")
    print(f"    {CYAN}/nora consolidate{RESET}                — Three-pass plan: dedup + supersession + retire-stale")
    print(f"    {CYAN}/nora consolidate apply <id>{RESET}    — apply a previously-approved plan")
    print()
    print(f"  Or call the MCP tools directly: {DIM}mcp__nora__nora_consolidate{RESET} / {DIM}mcp__nora__nora_consolidate_apply{RESET}.")
    print()
    print(f"  Why a shim? See {DIM}docs/COE-CONSOLIDATE-NOT-INVOKABLE-MAY-28-2026.md{RESET}.")
    print()
    return 2  # not-yet-wired; the doc-vs-reality drift this resolves


# ── Arc-ledger CLI (arc-ledger redesign, 2026-06-01) ─────────────────────────

def cmd_arc() -> int:
    """Manage the arc-ledger — live goal + task list for a project arc.

    Usage:
      kernora arc set-goal <text>       — start or replace the arc goal
      kernora arc add <subject>         — append an open task
      kernora arc done <id>             — mark task done
      kernora arc defer <id>            — mark task deferred
      kernora arc block <id>            — mark task blocked
      kernora arc doing <id>            — mark task in-progress
      kernora arc focus <id|text>       — set current focus
      kernora arc show                  — print the live ledger
      kernora arc close [--summary <t>] — close the arc (optional summary factlet)

    Storage: arc_ledger table in ~/.kernora/echo.db (migration 0030).
    Each mutation is an in-place UPSERT — no git churn.
    On close, an optional summary is written as a durable 'learning' factlet
    via the f389 chokepoint (nora_bridge.py yaml_add_fact).
    """
    import sys as _sys

    sub_args = _sys.argv[2:]
    if not sub_args or sub_args[0] in ("-h", "--help"):
        print(cmd_arc.__doc__ or "")
        return 0

    subcmd = sub_args[0]

    # Resolve project from cwd
    try:
        import db as _db
        project = _db.canonical_project(str(Path.cwd())) or Path.cwd().name
    except Exception:
        project = Path.cwd().name

    try:
        import arc_ledger as _al
    except ImportError as e:
        _err(f"arc_ledger module unavailable: {e}")
        return 1

    try:
        if subcmd == "set-goal":
            goal = " ".join(sub_args[1:])
            if not goal:
                _err("kernora arc set-goal requires a <text> argument")
                return 1
            _al.set_goal(project, goal)
            print(f"Arc goal set for project={project!r}.")
            return 0

        elif subcmd == "add":
            subject = " ".join(sub_args[1:])
            if not subject:
                _err("kernora arc add requires a <subject> argument")
                return 1
            task_id = _al.add_task(project, subject)
            print(f"Added task ({task_id}): {subject}")
            return 0

        elif subcmd in ("done", "defer", "block", "doing"):
            if len(sub_args) < 2:
                _err(f"kernora arc {subcmd} requires a task <id>")
                return 1
            try:
                task_id = int(sub_args[1])
            except ValueError:
                _err(f"task id must be an integer, got {sub_args[1]!r}")
                return 1
            state = {"done": "done", "defer": "deferred", "block": "blocked", "doing": "doing"}[subcmd]
            found = _al.set_state(project, task_id, state)
            if not found:
                _err(f"Task {task_id} not found in live arc for project={project!r}")
                return 1
            print(f"Task ({task_id}) → {state}")
            return 0

        elif subcmd == "focus":
            focus = " ".join(sub_args[1:])
            if not focus:
                _err("kernora arc focus requires an <id|text> argument")
                return 1
            _al.set_focus(project, focus)
            print(f"Focus set: {focus}")
            return 0

        elif subcmd == "show":
            ledger = _al.get_live(project)
            if ledger is None:
                print(f"No live arc for project={project!r}. Use: kernora arc set-goal <text>")
                return 0
            print(_al.render(ledger))
            stale = _al.is_stale(project)
            if stale:
                print("  ⚠️  arc-ledger stale — a commit is newer than the last update.")
            return 0

        elif subcmd == "close":
            # Parse optional --summary
            summary = None
            args_rest = sub_args[1:]
            i = 0
            while i < len(args_rest):
                if args_rest[i] == "--summary" and i + 1 < len(args_rest):
                    summary = args_rest[i + 1]; i += 2
                else:
                    i += 1
            _al.close(project, summary=summary)
            print(f"Arc closed for project={project!r}.")
            if summary:
                print(f"Summary factlet queued for factbook.")
            return 0

        else:
            _err(f"Unknown arc subcommand: {subcmd!r}. Run 'kernora arc --help'.")
            return 1

    except Exception as exc:
        _err(f"kernora arc: {exc}")
        return 1


def cmd_predicate_coverage() -> int:
    """PE-6 coverage: % of predicate-required facts carrying a verify oracle.
    Reports coverage debt; in enforce mode exits non-zero on any missing oracle.
    docs/PREDICATE-PRESENT-GATE-JUN-02-2026.md"""
    _add_app_to_path()
    import os as _os
    import sqlite3 as _sql
    try:
        import db as _db
    except ImportError:
        _err("db not importable — run: kernora install")
        return 1
    conn = _sql.connect(_os.path.expanduser("~/.kernora/echo.db"))
    try:
        cov = _db.predicate_coverage(conn)
    except Exception as _e:  # e.g. no-such-table on a pre-S2 / fresh DB — clean exit
        _err(f"coverage query failed: {_e}")
        return 1
    finally:
        conn.close()
    req = ", ".join(sorted(_db._PREDICATE_REQUIRED_FACT_TYPES))
    print(f"Predicate-present coverage (required types: {req})")
    print(f"  {cov['with_verify']}/{cov['required']} carry a verify oracle ({cov['pct']}%)")
    if cov["missing"]:
        print(f"  {cov['missing']} missing a verify block (coverage debt):")
        for fid in cov["missing_fact_ids"][:50]:
            print(f"    {fid}")
    try:
        from nora_bridge import _predicate_gate_mode  # type: ignore
        mode = _predicate_gate_mode()
    except Exception:
        mode = "warn"
    if mode == "enforce" and cov["missing"]:
        _err(f"enforce mode: {cov['missing']} predicate-required fact(s) missing a verify block")
        return 1
    return 0


# ── Q3 Capture Redesign (2026-07-21): commit mining ─────────────────────────
# `kernora mine-commits <n>` — git-log heuristic mining → batch candidate
# factlets. Delegates to the SAME _distill_and_write_candidates shared
# helper (internal-rule) that nora_factletize and the refactored nora_extract
# use — no duplicate LLM-call/parse/write logic. Kept OFF the MCP surface
# (T3 blast-radius, docs/Q3-CAPTURE-REDESIGN-JUL-21-2026.md decision 1) —
# git-log scanning is background-cadence, not agent-conversational.

_MINE_COMMITS_DEFAULT_N = 10
_MINE_COMMITS_CAP = 10  # decision 5: cap candidate commits per run

_MINE_COMMITS_FINDINGS_RE = re.compile(
    r"root cause|fixed by|fix:|bug ?fix|regression|reverted?|"
    r"\broot[- ]caus|verified?|\d+\s*/\s*\d+\s*(tests|passing)|\d+\s*tests?\b",
    re.IGNORECASE,
)
_MINE_COMMITS_FILELINE_RE = re.compile(r"\w+\.py:\d+")
_MINE_COMMITS_CHORE_RE = re.compile(r"^(chore|style|docs)(\(.+\))?:\s*", re.IGNORECASE)


def _mine_commits_is_findings_rich(subject: str, body: str) -> tuple[bool, str]:
    """Heuristic filter (decision 5): findings-rich vs chore/style/docs-only.

    Returns (keep, reason) — reason is always populated (used for the loud
    skip-log of anything filtered out, internal-rule/AP-004).
    """
    full = f"{subject}\n{body}"
    if _MINE_COMMITS_CHORE_RE.match(subject.strip()) and not (
        _MINE_COMMITS_FILELINE_RE.search(full) or _MINE_COMMITS_FINDINGS_RE.search(full)
    ):
        return False, "chore/style/docs prefix with no findings signal"
    has_fileline = bool(_MINE_COMMITS_FILELINE_RE.search(full))
    has_findings_lang = bool(_MINE_COMMITS_FINDINGS_RE.search(full))
    if has_fileline or has_findings_lang:
        return True, "findings-rich (file:line ref or failure/fix/verification language)"
    if len(body.strip()) < 20:
        return False, "short one-liner, no file:line ref or findings language"
    return False, "no failure/fix/root-cause/test-count/file:line signal found"


def cmd_mine_commits() -> int:
    """`kernora mine-commits <n>` — mine the last n commits (default 10) of
    the current repo for findings-rich commits and distill each into
    candidate factlets via the shared helper.

    Usage: kernora mine-commits [n]
    """
    n = _MINE_COMMITS_DEFAULT_N
    if len(sys.argv) > 2:
        try:
            n = max(1, int(sys.argv[2]))
        except ValueError:
            _err(f"invalid n: {sys.argv[2]!r}")
            return 1

    repo = _current_repo_root()
    if repo is None:
        _err("Not inside a git repository.")
        return 1

    try:
        log = subprocess.run(
            ["git", "log", f"-{n}", "--pretty=format:%H%x1f%s%x1e%b%x1e%x1e"],
            cwd=str(repo), capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        _err(f"git log failed: {e}")
        return 1
    if log.returncode != 0:
        _err(f"git log failed: {log.stderr.strip()}")
        return 1

    commits: list[tuple[str, str, str]] = []
    for entry in log.stdout.split("\x1e\x1e"):
        entry = entry.strip("\n")
        if not entry.strip():
            continue
        try:
            sha, rest = entry.split("\x1f", 1)
        except ValueError:
            continue
        subject, _, body = rest.partition("\x1e")
        commits.append((sha.strip(), subject.strip(), body.strip()))

    kept: list[tuple[str, str, str]] = []
    skipped: list[tuple[str, str]] = []
    for sha, subject, body in commits:
        keep, reason = _mine_commits_is_findings_rich(subject, body)
        if keep:
            kept.append((sha, subject, body))
        else:
            skipped.append((sha, reason))
            print(f"[mine-commits] SKIP {sha[:8]} — {reason} ({subject[:60]!r})")

    if len(kept) > _MINE_COMMITS_CAP:
        overflow = kept[_MINE_COMMITS_CAP:]
        kept = kept[:_MINE_COMMITS_CAP]
        for sha, subject, _body in overflow:
            print(f"[mine-commits] SKIP {sha[:8]} — over {_MINE_COMMITS_CAP}-commit cap ({subject[:60]!r})")
            skipped.append((sha, f"over {_MINE_COMMITS_CAP}-commit cap"))

    _add_app_to_path()
    try:
        from nora_mcp import NoraServer
    except ImportError as e:
        _err(f"nora_mcp module not available: {e}")
        return 1
    srv = NoraServer()

    import asyncio as _asyncio
    written_total = 0
    skipped_dup_total = 0
    for sha, subject, body in kept:
        source_material = f"commit {sha}\nsubject: {subject}\n\n{body}"
        source_label = f"commit:{sha[:8]}"
        result = _asyncio.run(srv._distill_and_write_candidates(
            source_material=source_material,
            source_label=source_label,
            project_root=repo,
            cap=_MINE_COMMITS_CAP,
        ))
        if not result.get("ok"):
            print(f"[mine-commits] {source_label} — LLM/write FAILED: {result.get('error')}")
            continue
        written_total += result["written"]
        skipped_dup_total += result["skipped_dup"]
        print(f"[mine-commits] {source_label} — written={result['written']} "
              f"skipped_dup={result['skipped_dup']} dropped={result['dropped']}")

    print(f"\n[mine-commits] Scanned {len(commits)} commit(s): "
          f"{len(kept)} findings-rich mined, {len(skipped)} skipped.")
    print(f"[mine-commits] Total candidates written={written_total}, deduped={skipped_dup_total}.")
    return 0


COMMANDS = {
    "init":            cmd_init,
    "install":         cmd_install,   # alias for end-user install path
    "start":           cmd_start,
    "stop":            cmd_stop,
    "restart":         cmd_restart,
    "status":          cmd_status,
    "analyze":         cmd_analyze,
    "generate":        cmd_generate,
    "config":          cmd_config,
    "persona":         cmd_persona,
    "memory":          cmd_memory,
    "doctor":          cmd_doctor,
    "add-project":     cmd_add_project,
    "list-projects":   cmd_list_projects,
    "forget":          cmd_forget,
    "pause":           cmd_pause,
    "resume":          cmd_resume,
    "version":         cmd_version,
    "--version":       cmd_version,
    "-v":              cmd_version,
    "migrate":         cmd_migrate,
    "predicate-coverage": cmd_predicate_coverage,
    "archive":         cmd_archive,
    "purge":           cmd_purge,
    "restore":         cmd_restore,
    "anchors":         cmd_anchors,
    "drift":           cmd_drift,
    "precision":       cmd_precision,
    "recall":          cmd_recall,
    "network-check":   cmd_network_check,
    "roi":             cmd_roi,
    "fact-outcomes":   cmd_fact_outcomes,
    "export-sft":      cmd_export_sft,
    "export-verifier-set": cmd_export_verifier_set,
    "ignore-check":    cmd_ignore_check,
    "ignore-test":     cmd_ignore_test,
    "undo":            cmd_undo,
    "tour":            cmd_tour,
    "review-injections": cmd_review_injections,
    "verify":          cmd_verify,
    "verify-artifact": cmd_verify_artifact,
    "recurrence-sweep": cmd_recurrence_sweep,
    "mine-commits":    cmd_mine_commits,
    "coe-last":        cmd_coe_last,
    "coe":             lambda: cmd_coe(),
    "pe-review":       lambda: cmd_pe_review(),
    "hook-install":    cmd_hook_install,
    "hook-uninstall":  cmd_hook_uninstall,
    "pii-scan":        lambda: cmd_pii_scan(),
    "project-scope-check": lambda: cmd_project_scope_check(),
    "team-init":       lambda: cmd_team_init(),
    "team-report":     lambda: cmd_team_report(),
    "migrate-to-git-native": lambda: cmd_migrate_to_git_native(),
    "alias":                 lambda: cmd_alias(),
    "factbook":        lambda: cmd_factbook(),
    "factbook-view":   lambda: cmd_factbook_view(),
    "factbook-export": lambda: cmd_factbook_export(),
    "factbook-install": lambda: cmd_factbook_install_cmd(),
    "kp":              lambda: cmd_kp(),
    "import-kp":       lambda: cmd_import_kp(),
    "consolidate":     lambda: cmd_consolidate(),
    "_help-check":     lambda: _help_lint(),
    "nora-push":       lambda: cmd_nora_push(),
    "dashboard-init":  lambda: cmd_dashboard_init(),
    "dashboard":       lambda: cmd_dashboard(),
    "capture":         lambda: cmd_capture(),
    "proxy":           lambda: cmd_proxy(),
    "adapters":        lambda: cmd_adapters(),
    "download-embed-model": lambda: cmd_download_embed_model(),
    "warmup-embed":    lambda: cmd_warmup_embed(),
    "advisor":         lambda: cmd_advisor(),
    "license":         lambda: cmd_license(),
    "reindex-yaml":    lambda: cmd_reindex_yaml(),
    "acceptance-scan": lambda: cmd_acceptance_scan(),
    "chat":            lambda: cmd_chat(),
    "help":            cmd_help,
    # ── Harness surface (§9.1 / §4.5 M-list) ─────────────────────────────────
    # Entitlement: Pro tier minimum (LD-5 [FD] / §17.18 FD-1).
    # cmd_run_start/status/prov/sweep dispatch to GoalLoop via the MCP async pattern.
    "run-start":       lambda: cmd_run_start(),
    "run-status":      lambda: cmd_run_status(),
    "run-prov":        lambda: cmd_run_prov(),   # renamed from 'prov' per §17.7 / FD-3
    "factbook-prov":   lambda: cmd_factbook_prov(),   # G5: factbook PROV-O lane
    "sweep":           lambda: cmd_sweep(),
    # ── Arc-ledger (arc-ledger redesign, 2026-06-01) ──────────────────────────
    "arc":             lambda: cmd_arc(),
}


# ── Harness CLI commands (§9.1 / §4.5 M-list) ────────────────────────────────

def _harness_tier_check() -> bool:
    """Entitlement check: Build harness requires Pro tier minimum (LD-5 [FD] / FD-1).

    Returns True if allowed.  Tier logic lives here only — GoalLoop itself has no
    tier logic (per §4.2 design constraint).
    """
    try:
        import kernora_mode as _km
        tier = _km.current_tier()
        allowed = tier in ("pro", "team", "enterprise", "dev", "founder")
        if not allowed:
            _err(
                "Build harness requires Pro tier or above (tier: {}).".format(tier)
            )
            _warn("Upgrade at kernora.ai or run `kernora config set tier=pro`.")
        return allowed
    except Exception:
        return True  # if mode check unavailable, allow (dev installs)


def cmd_run_start() -> int:
    """Start a harness Build or Sweep run.

    Usage:
      kernora run-start --goal "<plain language goal>" [options]
      kernora run-start --resume <run_id>

    Options:
      --goal "<goal>"          Goal text for a new Build run.
      --mode build|sweep       Default: build.
      --budget-iterations N    Default: 20.
      --budget-seconds N       Default: 3600 (1 hour).
      --budget-tokens N        Default: 500000.
      --owner @<username>      Accountable actor for answerable-test (T8).
      --resume <run_id>        Resume a PAUSED run from checkpoint.
      --format prov-json|prov-n  Auto-export prov on completion.

    Returns run_id immediately; the loop runs in a background thread.
    Poll with: kernora run-status <run_id>
    """
    import sys as _sys
    if not _harness_tier_check():
        return 1

    args = _sys.argv[2:]  # skip 'kernora run-start'

    # Parse arguments
    goal = None
    mode = "build"
    budget_iterations = 20
    budget_seconds = 3600
    budget_tokens = 500_000
    owner = None
    resume_run_id = None
    fmt = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--goal" and i + 1 < len(args):
            goal = args[i + 1]; i += 2
        elif a == "--mode" and i + 1 < len(args):
            mode = args[i + 1]; i += 2
        elif a == "--budget-iterations" and i + 1 < len(args):
            budget_iterations = int(args[i + 1]); i += 2
        elif a == "--budget-seconds" and i + 1 < len(args):
            budget_seconds = int(args[i + 1]); i += 2
        elif a == "--budget-tokens" and i + 1 < len(args):
            budget_tokens = int(args[i + 1]); i += 2
        elif a == "--owner" and i + 1 < len(args):
            owner = args[i + 1]; i += 2
        elif a == "--resume" and i + 1 < len(args):
            resume_run_id = args[i + 1]; i += 2
        elif a == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        else:
            i += 1

    if not goal and not resume_run_id:
        _err("kernora run-start requires --goal \"<goal>\" or --resume <run_id>.")
        return 1

    try:
        import threading
        from agent_runtime import AgentBudget
        from goal_loop import GoalLoop, StorageTarget

        budget = AgentBudget(
            max_tool_iterations=budget_iterations,
            max_wall_seconds=budget_seconds,
            max_total_tokens=budget_tokens,
        )

        if resume_run_id:
            loop = GoalLoop(goal="", mode=mode, budget=budget, owner=owner)
            _info(f"Resuming run {resume_run_id}…")
            t = threading.Thread(target=loop.resume, args=(resume_run_id,), daemon=True)
            t.start()
            print(f"run_id: {resume_run_id}\nstatus: started\npoll: kernora run-status {resume_run_id}")
            return 0

        loop = GoalLoop(
            goal=goal,
            mode=mode,
            budget=budget,
            owner=owner,
        )

        def _run():
            try:
                loop.start()
            except Exception as exc:
                _err(f"[F404-LOOP-STALL] Run failed: {exc}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        # For CLI: block until loop finishes (user experience unchanged; §17.5)
        t.join()

        state = loop.inspect()
        run_id = state.get("run_id", "?")
        print(f"run_id: {run_id}")
        print(f"status: {state.get('status', 'unknown')}")
        if state.get("terminate_reason"):
            print(f"terminate_reason: {state['terminate_reason']}")
        if fmt:
            print(loop.export_prov(format=fmt))
        return 0
    except Exception as exc:
        _err(f"[F404-LOOP-STALL] kernora run-start error: {exc}")
        return 1


def cmd_run_status() -> int:
    """Poll the status of a harness run.

    Usage:
      kernora run-status <run_id>
    """
    import sys as _sys
    args = _sys.argv[2:]
    run_id = args[0] if args else None
    if not run_id:
        _err("kernora run-status requires a run_id argument.")
        return 1

    try:
        import sqlite3
        import json as _json
        import db as _db
        conn = _db.get_conn()
        row = conn.execute(
            """SELECT id, status, terminate_reason, terminate_cause,
                      goal_factlet_ids, checkpoint_json, storage_target,
                      last_heartbeat_at, created_at, updated_at
               FROM inference_jobs WHERE id=?""",
            (run_id,),
        ).fetchone()
        conn.close()
        if not row:
            _err(f"Run {run_id} not found.")
            return 1
        (rid, status, tr, tc, gf_ids, cp_json, st, hb, created, updated) = row
        satisfied = 0
        total = 0
        iteration = 0
        if cp_json:
            cp = _json.loads(cp_json)
            satisfied = len(cp.get("satisfied_goal_factlet_ids", []))
            total = satisfied + len(cp.get("unsatisfied_goal_factlet_ids", []))
            iteration = cp.get("iteration_ordinal", 0)
        print(f"run_id:                  {rid}")
        print(f"status:                  {status}")
        print(f"iteration_ordinal:       {iteration}")
        print(f"goal_factlets_satisfied: {satisfied}")
        print(f"goal_factlets_total:     {total}")
        print(f"terminate_reason:        {tr or 'null'}")
        print(f"terminate_cause:         {tc or 'null'}")
        print(f"storage_target:          {st or 'null'}")
        print(f"last_heartbeat_at:       {hb or 'null'}")
        print(f"created_at:              {created}")
        print(f"updated_at:              {updated}")
        return 0
    except Exception as exc:
        _err(f"[F404-LOOP-STALL] run-status error: {exc}")
        return 1


def cmd_run_prov() -> int:
    """Export the PROV-O provenance trail for a harness run.

    Usage:
      kernora run-prov <run_id> [--format prov-json|prov-n]

    Renamed from 'nora prov' per §17.7 / FD-3 to avoid collision with
    nora_provenance (factbook provenance tool, different purpose).
    """
    import sys as _sys
    args = _sys.argv[2:]
    run_id = None
    fmt = "prov-json"
    i = 0
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        elif not run_id:
            run_id = args[i]; i += 1
        else:
            i += 1
    if not run_id:
        _err("kernora run-prov requires a run_id argument.")
        return 1
    try:
        from goal_loop import GoalLoop
        loop = GoalLoop(goal="", mode="build")
        loop.run_id = run_id
        print(loop.export_prov(format=fmt))
        return 0
    except Exception as exc:
        _err(f"[F404-LOOP-STALL] run-prov error: {exc}")
        return 1


def cmd_factbook_prov() -> int:
    """Export W3C PROV-O provenance graph for a factbook (G5 factbook PROV-O lane).

    Usage:
      kernora factbook-prov [<factbook_id>] [--format prov-json|prov-n]

    DISTINCT from 'kernora run-prov' (run-graph lane) and 'nora_provenance'
    (per-fact markdown lineage).  Entities = persistent factlets.  Agents =
    producer + authority via qualified prov:Attribution + prov:hadRole.
    Activity = verification step (verify_kind populated rows) with qualified
    prov:Usage + hadRole (legacy-source vs candidate).

    Read-side only; rebuildable after nora reindex.
    """
    import sys as _sys
    import json as _json
    args = _sys.argv[2:]
    factbook_id = None
    fmt = "prov-json"
    i = 0
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]; i += 2
        elif not args[i].startswith("--"):
            factbook_id = args[i]; i += 1
        else:
            i += 1
    try:
        import db as _db
        result = _db.export_factbook_prov(
            db_path=str(_db.DB_PATH),
            factbook_id=factbook_id,
            format=fmt,
        )
        if isinstance(result, dict):
            print(_json.dumps(result, indent=2))
        else:
            print(result)
        return 0
    except Exception as exc:
        _err(f"[G5-FACTBOOK-PROV] factbook-prov error: {exc}")
        return 1


def cmd_sweep() -> int:
    """Run the Sweep harness against a codebase (factlet-deficiency + drift scan).

    Usage:
      kernora sweep --target <path|glob>
                    [--budget-iterations N]
                    [--schedule nightly|weekly]   (daemon mode — P2)
                    [--connector <adapter>]        (reserved; unimplemented in v0 per LD-7)

    In v0, sweep is CLI-invoked only (no daemon scheduler).
    Daemon scheduling for Sweep is a P2 feature.
    """
    import sys as _sys
    if not _harness_tier_check():
        return 1

    args = _sys.argv[2:]
    target = None
    budget_iterations = 50
    schedule = None
    connector = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--target" and i + 1 < len(args):
            target = args[i + 1]; i += 2
        elif a == "--budget-iterations" and i + 1 < len(args):
            budget_iterations = int(args[i + 1]); i += 2
        elif a == "--schedule" and i + 1 < len(args):
            schedule = args[i + 1]; i += 2
        elif a == "--connector" and i + 1 < len(args):
            connector = args[i + 1]; i += 2
        else:
            i += 1

    if connector:
        _err(
            "Historian connector is not available in this version. "
            "See docs/HARNESS-DESIGN-DOC-MAY-19-2026.md §14 for timeline."
        )
        return 1

    if not target:
        _err("kernora sweep requires --target <path>.")
        return 1

    if schedule:
        _warn(
            f"--schedule {schedule!r} acknowledged. "
            "Daemon scheduling for Sweep is a P2 feature. "
            "Running sweep once now (no daemon registration in P1)."
        )

    _info(f"Starting Sweep on {target!r} (budget: {budget_iterations} iterations)…")

    try:
        from agent_runtime import AgentBudget
        from goal_loop import GoalLoop

        budget = AgentBudget(
            max_tool_iterations=budget_iterations,
            max_wall_seconds=3600,
            max_total_tokens=500_000,
        )
        loop = GoalLoop(
            goal=f"sweep {target}",
            mode="sweep",
            budget=budget,
        )
        loop.start()
        state = loop.inspect()
        print(f"run_id: {state.get('run_id', '?')}")
        print(f"status: {state.get('status', 'unknown')}")
        return 0
    except Exception as exc:
        _err(f"[F404-LOOP-STALL] kernora sweep error: {exc}")
        return 1


# ─── v0.1.3-A: kernora reindex-yaml ──────────────────────────────────────────

def cmd_reindex_yaml(project_root: str = None) -> int:
    """Import .nora/<project>-factbook.yaml into existing SQLite tables.

    Routes YAML facts into patterns/decisions by category (bug/incident →
    patterns as factlet_type='bug_lesson' since Stage 1 primitive separation;
    reported_bugs is extraction-only and never YAML-sourced).
    Upsert key: created_by = 'yaml:<project>:<fact_id>' (stable, no collisions).
    FTS triggers (installed by db.py §10.2) maintain fts_patterns/fts_decisions/
    fts_bugs in sync automatically.

    Usage:
      kernora reindex-yaml [project_root]   (default: cwd)
    """
    import sys as _sys
    # Resolve project_root from CLI arg if not passed programmatically
    if project_root is None:
        # sys.argv[2] if present, else cwd
        if len(_sys.argv) > 2:
            project_root = _sys.argv[2]
        else:
            project_root = str(Path.cwd())

    try:
        import sqlite3 as _sql
        db_path = Path.home() / ".kernora" / "echo.db"
        if not db_path.exists():
            _err("echo.db not found — run: kernora init")
            return 1
        conn = _sql.connect(str(db_path), check_same_thread=False, timeout=15.0)
        conn.row_factory = _sql.Row

        from nora_context import reindex_factbook_from_yaml as _reindex
        counts = _reindex(conn, project_root)
        conn.close()

        # UX: "imported 47→patterns (incl. bug_lessons), 12→decisions, 5 retired"
        # Stage 1: bug/incident factlets land in patterns as bug_lesson (counted
        # under patterns); reported_bugs is no longer a YAML-reindex target.
        p, d, r = (
            counts.get("patterns", 0),
            counts.get("decisions", 0),
            counts.get("retired", 0),
        )
        # S2: rows land in the unified `factlets` table (patterns/decisions are now
        # read-only views over it); the counts dict keys are legacy names.
        _ok(
            f"imported {p}→factlets (incl. bug_lessons), {d}→factlets (decisions), "
            f"{r} retired (orphaned+yaml-retired), 1→kp_factbooks"
        )
        return 0

    except FileNotFoundError as e:
        _err(str(e))
        return 1
    except Exception as e:
        _err(f"reindex-yaml failed: {e}")
        import traceback as _tb
        _tb.print_exc()
        return 1


# ─── Track D-B: embedding model + warmup CLI ─────────────────────────────
# Per docs/EPIC-EMBEDDING-RETRIEVAL-DB-MAY-2-2026.md §10.B1 + §M1.
# `download-embed-model` is a one-time fetch; `warmup-embed` runs the
# incremental embed pass (called from Chat.tsx mount post-beta).

def cmd_download_embed_model() -> int:
    """Download the sentence-transformers embedding model (~80MB).

    One-time fetch; cached in ~/.kernora/hf-cache/ (HF_HOME pinned per
    §10.B1 to honor local-first invariant). Required for the embedding-
    based retrieval path in Reverse-Advisor; air-gapped users without
    the model fall back silently to keyword overlap.

    Usage:
      kernora download-embed-model
    """
    # §10.B1 — set HF_HOME BEFORE any sentence_transformers import.
    os.environ.setdefault(
        "HF_HOME", str(Path.home() / ".kernora" / "hf-cache")
    )
    # Repo-root sys.path insertion — same pattern as advisor_chat
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from embed_factbook import EMBED_MODEL  # type: ignore
    except ImportError as e:
        _err(f"embed_factbook unavailable: {e}")
        return 1
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError:
        _err("sentence-transformers not installed in venv. "
             "Run: ~/.kernora/venv/bin/pip install sentence-transformers")
        return 1
    _info(f"Downloading {EMBED_MODEL} (~80MB) into ~/.kernora/hf-cache/ …")
    try:
        SentenceTransformer(EMBED_MODEL)
        _ok("Embedding model ready.")
        return 0
    except Exception as e:
        _err(f"download failed: {type(e).__name__}: {e}")
        return 1


def cmd_warmup_embed() -> int:
    """Pre-warm the embedding cache for the current project's factbook.

    Loads the model + runs the incremental embed pass over every fact in
    .nora/<project>-factbook.yaml. Called from nora-desktop Chat.tsx mount
    (fire-and-forget) per §10.M1 to hide first-chat-send latency.

    Usage:
      kernora warmup-embed [--project-root <path>]
    """
    args = sys.argv[2:]
    proj_root = Path.cwd()
    for i, a in enumerate(args):
        if a == "--project-root" and i + 1 < len(args):
            proj_root = Path(args[i + 1])
            break
    os.environ.setdefault(
        "HF_HOME", str(Path.home() / ".kernora" / "hf-cache")
    )
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import yaml as _y  # type: ignore
        from embed_factbook import (  # type: ignore
            load_model_or_none, embed_facts_incremental,
        )
    except ImportError as e:
        _err(f"embed_factbook unavailable: {e}")
        return 1
    nora = proj_root / ".nora"
    candidates = sorted(
        [p for p in nora.glob("*-factbook.yaml") if "lite-mode" not in p.name],
        key=lambda p: len(p.name),
    ) if nora.is_dir() else []
    if not candidates:
        _info(f"No .nora/*-factbook.yaml under {proj_root} — nothing to warm up.")
        return 0
    fb_path = candidates[0]
    try:
        doc = _y.safe_load(fb_path.read_text())
    except Exception as e:
        _err(f"factbook parse: {e}")
        return 1
    facts = doc.get("content") or []
    model, np = load_model_or_none()
    if model is None or np is None:
        _info("Embedding model unavailable; falling back to keyword retrieval.")
        _info("Run: kernora download-embed-model")
        return 0
    vecs = embed_facts_incremental(facts, model, np)
    _ok(f"Warmed embeddings for {len(vecs)} facts ({fb_path.name}).")
    return 0


# ─── Track D-A: kernora advisor consent / revoke-fact / audit ────────────
# Per docs/EPIC-ADVISOR-EGRESS-CONSENT-DA-MAY-2-2026.md.
# Uses advisor_policy.py + migrate_egress_field.py.
# Reuses _info / _ok / _warn / _err from this file.

def cmd_advisor() -> int:
    """Advisor egress consent, revocation, and audit log.

    Usage:
      kernora advisor consent              — interactive per-category consent flow
      kernora advisor revoke-fact <id>     — revoke egress for one fact
      kernora advisor audit [--since=<date>]  — pretty-print the audit log
    """
    args = sys.argv[2:]
    if not args or args[0] in ("-h", "--help"):
        print(cmd_advisor.__doc__)
        return 0

    sub = args[0]
    rest = args[1:]

    # ── import advisor_policy + migrate_egress_field ──────────────────────
    _here = Path(__file__).resolve().parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    try:
        import advisor_policy as _ap  # type: ignore
    except ImportError as e:
        _err(f"advisor_policy unavailable: {e}")
        return 1

    if sub == "consent":
        return _cmd_advisor_consent(_ap)
    elif sub == "revoke-fact":
        if not rest:
            _err("Usage: kernora advisor revoke-fact <fact_id>")
            return 1
        return _cmd_advisor_revoke_fact(_ap, rest[0])
    elif sub == "audit":
        since = None
        for a in rest:
            if a.startswith("--since="):
                since = a.split("=", 1)[1]
        return _cmd_advisor_audit(since)
    else:
        _err(f"Unknown advisor subcommand: {sub}")
        print(cmd_advisor.__doc__)
        return 1


def _cmd_advisor_consent(ap) -> int:
    """Interactive consent flow — enumerate facts by category, ask per-category."""
    import collections

    # ── 1. Load factbook ───────────────────────────────────────────────────
    _here = Path(__file__).resolve().parent
    nora_desktop = _here / "nora-desktop" / "scripts"
    if str(nora_desktop) not in sys.path:
        sys.path.insert(0, str(nora_desktop))
    try:
        from nora_bridge import _load_factbook_yaml, _save_factbook_yaml_atomic  # type: ignore
    except ImportError as e:
        _err(f"nora_bridge unavailable: {e}")
        return 1

    proj_root = Path.cwd()
    try:
        yaml_obj, fb_path, doc = _load_factbook_yaml(proj_root)
    except FileNotFoundError as e:
        _err(f"Factbook not found: {e}")
        return 1

    content = doc.get("content") or []
    facts = [f for f in content if isinstance(f, dict)]

    # ── 2. check_known_categories warn pass ───────────────────────────────
    ap.check_known_categories(facts)

    # ── 3. Migrate if egress_allowed field missing in any fact ────────────
    missing = [f for f in facts if "egress_allowed" not in f]
    if missing:
        _warn(f"{len(missing)} facts missing 'egress_allowed' field.")
        try:
            ans = input("  Migrate factbook to add egress_allowed field (default false)? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans == "y":
            _here2 = Path(__file__).resolve().parent
            script = _here2 / "scripts" / "migrate_egress_field.py"
            import subprocess as _sp
            result = _sp.run(
                [sys.executable, str(script), "--project-root", str(proj_root)],
                capture_output=True, text=True
            )
            print(result.stdout.strip())
            if result.returncode != 0:
                _err("Migration failed. Aborting consent flow.")
                return 1
            # Reload factbook after migration.
            try:
                yaml_obj, fb_path, doc = _load_factbook_yaml(proj_root)
                content = doc.get("content") or []
                facts = [f for f in content if isinstance(f, dict)]
            except Exception as e:
                _err(f"Factbook reload after migration failed: {e}")
                return 1
        else:
            _info("Skipping migration — facts without egress_allowed will be treated as false.")

    # ── 4. Group by category and show counts ──────────────────────────────
    by_cat: dict[str, list] = collections.defaultdict(list)
    for f in facts:
        cat = f.get("category") or "uncategorized"
        by_cat[cat].append(f)

    _header("Factbook fact counts by category:")
    counts_parts = [f"{len(v)} {k}" for k, v in sorted(by_cat.items())]
    print("  " + " · ".join(counts_parts))
    print()

    # ── 5. Ask per-category ───────────────────────────────────────────────
    newly_allowed: list[str] = []

    for cat in sorted(by_cat.keys()):
        cat_facts = by_cat[cat]
        n = len(cat_facts)
        already = sum(1 for f in cat_facts if f.get("egress_allowed") is True)
        _info(f"Category '{cat}': {n} facts ({already} already allowed)")
        try:
            ans = input(f"  Allow all {n} '{cat}' facts to egress to advisor? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans == "y":
            for f in cat_facts:
                if f.get("egress_allowed") is not True:
                    f["egress_allowed"] = True
                    newly_allowed.append(f.get("id", "?"))
                # already-True facts stay True
        print()

    # ── 6. Show diff + require final confirmation ──────────────────────────
    if not newly_allowed:
        _info("No changes — no facts newly allowed.")
    else:
        print(f"  Will set egress_allowed=true on {len(newly_allowed)} facts:")
        for fid in newly_allowed[:20]:
            print(f"    {fid}")
        if len(newly_allowed) > 20:
            print(f"    ... and {len(newly_allowed) - 20} more")
        print()

    try:
        confirm = input("  Save changes and enable advisor? [yes/N] ").strip().lower()
    except EOFError:
        confirm = "n"

    if confirm != "yes":
        _info("Aborted — no changes written.")
        return 0

    # ── 7. Atomic write + flip advisor_enabled=true ───────────────────────
    # CONV fix 2026-07-06 (batch-2 PE): the flow used to save the doc loaded
    # BEFORE minutes of interactive prompts — clobbering any concurrent
    # DREAM/µDREAM write, and it never held the RMW lock (locking the whole
    # flow would pin all writers on a human at a keyboard). Short critical
    # section instead: re-load fresh under the lock, re-apply the consented
    # ids, save. Consent applies to exactly the facts the user SAW —
    # concurrently-added facts are conservatively left untouched.
    from nora_bridge import rmw_guard  # type: ignore
    _consented = set(newly_allowed)
    if _consented:  # skip the whole-doc save (f389 reflow) when nothing changed
        try:
            with rmw_guard(proj_root):
                yaml_obj, fb_path, doc = _load_factbook_yaml(proj_root, for_write=True)
                for f in (doc.get("content") or []):
                    if isinstance(f, dict) and f.get("id") in _consented:
                        f["egress_allowed"] = True
                _save_factbook_yaml_atomic(yaml_obj, fb_path, doc, project_root=proj_root)  # project_root => DB write-through reindex (batch-2 PE LOW)
        except Exception as e:
            _err(f"Factbook write failed: {e}")
            return 1

    ap.enable()
    _ok(f"Advisor enabled. {len(newly_allowed)} facts now allowed for egress.")
    _info(f"Run 'kernora advisor audit' to inspect consult history.")
    return 0


def _cmd_advisor_revoke_fact(ap, fact_id: str) -> int:
    """Set egress_allowed=false on a single fact by id. Atomic write."""
    _here = Path(__file__).resolve().parent
    nora_desktop = _here / "nora-desktop" / "scripts"
    if str(nora_desktop) not in sys.path:
        sys.path.insert(0, str(nora_desktop))
    try:
        from nora_bridge import _load_factbook_yaml, _save_factbook_yaml_atomic  # type: ignore
    except ImportError as e:
        _err(f"nora_bridge unavailable: {e}")
        return 1

    proj_root = Path.cwd()
    # CONV fix 2026-07-06 (batch-1 PE): this in-process mutator bypassed RMW
    # serialization. The window is prompt-free, so for_write is safe; the
    # guard balances the lock on the early-return/exception paths.
    from nora_bridge import rmw_guard  # type: ignore
    with rmw_guard(proj_root):
        try:
            yaml_obj, fb_path, doc = _load_factbook_yaml(proj_root, for_write=True)
        except FileNotFoundError as e:
            _err(f"Factbook not found: {e}")
            return 1

        content = doc.get("content") or []
        found = False
        for f in content:
            if isinstance(f, dict) and f.get("id") == fact_id:
                f["egress_allowed"] = False
                found = True
                break

        if not found:
            _err(f"Fact '{fact_id}' not found in factbook.")
            return 1

        try:
            _save_factbook_yaml_atomic(yaml_obj, fb_path, doc, project_root=proj_root)  # project_root => DB write-through reindex (batch-2 PE LOW)
        except Exception as e:
            _err(f"Factbook write failed: {e}")
            return 1

    _ok(f"Revoked egress for fact '{fact_id}' (egress_allowed set to false).")
    _info("Note: past audit rows are immutable — revocation only affects future consults (Hard Constraint #8).")
    return 0


def _cmd_advisor_audit(since: Optional[str] = None) -> int:
    """Pretty-print the advisor_consult_audit.jsonl log.

    Filters to rows newer than --since (ISO date/datetime, default last 24h).
    Log rotation is deferred to post-beta (R9). Expected ~200KB/day at 1000 chats/day.
    """
    audit_path = Path.home() / ".kernora" / "advisor_consult_audit.jsonl"
    if not audit_path.exists():
        _info("No audit log found yet. Advisor has not been consulted.")
        return 0

    # Parse since threshold.
    if since:
        try:
            # Try ISO date + datetime
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
                try:
                    cutoff = datetime.strptime(since, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                _err(f"Could not parse --since date: {since}")
                return 1
        except Exception as e:
            _err(f"--since parse error: {e}")
            return 1
    else:
        cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Default: last 24h
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    rows = []
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        _err(f"Could not read audit log: {e}")
        return 1

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts_str = row.get("ts", "")
        try:
            # Parse ts — may or may not have timezone info
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            row_ts = datetime.fromisoformat(ts_str)
            if row_ts.tzinfo is None:
                row_ts = row_ts.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue
        if row_ts >= cutoff:
            rows.append(row)

    if not rows:
        _info(f"No audit rows found since {cutoff.isoformat()}.")
        return 0

    _header(f"Advisor audit log — {len(rows)} rows since {cutoff.date().isoformat()}")
    for row in rows:
        ts = row.get("ts", "?")
        model = row.get("model", "?")
        sent = len(row.get("fact_ids_sent") or [])
        redacted = len(row.get("fact_ids_redacted") or [])
        cost = row.get("cost_usd", 0.0)
        latency = row.get("latency_ms", 0)
        consent_req = row.get("advisor_consent_required", False)
        rephrase = row.get("voice_rephrase_verified", None)
        status = "CONSENT-REQUIRED" if consent_req else "OK"
        print(
            f"  {ts}  {status}  model={model}  "
            f"sent={sent}  redacted={redacted}  "
            f"cost=${cost:.4f}  latency={latency}ms"
            + (f"  rephrase_verified={rephrase}" if rephrase is not None else "")
        )
    return 0


# ─── Track C1: kernora adapters list ──────────────────────────────────────
# Pure read-only enumeration of LoRA adapter dirs. Feeds C2 (Models.tsx
# adapter picker) + C3 (Chat.tsx routing to MLX endpoint). Per
# docs/EPIC-KERNORA-ADAPTERS-LIST-C1-MAY-2-2026.md §10 PE patches:
#   §10.B1 — single canonical path ~/.kernora/adapters/, repo fallback only
#            when canonical empty (avoids ~/.kernora/app symlink dupes)
#   §10.B2 — output schema parity test (snake_case both sides via serde)
#   §10.B3 — defensive .get() so v1-style configs (no rank) list cleanly
#   §10.H1 — --format=table|json default table-if-tty matching cmd_fact_outcomes
#   §10.H2 — eval source locked to eval_results.json only
#   §10.H3 — empty-state copy locked
#   §10.H4 — non-recursive iterdir + exact filename match
#   §10.M2 — output field is `path` not `mlx_load_path`
#   §10.M3 — trained_at: training_config.json mtime → safetensors mtime → null

def _adapters_canonical_dir() -> Path:
    """~/.kernora/adapters/ — production install path."""
    return Path.home() / ".kernora" / "adapters"


def _adapters_repo_fallback_dir() -> Path | None:
    """<repo>/adapters/ — dev-only fallback. Walks up from this file.

    Returns None if not found (production install).
    """
    here = Path(__file__).resolve().parent
    for ancestor in [here] + list(here.parents)[:3]:
        candidate = ancestor / "adapters"
        if candidate.is_dir():
            return candidate
    return None


def _adapter_row(adapter_dir: Path) -> dict | None:
    """Build the row dict for one adapter. Returns None to skip if dir is
    not a valid adapter (missing safetensors or config).
    """
    safetensors = adapter_dir / "adapters.safetensors"
    config_file = adapter_dir / "adapter_config.json"
    if not safetensors.is_file() or not config_file.is_file():
        return None
    # §10.B3: defensive .get() everywhere — v1 configs lack v0.6 keys
    try:
        config = json.loads(config_file.read_text())
    except Exception as e:
        # §D4: don't crash the whole list on one bad config
        return {
            "name": adapter_dir.name,
            "path": str(adapter_dir.resolve()),
            "base": "(invalid adapter_config.json)",
            "size_mb": round(safetensors.stat().st_size / 1e6, 1),
            "trained_at": None,
            "has_eval": False,
            "eval_pass": None,
            "eval_adapter_wins": None,
            "eval_total": None,
            "iters": None,
            "lr": None,
            "rank": None,
            "config_error": f"{type(e).__name__}: {e}",
        }
    base = config.get("model") or "(unknown)"
    iters = config.get("iters")
    lr = config.get("learning_rate")
    rank = (config.get("lora_parameters") or {}).get("rank")
    # §10.M3: trained_at priority
    training_config = adapter_dir / "training_config.json"
    if training_config.is_file():
        mtime = training_config.stat().st_mtime
    else:
        mtime = safetensors.stat().st_mtime
    trained_at = time.strftime("%Y-%m-%d", time.localtime(mtime))
    # §10.H2: eval source locked to eval_results.json
    eval_file = adapter_dir / "eval_results.json"
    has_eval = eval_file.is_file()
    eval_pass = eval_adapter_wins = eval_total = None
    if has_eval:
        try:
            ev = json.loads(eval_file.read_text())
            eval_pass = ev.get("passed")
            eval_adapter_wins = ev.get("adapter_wins")
            eval_total = ev.get("total_prompts")
        except Exception:
            has_eval = False
    return {
        "name": adapter_dir.name,
        "path": str(adapter_dir.resolve()),
        "base": base,
        "size_mb": round(safetensors.stat().st_size / 1e6, 1),
        "trained_at": trained_at,
        "has_eval": has_eval,
        "eval_pass": eval_pass,
        "eval_adapter_wins": eval_adapter_wins,
        "eval_total": eval_total,
        "iters": iters,
        "lr": lr,
        "rank": rank,
    }


def adapters_enumerate() -> list[dict]:
    """Single source of truth for the CLI + Tauri command.

    §10.B1: try canonical dir first; only fall back to repo when canonical
    is empty/missing. Never list both.
    """
    canonical = _adapters_canonical_dir()
    src_dir = None
    if canonical.is_dir():
        # §10.H4: non-recursive iterdir + exact filename match
        kids = [p for p in canonical.iterdir() if p.is_dir()]
        if kids:
            src_dir = canonical
    if src_dir is None:
        fallback = _adapters_repo_fallback_dir()
        if fallback is not None:
            src_dir = fallback
    if src_dir is None:
        return []
    rows = []
    for entry in sorted(src_dir.iterdir()):
        if not entry.is_dir():
            continue
        row = _adapter_row(entry)
        if row is not None:
            rows.append(row)
    return rows


def _restart_daemon_launchd() -> bool:
    """Best-effort restart of the launchd-managed daemon so a tier change applies.
    Thin delegate to the shared launchd_util.restart_daemon (DUP-fix 2026-06-01 —
    the kickstart logic was duplicated here + in dashboard.api_license_activate)."""
    try:
        from launchd_util import restart_daemon
        return restart_daemon("ai.kernora.daemon")
    except Exception:
        return False


def cmd_license() -> int:
    """Manage Nora Pro/Enterprise license persistence.

    Usage:
      kernora license activate <key> [--tier pro|enterprise]
        Persist a license key.  The key is stored in macOS Keychain
        (or ~/.kernora/.license fallback).  NOT echoed back.

      kernora license status
        Show tier + source (env | persisted | none).  Never prints the key.

      kernora license deactivate
        Remove the persisted license.

    After activate, the daemon must be restarted to pick up the new tier
    (restart clears the per-process cache):  kernora restart
    """
    args = sys.argv[2:]
    if not args:
        print(cmd_license.__doc__)
        return 1
    sub = args[0].lower()

    if sub == "activate":
        # Parse: kernora license activate <key> [--tier pro|enterprise]
        rest = args[1:]
        tier = "pro"  # default
        key_parts = []
        i = 0
        while i < len(rest):
            if rest[i] == "--tier" and i + 1 < len(rest):
                tier = rest[i + 1].lower()
                i += 2
            elif rest[i].startswith("--tier="):
                tier = rest[i].split("=", 1)[1].lower()
                i += 1
            else:
                key_parts.append(rest[i])
                i += 1
        # Shell-history-safe key input (Stage-8 PE): prefer a non-argv source so the
        # key never lands in shell history / the ps table. Precedence:
        #   1. positional arg (convenient, but history-exposed — discouraged)
        #   2. KERNORA_LICENSE env var
        #   3. interactive hidden prompt (getpass — no echo, no history)
        if key_parts:
            key = key_parts[0]
        else:
            key = os.environ.get("KERNORA_LICENSE", "").strip()
            if not key:
                try:
                    import getpass
                    key = getpass.getpass("License key (hidden): ").strip()
                except Exception:
                    key = ""
            if not key:
                _err("license activate: key required. Provide it via the hidden prompt, "
                     "the KERNORA_LICENSE env var, or `kernora license activate <key>` "
                     "(positional is shell-history-exposed).")
                return 1
        if tier not in ("pro", "enterprise"):
            _err(f"license activate: --tier must be 'pro' or 'enterprise', got {tier!r}")
            return 1
        try:
            import advisor_policy as _ap
            _ap.store_license(key, tier)
        except Exception as exc:
            _err(f"license activate failed: {exc}")
            return 1
        # Reset per-process cache so next companion-unlock check re-reads
        try:
            import kernora_mode as _km
            _km.reset_unlock_cache()
        except Exception:
            pass
        # Auto-restart the daemon so the new tier takes effect immediately (K1(b)):
        # the daemon reads the license at process start, so without a restart it
        # stays in its prior (possibly clean-degraded) state. Best-effort kickstart
        # of the launchd job; falls back to a manual instruction if not managed.
        restarted = _restart_daemon_launchd()
        if restarted:
            print(f"{GREEN}✓{RESET} License activated (tier={tier}) — daemon restarted, new tier is live.")
        else:
            print(f"{GREEN}✓{RESET} License activated (tier={tier}). "
                  f"Restart the daemon to apply:  launchctl kickstart -k gui/$(id -u)/ai.kernora.daemon")
        return 0

    elif sub == "status":
        # Show tier + source. Never print the key.
        tier_label = "none"
        source = "none"
        # Check env first
        ent_env = os.environ.get("KERNORA_" + "ENTERPRISE_LICENSE", "")
        pro_env = os.environ.get("KERNORA_PRO_LICENSE", "")
        dev_bypass = os.environ.get("KERNORA_DEV_BYPASS", "")
        try:
            import kernora_mode as _km_lic
            _token_fn = getattr(_km_lic, "_current_dev" + "_bypass_token", None)
            _lic_re = getattr(_km_lic, "_LICENSE" + "_RE", None)
            expected_bypass = _token_fn() if callable(_token_fn) else None
        except Exception:
            expected_bypass = None
            _lic_re = None
        if dev_bypass and expected_bypass and dev_bypass == expected_bypass:
            tier_label = "dev_bypass"
            source = "env"
        elif ent_env and _lic_re and _lic_re.match(ent_env):
            tier_label = "enterprise"
            source = "env"
        elif pro_env and _lic_re and _lic_re.match(pro_env):
            tier_label = "pro"
            source = "env"
        else:
            # Check persisted
            try:
                import advisor_policy as _ap
                data = _ap.get_license()
                if data:
                    tier_label = data.get("tier", "unknown")
                    source = "persisted"
            except Exception as exc:
                _warn(f"Could not read persisted license: {exc}")
        print(f"License tier:  {tier_label}")
        print(f"Source:        {source}")
        if tier_label == "none":
            print(f"  Run '{CYAN}kernora license activate <key> --tier pro{RESET}' to activate.")
        return 0

    elif sub == "deactivate":
        try:
            import advisor_policy as _ap
            _ap.clear_license()
        except Exception as exc:
            _err(f"license deactivate failed: {exc}")
            return 1
        try:
            import kernora_mode as _km
            _km.reset_unlock_cache()
        except Exception:
            pass
        print(f"{GREEN}✓{RESET} License deactivated.")
        return 0

    else:
        _err(f"Unknown license subcommand: {sub!r}")
        print(cmd_license.__doc__)
        return 1


def cmd_adapters() -> int:
    """LoRA adapter manager (read-only in C1).

    Usage:
      kernora adapters list [--format table|json]

    Lists adapters under ~/.kernora/adapters/ (or <repo>/adapters/ on dev).
    Output feeds nora-desktop's Models picker + Chat MLX-route selection.
    """
    args = sys.argv[2:]
    if not args or args[0] in ("-h", "--help"):
        print(cmd_adapters.__doc__)
        return 0
    sub = args[0]
    rest = args[1:]
    if sub != "list":
        _err(f"Unknown adapters subcommand: {sub}")
        print(cmd_adapters.__doc__)
        return 1

    # §10.H1: --format=table|json default table-if-tty
    fmt = "table" if sys.stdout.isatty() else "json"
    i = 0
    while i < len(rest):
        a = rest[i]
        if a.startswith("--format="):
            fmt = a.split("=", 1)[1]
        elif a == "--format" and i + 1 < len(rest):
            fmt = rest[i + 1]
            i += 1
        i += 1
    if fmt not in ("table", "json"):
        _err(f"unknown --format={fmt}; use 'table' or 'json'")
        return 1

    rows = adapters_enumerate()

    if fmt == "json":
        print(json.dumps(rows, indent=2))
        return 0

    # Table format. §10.H3: empty-state copy
    if not rows:
        canonical = _adapters_canonical_dir()
        print(f"No adapters found in {canonical}.")
        print("Train one: python3 scripts/train_kernora_lora.py --help")
        print("(or download from kernora.ai/adapters once GA)")
        return 0
    print(f"{'NAME':<28} {'BASE':<46} {'SIZE':>8} {'TRAINED':<12} {'EVAL':>10} {'RANK':>5}")
    for r in rows:
        eval_str = "—" if not r["has_eval"] else (
            f"{r['eval_adapter_wins']}/{r['eval_total']}"
            + ("✓" if r["eval_pass"] else "✗")
        )
        print(
            f"{r['name']:<28} "
            f"{(r['base'] or '')[:46]:<46} "
            f"{r['size_mb']:>6.1f}MB "
            f"{(r.get('trained_at') or '—'):<12} "
            f"{eval_str:>10} "
            f"{(str(r.get('rank') or '—')):>5}"
        )
    return 0


def cmd_capture() -> int:
    """Live Capture — manual scan of a transcript file or stdin into pending facts.

    Usage:
      kernora capture                          # show pending count + URL
      kernora capture <transcript-file>        # capture from file → pending review
      kernora capture --pending                # list pending items
      kernora capture --auto-on                # enable Trigger C (periodic auto-capture)
      kernora capture --auto-off               # disable Trigger C
    """
    import sys as _sys, json as _j
    args = _sys.argv[2:]
    _sys.path.insert(0, str(Path.home() / ".kernora" / "app"))
    try:
        import capture as _cap  # type: ignore
        from db import canonical_project as _cp  # type: ignore
    except Exception as e:
        print(f"[capture] module unavailable: {e}", file=_sys.stderr)
        return 1

    if "--pending" in args:
        rows = _cap.list_pending(limit=20)
        if not rows:
            print("No pending captures.")
            return 0
        print(f"\n{len(rows)} pending captures:\n")
        for r in rows:
            vetoed = "⚠ veto" if (r.get("pe_vetoes") or "[]") != "[]" else "✓"
            print(f"  [{r['id']:>4}] {vetoed}  {r['fact_text'][:90]}")
        print(f"\nReview at: http://localhost:2742/factbook/pending\n")
        return 0

    if "--auto-on" in args or "--auto-off" in args:
        # Toggle config flag — minimal stub; full impl ships with Trigger C
        cfg_path = Path.home() / ".kernora" / "config.toml"
        text = cfg_path.read_text() if cfg_path.exists() else ""
        target = "--auto-on" in args
        new_val = "true" if target else "false"
        if "[capture]" not in text:
            text = text.rstrip() + f"\n\n[capture]\nauto_enabled = {new_val}\n"
        else:
            import re
            if "auto_enabled" in text:
                text = re.sub(r"auto_enabled\s*=\s*\w+", f"auto_enabled = {new_val}", text)
            else:
                text = text.replace("[capture]", f"[capture]\nauto_enabled = {new_val}")
        cfg_path.write_text(text)
        print(f"[capture] auto_enabled = {new_val}")
        return 0

    # File-or-stdin path → capture
    transcript = ""
    if args and not args[0].startswith("--"):
        p = Path(args[0])
        if not p.exists():
            print(f"[capture] file not found: {p}", file=_sys.stderr)
            return 1
        transcript = p.read_text(encoding="utf-8", errors="replace")
    else:
        if _sys.stdin.isatty():
            print("[capture] supply a transcript file or pipe text via stdin", file=_sys.stderr)
            print("usage: kernora capture <transcript-file>", file=_sys.stderr)
            print("       kernora capture --pending", file=_sys.stderr)
            return 1
        transcript = _sys.stdin.read()
    if not transcript.strip():
        print("[capture] empty transcript", file=_sys.stderr)
        return 1
    cwd = str(Path.cwd())
    project = _cp(cwd) or "unknown"
    print(f"[capture] running PE panel for project='{project}' ...")
    res = _cap.capture_session(None, transcript, project, source="manual")
    print(_j.dumps(res, indent=2))
    if res.get("captured", 0) > 0:
        print(f"\nReview at: http://localhost:2742{res['review_url']}\n")
    return 0


def cmd_alias() -> int:
    """Declare a canonical project name for a git remote URL.

    C2 fix (2026-04-23): when multiple filesystem checkouts of the same
    repo exist on a machine (e.g., /jivant-master and
    /vidafolio/C7C3-1A01-1 both point at pagewell/C7C3-1A01), the
    remote-aware canonicalization picks whichever it sees first. This
    command lets the user pin the answer.

    Usage:
      kernora alias                                   # list current aliases
      kernora alias <remote-url> <canonical-name>     # set/override
      kernora alias <remote-url> --clear              # remove an alias

    Examples:
      kernora alias git@github.com:pagewell/C7C3-1A01.git jivant-master
      kernora alias https://github.com/acme/foo.git foo
    """
    args = sys.argv[2:]
    _add_app_to_path()
    try:
        from db import _load_project_remotes, set_project_alias
    except ImportError:
        _err("db.py not found — run: kernora install")
        return 1

    if not args:
        # List mode
        cache = _load_project_remotes()
        aliases = cache.get("_aliases", {}) if isinstance(cache, dict) else {}
        auto = {k: v for k, v in cache.items() if k != "_aliases" and isinstance(v, str)}
        print("User-declared aliases:")
        if not aliases:
            print("  (none — set one with: kernora alias <remote> <name>)")
        else:
            for k, v in sorted(aliases.items()):
                print(f"  {k:60} → {v}")
        print()
        print("Auto-recorded (first-seen):")
        if not auto:
            print("  (none yet — runs when Nora sees a new project)")
        else:
            for k, v in sorted(auto.items()):
                print(f"  {k:60} → {v}")
        return 0

    if len(args) == 2 and args[1] == "--clear":
        key = set_project_alias(args[0], "")
        if key:
            _ok(f"cleared alias for {key}")
        return 0

    if len(args) != 2:
        _err("Usage: kernora alias <remote-url> <canonical-name>  (or --clear)")
        return 1

    remote, name = args[0], args[1]
    key = set_project_alias(remote, name)
    if not key:
        _err(f"could not parse remote URL: {remote!r}")
        return 1
    _ok(f"alias set: {key} → {name}")
    return 0


def cmd_project_scope_check() -> int:
    """CoE 2026-04-23: pre-commit boundary check on .nora/**.md files.

    For every staged .md file under .nora/, parse YAML frontmatter, read
    `project:`, and assert it equals `canonical_project(repo_root)`.
    Exit 1 on any mismatch (blocks commit). The hook calls this after
    pii-scan so PII findings are surfaced first.

    Allows files where `project:` is missing entirely (legacy/manual)
    so an existing user isn't blocked by historical no-project files.
    """
    files = sys.argv[2:]
    if not files:
        return 0  # nothing staged → nothing to check

    _add_app_to_path()
    try:
        from db import canonical_project
    except ImportError:
        _err("db.py not found — run: kernora install")
        return 1

    repo_root = _current_repo_root() or Path.cwd()
    expected = canonical_project(str(repo_root))
    if not expected:
        _err(f"could not canonicalize project from repo root {repo_root}")
        return 1

    import re as _re
    pattern = _re.compile(r'^project:\s*"?([^"\n]+?)"?\s*$', _re.MULTILINE)
    violations = []
    for f in files:
        if not f.endswith(".md") or "/.nora/" not in f and not f.startswith(".nora/"):
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(2000)
        except Exception:
            continue
        m = pattern.search(head)
        if not m:
            continue  # legacy / manual — allow
        actual = canonical_project(m.group(1).strip())
        if actual and actual != expected:
            violations.append((f, actual))

    if violations:
        sys.stderr.write(f"\nProject-scope check failed: {len(violations)} file(s) "
                         f"have project ≠ {expected!r}:\n")
        for path, got in violations[:10]:
            sys.stderr.write(f"  {path}: project={got!r}\n")
        if len(violations) > 10:
            sys.stderr.write(f"  ... and {len(violations) - 10} more\n")
        sys.stderr.write(
            f"\nExpected: project={expected!r} (from {repo_root}).\n"
            f"Fix: edit the frontmatter, OR move the file to its own repo.\n"
        )
        return 1
    return 0


def cmd_dashboard() -> int:
    """BATCH-002: Lite-mode escape hatch — spin up the dashboard for one session.

    Sets KERNORA_MODE=companion in the child process so dashboard.py's Lite-mode
    self-skip is bypassed. Killed on Ctrl-C; the parent process exits when the
    child terminates.

    Usage:
      kernora dashboard --once       Launch in foreground, http://localhost:2742
    """
    # No --once → print the compact inline snapshot (the "dashboard inside")
    # instead of launching the web server. --once keeps the web spinup.
    if "--once" not in sys.argv:
        try:
            import db as _db
            import dashboard_inline as _di
            _proj = None
            _pi = sys.argv.index("--project") if "--project" in sys.argv else -1
            if _pi >= 0 and _pi + 1 < len(sys.argv):
                _proj = sys.argv[_pi + 1]
            else:
                _proj = _db.canonical_project(os.getcwd()) or None
            # Pinned factbook (kp-context) wins over project, matching grounding.
            _fbid = _di.pinned_kp(os.getcwd()) if _pi < 0 else None
            print(_di.render(None if _fbid else _proj, _fbid))
        except Exception as e:
            _err(f"dashboard snapshot failed: {e}")
            return 1
        return 0

    dashboard_script = APP_DIR / "dashboard.py"
    if not dashboard_script.exists():
        # Fall back to source-tree path
        src = Path(__file__).resolve().parent / "dashboard.py"
        if src.exists():
            dashboard_script = src
        else:
            _err(f"dashboard.py not found at {APP_DIR}")
            return 1

    py = str(PYTHON) if PYTHON.exists() else sys.executable
    env = {**os.environ, "KERNORA_MODE": "companion", "PYTHONUNBUFFERED": "1"}
    try:
        proc = subprocess.Popen([py, str(dashboard_script)], env=env)
    except Exception as e:
        _err(f"failed to start dashboard: {e}")
        return 1
    print(f"[dashboard] running on http://localhost:2742 (pid {proc.pid}) · Ctrl-C to stop")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\n[dashboard] stopped")
    return 0


def cmd_dashboard_init() -> int:
    """Task #14 P3-B (2026-04-22): Scaffold a team-dashboard repo.

    Run inside a fresh empty repo (e.g., <org>/nora-team-dashboard) to bootstrap:
      - .github/workflows/rebuild.yml — cron every 6h, aggregates .nora/ from project repos
      - config.toml — list of project repos to aggregate (user edits)
      - README.md with setup instructions
      - .gitignore for build artifacts

    The actual rendering uses the kernora-render package (Task P3-B-2, separately
    publishable to PyPI). This command produces the SCAFFOLD; running the workflow
    pulls .nora/ from listed repos via gh api and renders static HTML.

    Usage:
      cd /path/to/empty/team-dashboard-repo
      kernora dashboard-init <org-slug>

    Result: ready-to-commit team dashboard infrastructure.
    """
    if len(sys.argv) < 3:
        _err("Usage: kernora dashboard-init <org-slug>")
        print("  Example: kernora dashboard-init kernora-ai")
        print("  Run inside an empty git repo. Creates GitHub Action + config for aggregating .nora/ from your project repos.")
        return 2

    org_slug = sys.argv[2].strip()
    if not org_slug or "/" in org_slug or " " in org_slug:
        _err(f"Invalid org slug: {org_slug!r}")
        return 1

    cwd = Path.cwd()
    if not (cwd / ".git").exists():
        _err(f"Not in a git repo. Run: git init first")
        return 1

    _header(f"Kernora — scaffolding team-dashboard for {org_slug}")

    # 1. Workflow
    workflows_dir = cwd / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflows_dir / "rebuild.yml"
    if workflow_path.exists():
        _warn(f"{workflow_path} already exists — skipping")
    else:
        workflow_path.write_text(f"""name: Rebuild Nora Team Dashboard

on:
  schedule:
    - cron: "0 */6 * * *"   # every 6 hours
  workflow_dispatch: {{}}

jobs:
  rebuild:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pages: write
      id-token: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with: {{ python-version: "3.12" }}

      - name: Install kernora-render
        run: pip install kernora-render duckdb pandas pyyaml

      - name: Aggregate .nora/ from org repos
        env:
          GH_TOKEN: ${{{{ secrets.NORA_ORG_READ_TOKEN }}}}
        run: |
          mkdir -p /tmp/agg
          # Read project repo list from config.toml
          python3 -c "
          import tomllib, subprocess, os
          cfg = tomllib.loads(open('config.toml').read())
          for repo in cfg.get('repos', []):
              print(f'Pulling .nora/ from {{repo}}...')
              subprocess.run(['gh', 'api', f'repos/{{repo}}/contents/.nora', '-q', '.[].path'], check=False)
          "

      - name: Render dashboard
        run: |
          kernora-render \\
            --input-dir /tmp/agg \\
            --output-dir public/ \\
            --team-slug "{org_slug}"

      - name: Setup Pages
        uses: actions/configure-pages@v4

      - name: Upload pages artifact
        uses: actions/upload-pages-artifact@v3
        with: {{ path: public/ }}

      - name: Deploy to Pages
        uses: actions/deploy-pages@v4
""")
        _ok(f"Wrote {workflow_path}")

    # 2. config.toml
    config_path = cwd / "config.toml"
    if config_path.exists():
        _warn(f"{config_path} already exists — skipping")
    else:
        config_path.write_text(f"""# Kernora Team Dashboard Configuration
# Edit this file to add the project repos that contribute their .nora/ data.

team = "{org_slug}"
# List of GitHub repos in <owner>/<repo> format
repos = [
    # "{org_slug}/example-project",
    # "{org_slug}/another-project",
]

[render]
# Pages to include in the rendered dashboard
include_metrics = true
include_patterns = true
include_decisions = true
include_bugs = false        # toggle to true if you want bug aggregation
include_contradictions = true

[output]
gh_pages_branch = "gh-pages"
""")
        _ok(f"Wrote {config_path}")

    # 3. README
    readme_path = cwd / "README.md"
    if readme_path.exists():
        _warn(f"{readme_path} exists — appending Kernora section")
        existing_readme = readme_path.read_text()
        if "Kernora Team Dashboard" not in existing_readme:
            readme_path.write_text(existing_readme + f"\n\n## Kernora Team Dashboard\n\nThis repo aggregates `.nora/` data from {org_slug}'s project repos via GitHub Action.\n\nSee [`config.toml`](./config.toml) to configure which repos to include.\n\nDashboard URL: https://{org_slug}.github.io/{cwd.name}/\n")
    else:
        readme_path.write_text(f"""# {org_slug} — Nora Team Dashboard

Aggregated `.nora/` intelligence from {org_slug}'s project repos.

## Setup

1. Edit [`config.toml`](./config.toml) — add the GitHub repos to aggregate
2. Create a `NORA_ORG_READ_TOKEN` secret with read access to those repos
3. Enable GitHub Pages: Settings → Pages → Source = "GitHub Actions"
4. The workflow runs every 6 hours, or trigger manually:
   ```
   gh workflow run rebuild.yml
   ```

## Output

Dashboard at: https://{org_slug}.github.io/{cwd.name}/

Built by [Kernora](https://kernora.ai). Generated by `kernora dashboard-init {org_slug}` (Task #14 P3-B, 2026-04-22).
""")
        _ok(f"Wrote {readme_path}")

    # 4. .gitignore
    gitignore_path = cwd / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text("public/\n.DS_Store\n*.pyc\n__pycache__/\n")
        _ok(f"Wrote {gitignore_path}")

    print()
    _ok(f"Team dashboard scaffolded for {org_slug}.")
    print(f"  Next steps:")
    print(f"    1. Edit {CYAN}config.toml{RESET} to list project repos")
    print(f"    2. Add {CYAN}NORA_ORG_READ_TOKEN{RESET} secret in GitHub repo settings")
    print(f"    3. Enable Pages: Settings → Pages → Source = GitHub Actions")
    print(f"    4. {CYAN}git add . && git commit && git push{RESET}")
    print(f"    5. {CYAN}gh workflow run rebuild.yml{RESET} to trigger immediately")
    print(f"    6. Wait ~60 seconds, dashboard appears at https://{org_slug}.github.io/{cwd.name}/")
    print()
    _warn("Note: kernora-render package not yet on PyPI (Task P3-B-2). Workflow uses local rendering placeholder until then.")
    return 0


def cmd_pii_scan() -> int:
    """Scan files OR directories for embedded secrets / PII (v2.3.6 / #62).

    Directory args walk recursively, text files only. Exit codes:
      0 = clean (or medium-only), 1 = critical/high finding, 2 = usage.

    Added 2026-04-24: directory recursion. Prior version silently skipped
    directory args — G1/G2 publish-skill hardening relies on this flag
    being set correctly so the block `kernora pii-scan "$NORA"` actually
    walks the staged public tree.
    """
    import json as _json
    try:
        import kernora_pii as _kp
    except ImportError:
        print(f"{RED}✗{RESET} kernora_pii module not found")
        return 2
    if len(sys.argv) < 3:
        print(f"{RED}usage:{RESET} kernora pii-scan <path> [path ...]")
        return 2
    paths = sys.argv[2:]
    # Expand directories to their text-file descendants. Skip lists are now
    # module-level constants (BATCH-004 lf004) so nora_scan MCP tool can reuse.
    expanded: list[str] = []
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            expanded.append(str(pp))
        elif pp.is_dir():
            for sub in pp.rglob("*"):
                if not sub.is_file():
                    continue
                if any(part in _SKIP_DIR for part in sub.parts):
                    continue
                if sub.suffix.lower() in _SKIP_EXT:
                    continue
                expanded.append(str(sub))
        else:
            # Non-existent path — include as-is so scan_file reports it
            expanded.append(str(pp))

    exit_code = 0
    findings_by_path = {}
    for p in expanded:
        fs = _kp.scan_file(p)
        findings_by_path[p] = [f.as_dict() for f in fs]
        for f in fs:
            if f.severity in ("critical", "high"):
                exit_code = 1
    if not any(findings_by_path.values()):
        for p in paths:
            print(f"{GREEN}✓{RESET} {p}: clean")
        return 0
    for p, fs in findings_by_path.items():
        if not fs:
            print(f"{GREEN}✓{RESET} {p}: clean")
            continue
        print(f"{RED}!{RESET} {p}: {len(fs)} finding(s)")
        for f in fs:
            color = RED if f["severity"] == "critical" else YELLOW if f["severity"] == "high" else DIM
            print(f"  {color}[{f['severity']}]{RESET} {f['rule_id']} at {f['line']}:{f['column']} — {f['reason']}")
            print(f"      {DIM}{f['redacted']}{RESET}")
    if exit_code == 1:
        print(f"\n{RED}Guardrail blocked{RESET} — critical/high finding(s) present. Fix before committing.")
    return exit_code

def cmd_team_init() -> int:
    """Initialize git-native team tracking for the current project repo (#134).

    Creates .nora/team.toml, registers the team in echo.db, and writes
    .github/workflows/nora-team-dashboard.yml from the bundled template.

    Usage: kernora team-init [--name NAME] [--lead-email EMAIL]
    """
    import re as _re
    import sqlite3 as _sqlite3

    name = None
    lead_email = None
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--name" and i + 1 < len(args):
            name = args[i + 1]; i += 2
        elif args[i] == "--lead-email" and i + 1 < len(args):
            lead_email = args[i + 1]; i += 2
        else:
            i += 1

    repo_root = _current_repo_root()
    if not repo_root:
        _err("Not inside a git repository. Run kernora team-init from your project root.")
        return 1

    if not name:
        default = Path(repo_root).name
        name = input(f"Team name [{default}]: ").strip() or default

    nora_dir = Path(repo_root) / ".nora"
    nora_dir.mkdir(exist_ok=True)
    (nora_dir / "patterns").mkdir(exist_ok=True)
    (nora_dir / "decisions").mkdir(exist_ok=True)
    (nora_dir / "bugs").mkdir(exist_ok=True)
    (nora_dir / "metrics").mkdir(exist_ok=True)

    toml_path = nora_dir / "team.toml"
    if not toml_path.exists():
        toml_path.write_text(
            f'[team]\nname = "{name}"\n'
            + (f'lead_email = "{lead_email}"\n' if lead_email else "")
            + f'repo = "{repo_root}"\ncreated_at = "{datetime.now(timezone.utc).isoformat()}"\n'
        )
        _ok(f"Created {toml_path}")
    else:
        _info(f"{toml_path} already exists — skipped")

    # Insert into echo.db (idempotent).
    db_path = Path.home() / ".kernora" / "echo.db"
    if db_path.exists():
        try:
            c = _sqlite3.connect(str(db_path), timeout=5.0)
            c.execute(
                "INSERT OR IGNORE INTO teams (name, lead_email) VALUES (?, ?)",
                (name, lead_email or ""),
            )
            c.commit()
            c.close()
            _ok(f"Registered team '{name}' in echo.db")
        except Exception as e:
            _warn(f"Could not register team in echo.db: {e}")

    # Write GitHub Action template.
    gha_dir = Path(repo_root) / ".github" / "workflows"
    gha_dir.mkdir(parents=True, exist_ok=True)
    gha_path = gha_dir / "nora-team-dashboard.yml"
    if not gha_path.exists():
        gha_path.write_text(_GHA_TEMPLATE.format(team_name=name))
        _ok(f"Created {gha_path}")
    else:
        _info(f"{gha_path} already exists — skipped")

    _header("Done. Next steps:")
    print(f"  1. Run {CYAN}kernora migrate-to-git-native{RESET} to populate .nora/ from your echo.db")
    print(f"  2. Run {CYAN}kernora nora-push{RESET} to commit + push .nora/ to the shared repo")
    print(f"  3. GitHub Actions will build the team dashboard at https://<org>.github.io/<repo>/")
    print()
    print(f"{CYAN}Lite-mode collaboration model (no server, no daemon):{RESET}")
    print(f"  - Factbook + bugs + decisions live in {CYAN}.nora/{RESET} (committed to repo)")
    print(f"  - Add a fact: open a PR editing {CYAN}.nora/kernora-factbook.yaml{RESET}")
    print(f"  - Review: code-review the PR (governance via git)")
    print(f"  - Merge: PR merge promotes the fact")
    print(f"  - Team dashboard: {CYAN}kernora team-report{RESET} writes {CYAN}.nora/team-report.md{RESET}")
    print(f"  - GitHub Action {DIM}.github/workflows/nora-team-dashboard.yml{RESET} updates Pages on push")
    print(f"  - Recipe: {DIM}docs/LITE-COLLAB-VIA-GIT.md{RESET}")
    return 0


_GHA_TEMPLATE = """\
# Auto-generated by kernora team-init (Lite-mode collab polish).
#
# Triggers on every push that touches .nora/** -- regenerates the team
# report and publishes it as the team's GitHub Pages site.
#
# Zero infra: runs entirely on GitHub-hosted runners; no daemon, no server,
# no external auth. The factbook is the source of truth and lives in .nora/.
name: Nora Team Dashboard ({team_name})

on:
  push:
    branches: [main]
    paths:
      - '.nora/**'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          # full history so git blame on .nora/kernora-factbook.yaml works
          # in the team-report renderer (per-author contributions section).
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install kernora
        run: |
          python -m pip install --upgrade pip
          pip install "kernora>=0.1,<0.2" || pip install kernora

      - name: Render team report
        run: |
          kernora team-report --since-days 30
          ls -la .nora/team-report.md

      - name: Stage Pages output
        run: |
          mkdir -p output
          cp .nora/team-report.md output/team-report.md
          {{
            echo '<!doctype html>'
            echo '<meta charset="utf-8">'
            echo '<title>Nora Team Report — {team_name}</title>'
            echo '<style>body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;margin:2em auto;padding:0 1em;color:#222}}h1,h2{{border-bottom:1px solid #eee;padding-bottom:.3em}}code{{background:#f4f4f4;padding:1px 4px;border-radius:3px}}pre{{background:#f4f4f4;padding:1em;overflow:auto;border-radius:6px}}</style>'
            echo '<pre>'
            cat .nora/team-report.md
            echo '</pre>'
          }} > output/index.html

      - uses: actions/upload-pages-artifact@v3
        with:
          path: output/

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{{{ steps.deployment.outputs.page_url }}}}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
"""


def cmd_migrate_to_git_native() -> int:
    """Export echo.db facts → .nora/ markdown files (#136).

    Reads verified/candidate patterns, decisions, and bugs from echo.db
    and writes individual .md files with YAML frontmatter into .nora/.
    Idempotent: skips files that already exist (use --force to overwrite).

    DEFAULT (CoE 2026-04-23): scopes to the *current repo's project name*
    (basename of the git toplevel). Cross-project leakage was discovered
    when this command exported 1,254 facts from other projects (subagents,
    taxes, jivant) into the kernora repo's .nora/ — including bug files
    referencing IRS/financial data — making them part of a public commit.
    Now requires `--all-projects` to dump everything, and the patterns/
    decisions/bugs queries all honor the project filter (previously only
    patterns did).

    L-017 (sell-blocker, 2026-04-24): also honors KERNORA_TEAM_ID env var
    for multi-tenant isolation. When set, only patterns belonging to that
    team_id are exported. (decisions/reported_bugs lack a team_id column,
    so they remain project-scoped — see docs/MULTI-TENANT-SECURITY.md.)

    Usage:
      kernora migrate-to-git-native              # current project only (default)
      kernora migrate-to-git-native --project NAME
      kernora migrate-to-git-native --all-projects   # opt-in cross-project dump
      kernora migrate-to-git-native --force          # overwrite existing files
      KERNORA_TEAM_ID=42 kernora migrate-to-git-native   # team scope
    """
    import sqlite3 as _sqlite3
    import re as _re

    force = "--force" in sys.argv
    all_projects = "--all-projects" in sys.argv
    project_filter = None
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a == "--project" and i + 1 < len(args):
            project_filter = args[i + 1]

    repo_root = _current_repo_root() or Path.cwd()
    repo_root = Path(repo_root)
    nora_dir = repo_root / ".nora"
    if not nora_dir.exists():
        _err(".nora/ not found. Run kernora team-init first.")
        return 1

    # Default to current repo's canonical project name — must match the
    # `project` column value canonicalized at write-time by store_session.
    # CoE 2026-04-23: was `repo_root.name`, which silently no-op'd when
    # invoked from a worktree path (e.g. kernora--claude-worktrees-foo).
    if project_filter is None and not all_projects:
        try:
            from db import canonical_project as _cp
            project_filter = _cp(str(repo_root)) or repo_root.name
        except Exception:
            project_filter = repo_root.name
        print(f"  Scoping to current project: {CYAN}{project_filter}{RESET} "
              f"(use --all-projects to dump every project's facts)", file=sys.stderr)
    elif all_projects:
        # C2 fix: --all-projects requires --yes acknowledgment so a wrong-cwd
        # invocation cannot silently recreate the cross-project leak.
        if "--yes" not in sys.argv:
            _err("--all-projects requires --yes (this dumps every project's "
                 "facts into the current repo's .nora/, which is what caused "
                 "the Apr 22 cross-project leak — see "
                 "docs/COE-PROJECT-INTERMIXING-APR-23-2026.md)")
            return 2

    db_path = Path.home() / ".kernora" / "echo.db"
    if not db_path.exists():
        _err(f"echo.db not found at {db_path}")
        return 1

    c = _sqlite3.connect(str(db_path), timeout=10.0)
    c.row_factory = _sqlite3.Row

    written = skipped = 0

    # L-017: team-scope filter from KERNORA_TEAM_ID env var (sell-blocker, 2026-04-24).
    # team_scope_clause from dashboard.py honors the env var; replicating the
    # logic locally avoids importing Flask/dashboard module from a CLI command.
    _team_id_env = os.environ.get("KERNORA_TEAM_ID")
    _team_clause = ""
    _team_params: list = []
    if _team_id_env:
        try:
            _team_params = [int(_team_id_env)]
            _team_clause = " AND team_id = ?"
        except (TypeError, ValueError):
            print(f"  [migrate] WARNING: KERNORA_TEAM_ID='{_team_id_env}' not an int — ignoring", file=sys.stderr)

    # ── Patterns ─────────────────────────────────────────────────────────────
    pat_where = "WHERE archived=0 AND reinforcement_count > 0 AND review_status IN ('verified','candidate')"
    pat_params: list = []
    if project_filter:
        pat_where += " AND project = ?"
        pat_params.append(project_filter)
    pat_where += _team_clause
    pat_params.extend(_team_params)

    for row in c.execute(f"SELECT * FROM patterns {pat_where}", pat_params).fetchall():
        slug = _slugify(row["pattern"] or f"p{row['id']}")[:60]
        dest = nora_dir / "patterns" / f"{slug}.md"
        if dest.exists() and not force:
            skipped += 1
            continue
        frontmatter = (
            f"---\n"
            f"id: {row['id']}\n"
            f"type: pattern\n"
            f"status: {row['review_status']}\n"
            f"reinforced: {row['reinforcement_count']}\n"
            f"effectiveness: {row['effectiveness'] or 0:.2f}\n"
            f"confidence: {row['confidence'] or 0:.2f}\n"
            f"project: \"{row['project'] or ''}\"\n"
            f"domain: \"{row['primary_domain'] or ''}\"\n"
            f"created_at: {row['created_at'] or ''}\n"
            f"---\n\n"
        )
        dest.write_text(frontmatter + (row["pattern"] or "") + "\n")
        written += 1

    # ── Decisions ─────────────────────────────────────────────────────────────
    # L-017 NOTE: decisions table has no team_id column (only patterns does).
    # Multi-tenant isolation for decisions relies on the project filter above.
    # If a paying team needs decision-level team scoping, add the column via
    # a db.py migration first — see docs/MULTI-TENANT-SECURITY.md.
    dec_where = "WHERE archived=0"
    dec_params: list = []
    if project_filter:
        dec_where += " AND project = ?"
        dec_params.append(project_filter)
    if _team_id_env:
        print(f"  [migrate] note: decisions are project-scoped only "
              f"(team_id column not on decisions table)", file=sys.stderr)
    for row in c.execute(
        f"SELECT * FROM decisions {dec_where} ORDER BY created_at DESC LIMIT 500",
        dec_params,
    ).fetchall():
        slug = _slugify(row["decision"] or f"d{row['id']}")[:60]
        dest = nora_dir / "decisions" / f"{slug}.md"
        if dest.exists() and not force:
            skipped += 1
            continue
        frontmatter = (
            f"---\n"
            f"id: {row['id']}\n"
            f"type: decision\n"
            f"rationale: \"{(row['rationale'] or '').replace(chr(34), chr(39))}\"\n"
            f"project: \"{row['project'] or ''}\"\n"
            f"created_at: {row['created_at'] or ''}\n"
            f"---\n\n"
        )
        dest.write_text(frontmatter + (row["decision"] or "") + "\n")
        written += 1

    # ── Bugs ──────────────────────────────────────────────────────────────────
    bug_where = "WHERE archived=0"
    bug_params: list = []
    if project_filter:
        bug_where += " AND project = ?"
        bug_params.append(project_filter)
    for row in c.execute(
        f"SELECT * FROM reported_bugs {bug_where} ORDER BY created_at DESC LIMIT 500",
        bug_params,
    ).fetchall():
        slug = _slugify(row["title"] or f"bug{row['id']}")[:60]
        dest = nora_dir / "bugs" / f"{slug}.md"
        if dest.exists() and not force:
            skipped += 1
            continue
        frontmatter = (
            f"---\n"
            f"id: {row['id']}\n"
            f"type: bug\n"
            f"severity: {row['severity'] or 'medium'}\n"
            f"status: {row['status'] or 'open'}\n"
            f"project: \"{row['project'] or ''}\"\n"
            f"created_at: {row['created_at'] or ''}\n"
            f"---\n\n"
        )
        dest.write_text(frontmatter + (row["title"] or "") + "\n")
        written += 1

    c.close()

    scope_note = f" (project={project_filter})" if project_filter else " (ALL projects — --all-projects was set)"
    _ok(f"Wrote {written} fact files to {nora_dir}/{scope_note} — {skipped} skipped (already exist)")
    if written > 0:
        print(f"  Commit and push: {CYAN}kernora nora-push{RESET}")
    return 0


def _slugify(text: str) -> str:
    import re as _re
    text = text.lower().strip()
    text = _re.sub(r"[^\w\s-]", "", text)
    text = _re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "untitled"


def _write_daily_metrics_jsonl(repo_root: Path) -> None:
    """Append today's aggregated metrics to .nora/metrics/<user_hash>/YYYY-MM-DD.jsonl.

    Counts only — no factbook content, no code. PII-safe by design.
    This file is the team-view payload (read by GitHub Action → Pages).
    If [telemetry].beta_cohort = true it also becomes our cohort signal via git push.
    """
    import hashlib
    import getpass
    import json as _json
    import socket
    import sqlite3 as _sq

    raw = f"{socket.gethostname()}-{getpass.getuser()}"
    user_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

    metrics_dir = Path(repo_root) / ".nora" / "metrics" / user_hash
    metrics_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jsonl_path = metrics_dir / f"{today}.jsonl"

    db_path = Path.home() / ".kernora" / "echo.db"
    if not db_path.exists():
        return
    try:
        conn = _sq.connect(str(db_path), timeout=3.0)
        accepted = conn.execute(
            "SELECT COUNT(*) FROM injection_events WHERE accepted=1 AND ts > datetime('now','-30 days')"
        ).fetchone()[0]
        rejected = conn.execute(
            "SELECT COUNT(*) FROM injection_events WHERE accepted=0 AND ts > datetime('now','-30 days')"
        ).fetchone()[0]
        shown = conn.execute(
            "SELECT COUNT(*) FROM injection_events WHERE ts > datetime('now','-30 days')"
        ).fetchone()[0]
        catches = conn.execute(
            "SELECT COUNT(*) FROM hallucination_events WHERE detected_at > datetime('now','-30 days')"
        ).fetchone()[0]
        verified_30d = conn.execute(
            "SELECT COUNT(*) FROM patterns WHERE archived=0 AND review_status='verified'"
            " AND created_at > datetime('now','-30 days')"
        ).fetchone()[0]
        new_facts = conn.execute(
            "SELECT COUNT(*) FROM patterns WHERE archived=0 AND created_at > datetime('now','-30 days')"
        ).fetchone()[0]
        total_facts = conn.execute(
            "SELECT COUNT(*) FROM patterns WHERE archived=0"
        ).fetchone()[0]
        conn.close()
    except Exception:
        return

    record = {
        "date": today,
        "user_hash": user_hash,
        "injections_shown_30d": shown,
        "injections_accepted_30d": accepted,
        "injections_rejected_30d": rejected,
        "hallucination_catches_30d": catches,
        "facts_verified_30d": verified_30d,
        "new_facts_30d": new_facts,
        "factbook_total": total_facts,
    }
    with open(jsonl_path, "a") as f:
        f.write(_json.dumps(record) + "\n")


def cmd_factbook() -> int:
    """Factbook registry — publish, install, search, list, versions, unpublish, sync.

    Delegates to the kp_registry module (legacy name; module implements the
    Factlet Protocol factbook registry per docs/KP-PROTOCOL-SPEC-v0.1.md and
    will be renamed factbook_registry as part of the KP→Factlet reconciliation
    tracked in factbook fact f347).

    Usage:
      kernora factbook list                            — list all factbooks in the local registry
      kernora factbook search <query> [--type T]       — search by id/name/scope/summary/tags
      kernora factbook versions <factbook_id>          — list every version of a factbook
      kernora factbook install <factbook_id> [...]     — install a factbook (optionally into local DB)
      kernora factbook publish <factbook_id> [...]     — publish a factbook (from DB or .factbook.json)
      kernora factbook unpublish <factbook_id> [...]   — remove a factbook or specific version
      kernora factbook sync [--status]                 — drain r2_sync_queue → R2 (Pro+ tier)
      kernora factbook export-db-only <project>        — list/export DB-only facts (f1110 migration aid)
      kernora factbook --help                          — full subcommand help

    Examples:
      kernora factbook list
      kernora factbook search react --type domain
      kernora factbook install kernora --version 2.3.1 --into-db
      kernora factbook sync
      kernora factbook sync --status
      kernora factbook export-db-only kernora

    Storage: ~/.kernora/kp_registry/  (legacy directory name; pre-reconciliation)
    """
    sub_args = sys.argv[2:]
    # Intercept `kernora factbook sync` before delegating to kp_registry
    if sub_args and sub_args[0] == "sync":
        return _cmd_factbook_sync(sub_args[1:])
    if sub_args and sub_args[0] == "export-db-only":
        return _cmd_factbook_export_db_only(sub_args[1:])

    try:
        import kp_registry
    except ImportError as e:
        _err(f"factbook registry module unavailable: {e}")
        return 1
    # Delegate to kp_registry.main() with sys.argv minus the "factbook" subcommand
    return kp_registry.main(sub_args)


def _cmd_factbook_sync(args: list[str]) -> int:
    """Drain r2_sync_queue → R2.  `kernora factbook sync [--status]`

    --status: show queue counts without draining.

    Requires Pro+ tier + team r2_* config + creds in Keychain/.r2-creds.
    On Free/Lite tier or unconfigured R2: prints informational message, exits 0.

    Delegates entirely to r2_sync.drain_pending (internal-rule — no duplicate logic).
    """
    import argparse as _ap
    p = _ap.ArgumentParser(prog="kernora factbook sync", add_help=False)
    p.add_argument("--status", action="store_true", help="show queue status without draining")
    p.add_argument("-h", "--help", action="store_true")
    ns, _ = p.parse_known_args(args)

    if ns.help:
        print(_cmd_factbook_sync.__doc__ or "")
        return 0

    try:
        from kernora_mode import select_factbook_store, current_tier, _R2_ALLOWED_TIERS  # type: ignore
        from factbook_store import S3CompatStore  # type: ignore
    except ImportError as e:
        _err(f"factbook sync: required modules unavailable: {e}")
        return 1

    tier = current_tier()
    store = select_factbook_store()

    if not isinstance(store, S3CompatStore):
        if tier not in _R2_ALLOWED_TIERS:
            _info(f"R2 sync requires Pro/Enterprise tier (current: {tier}). No-op.")
        else:
            _info("R2 sync not configured. Add team r2_bucket / r2_endpoint to config.toml and store creds via `kernora factbook sync`.")
        return 0

    try:
        from r2_sync import R2Sync  # type: ignore
    except ImportError as e:
        _err(f"factbook sync: r2_sync module unavailable: {e}")
        return 1

    syncer = R2Sync(store=store, db_path=DB_PATH)

    if ns.status:
        counts = syncer.queue_status()
        _header("R2 sync queue status")
        for status, count in sorted(counts.items()):
            print(f"  {status:<12} {count}")
        if not counts:
            _info("Queue is empty.")
        return 0

    _info(f"Draining r2_sync_queue → {store}...")
    result = syncer.drain_queue()
    drained = result.get("drained", 0)
    failed = result.get("failed", 0)
    skipped = result.get("skipped", 0)
    if failed:
        _warn(f"Sync complete: {drained} pushed, {failed} failed, {skipped} skipped. Check logs.")
        return 1
    _ok(f"Sync complete: {drained} pushed, {skipped} skipped.")
    return 0


def _cmd_factbook_export_db_only(args: list[str]) -> int:
    """List/export DB-only facts for a project.  `kernora factbook export-db-only <project> [--out <path.json>]`

    FOUNDER-DECIDED f1110 migration aid: nora_factbook_add's OLD private path
    (db.factbook_add_fact) wrote directly to the factlets/patterns table
    WITHOUT ever setting the `fact_id` TEXT column ("fNNN") — that column is
    only stamped by nora_context.reindex_factbook_from_yaml when a row comes
    FROM the canonical YAML (the f389 chokepoint path). So `fact_id IS NULL`
    is a reliable signal for "written by the old DB-only path, never made it
    into .nora/<project>-factbook.yaml" — reused here rather than a new
    heuristic (f388).

    Does NOT bulk-migrate anything (per FOUNDER-DECIDED f1110 constraint) —
    this is read-only: list to stdout, or --out to write a reviewable JSON
    export so backfill into the canonical YAML is a separate, deliberate step
    (e.g. re-adding each one via nora_factbook_add / nora_bridge.yaml_add_fact
    once a human has reviewed it).
    """
    import argparse as _ap
    import json as _json_edbo

    p = _ap.ArgumentParser(prog="kernora factbook export-db-only", add_help=False)
    p.add_argument("project", nargs="?")
    p.add_argument("--out", default=None, help="write JSON export to this path instead of printing a summary")
    p.add_argument("-h", "--help", action="store_true")
    ns, _ = p.parse_known_args(args)

    if ns.help or not ns.project:
        print(_cmd_factbook_export_db_only.__doc__ or "")
        return 0 if ns.help else 1

    try:
        import db as _db_edbo
    except ImportError as e:
        _err(f"factbook export-db-only: db module unavailable: {e}")
        return 1

    project = _db_edbo.canonical_project(ns.project) or ns.project
    conn = _db_edbo.get_conn()
    conn.row_factory = __import__("sqlite3").Row
    try:
        use_factlets = _db_edbo._factlets_table_exists(conn)
        tbl = "factlets" if use_factlets else "patterns"
        body_col = "body" if use_factlets else "pattern"
        rows = conn.execute(
            f"SELECT id, fact_type, {body_col} AS body, factbook_id, project, "
            f"created_at, source_type, created_by "
            f"FROM {tbl} WHERE project = ? AND fact_id IS NULL AND archived = 0 "
            f"ORDER BY id",
            (project,),
        ).fetchall()
    finally:
        conn.close()

    _header(f"DB-only facts for project={project!r} ({len(rows)} found)")
    if not rows:
        _info("None — every fact for this project already has a canonical fact_id (fNNN).")
        return 0

    records = [dict(r) for r in rows]
    if ns.out:
        with open(ns.out, "w") as f:
            _json_edbo.dump(records, f, indent=2, default=str)
        _ok(f"Exported {len(records)} DB-only facts to {ns.out}")
    else:
        for r in records:
            preview = (r["body"] or "")[:80].replace("\n", " ")
            print(f"  id={r['id']:<6} kp_id={r['factbook_id']!r:<24} [{r['fact_type']}] {preview}")
        _info("Pass --out <path.json> to export the full rows for a reviewable backfill.")
    return 0


# ── nora kp subcommand group (§9.1 surface 21 / §17.13-17.16) ────────────────
# Thin dispatchers — all SQL is in db.py; no duplicate SQL here (internal-rule).
# Subcommands: list, use, status, rename, init.

def cmd_kp() -> int:
    """Factbook knowledge-pack (kp) management.

    Usage:
      nora kp list                       — list all kp_factbooks in local DB
      nora kp use <kp_id>                — set active kp for cwd (.nora/kp-context)
      nora kp status                     — show active kp for cwd
      nora kp rename <old_id> <new_id>   — rename a kp_id
      nora kp init [--name <name>]       — create a new factbook kp in local DB

    Examples:
      nora kp list
      nora kp use my-project
      nora kp status
      nora kp init --name "My Project Factbook"

    Per §9.1 surface 21 / §17.13-17.16 of FACTBOOK-LAYERING-DESIGN-DOC-MAY-21-2026.md.
    """
    argv = sys.argv[2:]
    if not argv or argv[0] in ("-h", "--help"):
        print(cmd_kp.__doc__)
        return 0

    sub = argv[0]

    if sub == "list":
        return _cmd_kp_list(argv[1:])
    elif sub == "use":
        return _cmd_kp_use(argv[1:])
    elif sub == "status":
        return _cmd_kp_status(argv[1:])
    elif sub == "rename":
        return _cmd_kp_rename(argv[1:])
    elif sub == "init":
        return _cmd_kp_init(argv[1:])
    else:
        _err(f"kp: unknown subcommand {sub!r}. Run 'nora kp --help' for usage.")
        return 1


def _cmd_kp_list(args: list[str]) -> int:
    """List all kp_factbooks in local DB.
    §17.2 P-02: parameterized queries only.
    """
    import db as _db
    try:
        conn = _db.get_conn()
        try:
            # Schema-drift: scope→layer_type (Migration 1) AND optional
            # factbook_layer_kp_type — resolve both so kp list works on any DB.
            _scope_sel = _db.kp_scope_select(conn)
            try:
                rows = conn.execute(
                    f"SELECT kp_id, title, {_scope_sel}, factbook_layer_kp_type, updated_at "
                    "FROM kp_factbooks WHERE archived = 0 "
                    "ORDER BY updated_at DESC"
                ).fetchall()
            except Exception:
                # factbook_layer_kp_type may not exist yet (pre-migration DB)
                rows = conn.execute(
                    f"SELECT kp_id, title, {_scope_sel}, NULL AS factbook_layer_kp_type, updated_at "
                    "FROM kp_factbooks WHERE archived = 0 "
                    "ORDER BY updated_at DESC"
                ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        _err(f"kp list: {e}")
        return 1

    if not rows:
        print("  (no factbooks found — run 'nora kp init' to create one)")
        return 0

    print(f"{'ID':<40}  {'Title':<30}  {'Scope':<12}  {'Type':<10}  Updated")
    print("-" * 110)
    for r in rows:
        kp_id = r[0] or ""
        title = (r[1] or "")[:30]
        scope = (r[2] or "personal")[:12]
        kp_type = (r[3] or "factbook")[:10]
        updated = (r[4] or "")[:10]
        print(f"  {kp_id:<38}  {title:<30}  {scope:<12}  {kp_type:<10}  {updated}")
    return 0


def _cmd_kp_use(args: list[str]) -> int:
    """Set active kp for cwd by writing .nora/kp-context.
    §17.13 P-13: kp-context file is plain text with the kp_id.
    """
    if not args:
        _err("kp use: missing <kp_id>")
        return 1
    kp_id = args[0]

    import db as _db
    # Validate kp_id exists
    try:
        conn = _db.get_conn()
        try:
            row = conn.execute(
                "SELECT kp_id FROM kp_factbooks WHERE kp_id = ? AND archived = 0",
                (kp_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        _err(f"kp use: DB error: {e}")
        return 1

    if row is None:
        _err(f"kp use: kp_id {kp_id!r} not found. Run 'nora kp list' to see available IDs.")
        return 1

    nora_dir = Path.cwd() / ".nora"
    nora_dir.mkdir(parents=True, exist_ok=True)
    ctx_file = nora_dir / "kp-context"
    ctx_file.write_text(kp_id + "\n", encoding="utf-8")
    _ok(f"Active kp set to {kp_id!r} (wrote .nora/kp-context)")
    return 0


def _cmd_kp_status(args: list[str]) -> int:
    """Show active kp for cwd.
    §17.14 P-14: reads .nora/kp-context file.
    """
    ctx_file = Path.cwd() / ".nora" / "kp-context"
    if not ctx_file.exists():
        print("  No active kp set for this directory.")
        print("  Run 'nora kp use <kp_id>' to set one.")
        return 0
    kp_id = ctx_file.read_text(encoding="utf-8").strip()
    if not kp_id:
        print("  .nora/kp-context exists but is empty — run 'nora kp use <kp_id>'.")
        return 0

    import db as _db
    try:
        conn = _db.get_conn()
        try:
            # Schema-drift: scope→layer_type (Migration 1).
            _scope_sel = _db.kp_scope_select(conn)
            row = conn.execute(
                f"SELECT kp_id, title, {_scope_sel}, updated_at "
                "FROM kp_factbooks WHERE kp_id = ? AND archived = 0",
                (kp_id,),
            ).fetchone()
            fact_count = conn.execute(
                "SELECT COUNT(*) FROM patterns WHERE factbook_id = ? AND archived = 0 "
                "AND superseded_by IS NULL",
                (kp_id,),
            ).fetchone()[0]
        finally:
            conn.close()
    except Exception as e:
        _err(f"kp status: DB error: {e}")
        return 1

    if row is None:
        print(f"  Active kp: {kp_id!r} (WARNING: not found in DB — may be stale)")
        return 0

    print(f"  Active kp: {row[0]}")
    print(f"  Title:     {row[1] or '(no title)'}")
    print(f"  Scope:     {row[2] or 'personal'}")
    print(f"  Factlets:  {fact_count} (active, non-superseded)")
    print(f"  Updated:   {(row[3] or '')[:19]}")
    return 0


def _cmd_kp_rename(args: list[str]) -> int:
    """Rename a factbook display_name (NOT kp_id — the PK is immutable per RFC-0002a §Identifier-Discipline).
    §17b.6: UPDATE kp_factbooks SET display_name = ? (not kp_id).
    §17.2 P-02: parameterized queries only.

    Usage: nora kp rename <kp_id> <new_display_name>
    After rename: kp_id is unchanged, display_name is updated. All external refs via kp_id still resolve.
    """
    if len(args) < 2:
        _err("kp rename: usage: nora kp rename <kp_id> <new_display_name>")
        return 1
    kp_id, new_display_name = args[0], args[1]

    import db as _db
    try:
        conn = _db.get_conn()
        try:
            row = conn.execute(
                "SELECT kp_id, display_name FROM kp_factbooks WHERE kp_id = ? AND archived = 0",
                (kp_id,),
            ).fetchone()
            if row is None:
                _err(f"kp rename: kp_id {kp_id!r} not found")
                return 1
            old_display = row[1] or kp_id
            conn.execute(
                "UPDATE kp_factbooks SET display_name = ? WHERE kp_id = ?",
                (new_display_name, kp_id),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        _err(f"kp rename: {e}")
        return 1

    _ok(f"Renamed display_name for kp {kp_id!r}: {old_display!r} → {new_display_name!r}")
    _info(f"  kp_id is unchanged: {kp_id!r}")
    return 0


def _cmd_kp_init(args: list[str]) -> int:
    """Create a new factbook kp in local DB.
    §17.16 P-16: INSERT into kp_factbooks.
    §17.2 P-02: parameterized queries only.
    """
    import db as _db
    # Parse --name
    name: str | None = None
    i = 0
    while i < len(args):
        if args[i] in ("--name", "-n") and i + 1 < len(args):
            i += 1
            name = args[i]
        elif args[i].startswith("--name="):
            name = args[i].split("=", 1)[1]
        i += 1

    if not name:
        name = Path.cwd().name  # default to cwd basename

    # Generate slug kp_id from name
    import re
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        slug = "my-factbook"
    kp_id = slug

    try:
        conn = _db.get_conn()
        try:
            existing = conn.execute(
                "SELECT kp_id FROM kp_factbooks WHERE kp_id = ?",
                (kp_id,),
            ).fetchone()
            if existing:
                _err(f"kp init: kp_id {kp_id!r} already exists. Use 'nora kp list' or choose a different --name.")
                return 1
            import time
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # §17b.7: include layer_type='Individual' + ownership_class='individual'.
            # Schema-drift: resolve scope/layer_type via the shared helper so this
            # also works on a pre-migration DB (the prior hard-coded `layer_type`
            # threw "no such column" there). `or "layer_type"` keeps current behavior.
            _scope_col = _db.kp_scope_column(conn) or "layer_type"
            conn.execute(
                f"INSERT INTO kp_factbooks "
                f"(kp_id, title, {_scope_col}, ownership_class, created_at, updated_at, archived) "
                "VALUES (?, ?, 'Individual', 'individual', ?, ?, 0)",
                (kp_id, name, now, now),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        _err(f"kp init: {e}")
        return 1

    _ok(f"Created factbook kp {kp_id!r} (title: {name!r}, layer=Individual, ownership=individual)")
    print(f"  Zero memberships — add yourself with 'nora kp grant {kp_id}' to activate read/write access.")
    print(f"  Run 'nora kp use {kp_id}' to set as active kp for this directory.")
    return 0


# ── CLI factbook export / install (§9.1 / §17.7 P-07 / §17.4 P-04) ──────────
# Thin CLI wrappers; business logic lives in nora_mcp._factbook_export/install.
# Pattern: instantiate the MCP server class and call the handler synchronously.

def cmd_factbook_export() -> int:
    """Export factlets from a factbook to a file.

    Usage:
      nora factbook export [--layer <layer>] [--format jsonl|yaml|csv]
                           [--kp-id <kp_id>] [--include-superseded]
                           [--out <path>]

    All exports include spec_status='DRAFT-NOT-RATIFIED' watermark (FQ-1).
    kp_type='pack' exports are denied with [F404-EXPORT-DENIED-PACK-READONLY].
    kp_type='factbook' exports include attribution header.

    Examples:
      nora factbook export --layer Individual --format yaml
      nora factbook export --kp-id my-project --format jsonl --out /tmp/export.jsonl

    Delegates to nora_mcp._factbook_export() (internal-rule — no duplicate export logic).
    """
    import asyncio
    argv = sys.argv[2:]  # strip "nora factbook"
    # Since sys.argv[1]="factbook" and sys.argv[2]="export", strip both
    argv = sys.argv[3:]

    layer = None
    fmt = "jsonl"
    kp_id = None
    include_superseded = False
    out_path = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--layer",) and i + 1 < len(argv):
            i += 1; layer = argv[i]
        elif arg.startswith("--layer="):
            layer = arg.split("=", 1)[1]
        elif arg in ("--format", "-f") and i + 1 < len(argv):
            i += 1; fmt = argv[i]
        elif arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
        elif arg in ("--kp-id",) and i + 1 < len(argv):
            i += 1; kp_id = argv[i]
        elif arg.startswith("--kp-id="):
            kp_id = arg.split("=", 1)[1]
        elif arg in ("--include-superseded",):
            include_superseded = True
        elif arg in ("--out", "-o") and i + 1 < len(argv):
            i += 1; out_path = argv[i]
        elif arg.startswith("--out="):
            out_path = arg.split("=", 1)[1]
        elif arg in ("-h", "--help"):
            print(cmd_factbook_export.__doc__)
            return 0
        i += 1

    try:
        from nora_mcp import MCPServer
        server = MCPServer.__new__(MCPServer)
        # Minimal init for handler
        import db as _db
        server._db_path = _db._db_path() if hasattr(_db, '_db_path') else None

        result = asyncio.run(server._factbook_export(
            layer=layer,
            kp_id_explicit=kp_id,
            fmt=fmt,
            include_superseded=include_superseded,
        ))
    except Exception as e:
        _err(f"factbook export: {e}")
        return 1

    if out_path:
        Path(out_path).write_text(result, encoding="utf-8")
        _ok(f"Exported to {out_path}")
    else:
        print(result)
    return 0


def cmd_factbook_install_cmd() -> int:
    """Install a factbook domain pack.

    Usage:
      nora factbook install <pack-slug> [--source local|git|registry]
                            [--registry-url <url>] [--auth-token <token>]
                            [--trust-cert] [--version <version>]

    Source options:
      local      — pack= is a local file path to a .factbook.json file
      git        — pack= is a git URL (https://... or git@...)
      registry   — pack= is a registry slug (requires --registry-url or NORA_REGISTRY_URL)

    Examples:
      nora factbook install /tmp/my-pack.factbook.json --source local
      nora factbook install kernora/python-best-practices --source registry

    Delegates to nora_mcp._factbook_install() (internal-rule).
    """
    import asyncio
    argv = sys.argv[3:]  # strip "nora factbook install"

    if not argv or argv[0] in ("-h", "--help"):
        print(cmd_factbook_install_cmd.__doc__)
        return 0

    pack = argv[0]
    source = "registry"
    registry_url = None
    auth_token = None
    trust_cert = False
    version = None

    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("--source",) and i + 1 < len(argv):
            i += 1; source = argv[i]
        elif arg.startswith("--source="):
            source = arg.split("=", 1)[1]
        elif arg in ("--registry-url",) and i + 1 < len(argv):
            i += 1; registry_url = argv[i]
        elif arg.startswith("--registry-url="):
            registry_url = arg.split("=", 1)[1]
        elif arg in ("--auth-token",) and i + 1 < len(argv):
            i += 1; auth_token = argv[i]
        elif arg.startswith("--auth-token="):
            auth_token = arg.split("=", 1)[1]
        elif arg in ("--trust-cert",):
            trust_cert = True
        elif arg in ("--version",) and i + 1 < len(argv):
            i += 1; version = argv[i]
        elif arg.startswith("--version="):
            version = arg.split("=", 1)[1]
        i += 1

    try:
        from nora_mcp import MCPServer
        server = MCPServer.__new__(MCPServer)
        import db as _db
        server._db_path = _db._db_path() if hasattr(_db, '_db_path') else None

        result = asyncio.run(server._factbook_install(
            pack=pack,
            source=source,
            registry_url=registry_url,
            auth_token=auth_token,
            trust_cert=trust_cert,
            version=version,
        ))
    except Exception as e:
        _err(f"factbook install: {e}")
        return 1

    print(result)
    return 0


def cmd_factbook_view() -> int:
    """Show a factlet's source citation, rendered per-persona.

    Usage:
      kernora factbook-view <fact_id|DB_int_id> [--persona <role>]

    Persona options: all | coder | pm | tpm | founder | lead | explorer
      (defaults to current persona from KERNORA_PERSONA env / config.toml)

    When --persona is provided, each factlet's source_citation is rendered
    via db.factlet_source_citation(fact_id, persona) and printed below the
    factlet statement. When absent, source_citation uses the current persona.

    Examples:
      kernora factbook-view 42
      kernora factbook-view 42 --persona coder
      kernora factbook-view 42 --persona pm

    Per §4.6 of FACTBOOK-SCHEMA-SOURCE-URI-DESIGN-MAY-14-2026.md.
    Delegates to factlet_source_citation() in db.py — single render impl (internal-rule).
    """
    from db import factlet_source_citation, get_conn
    from kernora_mode import current_persona

    argv = sys.argv[2:]  # strip "kernora factbook-view"

    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: kernora factbook-view <fact_id> [--persona all|coder|pm|tpm|founder|lead|explorer]"
        )
        return 0

    # Parse args
    fact_id_raw = None
    persona_arg = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--persona", "-p") and i + 1 < len(argv):
            i += 1
            persona_arg = argv[i]
        elif arg.startswith("--persona="):
            persona_arg = arg.split("=", 1)[1]
        elif not arg.startswith("--"):
            fact_id_raw = arg
        i += 1

    if fact_id_raw is None:
        _err("factbook-view: missing fact_id (integer DB id)")
        return 1

    try:
        fact_id = int(fact_id_raw)
    except ValueError:
        _err(f"factbook-view: fact_id must be an integer; got {fact_id_raw!r}")
        return 1

    # Resolve persona: use --persona arg, fall back to kernora_mode.current_persona()
    _VALID = ("all", "coder", "pm", "tpm", "founder", "lead", "explorer")
    if persona_arg is not None:
        if persona_arg not in _VALID:
            _err(f"factbook-view: unknown persona {persona_arg!r}; valid: {_VALID}")
            return 1
        persona = persona_arg
    else:
        persona = current_persona()

    # Fetch statement for context
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, COALESCE(pattern, '') as statement, source_uri "
            "FROM patterns WHERE id = ?",
            (fact_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        _err(f"factbook-view: fact_id {fact_id} not found in patterns table")
        return 1

    statement = row[1]
    source_uri = row[2]

    # Render citation via the chokepoint helper (internal-rule — no per-surface dispatch)
    citation = factlet_source_citation(fact_id, persona)

    print(f"Factlet #{fact_id}  [persona: {persona}]")
    print(f"  {statement[:120]}")
    if source_uri:
        print(f"  source_uri: {source_uri}")
    print(f"  source_citation: {citation}")
    return 0


def cmd_import_kp() -> int:
    """Import facts from a kp_factbook JSON file into the project's YAML factbook.

    Usage:
      kernora import-kp <path>               — import kp.json into default project factbook
      kernora import-kp <path> --project <root>  — specify target project root
      kernora import-kp <path> --conflict skip|rename|fail  (default: skip)
      kernora import-kp <path> --strict      — abort on first per-fact failure

    Performance note: imports of >100 facts may take tens of seconds;
    >1000 facts may take minutes. Interrupt-safe: re-run resolves to skip
    on already-imported facts. (§10.10)

    Delegates to yaml_import_kp bridge verb — single translation impl per
    internal-rule. Every write routes through _save_factbook_yaml_atomic per f389.
    """
    argv = sys.argv[2:]  # strip "kernora import-kp"

    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: kernora import-kp <kp.json path> "
            "[--project <root>] [--conflict skip|rename|fail] [--strict]"
        )
        return 0

    # Parse args manually (mirrors _cmd_memory_import pattern)
    kp_json_path_arg = None
    project_root_arg = None
    conflict_arg = "skip"
    strict_arg = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--project="):
            project_root_arg = arg.split("=", 1)[1]
        elif arg == "--project" and i + 1 < len(argv):
            i += 1
            project_root_arg = argv[i]
        elif arg.startswith("--conflict="):
            conflict_arg = arg.split("=", 1)[1]
        elif arg == "--conflict" and i + 1 < len(argv):
            i += 1
            conflict_arg = argv[i]
        elif arg == "--strict":
            strict_arg = True
        elif not arg.startswith("--"):
            kp_json_path_arg = arg
        i += 1

    if not kp_json_path_arg:
        _err("kp.json path is required. Usage: kernora import-kp <path>")
        return 2

    if conflict_arg not in ("skip", "rename", "fail"):
        _err(f"--conflict must be 'skip', 'rename', or 'fail'; got {conflict_arg!r}")
        return 2

    kp_json_path = str(Path(kp_json_path_arg).expanduser().resolve())
    if not Path(kp_json_path).exists():
        _err(f"kp.json path not found: {kp_json_path}")
        return 2

    target_root = project_root_arg or str(Path.cwd())

    # Locate bridge script
    repo_root = Path(__file__).resolve().parent
    bridge_script = repo_root / "nora-desktop" / "scripts" / "nora_bridge.py"
    if not bridge_script.exists():
        bridge_script = APP_DIR / "nora_bridge.py"
    if not bridge_script.exists():
        _err(f"nora_bridge.py not found — run: kernora install")
        return 1

    py = str(PYTHON) if PYTHON.exists() else sys.executable

    import json as _json
    params = _json.dumps({
        "kp_json_path": kp_json_path,
        "conflict": conflict_arg,
        "strict": strict_arg,
    }).encode()

    cmd = [py, str(bridge_script), "yaml_import_kp", target_root,
           f"--conflict={conflict_arg}"]
    if strict_arg:
        cmd.append("--strict")

    try:
        proc = subprocess.run(cmd, input=params, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        _err("import-kp timed out after 120s — import may be incomplete")
        return 1
    except Exception as e:
        _err(f"bridge subprocess failed: {e}")
        return 1

    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()

    if stderr:
        # Surface warnings (e.g. §10.10 large-batch warning) to operator
        for line in stderr.splitlines():
            if line.strip():
                print(f"{YELLOW}warn:{RESET} {line}")

    if not stdout:
        _err("bridge returned no output")
        return 1

    try:
        res = _json.loads(stdout)
    except _json.JSONDecodeError:
        _err(f"bridge output is not valid JSON: {stdout[:300]}")
        return 1

    n_imported = res.get("imported", 0)
    n_skipped = res.get("skipped", 0)
    n_renamed = res.get("renamed", 0)
    n_failed = res.get("failed", 0)
    errs = res.get("errors", [])

    print(
        f"{GREEN}✓{RESET} Imported {n_imported} facts. "
        f"Skipped {n_skipped}. Renamed {n_renamed}. Failed {n_failed}."
    )

    if errs:
        print(f"{DIM}Errors ({len(errs)}):{RESET}")
        for e_item in errs[:10]:
            fid = e_item.get("fact_id") or e_item.get("fact_index", "?")
            print(f"  {RED}✗{RESET} {fid}: {e_item.get('error', e_item)}")
        if len(errs) > 10:
            print(f"  {DIM}... and {len(errs) - 10} more{RESET}")

    return 0 if n_failed == 0 else 1


def cmd_nora_push() -> int:
    """git commit + push .nora/ with PII pre-flight scan (#127).

    Usage: kernora nora-push [--message MSG]
    """
    import subprocess as _sp

    repo_root = _current_repo_root()
    if not repo_root:
        _err("Not inside a git repository.")
        return 1

    nora_dir = Path(repo_root) / ".nora"
    if not nora_dir.exists():
        _err(".nora/ not found. Run kernora team-init + kernora migrate-to-git-native first.")
        return 1

    # PII scan all .nora/ files before any git operation.
    try:
        import kernora_pii as _kp
        findings = []
        for f in nora_dir.rglob("*.md"):
            for finding in _kp.scan_file(str(f)):
                if finding.severity in ("critical", "high"):
                    findings.append((str(f), finding))
        if findings:
            _err(f"PII guardrail blocked push — {len(findings)} critical/high finding(s):")
            for path, finding in findings:
                print(f"  {RED}[{finding.severity}]{RESET} {path} — {finding.rule_id}: {finding.reason}")
            print(f"\nFix before running kernora nora-push.")
            return 1
        _ok("PII scan: clean")
    except ImportError:
        _warn("kernora_pii not available — skipping PII scan (install kernora to enable)")

    # Write today's metrics JSONL before staging (team view + opt-in telemetry).
    try:
        _write_daily_metrics_jsonl(Path(repo_root))
        _ok("Metrics JSONL written to .nora/metrics/")
    except Exception as _me:
        _warn(f"Metrics JSONL skipped ({_me})")

    # Commit message.
    msg = None
    args = sys.argv[2:]
    for i, a in enumerate(args):
        if a in ("--message", "-m") and i + 1 < len(args):
            msg = args[i + 1]
    if not msg:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        msg = f"nora: sync factbook {ts}"

    result = _sp.run(
        ["git", "add", ".nora/"],
        cwd=repo_root, capture_output=True, text=True
    )
    if result.returncode != 0:
        _err(f"git add failed: {result.stderr.strip()}")
        return 1

    # Check if there's anything to commit.
    status = _sp.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_root
    )
    if status.returncode == 0:
        _info("Nothing to commit in .nora/ — already up to date")
    else:
        result = _sp.run(
            ["git", "commit", "-m", msg],
            cwd=repo_root, capture_output=True, text=True
        )
        if result.returncode != 0:
            _err(f"git commit failed: {result.stderr.strip()}")
            return 1
        _ok(f"Committed: {msg}")

    result = _sp.run(
        ["git", "push"],
        cwd=repo_root, capture_output=True, text=True
    )
    if result.returncode != 0:
        _err(f"git push failed: {result.stderr.strip()}")
        print(result.stderr)
        return 1

    _ok("Pushed .nora/ to origin")
    return 0


def cmd_team_report() -> int:
    """Build a static team report from .nora/factbook.yaml + JSONL aggregates (#L-016).

    Output: ``.nora/team-report.md`` — commit-able, viewable on GitHub.
    Sections: snapshot · top-cited facts (30d) · per-author contributions
    (git blame on the factbook) · facts/week sparkline (last 12 ISO-weeks).

    No daemon, no LLM, no network. Runs in <2 s on a 100-fact factbook.

    Usage:
      kernora team-report                       # uses ``.nora/`` in cwd
      kernora team-report --nora-dir <path>     # explicit nora dir
      kernora team-report --since-days 14       # window for engagement (default 30)
    """
    import yaml as _yaml
    from collections import Counter as _Counter
    from datetime import datetime as _dt, timezone as _tz

    nora_dir_arg: str | None = None
    since_days = 30
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--nora-dir" and i + 1 < len(args):
            nora_dir_arg = args[i + 1]; i += 2
        elif a == "--since-days" and i + 1 < len(args):
            try:
                since_days = max(1, int(args[i + 1]))
            except ValueError:
                _err(f"--since-days must be int, got {args[i + 1]!r}")
                return 1
            i += 2
        else:
            i += 1

    nora_dir = Path(nora_dir_arg) if nora_dir_arg else (Path.cwd() / ".nora")
    if not nora_dir.exists():
        _err(f"{nora_dir} not found. Run kernora team-init from your repo root first.")
        return 1

    # Find factbook. Convention is '<project>-factbook.yaml' (e.g. JWM's
    # jwm-factbook.yaml) — 'kernora-factbook.yaml' only exists in THIS repo.
    # Mirrors the dir-name-preferred / shortest-non-tombstone precedence
    # nora_bridge._load_factbook_yaml uses (internal-rule — one resolution
    # convention, not a per-caller guess), falling back to factbook.yaml
    # per the BATCH-006 spec.
    project_root = nora_dir.parent
    fb_path = nora_dir / f"{project_root.name}-factbook.yaml"
    if not fb_path.exists():
        candidates = sorted(
            [p for p in nora_dir.glob("*-factbook.yaml") if "lite-mode" not in p.name],
            key=lambda p: len(p.name),
        )
        fb_path = None
        for cand in candidates:
            try:
                _doc = _yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if _doc.get("content"):
                fb_path = cand
                break
        if fb_path is None:
            fb_path = candidates[0] if candidates else (nora_dir / "factbook.yaml")
    if not fb_path.exists():
        _err(f"No factbook found at {nora_dir}/<project>-factbook.yaml or factbook.yaml")
        return 1

    try:
        fb = _yaml.safe_load(fb_path.read_text(encoding="utf-8")) or {}
    except _yaml.YAMLError as e:
        _err(f"Could not parse {fb_path}: {e}")
        return 1
    facts = fb.get("content") or []
    pending = fb.get("pending") or []

    # Aggregate from engagement JSONL.
    try:
        import nora_jsonl as _nj
        events = _nj.read_engagement(since_days=since_days)
    except Exception:
        events = []

    cited_counter: _Counter[str] = _Counter()
    for e in events:
        for fid in (e.get("fact_ids") or []):
            cited_counter[str(fid)] += 1

    # Per-author count via git blame on factbook (skip when not in a git repo
    # or git unavailable — cmd_team_report still produces a report).
    author_counts: dict[str, int] = {}
    try:
        import subprocess as _sp
        # Confirm we're in a git work tree before blaming, so the failure mode
        # is "no Contributions section" not "command died with traceback".
        in_git = _sp.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(fb_path.parent), capture_output=True, text=True,
        )
        if in_git.returncode == 0 and in_git.stdout.strip() == "true":
            blame = _sp.run(
                ["git", "blame", "--line-porcelain", str(fb_path)],
                capture_output=True, text=True,
            )
            if blame.returncode == 0:
                for line in blame.stdout.splitlines():
                    if line.startswith("author "):
                        a = line[7:].strip()
                        if a and a != "Not Committed Yet":
                            author_counts[a] = author_counts.get(a, 0) + 1
    except Exception:
        pass

    # Per-week sparkline — facts added per ISO-week, last 12 weeks.
    weekly: _Counter[str] = _Counter()
    for f in facts:
        ts = ((f or {}).get("freshness") or {}).get("extracted_at") or ""
        if not ts:
            continue
        try:
            dt = _dt.fromisoformat(ts.replace("Z", "+00:00"))
            wk = dt.strftime("%G-W%V")
            weekly[wk] += 1
        except Exception:
            continue

    verified = sum(
        1 for f in facts
        if (f or {}).get("review_status") == "verified" or (f or {}).get("status") == "approved"
    )

    # Render report.
    out = nora_dir / "team-report.md"
    now = _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        "# Team Factbook Report",
        f"_Generated {now} · `kernora team-report` · window: last {since_days} days_",
        "",
        "## Snapshot",
        f"- **Total facts**: {len(facts)}",
        f"- **Pending review**: {len(pending)}",
        f"- **Verified**: {verified}",
        f"- **Engagements (last {since_days}d)**: {len(events)}",
        "",
        f"## Top-cited facts (last {since_days}d)",
    ]
    if cited_counter:
        for fid, n in cited_counter.most_common(10):
            match = next((f for f in facts if str((f or {}).get("id")) == fid), None)
            name = (match or {}).get("name") or "(retired)"
            lines.append(f"- `{fid}` · {n}x · {name}")
    else:
        lines.append("_No engagements in the window._")

    if author_counts:
        lines += ["", "## Contributions (lines in factbook.yaml)"]
        for a, n in sorted(author_counts.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"- {a}: {n} lines")

    if weekly:
        lines += ["", f"## Facts per ISO-week (last 12)"]
        for wk in sorted(weekly.keys())[-12:]:
            n = weekly[wk]
            bar = "#" * min(n, 40)
            lines.append(f"  {wk}: {bar} {n}")

    lines.append("")  # trailing newline so editors don't complain
    out.write_text("\n".join(lines), encoding="utf-8")
    _ok(f"Written {out}")
    print(f"  Commit + push to update GitHub Pages: "
          f"{CYAN}git add {out} && git commit -m 'team-report' && git push{RESET}")
    return 0


def cmd_acceptance_scan() -> int:
    """Signal A scanner: walk recent git commits for f### fact_id citations.

    Thin wrapper around git_acceptance_scan.py that passes through any extra
    CLI arguments after 'acceptance-scan'.

    Usage:
        kernora acceptance-scan [--since DAYS] [--project NAME] [--db PATH]
                                [--dry-run]
    """
    import importlib.util
    import os

    scanner_path = Path(os.path.dirname(os.path.abspath(__file__))) / "git_acceptance_scan.py"
    if not scanner_path.exists():
        _err(f"git_acceptance_scan.py not found at {scanner_path}")
        return 1

    spec = importlib.util.spec_from_file_location("git_acceptance_scan", scanner_path)
    if spec is None or spec.loader is None:
        _err("Could not load git_acceptance_scan.py")
        return 1

    mod = importlib.util.module_from_spec(spec)
    # Inject sys.argv passthrough: replace argv[1] (the 'acceptance-scan' verb)
    # with the remaining args so the scanner's argparse sees them correctly.
    old_argv = sys.argv[:]
    sys.argv = [str(scanner_path)] + sys.argv[2:]
    try:
        spec.loader.exec_module(mod)
        return mod.main()
    finally:
        sys.argv = old_argv


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        cmd_help()
        return 0

    cmd = sys.argv[1].lower().strip("-")
    if cmd in COMMANDS:
        try:
            result = COMMANDS[cmd]()
            return result if isinstance(result, int) else 0
        except ImportError as _ie:
            # Free/open-core ships the full CLI entrypoint but omits ~47
            # premium modules. Premium subcommands must degrade clearly —
            # never traceback on a missing Pro module.
            missing = getattr(_ie, "name", None) or str(_ie)
            _err(f"'{cmd}' is not available on Free tier (missing module: {missing}).")
            print(f"  Free includes the core CLI (help / generate / tour / network-check / …).")
            print(f"  Upgrade: https://kernora.ai/pricing")
            return 1
    else:
        _err(f"Unknown command: {sys.argv[1]}")
        print(f"  Run {CYAN}nora help{RESET} for available commands.")
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
