# Built-in Toolkits

Hive ships with 18 toolkits. Agents can use any combination. All toolkits follow the same pattern: instantiate and pass to `Agent(toolkits=[...])`.

## FileToolkit

Read, write, edit, and list files in the agent's workspace.

```python
from hive.runtime import FileToolkit

tk = FileToolkit(workspace="./workspaces/coder")
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `file_read` | `path`, `offset=0`, `limit=500` | Read a file (paginated) |
| `file_write` | `path`, `content` | Write content to a file (creates dirs) |
| `file_edit` | `path`, `old_text`, `new_text` | Replace a string in a file |
| `list_dir` | `path="."`, `max_depth=2` | List directory tree |

## ShellToolkit

Execute shell commands with security restrictions.

```python
from hive.runtime import ShellToolkit

tk = ShellToolkit(workspace="./workspaces/coder", timeout=30, restrict=True)
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `shell_exec` | `command` | Execute a shell command |

When `restrict=True` (default), only whitelisted commands are allowed (71 commands including `ls`, `cat`, `python`, `git`, `npm`, `pytest`, `curl`, etc.) and shell operators (`&&`, `||`, `|`, `;`, `` ` ``) are blocked.

## GitToolkit

Git operations within the agent's workspace.

```python
from hive.runtime import GitToolkit

tk = GitToolkit(workspace="./workspaces/coder")
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `git_status` | | Show working tree status |
| `git_diff` | `staged=False` | Show changes (optionally staged only) |
| `git_log` | `count=10` | Show recent commit history |
| `git_add` | `path="."` | Stage files |
| `git_commit` | `message` | Create a commit |
| `git_init` | | Initialize a new repository |

## WebToolkit

Fetch web pages and search with DuckDuckGo.

```python
from hive.tools.web.toolkit import WebToolkit

tk = WebToolkit(max_requests_per_cycle=10)
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `web_fetch` | `url` | Fetch a page and return readable text (max 4000 chars) |
| `web_search` | `query` | Search DuckDuckGo and return results |

## NotepadToolkit

Persistent scratchpad for agent journaling and reflection. Survives across daemon cycles.

```python
from hive.tools.notepad.toolkit import NotepadToolkit, Preset

tk = NotepadToolkit(preset=Preset.journal())
```

**Presets** control the notepad's guidance instructions:

| Preset | Purpose |
|--------|---------|
| `Preset.default()` | General-purpose scratchpad |
| `Preset.journal()` | Personal journal for reflection and emotional state |
| `Preset.evolution()` | Track learning, growth, and strategy changes |
| `Preset.tool_requests()` | Log tool needs and missing capabilities |
| `Preset.custom(instructions)` | Custom guidance text |

| Tool | Parameters | Description |
|------|-----------|-------------|
| `write_notepad` | `content` | Append an entry to the notepad |
| `read_notepad` | | Read your notepad contents |
| `clear_notepad` | | Clear and start fresh |
| `read_agent_notepad` | `agent_id` | Read another agent's notepad |

## MemoryToolkit

Simple key-value persistent memory for agents.

```python
from hive import MemoryToolkit

tk = MemoryToolkit()
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `memory_set` | `key`, `value` | Store a value for later retrieval |
| `memory_get` | `key` | Retrieve a previously stored value |

For similarity-based memory search, see [Semantic Memory](daemon-mode.md#semantic-memory).

## CommsToolkit

Simple message passing between agents via file-backed inboxes.

```python
from hive import CommsToolkit

tk = CommsToolkit()
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `send_message` | `target_agent`, `message` | Send a message to another agent |
| `read_inbox` | | Read all messages from other agents |

For structured messaging with typed protocols, use [A2AToolkit](#a2atoolkit) instead.

## A2AToolkit

Agent-to-agent messaging with 9 typed message types, threading, and priority.

```python
from hive.tools.a2a.toolkit import A2AToolkit
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `send_request` | `to_agent`, `subject`, `body`, `priority=4` | Send a request expecting a response |
| `send_query` | `to_agent`, `question` | Ask another agent a question |
| `send_review_request` | `to_agent`, `subject`, `body` | Request a peer review |
| `check_inbox` | `unread_only=True` | Check inbox for messages |
| `read_message` | `message_id` | Read a specific message |
| `reply` | `message_id`, `body` | Reply (auto-selects response type) |
| `accept_request` | `message_id`, `body=""` | Accept a request/delegation with ACK |
| `reject_request` | `message_id`, `reason=""` | Reject a request with reason |
| `list_agents` | | List all agents you can message |
| `find_agent` | `capability` | Find the best agent for a task type |

**Message types:** REQUEST, RESPONSE, QUERY, ANSWER, REVIEW, FEEDBACK, DELEGATE, ACK, REJECT.

Replies auto-map: REQUEST->RESPONSE, QUERY->ANSWER, REVIEW->FEEDBACK, DELEGATE->ACK or REJECT.

## DelegationToolkit

Delegate tasks to other agents and check results.

**For daemon agents:**

```python
from hive.runtime import DaemonDelegationToolkit
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `delegate_task` | `agent_name`, `objective` | Delegate a task to another agent |
| `check_delegation` | `delegation_id` | Check status of a delegation |
| `list_peers` | | List alive agents to delegate to |

**For standalone agents:**

```python
from hive.runtime import DelegationToolkit
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `delegate_task` | `agent_name`, `task` | Delegate and get result |
| `list_agents` | | List available agents |

## SubAgentToolkit

Spawn child agents to handle subtasks. Max depth 2, max 5 children per agent.

```python
from hive.tools.sub_agents.toolkit import SubAgentToolkit
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `spawn_sub_agent` | `name`, `role`, `task`, `max_cycles=10` | Spawn a child agent |
| `list_sub_agents` | | List your sub-agents and status |
| `get_sub_agent_status` | `sub_agent_id` | Detailed sub-agent status |
| `read_sub_agent_journal` | `sub_agent_id` | Read sub-agent's notepad |
| `send_instruction` | `sub_agent_id`, `instruction` | Send direction to sub-agent |
| `get_sub_agent_result` | `sub_agent_id` | Get result from completed sub-agent |
| `terminate_sub_agent` | `sub_agent_id` | Force-kill a sub-agent |

Expired sub-agents are auto-killed by the daemon each cycle.

## ScheduleToolkit

Schedule recurring goals that fire every N daemon cycles.

```python
from hive.tools.schedule.toolkit import ScheduleToolkit
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `schedule_goal` | `objective`, `every_n_cycles` | Create a recurring goal |
| `list_schedules` | | List active schedules |
| `cancel_schedule` | `schedule_id` | Cancel a schedule |

## WorldToolkit

Interact with the simulated economy -- jobs, money, skills, gambling.

```python
from hive.tools.world.toolkit import WorldToolkit
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `work` | | Perform your job to earn salary |
| `apply_job` | `job_id` | Apply for a job (must be unemployed) |
| `quit_job` | | Quit current job |
| `learn` | `skill_name` | Study a skill (costs money) |
| `gamble` | `game="blackjack"`, `wager=10.0` | Bet on blackjack or lottery |
| `query_world` | `query_type="status"` | Query jobs/skills/finances/status/market |

**Available jobs:** Analyst, Reviewer, Researcher, Teacher, Architect -- each with salary and skill requirements.

**Learnable skills:** analysis, testing, writing, coding, research, teaching.

## MCPToolkit

Connect to external MCP servers and use their tools.

```python
from hive import MCPToolkit

async with await MCPToolkit.from_stdio("npx", ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]) as tk:
    agent = Agent(name="bot", model=Anthropic.lite(), toolkits=[tk])
```

| Method | Description |
|--------|-------------|
| `from_stdio(command, args, env, cwd)` | Connect via stdio transport |
| `from_config(config)` | Connect from config dict |
| `get_tools()` | Get Hive Tool objects from MCP server |
| `close()` | Close connection |

## LinkToolkit

Save, search, and scrape web links. Uses SemanticMemory for storage with metadata filtering.

```python
from hive.tools.links import LinkToolkit

# Daemon mode (shared memory):
tk = LinkToolkit(memory=semantic_memory)

# Standalone mode:
tk = LinkToolkit(memory_dir=".hive")
tk.bind("my-agent")
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `save_link` | `url`, `tags=""`, `notes=""` | Save a URL -- auto-scrapes title and summary |
| `search_links` | `query`, `limit=5` | Search saved links by content or tags |
| `list_links` | `limit=10` | List recently saved links |
| `scrape_link` | `url` | Fetch and return page content as markdown (4000 char limit) |

Links are stored in SemanticMemory with `metadata.type = "link"`, so they coexist with knowledge notes without interference.

## TaskToolkit

Create, list, complete, reopen, update, and delete tasks. Persisted in SQLite via HiveStore.

```python
from hive.tools.tasks import TaskToolkit

# Daemon mode (shared store):
tk = TaskToolkit(store=hive_store)

# Standalone mode:
tk = TaskToolkit(db_path="app.db")
tk.bind("my-agent")
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `create_task` | `description`, `priority="medium"`, `due=""` | Create a task (priority: high/medium/low) |
| `list_tasks` | `status="pending"`, `priority=""` | List tasks filtered by status and optionally priority |
| `complete_task` | `task_id` | Mark a task as done |
| `uncomplete_task` | `task_id` | Reopen a completed task, setting it back to pending |
| `update_task` | `task_id`, `description=""`, `priority=""`, `due=""` | Update one or more fields on an existing task |
| `delete_task` | `task_id` | Delete a task |

Host applications can also call `query_tasks(status, priority)` and `query_all_tasks(status, priority)` for programmatic access without going through the agent tool layer.

## KnowledgeToolkit

Save, search, update, and delete notes in a semantic knowledge base. Uses TF-IDF similarity search by default, with an optional ChromaDB vector backend.

```python
from hive.tools.knowledge import KnowledgeToolkit

# Daemon mode (shared memory):
tk = KnowledgeToolkit(memory=semantic_memory)

# Standalone mode:
tk = KnowledgeToolkit(memory_dir=".hive")
tk.bind("my-agent")
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `save_note` | `content`, `tags=""` | Save a note with optional comma-separated tags |
| `search_notes` | `query`, `limit="5"` | Search notes by topic or keywords |
| `list_recent_notes` | `limit="10"` | List most recent notes chronologically |
| `delete_note` | `note_id` | Delete a note by ID |
| `update_note` | `note_id`, `content=""`, `tags=""` | Update a note's content or tags in-place, preserving its ID and timestamp |

Notes are agent-isolated -- each agent has its own memory directory. Host applications can call `query_recent(limit)` for programmatic access.

## AlarmToolkit

Set timed alarms that fire macOS notifications. Supports both relative delays and absolute times.

```python
from hive.tools.alarms import AlarmToolkit

# Daemon mode (shared store):
tk = AlarmToolkit(store=hive_store)

# Standalone mode:
tk = AlarmToolkit(db_path="app.db")
tk.bind("my-agent")
```

| Tool | Parameters | Description |
|------|-----------|-------------|
| `set_alarm` | `description`, `hours="0"`, `minutes="0"`, `seconds="0"` | Set an alarm that fires after a relative delay |
| `set_alarm_at` | `description`, `time` | Set an alarm for an absolute time -- accepts "3pm", "15:00", "tomorrow 9am", "2026-06-01 14:30" |
| `list_alarms` | | List all pending alarms |
| `cancel_alarm` | `alarm_id` | Cancel a pending alarm |

Use `AlarmChecker` to poll for due alarms and fire notifications in a background loop. The `set_alarm_at` tool uses `python-dateutil` for time parsing, interprets naive times as local timezone, and auto-rolls time-only inputs to tomorrow if the time has already passed today.

## Using Multiple Toolkits

```python
from hive import Agent
from hive.runtime import FileToolkit, ShellToolkit, GitToolkit
from hive.models.anthropic import Anthropic

agent = Agent(
    name="coder",
    model=Anthropic.lite(),
    toolkits=[FileToolkit(), ShellToolkit(), GitToolkit()],
)
```

Or use zero-config to get all toolkits at once:

```python
from hive import Agent, collect_tools
from hive.runtime import FileToolkit, ShellToolkit, GitToolkit, WebToolkit
from hive.models.anthropic import Anthropic

agent = Agent(
    name="coder",
    model=Anthropic.lite(),
    toolkits=[FileToolkit(), ShellToolkit(), GitToolkit()],
)
```
