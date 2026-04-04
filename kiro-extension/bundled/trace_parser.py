# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
import json
import re

def parse_traces(turns_json: str) -> list[dict]:
    """Extract decision traces from session transcript.
    
    Args:
        turns_json: JSON string of turns array from sessions.turns_json
        
    Returns:
        List of trace dicts with keys: turn_index, ai_proposal, human_edit,
        delta_type, context. Empty list if < 2 turns or parse error.
    """
    try:
        turns = json.loads(turns_json) if isinstance(turns_json, str) else turns_json
    except (json.JSONDecodeError, TypeError):
        return []
    
    if not turns or len(turns) < 2:
        return []
    
    traces = []
    for i, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        role = turn.get("role", "")
        msg = turn.get("message", {})
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg) if msg else ""
        
        if not content:
            continue
            
        if role == "assistant" and i + 1 < len(turns):
            next_turn = turns[i + 1]
            if not isinstance(next_turn, dict):
                continue
            next_role = next_turn.get("role", "")
            if next_role != "human":
                continue
            next_msg = next_turn.get("message", {})
            next_content = (
                next_msg.get("content", "") if isinstance(next_msg, dict)
                else str(next_msg) if next_msg else ""
            )
            
            delta_type = _classify_delta(content, next_content)
            traces.append({
                "turn_index": i,
                "ai_proposal": content[:4000],  # cap storage size
                "human_edit": next_content[:4000] if next_content else None,
                "delta_type": delta_type,
                "context": None,
            })
    
    return traces


_ACCEPT_TOKENS = frozenset([
    "yes", "ok", "okay", "sure", "thanks", "thank you", "lgtm",
    "looks good", "perfect", "great", "nice", "good", "done",
    "approved", "ship it", "merge it", "go ahead",
])

_QUESTION_PATTERNS = re.compile(
    r'\?$|^(can you|could you|what about|how do|why not|what if|should)',
    re.IGNORECASE | re.MULTILINE
)


def _classify_delta(ai_content: str, human_content: str) -> str:
    """Classify the delta between AI proposal and human response.
    
    Returns one of: 'accepted', 'modified', 'rejected', 'escalated'.
    
    V1 heuristic — keyword overlap threshold (0.3) is approximate. TODO: Replace with LLM-based classification when IDE LLM bridge is reliable.
    """
    if not human_content or not human_content.strip():
        return "accepted"
    
    human_lower = re.sub(r'[^\w\s]', '', human_content.strip().lower())
    
    # Short affirmative responses
    if len(human_lower) < 50 and human_lower in _ACCEPT_TOKENS:
        return "accepted"
    
    # Question → escalated
    if _QUESTION_PATTERNS.search(human_content):
        return "escalated"
    
    # Compute keyword overlap to distinguish modified vs rejected
    ai_words = set(re.findall(r'\b\w{3,}\b', ai_content.lower()))
    human_words = set(re.findall(r'\b\w{3,}\b', human_lower))
    
    if not ai_words:
        return "modified"
    
    overlap = len(ai_words & human_words) / len(ai_words)
    
    # V1 threshold — calibrate with real user data
    if overlap > 0.3:
        return "modified"
    else:
        return "rejected"
