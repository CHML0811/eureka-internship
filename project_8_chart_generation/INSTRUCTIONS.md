# Project 8 — Chart Generation Router (Mermaid + Vega-Lite)

**[Load EUREKA_MASTER_CONTEXT.md before starting]**

**Updated for the private-model constraint (see EUREKA_MASTER_CONTEXT §4):** "LLM tool call" below means a call to the self-hosted **Llama 3.1/3.3** model, not Anthropic or OpenAI. The chart data (court-case counts, sanctions hits, ownership %) is real KYC data — it doesn't leave Eureka's infrastructure. Expect Llama's tool-calling to be less consistent out of the box than Claude/GPT-4o; the retry-with-parser-error pattern in Task 3 is what compensates for that gap, and Task 4's validator does the same for Vega-Lite.

## Goal
When a user asks Eureka's chat "show me the court case count by year for Company X" or "draw the shareholding structure," the chat should return a chart that renders inline. The LLM picks the right format, emits a validated spec via tool calling, the frontend renders it.

## Why not "just use Mermaid"
Your professor's core intuition is right: LLMs are good at emitting *text graph description languages*, so render from text. But Mermaid only does **structural** diagrams well — flowcharts, sequence, mindmap, ER, state, class, gantt. It has a pie chart and a crude xy-chart, but nothing credible for line / bar / time series / distribution / scatter with real data. Those need a proper data-viz grammar. **Vega-Lite** is the right tool: it's declarative JSON, the spec is small, LLMs produce it reliably under structured output, and it handles every chart type Mermaid can't.

So: two renderers, one router.

## Architecture
```
user question + data
    │
    ▼
[1] intent router (LLM tool call)
      tool A: render_diagram(mermaid_code)       ← flows, sequence, mindmap, ER, state
      tool B: render_chart(vega_lite_spec)       ← pie, bar, line, time series, dist, scatter
      tool C: render_graph(cytoscape_elements)   ← network/relationship graphs (their core)
    │
    ▼
[2] spec validator (schema check before sending to frontend)
    │
    ▼
[3] frontend renderer (Mermaid.js | vega-embed | Cytoscape.js)
```

## Tasks

### Task 1 — Scaffold and pick the stack
- Create `chart_router/` with `llm_client.py`, `tools.py`, `validators.py`, `demo_ui/`.
- Demo UI: simplest possible — a single HTML page with a text input, a "Run" button, and three `<div>` renderers. Load Mermaid.js, vega-embed, and Cytoscape.js from CDN. No build tooling yet.
- **Learning Checkpoint:** Why is tool calling better than asking the LLM to "reply with a JSON object and nothing else"? Cite two specific failure modes of the latter.

### Task 2 — Define the three tools
- In `tools.py`, define three tool schemas in the JSON-schema format Llama's tool-calling API expects (Ollama exposes an OpenAI-compatible `tools` parameter, so an OpenAI-style function schema works):
  - `render_diagram` — input: `{mermaid_code: string, diagram_type: enum[flowchart, sequence, mindmap, er, state, class, gantt]}`
  - `render_chart` — input: a Vega-Lite v5 spec (JSON). Type this as `Dict[str, Any]` but validate downstream.
  - `render_graph` — input: `{nodes: [...], edges: [...]}` in Cytoscape.js format.
- Write the system prompt that teaches the LLM when to pick which: "Use `render_diagram` for structural/conceptual relationships. Use `render_chart` for anything with numeric data on an axis. Use `render_graph` when the answer is a subgraph of the KYC database." Llama models tend to need more explicit few-shot examples in the system prompt than Claude/GPT-4o to reliably pick the right tool — plan to iterate on this.
- **Learning Checkpoint:** Give one prompt where the right tool is `render_chart` and one where it's `render_diagram`, and explain the distinction.

### Task 3 — Mermaid generation, tested on all 7 subtypes
- For each Mermaid diagram type, write one realistic KYC prompt and verify the LLM produces rendering-valid Mermaid on the first call ≥ 80% of the time.
- Examples: `mindmap` for "map the red flags in this case," `flowchart` for "draw the KYC onboarding workflow," `sequence` for "show how a sanctions hit gets escalated," `er` for "sketch the data model of our entity store."
- Fail loudly if the generated code doesn't parse. Implement a retry with the parser error fed back to the LLM.
- **Learning Checkpoint:** Why does feeding the parser error back to the LLM on retry work so well? What does this tell you about the right way to build any LLM-to-DSL pipeline?

### Task 4 — Vega-Lite generation with structured outputs
- The hard and high-value part. Prompt the LLM with: (a) the user's question, (b) a compact description of the data it has available (column names + sample rows), (c) the `render_chart` tool.
- Test on: court cases per year (time series), entity types in a portfolio (pie), risk score distribution (histogram), sanctions hits by jurisdiction (bar), ownership % vs. risk score (scatter).
- Validate output with the `vega-lite` JSON schema before sending to the frontend.
- **Learning Checkpoint:** What is the difference between Vega-Lite and Vega? Why did we pick Vega-Lite for LLM-generated specs specifically?

### Task 5 — Graph renderer for relationship answers
- When the user asks "show me how Person A is connected to Company B," the answer is a subgraph, not a chart. The LLM should call `render_graph` with a small Cytoscape elements array.
- For now, hand-build the subgraph data — Project 9 will wire this to real Cypher results.
- Style it to roughly match Eureka's existing graph look (circles for entities, labeled edges, color by type).
- **Learning Checkpoint:** Why is a general-purpose chart library (Vega-Lite) wrong for network/relationship visualization? What specific features does Cytoscape.js give you that Vega-Lite does not?

### Task 6 — End-to-end demo script
- `demo.py` runs a scripted conversation of 8 prompts covering all three tools, captures each rendered output, and saves them to `demo_output/` as PNGs (via headless Chrome or puppeteer).
- This is the artifact you screen-share in the founder demo.
- **Learning Checkpoint:** Looking at the 8 outputs, where did the LLM pick the wrong tool? What would you change in the system prompt to fix it?

### Task 7 — Memo
`MEMO.md` — Problem / Approach / Trade-offs / Result / Next step. Emphasize the tool-calling reliability story and the Mermaid-vs-Vega-Lite split. The CEO will want to know why two libraries instead of one.

## What success looks like
You open the demo UI, type "What's the court case trend for Company X over the last 5 years?" — a Vega-Lite line chart renders. You type "Draw the escalation workflow for a sanctions hit" — a Mermaid sequence diagram renders. You type "How is Person A connected to Company B?" — a small Cytoscape subgraph renders. All from the same chat box, the LLM routed each one correctly.
