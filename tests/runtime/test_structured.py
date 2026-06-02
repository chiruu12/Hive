"""Tests for structured output — Pydantic schema extraction and response parsing."""

from __future__ import annotations

from typing import Any, Literal

import pytest
from pydantic import BaseModel

from hive.models.base import BaseProvider
from hive.runtime.structured import (
    StructuredGenerateResult,
    generate_structured_fallback,
    parse_structured_response,
    pydantic_to_json_schema,
    pydantic_to_response_format,
)
from hive.runtime.types import (
    GenerateResult,
    Message,
    StructuredTaskResult,
    Task,
    TaskStatus,
)


class SimpleModel(BaseModel):
    name: str
    age: int
    active: bool


class NestedModel(BaseModel):
    title: str
    author: SimpleModel


class OptionalModel(BaseModel):
    required_field: str
    optional_field: str | None = None


class EnumModel(BaseModel):
    status: Literal["active", "inactive"]
    priority: int


class TestPydanticToJsonSchema:
    def test_basic_model(self) -> None:
        schema = pydantic_to_json_schema(SimpleModel)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["age"]["type"] == "integer"
        assert schema["properties"]["active"]["type"] == "boolean"
        assert "title" not in schema

    def test_strips_titles(self) -> None:
        schema = pydantic_to_json_schema(SimpleModel)
        assert "title" not in schema
        for prop in schema["properties"].values():
            assert "title" not in prop

    def test_adds_additional_properties_false(self) -> None:
        schema = pydantic_to_json_schema(SimpleModel)
        assert schema.get("additionalProperties") is False

    def test_nested_model_inlines_defs(self) -> None:
        schema = pydantic_to_json_schema(NestedModel)
        assert "$defs" not in schema
        assert "$ref" not in str(schema)
        author_schema = schema["properties"]["author"]
        assert author_schema["type"] == "object"
        assert "name" in author_schema["properties"]

    def test_optional_field(self) -> None:
        schema = pydantic_to_json_schema(OptionalModel)
        assert "required_field" in schema["properties"]
        assert "optional_field" in schema["properties"]

    def test_literal_enum(self) -> None:
        schema = pydantic_to_json_schema(EnumModel)
        status_prop = schema["properties"]["status"]
        assert "enum" in status_prop
        assert set(status_prop["enum"]) == {"active", "inactive"}

    def test_required_fields(self) -> None:
        schema = pydantic_to_json_schema(SimpleModel)
        assert "required" in schema
        assert set(schema["required"]) == {"name", "age", "active"}


class TestPydanticToResponseFormat:
    def test_structure(self) -> None:
        fmt = pydantic_to_response_format(SimpleModel)
        assert fmt["type"] == "json_schema"
        assert fmt["json_schema"]["name"] == "SimpleModel"
        assert fmt["json_schema"]["strict"] is True
        assert "schema" in fmt["json_schema"]
        assert fmt["json_schema"]["schema"]["type"] == "object"


class TestParseStructuredResponse:
    def test_valid_json(self) -> None:
        content = '{"name": "Alice", "age": 30, "active": true}'
        result = parse_structured_response(content, SimpleModel)
        assert result.name == "Alice"
        assert result.age == 30
        assert result.active is True

    def test_markdown_fence(self) -> None:
        content = '```json\n{"name": "Bob", "age": 25, "active": false}\n```'
        result = parse_structured_response(content, SimpleModel)
        assert result.name == "Bob"

    def test_thinking_tokens(self) -> None:
        content = '<think>hmm</think>{"name": "Charlie", "age": 40, "active": true}'
        result = parse_structured_response(content, SimpleModel)
        assert result.name == "Charlie"

    def test_json_embedded_in_text(self) -> None:
        content = 'Here is the result: {"name": "Dave", "age": 35, "active": true} done.'
        result = parse_structured_response(content, SimpleModel)
        assert result.name == "Dave"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(Exception):
            parse_structured_response("not json at all", SimpleModel)

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(Exception):
            parse_structured_response('{"name": 123, "age": "old"}', SimpleModel)

    def test_trailing_prose_with_brace(self) -> None:
        # A naive rfind('}') slice would swallow the trailing lone brace and fail.
        content = '{"name": "Eve", "age": 28, "active": true}. Note: use {braces} sparingly.'
        result = parse_structured_response(content, SimpleModel)
        assert result.name == "Eve"

    def test_string_field_contains_braces(self) -> None:
        content = '{"name": "use } and { carefully", "age": 1, "active": true}'
        result = parse_structured_response(content, SimpleModel)
        assert result.name == "use } and { carefully"

    def test_nested_object(self) -> None:
        content = (
            'prefix {"title": "T", "author": '
            '{"name": "Ann", "age": 9, "active": true}} suffix'
        )
        result = parse_structured_response(content, NestedModel)
        assert result.author.name == "Ann"

    def test_raises_structured_parse_error_with_raw(self) -> None:
        from hive.errors import StructuredParseError

        with pytest.raises(StructuredParseError) as exc:
            parse_structured_response('{"name": 123, "age": "old"}', SimpleModel)
        assert '{"name": 123' in exc.value.raw


class MockStructuredProvider(BaseProvider):
    """Provider that returns structured JSON content."""

    def __init__(self, response_content: str) -> None:
        super().__init__("mock")
        self._content = response_content

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
        return GenerateResult(
            message=Message.assistant(self._content),
            model="mock",
            input_tokens=10,
            output_tokens=5,
        )

    async def generate_structured(
        self,
        messages: list[Message],
        output_type: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> Any:
        return await generate_structured_fallback(
            self, messages, output_type, temperature, max_tokens
        )


class _BareProvider(BaseProvider):
    """Provider that implements only generate_with_metadata (no structured override)."""

    def __init__(self, content: str) -> None:
        super().__init__("bare")
        self._content = content

    @property
    def available(self) -> bool:
        return True

    async def generate_with_metadata(self, *args: Any, **kwargs: Any) -> GenerateResult:
        return GenerateResult(message=Message.assistant(self._content), model="bare")


class TestBaseGenerateStructuredDefault:
    @pytest.mark.asyncio
    async def test_provider_without_override_uses_fallback(self) -> None:
        """A4: generate_structured works out of the box via the base fallback."""
        provider = _BareProvider('{"name": "Zoe", "age": 9, "active": false}')
        result = await provider.generate_structured([Message.user("hi")], SimpleModel)
        assert isinstance(result, StructuredGenerateResult)
        assert result.parsed.name == "Zoe"
        assert result.parsed.age == 9


class TestGenerateStructuredFallback:
    @pytest.mark.asyncio
    async def test_fallback_parses_response(self) -> None:
        provider = MockStructuredProvider('{"name": "Test", "age": 1, "active": true}')
        result = await generate_structured_fallback(provider, [Message.user("test")], SimpleModel)
        assert isinstance(result, StructuredGenerateResult)
        assert result.parsed.name == "Test"
        assert result.parsed.age == 1

    @pytest.mark.asyncio
    async def test_fallback_invalid_raises(self) -> None:
        provider = MockStructuredProvider("not valid json")
        with pytest.raises(Exception):
            await generate_structured_fallback(provider, [Message.user("test")], SimpleModel)


class TestAgentRunStructured:
    @pytest.mark.asyncio
    async def test_run_structured(self) -> None:
        from hive.runtime.agent import Agent

        provider = MockStructuredProvider('{"name": "Agent", "age": 5, "active": true}')
        agent = Agent(name="test", model=provider)

        result = await agent.run_structured(
            Task(instruction="Give me a person"),
            output_type=SimpleModel,
        )
        assert isinstance(result, StructuredTaskResult)
        assert result.status == TaskStatus.COMPLETED
        assert result.parsed.name == "Agent"
        assert result.parsed.age == 5

    @pytest.mark.asyncio
    async def test_run_structured_failure(self) -> None:
        from hive.runtime.agent import Agent

        provider = MockStructuredProvider("totally broken")
        agent = Agent(name="test", model=provider)

        result = await agent.run_structured(
            Task(instruction="Give me a person"),
            output_type=SimpleModel,
        )
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
