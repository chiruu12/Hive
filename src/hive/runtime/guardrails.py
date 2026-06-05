"""Guardrails -- inspect and sanitize model input/output in the ReAct loop.

The model-I/O analog of the daemon's lifecycle hooks: a ``Guardrail`` runs on the
text entering the model (a **pre**-hook on the task input) and on the text leaving it
(a **post**-hook on the assistant output). Each guardrail carries an ``action``
(flag / redact / block) it applies when it matches. A ``GuardrailPipeline`` chains
several and aggregates their verdicts.

Built-ins: ``PIIGuardrail`` (emails, phones, SSNs, cards, IPs) and
``PromptInjectionGuardrail`` (jailbreak / instruction-override phrases). Custom
guardrails implement the ``Guardrail`` protocol; register them on
``GuardrailRegistry`` to compose with the built-ins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from hive.config import GuardrailConfig


class GuardrailStage(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class GuardrailAction(StrEnum):
    """What a guardrail does when it matches."""

    FLAG = "flag"  # log and continue, text unchanged
    REDACT = "redact"  # mask the matched spans, continue
    BLOCK = "block"  # stop -- refuse the input or replace the output


@dataclass(frozen=True)
class GuardrailFinding:
    """Verdict for one guardrail (or the aggregate from a pipeline)."""

    triggered: bool
    action: GuardrailAction
    text: str  # possibly-redacted text (equals the input when nothing changed)
    reasons: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.triggered and self.action is GuardrailAction.BLOCK


@runtime_checkable
class Guardrail(Protocol):
    name: str
    action: GuardrailAction

    def inspect(self, text: str, stage: GuardrailStage) -> GuardrailFinding:
        """Inspect ``text`` for this stage; return a finding (triggered or not)."""
        ...


def _passthrough(text: str) -> GuardrailFinding:
    return GuardrailFinding(triggered=False, action=GuardrailAction.FLAG, text=text)


class _RegexGuardrail:
    """Shared base: match named regex patterns, then flag/redact/block."""

    name = "regex"

    def __init__(
        self,
        patterns: dict[str, re.Pattern[str]],
        action: GuardrailAction,
        stages: tuple[GuardrailStage, ...],
        redaction: str = "[REDACTED:{label}]",
    ):
        self._patterns = patterns
        self.action = action
        self._stages = stages
        self._redaction = redaction

    def inspect(self, text: str, stage: GuardrailStage) -> GuardrailFinding:
        if stage not in self._stages:
            return _passthrough(text)
        reasons: list[str] = []
        redacted = text
        for label, pattern in self._patterns.items():
            if pattern.search(text):
                reasons.append(f"{self.name}: {label}")
                if self.action is GuardrailAction.REDACT:
                    redacted = pattern.sub(self._redaction.format(label=label), redacted)
        if not reasons:
            return _passthrough(text)
        out = redacted if self.action is GuardrailAction.REDACT else text
        return GuardrailFinding(triggered=True, action=self.action, text=out, reasons=reasons)


# --- PII ---

_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "phone": re.compile(r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}


class PIIGuardrail(_RegexGuardrail):
    """Detect (and optionally redact) common PII. Defaults to redacting output."""

    name = "pii"

    def __init__(
        self,
        action: GuardrailAction = GuardrailAction.REDACT,
        stages: tuple[GuardrailStage, ...] = (GuardrailStage.OUTPUT,),
    ):
        super().__init__(_PII_PATTERNS, action, stages)


# --- Prompt injection ---

_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|the\s+above)\s+"
        r"(?:instructions?|prompts?|rules?)",
        re.IGNORECASE,
    ),
    "disregard": re.compile(
        r"\bdisregard\s+(?:all\s+)?(?:previous|prior|the\s+above|your)\b", re.IGNORECASE
    ),
    "override_system": re.compile(
        r"\b(?:ignore|forget|override|bypass)\s+(?:your\s+)?(?:system\s+prompt|instructions|guardrails)",
        re.IGNORECASE,
    ),
    "role_override": re.compile(
        r"\byou\s+are\s+now\b|\bact\s+as\s+(?:a\s+)?(?:DAN|jailbroken)|\bdeveloper\s+mode\b",
        re.IGNORECASE,
    ),
}


class PromptInjectionGuardrail(_RegexGuardrail):
    """Detect instruction-override / jailbreak phrasing. Defaults to blocking input."""

    name = "prompt_injection"

    def __init__(
        self,
        action: GuardrailAction = GuardrailAction.BLOCK,
        stages: tuple[GuardrailStage, ...] = (GuardrailStage.INPUT,),
    ):
        super().__init__(_INJECTION_PATTERNS, action, stages)


class GuardrailPipeline:
    """Run a list of guardrails for a stage and aggregate their findings.

    Redactions chain (each guardrail rewrites the text the next one sees); a single
    BLOCK short-circuits the aggregate to BLOCK. An empty pipeline is a no-op.
    """

    def __init__(self, guardrails: list[Guardrail]):
        self._guardrails = guardrails

    def __bool__(self) -> bool:
        return bool(self._guardrails)

    def run(self, text: str, stage: GuardrailStage) -> GuardrailFinding:
        reasons: list[str] = []
        current = text
        triggered = False
        action = GuardrailAction.FLAG
        for guard in self._guardrails:
            finding = guard.inspect(current, stage)
            if not finding.triggered:
                continue
            triggered = True
            reasons.extend(finding.reasons)
            if finding.action is GuardrailAction.BLOCK:
                return GuardrailFinding(True, GuardrailAction.BLOCK, text, reasons)
            if finding.action is GuardrailAction.REDACT:
                current = finding.text
                action = GuardrailAction.REDACT
            elif action is not GuardrailAction.REDACT:
                action = GuardrailAction.FLAG
        return GuardrailFinding(triggered, action, current, reasons)


class GuardrailRegistry:
    """Pluggable registry of guardrail factories (registries over hardcoded lists).

    The default registry holds the built-in ``pii`` and ``prompt_injection``
    guardrails; register a callable ``(action, stages) -> Guardrail`` under a name to
    add your own, then enable it via config.
    """

    _default: GuardrailRegistry | None = None

    def __init__(self) -> None:
        self._factories: dict[str, type[_RegexGuardrail]] = {}

    def register(self, name: str, factory: type[_RegexGuardrail]) -> None:
        self._factories[name] = factory

    def get(self, name: str) -> type[_RegexGuardrail] | None:
        return self._factories.get(name)

    @classmethod
    def default(cls) -> GuardrailRegistry:
        if cls._default is None:
            reg = cls()
            reg.register("pii", PIIGuardrail)
            reg.register("prompt_injection", PromptInjectionGuardrail)
            cls._default = reg
        return cls._default

    @classmethod
    def _reset(cls) -> None:
        cls._default = None


def build_guardrail_pipeline(config: GuardrailConfig) -> GuardrailPipeline:
    """Construct the active guardrail pipeline from config (empty if disabled)."""
    if not config.enabled:
        return GuardrailPipeline([])
    guardrails: list[Guardrail] = []
    if config.pii:
        guardrails.append(PIIGuardrail(action=GuardrailAction(config.pii_action)))
    if config.prompt_injection:
        guardrails.append(
            PromptInjectionGuardrail(action=GuardrailAction(config.injection_action))
        )
    return GuardrailPipeline(guardrails)
