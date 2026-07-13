"""Small immutable values shared by the KYC graph workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CypherRequest:
    question: str
    query: str
    parameters: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""


@dataclass(frozen=True)
class ValidatedCypher:
    query: str
    parameters: dict[str, Any]
    uses_parameters: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterpretedResult:
    summary: str
    chart_handoff: dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    request: CypherRequest
    rows: list[dict[str, Any]]
    summary: str
    chart_handoff: dict[str, Any]
