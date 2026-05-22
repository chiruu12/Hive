"""Production Hardening — all the reliability features in one place.

Demonstrates:
1. Retry/backoff behavior (automatic, built into all providers)
2. Budget enforcement with 80% warnings (cost + token)
3. Conversation history persistence (JSON logs)
4. Better error messages (agent context in all logs)
5. Safe toolkit binding (bind vs rebind)
6. Config validation (threshold ordering, heartbeat, balance)
7. Per-agent timeout in daemon (cycle_timeout)

Run: uv run python examples/21_production_hardening.py
"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hive import (
    Agent,
    Task,
    Toolkit,
    ToolkitAlreadyBoundError,
    tool,
)
from hive.config import DaemonConfig, HiveConfig, SufferingConfig
from hive.models.base import BaseProvider
from hive.runtime.types import GenerateResult, Message, ToolCall

logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Mock provider for examples (no API key needed)
# ---------------------------------------------------------------------------
class DemoProvider(BaseProvider):
    """A provider that returns canned responses for demo purposes."""

    def __init__(self, responses: list[Message], cost: float = 0.005) -> None:
        super().__init__("demo-model")
        self._responses = list(responses)
        self._idx = 0
        self._cost = cost

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> GenerateResult:
        msg = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return GenerateResult(
            message=msg,
            model="demo-model",
            input_tokens=100,
            output_tokens=50,
            cost_usd=self._cost,
        )

    async def generate_structured(self, *a: Any, **kw: Any) -> Any:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 1. Budget enforcement with 80% warnings
# ---------------------------------------------------------------------------
async def demo_budget_enforcement() -> None:
    print("\n=== 1. Budget Enforcement ===")

    class Calculator(Toolkit):
        @tool()
        def add(self, a: int, b: int) -> str:
            """Add two numbers.

            Args:
                a: First number.
                b: Second number.
            """
            return str(a + b)

    responses = [
        Message.assistant(
            "Let me calculate.",
            [ToolCall(id="t1", name="add", arguments={"a": 2, "b": 3})],
        ),
        Message.assistant(
            "One more.",
            [ToolCall(id="t2", name="add", arguments={"a": 5, "b": 7})],
        ),
        Message.assistant("Done! 2+3=5 and 5+7=12."),
    ]

    # cost=0.005 per call, budget=$0.01 -> stops at call 2
    provider = DemoProvider(responses, cost=0.005)
    agent = Agent(
        name="budget-demo",
        model=provider,
        toolkits=[Calculator()],
        max_cost_usd=0.01,
    )

    result = await agent.run(Task(instruction="Add 2+3 and 5+7"))
    print(f"  Status: {result.status}")
    print(f"  Error:  {result.error}")
    print(f"  Steps:  {result.steps_taken}")
    print("  -> Agent stopped because cost budget was exceeded")

    # run_once also enforces budget
    provider2 = DemoProvider([Message.assistant("ok")], cost=0.02)
    agent2 = Agent(name="once-budget", model=provider2, max_cost_usd=0.01)
    text = await agent2.run_once("hi")
    print(f"  run_once result: {text!r}")


# ---------------------------------------------------------------------------
# 2. Conversation history persistence
# ---------------------------------------------------------------------------
async def demo_conversation_logging() -> None:
    print("\n=== 2. Conversation History Persistence ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = Path(tmpdir) / "conv_logs"
        provider = DemoProvider([Message.assistant("The answer is 42.")])
        agent = Agent(
            name="logger-demo",
            model=provider,
            conversation_log_dir=log_dir,
        )

        result = await agent.run(Task(instruction="What is the meaning of life?"))
        print(f"  Status: {result.status}")

        # Check what was written
        agent_dir = log_dir / "logger-demo"
        log_files = list(agent_dir.glob("*.json"))
        print(f"  Log files created: {len(log_files)}")

        data = json.loads(log_files[0].read_text())
        print(f"  Log keys: {list(data.keys())}")
        print(f"  Messages logged: {len(data['messages'])}")
        print(f"  Total cost: ${data['total_cost_usd']:.4f}")
        print(f"  Status in log: {data['status']}")


# ---------------------------------------------------------------------------
# 3. Safe toolkit binding (bind vs rebind)
# ---------------------------------------------------------------------------
async def demo_safe_binding() -> None:
    print("\n=== 3. Safe Toolkit Binding ===")

    class Greeter(Toolkit):
        @tool()
        def greet(self) -> str:
            """Say hello."""
            return f"Hello from agent {self._agent_id}!"

    tk = Greeter()

    # First bind works fine
    tk.bind("agent-alpha")
    print(f"  Bound to: {tk._agent_id}")

    # Same agent is idempotent
    tk.bind("agent-alpha")
    print("  Same-agent bind: OK (idempotent)")

    # Different agent raises
    try:
        tk.bind("agent-beta")
    except ToolkitAlreadyBoundError as e:
        print("  Different-agent bind: ToolkitAlreadyBoundError raised")
        print(f"    -> {e}")

    # rebind() is the escape hatch for server patterns
    tk.rebind("agent-beta")
    print(f"  After rebind: {tk._agent_id}")

    # Tools use the rebound agent_id
    greet_tool = tk.get_tools()[0]
    result = await greet_tool.call()
    print(f"  Tool output: {result}")


# ---------------------------------------------------------------------------
# 4. Config validation
# ---------------------------------------------------------------------------
def demo_config_validation() -> None:
    print("\n=== 4. Config Validation ===")

    # Valid config
    cfg = HiveConfig()
    print(f"  Default thresholds: {cfg.suffering.threshold_prominent} < "
          f"{cfg.suffering.threshold_constrained} < "
          f"{cfg.suffering.threshold_dominant} < "
          f"{cfg.suffering.threshold_crisis}")

    # Invalid threshold ordering
    try:
        SufferingConfig(threshold_prominent=0.8, threshold_constrained=0.5)
    except ValidationError:
        print("  Bad thresholds: ValidationError caught")

    # Invalid heartbeat
    try:
        DaemonConfig(heartbeat=0)
    except ValidationError:
        print("  heartbeat=0: ValidationError caught")

    # Environment validation
    warnings = cfg.validate_environment()
    if warnings:
        print(f"  Environment warnings: {warnings}")
    else:
        print("  Environment: all API keys present")


# ---------------------------------------------------------------------------
# 5. Error messages with agent context
# ---------------------------------------------------------------------------
async def demo_error_context() -> None:
    print("\n=== 5. Error Messages with Agent Context ===")

    # Model failure -> log includes agent name, step, model
    class FailProvider(BaseProvider):
        @property
        def available(self) -> bool:
            return True

        async def generate_with_metadata(self, *a: Any, **kw: Any) -> Any:
            raise RuntimeError("API rate limit")

        async def generate_structured(self, *a: Any, **kw: Any) -> Any:
            raise NotImplementedError

    agent = Agent(name="error-demo", model=FailProvider("broken-model"))
    result = await agent.run(Task(instruction="fail please"))
    print(f"  Status: {result.status}")
    print(f"  Error: {result.error}")
    print("  -> Check logs: includes 'Agent error-demo', step number, model name")

    # Unknown tool -> agent name in warning
    responses = [
        Message.assistant(
            "calling", [ToolCall(id="t1", name="nonexistent", arguments={})]
        ),
        Message.assistant("ok"),
    ]
    agent2 = Agent(name="tool-err-demo", model=DemoProvider(responses))
    result2 = await agent2.run(Task(instruction="use fake tool"))
    print(f"  Unknown tool handled: status={result2.status}")
    print("  -> Check logs: 'Agent tool-err-demo: unknown tool nonexistent'")


# ---------------------------------------------------------------------------
# 6. Retry behavior (built into all providers)
# ---------------------------------------------------------------------------
def demo_retry_info() -> None:
    print("\n=== 6. Retry/Backoff (built into all providers) ===")
    print("  All 7 providers (Anthropic, OpenAI, Groq, Fireworks,")
    print("  Ollama, LMStudio, OpenRouter) automatically retry on:")
    print("    - 429 (rate limit)")
    print("    - 500, 502, 503, 529 (server errors)")
    print("    - Connection errors (httpx.ConnectError, ConnectionError)")
    print("    - Timeout errors")
    print("  Non-retryable (fail immediately):")
    print("    - 400 (bad request)")
    print("    - 401 (auth failure)")
    print("    - 403 (forbidden)")
    print("  Backoff: 1s, 2s, 4s (exponential, 3 retries max)")


# ---------------------------------------------------------------------------
# 7. Per-agent timeout
# ---------------------------------------------------------------------------
def demo_timeout_info() -> None:
    print("\n=== 7. Per-Agent Timeout (daemon mode) ===")
    cfg = DaemonConfig()
    print(f"  Default cycle_timeout: {cfg.cycle_timeout}s")
    print("  When a daemon agent's cycle exceeds this limit:")
    print("    1. asyncio.wait_for raises TimeoutError")
    print("    2. Active goal is abandoned")
    print("    3. Agent status set to IDLE")
    print("    4. Daemon continues with next agent")
    print("  Set cycle_timeout=0 to disable")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    print("Hive Production Hardening Examples")
    print("=" * 50)

    await demo_budget_enforcement()
    await demo_conversation_logging()
    await demo_safe_binding()
    demo_config_validation()
    await demo_error_context()
    demo_retry_info()
    demo_timeout_info()

    print("\n" + "=" * 50)
    print("All examples complete.")


if __name__ == "__main__":
    asyncio.run(main())
