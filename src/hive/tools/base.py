"""Tool and Toolkit system with automatic JSON Schema extraction."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Union, get_args, get_origin

logger = logging.getLogger(__name__)


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
        if result is None:
            return ""
        if isinstance(result, (dict, list)):
            import json

            return json.dumps(result, default=str)
        return str(result)


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
    if tp is dict:
        return {"type": "object"}

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
        args = get_args(tp)
        if args and len(args) == 2:
            return {
                "type": "object",
                "additionalProperties": _python_type_to_json_schema(args[1]),
            }
        return {"type": "object"}

    if origin is Union:
        args = get_args(tp)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _python_type_to_json_schema(non_none[0])
        return {"anyOf": [_python_type_to_json_schema(a) for a in non_none]}

    if _is_pydantic_model(tp):
        return _pydantic_to_inline_schema(tp)

    if _is_dataclass(tp):
        return _dataclass_to_schema(tp)

    return {"type": "string"}


def _is_pydantic_model(tp: Any) -> bool:
    try:
        from pydantic import BaseModel

        return isinstance(tp, type) and issubclass(tp, BaseModel)
    except ImportError:
        return False


def _is_dataclass(tp: Any) -> bool:
    import dataclasses

    return dataclasses.is_dataclass(tp) and isinstance(tp, type)


def _pydantic_to_inline_schema(model: type[Any]) -> dict[str, Any]:
    """Convert a Pydantic model to an inlined JSON Schema (no $refs)."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    raw.pop("title", None)
    return _resolve_refs(raw, defs)


def _resolve_refs(
    schema: dict[str, Any],
    defs: dict[str, Any],
) -> dict[str, Any]:
    """Recursively inline $ref references."""
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        if ref_name in defs:
            resolved = dict(defs[ref_name])
            resolved.pop("title", None)
            return _resolve_refs(resolved, defs)
        return {"type": "object"}

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            result[key] = _resolve_refs(value, defs)
        elif isinstance(value, list):
            result[key] = [_resolve_refs(v, defs) if isinstance(v, dict) else v for v in value]
        else:
            result[key] = value
    return result


def _dataclass_to_schema(dc: type[Any]) -> dict[str, Any]:
    """Convert a dataclass to JSON Schema."""
    import dataclasses

    properties: dict[str, Any] = {}
    required: list[str] = []
    hints = typing.get_type_hints(dc)
    for field in dataclasses.fields(dc):
        tp = hints.get(field.name, str)
        prop = _python_type_to_json_schema(tp)
        properties[field.name] = prop
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            required.append(field.name)
    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


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


def _extract_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Extract JSON Schema from a function's type hints and docstring."""
    fn_name = getattr(fn, "__name__", "unknown")
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
        logger.warning("Tool '%s': could not resolve type hints", fn_name)

    sig = inspect.signature(fn)
    doc_args = _parse_docstring_args(fn.__doc__)

    properties: dict[str, Any] = {}
    required: list[str] = []

    user_params = [(n, p) for n, p in sig.parameters.items() if n not in ("self", "cls", "return")]

    for param_name, param in user_params:
        if param_name not in hints:
            logger.warning(
                "Tool '%s': parameter '%s' has no type annotation, defaulting to str",
                fn_name,
                param_name,
            )

        tp = hints.get(param_name, str)
        schema = _python_type_to_json_schema(tp)

        if param_name in doc_args:
            schema["description"] = doc_args[param_name]
        else:
            if user_params:
                logger.debug(
                    "Tool '%s': parameter '%s' has no description "
                    "(add an Args: section to the docstring)",
                    fn_name,
                    param_name,
                )

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
) -> Callable[..., Any]:
    """Decorator that marks a function as a tool with auto-extracted JSON Schema.

    The function's docstring is used as the tool description sent to the LLM.
    A warning is logged if no docstring is provided.
    Parameter descriptions are extracted from an ``Args:`` section in the docstring.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or fn.__name__
        raw_doc = inspect.cleandoc(fn.__doc__ or "")

        if not description and not raw_doc:
            logger.warning(
                "Tool '%s': no docstring provided — the LLM won't know "
                "what this tool does. Add a docstring.",
                tool_name,
            )

        tool_desc = description or raw_doc.split("\n\n")[0].strip() or tool_name

        fn._tool_meta = {  # type: ignore[attr-defined]
            "name": tool_name,
            "description": tool_desc,
            "parameters": _extract_schema(fn),
        }
        return fn

    return decorator


def make_tool(fn: Callable[..., Any]) -> Tool:
    """Convert a callable into a Tool. Applies @tool() if not already decorated."""
    if not hasattr(fn, "_tool_meta"):
        fn = tool()(fn)
    meta = fn._tool_meta  # type: ignore[attr-defined]
    return Tool(
        name=meta["name"],
        description=meta["description"],
        parameters=meta["parameters"],
        fn=fn,
        is_async=inspect.iscoroutinefunction(fn),
    )


def collect_tools(*fns: Callable[..., Any]) -> list[Tool]:
    """Convert multiple functions into Tool objects."""
    return [make_tool(fn) for fn in fns]


class Toolkit:
    """Base class for grouping related tools. Subclass and decorate methods with @tool."""

    _agent_id: str = ""

    def bind(self, agent_id: str) -> None:
        """Called by the Agent to set the agent context. Override if needed."""
        if self._agent_id and self._agent_id != agent_id:
            logger.warning(
                "Toolkit %s already bound to %r, rebinding to %r",
                self.__class__.__name__,
                self._agent_id,
                agent_id,
            )
        self._agent_id = agent_id

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
