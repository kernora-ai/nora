#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""
Background daemon.
Run:        python daemon.py
Background: nohup python daemon.py > ~/.kernora/logs/daemon.log 2>&1 &
LaunchAgent installs this automatically on macOS.

Threads:
  socket_server   — receives session payloads from IDE extensions
  analysis_loop   — analyzes new sessions hourly via LiteLLM (BYOK)
  dreamer_loop    — Dreamer nightly consolidation (2 AM, cross-session synthesis)
  pulse_loop      — PULSE codebase nervous system (commits, hotspots, co-changes, docs)
"""
import fcntl
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

from db import init_db, store_session, get_unanalyzed, mark_analyzed

# Free/open-core public db.py may omit resolve_db_path (private helper).
# Provide a compatible fallback so the full daemon still boots on Free.
try:
    from db import resolve_db_path
except ImportError:
    def resolve_db_path():  # type: ignore[misc]
        env = os.environ.get("KERNORA_DB_PATH") or os.environ.get("KERNORA_DB")
        if env:
            return Path(env)
        home = os.environ.get("KERNORA_HOME")
        return Path(home) / "echo.db" if home else (Path.home() / ".kernora" / "echo.db")

# A-ISO fix (2026-07-18): honor KERNORA_HOME so an isolated daemon instance
# (KERNORA_HOME=/tmp/sandbox python3 daemon.py) scopes its socket, spool,
# singleton lock, and echo.db under the sandbox instead of the operator's
# real ~/.kernora — mirrors the resolver in db.py / dashboard.py's _KERNORA_HOME.
# Unset KERNORA_HOME still resolves to ~/.kernora (no behavior change for a
# normal install).
HOME  = Path(os.environ.get("KERNORA_HOME") or (Path.home() / ".kernora"))
SOCK  = HOME / "daemon.sock"
SPOOL = HOME / "spool"
MAX_BODY = 1_000_000

# PULSE state is managed in pulse.py (DB-persisted, no in-memory state needed here)

# ── Singleton lock (§10.4 / D4) ───────────────────────────────────────────────
# Advisory flock on daemon.lock, held for the full process lifetime.
# Acquired in main() BEFORE replay_spool() (the real write hazard).
# The fd is kept as a module-level variable — a `with` block would release it.
_SINGLETON_LOCK_FD: int | None = None
_SINGLETON_LOCK_PATH = HOME / "daemon.lock"


def _acquire_singleton_lock(lock_path: Path | None = None) -> bool:
    """Acquire LOCK_EX|LOCK_NB on <lock_path> (default: HOME/daemon.lock).

    Returns True on success (this process owns the lock).
    Returns False if another process already holds it.
    Stores the open fd in _SINGLETON_LOCK_FD so it is NEVER closed.
    Accepts an explicit lock_path so tests can use an isolated tempdir path.
    """
    global _SINGLETON_LOCK_FD
    path = lock_path if lock_path is not None else _SINGLETON_LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _SINGLETON_LOCK_FD = fd  # hold forever — do NOT close
        return True
    except OSError:
        os.close(fd)
        return False


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


_SPOOL_SIZE_LIMIT = 10 * 1024 * 1024  # 10 MB — oversized turns arrays OOM the process


def replay_spool():
    """Replay spooled session JSON files into echo.db.

    Size guard (internal-rule): spool files above _SPOOL_SIZE_LIMIT contain
    transcript turns arrays that are too large to parse safely (observed:
    90-96 MB files from long sessions).  For oversized files we strip the
    turns before ingesting so session metadata still lands in the DB.
    """
    if not SPOOL.exists():
        return
    for f in sorted(SPOOL.glob("*.json")):
        try:
            file_size = f.stat().st_size
            if file_size > _SPOOL_SIZE_LIMIT:
                # [FALLBACK] log loudly per internal-rule — do NOT silently drop
                log(
                    f"[FALLBACK] spool file {f.name} is {file_size // (1024*1024)} MB "
                    f"(>{_SPOOL_SIZE_LIMIT // (1024*1024)} MB limit) — "
                    f"stripping turns array, storing metadata only"
                )
                try:
                    raw = f.read_bytes()
                    payload = json.loads(raw)
                    del raw  # release large buffer immediately
                    payload["turns"] = []
                    payload["_spool_turns_stripped"] = True
                    payload["_spool_original_size"] = file_size
                except Exception as parse_err:
                    log(f"[FALLBACK] spool parse error {f.name}: {parse_err} — skipping")
                    continue
            else:
                payload = json.loads(f.read_text())
            store_session(payload)
            try:
                f.unlink()
            except FileNotFoundError:
                pass  # already deleted — harmless
            log(f"replayed: {f.name}")
        except Exception as e:
            log(f"spool error {f.name}: {e}")


def _is_session_in_scope(payload: dict) -> bool:
    """Project-scope gate (Layer 1, authoritative at daemon level).

    Uses the 'project' field from the session payload as the cwd signal.
    Returns True if session should be stored + analyzed, False if it should
    be silently discarded. On any error, defaults to True (allow through).
    """
    try:
        from project_scope import load_config, is_project_in_scope, is_paused

        # A-ISO fix (2026-07-18): this used to compute cfg_path from HOME
        # then immediately overwrite it with a hardcoded Path.home() re-
        # derivation (dead first assignment, and the second ignored
        # KERNORA_HOME). HOME already resolves KERNORA_HOME correctly.
        cfg_path = str(HOME / "config.toml")

        config = load_config(cfg_path)

        if is_paused(config):
            return False

        session_cwd = payload.get("project", "")
        return is_project_in_scope(session_cwd, config.get("allowed_projects", []))
    except Exception:
        return True  # fail open — never silently drop sessions due to import error


def handle_connection(data: bytes):
    try:
        payload = json.loads(data.decode().strip())
        sid = payload.get("session_id", "?")[:8]

        if not _is_session_in_scope(payload):
            log(f"session {sid} out of scope (cwd={payload.get('project', '?')!r}), discarded")
            return

        store_session(payload)
        tok = payload.get("tokens_in", 0) + payload.get("tokens_out", 0)
        log(f"stored session {sid} ({tok} tokens)")
    except Exception as e:
        log(f"session parse error: {e}")


def socket_server():
    SOCK.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
        srv.bind(str(SOCK))
        SOCK.chmod(0o600)
        srv.listen(5)
        log(f"socket listening at {SOCK}")
        while True:
            conn, _ = srv.accept()
            with conn:
                data = b""
                while chunk := conn.recv(4096):
                    data += chunk
                    if len(data) > MAX_BODY:
                        log(f"request body exceeded {MAX_BODY} bytes, rejecting")
                        try:
                            conn.sendall(b"HTTP/1.1 413 Payload Too Large\r\nContent-Length: 0\r\n\r\n")
                        except Exception:
                            pass
                        data = b""
                        break
                if data:
                    handle_connection(data)


# ── ANALYSIS LOOP ──────────────────────────────────────────────────────────────

def _get_analyzer():
    """Return the analysis function based on config.
    If coordinator_mode = true in config.toml, use COORDINATOR_MODE multi-agent pipeline."""
    try:
        # A-ISO fix (2026-07-18): cfg_path was computed but never read (dead
        # code) and cfg_file below ignored KERNORA_HOME via a hardcoded
        # Path.home() re-derivation. HOME already resolves KERNORA_HOME.
        cfg_file = HOME / "config.toml"
        coordinator_enabled = False
        if cfg_file.exists():
            try:
                import sys as _sys
                if _sys.version_info >= (3, 11):
                    import tomllib as _tomllib
                else:
                    try:
                        import tomllib as _tomllib
                    except ImportError:
                        import tomli as _tomllib  # type: ignore
                with open(cfg_file, "rb") as f:
                    cfg = _tomllib.load(f)
                coordinator_enabled = cfg.get("coordinator_mode", {}).get("enabled", False)
            except Exception:
                pass
    except Exception:
        coordinator_enabled = False

    if coordinator_enabled:
        try:
            from coordinator import coordinate
            log("using COORDINATOR_MODE (multi-agent parallel analysis)")
            return coordinate
        except ImportError:
            log("coordinator not available on this install — falling back to analyzer")
    from analyzer import analyze
    return analyze


def analysis_loop():
    """Analyze unanalyzed sessions using user's own LiteLLM credentials.
    First run after 30s (so dashboard populates quickly), then hourly.
    Supports COORDINATOR_MODE for parallel multi-agent analysis."""
    try:
        from notifier import notify
    except ImportError:
        # Free/open-core may omit notifier.py — keep analyzing; skip desktop notify.
        def notify(_title, _body=""):  # type: ignore[misc]
            return None

    log("analysis loop started (LiteLLM BYOK mode)")
    first_run = True
    analyze_fn = None  # lazy-loaded per loop so config changes take effect

    while True:
        time.sleep(30 if first_run else 3600)
        first_run = False

        try:
            sessions = get_unanalyzed(limit=20)
            if not sessions:
                continue

            log(f"analyzing {len(sessions)} session(s)...")

            # Reload analyzer each cycle so config changes (coordinator_mode) take effect
            analyze_fn = _get_analyzer()

            for session in sessions:
                try:
                    result = analyze_fn(session)
                    # Guard: if result has no meaningful content (API timeout, empty response),
                    # leave analyzed=0 so the session re-queues on next poll.
                    # Mirrors the identical guard in nora_analyze.py:156.
                    if not result.get("token_cost") and not result.get("summary") and not result.get("patterns"):
                        log(f"[Dreamer] analysis_loop: empty result for {session['id'][:8]} — leaving unanalyzed for retry")
                        continue
                    mark_analyzed(session["id"], result)
                    model = result.get("model_used", "?")
                    cost  = result.get("token_cost", 0)
                    bugs  = len(result.get("bugs", []))
                    pats  = len(result.get("reusable_patterns", []))
                    decs  = len(result.get("architectural_decisions", []))
                    mode  = "⚡ coordinator" if result.get("coordinator_mode") else "single-agent"

                    if result.get("low_signal"):
                        log(f"signal-gate skip {session['id'][:8]}: {result.get('skip_reason', '?')}")
                    elif pats == 0 and bugs == 0 and decs == 0:
                        log(f"zero-intel {session['id'][:8]}: LLM found nothing ({cost} tokens) [{model}]")
                    else:
                        log(f"analyzed {session['id'][:8]}: pat={pats} bug={bugs} dec={decs}, "
                            f"{cost} tokens [{model}] [{mode}]")

                    # µDreamer: incremental KP update after each session
                    try:
                        from micro_dreamer import run_micro_dreamer
                        project = session.get("project", "")
                        md_result = run_micro_dreamer(session["id"], project, result)
                        kps_updated = len(md_result.get("kps_updated", []))
                        if kps_updated:
                            log(f"µDreamer: {kps_updated} KP(s) updated for {session['id'][:8]}")
                    except Exception as md_e:
                        log(f"µDreamer skipped for {session['id'][:8]}: {md_e}")

                    notify(
                        "Nora",
                        result.get("summary") or "Session analyzed. Dashboard updated."
                    )
                except Exception as e:
                    log(f"analysis failed for {session['id'][:8]}: {e}")

        except Exception as e:
            log(f"analysis loop error: {e}")


# ── DREAMER LOOP ───────────────────────────────────────────────────────────────

def dreamer_loop():
    """
    Dreamer: Nightly intelligence consolidation.
    Polls every 30 minutes; runs when should_run_dreamer() 23-hour gap clears.
    Synthesizes cross-session patterns, promotes high-confidence knowledge,
    prunes stale entries, regenerates CLAUDE.md steering context.
    Inspired by Anthropic's internal DREAM system — Nora ships the open-source
    equivalent.
    """
    log("Dreamer loop started (nightly consolidation)")

    while True:
        # Poll every 30 minutes. The 2am hard-window is removed — should_run_dreamer()
        # already enforces a 23-hour minimum gap, which is the correct invariant.
        # Previously: hour==2 && minute<30 caused Dreamer to be permanently skipped
        # if the daemon started after 2:30am (crash recovery, laptop wake from sleep).
        time.sleep(1800)
        try:
            from dreamer import run_dreamer, should_run_dreamer, load_state
            # Ask explicitly whether it's a skip BEFORE calling run_dreamer so
            # we can distinguish skip-vs-crash in the log. Apr 10 2026:
            # conflating the two hid a dreamer.py schema-drift crash for weeks.
            state = load_state()
            will_run = should_run_dreamer(state)
            if not will_run:
                last = state.get("last_run")
                log(f"Dreamer: skipped — already ran (last_run={last})")
                continue
            log("Dreamer: starting nightly consolidation...")
            digest = run_dreamer()
            if digest:
                log(f"Dreamer: complete — {digest.get('pattern_report', {}).get('total', 0)} patterns consolidated")
                try:
                    from notifier import notify
                    notify("Nora · Dreamer", "Nightly intelligence consolidation complete. Steering context refreshed.")
                except Exception:
                    pass
                # Arc-ledger TTL sweep — purge closed ledgers older than 14 days.
                # Runs after a real DREAM pass (not on 30-min skip polls).
                # Defensive: never crash the dreamer_loop.
                try:
                    import sqlite3 as _arc_sqlite
                    # A-ISO fix (2026-07-18): was a hand-rolled fallback chain
                    # that stopped at KERNORA_DB_PATH/KERNORA_DB and dropped to
                    # a hardcoded Path.home() — missing the KERNORA_HOME tier.
                    # resolve_db_path() (db.py, imported above) is the shared
                    # call-time resolver arc_ledger's own default already
                    # delegates to (DUP-fix 2026-06-01) — reuse it here too.
                    _arc_conn = _arc_sqlite.connect(str(resolve_db_path()))
                    try:
                        import arc_ledger as _al
                        _swept = _al.sweep_closed(_arc_conn, days=14)
                        if _swept > 0:
                            log(f"Dreamer: arc-ledger TTL sweep — deleted {_swept} closed ledger(s) older than 14 days")
                    except Exception as _arc_e:
                        log(f"Dreamer: arc-ledger sweep skipped — {_arc_e}")
                    finally:
                        _arc_conn.close()
                except Exception as _arc_outer:
                    log(f"Dreamer: arc-ledger sweep (outer) skipped — {_arc_outer}")
            else:
                # run_dreamer returned None AFTER should_run_dreamer said True.
                # That means it crashed inside and swallowed the exception.
                # Real error is in ~/.kernora/logs/dream.log
                log("Dreamer: FAILED — run_dreamer() returned None. Check ~/.kernora/logs/dream.log for traceback.")
        except Exception as e:
            log(f"Dreamer: error — {e}")


# ── PULSE LOOP (formerly KAIROS) ──────────────────────────────────────────────

def pulse_loop():
    """
    PULSE: Persistent Unified Lifecycle Signal Engine.
    Nora's peripheral nervous system — always sensing changes in watched repos.
    Detects new commits, hotspot files, co-change patterns, and doc updates.
    All signals persisted to SQLite (pulse_signals table) and fed to DREAM
    and context injection.
    Runs every 5 minutes.
    """
    log("PULSE loop started (codebase nervous system)")
    time.sleep(60)  # Let the daemon settle before first scan

    while True:
        try:
            import pulse
            summary = pulse.scan_repos()
            if summary.get("new_commits") or summary.get("hotspots") or summary.get("doc_changes"):
                log(f"PULSE: {summary.get('new_commits', 0)} commits, "
                    f"{summary.get('hotspots', 0)} hotspots, "
                    f"{summary.get('doc_changes', 0)} doc changes")

            # Also write to legacy kairos_signals.json for backward compat
            # (will be removed in a future version)
            try:
                signals = pulse.get_signals(limit=50, hours=168)
                legacy = []
                for s in signals[:50]:
                    legacy.append({
                        "type": s.get("signal_type", ""),
                        "repo": s.get("repo", ""),
                        "file": s.get("file_path", ""),
                        "message": s.get("detail", ""),
                        "timestamp": s.get("created_at", ""),
                    })
                (HOME / "kairos_signals.json").write_text(json.dumps(legacy, indent=2))
            except Exception:
                pass

        except Exception as e:
            log(f"PULSE: error — {e}")

        time.sleep(300)  # 5-minute polling interval


# ── MANUAL TOOLS ───────────────────────────────────────────────────────────────

def run_analysis_now():
    """Force immediate analysis — for testing. Call from CLI."""
    from analyzer import analyze
    from notifier import notify

    sessions = get_unanalyzed(limit=5)
    print(f"[nora] found {len(sessions)} unanalyzed sessions")

    for session in sessions:
        print(f"[nora] analyzing {session['id'][:8]}...")
        try:
            result = analyze(session)
            mark_analyzed(session["id"], result)
            print(f"[nora] model used:  {result.get('model_used')}")
            print(f"[nora] token cost:  {result.get('token_cost')}")
            print(f"[nora] bugs found:  {len(result.get('bugs', []))}")
            print(f"[nora] summary:     {result.get('summary')}")
            notify("Nora", result.get("summary", ""))
        except Exception as e:
            print(f"[nora] error: {e}")


# ── CASCADE SCHEMA AUTO-MIGRATION (v0.4-A) ────────────────────────────────────

def _ensure_cascade_schema():
    """Auto-run migration 0016 on first daemon boot after v0.4-A upgrade.

    Checks whether cascade_events and fact_embeddings tables exist; if either
    is missing, imports the migration module and calls up(). Idempotent — safe
    to call on every startup (the migration itself is try/except guarded).

    If the migration fails, logs a clear error; cascade ops will return
    {degraded: true, reason: 'migration_pending'} via cascade_engine (v0.4-B).
    """
    import sqlite3 as _sqlite3
    db_path = HOME / "echo.db"
    if not db_path.exists():
        return  # fresh install — init_db() will create tables later

    try:
        conn = _sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        needs_migration = (
            "cascade_events" not in tables or "fact_embeddings" not in tables
        )
        if needs_migration:
            log("cascade schema missing — running migration 0016 inline")
            import importlib.util
            import os
            mig_path = Path(os.path.dirname(os.path.abspath(__file__))) / "migrations" / "0016_cascade_schema.py"
            spec = importlib.util.spec_from_file_location("_mig_0016", mig_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.up(conn)
                log("cascade schema migration 0016 applied")
            else:
                log("WARNING: could not load migrations/0016_cascade_schema.py — cascade ops degraded")

        # 0017 — nora_metrics.session_id (Q2 / Task #388 / internal-rule).
        # Idempotent ALTER; runs every boot, no-ops if column already present.
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(nora_metrics)").fetchall()}
            if "session_id" not in cols:
                log("nora_metrics.session_id missing — running migration 0017 inline")
                import importlib.util
                import os
                mig_path = Path(os.path.dirname(os.path.abspath(__file__))) / "migrations" / "0017_nora_metrics_session_id.py"
                spec = importlib.util.spec_from_file_location("_mig_0017", mig_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.up(conn)
                    log("nora_metrics.session_id migration 0017 applied")
                else:
                    log("WARNING: could not load migrations/0017_nora_metrics_session_id.py — IHR component will stay 0.0")
        except Exception as _e0017:
            log(f"_ensure_cascade_schema 0017 error: {_e0017} — IHR component may stay 0.0")

        # 0018 — acceptance_events (Q3 DAR data-collection sprint / internal-rule).
        # Idempotent CREATE TABLE IF NOT EXISTS; runs every boot, no-ops if table
        # already present.  Boot-check verifies table existence before applying.
        try:
            tables_now = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "acceptance_events" not in tables_now:
                log("acceptance_events table missing — running migration 0018 inline")
                import importlib.util
                import os
                mig_path = (
                    Path(os.path.dirname(os.path.abspath(__file__)))
                    / "migrations"
                    / "0018_acceptance_events.py"
                )
                spec = importlib.util.spec_from_file_location("_mig_0018", mig_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.up(conn)
                    log("acceptance_events migration 0018 applied")
                else:
                    log(
                        "WARNING: could not load migrations/0018_acceptance_events.py"
                        " — DAR acceptance instrumentation unavailable"
                    )
        except Exception as _e0018:
            log(
                f"[F404] _ensure_cascade_schema 0018 error: {_e0018}"
                " — acceptance_events table may be missing; DAR signals will not record"
            )

        # 0019 — decision_traces (leverage ceiling sprint / internal-rule).
        # Idempotent CREATE TABLE IF NOT EXISTS; runs every boot, no-ops if
        # table already present.  Without this table, _compute_decision_trace_depth
        # returns None (uncomputable) and the leverage ceiling stays at 3.8×.
        try:
            tables_0019 = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "decision_traces" not in tables_0019:
                log("decision_traces table missing — running migration 0019 inline")
                import importlib.util
                import os
                mig_path = (
                    Path(os.path.dirname(os.path.abspath(__file__)))
                    / "migrations"
                    / "0019_decision_traces.py"
                )
                spec = importlib.util.spec_from_file_location("_mig_0019", mig_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.up(conn)
                    log("decision_traces migration 0019 applied — leverage ceiling now 5.0×")
                else:
                    log(
                        "WARNING: could not load migrations/0019_decision_traces.py"
                        " — decision_trace_depth uncomputable; leverage capped at 3.8×"
                    )
        except Exception as _e0019:
            log(
                f"[F404] _ensure_cascade_schema 0019 error: {_e0019}"
                " — decision_traces table may be missing; leverage depth will return None"
            )

        # 0025 — broaden engagement_events.trigger CHECK to allow 'ambient'.
        # Idempotent rebuild; no-ops if the CHECK already includes 'ambient'.
        # Without this the Python-level _ALLOWED_TRIGGERS guard still accepts
        # ambient rows but the DB INSERT would be rejected by the CHECK constraint.
        try:
            row_0025 = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='engagement_events'"
            ).fetchone()
            needs_0025 = row_0025 and row_0025[0] and "'ambient'" not in row_0025[0]
            if needs_0025:
                log("engagement_events CHECK narrow — running migration 0025 inline")
                import importlib.util as _ilu
                import os as _os_0025
                mig_path_0025 = (
                    Path(_os_0025.path.dirname(_os_0025.path.abspath(__file__)))
                    / "migrations"
                    / "0025_engagement_ambient_trigger.py"
                )
                spec_0025 = _ilu.spec_from_file_location("_mig_0025", mig_path_0025)
                if spec_0025 and spec_0025.loader:
                    mod_0025 = _ilu.module_from_spec(spec_0025)
                    spec_0025.loader.exec_module(mod_0025)
                    mod_0025.apply(conn)
                    log("engagement_events migration 0025 applied — ambient trigger now allowed")
                else:
                    log(
                        "WARNING: could not load migrations/0025_engagement_ambient_trigger.py"
                        " — ambient engagement events will be silently dropped by DB CHECK"
                    )
        except Exception as _e0025:
            log(
                f"[F404] _ensure_cascade_schema 0025 error: {_e0025}"
                " — ambient engagement events may not record; ambient grounding still works"
            )

        conn.close()
    except Exception as e:
        log(f"_ensure_cascade_schema error: {e} — cascade ops may be degraded")


# ── Harness Sweep scheduler entry point (§9.2 / §4.5 M-list — daemon.py) ────
#
# P1 NOTE: Sweep is CLI-invoked only in P1 (per §4.5 daemon.py WHY and §17.16).
# This function is the v1 hook point for daemon-scheduled Sweep GoalLoop
# invocations.  Shape C (new while-True loop) was rejected at Stage 3 §4.
# The Sweep is NOT a new while-True loop; it is a thin wrapper that calls
# GoalLoop.start() on a schedule.  P2 wires this into the daemon thread pool.
#
# TODO(P2): call schedule_sweep_loop() from main() after the Sweep daemon
# scheduling design is finalized.  Gated on P2 scope completion.

def schedule_sweep_loop():
    """P1 stub: v1 hook point for Sweep GoalLoop daemon invocations.

    In P1, this function is never called by main() — Sweep is CLI-only.
    In P2, a thin daemon wrapper calls this on a configurable schedule
    (nightly/weekly) without a new while-True loop.  GoalLoop owns all
    loop semantics; this function owns only scheduling.

    Usage (P2 caller pattern):
        t_sweep = threading.Thread(target=schedule_sweep_loop, daemon=True, name="sweep")
        t_sweep.start()
    """
    # P1: no-op stub.  Sweep scheduling wired in P2.
    pass


# ── R2 SYNC LOOP (issue #19 — scheduled replica drainer) ───────────────────────

def r2_sync_loop():
    """Periodically drain r2_sync_queue → push to R2, so chokepoint writes
    replicate WITHOUT a manual `kernora factbook sync`.

    No-op (cheap) when R2 isn't configured/licensed (select_factbook_store returns
    LocalYamlStore) — the common case for most installs. NEVER crashes the daemon.
    Cadence: config r2_sync_interval_s (default 900s, floor 60s). Sleeps first so
    boot isn't a thundering drain. The push path is the same one verified live
    (r2_sync.drain_pending → R2Sync.push, ETag-compare + Zone-C/candidate gates).
    """
    log("R2 sync loop started (replica drainer)")
    while True:
        interval = 900
        try:
            import kernora_mode as _km
            cfg = _km._read_r2_config()
            if cfg and cfg.get("r2_sync_interval_s"):
                interval = max(60, int(cfg["r2_sync_interval_s"]))
        except Exception:
            pass
        time.sleep(interval)
        try:
            import kernora_mode as _km
            store = _km.select_factbook_store()
            if type(store).__name__ != "S3CompatStore":
                continue  # R2 not configured/licensed — cheap no-op
            from r2_sync import drain_pending
            res = drain_pending(str(HOME / "echo.db"), store)
            if (res.get("drained", 0) + res.get("failed", 0) + res.get("skipped", 0)) > 0:
                log(f"R2 sync: drained={res.get('drained',0)} "
                    f"failed={res.get('failed',0)} skipped={res.get('skipped',0)}")
        except Exception as e:
            log(f"R2 sync loop error (non-fatal): {e}")


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "logs").mkdir(exist_ok=True)

    # ── Single-instance guard (§10.4 / D4) ───────────────────────────────────
    # Acquire BEFORE replay_spool (the real write hazard). Lock held for
    # process lifetime via module-global fd — never released by a `with` block.
    if not _acquire_singleton_lock():
        log("[SINGLETON] another daemon holds the lock — exiting")
        sys.exit(0)

    log("Nora daemon starting (BYOK mode)")
    log("Zero bytes will leave this machine.")
    init_db()
    _ensure_cascade_schema()
    replay_spool()

    t_socket   = threading.Thread(target=socket_server,  daemon=True, name="socket")
    t_analysis = threading.Thread(target=analysis_loop,  daemon=True, name="analysis")
    t_dreamer  = threading.Thread(target=dreamer_loop,   daemon=True, name="dreamer")
    t_pulse    = threading.Thread(target=pulse_loop,     daemon=True, name="pulse")
    t_r2sync   = threading.Thread(target=r2_sync_loop,   daemon=True, name="r2sync")

    t_socket.start()
    t_analysis.start()
    t_dreamer.start()
    t_pulse.start()
    t_r2sync.start()

    log("daemon ready. threads: socket | analysis | dreamer | pulse | r2sync")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log("daemon stopped.")


if __name__ == "__main__":
    # Founder 2026-07-24: Free/open-core ships and RUNS the full daemon.
    # Free↔full asymmetry is MCP tool count only — not CLI/daemon presence.
    # Companion without unlock still clean-degrades (KeepAlive-safe exit 0).
    # Missing kernora_mode (Free tree) → start Free daemon; premium loops
    # already degrade via their own try/except ImportError.
    try:
        import kernora_mode as _km
        requested = _km.requested_mode()
        if requested == "lite":
            print("[daemon] Free/Lite mode — starting daemon")
        else:
            _unlocked = getattr(_km, "is_companion" + "_unlocked", lambda: False)
            if not _unlocked():
                # K1: clean-degrade, NOT sys.exit(2). KeepAlive={SuccessfulExit:false}
                # so exit 0 is not respawned.
                print(
                    "[BLOCKED] companion requested but no license — "
                    "run 'kernora license activate' or use the dashboard banner",
                    file=sys.stderr,
                )
                sys.exit(0)
    except ImportError:
        print("[daemon] Free tier — starting without companion license module")
    except SystemExit:
        raise
    except Exception as _mode_exc:
        # kernora_mode present but unreadable — fail closed (do not run ungated).
        import traceback as _tb
        print(
            f"[DAEMON-STARTUP] FATAL: license module read failed "
            f"({type(_mode_exc).__name__}: {_mode_exc}) — cannot verify tier, "
            "refusing to start ungated. Fix the install (bash sync.sh) and restart: "
            "launchctl kickstart -k gui/$(id -u)/ai.kernora.daemon",
            file=sys.stderr,
        )
        _tb.print_exc(file=sys.stderr)
        sys.exit(0)
    main()
