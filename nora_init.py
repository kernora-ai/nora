#!/usr/bin/env python3
"""
Kernora — nora init (v3)
Scans a codebase, proposes Agents, generates seed Knowledge Packs.

This is the bridge between Kernora's session-level intelligence (what you
talked about with the AI) and codebase-level intelligence (what the code
itself reveals).

Flow:
  1. SCAN  — code structure, git history (6mo), docs (PRFAQs, ADRs, tenets)
  2. PROPOSE — suggest domain-specific Agents based on what was found
  3. APPROVE — hybrid lifecycle: user reviews and approves/edits agents
  4. REGISTER — approved agents generate seed KPs and wire into DREAM pipeline

Usage:
  python3 nora_init.py [path]              # scan and propose
  python3 nora_init.py [path] --approve    # auto-approve all proposed agents
  python3 nora_init.py --status            # show registered agents

Integrates with:
  - db.py (echo.db — sessions, patterns, decisions)
  - knowledge_pack.py (KP creation and versioning)
  - dream.py (DREAM picks up agent contributions)
  - nora_context.py (context injection uses agent-derived patterns)
  - dashboard.py (shows agent status)

Elastic License 2.0 — commercial use requires agreement with kernora.ai
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────

KERNORA_DIR = Path.home() / ".kernora"
DB_PATH = KERNORA_DIR / "echo.db"
AGENTS_DIR = KERNORA_DIR / "agents"
KP_DIR = KERNORA_DIR / "knowledge_packs"

SKIP_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".env", "dist", "build", ".next", ".nuxt", "coverage", ".pytest_cache",
    ".mypy_cache", ".tox", "target", "vendor", "Pods", ".build",
    ".kernora", ".claude", ".nora", "Library", "Applications", ".kiro",
    "kernora-mfg",  # skip manufacturing prototype
}

CODE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".swift", ".kt", ".go",
    ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh", ".sql",
    ".css", ".html", ".vue", ".svelte",
}

DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc"}

DOC_MARKERS = {
    "prfaq": ["PRFAQ", "Press Release", "FAQ", "press_release"],
    "architecture": ["ARCHITECTURE", "ADR", "RFC", "design_doc", "TECHNICAL_DESIGN"],
    "tenets": ["TENETS", "PRINCIPLES", "tenet"],
    "roadmap": ["ROADMAP", "roadmap", "MILESTONE"],
    "strategy": ["STRATEGY", "PRODUCT_STRATEGY", "VISION", "ULTRATHINK"],
    "readme": ["README", "CONTRIBUTING", "QUICKSTART"],
    "runbook": ["RUNBOOK", "PLAYBOOK", "INCIDENT", "POST_MORTEM"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: SCANNERS
# ═══════════════════════════════════════════════════════════════════════════════

class CodeScanResult:
    """What the code scanner found."""
    def __init__(self):
        self.languages: Counter = Counter()         # ext → file count
        self.total_files: int = 0
        self.total_sloc: int = 0
        self.modules: list[dict] = []               # top-level dirs with code
        self.entry_points: list[str] = []           # main.py, index.ts, etc.
        self.config_files: list[str] = []           # pyproject.toml, package.json, etc.
        self.test_dirs: list[str] = []              # test/, tests/, __tests__/
        self.has_ci: bool = False                   # .github/workflows, .circleci, etc.
        self.has_docker: bool = False               # Dockerfile, docker-compose
        self.has_deps: dict = {}                    # {manager: file_path}
        self.frameworks: list[str] = []             # detected: flask, fastapi, react, etc.

    def to_dict(self) -> dict:
        return {
            "languages": dict(self.languages.most_common(10)),
            "total_files": self.total_files,
            "total_sloc": self.total_sloc,
            "modules": self.modules[:20],
            "entry_points": self.entry_points,
            "config_files": self.config_files,
            "test_dirs": self.test_dirs,
            "has_ci": self.has_ci,
            "has_docker": self.has_docker,
            "has_deps": self.has_deps,
            "frameworks": self.frameworks,
        }


class GitScanResult:
    """What the git scanner found."""
    def __init__(self):
        self.total_commits_6mo: int = 0
        self.authors: Counter = Counter()           # author → commit count
        self.churn_hotspots: list[dict] = []        # files with most changes
        self.commit_frequency: dict = {}            # weekly/daily averages
        self.recent_activity: list[dict] = []       # last 10 commits summary
        self.branch_count: int = 0
        self.tags: list[str] = []
        self.first_commit_date: str = ""
        self.latest_commit_date: str = ""

    def to_dict(self) -> dict:
        return {
            "total_commits_6mo": self.total_commits_6mo,
            "authors": dict(self.authors.most_common(10)),
            "churn_hotspots": self.churn_hotspots[:15],
            "commit_frequency": self.commit_frequency,
            "recent_activity": self.recent_activity[:10],
            "branch_count": self.branch_count,
            "tags": self.tags[-5:],
            "first_commit_date": self.first_commit_date,
            "latest_commit_date": self.latest_commit_date,
        }


class DocScanResult:
    """What the document scanner found."""
    def __init__(self):
        self.documents: list[dict] = []             # {path, type, title, size}
        self.doc_types: Counter = Counter()         # type → count
        self.total_doc_size: int = 0
        self.has_prfaq: bool = False
        self.has_architecture: bool = False
        self.has_tenets: bool = False
        self.has_roadmap: bool = False
        self.has_strategy: bool = False

    def to_dict(self) -> dict:
        return {
            "documents": self.documents[:30],
            "doc_types": dict(self.doc_types),
            "total_doc_size": self.total_doc_size,
            "has_prfaq": self.has_prfaq,
            "has_architecture": self.has_architecture,
            "has_tenets": self.has_tenets,
            "has_roadmap": self.has_roadmap,
            "has_strategy": self.has_strategy,
        }


# ── Code Scanner ─────────────────────────────────────────────────────────────

def scan_code(root: Path) -> CodeScanResult:
    """Scan code structure, languages, modules, frameworks."""
    result = CodeScanResult()
    root = root.resolve()

    # Detect top-level config files
    CONFIG_FILES = [
        "pyproject.toml", "setup.py", "setup.cfg",
        "package.json", "tsconfig.json",
        "Cargo.toml", "go.mod", "build.gradle", "pom.xml",
        "Gemfile", "Makefile", "CMakeLists.txt",
        "requirements.txt", "Pipfile",
    ]
    for cf in CONFIG_FILES:
        if (root / cf).exists():
            result.config_files.append(cf)
            if cf == "pyproject.toml":
                result.has_deps["pip"] = cf
            elif cf == "package.json":
                result.has_deps["npm"] = cf
            elif cf == "requirements.txt":
                result.has_deps["pip"] = cf
            elif cf == "Cargo.toml":
                result.has_deps["cargo"] = cf
            elif cf == "go.mod":
                result.has_deps["go"] = cf

    # CI detection
    ci_paths = [".github/workflows", ".circleci", ".gitlab-ci.yml", "Jenkinsfile", ".travis.yml"]
    for cp in ci_paths:
        if (root / cp).exists():
            result.has_ci = True
            break

    # Docker detection
    docker_files = ["Dockerfile", "docker-compose.yaml", "docker-compose.yml"]
    for df in docker_files:
        if (root / df).exists():
            result.has_docker = True
            break

    # Walk code files
    modules_seen = set()
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip excluded dirs
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        rel_dir = Path(dirpath).relative_to(root)

        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()

            if ext in CODE_EXTENSIONS:
                result.total_files += 1
                result.languages[ext] += 1

                # Count SLOC (fast: just non-blank lines)
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    sloc = sum(1 for line in text.splitlines() if line.strip())
                    result.total_sloc += sloc
                except Exception:
                    pass

                # Track top-level modules
                parts = rel_dir.parts
                if parts and parts[0] not in modules_seen:
                    modules_seen.add(parts[0])

                # Entry points
                if fname in ("main.py", "__main__.py", "index.ts", "index.js",
                             "app.py", "server.py", "cli.py", "main.go", "main.rs"):
                    result.entry_points.append(str(rel_dir / fname))

    # Top-level module info
    for mod_name in sorted(modules_seen):
        mod_path = root / mod_name
        if mod_path.is_dir():
            file_count = sum(1 for _ in mod_path.rglob("*") if _.is_file() and _.suffix in CODE_EXTENSIONS)
            if file_count > 0:
                result.modules.append({
                    "name": mod_name,
                    "files": file_count,
                })

    # Test directory detection
    test_names = {"test", "tests", "__tests__", "spec", "specs", "test_", "testing"}
    for d in root.iterdir():
        if d.is_dir() and d.name.lower() in test_names:
            result.test_dirs.append(d.name)

    # Framework detection (from imports / config)
    _detect_frameworks(root, result)

    return result


def _detect_frameworks(root: Path, result: CodeScanResult):
    """Detect frameworks from config files and imports."""
    # Python frameworks from pyproject.toml / requirements.txt
    for dep_file in ["pyproject.toml", "requirements.txt", "setup.py"]:
        fpath = root / dep_file
        if fpath.exists():
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore").lower()
                frameworks_map = {
                    "flask": "Flask", "fastapi": "FastAPI", "django": "Django",
                    "streamlit": "Streamlit", "gradio": "Gradio",
                    "sqlalchemy": "SQLAlchemy", "pydantic": "Pydantic",
                    "pytest": "pytest", "celery": "Celery",
                }
                for key, name in frameworks_map.items():
                    if key in text and name not in result.frameworks:
                        result.frameworks.append(name)
            except Exception:
                pass

    # JS/TS frameworks from package.json
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            js_map = {
                "react": "React", "next": "Next.js", "vue": "Vue",
                "angular": "Angular", "svelte": "Svelte", "express": "Express",
                "typescript": "TypeScript", "jest": "Jest", "vitest": "Vitest",
                "tailwindcss": "Tailwind", "prisma": "Prisma",
            }
            for key, name in js_map.items():
                if key in deps and name not in result.frameworks:
                    result.frameworks.append(name)
        except Exception:
            pass


# ── Git Scanner ──────────────────────────────────────────────────────────────

def scan_git(root: Path) -> Optional[GitScanResult]:
    """Scan git history for velocity, churn, and patterns."""
    if not (root / ".git").exists():
        return None

    result = GitScanResult()

    def _run_git(args: list[str]) -> str:
        try:
            proc = subprocess.run(
                ["git"] + args,
                cwd=root, capture_output=True, text=True, timeout=30,
            )
            return proc.stdout.strip() if proc.returncode == 0 else ""
        except Exception:
            return ""

    # Commits in last 6 months
    since = "6 months ago"
    log_output = _run_git([
        "log", f"--since={since}", "--format=%H|%an|%ae|%aI|%s",
        "--no-merges",
    ])
    if not log_output:
        return result

    commits = []
    for line in log_output.splitlines():
        parts = line.split("|", 4)
        if len(parts) >= 5:
            commits.append({
                "hash": parts[0][:8],
                "author": parts[1],
                "email": parts[2],
                "date": parts[3],
                "subject": parts[4],
            })
            result.authors[parts[1]] += 1

    result.total_commits_6mo = len(commits)
    result.recent_activity = [
        {"hash": c["hash"], "author": c["author"], "date": c["date"][:10], "subject": c["subject"][:80]}
        for c in commits[:10]
    ]

    if commits:
        result.latest_commit_date = commits[0]["date"][:10]

    # First commit ever
    first = _run_git(["log", "--reverse", "--format=%aI", "-1"])
    if first:
        result.first_commit_date = first[:10]

    # Branch count
    branches = _run_git(["branch", "-a"])
    if branches:
        result.branch_count = len([b for b in branches.splitlines() if b.strip()])

    # Tags
    tags = _run_git(["tag", "--sort=-creatordate"])
    if tags:
        result.tags = [t.strip() for t in tags.splitlines()[:10]]

    # Churn hotspots (files changed most often in last 6 months)
    churn_output = _run_git([
        "log", f"--since={since}", "--format=", "--name-only", "--no-merges",
    ])
    if churn_output:
        file_changes: Counter = Counter()
        for line in churn_output.splitlines():
            if line.strip():
                file_changes[line.strip()] += 1

        result.churn_hotspots = [
            {"file": f, "changes": c}
            for f, c in file_changes.most_common(20)
            if not any(skip in f for skip in SKIP_DIRS)
        ]

    # Commit frequency
    if commits:
        from datetime import datetime as dt
        try:
            dates = []
            for c in commits:
                d = c["date"][:10]
                dates.append(dt.strptime(d, "%Y-%m-%d"))
            if len(dates) >= 2:
                span_days = max(1, (dates[0] - dates[-1]).days)
                result.commit_frequency = {
                    "commits_per_week": round(len(commits) / max(1, span_days / 7), 1),
                    "commits_per_day": round(len(commits) / span_days, 1),
                    "active_days": len(set(d.strftime("%Y-%m-%d") for d in dates)),
                    "span_days": span_days,
                }
        except Exception:
            pass

    return result


# ── Document Scanner ─────────────────────────────────────────────────────────

def scan_docs(root: Path) -> DocScanResult:
    """Scan for strategy docs, PRFAQs, architecture docs, tenets, etc."""
    result = DocScanResult()
    root = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()

            if ext not in DOC_EXTENSIONS:
                continue

            # Classify document type (use rel_path to avoid false positives from parent dirs)
            rel_path = str(fpath.relative_to(root))
            doc_type = _classify_doc(fname, rel_path)

            try:
                size = fpath.stat().st_size
            except Exception:
                size = 0

            # Extract title from first non-empty line
            title = fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
                for line in text.splitlines():
                    stripped = line.strip().lstrip("#").strip()
                    if stripped:
                        title = stripped[:100]
                        break
            except Exception:
                pass

            result.documents.append({
                "path": rel_path,
                "type": doc_type,
                "title": title,
                "size_bytes": size,
                "filename": fname,
            })
            result.doc_types[doc_type] += 1
            result.total_doc_size += size

            # Flag key doc types
            if doc_type == "prfaq":
                result.has_prfaq = True
            elif doc_type == "architecture":
                result.has_architecture = True
            elif doc_type == "tenets":
                result.has_tenets = True
            elif doc_type == "roadmap":
                result.has_roadmap = True
            elif doc_type == "strategy":
                result.has_strategy = True

    return result


def _classify_doc(filename: str, rel_path: str) -> str:
    """Classify a document by its filename and project-relative path."""
    name_upper = filename.upper()
    path_str = rel_path.upper()

    for doc_type, markers in DOC_MARKERS.items():
        for marker in markers:
            if marker.upper() in name_upper or marker.upper() in path_str:
                return doc_type

    # Generic classification
    if filename.upper().startswith("LICENSE") or filename.upper().startswith("CHANGELOG"):
        return "meta"

    return "general"


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: AGENT PROPOSAL ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class ProposedAgent:
    """An Agent proposed by nora init for user approval."""
    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        name: str,
        description: str,
        scope: str,
        signals: list[str],
        confidence: float,
        reason: str,
    ):
        self.agent_id = agent_id
        self.agent_type = agent_type      # repo, architecture, dependency, doc, test, ci
        self.name = name
        self.description = description
        self.scope = scope                # what it monitors
        self.signals = signals            # what signals it watches
        self.confidence = confidence      # 0-1: how useful this agent would be
        self.reason = reason              # why it was proposed
        self.approved = False

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "signals": self.signals,
            "confidence": self.confidence,
            "reason": self.reason,
            "approved": self.approved,
        }


def propose_agents(
    code: CodeScanResult,
    git: Optional[GitScanResult],
    docs: DocScanResult,
    project_name: str,
) -> list[ProposedAgent]:
    """Analyze scan results and propose agents."""
    agents: list[ProposedAgent] = []

    # ── 1. Repo Agent (always proposed if code exists) ───────────────────
    if code.total_files > 0:
        lang_str = ", ".join(f"{ext} ({n})" for ext, n in code.languages.most_common(3))
        agents.append(ProposedAgent(
            agent_id=f"{project_name}-repo",
            agent_type="repo",
            name=f"{project_name} Repo Agent",
            description=(
                f"Monitors codebase health for {project_name}. "
                f"Tracks {code.total_files} files across {len(code.languages)} languages ({lang_str}). "
                f"Baselines: commit velocity, SLOC growth, module complexity."
            ),
            scope=f"{code.total_files} files, {code.total_sloc:,} SLOC",
            signals=[
                "commit_frequency", "sloc_delta", "file_churn",
                "test_coverage_delta", "build_pass_rate",
            ],
            confidence=0.95,
            reason="Every codebase needs a health baseline. This is the foundation agent.",
        ))

    # ── 2. Architecture Agent (if ADRs, ARCHITECTURE.md, or strategy docs) ──
    if docs.has_architecture or docs.has_strategy:
        arch_docs = [d for d in docs.documents if d["type"] in ("architecture", "strategy")]
        agents.append(ProposedAgent(
            agent_id=f"{project_name}-architecture",
            agent_type="architecture",
            name=f"{project_name} Architecture Agent",
            description=(
                f"Tracks architectural intent vs reality. "
                f"Scans {len(arch_docs)} architecture/strategy docs. "
                f"Detects drift: when code evolves away from documented decisions."
            ),
            scope=f"{len(arch_docs)} architecture docs",
            signals=[
                "architecture_doc_staleness", "decision_drift",
                "module_boundary_violations", "dependency_direction",
            ],
            confidence=0.85,
            reason=f"Found {len(arch_docs)} architecture/strategy documents. Drift detection prevents silent technical debt.",
        ))

    # ── 3. Dependency Agent (if package manager found) ───────────────────
    if code.has_deps:
        managers = ", ".join(code.has_deps.keys())
        agents.append(ProposedAgent(
            agent_id=f"{project_name}-deps",
            agent_type="dependency",
            name=f"{project_name} Dependency Agent",
            description=(
                f"Monitors dependency health via {managers}. "
                f"Tracks: staleness, known vulnerabilities, update velocity, "
                f"abandoned packages, license changes."
            ),
            scope=f"Package managers: {managers}",
            signals=[
                "dep_staleness_days", "dep_vulnerability_count",
                "dep_update_lag", "dep_abandoned_risk",
            ],
            confidence=0.80,
            reason=f"Found {managers} dependency management. Stale deps are the #1 source of security incidents in software.",
        ))

    # ── 4. Product Intent Agent (if PRFAQs, roadmaps found) ─────────────
    if docs.has_prfaq or docs.has_roadmap:
        intent_docs = [d for d in docs.documents if d["type"] in ("prfaq", "roadmap")]
        agents.append(ProposedAgent(
            agent_id=f"{project_name}-product",
            agent_type="product",
            name=f"{project_name} Product Intent Agent",
            description=(
                f"Aligns engineering work with product intent. "
                f"Cross-references {len(intent_docs)} PRFAQs/roadmaps against "
                f"recent commits and session activity. Detects when engineering "
                f"drifts from product priorities."
            ),
            scope=f"{len(intent_docs)} product docs",
            signals=[
                "roadmap_item_progress", "prfaq_coverage",
                "feature_vs_maintenance_ratio", "unplanned_work_pct",
            ],
            confidence=0.75,
            reason=f"Found PRFAQs/roadmaps. Engineering-product alignment is the highest-leverage insight for founders.",
        ))

    # ── 5. Test Health Agent (if test dirs found) ────────────────────────
    if code.test_dirs:
        agents.append(ProposedAgent(
            agent_id=f"{project_name}-tests",
            agent_type="test",
            name=f"{project_name} Test Health Agent",
            description=(
                f"Monitors test suite quality. "
                f"Tracks coverage trends, flaky tests, test-to-code ratio, "
                f"and which code changes skip test updates."
            ),
            scope=f"Test directories: {', '.join(code.test_dirs)}",
            signals=[
                "test_coverage_pct", "test_to_code_ratio",
                "flaky_test_count", "untested_hotspot_files",
            ],
            confidence=0.70,
            reason=f"Found test directories ({', '.join(code.test_dirs)}). Test quality directly predicts production reliability.",
        ))

    # ── 6. CI/CD Agent (if CI config found) ──────────────────────────────
    if code.has_ci:
        agents.append(ProposedAgent(
            agent_id=f"{project_name}-cicd",
            agent_type="ci",
            name=f"{project_name} CI/CD Agent",
            description=(
                f"Monitors build pipeline health. "
                f"Tracks: build pass rate, deploy frequency, pipeline duration, "
                f"rollback rate, build-to-deploy cycle time."
            ),
            scope="CI/CD pipeline",
            signals=[
                "build_pass_rate", "deploy_frequency",
                "pipeline_duration_trend", "rollback_rate",
            ],
            confidence=0.70,
            reason="Found CI/CD configuration. Pipeline health is a leading indicator of engineering velocity.",
        ))

    # ── 7. Tenets Agent (if TENETS.md found) ─────────────────────────────
    if docs.has_tenets:
        agents.append(ProposedAgent(
            agent_id=f"{project_name}-tenets",
            agent_type="tenets",
            name=f"{project_name} Tenets Agent",
            description=(
                f"Guards engineering tenets. "
                f"Monitors sessions and commits for tenet violations. "
                f"Surfaces when decisions contradict documented principles."
            ),
            scope="TENETS.md",
            signals=[
                "tenet_violation_count", "tenet_reinforcement_count",
                "decision_tenet_alignment",
            ],
            confidence=0.65,
            reason="Found TENETS.md. Tenets only work if someone enforces them. This agent does that automatically.",
        ))

    # ── 8. Git Velocity Agent (if git history exists) ────────────────────
    if git and git.total_commits_6mo > 20:
        freq = git.commit_frequency.get("commits_per_week", 0)
        agents.append(ProposedAgent(
            agent_id=f"{project_name}-velocity",
            agent_type="velocity",
            name=f"{project_name} Velocity Agent",
            description=(
                f"Tracks engineering velocity patterns. "
                f"{git.total_commits_6mo} commits in last 6 months "
                f"({freq} commits/week average). "
                f"Detects slowdowns, context-switching overhead, and churn spikes."
            ),
            scope=f"{git.total_commits_6mo} commits, {len(git.authors)} contributors",
            signals=[
                "commits_per_week_trend", "pr_cycle_time",
                "context_switch_rate", "churn_spike_detection",
            ],
            confidence=0.80,
            reason=f"Enough git history ({git.total_commits_6mo} commits) to establish velocity baselines.",
        ))

    # Sort by confidence descending
    agents.sort(key=lambda a: a.confidence, reverse=True)
    return agents


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: SEED KNOWLEDGE PACK GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def generate_seed_kp(
    agent: ProposedAgent,
    code: CodeScanResult,
    git: Optional[GitScanResult],
    docs: DocScanResult,
    project_name: str,
) -> dict:
    """Generate a seed Knowledge Pack from scan data for an approved agent."""
    now = datetime.now(timezone.utc).isoformat()

    kp = {
        "id": f"kp-{agent.agent_id}",
        "name": f"{agent.name} — Seed KP",
        "pack_type": "project",
        "scope": project_name,
        "version": "0.1.0",
        "agent_id": agent.agent_id,
        "agent_type": agent.agent_type,
        "created_by": "nora_init",
        "created_at": now,
        "source": "code_scan",
        "baselines": {},
        "patterns": [],
        "decisions": [],
        "signals_monitored": agent.signals,
    }

    # ── Baselines from scan data ─────────────────────────────────────────
    if agent.agent_type == "repo":
        kp["baselines"] = {
            "total_files": code.total_files,
            "total_sloc": code.total_sloc,
            "languages": dict(code.languages.most_common(10)),
            "module_count": len(code.modules),
            "frameworks": code.frameworks,
            "has_tests": bool(code.test_dirs),
            "has_ci": code.has_ci,
            "has_docker": code.has_docker,
        }
        if git:
            kp["baselines"]["commits_per_week"] = git.commit_frequency.get("commits_per_week", 0)
            kp["baselines"]["contributor_count"] = len(git.authors)
            kp["baselines"]["churn_hotspots"] = [h["file"] for h in git.churn_hotspots[:5]]

    elif agent.agent_type == "architecture":
        arch_docs = [d for d in docs.documents if d["type"] in ("architecture", "strategy")]
        kp["baselines"] = {
            "architecture_docs": [d["path"] for d in arch_docs],
            "modules": [m["name"] for m in code.modules],
            "module_boundaries": {m["name"]: m["files"] for m in code.modules},
        }

    elif agent.agent_type == "dependency":
        kp["baselines"] = {
            "package_managers": list(code.has_deps.keys()),
            "frameworks": code.frameworks,
            "scan_date": now[:10],
        }

    elif agent.agent_type == "product":
        intent_docs = [d for d in docs.documents if d["type"] in ("prfaq", "roadmap")]
        kp["baselines"] = {
            "product_docs": [d["path"] for d in intent_docs],
            "doc_count": len(intent_docs),
        }

    elif agent.agent_type == "velocity" and git:
        kp["baselines"] = {
            "commits_per_week": git.commit_frequency.get("commits_per_week", 0),
            "commits_per_day": git.commit_frequency.get("commits_per_day", 0),
            "contributor_count": len(git.authors),
            "top_contributors": dict(git.authors.most_common(5)),
            "churn_hotspots": git.churn_hotspots[:10],
            "branch_count": git.branch_count,
        }

    elif agent.agent_type == "test":
        kp["baselines"] = {
            "test_dirs": code.test_dirs,
            "has_ci": code.has_ci,
        }

    elif agent.agent_type == "ci":
        kp["baselines"] = {
            "has_ci": code.has_ci,
            "has_docker": code.has_docker,
        }

    elif agent.agent_type == "tenets":
        tenet_docs = [d for d in docs.documents if d["type"] == "tenets"]
        kp["baselines"] = {
            "tenet_docs": [d["path"] for d in tenet_docs],
        }

    return kp


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: PERSISTENCE — REGISTER AGENTS + STORE KPs
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_agents_table(conn: sqlite3.Connection):
    """Create agents table if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id           TEXT PRIMARY KEY,
            agent_type   TEXT NOT NULL,
            name         TEXT NOT NULL,
            description  TEXT,
            scope        TEXT,
            signals      TEXT,
            project      TEXT,
            status       TEXT DEFAULT 'active',
            seed_kp_id   TEXT,
            config_json  TEXT,
            created_at   TEXT DEFAULT (datetime('now')),
            updated_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_signals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id     TEXT REFERENCES agents(id),
            signal_type  TEXT NOT NULL,
            signal_value TEXT,
            timestamp    TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_signals_agent ON agent_signals(agent_id, timestamp)")
    conn.commit()


def register_agent(conn: sqlite3.Connection, agent: ProposedAgent, kp: dict, project: str):
    """Register an approved agent and its seed KP in the database."""
    conn.execute("""
        INSERT OR REPLACE INTO agents (id, agent_type, name, description, scope, signals, project, seed_kp_id, config_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        agent.agent_id, agent.agent_type, agent.name, agent.description,
        agent.scope, json.dumps(agent.signals), project,
        kp["id"], json.dumps(agent.to_dict()),
    ))
    conn.commit()


def store_seed_kp(conn: sqlite3.Connection, kp: dict, scan_sources: list[str] | None = None):
    """Store a seed KP in the knowledge_packs table (v2 schema)."""
    # Use the existing KP schema from knowledge_pack.py
    try:
        from knowledge_pack import ensure_kp_tables
        ensure_kp_tables(conn)
    except ImportError:
        pass  # Table may already exist

    # v2: build provenance from nora_init context
    provenance = {
        "method": "nora_init",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_type": kp.get("agent_type", ""),
    }
    if kp.get("scan_summary"):
        provenance["scan_summary"] = kp["scan_summary"]

    # v2: build basic dependencies from agent signals
    dependencies = {"required": {"tools": [], "skills": [], "kps": []},
                    "recommended": {"tools": [], "skills": [], "kps": []}}

    # v2: calculate initial confidence from baselines
    baselines = kp.get("baselines", {})
    baseline_count = len(baselines)
    confidence = min(1.0, 0.3 + (baseline_count * 0.08))

    # UPSERT — do NOT use INSERT OR REPLACE: it blows away fields that the
    # user or other subsystems may have set (pin_state, share_token,
    # injection_md, tags, ...). Instead, insert on conflict update only the
    # nora_init-owned columns, and explicitly preserve pin_state.
    existing = conn.execute(
        "SELECT id, pin_state FROM knowledge_packs WHERE id = ?",
        (kp["id"],),
    ).fetchone()
    if existing:
        # Preserve pin_state — refresh the seed content, but don't unpin.
        conn.execute("""
            UPDATE knowledge_packs
            SET name          = ?,
                pack_type     = ?,
                scope         = ?,
                version       = ?,
                content_json  = ?,
                summary       = ?,
                dependencies  = ?,
                scan_sources  = ?,
                provenance    = ?,
                confidence    = ?,
                refresh_state = 'current',
                updated_at    = datetime('now')
            WHERE id = ?
        """, (
            kp["name"], kp["pack_type"], kp["scope"],
            kp["version"], json.dumps(kp), kp["name"],
            json.dumps(dependencies),
            json.dumps(scan_sources or []),
            json.dumps(provenance),
            round(confidence, 3),
            kp["id"],
        ))
    else:
        conn.execute("""
            INSERT INTO knowledge_packs
                (id, name, pack_type, scope, version, content_json, summary, created_at,
                 dependencies, scan_sources, provenance, confidence, refresh_state, pin_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'),
                    ?, ?, ?, ?, 'current', 'pinned')
        """, (
            kp["id"], kp["name"], kp["pack_type"], kp["scope"],
            kp["version"], json.dumps(kp), kp["name"],
            json.dumps(dependencies),
            json.dumps(scan_sources or []),
            json.dumps(provenance),
            round(confidence, 3),
        ))
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR — nora init
# ═══════════════════════════════════════════════════════════════════════════════

def run_init(
    root: Path,
    auto_approve: bool = False,
    verbose: bool = True,
    ingest_docs: bool = False,
) -> dict:
    """
    Run the full nora init pipeline:
      1. Scan code, git, docs
      2. Propose agents
      3. Approve (interactive or auto)
      4. Register agents + generate seed KPs
      5. (optional, --ingest-docs) LLM fact extraction from documents
    """
    root = root.resolve()
    project_name = root.name

    results = {
        "project": project_name,
        "root": str(root),
        "scan": {},
        "proposed_agents": [],
        "approved_agents": [],
        "kps_generated": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # ── Phase 1: SCAN ────────────────────────────────────────────────────
    if verbose:
        print(f"\n{'━' * 60}")
        print(f"  NORA INIT — {project_name}")
        print(f"  {root}")
        print(f"{'━' * 60}\n")
        print("  Phase 1: Scanning codebase...")

    t0 = time.time()
    code = scan_code(root)
    git = scan_git(root)
    docs = scan_docs(root)
    scan_time = time.time() - t0

    results["scan"] = {
        "code": code.to_dict(),
        "git": git.to_dict() if git else None,
        "docs": docs.to_dict(),
        "scan_time_ms": round(scan_time * 1000),
    }

    if verbose:
        print(f"\n  Code: {code.total_files} files, {code.total_sloc:,} SLOC, "
              f"{len(code.languages)} languages")
        if code.frameworks:
            print(f"  Frameworks: {', '.join(code.frameworks)}")
        if git:
            print(f"  Git: {git.total_commits_6mo} commits (6mo), "
                  f"{len(git.authors)} contributors")
            if git.commit_frequency:
                print(f"  Velocity: {git.commit_frequency.get('commits_per_week', 0)} commits/week")
        print(f"  Docs: {len(docs.documents)} documents "
              f"({'PRFAQ ' if docs.has_prfaq else ''}"
              f"{'ARCH ' if docs.has_architecture else ''}"
              f"{'TENETS ' if docs.has_tenets else ''}"
              f"{'ROADMAP ' if docs.has_roadmap else ''}"
              f"{'STRATEGY' if docs.has_strategy else ''})")
        print(f"  Scan time: {scan_time * 1000:.0f}ms")

    # ── Phase 2: PROPOSE AGENTS ──────────────────────────────────────────
    if verbose:
        print(f"\n  Phase 2: Proposing agents...\n")

    proposed = propose_agents(code, git, docs, project_name)
    results["proposed_agents"] = [a.to_dict() for a in proposed]

    if verbose:
        for i, agent in enumerate(proposed):
            conf_bar = "█" * int(agent.confidence * 10) + "░" * (10 - int(agent.confidence * 10))
            print(f"  [{i+1}] {agent.name}")
            print(f"      Type: {agent.agent_type} | Confidence: {conf_bar} {agent.confidence:.0%}")
            print(f"      {agent.reason}")
            print()

    if not proposed:
        if verbose:
            print("  No agents proposed. Is this a code repository?")
        return results

    # ── Phase 3: APPROVE ─────────────────────────────────────────────────
    if auto_approve:
        for agent in proposed:
            agent.approved = True
        if verbose:
            print(f"  Phase 3: Auto-approved {len(proposed)} agents\n")
    else:
        if verbose:
            print(f"  Phase 3: Review proposed agents")
            print(f"  (Enter numbers to approve, 'all' for all, 'q' to quit)\n")
            try:
                choice = input(f"  Approve agents [all]: ").strip().lower()
                if choice in ("", "all", "a", "y", "yes"):
                    for agent in proposed:
                        agent.approved = True
                elif choice in ("q", "quit", "n", "no"):
                    pass
                else:
                    # Parse comma-separated numbers
                    for num_str in choice.replace(",", " ").split():
                        try:
                            idx = int(num_str) - 1
                            if 0 <= idx < len(proposed):
                                proposed[idx].approved = True
                        except ValueError:
                            pass
            except (EOFError, KeyboardInterrupt):
                # Non-interactive — approve all
                for agent in proposed:
                    agent.approved = True

    approved = [a for a in proposed if a.approved]
    results["approved_agents"] = [a.to_dict() for a in approved]

    if not approved:
        if verbose:
            print("  No agents approved. Run with --approve to auto-approve.")
        return results

    # ── Phase 4: REGISTER + GENERATE KPs ─────────────────────────────────
    if verbose:
        print(f"  Phase 4: Registering {len(approved)} agents + generating seed KPs...\n")

    # Open DB
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_agents_table(conn)

    # Build scan_sources list from scanned root
    scan_source_paths = [str(root)]

    for agent in approved:
        kp = generate_seed_kp(agent, code, git, docs, project_name)
        # v2: attach scan summary to KP for provenance
        kp["scan_summary"] = {
            "files": code.total_files,
            "sloc": code.total_sloc,
            "commits": git.total_commits_6mo if git else 0,
            "docs": len(docs.documents),
        }
        register_agent(conn, agent, kp, project_name)
        store_seed_kp(conn, kp, scan_sources=scan_source_paths)
        results["kps_generated"].append(kp["id"])

        if verbose:
            baseline_count = len(kp.get("baselines", {}))
            print(f"    ✓ {agent.name} → KP {kp['id']} ({baseline_count} baselines)")

    conn.close()

    # ── Write scan results to disk ───────────────────────────────────────
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    scan_file = AGENTS_DIR / f"{project_name}-init.json"
    with open(scan_file, "w") as f:
        json.dump(results, f, indent=2)

    # ── Phase 5: Document fact extraction (optional) ─────────────────────
    doc_ingest_result = None
    if ingest_docs and docs.documents:
        if verbose:
            print(f"\n  Phase 5: Document fact extraction ({len(docs.documents)} docs)...\n")
        try:
            from doc_ingest import ingest_documents, _load_cfg
            cfg = _load_cfg()
            doc_ingest_result = ingest_documents(
                project_paths=[str(root)],
                db_path=str(DB_PATH),
                cfg=cfg,
                force=False,
            )
            results["doc_ingest"] = doc_ingest_result
            if verbose:
                print(f"  Facts extracted from {doc_ingest_result.get('analyzed', 0)} documents "
                      f"({doc_ingest_result.get('skipped', 0)} skipped, "
                      f"{doc_ingest_result.get('errors', 0)} errors)")
        except ImportError:
            if verbose:
                print("  [skip] doc_ingest not available")
        except Exception as e:
            if verbose:
                print(f"  [warn] Document fact extraction failed: {e}")

    if verbose:
        print(f"\n{'━' * 60}")
        print(f"  NORA INIT COMPLETE")
        print(f"{'━' * 60}")
        print(f"  Agents registered: {len(approved)}")
        print(f"  Seed KPs generated: {len(results['kps_generated'])}")
        print(f"  Scan saved: {scan_file}")
        if docs.documents and not ingest_docs:
            print(f"\n  Tip: {len(docs.documents)} documents found. Run with --ingest-docs")
            print(f"  to extract key facts, learnings, and decisions via LLM.")
        print(f"\n  Next: agents will contribute to DREAM consolidation")
        print(f"  and inject code-derived patterns into your sessions.")
        print(f"{'━' * 60}\n")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="nora init — scan codebase, propose agents, generate seed KPs",
    )
    parser.add_argument("path", nargs="?", default=".",
                        help="Path to the project root (default: current directory)")
    parser.add_argument("--approve", action="store_true",
                        help="Auto-approve all proposed agents")
    parser.add_argument("--status", action="store_true",
                        help="Show currently registered agents")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--quiet", action="store_true",
                        help="Minimal output")
    parser.add_argument("--ingest-docs", action="store_true",
                        help="Run LLM fact extraction on found documents (Phase 5)")
    args = parser.parse_args()

    if args.status:
        _show_status()
        return

    root = Path(args.path).resolve()
    if not root.exists():
        print(f"Error: path does not exist: {root}")
        sys.exit(1)

    results = run_init(
        root=root,
        auto_approve=args.approve,
        verbose=not args.quiet and not args.json,
        ingest_docs=args.ingest_docs,
    )

    if args.json:
        print(json.dumps(results, indent=2))


def _show_status():
    """Show registered agents."""
    if not DB_PATH.exists():
        print("  No database found. Run: nora init <path>")
        return

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    ensure_agents_table(conn)

    agents = conn.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
    if not agents:
        print("  No agents registered. Run: nora init <path>")
        return

    print(f"\n  Registered Agents ({len(agents)}):\n")
    for a in agents:
        signals = json.loads(a["signals"]) if a["signals"] else []
        print(f"  [{a['status']}] {a['name']} ({a['agent_type']})")
        print(f"          Scope: {a['scope']}")
        print(f"          Signals: {', '.join(signals[:3])}")
        print(f"          KP: {a['seed_kp_id']}")
        print()

    conn.close()


if __name__ == "__main__":
    main()
