"""Async validate-and-retry router for KYC visualization tool calls."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from common.config import Settings
from common.llm import ChatMessage, LLM, ToolCall, create_llm
from chart_router.tools import (
    KYC_ROUTING_PROMPT,
    RENDER_CHART,
    RENDER_DIAGRAM,
    RENDER_GRAPH,
    TOOLS,
)
from chart_router.validators import (
    SpecValidationError,
    validate_graph,
    validate_mermaid,
    validate_vega_lite,
)


class RoutingError(RuntimeError):
    """Raised when no valid visualization tool call is produced."""


class RouteResult(BaseModel):
    """Validated renderer instruction safe to pass to the demo frontend."""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    attempts: int
    model: str


def _data_context(data: Sequence[Mapping[str, Any]] | None) -> str:
    if not data:
        return "No tabular data was supplied; use only facts in the question."
    sample = [dict(row) for row in data[:5]]
    columns = list(dict.fromkeys(key for row in sample for key in row))
    return (
        f"Available columns: {', '.join(columns)}\n"
        f"Sample rows: {json.dumps(sample, sort_keys=True, default=str)}"
    )


def _validate_call(call: ToolCall) -> None:
    arguments = call.arguments
    if call.name == RENDER_DIAGRAM:
        if set(arguments) != {"mermaid_code", "diagram_type"}:
            raise SpecValidationError(
                "render_diagram requires only mermaid_code and diagram_type"
            )
        validate_mermaid(arguments["mermaid_code"], arguments["diagram_type"])
    elif call.name == RENDER_CHART:
        if set(arguments) != {"vega_lite_spec"}:
            raise SpecValidationError(
                "render_chart requires only vega_lite_spec"
            )
        validate_vega_lite(arguments["vega_lite_spec"])
    elif call.name == RENDER_GRAPH:
        validate_graph(arguments)
    else:
        raise SpecValidationError(f"Unknown visualization tool {call.name!r}")


def _diagram_type(question: str) -> str:
    lowered = question.lower()
    if any(word in lowered for word in ("sequence", "escalat", "interaction")):
        return "sequence"
    if any(word in lowered for word in ("mindmap", "mind map", "red flag")):
        return "mindmap"
    if any(word in lowered for word in ("data model", "entity relationship", " er ")):
        return "er"
    if "state" in lowered or "lifecycle" in lowered:
        return "state"
    if "class" in lowered:
        return "class"
    if any(word in lowered for word in ("gantt", "timeline", "schedule")):
        return "gantt"
    return "flowchart"


def _mock_diagram(question: str) -> dict[str, Any]:
    diagram_type = _diagram_type(question)
    examples = {
        "flowchart": "flowchart LR\nA[KYC Intake] --> B{Risk flags?}\nB -->|Yes| C[EDD Review]\nB -->|No| D[Approve]",
        "sequence": "sequenceDiagram\nScreening->>Analyst: Sanctions hit\nAnalyst->>MLRO: Escalate match\nMLRO-->>Analyst: Review decision",
        "mindmap": "mindmap\n  root((EDD red flags))\n    Sanctions\n    PEP exposure\n    Adverse media",
        "er": "erDiagram\nPERSON ||--o{ COMPANY : OWNS\nCOMPANY ||--o{ CASE : INVOLVED_IN",
        "state": "stateDiagram-v2\n[*] --> Screening\nScreening --> Review\nReview --> Approved\nReview --> Rejected",
        "class": "classDiagram\nclass Entity\nEntity : +string name\nclass Company\nEntity <|-- Company",
        "gantt": "gantt\ntitle EDD review\nsection Compliance\nScreening :a1, 2026-01-01, 2d\nApproval :after a1, 1d",
    }
    return {"mermaid_code": examples[diagram_type], "diagram_type": diagram_type}


def _mock_chart(
    data: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    rows = (
        [dict(row) for row in data]
        if data
        else [
            {"year": "2022", "cases": 2},
            {"year": "2023", "cases": 4},
            {"year": "2024", "cases": 3},
            {"year": "2025", "cases": 6},
        ]
    )
    columns = list(rows[0]) if rows else ["category", "value"]
    x_field = columns[0]
    y_field = columns[1] if len(columns) > 1 else columns[0]
    x_values = [row.get(x_field) for row in rows]
    y_values = [row.get(y_field) for row in rows]
    x_type = (
        "temporal"
        if re.search(r"year|date|time", x_field, re.IGNORECASE)
        else "quantitative"
        if x_values and all(isinstance(value, (int, float)) for value in x_values)
        else "nominal"
    )
    y_type = (
        "quantitative"
        if y_values and all(isinstance(value, (int, float)) for value in y_values)
        else "nominal"
    )
    mark = "line" if x_type == "temporal" and y_type == "quantitative" else "bar"
    return {
        "vega_lite_spec": {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "description": "Deterministic local KYC chart",
            "data": {"values": rows},
            "mark": {"type": mark, "tooltip": True},
            "encoding": {
                "x": {"field": x_field, "type": x_type},
                "y": {"field": y_field, "type": y_type},
            },
        }
    }


def _mock_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"data": {"id": "person-a", "label": "Person A", "type": "person"}},
            {"data": {"id": "holding", "label": "Holding Co", "type": "company"}},
            {"data": {"id": "company-b", "label": "Company B", "type": "company"}},
        ],
        "edges": [
            {
                "data": {
                    "id": "ownership-1",
                    "source": "person-a",
                    "target": "holding",
                    "label": "UBO_OF",
                }
            },
            {
                "data": {
                    "id": "ownership-2",
                    "source": "holding",
                    "target": "company-b",
                    "label": "OWNS",
                }
            },
        ],
    }


def _mock_call(
    question: str, data: Sequence[Mapping[str, Any]] | None
) -> ToolCall:
    lowered = question.lower()
    graph_terms = (
        "connected",
        "connection",
        "ubo",
        "ownership chain",
        "subgraph",
        "relationship path",
    )
    chart_terms = (
        "trend",
        " per year",
        " by year",
        "distribution",
        "histogram",
        "scatter",
        "chart",
        "count",
        "percentage by",
    )
    if any(term in lowered for term in graph_terms):
        name, arguments = RENDER_GRAPH, _mock_graph()
    elif data or any(term in lowered for term in chart_terms):
        name, arguments = RENDER_CHART, _mock_chart(data)
    else:
        name, arguments = RENDER_DIAGRAM, _mock_diagram(question)
    return ToolCall(id="local-domain-mock", name=name, arguments=arguments)


class ChartRouter:
    """Route a question to one validated visualization instruction."""

    def __init__(
        self,
        llm: LLM | None = None,
        *,
        mock_mode: bool | None = None,
    ) -> None:
        if llm is None:
            settings = Settings.from_env()
            self.llm = create_llm(settings)
            self.mock_mode = (
                settings.llm_provider == "mock"
                if mock_mode is None
                else mock_mode
            )
        else:
            self.llm = llm
            self.mock_mode = bool(mock_mode)

    async def route(
        self,
        question: str,
        *,
        data: Sequence[Mapping[str, Any]] | None = None,
    ) -> RouteResult:
        if not question.strip():
            raise ValueError("question must not be empty")

        if self.mock_mode:
            call = _mock_call(question, data)
            _validate_call(call)
            return RouteResult(
                tool_name=call.name,
                arguments=call.arguments,
                attempts=1,
                model=self.llm.model,
            )

        messages = [
            ChatMessage(role="system", content=KYC_ROUTING_PROMPT),
            ChatMessage(
                role="user",
                content=f"Question: {question}\n{_data_context(data)}",
            ),
        ]
        last_error = "no tool call"
        for attempt in (1, 2):
            response = await self.llm.complete(
                messages,
                tools=TOOLS,
                temperature=0.0,
            )
            try:
                if len(response.tool_calls) != 1:
                    raise SpecValidationError(
                        "The model must return exactly one visualization tool call"
                    )
                call = response.tool_calls[0]
                _validate_call(call)
                return RouteResult(
                    tool_name=call.name,
                    arguments=call.arguments,
                    attempts=attempt,
                    model=response.model,
                )
            except (SpecValidationError, KeyError, TypeError) as exc:
                last_error = str(exc)
                if attempt == 1:
                    messages.append(
                        ChatMessage(
                            role="user",
                            content=(
                                "Validation error: "
                                f"{last_error}. Return one corrected tool call only."
                            ),
                        )
                    )

        raise RoutingError(
            f"LLM produced no valid visualization after 2 attempts: {last_error}"
        )
