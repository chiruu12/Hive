"""Tool and Toolkit system with automatic JSON Schema extraction."""

from __future__ import annotations

import asyncio
import inspect
import re
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Union, get_args, get_origin


@dataclass
class Tool:
    """A callable tool with metadata and JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]
    is_async: bool = False

    def to_schema(self) -> dict[str, Any]:
        """Return tool definition in the format expected by LLM APIs."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    async def call(self, **kwargs: Any) -> str:
        """Execute the tool function, handling sync/async transparently."""
        if self.is_async:
            result = await self.fn(**kwargs)
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.fn(**kwargs))
        return str(result) if result is not None else ""


def _python_type_to_json_schema(tp: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema type."""
    if tp is str:
        return {"type": "string"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is bool:
        return {"type": "boolean"}

    origin = get_origin(tp)

    if origin is Literal:
        values = list(get_args(tp))
        if all(isinstance(v, str) for v in values):
            return {"type": "string", "enum": values}
        return {"enum": values}

    if origin is list:
        args = get_args(tp)
        items = _python_type_to_json_schema(args[0]) if args else {}
        return {"type": "array", "items": items}

    if origin is dict:
        return {"type": "object"}

    if origin is Union:
        args = get_args(tp)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _python_type_to_json_schema(non_none[0])
        return {"anyOf": [_python_type_to_json_schema(a) for a in non_none]}

    return {"type": "string"}


def _parse_docstring_args(docstring: str | None) -> dict[str, str]:
    """Extract parameter descriptions from a Google-style Args: section."""
    if not docstring:
        return {}

    descriptions: dict[str, str] = {}
    in_args = False

    for line in docstring.splitlines():
        stripped = line.strip()

        if stripped.lower().startswith("args:"):
            in_args = True
            continue

        if in_args:
            if stripped and not stripped[0].isspace() and not stripped.startswith("-"):
                if ":" not in stripped or re.match(r"^[A-Z]", stripped):
                    break

            match = re.match(r"^\s*(\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)", line)
            if match:
                descriptions[match.group(1)] = match.group(2).strip()

    return descriptions


def _extract_schema(fn: Callable) -> dict[str, Any]:
    """Extract JSON Schema from a function's type hints and docstring."""
    hints = typing.get_type_hints(fn)
    sig = inspect.signature(fn)
    doc_args = _parse_docstring_args(fn.__doc__)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls", "return"):
            continue

        tp = hints.get(param_name, str)
        schema = _python_type_to_json_schema(tp)

        if param_name in doc_args:
            schema["description"] = doc_args[param_name]

        properties[param_name] = schema

        origin = get_origin(tp)
        is_optional = origin is Union and type(None) in get_args(tp)

        if param.default is inspect.Parameter.empty and not is_optional:
            required.append(param_name)

    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


def tool(
    name: str | None = None,
    description: str | None = None,
) -> Callable:
    """Decorator that marks a function as a tool with auto-extracted JSON Schema."""

    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        raw_doc = inspect.cleandoc(fn.__doc__ or "")
        tool_desc = description or raw_doc.split("\n\n")[0].strip() or tool_name

        fn._tool_meta = {  # type: ignore[attr-defined]
            "name": tool_name,
            "description": tool_desc,
            "parameters": _extract_schema(fn),
        }
        return fn

    return decorator


class Toolkit:
    """Base class for grouping related tools. Subclass and decorate methods with @tool."""

    def get_tools(self) -> list[Tool]:
        """Auto-discover all @tool-decorated methods on this instance."""
        tools: list[Tool] = []
        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue
            method = getattr(self, attr_name, None)
            if method is None or not callable(method):
                continue
            meta = getattr(method, "_tool_meta", None)
            if meta is None:
                continue
            tools.append(
                Tool(
                    name=meta["name"],
                    description=meta["description"],
                    parameters=meta["parameters"],
                    fn=method,
                    is_async=inspect.iscoroutinefunction(method),
                )
            )
        return tools
