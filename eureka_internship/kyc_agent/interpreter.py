"""Turn graph rows into concise prose and a dependency-free chart payload."""

from __future__ import annotations

from typing import Any

from chart_router.tools import RENDER_CHART, RENDER_GRAPH
from kyc_agent.models import InterpretedResult


class ResultInterpreter:
    def interpret(
        self, question: str, rows: list[dict[str, Any]]
    ) -> InterpretedResult:
        if not rows:
            summary = "No matching KYC graph evidence was found."
            return InterpretedResult(
                summary=summary,
                chart_handoff={},
            )

        lowered = question.lower()
        subject = rows[0].get("entity") or rows[0].get("person")
        if "risk profile" in lowered:
            summary = (
                f"Risk profile returned {len(rows)} aggregate record(s), covering "
                "sanctions, litigation, news, and jurisdiction exposure."
            )
        elif "sanction" in lowered:
            summary = (
                f"Found {len(rows)} sanction exposure record(s)"
                + (f" for {subject}." if subject else ".")
            )
        elif "pep" in lowered:
            summary = f"Found {len(rows)} director(s) flagged as politically exposed."
        elif "news article" in lowered:
            summary = f"Found {len(rows)} co-mentioned entity/article pair(s)."
        elif "court" in lowered or "case" in lowered:
            summary = f"Found {len(rows)} linked court case record(s)."
        elif "owner" in lowered or "own " in lowered:
            summary = f"Found {len(rows)} ownership result(s), including bounded paths."
        elif "jurisdiction" in lowered:
            summary = f"Found {len(rows)} high-risk jurisdiction exposure result(s)."
        else:
            summary = f"Found {len(rows)} graph result(s) for the KYC question."

        if "ultimate beneficial owner" in lowered:
            path = rows[0].get("ownership_path", [])
            nodes = [
                {
                    "data": {
                        "id": f"node-{index}",
                        "label": str(name),
                        "type": "person" if index == 0 else "company",
                    }
                }
                for index, name in enumerate(path)
            ]
            edges = [
                {
                    "data": {
                        "id": f"owns-{index}",
                        "source": f"node-{index}",
                        "target": f"node-{index + 1}",
                        "label": "OWNS",
                    }
                }
                for index in range(max(0, len(nodes) - 1))
            ]
            handoff = {
                "tool_name": RENDER_GRAPH,
                "arguments": {"nodes": nodes, "edges": edges},
            }
        elif "per year" in lowered or "risk profile" in lowered:
            if "per year" in lowered:
                values = [dict(row) for row in rows]
                x_field, y_field = "year", "cases"
                mark = "line"
            else:
                aggregate = rows[0]
                values = [
                    {"signal": key, "count": value}
                    for key, value in aggregate.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                ]
                x_field, y_field = "signal", "count"
                mark = "bar"
            handoff = {
                "tool_name": RENDER_CHART,
                "arguments": {
                    "vega_lite_spec": {
                        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                        "description": question,
                        "data": {"values": values},
                        "mark": {"type": mark, "tooltip": True},
                        "encoding": {
                            "x": {
                                "field": x_field,
                                "type": "temporal" if x_field == "year" else "nominal",
                            },
                            "y": {"field": y_field, "type": "quantitative"},
                        },
                    }
                },
            }
        else:
            handoff = {}
        return InterpretedResult(summary=summary, chart_handoff=handoff)
