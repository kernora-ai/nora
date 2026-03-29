#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora/nora-engine/blob/main/LICENSE
"""
Analysis layer — Two-Phase Deep Extraction.

Phase 1 (deterministic, zero LLM cost):
  Extract tools_used, files_touched, commands_run from raw JSONL events.
  100% accuracy — no hallucination.

Phase 2 (LLM, condensed input):
  Build a "highlight reel" — user prompts, key decisions, error sequences —
  then send THAT (much smaller) plus Phase 1 metadata for semantic extraction.

Uses LiteLLM (MIT license) to support:
  - Anthropic Haiku (user's ANTHROPIC_API_KEY)
  - AWS Bedrock Nova Lite / Nova Micro / Nova Pro (user's AWS profile)
  - Ollama local models (localhost:11434)

User supplies credentials. Kernora never sees API keys or transcripts.
"""
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # pip install tomli
        except ImportError:
            tomllib = None  # type: ignore

CONFIG_PATH = Path.home() / ".kernora" / "config.toml"

# ── Phase 2 Prompt: focused semantic extraction ──────────────────────────────
# Phase 1 metadata is injected as context so the LLM doesn't have to guess at
# tools/files/commands and can focus on higher-order reasoning.
PROMPT = """You are Nora, an AI work intelligence analyst for Kernora.
Analyze this AI coding session. You receive two inputs:
1. PRE-EXTRACTED METADATA (deterministic, 100% accurate) — tools, files, commands
2. SESSION HIGHLIGHTS — condensed high-signal turns from the transcript

Your job: extract the SEMANTIC intelligence that only an LLM can provide.
Return ONLY valid JSON — no markdown, no prose outside the JSON.

Required JSON format:
{{
  "session_type": "one of: feature_build | debugging | refactoring | infrastructure | research | deployment | review | multi_agent_coordination | skill_creation | configuration | exploration",
  "workflow_stage": "one of: ideation | design | implementation | testing | review | deployment | maintenance",
  "summary": "2-3 sentence summary: what was built, what problems were solved, what was the outcome",
  "themes": [{{"label": "string", "severity": "high|medium|low", "count": 1}}],
  "bugs": [{{"title": "string", "file": "path or empty", "fix": "string", "severity": "high|medium|low"}}],
  "optimizations": [{{"title": "string", "impact": "high|medium|low", "suggestion": "string"}}],
  "playbook": "If this session represents a repeatable workflow, describe the step-by-step playbook in 3-8 steps. Empty string if not applicable.",
  "architectural_decisions": [{{"decision": "what was decided", "context": "why", "alternatives_considered": "what else was weighed"}}],
  "effective_prompts": [{{"prompt": "the user prompt that worked well", "why_effective": "what made it good"}}],
  "anti_patterns": [{{"pattern": "what went wrong", "impact": "wasted time|bugs|rework", "fix": "how to avoid next time"}}],
  "claude_md_rules": ["CLAUDE.md rule suggestions — things that should be codified as project rules based on this session"],
  "knowledge_domains": ["list of technical domains exercised: e.g. swift, flask, sqlite, launchd, htmx, git, etc."],
  "reusable_patterns": [{{"pattern": "reusable technique or approach discovered", "context": "when to apply it"}}],
  "prompt_quality": 0.0,
  "prompt_avg_words": 0,
  "repetition_count": 0
}}

Scoring rules:
- session_type: classify based on the PRIMARY activity, not everything that happened
- workflow_stage: where in the SDLC did this session operate
- playbook: only populate if the session shows a REPEATABLE workflow (e.g. "debug → diagnose → fix → test → verify")
- architectural_decisions: real decisions with tradeoffs, not just "used Python"
- effective_prompts: prompts that produced excellent results on first try — max 3
- anti_patterns: things the human or AI did that caused rework — max 3
- claude_md_rules: max 5 rules. Format as imperative sentences. Focus on project-specific conventions, not generic advice.
- prompt_quality: 0.0-1.0 (1.0 = precise, contextual, gives AI everything it needs)
- repetition_count: how many turns repeated/clarified something already said
- If session is empty or too short: return all empty arrays/strings, quality 0.0, summary "Empty session."

──────────────────────────────────────────────────────
PRE-EXTRACTED METADATA (Phase 1 — deterministic):
{metadata}

──────────────────────────────────────────────────────
SESSION HIGHLIGHTS (condensed transcript):
{transcript}"""


def _inject_key_from_plist() -> None:
    """
    LaunchAgents bake ANTHROPIC_API_KEY into the plist EnvironmentVariables block.
    When analyzer.py is run directly (e.g. `python3 -c "from daemon import ..."`),
    the shell may not have the key exported. This reads it from the daemon plist
    as a fallback so CLI invocations work without `export ANTHROPIC_API_KEY=...`.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return  # already set, nothing to do
    plist = Path.home() / "Library/LaunchAgents/ai.kernora.daemon.plist"
    if not plist.exists():
        return
    try:
        txt = plist.read_text()
        m = re.search(
            r'<key>ANTHROPIC_API_KEY</key>\s*<string>([^<]+)</string>', txt
        )
        if m:
            os.environ["ANTHROPIC_API_KEY"] = m.group(1).strip()
    except Exception:
        pass


# Auto-inject on import so any script using analyzer gets the key
_inject_key_from_plist()


def load_config() -> dict:
    if CONFIG_PATH.exists() and tomllib is not None:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {
        "model": {"provider": "auto"},
        "bedrock": {"region": "us-east-1", "model": "amazon.nova-lite-v1:0"},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL TIER SYSTEM — Deep extraction uses the best available model
#
# Three tiers, auto-selected based on available API keys:
#   DEEP   — Complex semantic extraction (playbooks, decisions, patterns)
#   CLASSIFY — Session classification, themes, bugs, summary
#   BUDGET — Fallback when only cheap/free models available
#
# Capability rating per model (1-5 for structured JSON extraction quality):
#   5: Sonnet 4.6, Gemini 2.5 Pro, GPT-4o
#   4: Sonnet 4, Gemini 2.5 Flash, Haiku 4.5, GPT-4o-mini
#   3: Nova Pro, Grok-beta
#   2: Nova Lite, Gemini 2.5 Flash Lite, Llama 3.2 8B
#   1: Nova Micro, Llama 3.2 3B — too weak, flag to user
# ═══════════════════════════════════════════════════════════════════════════════

# Model definitions: (litellm_id, capability_score, cost_per_M_input_tokens)
# Capability scores for structured JSON extraction from coding transcripts:
#   5: Frontier — excellent at nuanced extraction (playbooks, decisions, patterns)
#   4: Strong — reliable structured output, good for classification + summaries
#   3: Adequate — handles simple extraction, weaker on nuanced fields
#   2: Minimal — basic classification only, misses complex fields
#   1: Insufficient — too weak for this workload, flag to user
MODELS = {
    # ── Anthropic ──
    "sonnet-4.6":    ("anthropic/claude-sonnet-4-6",          5, 3.00),
    "haiku-4.5":     ("anthropic/claude-haiku-4-5-20251001",  4, 0.80),
    # ── Google Gemini 3.x (preview — latest as of March 2026) ──
    "gemini-3.1-pro":      ("gemini/gemini-3.1-pro-preview",       5, 1.25),
    "gemini-3-flash":      ("gemini/gemini-3-flash-preview",       4, 0.15),
    "gemini-3.1-flash-lite": ("gemini/gemini-3.1-flash-lite-preview", 3, 0.04),
    # ── Google Gemini 2.5 (GA — stable) ──
    "gemini-2.5-pro":      ("gemini/gemini-2.5-pro",               5, 1.25),
    "gemini-2.5-flash":    ("gemini/gemini-2.5-flash",             4, 0.15),
    "gemini-2.5-flash-lite": ("gemini/gemini-2.5-flash-lite",      2, 0.04),
    # ── OpenAI ──
    "gpt-4o":        ("openai/gpt-4o",                        5, 2.50),
    "gpt-4o-mini":   ("openai/gpt-4o-mini",                   4, 0.15),
    # ── Amazon Bedrock ──
    "nova-pro":      ("bedrock/amazon.nova-pro-v1:0",         3, 0.80),
    "nova-lite":     ("bedrock/amazon.nova-lite-v1:0",        2, 0.06),
    "nova-micro":    ("bedrock/amazon.nova-micro-v1:0",       1, 0.04),
    # ── xAI ──
    "grok-beta":     ("xai/grok-beta",                        3, 5.00),
    # ── Local (Ollama) ──
    "llama-3.2-8b":  ("ollama/llama3.2:8b",                   2, 0.00),
    "llama-3.2-3b":  ("ollama/llama3.2:3b",                   1, 0.00),
}

# Minimum capability for each tier
TIER_DEEP_MIN = 4       # playbooks, decisions, patterns — need strong model
TIER_CLASSIFY_MIN = 3   # session_type, themes, bugs — decent model OK
TIER_BUDGET_MIN = 1     # anything that runs

# Key → available models, sorted by capability (highest first)
_KEY_MODEL_MAP = {
    "ANTHROPIC_API_KEY": ["sonnet-4.6", "haiku-4.5"],
    "GEMINI_API_KEY":    ["gemini-3.1-pro", "gemini-3-flash", "gemini-3.1-flash-lite",
                          "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "OPENAI_API_KEY":    ["gpt-4o", "gpt-4o-mini"],
    "XAI_API_KEY":       ["grok-beta"],
    # Bedrock uses AWS credentials, not a single env var
}


def _detect_available_keys() -> dict:
    """Detect which API keys are available. Returns {key_name: True/False}."""
    keys = {}
    for env_var in ["ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"]:
        keys[env_var] = bool(os.environ.get(env_var))
    # Bedrock: check for AWS credentials
    try:
        import boto3
        session = boto3.session.Session()
        creds = session.get_credentials()
        keys["AWS_BEDROCK"] = creds is not None
    except Exception:
        keys["AWS_BEDROCK"] = False
    # Ollama: check if running
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as r:
            keys["OLLAMA"] = r.status == 200
    except Exception:
        keys["OLLAMA"] = False
    return keys


def _available_models(keys: dict) -> list:
    """Return list of (model_name, litellm_id, capability, cost) sorted by capability desc."""
    available = []
    for key_name, model_names in _KEY_MODEL_MAP.items():
        if keys.get(key_name):
            for name in model_names:
                litellm_id, cap, cost = MODELS[name]
                available.append((name, litellm_id, cap, cost))
    # Bedrock
    if keys.get("AWS_BEDROCK"):
        for name in ["nova-pro", "nova-lite", "nova-micro"]:
            litellm_id, cap, cost = MODELS[name]
            available.append((name, litellm_id, cap, cost))
    # Ollama
    if keys.get("OLLAMA"):
        for name in ["llama-3.2-8b", "llama-3.2-3b"]:
            litellm_id, cap, cost = MODELS[name]
            available.append((name, litellm_id, cap, cost))
    # Sort by capability descending, then cost ascending
    available.sort(key=lambda x: (-x[2], x[3]))
    return available


def select_models(cfg: dict) -> dict:
    """
    Select models for each tier based on available keys and config.
    Returns: {
        "deep": (litellm_id, capability, name),
        "classify": (litellm_id, capability, name),
        "warnings": [str],  — capability warnings for the user
    }
    """
    provider = cfg.get("model", {}).get("provider", "auto")
    keys = _detect_available_keys()
    warnings = []

    # If user explicitly set a provider, prefer models from that provider
    if provider != "auto":
        provider_key_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "google":    "GEMINI_API_KEY",
            "openai":    "OPENAI_API_KEY",
            "grok":      "XAI_API_KEY",
            "bedrock":   "AWS_BEDROCK",
            "ollama":    "OLLAMA",
        }
        required_key = provider_key_map.get(provider)
        if required_key and not keys.get(required_key):
            warnings.append(f"Provider '{provider}' configured but credentials not found")

    available = _available_models(keys)

    if not available:
        warnings.append("NO API keys detected — analysis will fail. Set at least one: ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY")
        return {
            "deep": ("ollama/llama3.2:3b", 1, "llama-3.2-3b"),
            "classify": ("ollama/llama3.2:3b", 1, "llama-3.2-3b"),
            "warnings": warnings,
        }

    # Pick the best model for deep extraction
    deep_candidates = [m for m in available if m[2] >= TIER_DEEP_MIN]
    if deep_candidates:
        deep = deep_candidates[0]  # highest capability
    else:
        deep = available[0]  # best available, even if below threshold
        warnings.append(
            f"Best available model '{deep[0]}' (capability {deep[2]}/5) is below recommended "
            f"threshold for deep extraction. Playbooks, architectural decisions, and effective "
            f"prompts may be lower quality. Add ANTHROPIC_API_KEY or GEMINI_API_KEY for better results."
        )

    # Pick cheapest STRONG model (cap≥4) for classify; fall back to cheapest adequate (cap≥3)
    strong_candidates = [m for m in available if m[2] >= TIER_DEEP_MIN]
    adequate_candidates = [m for m in available if m[2] >= TIER_CLASSIFY_MIN]
    if strong_candidates:
        # Cheapest strong model (cap≥4) — Flash, Haiku, 4o-mini tier
        classify = min(strong_candidates, key=lambda x: (x[3], -x[2]))
    elif adequate_candidates:
        # Fall back to cheapest adequate model (cap≥3)
        classify = min(adequate_candidates, key=lambda x: (x[3], -x[2]))
        warnings.append(
            f"Classify model '{classify[0]}' (capability {classify[2]}/5) is adequate but not strong. "
            f"Session types and themes may be less precise."
        )
    else:
        classify = available[-1]  # cheapest available, whatever it is
        warnings.append(
            f"Classification model '{classify[0]}' (capability {classify[2]}/5) may produce "
            f"inaccurate session_type and theme extraction."
        )

    # If only one key available and it maps to a weak model, warn
    active_keys = [k for k, v in keys.items() if v and k not in ("OLLAMA",)]
    if len(active_keys) == 1 and deep[2] < TIER_DEEP_MIN:
        key_name = active_keys[0]
        warnings.append(
            f"Only {key_name} available. For best results, also set ANTHROPIC_API_KEY "
            f"(Sonnet for deep extraction) or GEMINI_API_KEY (Gemini Pro as alternative)."
        )

    return {
        "deep": (deep[1], deep[2], deep[0]),
        "classify": (classify[1], classify[2], classify[0]),
        "warnings": warnings,
    }


def get_model_string(cfg: dict) -> str:
    """Legacy single-model selector — returns the best available model."""
    models = select_models(cfg)
    return models["deep"][0]


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: Deterministic pre-extraction (zero LLM cost, 100% accurate)
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_text_from_content(content) -> str:
    """Extract plain text from a message content field (string or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content) if content else ""


def phase1_extract(turns: list) -> dict:
    """
    Deterministic extraction from raw JSONL events.
    Returns tools_used (Counter), files_touched (set), commands_run (list),
    plus metadata for the condensed transcript builder.
    """
    tools_used = Counter()       # tool_name → count
    files_touched = set()        # unique file paths
    commands_run = []            # bash commands (deduplicated, max 50)
    commands_seen = set()
    user_turns = []              # (index, text) for transcript condenser
    assistant_summaries = []     # short assistant excerpts
    error_sequences = []         # turns involving errors/failures
    git_branch = ""
    cwd = ""

    for i, turn in enumerate(turns):
        event_type = turn.get("type", "")
        msg = turn.get("message", {})
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "") or turn.get("type", "")
        content = msg.get("content", "")

        # Capture git branch and working directory from event metadata
        if turn.get("gitBranch") and not git_branch:
            git_branch = turn["gitBranch"]
        if turn.get("cwd") and not cwd:
            cwd = turn["cwd"]

        # ── Extract user prompts (high signal) ──
        if event_type == "user" or role == "user":
            text = _extract_text_from_content(content)
            if text and len(text.strip()) > 10:
                user_turns.append((i, text.strip()))

        # ── Extract tool_use blocks from assistant content ──
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue

                if block.get("type") == "tool_use":
                    name = block.get("name", "unknown")
                    tools_used[name] += 1
                    inp = block.get("input", {})

                    if isinstance(inp, dict):
                        # Extract file paths from tool inputs
                        for key in ("file_path", "path", "file"):
                            val = inp.get(key, "")
                            if isinstance(val, str) and "/" in val and len(val) < 300:
                                # Filter out noise: only keep real file paths
                                if not val.startswith("http") and not val.startswith("<"):
                                    files_touched.add(val)

                        # Extract glob patterns
                        if "pattern" in inp and name in ("Glob", "Grep"):
                            pass  # patterns aren't files

                        # Extract bash commands
                        if "command" in inp and name == "Bash":
                            cmd = inp["command"].strip()
                            if cmd and cmd not in commands_seen and len(cmd) < 500:
                                commands_seen.add(cmd)
                                commands_run.append(cmd)

                elif block.get("type") == "text":
                    text = block.get("text", "")
                    # Detect error sequences
                    if any(kw in text.lower() for kw in
                           ["error", "failed", "traceback", "exception",
                            "bug", "fix", "broken", "crash"]):
                        error_sequences.append((i, text[:300]))

        # ── Also check string content for error keywords (assistant prose) ──
        elif isinstance(content, str) and (role == "assistant" or event_type == "assistant"):
            if len(content) > 50:
                assistant_summaries.append((i, content[:200]))

    return {
        "tools_used":          dict(tools_used.most_common(30)),
        "files_touched":       sorted(files_touched)[:100],
        "commands_run":        commands_run[:50],
        "user_turns":          user_turns,
        "assistant_summaries": assistant_summaries,
        "error_sequences":     error_sequences,
        "git_branch":          git_branch,
        "cwd":                 cwd,
        "total_events":        len(turns),
        "user_turn_count":     len(user_turns),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSCRIPT CONDENSER: Build a "highlight reel" for Phase 2
# ═══════════════════════════════════════════════════════════════════════════════

def condense_transcript(phase1: dict, max_tokens: int = 12000) -> str:
    """
    Build a condensed transcript focused on high-signal content:
    1. ALL user prompts (these show intent, quality, and patterns)
    2. Key error sequences (show debugging patterns)
    3. Tool usage summary (already extracted — just reference it)

    Target: fit within max_tokens (~48K chars) so we can send it in ONE LLM call.
    """
    sections = []
    char_budget = max_tokens * 4  # ~4 chars per token

    # ── Section 1: User prompts (highest signal) ──
    user_turns = phase1.get("user_turns", [])
    if user_turns:
        sections.append("=== USER PROMPTS (chronological) ===")
        prompt_budget = int(char_budget * 0.6)  # 60% of budget for user prompts
        used = 0
        for idx, (turn_idx, text) in enumerate(user_turns):
            # Truncate individual prompts but keep them meaningful
            truncated = text[:800] if len(text) > 800 else text
            # Strip uploaded file XML noise
            truncated = re.sub(r'<uploaded_files>.*?</uploaded_files>', '[uploaded files]',
                               truncated, flags=re.DOTALL)
            truncated = re.sub(r'<file_content>.*?</file_content>', '[file content]',
                               truncated, flags=re.DOTALL)
            entry = f"[Turn {turn_idx}] {truncated}"
            if used + len(entry) > prompt_budget:
                sections.append(f"... ({len(user_turns) - idx} more user turns truncated)")
                break
            sections.append(entry)
            used += len(entry)

    # ── Section 2: Error/debugging sequences (high signal) ──
    errors = phase1.get("error_sequences", [])
    if errors:
        sections.append("\n=== ERROR/DEBUGGING SEQUENCES ===")
        error_budget = int(char_budget * 0.2)
        used = 0
        for turn_idx, text in errors[:15]:  # max 15 error snippets
            entry = f"[Turn {turn_idx}] {text[:200]}"
            if used + len(entry) > error_budget:
                break
            sections.append(entry)
            used += len(entry)

    # ── Section 3: Session metadata context ──
    sections.append("\n=== SESSION CONTEXT ===")
    sections.append(f"Working directory: {phase1.get('cwd', 'unknown')}")
    sections.append(f"Git branch: {phase1.get('git_branch', 'unknown')}")
    sections.append(f"Total events: {phase1.get('total_events', 0)}")
    sections.append(f"User turns: {phase1.get('user_turn_count', 0)}")

    return "\n".join(sections)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: LLM semantic extraction
# ═══════════════════════════════════════════════════════════════════════════════

def _format_metadata_for_prompt(phase1: dict) -> str:
    """Format Phase 1 results as structured text for the LLM prompt."""
    lines = []
    lines.append(f"Project: {phase1.get('cwd', 'unknown')}")
    lines.append(f"Git branch: {phase1.get('git_branch', 'unknown')}")
    lines.append(f"Total events: {phase1.get('total_events', 0)}")
    lines.append(f"User turns: {phase1.get('user_turn_count', 0)}")

    tools = phase1.get("tools_used", {})
    if tools:
        tool_str = ", ".join(f"{name}({count})" for name, count in
                             sorted(tools.items(), key=lambda x: -x[1])[:15])
        lines.append(f"Tools used: {tool_str}")

    files = phase1.get("files_touched", [])
    if files:
        # Group by directory for readability
        lines.append(f"Files touched ({len(files)} total): {', '.join(files[:30])}")

    cmds = phase1.get("commands_run", [])
    if cmds:
        cmd_summary = "; ".join(c[:80] for c in cmds[:15])
        lines.append(f"Commands run ({len(cmds)} total): {cmd_summary}")

    return "\n".join(lines)


def _llm_call(model: str, prompt_text: str) -> tuple:
    """
    Single LLM call with retry on rate limit. Returns (parsed_dict, tokens_used).
    """
    from litellm import completion

    resp = None
    total_tokens = 0

    for attempt in range(3):
        try:
            resp = completion(
                model=model,
                messages=[{"role": "user", "content": prompt_text}],
                response_format={"type": "json_object"},
                timeout=180,
            )
            break
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "RateLimitError" in type(e).__name__:
                wait = 15 * (2 ** attempt)  # 15s, 30s, 60s
                print(f"[kernora] rate limit hit, waiting {wait}s (attempt {attempt+1}/3)...")
                time.sleep(wait)
                if attempt == 2:
                    print(f"[kernora] analyzer error: {e}")
                    return {}, 0
            else:
                print(f"[kernora] analyzer error: {e}")
                return {}, 0

    if resp is None:
        return {}, 0

    try:
        total_tokens = (
            getattr(resp.usage, "prompt_tokens", 0) +
            getattr(resp.usage, "completion_tokens", 0)
        )
        text = resp.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
        # Extract JSON object
        m = re.search(r'\{.*\}', text, re.DOTALL)
        parsed_text = m.group(0) if m else text
        return json.loads(parsed_text), total_tokens
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"[kernora] JSON parse error: {e}")
        return {}, total_tokens


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def analyze(session: dict) -> dict:
    """
    Two-phase analysis pipeline:
    Phase 1: Deterministic extraction (tools, files, commands) — zero LLM cost
    Phase 2: LLM semantic extraction — uses tiered model selection:
             Deep model (Sonnet/Gemini Pro) for semantic fields,
             with fallback to classify model (Haiku/Flash) if deep fails.
    Merge: Combine both phases into a single insight record.
    """
    cfg = load_config()
    models = select_models(cfg)
    deep_model, deep_cap, deep_name = models["deep"]
    classify_model, classify_cap, classify_name = models["classify"]

    for w in models.get("warnings", []):
        print(f"[kernora] ⚠ {w}")

    turns = json.loads(session.get("turns_json", "[]"))

    if not turns:
        return _empty_result(deep_model)

    # ── Phase 1: Deterministic extraction ──────────────────────────────────
    print(f"[kernora] Phase 1: extracting metadata from {len(turns)} events...")
    phase1 = phase1_extract(turns)
    print(f"[kernora]   tools: {len(phase1['tools_used'])} unique, "
          f"files: {len(phase1['files_touched'])}, "
          f"commands: {len(phase1['commands_run'])}, "
          f"user turns: {phase1['user_turn_count']}")

    # ── Condense transcript ────────────────────────────────────────────────
    condensed = condense_transcript(phase1)
    metadata_text = _format_metadata_for_prompt(phase1)

    # ── Phase 2: LLM semantic extraction ──────────────────────────────────
    # Use deep model (best available). If it fails, fall back to classify model.
    prompt_text = PROMPT.format(metadata=metadata_text, transcript=condensed)

    # Check if condensed transcript fits in a single call
    estimated_tokens = len(prompt_text) // 4
    if estimated_tokens > 30000:
        print(f"[kernora]   condensed transcript too large ({estimated_tokens} est. tokens), truncating...")
        condensed = condensed[:80000]  # ~20K tokens
        prompt_text = PROMPT.format(metadata=metadata_text, transcript=condensed)

    print(f"[kernora] Phase 2: deep extraction with {deep_name} (capability {deep_cap}/5)...")
    llm_result, token_cost = _llm_call(deep_model, prompt_text)

    # Fallback: if deep model failed AND we have a different classify model, try that
    if not llm_result and classify_model != deep_model:
        print(f"[kernora]   deep model failed — falling back to {classify_name} (capability {classify_cap}/5)...")
        llm_result, fallback_cost = _llm_call(classify_model, prompt_text)
        token_cost += fallback_cost
        if llm_result:
            # Flag that results came from a lower-tier model
            llm_result["_model_degraded"] = True

    model_used = deep_model  # for metadata reporting
    if not llm_result:
        print("[kernora]   all LLM calls failed — returning Phase 1 results only")
        return _phase1_only_result(phase1, model_used, token_cost)

    # ── Merge Phase 1 + Phase 2 ──────────────────────────────────────────
    return {
        # Phase 2 (LLM semantic extraction)
        "session_type":            llm_result.get("session_type", ""),
        "workflow_stage":          llm_result.get("workflow_stage", ""),
        "summary":                 llm_result.get("summary", ""),
        "themes":                  llm_result.get("themes", []),
        "bugs":                    llm_result.get("bugs", []),
        "optimizations":           llm_result.get("optimizations", []),
        "playbook":                llm_result.get("playbook", ""),
        "architectural_decisions": llm_result.get("architectural_decisions", []),
        "effective_prompts":       llm_result.get("effective_prompts", []),
        "anti_patterns":           llm_result.get("anti_patterns", []),
        "claude_md_rules":         llm_result.get("claude_md_rules", []),
        "knowledge_domains":       llm_result.get("knowledge_domains", []),
        "reusable_patterns":       llm_result.get("reusable_patterns", []),
        "prompt_quality":          float(llm_result.get("prompt_quality", 0)),
        "prompt_avg_words":        int(llm_result.get("prompt_avg_words", 0)),
        "repetition_count":        int(llm_result.get("repetition_count", 0)),
        "skill_opportunity":       _best_rule(llm_result.get("claude_md_rules", [])),
        # Phase 1 (deterministic — overrides any LLM guesses)
        "tools_used":              phase1["tools_used"],
        "files_touched":           phase1["files_touched"],
        "commands_run":            phase1["commands_run"],
        # Meta
        "token_cost":              token_cost,
        "model_used":              f"{deep_name}(cap={deep_cap})" + (" [degraded]" if llm_result.get("_model_degraded") else ""),
    }


def _best_rule(rules: list) -> str:
    """Pick the single best CLAUDE.md rule from the list (for backward compat)."""
    if not rules:
        return ""
    # Prefer longer, more specific rules
    return max(rules, key=lambda r: len(r) if isinstance(r, str) else 0)


def _empty_result(model: str) -> dict:
    """Return structure for empty/short sessions."""
    return {
        "session_type": "", "workflow_stage": "", "summary": "Empty session.",
        "themes": [], "bugs": [], "optimizations": [],
        "playbook": "", "architectural_decisions": [], "effective_prompts": [],
        "anti_patterns": [], "claude_md_rules": [], "knowledge_domains": [],
        "reusable_patterns": [],
        "prompt_quality": 0.0, "prompt_avg_words": 0, "repetition_count": 0,
        "skill_opportunity": "",
        "tools_used": {}, "files_touched": [], "commands_run": [],
        "token_cost": 0, "model_used": model,
    }


def _phase1_only_result(phase1: dict, model: str, token_cost: int) -> dict:
    """Fallback when LLM fails — return Phase 1 data with empty semantic fields."""
    result = _empty_result(model)
    result["tools_used"] = phase1["tools_used"]
    result["files_touched"] = phase1["files_touched"]
    result["commands_run"] = phase1["commands_run"]
    result["summary"] = f"Phase 1 only: {phase1['user_turn_count']} user turns, {len(phase1['tools_used'])} tools used."
    result["token_cost"] = token_cost
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY COMPAT: keep old functions available for any external callers
# ═══════════════════════════════════════════════════════════════════════════════

def format_turns(turns: list) -> str:
    """Legacy — kept for backward compatibility."""
    lines = []
    for t in turns:
        role = t.get("role", "")
        msg = t.get("message", {})
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if content:
            lines.append(f"{role}: {content[:800]}")
    return "\n\n".join(lines) or "(empty session)"


def chunk_transcript(turns: list, max_tokens: int = 8000) -> list:
    """Legacy — kept for backward compatibility."""
    chunks, current, count = [], [], 0
    for t in turns:
        msg = t.get("message", {})
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        text = f"{t.get('role', '')}: {content}"
        toks = max(1, len(text) // 4)
        if count + toks > max_tokens and current:
            chunks.append("\n\n".join(current))
            current, count = [], 0
        current.append(text)
        count += toks
    if current:
        chunks.append("\n\n".join(current))
    return chunks or ["(empty session)"]
