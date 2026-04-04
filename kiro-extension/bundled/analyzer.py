#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
"""
Analysis layer.
Uses LiteLLM (MIT license) to support:
  - Anthropic Haiku (user's ANTHROPIC_API_KEY)
  - AWS Bedrock Nova Lite / Nova Micro / Nova Pro (user's AWS profile)
  - Ollama local models (localhost:11434)

User supplies credentials. Kernora never sees API keys or transcripts.
"""
import json
import os
import sys
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

PROMPT = """You are Nora, an AI work intelligence analyst for Kernora.
Analyze this AI coding session transcript.
Return ONLY valid JSON — no markdown, no prose, no explanation outside JSON.

Required format:
{{
  "themes": [{{"label": "string", "severity": "high|medium|low", "count": 1}}],
  "bugs": [{{"title": "string", "severity": "high|medium|low", "error_signature": "string or empty", "file_path": "string or empty", "fix_code": "string or empty"}}],
  "optimizations": [{{"title": "string", "impact": "high|medium|low", "suggestion": "string"}}],
  "prompt_quality": 0.0,
  "prompt_avg_words": 0,
  "repetition_count": 0,
  "skill_opportunity": "one CLAUDE.md rule sentence, or empty string",
  "summary": "2-sentence plain English summary of this session",
  "prompt_coaching": "string",
  "prompt_antipatterns": ["string"],
  "tokens_estimated": 0,
  "session_type": "string",
  "playbook": "string",
  "architectural_decisions": [{{"decision": "string", "rationale": "string", "alternatives": ["string"], "files": ["string"], "context": "string"}}],
  "anti_patterns": ["string"],
  "claude_md_rules": ["string"],
  "knowledge_domains": ["string"],
  "reusable_patterns": [{{"name": "string", "pattern": "string", "code_example": "string", "domains": ["string"], "context": "string"}}],
  "agent_workflow_rules": [{{"trigger": "string", "instruction": "string"}}],
  "files_touched": ["string"],
  "tools_used": ["string"]
}}

Rules:
- prompt_quality: 0.0-1.0 (1.0 = precise, detailed, contextual prompts)
- prompt_avg_words: average words per user turn
- repetition_count: how many turns repeated a concept from a previous turn (estimate)
- skill_opportunity: the single most valuable rule to add to CLAUDE.md
- If session is empty or too short: return all empty arrays, quality 0.0, summary "Empty session."

Session transcript:
{transcript}"""


def load_config() -> dict:
    if CONFIG_PATH.exists() and tomllib is not None:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    return {
        "model": {"provider": "anthropic"},
        "bedrock": {"region": "us-east-1", "model": "amazon.nova-lite-v1:0"},
    }


def get_model_string(cfg: dict) -> str:
    provider = cfg.get("model", {}).get("provider", "anthropic")
    if provider == "anthropic":
        return "anthropic/claude-haiku-4-5-20251001"
    if provider == "bedrock":
        model = cfg.get("bedrock", {}).get("model", "amazon.nova-lite-v1:0")
        return f"bedrock/{model}"
    if provider == "ollama":
        return "ollama/llama3.2:3b"
    if provider == "google":
        model = cfg.get("google", {}).get("model", "gemini-2.5-pro")
        return f"gemini/{model}"
    if provider == "grok":
        model = cfg.get("grok", {}).get("model", "grok-beta")
        return f"xai/{model}"
    if provider == "openai":
        model = cfg.get("openai", {}).get("model", "gpt-4o-mini")
        return f"openai/{model}"
    # auto: try in order
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic/claude-haiku-4-5-20251001"
    if os.environ.get("GEMINI_API_KEY"):
        return f"gemini/{cfg.get('google', {}).get('model', 'gemini-2.5-pro')}"
    if os.environ.get("OPENAI_API_KEY"):
        return f"openai/{cfg.get('openai', {}).get('model', 'gpt-4o')}"
    if os.environ.get("XAI_API_KEY"):
        return f"xai/{cfg.get('grok', {}).get('model', 'grok-beta')}"
    try:
        import boto3
        boto3.client("bedrock-runtime", region_name="us-east-1")
        return f"bedrock/{cfg.get('bedrock', {}).get('model', 'amazon.nova-lite-v1:0')}"
    except Exception:
        pass
    return "ollama/llama3.2:3b"


def format_turns(turns: list) -> str:
    lines = []
    for t in turns:
        role = t.get("role", "")
        msg  = t.get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content", "")
        else:
            content = str(msg)
        if content:
            lines.append(f"{role}: {content[:800]}")
    return "\n\n".join(lines) or "(empty session)"


def chunk_transcript(turns: list, max_tokens: int = 3000) -> list:
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


def analyze(session: dict) -> dict:
    from litellm import completion

    cfg   = load_config()
    model = get_model_string(cfg)

    turns  = json.loads(session.get("turns_json", "[]"))
    chunks = chunk_transcript(turns)

    all_themes, all_bugs, all_opts = [], [], []
    rules, summaries = [], []
    prompt_coachings, session_types, playbooks = [], [], []
    all_prompt_antipatterns, all_architectural_decisions, all_anti_patterns = [], [], []
    all_claude_md_rules, all_knowledge_domains, all_reusable_patterns = [], [], []
    all_files_touched, all_tools_used, all_agent_workflow_rules = [], [], []
    total_tokens = 0
    estimated_tokens_list = []
    qualities, word_counts, repetitions = [], [], []

    for chunk in chunks:
        try:
            resp = completion(
                model=model,
                messages=[{
                    "role": "user",
                    "content": PROMPT.format(transcript=chunk)
                }],
                response_format={"type": "json_object"},
                timeout=120,
            )
            total_tokens += (
                getattr(resp.usage, "prompt_tokens", 0) +
                getattr(resp.usage, "completion_tokens", 0)
            )
            text = resp.choices[0].message.content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
                
            import re
            m = re.search(r'\{.*\}', text, re.DOTALL)
            parsed_text = m.group(0) if m else text
            
            d = json.loads(parsed_text)
            all_themes += d.get("themes", [])
            all_bugs   += d.get("bugs", [])
            all_opts   += d.get("optimizations", [])
            all_prompt_antipatterns += d.get("prompt_antipatterns", [])
            all_architectural_decisions += d.get("architectural_decisions", [])
            all_anti_patterns += d.get("anti_patterns", [])
            all_claude_md_rules += d.get("claude_md_rules", [])
            all_knowledge_domains += d.get("knowledge_domains", [])
            all_reusable_patterns += d.get("reusable_patterns", [])
            all_files_touched += d.get("files_touched", [])
            all_tools_used += d.get("tools_used", [])
            all_agent_workflow_rules += d.get("agent_workflow_rules", [])
            
            if d.get("skill_opportunity"): rules.append(d["skill_opportunity"])
            if d.get("summary"): summaries.append(d["summary"])
            if d.get("prompt_coaching"): prompt_coachings.append(d["prompt_coaching"])
            if d.get("session_type"): session_types.append(d["session_type"])
            if d.get("playbook"): playbooks.append(d["playbook"])
            
            if d.get("prompt_quality") is not None: qualities.append(float(d["prompt_quality"]))
            if d.get("prompt_avg_words") is not None: word_counts.append(int(d["prompt_avg_words"]))
            if d.get("repetition_count") is not None: repetitions.append(int(d["repetition_count"]))
            if d.get("tokens_estimated") is not None: estimated_tokens_list.append(int(d["tokens_estimated"]))
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"[kernora] analyzer error on chunk: {e}")

    return {
        "themes":            all_themes,
        "bugs":              all_bugs,
        "optimizations":     all_opts,
        "prompt_quality":    round(sum(qualities) / len(qualities), 2) if qualities else 0.0,
        "prompt_avg_words":  int(sum(word_counts) / len(word_counts)) if word_counts else 0,
        "repetition_count":  max(repetitions) if repetitions else 0,
        "skill_opportunity": rules[0] if rules else "",
        "summary":           summaries[0] if summaries else "",
        "token_cost":        total_tokens,
        "prompt_coaching":   prompt_coachings[0] if prompt_coachings else "",
        "prompt_antipatterns": all_prompt_antipatterns,
        "tokens_estimated":  sum(estimated_tokens_list),
        "session_type":      session_types[0] if session_types else "",
        "playbook":          playbooks[0] if playbooks else "",
        "architectural_decisions": all_architectural_decisions,
        "anti_patterns":     all_anti_patterns,
        "claude_md_rules":   all_claude_md_rules,
        "knowledge_domains": all_knowledge_domains,
        "reusable_patterns": all_reusable_patterns,
        "files_touched":     list(set(all_files_touched)),
        "tools_used":        list(set(all_tools_used)),
        "agent_workflow_rules": all_agent_workflow_rules,
        "model_used":        model,
    }


def queue_ide_jobs(session: dict):
    from db import queue_inference_job
    turns  = json.loads(session.get("turns_json", "[]"))
    chunks = chunk_transcript(turns)
    for chunk in chunks:
        prompt_text = PROMPT.format(transcript=chunk)
        queue_inference_job(session["id"], prompt_text)


def finalize_ide_analysis(session: dict, jobs: list) -> dict:
    all_themes, all_bugs, all_opts = [], [], []
    rules, summaries = [], []
    prompt_coachings, session_types, playbooks = [], [], []
    all_prompt_antipatterns, all_architectural_decisions, all_anti_patterns = [], [], []
    all_claude_md_rules, all_knowledge_domains, all_reusable_patterns = [], [], []
    all_files_touched, all_tools_used = [], []
    estimated_tokens_list = []
    total_tokens = 0
    qualities, word_counts, repetitions = [], [], []

    for job in jobs:
        text = job.get("response", "")
        if not text:
            continue
        try:
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            
            import re
            m = re.search(r'\{.*\}', text, re.DOTALL)
            parsed_text = m.group(0) if m else text
            
            d = json.loads(parsed_text)
            all_themes += d.get("themes", [])
            all_bugs   += d.get("bugs", [])
            all_opts   += d.get("optimizations", [])
            all_prompt_antipatterns += d.get("prompt_antipatterns", [])
            all_architectural_decisions += d.get("architectural_decisions", [])
            all_anti_patterns += d.get("anti_patterns", [])
            all_claude_md_rules += d.get("claude_md_rules", [])
            all_knowledge_domains += d.get("knowledge_domains", [])
            all_reusable_patterns += d.get("reusable_patterns", [])
            all_files_touched += d.get("files_touched", [])
            all_tools_used += d.get("tools_used", [])
            
            if d.get("skill_opportunity"): rules.append(d["skill_opportunity"])
            if d.get("summary"): summaries.append(d["summary"])
            if d.get("prompt_coaching"): prompt_coachings.append(d["prompt_coaching"])
            if d.get("session_type"): session_types.append(d["session_type"])
            if d.get("playbook"): playbooks.append(d["playbook"])
            
            if d.get("prompt_quality") is not None: qualities.append(float(d["prompt_quality"]))
            if d.get("prompt_avg_words") is not None: word_counts.append(int(d["prompt_avg_words"]))
            if d.get("repetition_count") is not None: repetitions.append(int(d["repetition_count"]))
            if d.get("tokens_estimated") is not None: estimated_tokens_list.append(int(d["tokens_estimated"]))
            
            total_tokens += len(job.get("prompt", "")) // 4 + len(text) // 4
        except Exception as e:
            print(f"[analyzer] finalize_ide_analysis failed to parse JSON chunk for session {session.get('id', '?')[:8]}: {e}")

    return {
        "themes":            all_themes,
        "bugs":              all_bugs,
        "optimizations":     all_opts,
        "prompt_quality":    round(sum(qualities) / len(qualities), 2) if qualities else 0.0,
        "prompt_avg_words":  int(sum(word_counts) / len(word_counts)) if word_counts else 0,
        "repetition_count":  max(repetitions) if repetitions else 0,
        "skill_opportunity": rules[0] if rules else "",
        "summary":           summaries[0] if summaries else "",
        "token_cost":        total_tokens,
        "prompt_coaching":   prompt_coachings[0] if prompt_coachings else "",
        "prompt_antipatterns": all_prompt_antipatterns,
        "tokens_estimated":  sum(estimated_tokens_list),
        "session_type":      session_types[0] if session_types else "",
        "playbook":          playbooks[0] if playbooks else "",
        "architectural_decisions": all_architectural_decisions,
        "anti_patterns":     all_anti_patterns,
        "claude_md_rules":   all_claude_md_rules,
        "knowledge_domains": all_knowledge_domains,
        "reusable_patterns": all_reusable_patterns,
        "files_touched":     list(set(all_files_touched)),
        "tools_used":        list(set(all_tools_used)),
        "model_used":        "ide/provided",
    }
