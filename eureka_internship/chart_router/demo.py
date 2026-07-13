"""Generate eight portable HTML demo artifacts with the local router."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
from pathlib import Path
from typing import Any

from chart_router.router import ChartRouter, RouteResult

EXAMPLES: list[dict[str, Any]] = [
    {
        "slug": "court-cases-trend",
        "question": "Show court cases per year for Company X",
        "data": [
            {"year": "2022", "cases": 2},
            {"year": "2023", "cases": 4},
            {"year": "2024", "cases": 3},
            {"year": "2025", "cases": 6},
        ],
    },
    {
        "slug": "sanctions-by-jurisdiction",
        "question": "Chart sanctions hit count by jurisdiction",
        "data": [
            {"jurisdiction": "Hong Kong", "hits": 4},
            {"jurisdiction": "Singapore", "hits": 2},
            {"jurisdiction": "United Kingdom", "hits": 3},
        ],
    },
    {
        "slug": "risk-distribution",
        "question": "Show the risk score distribution as a chart",
        "data": [
            {"band": "Low", "entities": 12},
            {"band": "Medium", "entities": 7},
            {"band": "High", "entities": 3},
        ],
    },
    {
        "slug": "sanctions-escalation",
        "question": "Draw the sequence for sanctions-hit escalation",
    },
    {
        "slug": "edd-red-flags",
        "question": "Create a mind map of EDD red flags",
    },
    {
        "slug": "onboarding-workflow",
        "question": "Draw the KYC onboarding workflow",
    },
    {
        "slug": "ubo-chain",
        "question": "Show the UBO chain from Person A to Company B",
    },
    {
        "slug": "entity-connection",
        "question": "How is Person A connected to Company B in the KYC database?",
    },
]


def build_artifact(question: str, result: RouteResult) -> str:
    """Build one HTML file with its validated render instruction embedded."""
    payload = json.dumps(result.model_dump(), sort_keys=True).replace("</", "<\\/")
    title = html.escape(question)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'unsafe-inline'; img-src data:">
<title>{title}</title>
<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
window.mermaid = mermaid; mermaid.initialize({{startOnLoad:false,securityLevel:"strict"}});
</script>
<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape@3/dist/cytoscape.min.js"></script>
<style>
body{{font-family:system-ui;margin:32px;color:#172033}} #view{{height:600px;border:1px solid #dbe3ef;border-radius:10px;padding:16px}}
.note{{color:#526078}}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="note">Generated locally; CDN renderers require network access.</p>
<div id="view"></div>
<script>
const result = {payload};
addEventListener("load", async () => {{
  const view = document.querySelector("#view"), args = result.arguments;
  if (result.tool_name === "render_diagram") {{
    view.className = "mermaid"; view.textContent = args.mermaid_code;
    await window.mermaid.run({{nodes:[view]}});
  }} else if (result.tool_name === "render_chart") {{
    await vegaEmbed(view, args.vega_lite_spec, {{actions:false}});
  }} else {{
    cytoscape({{
      container:view, elements:[...args.nodes,...args.edges], layout:{{name:"cose"}},
      style:[
        {{selector:"node",style:{{label:"data(label)","background-color":"#3d75d6"}}}},
        {{selector:"edge",style:{{label:"data(label)","target-arrow-shape":"triangle","curve-style":"bezier"}}}}
      ]
    }});
  }}
}});
</script>
</body>
</html>
"""


async def generate(output_dir: Path) -> list[Path]:
    """Run all examples and write one HTML artifact for each."""
    output_dir.mkdir(parents=True, exist_ok=True)
    router = ChartRouter()
    paths: list[Path] = []
    for example in EXAMPLES:
        result = await router.route(
            example["question"],
            data=example.get("data"),
        )
        path = output_dir / f"{example['slug']}.html"
        path.write_text(
            build_artifact(example["question"], result),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).with_name("demo_output"),
    )
    args = parser.parse_args()
    paths = asyncio.run(generate(args.output_dir))
    print(f"Generated {len(paths)} HTML artifacts in {args.output_dir}")


if __name__ == "__main__":
    main()
