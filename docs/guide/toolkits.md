# Built-in Toolkits

Hive ships with 14 toolkits. Agents can use any combination. All toolkits follow the same pattern: instantiate and pass to `Agent(toolkits=[...])`.

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
