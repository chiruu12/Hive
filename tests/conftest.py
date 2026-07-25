"""Shared fixtures for Hive tests."""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from hive.config import HiveConfig, set_config
from hive.models.base import GenerateResult
from hive.runtime.types import Message, Role


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(autouse=True)
def _reset_config():
    set_config(HiveConfig())
    yield
    set_config(HiveConfig())


class MockProvider:
    """Reusable mock LLM provider with scriptable responses.

    Usage:
        provider = MockProvider([Message.assistant("hello")])
        result = await provider.generate_with_metadata(messages=[...])

    Supports:
        - Sequential response queue (pops next response per call)
        - Call recording for assertions
        - Optional tool-call responses
        - Failure injection via `fail_after` or `fail_with`
    """

    def __init__(
        self,
        responses: list[Message] | None = None,
        *,
        fail_after: int | None = None,
        fail_with: Exception | None = None,
    ):

        self._responses = list(responses or [Message(role=Role.ASSISTANT, content="ok")])
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []
        self._fail_after = fail_after
        self._fail_with = fail_with or RuntimeError("Mock provider failure")
        self.model_name = "mock-model"

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> GenerateResult:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )

        if self._fail_after is not None and self._call_count >= self._fail_after:
            raise self._fail_with

        idx = min(self._call_count, len(self._responses) - 1)
        response = self._responses[idx]
        self._call_count += 1

        return GenerateResult(
            message=response,
            model=self.model_name,
            input_tokens=len(str(response.content)) // 4,
            output_tokens=len(str(response.content)) // 4,
            cost_usd=0.001,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        result = await self.generate_with_metadata(messages, **kwargs)
        import json

        try:
            start = result.message.content.find("{")
            end = result.message.content.rfind("}")
            if start != -1 and end > start:
                data = json.loads(result.message.content[start : end + 1])
                return response_model(**data)
        except Exception:
            pass
        return response_model()

    def assert_called_n(self, n: int) -> None:
        assert len(self.calls) == n, f"Expected {n} calls, got {len(self.calls)}"

    def last_call_messages(self) -> list[Message]:
        return self.calls[-1]["messages"]

    def last_call_tools(self) -> list[dict[str, Any]] | None:
        return self.calls[-1]["tools"]


@pytest.fixture
def mock_provider():
    """Create a MockProvider with default 'ok' response."""
    return MockProvider()


@pytest.fixture
def make_mock_provider():
    """Factory fixture: call with a list of Messages to get a configured MockProvider."""

    def _factory(responses: list[Message], **kwargs: Any) -> MockProvider:
        return MockProvider(responses, **kwargs)

    return _factory
