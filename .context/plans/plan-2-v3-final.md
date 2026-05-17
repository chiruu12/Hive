# Plan 2 v3: Sub-Agents, Journals, and A2A Interactions

## Vision

Agents don't create tools — they spawn sub-agents, keep journals, request what
they need, and talk to each other through structured protocols. Users see the
agent's inner life through its notepad. The "self-evolving agent" isn't one that
rewrites its own code — it's one that THINKS about what it needs, writes it down,
and lets humans decide.

---

## Task 2.1: Comprehensive Sub-Agent Spawning Toolkit

**Priority:** Critical | **Est:** 4-5 hours

Not a simple "spawn and forget." A full parent-child agent lifecycle.

### What the toolkit exposes:

```python
class SubAgentToolkit(Toolkit):
    # Spawn
    spawn_sub_agent(
        profile: str,           # "coder", "researcher", "reviewer", etc.
        objective: str,         # what the sub-agent should accomplish
        instructions: str = "", # additional context from parent
        max_cycles: int = 10,   # auto-kill after N cycles
    ) -> str  # returns sub_agent_id

    # Monitor
    list_sub_agents() -> str           # all spawned children + status + current goal
    get_sub_agent_status(agent_id: str) -> str  # detailed: goal progress, steps, suffering
    read_sub_agent_journal(agent_id: str) -> str  # read child's notepad

    # Interact
    send_instruction(agent_id: str, message: str) -> str  # nudge a child
    get_sub_agent_result(agent_id: str) -> str  # get final output/result

    # Lifecycle
    terminate_sub_agent(agent_id: str) -> str  # force-kill
```

### Agent state changes:

- Add to `AgentState`: `spawned_by: str | None`, `max_cycles: int | None`, `cycles_lived: int`
- Add to `HiveStore`: `sub_agents` table (parent_id, child_id, objective, status, result)
- Sub-agents appear in `hive status` with `[sub]` tag showing parent

### Daemon loop changes:

- Sub-agents join the heartbeat loop like normal agents
- Each cycle increments `cycles_lived`; auto-kill when `cycles_lived >= max_cycles`
- On sub-agent death: write result to parent's inbox + store
- On sub-agent goal completion: notify parent, store result
- Depth limit: max 2 levels deep (agent → sub-agent → sub-sub-agent, no deeper)
- Per-parent limit: max 5 active sub-agents

### How it feels:

```
[coder-a1b2c3d4] I need someone to review this code...
  → spawn_sub_agent("reviewer", "Review the sorting implementation in sort.py")
  → [reviewer-e5f6g7h8] spawned by coder-a1b2c3d4 (max 10 cycles)
  → reviewer does its work, writes findings to its journal
  → coder reads reviewer's journal + result
  → coder continues with the feedback
```

### Files:
- **New:** `src/hive/runtime/sub_agents.py` (SubAgentToolkit + SubAgentManager)
- **Modify:** `src/hive/agents/state.py` (spawned_by, max_cycles, cycles_lived)
- **Modify:** `src/hive/memory/store.py` (sub_agents table)
- **Modify:** `src/hive/daemon/loop.py` (sub-agent lifecycle, auto-kill, result relay)
- **Modify:** `src/hive/cli/main.py` (show sub-agents in status)

### Tests:
- Parent spawns child → child runs → child completes → parent gets result
- Max depth enforcement (3rd level spawn rejected)
- Max children enforcement (6th spawn rejected)
- Auto-kill at max_cycles
- Parent reads child journal

---

## Task 2.2: Agent Notepad / Journal System

**Priority:** Critical | **Est:** 3-4 hours

Every agent gets a personal notepad — a place to write thoughts, observations,
tool requests, improvement ideas. This is the "window into agent thinking."

### What the notepad looks like:

```
.hive/journals/{agent_id}/
├── notepad.md          # free-form writing (the main journal)
├── tool_requests.md    # "I wish I had a tool that..."
└── evolution.md        # "I think I could improve by..."
```

### Toolkit:

```python
class NotepadToolkit(Toolkit):
    # Core writing
    write_notepad(content: str) -> str          # append to notepad.md
    read_notepad() -> str                       # read own notepad
    clear_notepad() -> str                      # start fresh

    # Structured sections
    request_tool(
        name: str,             # what they'd call it
        description: str,      # what it should do
        why: str,              # why they need it
    ) -> str                   # appends to tool_requests.md

    write_evolution_note(
        observation: str,      # what they noticed about themselves
        suggestion: str,       # how they think they could improve
    ) -> str                   # appends to evolution.md

    # Reading others (if permitted)
    read_agent_journal(agent_id: str) -> str  # read another agent's notepad
```

### Default system prompt instructions:

Added to every agent's system prompt (configurable per profile):

```
You have a personal notepad. Use it freely:
- Write observations, interesting discoveries, things you want to remember
- Note anything you think the user would want to see
- If you wish you had a tool you don't have, use request_tool to describe it
- If you notice patterns in your own behavior, write evolution notes
- Your notepad persists across cycles — use it as your memory and journal

The user can read your notepad at any time. Write as if someone is watching.
```

### CLI commands:

```bash
hive journal <agent>          # read an agent's notepad
hive journal <agent> --tools  # see tool requests
hive journal <agent> --evo    # see evolution notes
hive journals                 # summary of all agents' latest entries
hive tool-requests            # aggregate all tool requests across agents
```

### How the "evolving agent" works:

1. Agent runs, encounters something it can't do
2. Agent writes: `request_tool("web_search", "Search the internet for information", "I keep needing external data but can only read local files")`
3. Agent writes evolution note: `"I notice I'm good at code review but struggle with architecture decisions. I think I need more context about the project's goals."`
4. User runs `hive tool-requests` → sees what agents want
5. User runs `hive journal coder --evo` → sees how the agent thinks about itself
6. User decides whether to add the requested tool or adjust the agent's profile

The agent isn't self-modifying — it's self-AWARE and communicative about its needs.
The human stays in the loop. But the agent's thinking is visible and persistent.

### Integration with identity system:

- Notepad entries feed into the identity narrative (condensed)
- Evolution notes can update `open_questions` in AgentIdentity
- Tool requests tracked as a new field in specialization: "tools_requested"
- Journal activity creates `JOURNAL_ENTRY` events in the event log

### Files:
- **New:** `src/hive/runtime/notepad.py` (NotepadToolkit + NotepadManager)
- **Modify:** `src/hive/agents/existence.py` (add notepad context to goal generation prompt)
- **Modify:** `src/hive/agents/profile.py` (add notepad instructions to system prompt)
- **Modify:** `src/hive/cli/main.py` (journal commands)
- **Modify:** `src/hive/memory/events.py` (add JOURNAL_ENTRY event type)

### Tests:
- Agent writes to notepad → read back matches
- Tool request stored and retrievable
- Evolution notes stored and retrievable
- Agent A reads Agent B's journal
- CLI commands show correct content
- Journal entries create events

---

## Task 2.3: A2A Interaction Protocol

**Priority:** High | **Est:** 4-5 hours

Currently agents message each other via JSONL inboxes (fire-and-forget). This
adds structured request/response patterns — a real Agent-to-Agent protocol.

### Protocol layers:

```
Layer 3: Collaboration Patterns (mentor, review, debate, chain)
Layer 2: A2A Protocol (request/response, typed messages)
Layer 1: Transport (existing CommsToolkit JSONL + store)
```

### Layer 2: A2A Protocol

**Message types:**

```python
class A2AMessageType(StrEnum):
    REQUEST = "request"       # "I need you to do something"
    RESPONSE = "response"     # "Here's what I did"
    QUERY = "query"           # "What do you think about X?"
    ANSWER = "answer"         # "I think Y because Z"
    REVIEW = "review"         # "Please review this"
    FEEDBACK = "feedback"     # "Here's my review"
    DELEGATE = "delegate"     # "Take ownership of this"
    ACK = "ack"               # "Got it, working on it"
    REJECT = "reject"         # "Can't do that, here's why"

class A2AMessage:
    message_id: str
    message_type: A2AMessageType
    from_agent: str
    to_agent: str
    subject: str              # short description
    body: str                 # full content
    reply_to: str | None      # thread support (message_id of parent)
    priority: int             # 1-5
    expects_reply: bool       # should recipient respond?
    metadata: dict
    ts: datetime
```

**A2A Toolkit (added to agent tools):**

```python
class A2AToolkit(Toolkit):
    # Send
    send_request(to_agent: str, subject: str, body: str) -> str
    send_query(to_agent: str, question: str) -> str
    send_review_request(to_agent: str, content: str, context: str) -> str

    # Receive
    check_inbox(unread_only: bool = True) -> str
    read_message(message_id: str) -> str

    # Respond
    reply(message_id: str, body: str) -> str          # auto-detects type
    accept_request(message_id: str, body: str) -> str  # ACK + start work
    reject_request(message_id: str, reason: str) -> str

    # Discovery
    list_agents() -> str           # who's alive, their role, specialization
    find_agent(capability: str) -> str  # who's best at X (uses specialization)
```

**Storage:** `.hive/a2a/{agent_id}/inbox.jsonl` and `outbox.jsonl`
**Threads:** Messages with `reply_to` form conversation threads

### Layer 3: Collaboration Patterns

New interaction classes that build on A2A:

```python
# src/hive/interactions/patterns/

class ReviewPattern:
    """Agent A submits work → Agent B reviews → feedback → revision loop"""
    # Max 3 revision rounds
    # Reviewer uses feedback message type
    # Author uses response message type
    # Ends when reviewer approves or max rounds hit

class MentorPattern:
    """Senior agent guides junior through a task"""
    # Mentor observes mentee's journal + goals
    # Sends queries about approach
    # Mentee responds with reasoning
    # Mentor sends guidance (not commands)

class DebatePattern:
    """Two agents argue a position, third agent judges"""
    # Structured: opening → rebuttal → closing
    # Judge scores on reasoning quality
    # Uses ExchangeRunner with round_table internally

class ChainPattern:
    """Sequential processing: A → B → C"""
    # Each agent transforms/enriches the output
    # Like a pipeline but each step is an autonomous agent
    # Uses A2A request/response for handoffs

class SwarmTaskPattern:
    """All agents work on same problem independently, compare solutions"""
    # Broadcast the task to N agents
    # Each works independently
    # Collect results, score/compare
    # Uses model benchmarking infrastructure
```

### How A2A integrates with existing systems:

- **Delegation engine** uses A2A protocol under the hood (DELEGATE + ACK)
- **Swarm learning** reads A2A message patterns for collaboration insights
- **Specialization** informs `find_agent()` routing
- **ExchangeRunner** can use A2A messages instead of raw strings
- **Daemon loop** processes A2A inbox each cycle (like nudges)

### CLI:

```bash
hive messages <agent>          # show agent's A2A inbox/outbox
hive threads                   # show active conversation threads
hive interactions              # list active collaboration patterns
```

### Files:
- **New:** `src/hive/interactions/a2a.py` (A2AMessage, A2AProtocol, A2AToolkit)
- **New:** `src/hive/interactions/patterns/review.py`
- **New:** `src/hive/interactions/patterns/mentor.py`
- **New:** `src/hive/interactions/patterns/debate.py`
- **New:** `src/hive/interactions/patterns/chain.py`
- **New:** `src/hive/interactions/patterns/swarm_task.py`
- **Modify:** `src/hive/agents/delegation.py` (use A2A protocol)
- **Modify:** `src/hive/daemon/loop.py` (process A2A inbox per cycle)
- **Modify:** `src/hive/cli/main.py` (messages, threads, interactions commands)

### Tests:
- Request/response round-trip between two agents
- Thread formation (3+ message chain)
- Review pattern: submit → feedback → revision → approval
- Chain pattern: A → B → C with data transformation
- find_agent routes to highest-specialized agent
- Reject handling (agent says no, requester retries or delegates elsewhere)

---

## Task 2.4: Model Benchmarking Mode

**Priority:** High | **Est:** 3-4 hours

Same scenario, different models, compare results. Uses the new tier preset syntax.

- `hive benchmark <scenario> --models anthropic:lite,openai:lite,groq:lite`
- Runs scenario N times per model
- Tracks: goal completion rate, avg steps, cost, suffering trajectory, journal quality
- NEW: Also compares A2A interaction patterns (do different models collaborate differently?)
- Generates Rich comparison table + JSON export
- Built-in benchmarks: "survive-50-cycles", "detective", "collaborate-and-build"

### Files:
- **New:** `src/hive/benchmark/` (runner.py, report.py)
- **New:** `scenarios/benchmarks/` (built-in benchmark configs)
- **Modify:** `src/hive/cli/main.py` (benchmark command)

---

## Task 2.5: Polish Detective Demo + New Scenarios

**Priority:** High | **Est:** 2-3 hours

- Fix JSON parsing for Fireworks/Groq (fallback extraction)
- Update to provider tier presets
- Add Rich output during investigation
- Generate case report
- `hive demo detective` command
- NEW scenario: "startup pitch" — agents pitch ideas, oracle judges
- NEW scenario: "code review chain" — uses ChainPattern from 2.3

### Files:
- **Modify:** `scenarios/detective/run.py`
- **New:** `scenarios/startup/`, `scenarios/code-review/`
- **Modify:** `src/hive/cli/main.py` (demo command)

---

## Task 2.6: Shareable HTML Run Reports

**Priority:** High | **Est:** 3-4 hours

`hive export <run_id>` → standalone HTML file for social sharing.

- Agent cards with journal excerpts (notepad highlights)
- Goal timeline (visual)
- Suffering graphs (SVG)
- A2A message threads (conversation view)
- Tool request summary ("agents wished they had...")
- Evolution notes summary ("agents think they could improve by...")
- Cost breakdown
- Dark theme, <500KB, inline everything

### Files:
- **New:** `src/hive/export/` (html.py, template.py)
- **Modify:** `src/hive/cli/main.py` (export command)

---

## Task 2.7: Web Browsing Toolkit

**Priority:** Medium | **Est:** 2-3 hours

Research agents need internet access.

- `web_fetch(url)` → markdown (HTML stripped)
- `web_search(query)` → DuckDuckGo results (no API key)
- Rate limit 10 req/cycle, truncate 4000 chars
- Uses httpx (already dep) + beautifulsoup4 (add dep)

### Files:
- **Modify:** `src/hive/runtime/toolkits.py` (WebToolkit)
- **Modify:** `pyproject.toml` (add bs4)

---

## Task 2.8: Scheduled Goals

**Priority:** Medium | **Est:** 2 hours

Agent routines. "Every N cycles, do X."

- `schedule_goal(objective, every_n_cycles)` tool
- `schedules` table in SQLite
- Daemon fires scheduled goals when due
- Show in `hive status`

### Files:
- **Modify:** `src/hive/memory/store.py`, `src/hive/daemon/loop.py`, `src/hive/runtime/toolkits.py`, `src/hive/cli/main.py`

---

## Execution Order

```
2.2 Journal/Notepad     ← foundation (agents need somewhere to write before spawning)
2.1 Sub-Agent Spawning  ← builds on journals (sub-agents get journals, parents read them)
2.3 A2A Protocol        ← builds on comms (structured messaging between agents)
2.4 Benchmarking        ← uses all above to compare models
2.5 Detective Demo      ← showcase for A2A + journals
2.6 HTML Reports        ← includes journal excerpts + A2A threads
2.7 Web Browsing        ← independent
2.8 Scheduled Goals     ← independent
```

2.7 and 2.8 can run in parallel with anything after 2.3.

---

## What Makes This Different From Every Other Framework

1. **Journals/Notepads** — No framework gives agents a persistent "inner life" that
   humans can read. This is observability for agent COGNITION, not just execution.

2. **Tool Requests** — Instead of agents modifying themselves (dangerous, unpredictable),
   they REQUEST capabilities. Human stays in the loop. Agent stays self-aware.

3. **A2A Protocol** — Not just "agents call each other." Typed messages with threads,
   priorities, accept/reject. Real collaboration patterns (review, mentor, debate, chain).

4. **Sub-Agent Spawning** — Agents create specialized helpers for subtasks. Parent-child
   lifecycle with result relay. Self-organizing teams, not choreographed workflows.

5. **Evolution Notes** — The agent says "I think I could improve by..." and the user
   decides. Controlled self-evolution. Visible, auditable, fascinating to watch.
