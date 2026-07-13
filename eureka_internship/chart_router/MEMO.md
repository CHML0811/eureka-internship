# Project 8 Memo — KYC Visualization Router

## Problem

Eureka's chat needs to visualize both quantitative KYC evidence and structural
relationships. Treating every answer as Mermaid produces weak analytical
charts; treating every answer as a conventional chart loses ownership paths,
UBO chains, and process semantics. Model output is also untrusted DSL input:
syntactically plausible text can fail in the browser or create unsafe external
references.

## Approach

The package exposes three OpenAI-compatible tool definitions through the shared
provider-neutral `common.llm` API. An explicit KYC prompt routes numeric axes to
Vega-Lite, structural concepts to Mermaid, and database subgraphs to
Cytoscape.js. The selected arguments cross a validator before reaching the UI.
On failure, the private model receives the concrete validation error and gets
one correction attempt. A second failure is loud.

The offline path is deterministic and domain-aware. It does not depend on
`MockLLM` selecting the first listed tool, so the local demo meaningfully covers
all three routes without a model server.

## Trade-offs

Three browser libraries increase frontend weight, but each fits a materially
different grammar:

- Mermaid is compact and readable for workflows and conceptual structures.
- Vega-Lite is a concise, declarative chart grammar that compiles to Vega and
  handles axes, aggregation, and statistical marks.
- Cytoscape.js provides graph layout and node/edge interaction for KYC paths.

The dependency-free Vega-Lite validator implements a strict useful subset. It
is safer and easier to operate locally, but it is not a substitute for the full
upstream schema in production. Mermaid's local validation checks headers,
delimiters, and dangerous directives; final parsing still occurs in Mermaid.js.
The demo uses CDN assets for simplicity. Therefore the Python mock pipeline is
local, while the browser UI requires network access.

## Result

The async router has named tool contracts, compact data context, exactly-one
tool enforcement, validation, and a single retry. Tests cover every supported
Mermaid subtype, safe and unsafe Vega-Lite cases, graph integrity, retry
behavior, data context, domain-aware mock routing, and the local HTTP boundary.
The stdlib server makes the UI's Run button invoke the real router. The demo
script writes eight HTML artifacts covering all renderer families.

## Next step

Pin and self-host browser assets, add the official pinned Vega-Lite v5 schema,
and parse Mermaid server-side in a sandbox. Then evaluate a private Ollama model
against a fixed KYC prompt set, tracking first-pass validity, retry recovery,
wrong-tool rate, and factual fidelity. Project 9 can replace the hand-built
graph payload with validated Cypher query results.
