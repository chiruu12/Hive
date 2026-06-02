"""Pure conversions between Hive ``Message``s and provider wire formats.

Extracted from the provider classes so the logic is shared and unit-testable
without constructing an SDK client. OpenAI-compatible providers (Groq, Fireworks,
Ollama, LM Studio, OpenRouter) all reuse the OpenAI helpers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hive.runtime.types import Message, Role, ToolCall

logger = logging.getLogger(__name__)


def messages_to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert Hive messages to the OpenAI chat-completions message format."""
    api_messages: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == Role.SYSTEM:
            api_messages.append({"role": "system", "content": msg.content})
        elif msg.role == Role.USER:
            api_messages.append({"role": "user", "content": msg.content})
        elif msg.role == Role.ASSISTANT:
            entry: dict[str, Any] = {"role": "assistant"}
            if msg.content:
                entry["content"] = msg.content
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            if not msg.content and not msg.tool_calls:
                entry["content"] = ""
            api_messages.append(entry)
        elif msg.role == Role.TOOL:
            api_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                }
            )

    return api_messages


def tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Hive tool schemas to OpenAI function-tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def openai_response_to_message(response: Any) -> Message:
    """Convert an OpenAI chat-completion response to a Hive assistant Message."""
    choice = response.choices[0]
    msg = choice.message
    content = msg.content or ""

    tool_calls: list[ToolCall] = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                logger.warning(
                    "Malformed JSON arguments for tool %r; treating as no args. Raw: %r",
                    tc.function.name,
                    tc.function.arguments,
                )
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

    return Message.assistant(content, tool_calls or None)


def messages_to_anthropic(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Convert Hive messages to Anthropic's (system, messages) format.

    Anthropic carries the system prompt separately and groups consecutive tool
    results into a single user message.
    """
    system = ""
    api_messages: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == Role.SYSTEM:
            system = (system + "\n" + msg.content).strip()
            continue

        if msg.role == Role.USER:
            if pending_tool_results:
                api_messages.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []
            api_messages.append({"role": "user", "content": msg.content})

        elif msg.role == Role.ASSISTANT:
            if pending_tool_results:
                api_messages.append({"role": "user", "content": pending_tool_results})
                pending_tool_results = []

            content: list[dict[str, Any]] = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                content.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments,
                    }
                )
            api_messages.append({"role": "assistant", "content": content or msg.content})

        elif msg.role == Role.TOOL:
            tool_result: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": msg.tool_call_id,
                "content": msg.content,
            }
            if msg.is_error:
                tool_result["is_error"] = True
            pending_tool_results.append(tool_result)

    if pending_tool_results:
        api_messages.append({"role": "user", "content": pending_tool_results})

    return system, api_messages


def anthropic_response_to_message(response: Any) -> Message:
    """Convert an Anthropic messages response to a Hive assistant Message."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

    return Message.assistant("\n".join(text_parts), tool_calls or None)
