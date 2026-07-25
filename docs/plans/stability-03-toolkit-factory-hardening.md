# Stability 03: Toolkit factory hardening (SRP, caching, workspace init)

## Goal

Make toolkit construction **consistent, cheap, and typed** by eliminating duplicate guardrail builds, caching tool-name discovery, and passing orchestrator workspace through the constructor -- without changing tool behavior or sub-agent allowlist semantics.

## Why (stability)

| Problem | Impact |
|---------|--------|
| Duplicate `build_guardrail_pipeline()` | Daemon builds pipeline in `HiveDaemon.__init__` (`loop.py` ~67); factory rebuilds on every `build()` via `get_config().guardrails` (`toolkit_factory.py` ~120). Hot config reload can diverge mid-cycle. |
| `tool_names()` calls full `build()` | Startup log (`loop.py` ~289) instantiates every toolkit for agent `__system__`, creates workspace dirs, and repeats on every call. |
| Orchestrator workspace side channel | `set_workspace()` after `bind()` (`toolkit_factory.py` ~211–213) unlike other toolkits that take `workspace` in `__init__`. |
| Dead `HiveDaemon._orch_manager` | Field at `loop.py` ~145 is never read; `SessionManager` lives only on `ToolkitFactory._orch_manager`. |

Post-01/05 context (already landed, do not re-implement):

- **H3 sub-agent allowlist** -- `DEFAULT_SUB_AGENT_TOOLKITS` + `tools.sub_agent_toolkits` config; covered by `tests/adversarial/test_sub_agent_privileges.py`.
- **Guardrails wired** -- Comms, A2A, schedule, delegation toolkits receive a pipeline in `build()`; daemon passes the same pipeline to the agent runtime (`loop.py` ~655–685).
- **Adversarial CI gate** -- plan 05; merge gate runs `tests/adversarial/`.

## Current state (file refs)

| Concern | Location |
|---------|----------|
| Factory | `src/hive/daemon/toolkit_factory.py` -- `ToolkitFactory.__init__`, `build()`, `tool_names()`, `tools_description()` |
| Daemon wiring | `src/hive/daemon/loop.py` -- `_guardrails`, `_toolkit_factory`, `_build_toolkits`, `_get_tool_names`, dead `_orch_manager`, plugin hot-load (~347–360) |
| Orchestrator | `src/hive/orchestrator/toolkit.py` -- `set_workspace()`, path containment in `run_code_task` |
| Guardrails | `src/hive/runtime/guardrails.py` -- `GuardrailPipeline`, `build_guardrail_pipeline()` |
| Sub-agent allowlist | `toolkit_factory.py` `DEFAULT_SUB_AGENT_TOOLKITS`, `_allowed_keys()` |
| Config | `src/hive/config.py` `ToolsConfig.sub_agent_toolkits` |
| Tests | `tests/adversarial/test_orchestrator_workspace.py`, `tests/adversarial/test_sub_agent_privileges.py`, `tests/test_daemon_setup.py` |

## Proposed changes (numbered, executable)

### 1. Inject guardrail pipeline once

**Change:**

```python
# ToolkitFactory.__init__(..., guardrails: GuardrailPipeline, ...)
self._guardrails = guardrails
```

- `HiveDaemon` passes `self._guardrails` when constructing the factory (`loop.py` ~161).
- Remove `build_guardrail_pipeline(get_config().guardrails)` from `ToolkitFactory.build()`; use `self._guardrails` for Comms, A2A, schedule, delegation.
- **Config reload semantics:** guardrail config changes require daemon restart (same as approval pipeline refresh today). Document in factory docstring; do not rebuild per agent cycle.

**Verify:** `rg 'build_guardrail_pipeline' src/hive/daemon/` shows one call site in `loop.py` init only.

### 2. Remove dead `HiveDaemon._orch_manager`

- Delete `self._orch_manager: Any = None` from `HiveDaemon.__init__` (`loop.py` ~145).
- Single `SessionManager` owner remains on `ToolkitFactory._orch_manager` (lazy, reused across agents).

### 3. Cache `tool_names()` with plugin invalidation

**Change:**

- Add `_tool_names_cache: list[str] | None = None` on factory.
- `tool_names()`: return cache on hit; on miss, call `build("__tool_catalog__", is_sub_agent=False)`, extract names, store cache.
- Add `invalidate_tool_names_cache() -> None` (sets cache to `None`).
- `HiveDaemon._run()`: after extending `_plugin_toolkits` with newly discovered plugins, call `self._toolkit_factory.invalidate_tool_names_cache()` when the batch is non-empty (~347–360).

**Note:** catalog build still creates one workspace dir under `workspaces/__tool_catalog__` on first call -- acceptable vs rebuilding every toolkit on every daemon start. Future optimization: static registry keys without instantiation (optional, out of scope).

**Verify:** unit test asserts second `tool_names()` does not invoke `build()` (spy/mock).

### 4. Orchestrator workspace via constructor

**Change:**

```python
# orchestrator/toolkit.py
def __init__(self, manager: SessionManager, workspace: Path | None = None):
    ...
    if workspace is not None:
        self._agent_workspace = workspace.resolve()
```

- Factory: `OrchestratorToolkit(self._orch_manager, workspace=workspace)` then `bind(agent_id)`; remove post-bind `set_workspace()`.
- Keep `set_workspace()` as backward-compatible alias (delegates to same resolve logic) for one release; adversarial tests prefer constructor injection.

### 5. Factory SRP / typing cleanups (same PR)

- Import `GuardrailPipeline` and type the injected field.
- Type `delegation` as `DelegationEngine` (from `hive.agents.delegation`).
- Type `plugin_toolkits` as `list[type[Toolkit]]` where mypy-clean.
- Type `ToolkitFactory._orch_manager` as `SessionManager | None`.
- **Do not** split `toolkit_registry.py` in this PR (defer to plan 04 or follow-up if `build()` still exceeds readability threshold).

## Non-goals

- Changing `DEFAULT_SUB_AGENT_TOOLKITS` membership or H3 semantics.
- Changing individual toolkit behavior (shell jail, web SSRF, file limits).
- Moving plugin discovery into the factory (stays in daemon `_run()`).
- Plan 02 extension-point wiring or plan 04 loop decomposition.
- Static tool catalog without instantiation (future optimization).

## Risks / rollback

| Change | Risk | Mitigation |
|--------|------|------------|
| Shared guardrail pipeline | Divergence if pipeline mutated at runtime | `GuardrailPipeline` is immutable after build (list of guardrails, no setters) |
| Cached `tool_names()` | Stale after hot-loaded plugins | `invalidate_tool_names_cache()` on every non-empty plugin batch |
| Constructor workspace | External callers using only `set_workspace` | Keep `set_workspace()`; adversarial tests cover both paths |
| Required `guardrails` ctor arg | Test/fixture breakage | Pass `GuardrailPipeline([])` or `build_guardrail_pipeline(...)` in fixtures |

**Rollback:** revert factory constructor signature; restore per-build `build_guardrail_pipeline()` in `build()`.

## Acceptance criteria (testable)

```bash
uv run pytest tests/adversarial/test_orchestrator_workspace.py tests/adversarial/test_sub_agent_privileges.py tests/test_daemon_setup.py -q --tb=short
uv run pytest -q -k "toolkit_factory or ToolkitFactory or orchestrat" --tb=short
uv run pytest tests/test_toolkits_extended.py -q --tb=short
uv run mypy src/hive/daemon/toolkit_factory.py src/hive/orchestrator/toolkit.py
```

Checklist:

- [ ] Single `build_guardrail_pipeline()` per daemon lifetime in `src/hive/daemon/` (init only, not in `build()`).
- [ ] `tool_names()` second call does not call `build()` (unit test with spy).
- [ ] Plugin hot-load invalidates cache (unit test: invalidate → second call rebuilds).
- [ ] Sub-agent build still excludes shell/git/delegation/schedule/orchestrator/plugins per adversarial tests.
- [ ] Orchestrator path containment passes with `workspace=` constructor arg.
- [ ] `HiveDaemon` has no `_orch_manager`; one `SessionManager` reused via factory.
- [ ] Daemon startup log tool count unchanged (integration smoke via existing tests).

## Implementation order

| Step | Task | Est. |
|------|------|------|
| 1 | Inject guardrails; remove duplicate build in `build()` | 1h |
| 2 | Remove dead `_orch_manager` from `loop.py` | 15m |
| 3 | Cache `tool_names()` + `invalidate_tool_names_cache()` + loop hook | 1h |
| 4 | Orchestrator `__init__(workspace=...)` + factory + test updates | 1h |
| 5 | Add `tests/test_toolkit_factory.py`; fix fixtures | 1h |
| 6 | Typing cleanup + mypy | 30m |

**Total:** **M** (~2–3 days calendar; ~4–5h focused implementation).

## Estimate

**M** (2–3 days) -- low behavior risk, mostly structural. Land before plan 04 loop split.
