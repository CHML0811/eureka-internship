from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Sequence

import pytest

from common.llm import ChatMessage, LLMResponse, MockLLM, ToolCall, ToolDefinition
from chart_router.demo import EXAMPLES, build_artifact
from chart_router.demo_server import SECURITY_HEADERS, route_payload
from chart_router.router import ChartRouter, RoutingError
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


def test_tools_expose_openai_style_parameter_schemas() -> None:
    assert [tool.name for tool in TOOLS] == [
        RENDER_DIAGRAM,
        RENDER_CHART,
        RENDER_GRAPH,
    ]
    for tool in TOOLS:
        assert isinstance(tool, ToolDefinition)
        assert tool.parameters["type"] == "object"
        assert tool.parameters.get("additionalProperties") is False

    diagram = TOOLS[0].parameters
    assert diagram["properties"]["diagram_type"]["enum"] == [
        "flowchart",
        "sequence",
        "mindmap",
        "er",
        "state",
        "class",
        "gantt",
    ]
    assert set(diagram["required"]) == {"mermaid_code", "diagram_type"}


def test_prompt_makes_kyc_routing_rules_explicit() -> None:
    prompt = KYC_ROUTING_PROMPT.lower()
    assert "numeric data on an axis" in prompt
    assert "subgraph of the kyc database" in prompt
    assert "structural" in prompt
    assert "court cases per year" in prompt
    assert "ubo" in prompt


@pytest.mark.parametrize(
    ("diagram_type", "code"),
    [
        ("flowchart", "flowchart LR\nA[Applicant] --> B{PEP hit?}"),
        ("sequence", "sequenceDiagram\nAnalyst->>MLRO: Escalate sanctions hit"),
        ("mindmap", "mindmap\n  root((Red flags))\n    PEP\n    Sanctions"),
        ("er", "erDiagram\nPERSON ||--o{ COMPANY : OWNS"),
        ("state", "stateDiagram-v2\n[*] --> Screening\nScreening --> Review"),
        ("class", "classDiagram\nclass Entity\nEntity : +string name"),
        ("gantt", "gantt\ntitle EDD review\nsection Review\nScreening :a1, 2026-01-01, 2d"),
    ],
)
def test_mermaid_validator_accepts_all_supported_subtypes(
    diagram_type: str, code: str
) -> None:
    validate_mermaid(code, diagram_type)


@pytest.mark.parametrize(
    ("code", "diagram_type", "message"),
    [
        ("pie\n  title Risk", "pie", "supported"),
        ("flowchart LR\nA --> B", "sequence", "header"),
        ("```mermaid\nflowchart LR\nA-->B\n```", "flowchart", "fence"),
        ("flowchart LR\nA[broken --> B", "flowchart", "balanced"),
        ("flowchart LR\nclick A javascript:alert(1)", "flowchart", "unsafe"),
    ],
)
def test_mermaid_validator_rejects_invalid_or_unsafe_input(
    code: str, diagram_type: str, message: str
) -> None:
    with pytest.raises(SpecValidationError, match=message):
        validate_mermaid(code, diagram_type)


def valid_chart_spec() -> dict[str, object]:
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": "Court cases by year",
        "data": {
            "values": [
                {"year": "2022", "cases": 2},
                {"year": "2023", "cases": 4},
            ]
        },
        "mark": "line",
        "encoding": {
            "x": {"field": "year", "type": "temporal"},
            "y": {"field": "cases", "type": "quantitative"},
        },
    }


def test_vega_lite_validator_accepts_safe_v5_inline_spec() -> None:
    validate_vega_lite(valid_chart_spec())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"$schema": "https://vega.github.io/schema/vega-lite/v4.json"}, "version 5"),
        ({"data": {"url": "https://example.com/private.csv"}}, "inline"),
        ({"mark": "unknown-mark"}, "mark"),
        ({"encoding": {"x": {"field": "year", "type": "mystery"}}}, "type"),
        ({"transform": [{"calculate": "datum.secret", "as": "x"}]}, "unsafe"),
    ],
)
def test_vega_lite_validator_rejects_unsafe_or_malformed_specs(
    change: dict[str, object], message: str
) -> None:
    spec = valid_chart_spec()
    spec.update(change)
    with pytest.raises(SpecValidationError, match=message):
        validate_vega_lite(spec)


def test_graph_validator_accepts_cytoscape_nodes_and_edges() -> None:
    validate_graph(
        {
            "nodes": [
                {"data": {"id": "person-a", "label": "Person A", "type": "person"}},
                {"data": {"id": "company-b", "label": "Company B", "type": "company"}},
            ],
            "edges": [
                {
                    "data": {
                        "id": "owns",
                        "source": "person-a",
                        "target": "company-b",
                        "label": "UBO_OF",
                    }
                }
            ],
        }
    )


class RecordingLLM:
    model = "test"

    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self.responses = list(responses)
        self.messages: list[list[ChatMessage]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        assert tools == TOOLS
        assert temperature == 0.0
        self.messages.append(list(messages))
        return self.responses.pop(0)


def response(name: str, arguments: dict[str, object], call_id: str = "call") -> LLMResponse:
    return LLMResponse(
        model="test",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
    )


def test_router_retries_once_with_validation_error_and_returns_valid_call() -> None:
    llm = RecordingLLM(
        [
            response(
                RENDER_DIAGRAM,
                {"diagram_type": "sequence", "mermaid_code": "flowchart LR\nA-->B"},
            ),
            response(
                RENDER_DIAGRAM,
                {
                    "diagram_type": "sequence",
                    "mermaid_code": "sequenceDiagram\nA->>B: Escalate",
                },
                "retry",
            ),
        ]
    )

    result = asyncio.run(ChartRouter(llm).route("Show the sanctions escalation"))

    assert result.tool_name == RENDER_DIAGRAM
    assert result.attempts == 2
    assert "validation error" in llm.messages[1][-1].content.lower()
    assert "header" in llm.messages[1][-1].content.lower()


def test_router_fails_loudly_after_one_retry() -> None:
    invalid = response(
        RENDER_CHART,
        {"vega_lite_spec": {"$schema": "v4", "mark": "line", "encoding": {}}},
    )
    llm = RecordingLLM([invalid, invalid])

    with pytest.raises(RoutingError, match="after 2 attempts"):
        asyncio.run(ChartRouter(llm).route("Chart court cases"))


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Show court cases per year for Company X", RENDER_CHART),
        ("Draw the sanctions escalation workflow", RENDER_DIAGRAM),
        ("How is Person A connected to Company B in the KYC database?", RENDER_GRAPH),
    ],
)
def test_mock_pipeline_routes_by_domain_instead_of_first_tool(
    question: str, expected: str
) -> None:
    result = asyncio.run(ChartRouter(MockLLM(), mock_mode=True).route(question))
    assert result.tool_name == expected
    if expected == RENDER_CHART:
        validate_vega_lite(result.arguments["vega_lite_spec"])
    elif expected == RENDER_DIAGRAM:
        validate_mermaid(
            result.arguments["mermaid_code"], result.arguments["diagram_type"]
        )
    else:
        validate_graph(result.arguments)


def test_router_includes_compact_data_context() -> None:
    llm = RecordingLLM([response(RENDER_CHART, {"vega_lite_spec": valid_chart_spec()})])
    data = [{"year": 2024, "cases": 3}, {"year": 2025, "cases": 5}]

    asyncio.run(ChartRouter(llm).route("Plot cases", data=data))

    user_message = llm.messages[0][-1].content
    assert "Available columns: year, cases" in user_message
    assert json.dumps(data, sort_keys=True) in user_message


def test_injected_mock_llm_uses_protocol_response_without_concrete_type_branch() -> None:
    llm = MockLLM(
        [
            response(
                RENDER_DIAGRAM,
                {
                    "mermaid_code": "flowchart LR\nA[Review] --> B[Approve]",
                    "diagram_type": "flowchart",
                },
            )
        ]
    )

    result = asyncio.run(
        ChartRouter(llm).route(
            "Show a court case trend",
            data=[{"year": 2025, "cases": 3}],
        )
    )

    assert result.tool_name == RENDER_DIAGRAM


def test_demo_ui_uses_local_api_and_all_three_cdn_renderers() -> None:
    html = (Path(__file__).parents[1] / "demo_ui" / "index.html").read_text()
    assert 'fetch("/api/route"' in html
    assert "cdn.jsdelivr.net/npm/mermaid" in html
    assert "cdn.jsdelivr.net/npm/vega-embed" in html
    assert "cdn.jsdelivr.net/npm/cytoscape" in html
    assert "requires network access" in html.lower()


def test_demo_ui_announces_results_and_exposes_visualizations_accessibly() -> None:
    html = (Path(__file__).parents[1] / "demo_ui" / "index.html").read_text()
    assert 'id="status" role="status" aria-live="polite" aria-atomic="true"' in html
    assert html.count('class="renderer" role="img"') == 3
    assert 'aria-describedby="status"' in html
    assert 'setAttribute("aria-invalid", "true")' in html
    assert '"shape": "ellipse"' in html


def test_demo_defines_eight_examples_covering_every_renderer() -> None:
    assert len(EXAMPLES) == 8
    results = [
        asyncio.run(
            ChartRouter(MockLLM(), mock_mode=True).route(
                item["question"], data=item.get("data")
            )
        )
        for item in EXAMPLES
    ]
    assert {result.tool_name for result in results} == set(
        [RENDER_DIAGRAM, RENDER_CHART, RENDER_GRAPH]
    )
    artifact = build_artifact(EXAMPLES[0]["question"], results[0])
    assert "<!doctype html>" in artifact.lower()
    assert json.dumps(results[0].model_dump(), sort_keys=True) in artifact


def test_demo_pages_and_server_define_browser_security_policy() -> None:
    result = asyncio.run(
        ChartRouter(MockLLM(), mock_mode=True).route("Draw a KYC workflow")
    )
    artifact = build_artifact("Draw a KYC workflow", result)

    assert "Content-Security-Policy" in artifact
    assert SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "cdn.jsdelivr.net" in SECURITY_HEADERS["Content-Security-Policy"]


def test_http_boundary_routes_json_payload_with_local_mock() -> None:
    payload = asyncio.run(
        route_payload(
            {
                "question": "Show sanctions hits by jurisdiction",
                "data": [
                    {"jurisdiction": "HK", "hits": 3},
                    {"jurisdiction": "SG", "hits": 1},
                ],
            }
        )
    )
    assert payload["tool_name"] == RENDER_CHART
    assert payload["model"] == "mock"
