"""Tests for the toolkit system and @tool decorator."""

from typing import Literal

import pytest

from hive.runtime.tools import (
    Tool,
    Toolkit,
    _extract_schema,
    _parse_docstring_args,
    collect_tools,
    make_tool,
    tool,
)


class TestDocstringParser:
    def test_google_style(self):
        doc = """Do something.

        Args:
            query: The search query.
            limit: Max results to return.
        """
        result = _parse_docstring_args(doc)
        assert result == {"query": "The search query.", "limit": "Max results to return."}

    def test_no_args_section(self):
        doc = "Just a description."
        assert _parse_docstring_args(doc) == {}

    def test_none_docstring(self):
        assert _parse_docstring_args(None) == {}


class TestSchemaExtraction:
    def test_basic_types(self):
        def fn(name: str, count: int, score: float, active: bool) -> str:
            pass

        schema = _extract_schema(fn)
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["properties"]["score"]["type"] == "number"
        assert schema["properties"]["active"]["type"] == "boolean"
        assert set(schema["required"]) == {"name", "count", "score", "active"}

    def test_optional_params(self):
        def fn(query: str, limit: int = 10) -> str:
            pass

        schema = _extract_schema(fn)
        assert schema["required"] == ["query"]
        assert "limit" in schema["properties"]

    def test_literal_enum(self):
        def fn(mode: Literal["fast", "slow"]) -> str:
            pass

        schema = _extract_schema(fn)
        assert schema["properties"]["mode"]["enum"] == ["fast", "slow"]

    def test_list_type(self):
        def fn(items: list[str]) -> str:
            pass

        schema = _extract_schema(fn)
        assert schema["properties"]["items"]["type"] == "array"
        assert schema["properties"]["items"]["items"]["type"] == "string"

    def test_optional_type(self):
        def fn(name: str | None = None) -> str:
            pass

        schema = _extract_schema(fn)
        assert "name" not in schema.get("required", [])

    def test_skips_self(self):
        class Foo:
            def method(self, x: int) -> str:
                pass

        schema = _extract_schema(Foo.method)
        assert "self" not in schema["properties"]

    def test_docstring_descriptions(self):
        def fn(query: str, limit: int = 5) -> str:
            """Search for things.

            Args:
                query: What to search for.
                limit: Max items.
            """
            pass

        schema = _extract_schema(fn)
        assert schema["properties"]["query"]["description"] == "What to search for."
        assert schema["properties"]["limit"]["description"] == "Max items."


class TestToolDecorator:
    def test_basic(self):
        @tool()
        def my_func(x: str) -> str:
            """Does a thing."""
            return x

        assert hasattr(my_func, "_tool_meta")
        meta = my_func._tool_meta
        assert meta["name"] == "my_func"
        assert meta["description"] == "Does a thing."
        assert "x" in meta["parameters"]["properties"]

    def test_custom_name(self):
        @tool(name="custom_name", description="Custom desc")
        def fn(a: int) -> str:
            return ""

        assert fn._tool_meta["name"] == "custom_name"
        assert fn._tool_meta["description"] == "Custom desc"


class TestToolkit:
    def test_discovers_tools(self):
        class MyToolkit(Toolkit):
            @tool()
            def tool_a(self, x: str) -> str:
                """Tool A."""
                return x

            @tool()
            def tool_b(self, y: int) -> str:
                """Tool B."""
                return str(y)

            def not_a_tool(self) -> None:
                pass

        tk = MyToolkit()
        tools = tk.get_tools()
        names = {t.name for t in tools}
        assert names == {"tool_a", "tool_b"}

    def test_empty_toolkit(self):
        class EmptyToolkit(Toolkit):
            pass

        tk = EmptyToolkit()
        assert tk.get_tools() == []


class TestToolCall:
    @pytest.mark.asyncio
    async def test_sync_tool(self):
        def add(a: int, b: int) -> int:
            return a + b

        t = Tool(name="add", description="add", parameters={}, fn=add, is_async=False)
        result = await t.call(a=2, b=3)
        assert result == "5"

    @pytest.mark.asyncio
    async def test_async_tool(self):
        async def greet(name: str) -> str:
            return f"Hello {name}"

        t = Tool(name="greet", description="greet", parameters={}, fn=greet, is_async=True)
        result = await t.call(name="World")
        assert result == "Hello World"


class TestToolSchema:
    def test_to_schema(self):
        t = Tool(
            name="search",
            description="Search things",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
            fn=lambda: None,
        )
        schema = t.to_schema()
        assert schema["name"] == "search"
        assert schema["description"] == "Search things"
        assert schema["input_schema"]["properties"]["q"]["type"] == "string"


class TestMakeTool:
    def test_decorated_function(self) -> None:
        @tool()
        def greet(name: str) -> str:
            """Say hello."""
            return f"Hello, {name}!"

        t = make_tool(greet)
        assert t.name == "greet"
        assert t.description == "Say hello."
        assert "name" in t.parameters.get("properties", {})
        assert not t.is_async

    def test_plain_function(self) -> None:
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        t = make_tool(add)
        assert t.name == "add"
        assert t.description == "Add two numbers."
        assert "a" in t.parameters.get("properties", {})

    def test_async_function(self) -> None:
        @tool()
        async def fetch(url: str) -> str:
            """Fetch a URL."""
            return "data"

        t = make_tool(fetch)
        assert t.is_async

    def test_preserves_custom_name(self) -> None:
        @tool(name="custom_name")
        def boring() -> str:
            """Do something."""
            return "done"

        t = make_tool(boring)
        assert t.name == "custom_name"

    @pytest.mark.asyncio
    async def test_tool_is_callable(self) -> None:
        def multiply(x: int, y: int) -> str:
            """Multiply."""
            return str(x * y)

        t = make_tool(multiply)
        result = await t.call(x=3, y=7)
        assert result == "21"


class TestCollectTools:
    def test_multiple(self) -> None:
        def alpha() -> str:
            """Alpha."""
            return "a"

        def beta() -> str:
            """Beta."""
            return "b"

        tools = collect_tools(alpha, beta)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"alpha", "beta"}

    def test_empty(self) -> None:
        assert collect_tools() == []

    def test_mixed_decorated_and_plain(self) -> None:
        @tool(name="custom")
        def decorated() -> str:
            """Decorated."""
            return "d"

        def plain() -> str:
            """Plain."""
            return "p"

        tools = collect_tools(decorated, plain)
        assert len(tools) == 2
        assert tools[0].name == "custom"
        assert tools[1].name == "plain"
