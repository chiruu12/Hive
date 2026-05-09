"""Tests for runtime type system."""

from hive.runtime.types import (
    GenerateResult,
    Message,
    Role,
    Task,
    TaskResult,
    TaskStatus,
    ToolCall,
    ToolResult,
)


class TestMessage:
    def test_system_factory(self):
        msg = Message.system("You are helpful.")
        assert msg.role == Role.SYSTEM
        assert msg.content == "You are helpful."
        assert msg.tool_calls == ()

    def test_user_factory(self):
        msg = Message.user("Hello")
        assert msg.role == Role.USER
        assert msg.content == "Hello"

    def test_assistant_factory_text_only(self):
        msg = Message.assistant("I can help.")
        assert msg.role == Role.ASSISTANT
        assert msg.content == "I can help."
        assert msg.tool_calls == ()

    def test_assistant_factory_with_tool_calls(self):
        tc = ToolCall(id="tc-1", name="search", arguments={"q": "test"})
        msg = Message.assistant("Searching...", [tc])
        assert msg.role == Role.ASSISTANT
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"

    def test_tool_result_factory(self):
        msg = Message.tool_result("tc-1", "found 5 results", name="search")
        assert msg.role == Role.TOOL
        assert msg.tool_call_id == "tc-1"
        assert msg.content == "found 5 results"
        assert msg.name == "search"

    def test_tool_result_error(self):
        msg = Message.tool_result("tc-1", "not found", is_error=True)
        assert msg.role == Role.TOOL

    def test_message_is_frozen(self):
        msg = Message.user("hello")
        try:
            msg.content = "changed"  # type: ignore[misc]
            assert False, "Should raise"
        except AttributeError:
            pass


class TestToolCall:
    def test_creation(self):
        tc = ToolCall(id="abc", name="read_file", arguments={"path": "/tmp"})
        assert tc.id == "abc"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/tmp"}

    def test_frozen(self):
        tc = ToolCall(id="a", name="b", arguments={})
        try:
            tc.name = "changed"  # type: ignore[misc]
            assert False
        except AttributeError:
            pass


class TestToolResult:
    def test_success(self):
        tr = ToolResult(tool_call_id="tc-1", content="ok")
        assert not tr.is_error

    def test_error(self):
        tr = ToolResult(tool_call_id="tc-1", content="fail", is_error=True)
        assert tr.is_error


class TestTask:
    def test_defaults(self):
        t = Task(instruction="do something")
        assert t.instruction == "do something"
        assert t.id.startswith("task-")
        assert t.max_steps == 25
        assert t.context == {}

    def test_custom(self):
        t = Task(instruction="x", id="my-task", max_steps=10, context={"k": "v"})
        assert t.id == "my-task"
        assert t.max_steps == 10


class TestTaskResult:
    def test_creation(self):
        r = TaskResult(
            task_id="t-1",
            status=TaskStatus.COMPLETED,
            output="done",
            steps_taken=3,
            tool_calls_made=5,
        )
        assert r.status == TaskStatus.COMPLETED
        assert r.steps_taken == 3


class TestGenerateResult:
    def test_creation(self):
        msg = Message.assistant("hello")
        result = GenerateResult(
            message=msg,
            model="claude-haiku-4-5",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            duration_ms=500,
        )
        assert result.message.content == "hello"
        assert result.model == "claude-haiku-4-5"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cost_usd == 0.001
        assert result.duration_ms == 500

    def test_defaults(self):
        msg = Message.assistant("hi")
        result = GenerateResult(message=msg)
        assert result.model == ""
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.cost_usd is None
        assert result.duration_ms is None

    def test_frozen(self):
        msg = Message.assistant("hi")
        result = GenerateResult(message=msg)
        try:
            result.model = "changed"  # type: ignore[misc]
            assert False, "Should raise"
        except AttributeError:
            pass
