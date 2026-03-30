# Claw Protocol

A claw is a lightweight adapter that captures transcripts from a specific AI coding agent and sends them to Nora for analysis. This document describes the protocol.

## Overview

Every AI coding agent stores session transcripts somewhere — Claude Code uses JSONL files, Cursor uses SQLite, Kiro uses its own format. A claw's job is simple: read that format and pipe it to Nora. That's it. No analysis logic, no model calls, no storage.

## Transport

Nora listens on a Unix domain socket:

```
~/.kernora/nora.sock
```

Send a JSON envelope over the socket. Nora acknowledges with `{"ok": true}` or `{"error": "reason"}`.

## Envelope format

```json
{
  "version": 1,
  "agent": "claude-code",
  "session_id": "unique-session-identifier",
  "project": "/absolute/path/to/project",
  "started_at": "2026-03-29T10:00:00Z",
  "ended_at": "2026-03-29T11:30:00Z",
  "model": "claude-sonnet-4-6",
  "turns": [
    {
      "role": "user",
      "content": "Fix the authentication middleware"
    },
    {
      "role": "assistant",
      "content": "I'll look at the middleware...",
      "tool_uses": [
        {
          "name": "Read",
          "input": {"file_path": "/src/middleware/auth.ts"}
        }
      ]
    }
  ],
  "metadata": {
    "git_branch": "fix/auth-middleware",
    "tokens_in": 12500,
    "tokens_out": 8400
  }
}
```

### Required fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | int | Protocol version. Currently `1`. |
| `agent` | string | Agent identifier. Use lowercase-hyphenated: `claude-code`, `kiro`, `cursor`, `windsurf`. |
| `session_id` | string | Unique session ID. Use the agent's native session ID if available. |
| `project` | string | Absolute path to the project directory. |
| `turns` | array | Array of turn objects (see below). |

### Optional fields

| Field | Type | Description |
|-------|------|-------------|
| `started_at` | string | ISO-8601 timestamp. |
| `ended_at` | string | ISO-8601 timestamp. |
| `model` | string | Primary model used in the session. |
| `metadata` | object | Agent-specific metadata. Nora stores but doesn't require specific keys. |

### Turn format

Each turn has:

| Field | Type | Description |
|-------|------|-------------|
| `role` | string | `"user"` or `"assistant"` |
| `content` | string or array | The message content. String for simple text. Array of content blocks for tool use. |
| `tool_uses` | array | Optional. Tools invoked in this turn. |

Nora's Phase 1 extractor understands tool use blocks from Claude Code's native format. If your agent uses a different format, convert to the above. If conversion is hard, send raw content as a string — Nora's Phase 2 (LLM) will still extract useful signal.

## Lifecycle

1. **Agent session ends** → your claw detects this (file watcher, hook, event listener)
2. **Claw reads transcript** from the agent's native storage
3. **Claw converts** to the envelope format above
4. **Claw sends** over Unix socket to `~/.kernora/nora.sock`
5. **Nora acknowledges** with `{"ok": true, "queued": true}`
6. **Nora analyzes asynchronously** — the claw doesn't wait

## Example: minimal Python claw

```python
import json
import socket

def send_to_nora(session: dict):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(Path.home() / ".kernora" / "nora.sock"))
    sock.sendall(json.dumps(session).encode() + b"\n")
    response = sock.recv(1024)
    sock.close()
    return json.loads(response)
```

## Naming convention

Claws are named `{agent}-claw`: `claude-claw`, `kiro-claw`, `cursor-claw`, `windsurf-claw`. The agent name should match the `agent` field in the envelope.

## Testing

Send a test envelope to verify your claw works:

```python
import json
import socket
from pathlib import Path

test_envelope = {
    "version": 1,
    "agent": "my-agent",
    "session_id": "test-001",
    "project": "/tmp/test-project",
    "turns": [
        {"role": "user", "content": "Test prompt"},
        {"role": "assistant", "content": "Test response"}
    ]
}

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect(str(Path.home() / ".kernora" / "nora.sock"))
sock.sendall(json.dumps(test_envelope).encode() + b"\n")
response = json.loads(sock.recv(1024))
print(response)  # {"ok": true, "queued": true}
sock.close()
```

Then check the dashboard at `localhost:2742` — your test session should appear within 60 seconds.

## Hooks

Claws capture transcripts. Hooks extend agent behavior in real-time. If your agent supports lifecycle hooks (like Kiro's 5 hooks or Claude Code's 2 hooks), see [docs/HOOKS.md](HOOKS.md) for the full reference.

---

Questions? Open an issue on [kernora-ai/nora](https://github.com/kernora-ai/nora/issues) or email hello@kernora.ai.
