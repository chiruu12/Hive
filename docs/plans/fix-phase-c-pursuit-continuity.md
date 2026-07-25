# Phase C -- Pursuit continuity

**Status: Done**

## Goal

Give multi-heartbeat goal pursuit **memory of its own ReAct transcript** so agents resume work across daemon cycles instead of restarting from a single-shot user message each time.

## Why (problems addressed -- bullet list with severity)

- **P0:** No cross-cycle pursuit transcript -- each heartbeat builds a fresh runtime `Agent`, runs one `run()` call, discards `ConversationMemory` (`src/hive/daemon/agent_cycle.py`, `src/hive/runtime/agent.py`).
- **P0:** Profile `max_steps` caps **per cycle**, not per goal lifetime (exacerbated until Phase B wires limits -- then still needs continuation semantics).
- **P1:** `CheckpointManager` saves suffering/identity/goals on completion (`src/hive/checkpoint.py`) but not in-progress conversation state.
- **P1:** Session JSONL logs exist (`src/hive/logging/writer.py`) but are not replayed into the runtime conversation on resume.
- **P2:** `run_once` CLI/API path vs daemon pursuit semantics diverge (`docs/guide/system-overview.md`).

## Related issues bundled

| ID | Finding |
|----|---------|
| LOOP-PURSUIT-01 | Fresh Agent + empty conversation every cycle |
| LOOP-PURSUIT-02 | No checkpoint / session resume for active goals |
| LOOP-PURSUIT-03 | Step budget semantics across cycles unclear |

## Current state (files)

| Area | Location | Behavior today |
|------|----------|----------------|
| Pursuit | `src/hive/daemon/agent_cycle.py` | `adapter.pursue_goal(objective, context=pursuit_context)` once per cycle |
| Bridge | `src/hive/runtime/bridge.py` | Single `Task` --> `Agent.run()` |
| Conversation | `src/hive/runtime/memory.py` `ConversationMemory` | In-memory only for task lifetime |
| Logs | `src/hive/logging/writer.py` | Decision/tool JSONL keyed by agent/session/goal |
| Checkpoint | `src/hive/checkpoint.py` | No conversation blob |
| Store | `src/hive/memory/store.py` `sessions` table | Session metadata; not full message replay |
| Docs | `docs/guide/prompt-assembly.md` | Describes single pursuit invocation |

## Proposed changes (numbered)

### Design choice (pick one primary approach)

| Option | Summary | Pros | Cons |
|--------|---------|------|------|
| **C1 -- Session transcript store** | Persist serialized messages per `(agent_id, goal_id)` in SQLite or JSONL slice; hydrate `ConversationMemory` at pursuit start | Clear audit trail; works with existing logs | Schema + size limits |
| **C2 -- Checkpoint conversation field** | Extend `CheckpointManager.save()` with optional `conversation_snapshot`; save each cycle end while goal active | Reuses checkpoint UX | Checkpoints currently on milestones only |
| **C3 -- Long-lived runtime Agent** | Cache `Agent` instance in `AgentContextCache` keyed by `(agent_id, goal_id)` | Minimal serialization | Memory growth; toolkits stale on config change |

**Recommendation:** **C1** as primary (store-backed transcript), with incremental flush from `ConversationMemory` after each pursuit slice. Keep checkpoint optional for operator snapshots.

1. **Stable pursuit session id:** Derive `pursuit_session_id` from `goal_id` (or store column) reused across cycles.

2. **Transcript persistence API** (new module e.g. `src/hive/memory/pursuit_transcript.py` or extend `store.py`):
   - `append_messages(goal_id, messages)`
   - `load_messages(goal_id, limit=N)`
   - Truncate policy: cap messages or tokens (config `daemon.pursuit_transcript_max_messages`).

3. **Bridge / Agent changes:**
   - `DaemonAgentAdapter.pursue_goal(..., resume: bool = True)` loads transcript before `_prepare_conversation`.
   - After `run()`, append new messages; if `MAX_STEPS` / cycle timeout partial, persist state without completing goal (pairs with Phase B continue policy).

4. **Cycle integration in `agent_cycle.py`:**
   - On active goal: load transcript --> run bounded step slice (`min(remaining, profile.max_steps)`).
   - On goal complete/abandon: delete transcript archive.

5. **Timeout behavior:** Align with Phase D -- on cycle timeout, persist transcript before parking agent (do not abandon goal by default; today timeout abandons -- consider changing in Phase B/G).

6. **Docs:** New section in `docs/guide/daemon-mode.md` + update `docs/guide/prompt-assembly.md` pursuit diagram.

## Non-goals

- Full semantic summarization of old transcript (optional later).
- Cross-agent shared transcripts.
- Changing ReAct algorithm.

## Risks / rollback

| Risk | Mitigation |
|------|------------|
| Unbounded transcript size | Hard cap + drop-oldest or summarize |
| SQLite write amplification | Batch append once per cycle |
| Stale tool definitions in old messages | Inject system note on toolkit version change |

Rollback: config `daemon.pursuit_resume: false` restores single-shot behavior.

## Acceptance criteria (testable)

```bash
uv run pytest tests/test_pursuit_transcript.py tests/test_daemon_integration.py -v
```

- [x] Mock agent with `max_steps=2` per cycle completes a 4-step goal across **two** heartbeat cycles with monotonic step counter in logs.
- [x] Transcript replay: second cycle's provider receives prior assistant/tool messages (assert on mock message list).
- [x] Goal completion deletes transcript rows/files for that `goal_id`.
- [x] Restart daemon mid-goal: reload transcript from disk and continue (integration test with temp hive dir).

## Suggested implementation order

1. Design doc section + config keys.
2. Store module + unit tests.
3. Bridge hydrate/persist hooks.
4. `agent_cycle.py` integration + Phase B outcome flags.
5. Integration test + docs.

## Estimate

**L** (4--6 days): persistence design, migration, integration tests.

## Dependencies (prior phases)

- **Phase B** -- `MAX_STEPS` continue policy and wired `max_steps` must be defined first.
- **Phase D** (soft) -- timeout should persist spend + transcript, not abandon blindly.
