#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
"""
Standalone CLI for Kernora. Works without VS Code / Kiro app.

Usage:
  kernora init       — first-time setup (venv, deps, db, steering files)
  kernora start      — start the dashboard daemon
  kernora stop       — stop the dashboard daemon
  kernora restart    — stop + start
  kernora status     — check health (dashboard, db, steering, hooks)
  kernora generate   — regenerate steering files now
  kernora help       — show this help

Install:
  After running `kernora init`, symlink is created at ~/.local/bin/kernora
  Or run directly: python3 ~/.kernora/app/kernora_cli.py <command>
"""
import db
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

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


# ── Init ──────────────────────────────────────────────────────────────────────

def cmd_init():
    """First-time setup: venv, deps, db, config, steering, CLI symlink."""
    _header("Kernora — Initializing")

    # 1. Check Python
    py = shutil.which("python3")
    if not py:
        _err("Python 3 not found. Install from https://python.org")
        sys.exit(1)
    _ok(f"Python 3 found: {py}")

    # 2. Create directories
    for d in [APP_DIR, LOG_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    _ok("Directories created")

    # 3. Sync bundled files (if running from extension bundled dir)
    script_dir = Path(__file__).resolve().parent
    bundled_count = 0
    for f in script_dir.glob("*.py"):
        if f.name != "__pycache__":
            target = APP_DIR / f.name
            if str(script_dir) != str(APP_DIR):
                shutil.copy2(f, target)
                bundled_count += 1
    if bundled_count:
        _ok(f"Synced {bundled_count} Python files to {APP_DIR}")

    # 4. Create venv
    if not PYTHON.exists():
        _info("Creating Python virtual environment...")
        subprocess.run([py, "-m", "venv", str(VENV_DIR)], check=True, capture_output=True)
        _ok("Virtual environment created")
    else:
        _ok("Virtual environment exists")

    # 5. Install deps
    _info("Installing dependencies (flask, mcp)...")
    subprocess.run(
        [str(PIP), "install", "flask", "mcp", "--quiet"],
        check=True, capture_output=True, timeout=120
    )
    _ok("Dependencies installed")

    # 6. Default config
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text("""[mode]
type = "byok"

[model]
provider = "anthropic"

[analysis]
run_every_minutes = 60

[dashboard]
port = 2742
auto_open = true

[privacy]
verified = true
""")
        _ok("Default config written")
    else:
        _ok("Config exists")

    # 7. Init DB
    db_init = APP_DIR / "db.py"
    if db_init.exists():
        subprocess.run([str(PYTHON), str(db_init)], capture_output=True, timeout=10)
        _ok("Database initialized")

    # 8. Generate steering files
    cmd_generate(quiet=True)

    # 9. Create CLI symlink
    _install_symlink()

    _header("Ready")
    print(f"  Dashboard: {CYAN}kernora start{RESET}")
    print(f"  Status:    {CYAN}kernora status{RESET}")
    print(f"  Help:      {CYAN}kernora help{RESET}")
    print()


def _install_symlink():
    """Create ~/.local/bin/kernora symlink."""
    cli_script = APP_DIR / "kernora_cli.py"
    if not cli_script.exists():
        # If we're running from source, copy self
        shutil.copy2(__file__, cli_script)
        cli_script.chmod(0o755)

    BIN_DIR.mkdir(parents=True, exist_ok=True)

    # Create a wrapper script (not symlink — symlinks break if venv moves)
    wrapper = SYMLINK_PATH
    wrapper.write_text(f"""#!/bin/sh
exec "{PYTHON}" "{cli_script}" "$@"
""")
    wrapper.chmod(0o755)
    _ok(f"CLI installed at {SYMLINK_PATH}")

    # Check if ~/.local/bin is in PATH
    path_dirs = os.environ.get("PATH", "").split(":")
    if str(BIN_DIR) not in path_dirs:
        _warn(f"Add to your shell profile: export PATH=\"$HOME/.local/bin:$PATH\"")


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
    cmd_stop()
    time.sleep(0.5)
    cmd_start()


# ── Status ────────────────────────────────────────────────────────────────────

def cmd_status():
    """Show health status of all Kernora components."""
    _header("Kernora Status")

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
    if pid:
        _ok(f"Dashboard: running (PID {pid}) → http://localhost:2742")
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
    """Regenerate steering files from current DB state."""
    sw = APP_DIR / "steering_writer.py"
    if not sw.exists():
        if not quiet:
            _err("steering_writer.py not found — run: kernora init")
        return

    python_cmd = str(PYTHON) if PYTHON.exists() else "python3"
    try:
        result = subprocess.run(
            [python_cmd, str(sw)],
            capture_output=True, text=True, timeout=10
        )
        steering_files = list(STEERING_DIR.glob("kernora-*.md")) if STEERING_DIR.exists() else []
        if steering_files:
            _ok(f"Steering files generated ({len(steering_files)} files)")
        elif not quiet:
            _warn("No steering files written (no data yet — that's OK)")
    except Exception as e:
        if not quiet:
            _err(f"Steering generation failed: {e}")


# ── Help ──────────────────────────────────────────────────────────────────────

def cmd_help():
    """Show help."""
    print(f"""
{BOLD}kernora{RESET} — AI Work Intelligence CLI

{BOLD}Commands:{RESET}
  {CYAN}kernora init{RESET}       First-time setup (venv, deps, db, steering)
  {CYAN}kernora start{RESET}      Start the dashboard daemon
  {CYAN}kernora stop{RESET}       Stop the dashboard daemon
  {CYAN}kernora restart{RESET}    Restart the dashboard
  {CYAN}kernora status{RESET}     Check health of all components
  {CYAN}kernora generate{RESET}   Regenerate steering files now
  {CYAN}kernora help{RESET}       Show this help

{BOLD}Inside a Kiro/Claude session:{RESET}
  {CYAN}/nora help{RESET}         Show all Nora commands
  {CYAN}/nora pe-review{RESET}    Code quality audit (4-tier)
  {CYAN}/nora coe [bug]{RESET}    Root cause investigation (5 whys)
  {CYAN}/nora retro{RESET}        Engineering retrospective
  {CYAN}/nora sofac{RESET}        Factory status check
  {CYAN}/nora inventory{RESET}    Feature surface area audit

{BOLD}Paths:{RESET}
  Data:      ~/.kernora/echo.db
  Config:    ~/.kernora/config.toml
  Logs:      ~/.kernora/logs/
  Steering:  ~/.kiro/steering/kernora-*.md
  Dashboard: http://localhost:2742
  Docs:      https://kernora.ai
""")


# ── Main ──────────────────────────────────────────────────────────────────────

COMMANDS = {
    "init": cmd_init,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "generate": cmd_generate,
    "help": cmd_help,
}

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        cmd_help()
        return

    cmd = sys.argv[1].lower().strip("-")
    if cmd in COMMANDS:
        COMMANDS[cmd]()
    else:
        _err(f"Unknown command: {sys.argv[1]}")
        print(f"  Run {CYAN}kernora help{RESET} for available commands.")
        sys.exit(1)


if __name__ == "__main__":
    main()
