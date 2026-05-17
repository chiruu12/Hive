"""Agent instructions — structured prompt configuration."""

from __future__ import annotations

import json
from typing import Any


class Instructions:
    """Structured instructions for an agent's system prompt.

    Usage:
        instructions = Instructions(
            persona="Senior Python developer",
            instructions=["Write production-quality code", "Add type hints"],
            context="Working on a FastAPI backend",
        )

    response_model is set by the Agent, not by the user directly.
    Toolkit instructions are collected by the Agent automatically.
    """

    def __init__(
        self,
        persona: str = "",
        instructions: str | list[str] | None = None,
        context: str = "",
    ):
        self.persona = persona
        self.context = context
        self._response_model: type[Any] | None = None

        if instructions is None:
            self._instructions: list[str] = []
        elif isinstance(instructions, str):
            self._instructions = [instructions]
        else:
            self._instructions = list(instructions)

    @property
    def goals(self) -> list[str]:
        return self._instructions

    @property
    def response_model(self) -> type[Any] | None:
        return self._response_model

    @response_model.setter
    def response_model(self, model: type[Any] | None) -> None:
        self._response_model = model

    def build_system_prompt(
        self,
        toolkit_instructions: list[str] | None = None,
    ) -> str:
        """Assemble the full system prompt from all parts."""
        parts: list[str] = []

        if self.persona:
            parts.append(f"You are {self.persona}.")

        if self._instructions:
            lines = "\n".join(f"- {i}" for i in self._instructions)
            parts.append(f"Instructions:\n{lines}")

        if self.context:
            parts.append(f"Context: {self.context}")

        if toolkit_instructions:
            for ti in toolkit_instructions:
                if ti.strip():
                    parts.append(ti)

        if self._response_model:
            schema = self._response_model.model_json_schema()
            schema.pop("title", None)
            parts.append(
                "Respond with a JSON object matching this schema:\n"
                f"```json\n{json.dumps(schema, indent=2)}\n```"
            )

        return "\n\n".join(parts)

    def __repr__(self) -> str:
        fields = []
        if self.persona:
            fields.append(f"persona={self.persona!r}")
        if self._instructions:
            fields.append(f"instructions={self._instructions!r}")
        if self._response_model:
            fields.append(f"response_model={self._response_model.__name__}")
        return f"Instructions({', '.join(fields)})"
