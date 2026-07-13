# Eureka Chart Generation Router

Project 8 routes one KYC question to one validated renderer instruction:

- `render_diagram`: Mermaid for structural diagrams and workflows.
- `render_chart`: Vega-Lite v5 for numeric and categorical visualization.
- `render_graph`: Cytoscape.js for KYC relationship subgraphs.

The router uses the shared `common.llm` contract. The default `MockLLM` path is
fully local and deterministic, with domain-aware routing rather than the shared
mock's generic "first tool" fallback. Configuring the existing shared provider
for private Ollama uses the same tool definitions and adds one validation retry.
No public model provider is introduced.

## Run

From the `eureka_internship/` Python project directory:

```bash
.venv/bin/python -m pytest chart_router/tests -q
.venv/bin/python -m chart_router.demo_server
```

Open <http://127.0.0.1:8008>. The Run button sends JSON to the local
`POST /api/route` endpoint, which invokes `ChartRouter`.

The Python mock routing pipeline runs locally and does not require network
access. The demo UI loads Mermaid, Vega/Vega-Lite/vega-embed, and Cytoscape.js
from jsDelivr; **the CDN UI requires network access**. This is the explicit
prototype boundary. A production deployment should pin and self-host those
browser assets.

Generate eight standalone HTML demo artifacts:

```bash
.venv/bin/python -m chart_router.demo
```

Files are written under `chart_router/demo_output/`. Each artifact embeds its
validated result and needs no Python server when opened, but still needs network
access for its CDN renderer. PNG capture is intentionally optional and omitted
to keep the backend Python-stdlib-only.

## Python API

```python
from chart_router import ChartRouter

result = await ChartRouter().route(
    "Show court cases per year",
    data=[{"year": "2025", "cases": 6}],
)
```

`RouteResult` contains `tool_name`, validated `arguments`, model name, and
attempt count. A private-model response gets at most two total attempts. The
second prompt includes the validator error; invalid output after that raises
`RoutingError` instead of being sent to a browser.

## Validation boundary

Mermaid validation allows the seven declared subtypes, checks the matching
header and basic delimiter syntax, strips no fences, and rejects executable
directives. Vega-Lite validation requires a v5 schema, JSON-safe bounded input,
supported marks and field types, inline `data.values`, and rejects remote URLs
and expression/signal keys. Cytoscape validation bounds graph size, enforces
unique IDs, and checks edge references.

These local checks intentionally implement the constrained subset used by this
demo. A production service should additionally validate against a pinned full
Vega-Lite v5 JSON schema and run Mermaid parsing in an isolated renderer.

## Design checkpoints

Tool calling is safer than "reply with JSON only" because free text commonly
adds Markdown fences or explanatory prose, and malformed/missing keys are not
bound to a named operation. Tool calls provide a typed operation envelope,
though their arguments still require validation.

`render_chart` is correct for "court cases per year" because values map to axes;
`render_diagram` is correct for "draw sanctions escalation" because order and
roles are structural. Parser errors work well as retry context because they
turn an open-ended regeneration task into a specific constrained correction.

Vega-Lite is a concise high-level grammar that compiles to lower-level Vega.
That smaller specification surface is easier for an LLM to generate reliably.
Cytoscape is separate because network layouts, graph traversal interactions,
node/edge styling, and relationship labels are first-class graph concepts,
unlike axis-oriented chart grammars.
