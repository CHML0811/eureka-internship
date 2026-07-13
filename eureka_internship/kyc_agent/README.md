# Project 9 — KYC Graph Agent

This package turns KYC questions into bounded, read-only Cypher, executes them
through an injectable protocol, and returns a concise summary plus a plain-dict
chart handoff. The offline path is deterministic and needs neither Neo4j nor a
model. The model-backed path uses the repository's `common.llm.LLM` contract.

## Offline demo and tests

From the `eureka_internship` Python project root:

```bash
python -m kyc_agent.demo
python -m kyc_agent.demo --verbose
python -m pytest kyc_agent/tests -q
python -m kyc_agent.eval_runner
```

The demo follows the required story: CEO lookup, direct ownership, UBO chain,
sanctions traversal, and open-ended risk profile. By default it shows Cypher,
summary, and visualization choice while withholding parameters and rows; use
`--verbose` only with non-sensitive demo data. `MockCypherGenerator` maps all
ten benchmark intents to distinct schema-valid queries.

## Recommended: Neo4j AuraDB Free

AuraDB avoids local Docker images and VM disk usage. Use it only for this
synthetic 80-node demo. Do not upload real KYC documents, client names, PII, or
regulated data to a free-tier instance.

1. Create one AuraDB Free instance at <https://console.neo4j.io/>.
2. Copy the connection URI, username, and generated password (shown once).
3. From the Python project root, copy the template and fill in your values:

```bash
cp .env.example .env
# edit .env — set NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD only
```

Never commit `.env`. Synthetic demo data only — no real KYC or PII.

4. Resume the instance in the Aura console if it is paused, then initialize:

```bash
.venv/bin/python -m kyc_agent.aura_setup
.venv/bin/python -m kyc_agent.eval_runner --neo4j
```

`aura_setup` reuses `schema.cypher` and `seed.cypher`, requires encrypted
`neo4j+s://` transport to an Aura managed host, and fails unless it verifies
exactly 80 nodes and 150 relationships. AuraDB Free may pause after inactivity;
resume it from the Aura console before reconnecting.

## Optional local Neo4j 5 development database

The Compose service binds ports only to loopback and refuses to start without a
password. Use a unique local password; do not reuse a production secret:
This local path connects through `eval_runner` and intentionally accepts
`bolt://localhost`; the separate `aura_setup` initializer accepts only encrypted
`neo4j+s://` Aura managed hosts.

```bash
export NEO4J_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker compose -f kyc_agent/docker-compose.yml up -d
docker compose -f kyc_agent/docker-compose.yml exec -T neo4j \
  cypher-shell -u neo4j -p "$NEO4J_PASSWORD" < kyc_agent/schema.cypher
docker compose -f kyc_agent/docker-compose.yml exec -T neo4j \
  cypher-shell -u neo4j -p "$NEO4J_PASSWORD" < kyc_agent/seed.cypher
```

The seed is re-runnable and creates exactly 80 nodes and 150 relationships
using only the required labels and relationship vocabulary. It includes a
shell/UBO chain, a PEP linked to a high-risk jurisdiction, a sanctions hit,
court cases over four years, and an adverse-media cluster. The mounted Cypher
files are read-only; Neo4j does not auto-run them, so
the explicit commands above make initialization observable.

Live evaluation is optional and requires the Neo4j Python driver:

```bash
python -m pip install neo4j
export NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j
export NEO4J_PASSWORD='your-local-password'
python -m kyc_agent.eval_runner --neo4j
```

## Agent contracts

- `LLMCypherGenerator` loads and caches the live schema through
  `CALL db.schema.visualization()`, includes three few-shot pairs, and invokes
  a Pydantic-defined `run_cypher(query, explanation)` tool through
  `common.llm.LLM`.
- `CypherValidator` masks comments and quoted strings before lexical checks,
  rejects write/admin clauses, `UNION`, and non-allowlisted procedures, rejects
  unbounded paths, caps paths at five hops, and injects/caps `LIMIT 200`.
- A validation refusal is returned to the generator with its exact reason and
  permits exactly one retry.
- Parameter use is reported and encouraged. The deterministic and gold
  queries parameterize user values.
- The optional EXPLAIN hook runs after validation and before execution.
- `CypherExecutor` supports both `InMemoryExecutor` and `Neo4jExecutor`.
- `ResultInterpreter` returns summary text and the exact Project 8 renderer
  envelope: `render_chart` with validated-shape Vega-Lite JSON for time series
  and risk aggregates, or `render_graph` with Cytoscape nodes and edges for UBO
  ownership paths. Lookup answers may return summary text without a chart.

## Defense in depth

Validation is not the sole security boundary. Production should apply all of
the following:

1. Use a dedicated read-only Neo4j account. `security.cypher` is an Enterprise
   example granting only graph MATCH plus `db.labels` and
   `db.relationshipTypes`, and `db.schema.visualization`, while explicitly
   denying WRITE. Neo4j Community,
   used by this local Compose file, does not provide equivalent fine-grained
   role controls and is therefore development-only.
2. Keep the database unreachable from public networks. Compose binds to
   `127.0.0.1`; production should use private networking and TLS.
3. Keep the five-second database transaction timeout and application executor
   timeout. Also enforce server-side memory/query limits appropriate to the
   deployment.
4. Maintain an explicit procedure allowlist. APOC network/file procedures,
   `dbms.*`, and unknown `CALL` targets are rejected by the validator and are
   not enabled by Compose.
5. Run `EXPLAIN` through the read-only account before execution. Treat explain
   errors as rejection, log query templates without sensitive parameter
   values, and monitor timeouts.
6. Never interpolate question text into Cypher. Bind all values as parameters.

The lexical scanner is intentionally conservative and string/comment-aware,
but it is not a full Cypher parser. Database privileges, timeouts, network
isolation, and procedure restrictions remain required.

## Benchmark interpretation

`benchmark.yaml` contains ten questions, parameterized gold Cypher, parameters,
and expected answer intent. It is JSON-compatible YAML so the minimal offline
environment can read it without adding dependencies. The evaluator reports
only integration metrics: validation/execution success and non-empty fixture
results. These scores do **not** establish real-model accuracy, factual
correctness, retrieval quality, or production readiness.
