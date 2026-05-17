"""Agent instructions — structured prompt configuration."""

from __future__ import annotations

from typing import Any


class Instructions:
    """Structured instructions for an agent's system prompt.

    Usage:
        # Full configuration
        instructions = Instructions(
            persona="Senior Python developer who values clean architecture",
            instructions=["Write production-quality code", "Add type hints"],
            context="Working on a FastAPI backend with PostgreSQL",
        )

        # Minimal
        instructions = Instructions(persona="Helpful coding assistant")

        # With structured output
        from pydantic import BaseModel
        class Review(BaseModel):
            score: int
            summary: str

        instructions = Instructions(
            persona="Code reviewer",
            instructions=["Review for bugs and style issues"],
            response_model=Review,
        )
    """

    def __init__(
        self,
        persona: str = "",
        instructions: str | list[str] | None = None,
        context: str = "",
        response_model: type[Any] | None = None,
    ):
        self.persona = persona
        self.context = context
        self.response_model = response_model

        if instructions is None:
            self._instructions: list[str] = []
        elif isinstance(instructions, str):
            self._instructions = [instructions]
        else:
            self._instructions = list(instructions)

    @property
    def goals(self) -> list[str]:
        return self._instructions

    def build_system_prompt(self, toolkit_instructions: list[str] | None = None) -> str:
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

        if self.response_model:
            schema = self.response_model.model_json_schema()
            schema.pop("title", None)
            import json

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
        if self.response_model:
            fields.append(f"response_model={self.response_model.__name__}")
        return f"Instructions({', '.join(fields)})"
