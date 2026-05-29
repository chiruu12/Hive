"""Tests for the shared message-conversion functions (A5)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from hive.models.conversion import (
    anthropic_response_to_message,
    messages_to_anthropic,
    messages_to_openai,
    openai_response_to_message,
    tools_to_openai,
)
from hive.runtime.types import Message, Role, ToolCall

_TOOLS = [{"name": "add", "description": "Add", "input_schema": {"type": "object"}}]


class TestOpenAIConversion:
    def test_roles_mapped(self) -> None:
        msgs = [
            Message.system("sys"),
            Message.user("hi"),
            Message.assistant("ok"),
        ]
        out = messages_to_openai(msgs)
        assert [m["role"] for m in out] == ["system", "user", "assistant"]
        assert out[1]["content"] == "hi"

    def test_assistant_tool_calls_serialized(self) -> None:
        msg = Message.assistant("", [ToolCall(id="c1", name="add", arguments={"a": 1})])
        out = messages_to_openai([msg])[0]
        assert out["tool_calls"][0]["id"] == "c1"
        assert json.loads(out["tool_calls"][0]["function"]["arguments"]) == {"a": 1}

    def test_tool_result_message(self) -> None:
        out = messages_to_openai([Message.tool_result("c1", "42", name="add")])[0]
        assert out == {"role": "tool", "tool_call_id": "c1", "content": "42"}

    def test_tools_to_openai_shape(self) -> None:
        out = tools_to_openai(_TOOLS)[0]
        assert out["type"] == "function"
        assert out["function"]["name"] == "add"
        assert out["function"]["parameters"] == {"type": "object"}

    def test_response_to_message_with_tool_calls(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="thinking",
                        tool_calls=[
                            SimpleNamespace(
                                id="c1",
                                function=SimpleNamespace(name="add", arguments='{"a": 1}'),
                            )
                        ],
                    )
                )
            ]
        )
        msg = openai_response_to_message(response)
        assert msg.role == Role.ASSISTANT
        assert msg.content == "thinking"
        assert msg.tool_calls[0].name == "add"
        assert msg.tool_calls[0].arguments == {"a": 1}

    def test_response_to_message_bad_json_args(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="c1", function=SimpleNamespace(name="x", arguments="not json")
                            )
                        ],
                    )
                )
            ]
        )
        msg = openai_response_to_message(response)
        assert msg.tool_calls[0].arguments == {}


class TestAnthropicConversion:
    def test_system_separated_and_collected(self) -> None:
        system, msgs = messages_to_anthropic(
            [Message.system("a"), Message.system("b"), Message.user("hi")]
        )
        assert system == "a\nb"
        assert msgs == [{"role": "user", "content": "hi"}]

    def test_assistant_tool_use_blocks(self) -> None:
        msg = Message.assistant("plan", [ToolCall(id="c1", name="add", arguments={"a": 1})])
        _, out = messages_to_anthropic([msg])
        content = out[0]["content"]
        assert content[0] == {"type": "text", "text": "plan"}
        assert content[1]["type"] == "tool_use"
        assert content[1]["id"] == "c1"

    def test_consecutive_tool_results_grouped(self) -> None:
        msgs = [
            Message.tool_result("c1", "r1"),
            Message.tool_result("c2", "r2", is_error=True),
            Message.user("next"),
        ]
        _, out = messages_to_anthropic(msgs)
        # Both tool results land in one user message, then the user turn follows.
        assert out[0]["role"] == "user"
        assert len(out[0]["content"]) == 2
        assert out[0]["content"][1]["is_error"] is True
        assert out[1] == {"role": "user", "content": "next"}

    def test_response_to_message(self) -> None:
        response = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="hello"),
                SimpleNamespace(type="tool_use", id="c1", name="add", input={"a": 1}),
            ]
        )
        msg = anthropic_response_to_message(response)
        assert msg.content == "hello"
        assert msg.tool_calls[0].name == "add"
        assert msg.tool_calls[0].arguments == {"a": 1}
