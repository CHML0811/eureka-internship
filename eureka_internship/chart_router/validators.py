"""Small, dependency-free safety validators for renderer specifications."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from chart_router.tools import DIAGRAM_TYPES


class SpecValidationError(ValueError):
    """Raised when generated renderer input is malformed or unsafe."""


_MERMAID_HEADERS = {
    "flowchart": re.compile(r"^flowchart\s+(TB|TD|BT|RL|LR)\b", re.IGNORECASE),
    "sequence": re.compile(r"^sequenceDiagram\b", re.IGNORECASE),
    "mindmap": re.compile(r"^mindmap\b", re.IGNORECASE),
    "er": re.compile(r"^erDiagram\b", re.IGNORECASE),
    "state": re.compile(r"^stateDiagram(?:-v2)?\b", re.IGNORECASE),
    "class": re.compile(r"^classDiagram\b", re.IGNORECASE),
    "gantt": re.compile(r"^gantt\b", re.IGNORECASE),
}
_UNSAFE_MERMAID = re.compile(
    r"(?:javascript\s*:|<script\b|%%\s*\{\s*init|^\s*click\s+)",
    re.IGNORECASE | re.MULTILINE,
)


def validate_mermaid(code: str, diagram_type: str) -> None:
    """Validate the declared Mermaid subtype, header, and basic safe syntax."""
    if diagram_type not in DIAGRAM_TYPES:
        raise SpecValidationError(
            f"diagram type {diagram_type!r} is not supported; use {DIAGRAM_TYPES}"
        )
    if not isinstance(code, str) or not code.strip():
        raise SpecValidationError("Mermaid code must be a non-empty string")
    if len(code) > 50_000:
        raise SpecValidationError("Mermaid code exceeds the 50,000 character limit")
    if "```" in code:
        raise SpecValidationError("Mermaid code must not contain a Markdown fence")
    if _UNSAFE_MERMAID.search(code):
        raise SpecValidationError("Mermaid code contains an unsafe directive")

    stripped = code.strip()
    first_line = stripped.splitlines()[0].strip()
    if not _MERMAID_HEADERS[diagram_type].match(first_line):
        raise SpecValidationError(
            f"Mermaid header does not match declared type {diagram_type!r}"
        )
    if len(stripped.splitlines()) < 2:
        raise SpecValidationError("Mermaid diagram needs a header and body")

    # Curly braces are meaningful one-sided ER relationship markers (``o{``),
    # so only delimiters used for node/label grouping are count-checkable.
    pairs = {"[": "]", "(": ")"}
    for opening, closing in pairs.items():
        if code.count(opening) != code.count(closing):
            raise SpecValidationError(
                f"Mermaid delimiters are not balanced: {opening}{closing}"
            )


_MARKS = {
    "arc",
    "area",
    "bar",
    "boxplot",
    "circle",
    "errorband",
    "errorbar",
    "geoshape",
    "image",
    "line",
    "point",
    "rect",
    "rule",
    "square",
    "text",
    "tick",
    "trail",
}
_FIELD_TYPES = {"quantitative", "temporal", "ordinal", "nominal", "geojson"}
_UNSAFE_VEGA_KEYS = {"url", "href", "expr", "signal", "calculate"}


def _walk_for_unsafe_values(value: Any, *, depth: int = 0) -> None:
    if depth > 20:
        raise SpecValidationError("Vega-Lite spec nesting is too deep")
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise SpecValidationError("Vega-Lite object keys must be strings")
            if key.lower() in _UNSAFE_VEGA_KEYS:
                if key.lower() == "url":
                    raise SpecValidationError(
                        "Vega-Lite data must be inline; remote URLs are forbidden"
                    )
                raise SpecValidationError(
                    f"Vega-Lite contains unsafe key {key!r}"
                )
            _walk_for_unsafe_values(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 10_000:
            raise SpecValidationError("Vega-Lite arrays may contain at most 10,000 items")
        for child in value:
            _walk_for_unsafe_values(child, depth=depth + 1)
    elif not isinstance(value, (str, int, float, bool, type(None))):
        raise SpecValidationError("Vega-Lite values must be JSON-compatible")


def _validate_encoding(encoding: Any) -> None:
    if not isinstance(encoding, Mapping):
        raise SpecValidationError("Vega-Lite encoding must be an object")
    for channel, definition in encoding.items():
        if not isinstance(channel, str) or not isinstance(definition, Mapping):
            raise SpecValidationError("Each Vega-Lite encoding channel must be an object")
        if not any(key in definition for key in ("field", "value", "datum", "aggregate")):
            raise SpecValidationError(
                f"Encoding channel {channel!r} needs field, value, datum, or aggregate"
            )
        field_type = definition.get("type")
        if field_type is not None and field_type not in _FIELD_TYPES:
            raise SpecValidationError(
                f"Unknown Vega-Lite field type {field_type!r}"
            )


def validate_vega_lite(spec: Mapping[str, Any]) -> None:
    """Validate a constrained, inline-data Vega-Lite v5 specification."""
    if not isinstance(spec, Mapping):
        raise SpecValidationError("Vega-Lite spec must be a JSON object")
    try:
        encoded = json.dumps(spec, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SpecValidationError(f"Vega-Lite spec is not valid JSON: {exc}") from exc
    if len(encoded) > 1_000_000:
        raise SpecValidationError("Vega-Lite spec exceeds the 1 MB limit")

    schema = spec.get("$schema")
    if not isinstance(schema, str) or "vega-lite/v5" not in schema:
        raise SpecValidationError("Vega-Lite $schema must declare version 5")

    data = spec.get("data")
    if data is not None:
        if not isinstance(data, Mapping) or set(data) != {"values"}:
            raise SpecValidationError(
                "Vega-Lite data must use only inline data.values"
            )
        if not isinstance(data["values"], list):
            raise SpecValidationError("Vega-Lite data.values must be an array")

    composition_keys = {"layer", "hconcat", "vconcat", "concat", "facet", "repeat"}
    if "mark" not in spec and not composition_keys.intersection(spec):
        raise SpecValidationError("Vega-Lite spec needs a mark or composition")
    if "mark" in spec:
        mark = spec["mark"]
        mark_type = mark.get("type") if isinstance(mark, Mapping) else mark
        if mark_type not in _MARKS:
            raise SpecValidationError(f"Unknown or unsupported Vega-Lite mark {mark_type!r}")
        if "encoding" not in spec:
            raise SpecValidationError("A marked Vega-Lite spec needs encoding")
        _validate_encoding(spec["encoding"])

    _walk_for_unsafe_values(spec)


def validate_graph(arguments: Mapping[str, Any]) -> None:
    """Validate a bounded Cytoscape node/edge payload and its references."""
    if not isinstance(arguments, Mapping) or set(arguments) != {"nodes", "edges"}:
        raise SpecValidationError("Graph arguments must contain only nodes and edges")
    nodes = arguments["nodes"]
    edges = arguments["edges"]
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise SpecValidationError("Graph nodes and edges must be arrays")
    if len(nodes) > 500 or len(edges) > 2_000:
        raise SpecValidationError("Graph exceeds the demo size limit")

    node_ids: set[str] = set()
    for node in nodes:
        data = node.get("data") if isinstance(node, Mapping) else None
        if not isinstance(data, Mapping):
            raise SpecValidationError("Every graph node needs a data object")
        node_id = data.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise SpecValidationError("Every graph node needs a non-empty string id")
        if node_id in node_ids:
            raise SpecValidationError(f"Duplicate graph node id {node_id!r}")
        node_ids.add(node_id)

    edge_ids: set[str] = set()
    for edge in edges:
        data = edge.get("data") if isinstance(edge, Mapping) else None
        if not isinstance(data, Mapping):
            raise SpecValidationError("Every graph edge needs a data object")
        edge_id = data.get("id")
        if not isinstance(edge_id, str) or not edge_id.strip():
            raise SpecValidationError("Every graph edge needs a non-empty string id")
        if edge_id in edge_ids:
            raise SpecValidationError(f"Duplicate graph edge id {edge_id!r}")
        edge_ids.add(edge_id)
        if data.get("source") not in node_ids or data.get("target") not in node_ids:
            raise SpecValidationError(
                f"Graph edge {edge_id!r} references an unknown node"
            )
