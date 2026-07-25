# Phase E -- Memory unification

## Goal

Unify the **three memory surfaces** (JSON `MemoryToolkit`, daemon `SemanticMemory`, runtime `PersistentMemory` recall) so writes are visible across pursuit and goal generation, and recalled context actually reaches the LLM.

## Why (problems addressed -- bullet list with severity)

- **P1:** Memory stored, never recalled in daemon pursuit -- runtime `Agent` is constructed without `memory=` in `agent_cycle.py`; `_prepare_conversation()` recall path unused (`src/hive/runtime/agent.py` lines 218--236).
- **P1:** Dual backends -- `MemoryToolkit` writes `.hive/agent_memory/{id}.json`; daemon uses `SemanticMemory` at `.hive/memory/` via `AgentContextCache.get_memory()` (`src/hive/tools/memory/toolkit.py`, `src/hive/daemon/agent_context.py`).
- **P1:** Goal generation ignores semantic memory -- `ExistenceLoop._build_prompt()` uses notepad, peers, nudges, not `SemanticMemory.recall()` (`src/hive/agents/existence.py`).
- **P2:** Docs promise `PersistentMemory` cross-session behavior (`docs/guide/developer-guide.md`) while daemon path differs.

## Related issues bundled

| ID | Finding |
|----|---------|
| LOOP-MEM-01 | Daemon pursuit skips `Agent._memory` recall |
| LOOP-MEM-02 | MemoryToolkit vs SemanticMemory split |
| LOOP-MEM-03 | Goal-gen lacks memory context |
| LOOP-MEM-04 | Knowledge toolkit uses SemanticMemory; memory tool uses JSON |

## Current state (files)

| Area | Location | Behavior today |
|------|----------|----------------|
| JSON KV tool | `src/hive/tools/memory/toolkit.py` | Per-agent JSON file |
| Semantic store | `src/hive/memory/semantic.py` | Used post-goal in `agent_cycle.py` `memory.store(...)` on completion |
| Daemon cache | `src/hive/daemon/agent_context.py` | `SemanticMemory(hive_dir, agent_id)` |
| Factory | `src/hive/daemon/toolkit_factory.py` | Instantiates both `MemoryToolkit` and `KnowledgeToolkit` |
| Runtime recall | `src/hive/runtime/agent.py` | Requires `memory` ctor arg |
| Protocol | `src/hive/memory/protocol.py` | Store protocol; memory abstraction partial |

## Proposed changes (numbered)

1. **Pick canonical store (recommend SemanticMemory):**
   - Implement adapter so `MemoryToolkit` delegates to same backend as daemon (`SemanticMemory` or thin wrapper implementing store/recall API).
   - Deprecate parallel JSON files with one-time migration: read legacy JSON into semantic store on first access.

2. **Wire recall into pursuit:**
   - Pass `memory=self._ctx.get_memory(agent_id)` (or `PersistentMemory` facade) into runtime `Agent` constructor in `agent_cycle.py`.
   - Verify mock test: after `memory.store`, next pursuit prompt includes "Relevant memories" system block.

3. **Wire recall into goal generation:**
   - In `ExistenceLoop._build_prompt()` and `GoalContext`, add `memory_snippets: list[str]` from `recall(profile.role or objective seed, limit=3)`.
   - Custom `GoalStrategy` receives same field on `GoalContext`.

4. **Toolkit factory alignment:**
   - `MemoryToolkit(agent_id=..., hive_dir=...)` shares backend instance with daemon cache (inject factory dependency).

5. **Docs:** Update `docs/guide/prompt-assembly.md`, `docs/guide/toolkits.md` memory section, `docs/extending/index.md` with single-memory diagram.

## Non-goals

- Chroma / embedding backend selection (optional extra).
- Long-term RAG over full JSONL logs.
- Changing KnowledgeToolkit semantics beyond shared backend path.

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| Migration loses JSON keys | Backup `.json`; idempotent import |
| Recall latency each cycle | Limit 3 entries; cache recall per goal_id |
| Breaking plugin MemoryToolkit subclass | Keep JSON read-only fallback one release |

Rollback: config `memory.unified: false` uses legacy JSON toolkit only.

## Acceptance criteria (testable)

```bash
uv run pytest tests/test_memory_strategies.py tests/memory/ tests/test_daemon_integration.py -v -k memory
```

- [x] `memory_set` via toolkit --> visible in `SemanticMemory.recall()` same agent.
- [x] Pursuit run includes recalled entry in provider messages (mock).
- [x] Generated goal prompt includes memory snippet when store non-empty.
- [x] Legacy JSON file migrates once; second start does not duplicate.

## Suggested implementation order

1. Backend adapter + migration helper.
2. Toolkit factory injection.
3. Pursuit Agent ctor wiring.
4. ExistenceLoop / GoalContext prompt fields.
5. Tests + docs.

## Estimate

**M** (2--3 days).

## Status

**Done** (2026-07-23). Canonical backend is `SemanticMemory` at `.hive/memory/<agent_id>/`. `MemoryToolkit` delegates when `memory.unified: true` (default); legacy JSON migrates once. Pursuit `Agent` receives `PersistentMemory(semantic=...)` for recall; goal generation gets `memory_snippets` on `GoalContext` / `ExistenceLoop._build_prompt`.

## Dependencies (prior phases)

- **Phase C** (soft) -- stable `goal_id` / session id helps correlate memory entries to active pursuit; can proceed in parallel if metadata uses `agent_id` only initially.
