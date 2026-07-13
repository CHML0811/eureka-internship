# Project 9 implementation memo

## Decision summary

The package separates generation, validation, execution, and interpretation so
each boundary can be tested and replaced independently. Model integration is
limited to `common.llm.LLM`; offline behavior uses a semantic deterministic
generator and fixture executor.

The graph fixture intentionally concentrates recognizable KYC patterns in 80
nodes: 16 `Person`, 20 `Company`, 12 `Address`, 5 `SanctionsEntry`, 8
`CourtCase`, 10 `NewsArticle`, and 9 `Jurisdiction` nodes. Exactly 150
relationships expose a shell/UBO chain, PEP/high-risk-jurisdiction signal,
sanctions match, multi-year litigation, and adverse-media co-mentions.

## Threat model and controls

Primary threats are generated writes, administrative Cypher, procedure escape,
unbounded traversal, excessive result sets, interpolation, and costly queries.
The validator removes comments and string/backtick contents from lexical
analysis, rejects mutating/admin tokens, `UNION`, and unknown procedures, bounds
variable paths to five hops, and enforces a maximum result limit of 200. An
EXPLAIN hook gives the executor a preflight point. Validation failures are fed
back with the exact reason for one retry only.

These controls can still be bypassed by future Cypher syntax the scanner does
not recognize. Production therefore also requires a read-only database user,
private connectivity, TLS, transaction timeout, procedure allowlist, and query
monitoring. The local Community container is explicitly not a production
authorization boundary.

## Evaluation limits

The ten-case benchmark captures intended query shape and answer intent. Offline
metrics are deterministic integration checks only. They are useful for
regression detection in wiring, safety validation, and result handoff, but make
no claim about real-model semantic accuracy. A meaningful model evaluation
would require independently labeled paraphrases, adversarial prompts,
execution-equivalence scoring against a controlled Neo4j snapshot, and human
review of answer faithfulness.

## Handoff

The interpreter hands results directly to Project 8's renderer contracts:
Vega-Lite for court-case time series and risk aggregates, and Cytoscape nodes
and edges for UBO paths. Simple lookups can remain summary-only. This keeps the
CEO demo auditable: each answer shows the bounded Cypher used, its summary, and
the visualization instruction selected from the same result rows.
