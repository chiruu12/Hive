# Hive Framework Hardening Specification

**Version:** 1.0
**Date:** 2026-07-22
**Related:** [Security Audit Report](./security-audit-2026-07-22.md)

This document contains detailed implementation specifications for each hardening change, including prompts that can be used to implement the changes.

---

## Table of Contents

1. [P0: Default `allow_dev_commands` to False](#p1-default-allow_dev_commands-to-false)
2. [P0: Add SSRF Guard to LinkToolkit](#p2-add-ssrf-guard-to-linktoolkit)
3. [P1: Add Path Restriction to Shell Safe Commands](#p3-add-path-restriction-to-shell-safe-commands)
4. [P1: Default `plugins.enabled` to False](#p4-default-pluginsenabled-to-false)
5. [P1: Restrict Orchestrator Workspace](#p5-restrict-orchestrator-workspace)
6. [P2: Apply Guardrails to Inter-Agent Content](#p6-apply-guardrails-to-inter-agent-content)
7. [P2: Flag `shell_exec` with `requires_approval`](#p7-flag-shell_exec-with-requires_approval)
8. [P2: Add `read_clipboard` Content Limit](#p8-add-read_clipboard-content-limit)

---

## P0: Default `allow_dev_commands` to False

**Status:** Implemented (0.7.0)

**Priority:** P0 (Critical)
**Effort:** 1 line + test updates
**Risk:** Breaking change for users who rely on default dev commands

### Problem

The default configuration allows LLM agents to execute `python`, `node`, `curl`, `wget`, and other dangerous commands. This gives any LLM agent full remote code execution capability.

### Specification

**File:** `src/hive/config.py`
**Change:** Line in `ToolsConfig` class

```python
# BEFORE
class ToolsConfig(BaseModel):
    shell_allow_dev_commands: bool = True  # DANGEROUS DEFAULT

# AFTER
class ToolsConfig(BaseModel):
    shell_allow_dev_commands: bool = False  # Safe default, opt-in
```

### Implementation Prompt

```
Change the default value of `shell_allow_dev_commands` in `src/hive/config.py` from `True` to `False`.

This is a security hardening change. The `DEV_COMMANDS` set includes `python`, `node`, `curl`, `wget`, and other commands that allow arbitrary code execution. By defaulting to `False`, agents must explicitly opt-in to these dangerous commands.

Requirements:
1. Change the default in `ToolsConfig` class
2. Update any documentation that references the default
3. Update tests that rely on the default being `True`
4. Add a comment explaining why the default is `False`

Files to modify:
- `src/hive/config.py` (line ~215)
- `tests/adversarial/test_shell_sandbox.py` (update dev_shell fixture if needed)
```

### Test Impact

- `tests/adversarial/test_shell_sandbox.py::TestDevCommandsDangerous` — These tests use an explicit `allow_dev_commands=True` fixture, so they should still pass
- Any tests that create `ShellToolkit()` without explicit `allow_dev_commands` will now get restricted mode

---

## P0: Add SSRF Guard to LinkToolkit

**Status:** Implemented (0.7.0) -- uses `hive.tools.url_safety.fetch_url_safe`

**Priority:** P0 (Critical)
**Effort:** ~30 lines
**Risk:** Low — adds validation, doesn't change existing behavior for valid URLs

### Problem

`LinkToolkit.scrape_link()` and `save_link()` make HTTP requests without any SSRF protection. An LLM agent can use these to access internal services, cloud metadata endpoints, and exfiltrate data.

### Specification

**File:** `src/hive/tools/links/toolkit.py`, `src/hive/tools/url_safety.py`

LinkToolkit routes HTTP fetches through shared SSRF guards in `url_safety.py`. The helpers:
1. Validate URL scheme (http/https only)
2. Resolve DNS and check for private/loopback/link-local IPs
3. Return validated IP for connection pinning (prevents DNS rebinding)
4. Apply to both `scrape_link()` and `save_link()` methods

### Implementation Prompt

```
Add SSRF protection to `src/hive/tools/links/toolkit.py` by porting the `_validate_url` function from `src/hive/tools/web/toolkit.py`.

The `_validate_url` function in WebToolkit:
1. Validates URL scheme is http or https
2. Resolves DNS and checks that the IP is not private, loopback, link-local, reserved, multicast, or unspecified
3. Returns a tuple of (error_message, validated_ip)
4. The validated IP is used for connection pinning to prevent DNS rebinding TOCTOU attacks

Steps:
1. Copy the `_is_blocked_ip` and `_validate_url` functions from `src/hive/tools/web/toolkit.py`
2. Import `ipaddress` and `socket` at the top of `src/hive/tools/links/toolkit.py`
3. Add URL validation to `scrape_link()` before making the HTTP request
4. Add URL validation to `save_link()` before making the HTTP request
5. If validation fails, return an error message to the agent
6. Add tests to `tests/adversarial/test_ssrf_bypass.py` verifying LinkToolkit now blocks private IPs

The validation should happen BEFORE the httpx request, not after.
```

### Test Updates

Add to `tests/adversarial/test_ssrf_bypass.py`:

```python
class TestLinkToolkitSSRFProtection:
    """Verify LinkToolkit now has SSRF protection."""

    @pytest.mark.asyncio
    async def test_blocks_private_ip(self, tmp_path):
        """LinkToolkit should block requests to private IPs."""
        from hive.tools.links.toolkit import LinkToolkit
        from hive.memory.semantic import SemanticMemory

        memory = SemanticMemory(tmp_path, "test-agent")
        toolkit = LinkToolkit(memory=memory)
        toolkit.bind("test-agent")

        result = await toolkit.scrape_link("http://127.0.0.1/")
        assert "blocked" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_blocks_cloud_metadata(self, tmp_path):
        """LinkToolkit should block requests to cloud metadata endpoints."""
        from hive.tools.links.toolkit import LinkToolkit
        from hive.memory.semantic import SemanticMemory

        memory = SemanticMemory(tmp_path, "test-agent")
        toolkit = LinkToolkit(memory=memory)
        toolkit.bind("test-agent")

        result = await toolkit.scrape_link("http://169.254.169.254/latest/meta-data/")
        assert "blocked" in result.lower() or "error" in result.lower()
```

---

## P1: Add Path Restriction to Shell Safe Commands

**Status:** Implemented (0.7.0)

**Priority:** P1 (High)
**Effort:** ~20 lines
**Risk:** Medium — may break legitimate use cases where agents need to read system files

### Problem

`cat`, `head`, `tail`, `grep`, `find` are in `SAFE_COMMANDS` but can read ANY file on the system. The workspace jail only applies to `FileToolkit`, not `ShellToolkit`.

### Specification

**File:** `src/hive/tools/shell/toolkit.py`

Add a path validation check for commands that accept file paths. The validation should:
1. Extract the file path argument from the command
2. Resolve it against the workspace directory
3. Reject if the resolved path is outside the workspace

### Implementation Prompt

```
Add workspace path validation to shell commands that accept file paths in `src/hive/tools/shell/toolkit.py`.

The following SAFE_COMMANDS accept file paths and should be validated:
- `cat` — reads file contents
- `head` — reads file contents
- `tail` — reads file contents
- `grep` — searches file contents (also accepts patterns, so be careful)
- `find` — lists files (already workspace-relative by default)
- `touch` — creates files
- `mkdir` — creates directories
- `cp` — copies files
- `mv` — moves files
- `rm` — deletes files

Implementation approach:
1. Add a `_validate_path_in_workspace(command: str) -> str | None` method to `ShellToolkit`
2. For commands that accept paths, extract the path argument(s)
3. Resolve the path against `self._workspace`
4. If the resolved path is outside the workspace, return an error message
5. Call this validation in `_check_command()` after the operator/redirect checks

Special cases:
- `grep` accepts `-r` (recursive) and pattern arguments — only validate the file/directory arguments, not the pattern
- `find` is already workspace-relative (no absolute paths typically)
- `echo`, `printf`, `wc`, `sort`, `uniq`, `diff`, `tr`, `cut` don't need path validation

The validation should use `Path.resolve()` and `is_relative_to()` like `FileToolkit` does.

Add tests verifying:
- `cat /etc/passwd` is blocked
- `cat test.txt` (in workspace) is allowed
- `cat ../../../etc/passwd` is blocked
- `grep -r "password" /etc/` is blocked
```

---

## P1: Default `plugins.enabled` to False

**Status:** Implemented (0.7.0)

**Priority:** P1 (High)
**Effort:** 1 line + test updates
**Risk:** Low — plugins are an advanced feature, disabling by default is safe

### Problem

Any `.py` file in `.hive/plugins/` is loaded and executed with full process privileges. Hot-loaded every 10 cycles.

### Specification

**File:** `src/hive/config.py`

```python
# BEFORE
class PluginsConfig(BaseModel):
    enabled: bool = True  # DANGEROUS DEFAULT

# AFTER
class PluginsConfig(BaseModel):
    enabled: bool = False  # Safe default, opt-in
```

### Implementation Prompt

```
Change the default value of `enabled` in `PluginsConfig` in `src/hive/config.py` from `True` to `False`.

This is a security hardening change. The plugin system executes arbitrary Python code with full process privileges. By defaulting to `False`, users must explicitly enable plugins.

Requirements:
1. Change the default in `PluginsConfig` class
2. Update any documentation that references the default
3. Add a comment explaining why the default is `False`

Files to modify:
- `src/hive/config.py`
```

---

## P1: Restrict Orchestrator Workspace

**Status:** Implemented (0.7.0)

**Priority:** P1 (High)
**Effort:** ~10 lines
**Risk:** Medium — may break legitimate use cases where agents need to work in specific directories

### Problem

`OrchestratorToolkit.run_code_task()` spawns Claude Code/Codex in any directory. The `workspace` parameter is only validated for `is_dir()`, not for path sensitivity.

### Specification

**File:** `src/hive/orchestrator/toolkit.py`

Restrict the workspace to:
1. The agent's own workspace directory, OR
2. Directories explicitly allowed in config

### Implementation Prompt

```
Restrict the orchestrator workspace to the agent's own workspace directory in `src/hive/orchestrator/toolkit.py`.

Currently, the `run_code_task` tool accepts any `workspace` parameter that is a valid directory. This allows an LLM agent to point Claude Code at sensitive directories like `/etc`, `~/.ssh`, etc.

Implementation:
1. Add a `_workspace` attribute to `OrchestratorToolkit` (set via `bind()`)
2. In `run_code_task()`, validate that the requested workspace is either:
   - The agent's own workspace directory, OR
   - A subdirectory of the agent's workspace
3. If the workspace is not specified, default to the agent's workspace
4. If the workspace is specified but outside the agent's workspace, return an error

The validation should use `Path.resolve()` and `is_relative_to()`.

Files to modify:
- `src/hive/orchestrator/toolkit.py`

Add tests verifying:
- Default workspace is the agent's workspace
- Specifying a subdirectory of the workspace is allowed
- Specifying a directory outside the workspace is rejected
- Specifying `/etc` or `~/.ssh` is rejected
```

---

## P2: Apply Guardrails to Inter-Agent Content

**Status:** Implemented (0.7.0)

**Priority:** P2 (Medium)
**Effort:** ~50 lines
**Risk:** Low — adds filtering, doesn't change existing behavior for clean content

### Problem

Agents can send arbitrary messages to other agents. These messages are injected into the target agent's LLM context without sanitization.

### Specification

**Files:** `src/hive/tools/comms/toolkit.py`, `src/hive/tools/a2a/toolkit.py`

Apply input guardrails to content received from other agents before injecting into context.

### Implementation Prompt

```
Apply input guardrails to inter-agent messages in `src/hive/tools/comms/toolkit.py` and `src/hive/tools/a2a/toolkit.py`.

When an agent reads messages from its inbox (via `read_inbox()` or `check_inbox()`), the message content should be sanitized through the input guardrail pipeline before being returned to the LLM context.

Implementation:
1. Add an optional `guardrails` parameter to the toolkit constructors
2. In `read_inbox()` and `check_inbox()`, apply guardrails to each message body
3. If guardrails block the message, replace it with a warning: "[Message blocked by guardrail]"
4. If guardrails redact, use the redacted version
5. Log any guardrail triggers for observability

This prevents cross-agent prompt injection where one agent sends malicious instructions to another.

Files to modify:
- `src/hive/tools/comms/toolkit.py`
- `src/hive/tools/a2a/toolkit.py`
- `src/hive/daemon/toolkit_factory.py` (pass guardrails to toolkits)
```

---

## P2: Flag `shell_exec` with `requires_approval`

**Status:** Implemented (0.7.0)

**Priority:** P2 (Medium)
**Effort:** 1 line
**Risk:** Low — only affects users who enable the approval system

### Problem

`shell_exec` is the highest-risk built-in tool. When the approval system is enabled, it must require human sign-off before execution.

### Specification

**File:** `src/hive/tools/shell/toolkit.py`

```python
@tool(requires_approval=True)
async def shell_exec(self, command: str) -> str:
```

When `approval.enabled: true`, `shell_exec` is gated unless listed in `approval.auto_approve`.

### Implementation Prompt

```
Add `requires_approval=True` to the `shell_exec` tool decorator in `src/hive/tools/shell/toolkit.py`.

This ensures that when the approval system is enabled, shell commands require human approval before execution.

Requirements:
1. Change `@tool()` to `@tool(requires_approval=True)` on the `shell_exec` method
2. Add a comment explaining why this tool requires approval
3. Verify that the approval system correctly gates this tool when enabled

Files to modify:
- `src/hive/tools/shell/toolkit.py`
```

---

## P2: Add `read_clipboard` Content Limit

**Status:** Implemented (0.7.0)

**Priority:** P2 (Medium)
**Effort:** ~5 lines
**Risk:** Low — adds size limit, doesn't change behavior for normal-sized clipboard content

### Problem

`read_clipboard()` returns whatever is on the system clipboard to the LLM context. Without a size limit, large clipboard payloads can flood context or aid exfiltration.

### Specification

**File:** `src/hive/tools/clipboard/toolkit.py`

Implemented as `MAX_CLIPBOARD_BYTES = 10_000` with truncation and a warning prefix when exceeded.

### Implementation Prompt

```
Add a content size limit to `read_clipboard()` in `src/hive/tools/clipboard/toolkit.py`.

Currently, `read_clipboard()` returns whatever is on the system clipboard without any size limit. This can be used for data exfiltration if the clipboard contains sensitive data.

Implementation:
1. Add a constant `MAX_CLIPBOARD_BYTES = 10_000` at the top of the file
2. In `read_clipboard()`, check if the clipboard content exceeds the limit
3. If it does, truncate and return a warning message
4. Add a comment explaining the security rationale

Files to modify:
- `src/hive/tools/clipboard/toolkit.py`
```

---

## Testing Strategy

For each hardening change:

1. **Unit tests** — Verify the specific behavior change
2. **Adversarial tests** — Verify the change blocks known attack vectors
3. **Integration tests** — Verify the change doesn't break existing functionality
4. **Regression tests** — Run full test suite to catch unexpected side effects

### Test Files to Update

- `tests/adversarial/test_shell_sandbox.py` — Shell sandbox tests
- `tests/adversarial/test_ssrf_bypass.py` — SSRF tests
- `tests/adversarial/test_daemon_resilience.py` — Daemon resilience tests
- `tests/adversarial/test_approval_bypass.py` — Approval tests
- `tests/adversarial/test_resource_exhaustion.py` — Resource exhaustion tests

---

## Migration Guide

### For Users Upgrading from 0.6.x

Defaults changed in 0.7.0. You must **opt in explicitly** to restore prior behavior.

1. **Shell commands:** Default is now `false`. If your agents rely on `python`, `curl`, or other dev commands, add to `.hive/config.yaml`:
   ```yaml
   tools:
     shell_allow_dev_commands: true  # opt in -- not the default
   ```

2. **Plugins:** Default is now `false`. If you use plugins, add to `.hive/config.yaml`:
   ```yaml
   plugins:
     enabled: true  # opt in -- not the default
   ```

3. **Orchestrator:** If your agents need to work in directories outside their workspace, you'll need to adjust the workspace configuration.

---

## References

- [Security Audit Report](./security-audit-2026-07-22.md)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [CWE-78: OS Command Injection](https://cwe.mitre.org/data/definitions/78.html)
- [CWE-918: Server-Side Request Forgery](https://cwe.mitre.org/data/definitions/918.html)
