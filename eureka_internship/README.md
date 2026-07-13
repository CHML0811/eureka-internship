# Eureka AI-G Data prototypes

Three composable, private-lane KYC/AML prototypes:

1. `doc_router/` classifies uploaded documents, routes forms/tables to
   Textract and charts/diagrams to a private vision model, then emits canonical
   graph-ingestion JSON with confidence and provenance.
2. `chart_router/` routes chat answers to Mermaid, Vega-Lite, or Cytoscape and
   validates every renderer specification before it reaches the browser.
3. `kyc_agent/` turns KYC questions into bounded read-only Cypher, validates
   and explains the query, executes it, summarizes the rows, and hands suitable
   results to the Project 8 renderer contracts.

## Safe local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

The defaults in `.env.example` are deterministic mocks. No document, entity,
or graph data is sent to a public model provider. To use self-hosted Llama,
set `LLM_PROVIDER=ollama` and point `LOCAL_LLM_BASE_URL` at localhost or a
private-network OpenAI-compatible Ollama endpoint.

## Demos

```bash
.venv/bin/python -m doc_router.eval.run_eval
.venv/bin/python -m chart_router.demo
.venv/bin/python -m chart_router.demo_server
.venv/bin/python -m kyc_agent.eval_runner
.venv/bin/python -m kyc_agent.demo
```

The chart UI is served at `http://127.0.0.1:8008`. Its Python routing remains
local, while the prototype renderer assets load from jsDelivr and therefore
require network access.

For the disk-free AuraDB Free synthetic demo (recommended), or the optional
local Neo4j fallback, follow `kyc_agent/README.md`.
Project-specific limitations and founder-facing summaries are documented in
each package's `README.md` and `MEMO.md`.
