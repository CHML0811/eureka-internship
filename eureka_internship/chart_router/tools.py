"""Tool contracts and routing guidance for KYC visualizations."""

from __future__ import annotations

from common.llm import ToolDefinition

RENDER_DIAGRAM = "render_diagram"
RENDER_CHART = "render_chart"
RENDER_GRAPH = "render_graph"

DIAGRAM_TYPES = [
    "flowchart",
    "sequence",
    "mindmap",
    "er",
    "state",
    "class",
    "gantt",
]

DIAGRAM_TOOL = ToolDefinition(
    name=RENDER_DIAGRAM,
    description="Render a structural or conceptual Mermaid diagram.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mermaid_code": {
                "type": "string",
                "description": "Complete Mermaid source without Markdown fences.",
            },
            "diagram_type": {
                "type": "string",
                "enum": DIAGRAM_TYPES,
            },
        },
        "required": ["mermaid_code", "diagram_type"],
    },
)

CHART_TOOL = ToolDefinition(
    name=RENDER_CHART,
    description="Render numeric or categorical data as a Vega-Lite v5 chart.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "vega_lite_spec": {
                "type": "object",
                "description": (
                    "A Vega-Lite v5 JSON specification using inline data.values."
                ),
            }
        },
        "required": ["vega_lite_spec"],
    },
)

GRAPH_TOOL = ToolDefinition(
    name=RENDER_GRAPH,
    description="Render a KYC relationship subgraph with Cytoscape.js.",
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "data": {
                            "type": "object",
                            "description": (
                                "Node data with string id, label, and entity type."
                            ),
                        }
                    },
                    "required": ["data"],
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "data": {
                            "type": "object",
                            "description": (
                                "Edge data with id, source, target, and label."
                            ),
                        }
                    },
                    "required": ["data"],
                },
            },
        },
        "required": ["nodes", "edges"],
    },
)

TOOLS = [DIAGRAM_TOOL, CHART_TOOL, GRAPH_TOOL]

KYC_ROUTING_PROMPT = """\
You are Eureka's KYC visualization router. Return exactly one tool call.

Routing rules:
1. Use render_diagram for structural or conceptual relationships and processes:
   workflows, sequences, mind maps, ER models, states, classes, and timelines.
2. Use render_chart for anything with numeric data on an axis or an aggregate
   comparison: trends, bars, lines, pies, histograms, distributions, or scatter.
   Emit Vega-Lite version 5 and use only the supplied inline data.
3. Use render_graph when the answer is a subgraph of the KYC database:
   UBO chains, ownership links, directors, sanctions links, and paths between
   people and companies. Graph node and edge IDs must be unique.

Examples:
- "Court cases per year for Acme" -> render_chart (numeric time series).
- "Draw the sanctions-hit escalation workflow" -> render_diagram (sequence).
- "Map the red flags in this EDD case" -> render_diagram (mindmap).
- "Show the UBO chain from Person A to Company B" -> render_graph (KYC subgraph).

Never invent a remote data URL, JavaScript expression, or Mermaid click action.
Use concise labels and preserve the user's supplied facts.
"""
