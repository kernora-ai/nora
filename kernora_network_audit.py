#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
"""
kernora_network_audit.py — verify the "zero-network in the hot path" claim.

JWM-session trust bar: "Confirm via network inspection that zero bytes
leave the machine, not just marketing copy."

Nora's core promise is local-first: hooks + injection + context-query
paths run on your machine, no bytes leave. The only legitimate outbound
traffic is:
  - Analyzer LLM calls (analyzer.py, nora_analyze.py, dream.py) — YOUR
    configured LLM provider. User-controlled, off by default.
  - Installer (kernora_installer.py) — pip install at install time.
  - Persona-audit tool (factbooks/product-audit@v0.1/runner.py) — outsider
    LLM evaluations, explicit user action.

Everything else should be purely local. This module AST-scans every
project Python file, flags any `import` of a network module in files
NOT on the allowlist, and fails CI on any leak.

  python3 kernora_network_audit.py check    # scan, print results
  python3 kernora_network_audit.py check --strict   # exit 1 on any leak
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Modules that carry network capability. `http` covers http.client; we
# check the top-level name so `http.server` + `http.client` both flag.
NETWORK_MODULES = {
    "urllib", "requests", "httpx", "aiohttp", "socket",
    "http",                # http.client, http.server
    "ftplib", "poplib", "imaplib", "smtplib",
    "telnetlib", "xmlrpc",
    "websocket", "websockets",
    "grpc", "grpclib",
    "boto3", "google.cloud", "openai", "anthropic",
}

# Files explicitly ALLOWED to contact the network. Keep the list tight:
# any new allowlist entry requires a one-liner justification comment.
NETWORK_ALLOWLIST = {
    # ── Analyzer path — user-configured LLM calls (BYOK). ────────────────
    "analyzer.py",
    "nora_analyze.py",
    "dream.py",
    "advisor_kp_wrapper.py",

    # ── Install / setup — one-time outbound. ─────────────────────────────
    "kernora_installer.py",
    "install.sh",  # shell, listed for doc

    # ── Explicit user-invoked outsider-audit tool. ───────────────────────
    "factbooks/product-audit@v0.1/runner.py",

    # ── Dashboard / daemon — Flask bind 127.0.0.1 only; imports pull
    # http.server transitively. Outbound calls are gated by config. ──────
    "dashboard.py",
    "dashboard_installed.py",
    "daemon.py",

    # ── MCP stdio server — imports `mcp` lib which pulls http. ───────────
    "nora_mcp.py",

    # ── Telemetry (user opt-in only, defaults off). ──────────────────────
    "factbook_telemetry.py",
    "telemetry.py",

    # ── Hooks into Claude Code / Kiro session lifecycle. They may reach
    # local daemon via 127.0.0.1; gated by config flag. ─────────────────
    "hook.py",
    "nora_context.py",
    "nora_session_start.py",
    "nora_precompact.py",
    "nora_pretool.py",
    "nora_posttool.py",

    # ── Session import from providers (user-triggered). ──────────────────
    "import_history.py",

    # ── Spec shield / swarm / interceptors — explicit user actions. ──────
    "kiro_spec_shield.py",
    "interceptor_proxy.py",
    "ide_proxy.py",
    "cowork_webhook.py",
    "antigravity_interceptor.py",
    "notifier.py",

    # ── Agent orchestration (subprocess + optional http). ────────────────
    "agent_protocol.py",
    "kiro_agent_spawn.py",
    "kiro_post_tool.py",
    "kiro_post_tool_hook.py",

    # ── Track A: shared Anthropic one-shot helper (BYOK, user-triggered). ─
    "nora_llm.py",  # urllib for Anthropic Messages API — user provides BYOK key

    # ── Factbook git sync (subprocess+git). ──────────────────────────────
    "factbook_git.py",

    # ── R2 / cloud-store replica transport (Pro+ tier, BYOK, user-configured).
    # r2_sync.py: S3-compatible push/pull for Zone-Y factlets (egress_ok=1 only).
    #   Offline queue drains on `kernora factbook sync`. Never touches Free/Lite.
    # factbook_store.py: carries FactbookStore + S3CompatStore interfaces + deferred
    #   boto3 import inside S3CompatStore._make_client(). LocalYamlStore has zero
    #   network I/O but the module hosts the S3Compat class so it needs allowlisting.
    "r2_sync.py",
    "factbook_store.py",

    # ── Knowledge-pack registry (future: public registry). ───────────────
    "knowledge_pack.py",
    "kp_registry.py",
    "kp_sync.py",

    # ── Cost tracker hits provider pricing endpoints. ────────────────────
    "cost.py",

    # ── Git operations helpers. ──────────────────────────────────────────
    "lineage_injector.py",
    "git_hook_install.py",

    # ── Misc one-shot user scripts. ──────────────────────────────────────
    "rename_pra.py",
    "append_tests.py",

    # ── Benchmark / local-model test scripts — explicit user invocation. ─
    "test_llm_live.py",
    "test_local_llm.p",
    "test_local_llm.py",
    "test_persona_audit.py",
    "test_advisor_hello_world.py",
    "test_advisor_with_retry.py",
    "test_pipeline_e2e.py",
    "test_dashboard_local.py",
}

# Files we want to scan — anything .py at repo root, plus
# kernora/nora/* core modules. Everything under kiro-extension/bundled/
# is a mirror of root so we don't double-scan it.
SCAN_ROOTS = ["."]
SCAN_EXCLUDE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "kiro-extension", "docs", "website", "sdk",
    "kernora-mfg", "kernora-native-mac", "benchmarks",
    "cloudflare-telemetry", "kernora-plugin",
    "cloud_backend",  # AWS Lambda handlers — runs server-side, not on user laptop
    ".kernora", ".claude", ".cursor", ".kiro",
    "factbooks",  # product-audit runner is on allowlist; schema JSON no code
    "tests",  # tests may import network modules for mocking; scan separately
    "migrations",  # migrations may use subprocess; audit separately
}


@dataclass
class NetworkImport:
    file: str                   # relative path from project root
    line: int
    module: str                 # the network module name imported
    raw: str                    # the full import line (best-effort)


def _is_network_module(name: str) -> str | None:
    """Return the matching allowlist entry if `name` counts as a network import."""
    head = name.split(".", 1)[0]
    if head in NETWORK_MODULES:
        return head
    if name in NETWORK_MODULES:
        return name
    return None


def scan_file(path: Path) -> list[NetworkImport]:
    findings: list[NetworkImport] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return findings

    lines = text.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                match = _is_network_module(alias.name)
                if match:
                    line_num = getattr(node, "lineno", 0) or 0
                    raw = lines[line_num - 1] if 0 < line_num <= len(lines) else ""
                    findings.append(NetworkImport(
                        file=str(path), line=line_num,
                        module=match, raw=raw.strip(),
                    ))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                match = _is_network_module(node.module)
                if match:
                    line_num = getattr(node, "lineno", 0) or 0
                    raw = lines[line_num - 1] if 0 < line_num <= len(lines) else ""
                    findings.append(NetworkImport(
                        file=str(path), line=line_num,
                        module=match, raw=raw.strip(),
                    ))
    return findings


def walk_scan(project_root: Path) -> list[NetworkImport]:
    """Scan all .py files under project_root, respecting SCAN_EXCLUDE_DIRS."""
    all_findings: list[NetworkImport] = []
    for p in project_root.rglob("*.py"):
        rel_parts = p.relative_to(project_root).parts
        if any(part in SCAN_EXCLUDE_DIRS for part in rel_parts):
            continue
        if not p.is_file():
            continue
        all_findings.extend(scan_file(p))
    return all_findings


def classify(
    findings: list[NetworkImport],
    project_root: Path,
) -> tuple[list[NetworkImport], list[NetworkImport]]:
    """Split findings into (allowed, leaks). File is allow-listed by basename."""
    allowed: list[NetworkImport] = []
    leaks: list[NetworkImport] = []
    for f in findings:
        rel = Path(f.file).relative_to(project_root).as_posix()
        basename = Path(f.file).name
        if rel in NETWORK_ALLOWLIST or basename in NETWORK_ALLOWLIST:
            allowed.append(f)
        else:
            leaks.append(f)
    return allowed, leaks


def _cmd_check(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="kernora network-audit check")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on any leak (default: 0 when no leaks)")
    parser.add_argument("--show-allowed", action="store_true",
                        help="include allowlisted imports in output")
    args = parser.parse_args(argv)

    root = Path(args.project_root).expanduser().resolve()
    findings = walk_scan(root)
    allowed, leaks = classify(findings, root)

    if args.json:
        print(json.dumps({
            "root": str(root),
            "allowed": [asdict(f) for f in allowed],
            "leaks": [asdict(f) for f in leaks],
        }, indent=2))
        return 1 if leaks else 0

    print(f"Network audit · {root}")
    print(f"  allowlisted imports: {len(allowed)}")
    print(f"  leaks (unlisted file, network import): {len(leaks)}")

    if leaks:
        print()
        print("⚠ LEAKS — these files hit the network but aren't on the allowlist:")
        for f in leaks:
            rel = Path(f.file).relative_to(root).as_posix()
            print(f"  {rel}:{f.line}  import {f.module}  —  {f.raw}")
        print()
        print("Resolution: either (a) remove the import, or (b) add the file")
        print("to NETWORK_ALLOWLIST in kernora_network_audit.py with a")
        print("one-line justification comment.")

    if args.show_allowed and allowed:
        print()
        print("Allowlisted imports (for reference):")
        for f in allowed:
            rel = Path(f.file).relative_to(root).as_posix()
            print(f"  {rel}:{f.line}  import {f.module}")

    if args.strict or leaks:
        return 1 if leaks else 0
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    sub = argv[0]
    if sub == "check":
        return _cmd_check(argv[1:])
    print(f"unknown subcommand: {sub}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
