# Phase F -- Collaboration safety

## Goal

Close **multi-agent and operator injection surfaces**: schedule IDOR, unsanitized nudges, residual sub-agent/orchestrator/clipboard/guardrail gaps, and optional secure defaults for production profiles.

## Why (problems addressed -- bullet list with severity)

- **HIGH:** `cancel_schedule` IDOR -- `ScheduleToolkit.cancel_schedule()` calls `store.disable_schedule(schedule_id)` with no agent ownership check (`src/hive/tools/schedule/toolkit.py`, `src/hive/memory/store.py`).
- **HIGH:** Unsanitized nudges -- `save_nudge` stores raw operator text; goal generation injects nudges without `sanitize_inter_agent_content` (`src/hive/server/routes/agents.py`, `src/hive/api.py`, `src/hive/cli/main.py`, `agent_cycle.py` lines 435--458 vs scheduled objectives which ARE sanitized).
- **HIGH:** Guardrails / approvals default off -- `guardrails.enabled` / `approval.enabled` default `False` (`src/hive/config.py`); regex bypassable (`docs/hardening-guide.md` H4).
- **MED:** HTTPS SSRF pin gap -- `build_pinned_request()` pins HTTP only; HTTPS uses hostname (TOCTOU window smaller but documented in `src/hive/tools/url_safety.py`).
- **MED:** Clipboard exfiltration surface -- `read_clipboard` truncated but still returns secrets to LLM (`src/hive/tools/clipboard/toolkit.py`).
- **MED:** Sub-agent residual fan-out / explicit `sub_agent_toolkits` re-enabling shell (Change 9 mitigated, config override remains).
- **MED:** Orchestrator workspace unset -- if [stability-03](stability-03-toolkit-factory-hardening.md) not merged, `OrchestratorToolkit` may lack workspace binding (`tests/adversarial/test_orchestrator_workspace.py`).

## Related issues bundled

| ID | Finding |
|----|---------|
| SEC-COLLAB-01 | Schedule cancel IDOR |
| SEC-COLLAB-02 | Raw nudge injection into goal prompt |
| SEC-COLLAB-03 | Guardrails off by default |
| SEC-COLLAB-04 | HTTPS no IP pin |
| SEC-COLLAB-05 | Clipboard / sub-agent / orchestrator residual |
| SEC-COLLAB-06 | Guardrail regex bypass (document + tighten high-signal patterns) |

## Current state (files)

| Area | Location | Behavior today |
|------|----------|----------------|
| Schedule | `src/hive/tools/schedule/toolkit.py` | Create lists own schedules; cancel by id only |
| Store | `src/hive/memory/store.py` | `disable_schedule(schedule_id)` no agent filter |
| Nudges | `src/hive/memory/store.py`, routes | Raw message storage |
| Sanitization | `src/hive/runtime/guardrails.py` | Used for A2A, schedules; not nudges |
| URL safety | `src/hive/tools/url_safety.py` | HTTP pin; HTTPS Host header path |
| Clipboard | `src/hive/tools/clipboard/toolkit.py` | Size limit per hardening guide |
| Sub-agents | `src/hive/daemon/toolkit_factory.py` | `DEFAULT_SUB_AGENT_TOOLKITS` |
| Tests | `tests/adversarial/test_inter_agent_guardrails.py`, `test_sub_agent_privileges.py` | Partial coverage |

## Proposed changes (numbered)

1. **Schedule IDOR fix:**
   - Change `disable_schedule(schedule_id, agent_id)` signature; SQL `WHERE schedule_id = ? AND agent_id = ?`.
   - `cancel_schedule` returns error if zero rows updated.
   - Add adversarial test: agent A cannot cancel agent B schedule.

2. **Sanitize nudges at write or read boundary:**
   - Prefer **read boundary** in `agent_cycle.py` when building nudge list (like A2A subjects).
   - Apply `sanitize_inter_agent_content(message, guardrails, agent_id=...)` even when guardrails disabled use structural strip (HTML/markdown/control chars) -- define `sanitize_operator_nudge()` minimal always-on sanitizer.
   - Optional: length cap on nudge storage (4k chars).

3. **Secure profile template (optional, non-breaking):**
   - Add `profiles/_secure.yaml.example` with `guardrails.enabled`, `approval.enabled`, `tools.shell_allow_dev_commands: false`, `plugins.enabled: false`.
   - Document in `docs/hardening-guide.md`; do **not** change global defaults.

4. **HTTPS pinning (optional sub-track):**
   - Evaluate CONNECT + custom TLS with pinned IP or restrict HTTPS fetches to allowlisted domains before enabling global pin.
   - If deferred, document limitation in `url_safety.py` module doc + hardening guide.

5. **Guardrail hardening (minimal):**
   - Add high-signal patterns (e.g. ignore-previous-instruction variants) to default pipeline when enabled.
   - Document bypass limits; full ML guardrail out of scope.

6. **Residual verification:**
   - Confirm orchestrator workspace set in `ToolkitFactory.build()` (stability-03).
   - Add clipboard test: oversized / binary clipboard handled.
   - Extend `tests/adversarial/test_sub_agent_privileges.py` for config override warning.

## Non-goals

- Flipping global guardrails/approval defaults (product decision).
- End-to-end prompt injection ML classifier.
- Disabling clipboard toolkit entirely.

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| Aggressive nudge sanitization strips legitimate markdown | Structural sanitizer only; guardrails optional layer |
| HTTPS pin breaks legitimate CDN hosts | Keep optional; default off |
| Schedule API break for cross-agent admin tools | REST admin uses separate operator role (future) |

Rollback: revert store signature with compat shim accepting missing agent_id (log warning).

## Acceptance criteria (testable)

```bash
uv run pytest tests/adversarial/test_inter_agent_guardrails.py tests/runtime/test_schedules.py tests/adversarial/test_sub_agent_privileges.py -v
uv run pytest tests/server/test_rest_api.py -v -k nudge
```

- [x] Agent A `cancel_schedule(B_sid)` fails / no-op with clear error.
- [x] Nudge containing injection marker stripped or blocked in goal-generation prompt (mock provider input).
- [x] `profiles/_secure.yaml.example` validates via `HiveConfig`.
- [x] Orchestrator adversarial tests pass (workspace containment).
- [x] Docs updated: `docs/guide/rest-api.md` nudge + schedule ownership.

## Status

**Done** (Phase F complete).

## Suggested implementation order

1. Schedule store + toolkit ownership check + tests.
2. Nudge sanitization at consumption in `agent_cycle.py`.
3. Secure profile example + docs.
4. Optional HTTPS / guardrail pattern sub-PRs.
5. Residual adversarial tests (clipboard, orchestrator verify).

## Estimate

**M** (2--3 days; +1 day if HTTPS pin pursued).

## Dependencies (prior phases)

- **Phase A** (soft) -- shared pattern for path/token validation mindset; not blocking.
