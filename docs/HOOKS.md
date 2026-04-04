# Nora Hooks Reference

**See also**: [README.md](../README.md) for project overview.

Nora integrates with AI coding agents (Kiro and Claude Code) via a hook system. Hooks are executable scripts that fire at key lifecycle events, enabling Nora to:
- Inject learned context into agent prompts
- Validate tool usage against known anti-patterns
- Capture session data for analysis
- Generate steering files that improve agent decision-making over time

---

## Hook Overview

| Hook | Agent(s) | When It Fires | Purpose | Blocking |
|------|----------|--------------|---------|----------|
| `agentSpawn` | Kiro only | Agent starts session | Health check, report stats, freshen steering files | No |
| `userPromptSubmit` | Kiro, Claude Code | User submits a prompt | Search past sessions for relevant context | No |
| `preToolUse` | Kiro only | Before any tool executes | Check input against known anti-patterns | **Yes** |
| `postToolUse` | Kiro only | After a tool completes | Check output for error signatures, log metrics | No |
| `stop` | Kiro, Claude Code | Session ends | Capture transcript for daemon analysis | No |

---

## Kiro Hooks (5)

### 1. agentSpawn

**When**: Kiro agent starts a new session (before first user prompt).

**Purpose**: Initialize Nora state, verify daemon health, report session stats, ensure steering files are fresh.

**File location**: `~/.kiro/hooks/nora_spawn.py`

**Input (JSON on stdin)**:
```json
{
  "hook": "agentSpawn",
  "session_id": "sess_abc123def456",
  "agent": "kiro",
  "timestamp": "2026-03-29T14:35:22Z"
}
```

**Expected behavior**:
1. Verify daemon is healthy (test socket connection to `~/.nora/daemon.sock`)
2. Log session start to local SQLite (nora.db)
3. Read session stats from past 30 days (count, success rate, avg duration)
4. Print session summary to stdout (shown in agent output)
5. Check steering file mtimes — if >24h old, print warning to stderr
6. Exit 0 always (never block)

**Output format**:

stdout (shown to user):
```
[Nora] Session started. Context from 47 past sessions available.
Effective patterns: 12 flagged. Anti-patterns: 8 known.
Steering files last updated 3h ago.
```

stderr (warnings only):
```
[Nora] Warning: steering file nora-patterns.md is >24h old. Consider running analysis.
```

**Exit code**: Always 0.

**Timeout**: 5 seconds.

---

### 2. userPromptSubmit

**When**: User submits a prompt to the Kiro agent.

**Purpose**: Search FTS5 index of past session transcripts for semantically relevant context. Return ranked suggestions to help agent understand similar problems it has solved before.

**File location**: `~/.kiro/hooks/nora_context.py`

**Input (JSON on stdin)**:
```json
{
  "hook": "userPromptSubmit",
  "prompt": {
    "content": "Fix the auth middleware — it's rejecting valid tokens",
    "conversation_id": "conv_xyz789"
  },
  "session_id": "sess_abc123def456",
  "agent": "kiro",
  "timestamp": "2026-03-29T14:35:45Z"
}
```

**Expected behavior**:
1. Tokenize the prompt: extract keywords and semantic intent
2. Search FTS5 index (nora_fts table) for matching past sessions
3. Rank results by relevance score (TF-IDF or BM25)
4. For top 3 results, extract:
   - Session ID and date
   - Relevant code snippets or solutions
   - Any warnings or gotchas discovered in that session
5. Format as markdown, output to stdout
6. Exit 0 always

**Output format**:

stdout (injected into agent context):
```markdown
## Nora Context Suggestions

Found 3 relevant past sessions:

### Session #45 (2026-03-27) — "Fix JWT validation in middleware"
**Relevance**: 0.87

Your solution then:
- Verify token expiration check happens BEFORE signature validation
- Use explicit error messages in validation failure cases
- Add test coverage for expired tokens vs invalid signatures

Common gotcha you hit: JWT library silently accepts `null` algorithm — check `alg !== "none"` explicitly.

Code pattern:
\`\`\`typescript
function validateToken(token: string) {
  const decoded = jwt.verify(token, SECRET, { algorithms: ['HS256'] });
  if (!decoded.sub) throw new Error('Missing subject claim');
  return decoded;
}
\`\`\`

### Session #38 (2026-03-25) — "Token refresh loop bug"
**Relevance**: 0.71
...
```

stderr: (warnings only if context is partial)
```
[Nora] Context index is 2 days old. Add new sessions with recent fixes for better suggestions.
```

**Exit code**: Always 0.

**Timeout**: 3 seconds (hard cutoff — agent won't wait longer for context).

---

### 3. preToolUse

**When**: Kiro is about to execute ANY tool (Bash, Read, Write, Glob, etc.).

**Purpose**: Validate tool input against known dangerous anti-patterns and unsafe operations discovered in past sessions. Kiro will NOT execute the tool if Nora blocks it.

**File location**: `~/.kiro/hooks/nora_pretool.py`

**Input (JSON on stdin)**:
```json
{
  "hook": "preToolUse",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/src/auth.ts",
    "content": "const SECRET_KEY = 'hardcoded-api-key-123';"
  },
  "session_id": "sess_abc123def456",
  "timestamp": "2026-03-29T14:35:50Z"
}
```

**Expected behavior**:
1. Load anti-pattern rules from `nora-antipatterns.md` and hardcoded checks
2. Validate against rules:
   - **Write tool**: Check for hardcoded secrets, credentials, API keys
   - **Bash tool**: Check for destructive commands (rm -rf /, git reset --hard, etc.)
   - **All tools**: Check for deprecated/dangerous APIs from past sessions
3. If violation found:
   - Exit 2 (block)
   - Print violation description to stderr
   - Suggest safe alternative to stdout
4. If no violations:
   - Exit 0 (allow execution)
   - May print advisory warnings to stderr

**Output format**:

**If ALLOWED (Exit 0)**:

stdout: (optional advisory)
```
[Nora] Tool check passed. No known anti-patterns detected.
```

stderr: (optional warnings)
```
[Nora] Note: This Write operation touches auth.ts. Verify the credential is not hardcoded in the final code.
```

**If BLOCKED (Exit 2)**:

stderr (shown to user as error):
```
[Nora] BLOCKED: Write tool rejected.
Reason: File content contains hardcoded API key pattern.
Details: Line 1 matches /const.*SECRET.*=.*['\"].*[a-zA-Z0-9]{16,}['\"]/ (past anti-pattern from session #12)
Safe alternative: Use environment variable: process.env.SECRET_KEY
```

stdout: (suggest fix)
```
const SECRET_KEY = process.env.SECRET_KEY || '';
if (!SECRET_KEY) throw new Error('SECRET_KEY env var not set');
```

**Exit code**:
- 0 = allow execution
- 2 = block execution (Kiro will not run the tool and show the error to user)

**Timeout**: 2 seconds (agent has other tools to run).

**Anti-pattern checks** (non-exhaustive):
- Hardcoded secrets: API keys, JWT secrets, database passwords matching regex patterns
- Destructive Bash: `rm -rf /`, `sudo *`, `git reset --hard`, `dropdb`
- Deprecated APIs from steering files
- SQL injection patterns (unparametrized queries)
- Direct file path manipulation in security-sensitive code

---

### 4. postToolUse

**When**: A tool completes execution (Bash returns, Write succeeds, etc.).

**Purpose**: Observational only. Check output for known error signatures, log tool execution metrics, and flag if an error matches a pattern from past sessions.

**File location**: `~/.kiro/hooks/nora_posttool.py`

**Input (JSON on stdin)**:
```json
{
  "hook": "postToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "npm run test"
  },
  "tool_output": {
    "stdout": "FAIL src/__tests__/auth.test.ts",
    "stderr": "Error: Cannot find module './middleware'",
    "exit_code": 1
  },
  "session_id": "sess_abc123def456",
  "timestamp": "2026-03-29T14:35:55Z"
}
```

**Expected behavior**:
1. Parse tool output (stdout, stderr, exit_code)
2. Search nora.db for past sessions with similar error signatures
3. If match found (confidence >0.7):
   - Log the match and suggested fix to local DB
   - Print suggestion to stderr
4. Log tool metric to nora.db: (tool_name, exit_code, duration_est, error_class)
5. Exit 0 always (never block)

**Output format**:

stderr (advisory):
```
[Nora] Seen this error before (session #34, 2026-03-24).
Pattern: "Cannot find module" in tests after refactoring imports.
Fix then: Check barrel export in src/index.ts — middleware export was removed.
```

stdout: (optional context for agent)
```
[Nora] Tool metric logged. 23 Bash tools executed so far in session.
```

**Exit code**: Always 0.

**Timeout**: 1 second (non-blocking).

---

### 5. stop

**When**: Kiro session ends (user types exit, error occurs, timeout).

**Purpose**: Capture the full transcript and send it to the Nora daemon for analysis. The daemon will extract patterns, anti-patterns, and decisions — these feed back into steering file generation.

**File location**: `~/.kiro/hooks/nora_stop.py`

**Input (JSON on stdin)**:
```json
{
  "hook": "stop",
  "session_id": "sess_abc123def456",
  "agent": "kiro",
  "transcript_path": "/tmp/kiro/sess_abc123def456/transcript.jsonl",
  "duration_seconds": 847,
  "exit_code": 0,
  "timestamp": "2026-03-29T14:50:30Z"
}
```

**Expected behavior**:
1. Read transcript from `transcript_path` (JSONL format, one message per line)
2. Validate transcript is non-empty and well-formed
3. Send to daemon via socket (`~/.nora/daemon.sock`) with session metadata
4. Wait for daemon ACK (timeout 5 seconds)
5. Log session completion to nora.db
6. Clean up temporary files if desired
7. Exit 0

**Transcript format** (JSONL):
Each line is a JSON object representing one turn in the conversation:
```json
{"role": "user", "content": "Fix the auth bug", "timestamp": "2026-03-29T14:35:45Z"}
{"role": "assistant", "content": "I'll check the token validation...", "timestamp": "2026-03-29T14:35:50Z"}
{"tool": "Read", "path": "/src/auth.ts", "result": {...}, "timestamp": "2026-03-29T14:35:52Z"}
{"role": "assistant", "content": "Found the issue: JWT expiration check is after signature validation", "timestamp": "2026-03-29T14:36:10Z"}
```

**Output format**:

stdout: (optional confirmation)
```
[Nora] Session transcript captured (847 seconds, 23 turns).
Sending to daemon for analysis...
Daemon ACK received. Session data will be indexed.
```

stderr: (warnings if any):
```
[Nora] Warning: No anti-patterns detected. Steering file suggestions are minimal.
```

**Exit code**: Always 0.

**Timeout**: 5 seconds for daemon response (hook continues even if daemon slow).

**Async**: Hook does NOT wait for daemon analysis — it returns immediately after sending the transcript. The daemon processes in the background and updates steering files asynchronously.

---

## Claude Code Hooks (2)

Claude Code (Anthropic's official CLI for Claude) has a smaller hook set, focused on context injection and session capture.

### 1. UserPromptSubmit

**When**: User submits a prompt to Claude Code.

**Purpose**: Identical to Kiro's `userPromptSubmit`. Search past sessions for relevant context.

**File location**: `~/.claude/hooks/nora_context.py`

**Input (JSON on stdin)**:
```json
{
  "hook": "UserPromptSubmit",
  "prompt": {
    "content": "Add error handling to the API route"
  },
  "session_id": "claude_sess_xyz123",
  "timestamp": "2026-03-29T14:35:45Z"
}
```

**Behavior**: Same as Kiro's userPromptSubmit (see section above).

**Output**: Same markdown format.

**Exit code**: Always 0.

**Timeout**: 3 seconds.

---

### 2. Stop

**When**: Claude Code session ends.

**Purpose**: Capture transcript and send to daemon, same as Kiro's `stop` hook.

**File location**: `~/.claude/hooks/kernora_hook.py` (note: different filename for historical reasons)

**Input (JSON on stdin)**:
```json
{
  "hook": "Stop",
  "session_id": "claude_sess_xyz123",
  "transcript_path": "/tmp/claude/claude_sess_xyz123/messages.jsonl",
  "duration_seconds": 420,
  "exit_code": 0,
  "timestamp": "2026-03-29T14:50:30Z"
}
```

**Behavior**: Same as Kiro's `stop` hook.

**Output**: Same format.

**Exit code**: Always 0.

**Timeout**: 5 seconds.

---

## Shared Hook Contract

All hooks (Kiro and Claude Code) follow this contract:

### Input
- **Format**: JSON on stdin
- **Always includes**: `hook` (name), `session_id`, `timestamp`
- **Agent-specific**: May include `agent` field (Kiro) or agent-inferred from file paths (Claude Code)

### Output
- **stdout**: Content shown/injected into agent output (suggestions, confirmations, fixes)
- **stderr**: Warnings, errors, debug info shown to the user
- **No stdout/stderr**: Hook ran silently (observational only)

### Exit Codes
| Code | Meaning | When Used |
|------|---------|-----------|
| 0 | Success (allow operation) | All hooks |
| 1 | Error/block (Claude Code preToolUse) | Claude Code only |
| 2 | Error/block (Kiro preToolUse) | Kiro only |

### Network/Concurrency
- **NO network calls** (localhost sockets only, never HTTP)
- **NO external dependencies** (stdlib + SQLite only)
- **Thread-safe**: Nora daemon serializes writes to nora.db
- **Async-safe**: Hooks return immediately; daemon processes asynchronously

### Timeout Behavior
- **agentSpawn**: 5s timeout (if slow, warning printed but session continues)
- **userPromptSubmit**: 3s timeout (hard cutoff — if slow, no context injected)
- **preToolUse**: 2s timeout (if slow, default to allow execution)
- **postToolUse**: 1s timeout (observational, non-blocking)
- **stop**: 5s timeout for daemon ACK (hook doesn't wait for full analysis)

---

## Steering Files

After analyzing past sessions, the Nora daemon generates three markdown steering files in `.kiro/steering/` (Kiro reads these automatically, Claude Code hooks can optionally check them):

### nora-patterns.md
Effective patterns and playbooks from past sessions. Includes:
- Successful code patterns (error handling, auth, database queries)
- Architecture decisions that worked well
- Reusable code snippets (with session attribution)
- Performance optimizations discovered
- Testing strategies that caught bugs early

Kiro injects a summary into every agent prompt: "Reference patterns from X past sessions."

### nora-decisions.md
Architectural decisions and CLAUDE.md-style rules. Includes:
- Database schema decisions
- API design patterns
- Module organization rationale
- Security decisions (auth, encryption, credential handling)
- Caching strategies

Useful for explaining WHY code is structured a certain way.

### nora-antipatterns.md
Known anti-patterns, recurring bugs, and things to avoid. Includes:
- Common bugs (off-by-one in loops, race conditions, etc.)
- Unsafe patterns (hardcoded secrets, unparametrized queries)
- Design mistakes (overly complex abstractions, wrong data structures)
- Performance pitfalls
- Security vulnerabilities

The `preToolUse` hook checks against this file before allowing operations.

---

## Hook Implementation Checklist

When implementing a new hook:

- [ ] Hook reads JSON from stdin (use `json.loads()` or equiv.)
- [ ] Hook exits with correct code (0 for success, 2 for block in preToolUse)
- [ ] stdout is user-friendly markdown or plain text
- [ ] stderr includes `[Nora]` prefix for identification
- [ ] No external network calls (localhost socket to daemon only if needed)
- [ ] No dependencies outside stdlib + SQLite3
- [ ] Hook respects timeout (returns before timeout expires)
- [ ] Hook handles missing nora.db gracefully (if first run)
- [ ] Hook logs errors to stderr, not silently failing
- [ ] No sensitive data logged to stdout (credentials, tokens, etc.)

---

## Example: Full Hook Chain for Single Prompt

User types: `"Fix the JWT token validation — it's rejecting valid tokens"`

1. **agentSpawn** fires (session start)
   - Nora verifies daemon health ✓
   - Prints session summary

2. **userPromptSubmit** fires (user submits prompt)
   - Nora searches past sessions, finds 3 similar fixes
   - Prints ranked suggestions with code patterns

3. Kiro reads suggestions, generates a fix

4. **preToolUse** fires (before Kiro writes auth.ts)
   - Nora checks if new code has hardcoded secrets ✓
   - Allows execution

5. **postToolUse** fires (after Kiro runs tests)
   - Test output shows "FAIL — Cannot find module './utils'"
   - Nora matches this to session #42 where same error was fixed
   - Suggests checking barrel exports

6. Kiro applies suggestion, tests pass

7. **stop** fires (session ends)
   - Nora captures full transcript
   - Sends to daemon for analysis
   - Daemon will update steering files overnight

---

## Daemon Communication Protocol

Hooks that send data to the daemon use this format:

```json
{
  "type": "session_capture",
  "session_id": "sess_abc123def456",
  "agent": "kiro",
  "transcript": [
    {"role": "user", "content": "..."},
    {"tool": "Write", "path": "...", "result": "..."}
  ],
  "metadata": {
    "duration_seconds": 847,
    "turn_count": 23,
    "exit_code": 0
  }
}
```

The daemon responds with:
```json
{"status": "ack", "session_id": "sess_abc123def456"}
```

If daemon is unavailable (socket missing, not listening), hook logs warning but does not fail.

---

## Debugging Hooks

To manually test a hook:

```bash
# Test userPromptSubmit
echo '{"hook": "userPromptSubmit", "prompt": {"content": "Fix auth"}, "session_id": "test_123"}' | \
  python3 ~/.kiro/hooks/nora_context.py

# Test preToolUse
echo '{"hook": "preToolUse", "tool_name": "Write", "tool_input": {"file_path": "/src/app.ts", "content": "const KEY = \"secret\""}}' | \
  python3 ~/.kiro/hooks/nora_pretool.py
```

Check nora.db directly:
```bash
sqlite3 ~/.nora/nora.db
> SELECT * FROM sessions LIMIT 5;
> SELECT * FROM tool_metrics WHERE tool_name = 'Bash';
> SELECT * FROM error_signatures LIMIT 10;
```

View steering file generation:
```bash
cat ~/.kiro/steering/nora-patterns.md
cat ~/.kiro/steering/nora-antipatterns.md
```

---

## Performance Notes

- **Hook latency**: userPromptSubmit (3s max), preToolUse (2s max) — these block the agent
- **Database size**: nora.db grows ~1-2 MB per 100 sessions; normal operation
- **FTS5 index**: Built incrementally; first 10 sessions may be slower
- **Daemon memory**: ~50 MB for 1000 sessions in analysis queue
- **Steering file updates**: Daemon runs analysis every 24h or on-demand via `nora analyze`

---

## See Also

- [README.md](../README.md) — Project overview and getting started
- [DAEMON.md](./DAEMON.md) — Daemon architecture and commands (if it exists)
- [DB_SCHEMA.md](./DB_SCHEMA.md) — Nora database schema (if it exists)
