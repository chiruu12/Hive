# Stabilization Phase 3 -- Security boundary closure

## Problem statement

Residual security gaps remain after Phases A and F. Audits confirmed **concrete bypasses** (shell filesystem oracle, web_search redirect path) and **missing sanitization** at sub-agent boundaries. Other items are **characterization** work without confirmed exploit today.

### Exact files and functions

| Finding | Location | Label |
|---------|----------|-------|
| Shell `test -f /etc/passwd` oracle | `src/hive/tools/shell/toolkit.py`, `tests/adversarial/test_shell_sandbox.py` | **Verified defect** |
| `sort -T /tmp` temp write outside workspace | Shell toolkit / process spawn | **Verified defect** (known residual) |
| `create_subprocess_shell` parser risk | `src/hive/tools/_process.py` | **Risk / hypothesis** |
| Sub-agent objective unsanitized | `src/hive/tools/sub_agents/toolkit.py`, pursuit write path in `agent_cycle.py` | **Verified defect** |
| `web_search` raw httpx | `src/hive/tools/web/toolkit.py` `web_search()` `follow_redirects=True` | **Verified defect** |
| Non-loopback REST no API key | `src/hive/server/` auth middleware, `config.py` | **Verified defect** (deployment exposure) |
| Loopback no-key | Same | **By design** (local-first) |
| Orchestrator child env secrets | `src/hive/orchestrator/toolkit.py`, subprocess spawn | **Verified defect** |
| MCP stdio trust model | `src/hive/mcp/server.py` | **Document** -- not network auth |
| HTTPS IP pinning | `url_safety.py` | **Backlog** (not this phase) |

## Scope

Close or characterize each boundary in **reviewable slices**. Preserve restricted-shell behavior for legitimate operators. Shared URL safety for all outbound HTTP from tools.

## Non-goals

- Full elimination of `create_subprocess_shell` (characterize + document only unless bypass found).
- HTTPS IP pinning (backlog).
- Default-enabling guardrails globally (product decision).
- MCP network authentication layer (trusted-host model stays).

## Implementation slices

### Slice 3.1 -- Shell: block `test`/`[` existence oracle

1. Extend restricted-shell command parser denylist for `test -f`, `[ -f`, `[[ -f` against absolute paths outside workspace.
2. Add adversarial parametrized cases: `/etc/passwd`, `/proc/self/environ`, workspace-relative allowed paths.
3. Regression: Phase A `~`/`$HOME` bypass tests still pass.

### Slice 3.2 -- Shell: `sort -T` and temp dir containment

1. Deny or rewrite `-T` pointing outside workspace; default temp to workspace `.hive/tmp`.
2. Audit other utilities accepting output path flags (`mktemp`, `tee`, etc.) -- fix only confirmed leaks.
3. Adversarial test: temp files appear only under workspace.

### Slice 3.3 -- Shell: parser / subprocess characterization

**Label: Risk / hypothesis — DEFERRED**

1. Document parser differential surface in `docs/hardening-guide.md`.
2. Add table-driven tests for quoting edge cases; no production change unless bypass found.
3. Optional spike PR: `execve argv` migration design doc only.

**Status:** Not implemented in Phase 3; characterization deferred until a confirmed bypass is found.

### Slice 3.4 -- Sub-agent objective sanitization

1. Apply shared guardrail sanitizer (from F patterns) at:
   - Sub-agent spawn / task write in `sub_agents/toolkit.py`
   - Pursuit objective boundary in `agent_cycle.py` before `pursue_goal`
2. Reject or strip control chars, path traversal markers, excessive length.
3. Adversarial tests in `test_sub_agent_privileges.py` + new injection cases.

### Slice 3.5 -- `web_search` URL safety

1. Route DuckDuckGo fetch through `url_safety.safe_request()` or per-hop validator matching `web_fetch`.
2. Disable blind `follow_redirects=True`; manual hop loop with SSRF checks each redirect.
3. Extend `tests/adversarial/test_ssrf_bypass.py` for search redirect chains.

### Slice 3.6 -- Non-loopback API key enforcement

1. When bind host not loopback (`0.0.0.0`, public interface): require non-empty `api.api_key` at server start (fail closed).
2. Loopback bind: keep optional key (local-first).
3. Document in `docs/guide/rest-api.md` and deployment guide.
4. Test: server refuses start without key on `0.0.0.0`; loopback works without key.

### Slice 3.7 -- Orchestrator env scrubbing

1. Strip provider secrets (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) from child process env in orchestrator spawn.
2. Pass only workspace-scoped vars allowlist.
3. Test: child env snapshot lacks provider keys.

## Acceptance criteria

```bash
uv run pytest tests/adversarial/test_shell_sandbox.py -v
uv run pytest tests/adversarial/test_ssrf_bypass.py -v
uv run pytest tests/adversarial/test_sub_agent_privileges.py -v
uv run pytest tests/adversarial/test_orchestrator_workspace.py -v
uv run pytest tests/test_api_production.py -v -k api_key
```

- [x] `test -f /etc/passwd` blocked in restricted mode.
- [x] `sort -T /tmp` blocked or redirected to workspace temp.
- [x] Sub-agent injection payloads sanitized at write boundary.
- [x] `web_search` rejects redirect to private IP.
- [x] Non-loopback serve fails without API key; loopback documented exception.
- [x] Orchestrator child env scrub verified.

**Status:** VERIFIED (2026-07-25)

## Regression matrix (Hardening A--G)

| Phase | Check |
|-------|-------|
| A | Existing shell bypass regressions remain blocked |
| F | Schedule IDOR + nudge sanitization unchanged |
| stability-05 | Adversarial CI gate extended, not weakened |

## Rollback / compatibility

- Shell restrictions: tighten only; no rollback except emergency revert PR.
- API key on non-loopback: env `HIVE_API_ALLOW_INSECURE=1` **discouraged** escape hatch for dev only (document risk).
- Sub-agent sanitization may reject previously accepted objectives -- document in CHANGELOG.

## Dependencies

- **Phase 0** -- green adversarial baseline.
- **Phase A/F** patterns for sanitization reuse.

## Risks and YAGNI cuts

| Risk | Mitigation |
|------|------------|
| Over-aggressive shell deny breaks legit scripts | Allowlist workspace paths; integration examples updated |
| API key breaks existing LAN deployments | Clear error + docs; loopback unchanged |

**YAGNI:** Full shell rewrite to execve; HTTPS IP pinning; MCP OAuth.

## Finding labels summary

See table in Problem statement. Items marked **Backlog** or **Risk / hypothesis** are explicitly out of slice scope unless bypass confirmed during implementation.
