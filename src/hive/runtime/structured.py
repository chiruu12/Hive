"""Structured output — Pydantic model validation for LLM responses."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from hive.runtime.types import GenerateResult

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class StructuredGenerateResult(Generic[T]):
    """GenerateResult with a validated Pydantic model."""

    result: GenerateResult
    parsed: T


def pydantic_to_json_schema(model_class: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model to a clean JSON Schema for LLM APIs.

    Inlines $defs, strips titles, and adds additionalProperties: false.
    """
    raw: dict[str, Any] = model_class.model_json_schema()
    defs: dict[str, Any] = raw.pop("$defs", {})
    resolved: dict[str, Any] = _resolve_refs(raw, defs)
    _strip_titles(resolved)
    _add_additional_properties_false(resolved)
    return resolved


def pydantic_to_response_format(model_class: type[BaseModel]) -> dict[str, Any]:
    """Build the OpenAI response_format dict for structured JSON output."""
    schema = pydantic_to_json_schema(model_class)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model_class.__name__,
            "strict": True,
            "schema": schema,
        },
    }


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced top-level ``{...}`` object in ``text``.

    Walks the string tracking brace depth while respecting string literals and
    escapes, so braces inside quoted strings (e.g. ``"use } carefully"``) don't
    throw off the match -- unlike a naive ``find('{')`` / ``rfind('}')`` slice.
    Returns ``None`` if no balanced object is found.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_structured_response(content: str, output_type: type[T]) -> T:
    """Parse and validate a JSON string against a Pydantic model.

    Handles markdown code fences and thinking tokens. Raises
    :class:`~hive.errors.StructuredParseError` (carrying the raw text) when no
    JSON object can be extracted or validation fails.
    """
    from hive.errors import StructuredParseError

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    think_match = re.search(r"</think>\s*(.*)", text, re.DOTALL)
    if think_match:
        text = think_match.group(1).strip()
    extracted = _extract_json_object(text)
    if extracted is not None:
        text = extracted
    try:
        return output_type.model_validate_json(text)
    except ValidationError as e:
        raise StructuredParseError(
            f"Could not validate response as {output_type.__name__}: {e}",
            raw=content,
        ) from e


def _resolve_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Recursively inline $ref pointers from $defs."""
    if isinstance(node, dict):
        if "$ref" in node:
            ref_name = node["$ref"].split("/")[-1]
            if ref_name in defs:
                return _resolve_refs(dict(defs[ref_name]), defs)
            return node
        return {k: _resolve_refs(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(item, defs) for item in node]
    return node


def _strip_titles(node: Any) -> None:
    """Remove 'title' keys from a JSON Schema tree in-place."""
    if isinstance(node, dict):
        node.pop("title", None)
        node.pop("default", None)
        for v in node.values():
            _strip_titles(v)
    elif isinstance(node, list):
        for item in node:
            _strip_titles(item)


def _add_additional_properties_false(node: Any) -> None:
    """Add additionalProperties: false to all object types in-place."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node.setdefault("additionalProperties", False)
        for v in node.values():
            _add_additional_properties_false(v)
    elif isinstance(node, list):
        for item in node:
            _add_additional_properties_false(item)


async def generate_structured_fallback(
    provider: Any,
    messages: list[Any],
    output_type: type[T],
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> StructuredGenerateResult[T]:
    """Fallback for providers without native structured output.

    Appends schema instructions to the prompt, then parses the response.
    """
    from hive.runtime.types import Message

    schema = pydantic_to_json_schema(output_type)
    schema_str = json.dumps(schema, indent=2)
    instruction = (
        f"\n\nRespond with ONLY valid JSON matching this schema:\n{schema_str}\n"
        "No markdown, no explanation. Just the JSON object."
    )

    augmented = list(messages)
    if augmented and augmented[-1].role.value == "user":
        last = augmented[-1]
        augmented[-1] = Message.user(last.content + instruction)
    else:
        augmented.append(Message.user(instruction))

    result = await provider.generate_with_metadata(
        augmented, temperature=temperature, max_tokens=max_tokens
    )

    parsed = parse_structured_response(result.message.content, output_type)
    return StructuredGenerateResult(result=result, parsed=parsed)
