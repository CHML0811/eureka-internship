# Project 9 — Text-to-Cypher KYC Agent (flagship)

**[Load EUREKA_MASTER_CONTEXT.md before starting]**

**Updated for the private-model constraint (see EUREKA_MASTER_CONTEXT §4) — read this before Task 3.** This project is the highest-sensitivity one: the LLM sees the full graph schema plus real entity names, ownership chains, and sanctions data on every query. All LLM calls here — Cypher generation, result interpretation, chart handoff — must go to the self-hosted **Llama 3.1/3.3** model, never Anthropic or OpenAI. This is precisely the scenario slide 38 of the deck is describing when it splits "Internal Data + LLM" from "External Data + ChatGPT + Owned Model" — this project *is* the internal-data path.

## Goal
Prototype the next generation of Eureka's product: natural language in → Cypher query → graph result → natural language summary + auto-rendered visualization. Even a toy version of this, working end-to-end on a seeded KYC graph, is the single thing most likely to land you a standing meeting with the CEO.

## Why this is the highest-leverage project
Eureka's own roadmap slide names "can we talk with the database for a deep analysis?" as their 6th-generation target. You will have built a working demo of their stated next step. That is a different kind of conversation than "here's a nice OCR service."

## Prerequisite
Complete projects 7 and 8 first. This project composes them: documents become graph nodes (project 7), query results become charts (project 8), and this project is the brain in the middle.

You must have finished Neo4j GraphAcademy's "Cypher Fundamentals" before starting Task 2. Non-negotiable.

## Architecture
```
user question
    │
    ▼
[1] schema-aware planner          (LLM sees graph schema + question)
    │
    ▼
[2] Cypher generator              (LLM tool call, schema-constrained)
    │
    ▼
[3] query validator / safety      (read-only check, LIMIT injection, cost guard)
    │
    ▼
[4] Neo4j execution
    │
    ▼
[5] result interpreter            (LLM summarizes + picks chart tool from project 8)
    │
    ▼
answer = {natural_language_summary, cypher_used, chart_or_subgraph}
```

## Tasks

### Task 1 — Toy KYC graph in Neo4j
- Spin up Neo4j locally via Docker: `docker run -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5`
- Design a realistic-but-small schema in `schema.cypher`:
  - Node labels: `Person`, `Company`, `Address`, `SanctionsEntry`, `CourtCase`, `NewsArticle`, `Jurisdiction`
  - Relationships: `OWNS` (with `percent` property), `DIRECTOR_OF`, `RESIDES_AT`, `REGISTERED_AT`, `INVOLVED_IN` (case), `MENTIONED_IN` (news), `MATCHED_TO` (sanctions), `SUBJECT_TO` (jurisdiction)
- Seed `seed.cypher` with ~80 nodes and ~150 edges including: one clean shell structure (Person → LLC → LLC → Target Company), one PEP with a high-risk jurisdiction, one sanctions hit, one adverse-media cluster.
- **Learning Checkpoint:** Why seed a *small* graph with *designed* risk patterns instead of a large random one? What does this give you that a big realistic graph does not?

### Task 2 — Write 10 benchmark questions by hand
Before writing any LLM code, write `benchmark.yaml` with 10 questions, the correct Cypher for each, and the expected natural-language answer. Mix difficulty:
1. Simple lookup: "Who is the CEO of Company X?"
2. One-hop: "What companies does Person A directly own?"
3. Multi-hop: "Who is the ultimate beneficial owner of Company X?" (requires variable-length path: `MATCH (p:Person)-[:OWNS*1..5]->(c:Company {name:'X'})`)
4. Aggregation: "How many court cases has Company X been involved in per year?"
5. Ownership threshold: "Which people own more than 25% of any company directly or indirectly?"
6. Risk traversal: "Does Company X have any connection within 3 hops to a sanctioned entity?"
7. Intersection: "Which directors of Company X are also PEPs?"
8. Adverse media: "Show me all entities mentioned in the same news article as Company X."
9. Jurisdiction risk: "List all companies registered in high-risk jurisdictions that are owned by Person A."
10. Open-ended analysis: "Summarize the risk profile of Company X."

This file is both your training target and your eval set.
- **Learning Checkpoint:** Question 3 uses variable-length paths. What is the Cypher syntax for that, and why is it dangerous to let the LLM generate it without an upper bound?

### Task 3 — Schema-aware prompt + Cypher tool
- Load the live schema from Neo4j via `CALL db.schema.visualization()` at startup and cache it.
- System prompt includes the schema, 3 few-shot (question, cypher) pairs from the benchmark, and strict rules: read-only, no `DELETE`/`CREATE`/`SET`/`MERGE`, always include `LIMIT`, variable-length paths capped at 5.
- Define a tool `run_cypher(query: string, explanation: string)` against the self-hosted Llama model (via Ollama's tool-calling API). Because open-weight models are less reliable at strict schema adherence, lean harder on the few-shot examples than you would with Claude/GPT-4o, and validate the tool call's arguments against a pydantic model before proceeding to Task 4.
- **Learning Checkpoint:** Why pass the live schema into the prompt instead of hardcoding it? What happens when the schema evolves?

### Task 4 — Query validator (this is the safety layer)
- Before any generated Cypher touches Neo4j, parse it and enforce:
  - No write clauses (`CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`, `DROP`).
  - Every `MATCH` has a `LIMIT` ≤ 200 (inject if missing).
  - Any variable-length path has an upper bound ≤ 5.
  - Estimated cost via `EXPLAIN` below a threshold — if not, refuse and ask the LLM to simplify.
- Refusals feed back to the LLM with the specific reason, and the LLM retries once.
- **Learning Checkpoint:** Why is "ask the LLM nicely to only write read queries" insufficient as a safety layer? Name the specific attack or failure mode this validator prevents.

### Task 5 — Result interpreter + chart handoff
- After execution, pass the rows (capped at ~50) back to the LLM with a second tool call that can either:
  - Emit a natural-language summary only, OR
  - Emit a summary plus one of the three rendering tools from Project 8 (`render_chart`, `render_graph`, `render_diagram`).
- For question 4 (court cases per year), expect `render_chart` with a Vega-Lite time-series spec.
- For question 3 (UBO chain), expect `render_graph` with the ownership subgraph.
- For question 10 (risk profile), expect both: a written summary and an auto-chosen visualization.
- **Learning Checkpoint:** Why is it better to let the same LLM turn that generated Cypher *also* choose the visualization, rather than running a separate chart-picker model?

### Task 6 — Run the benchmark, report honest numbers
- `eval/run_benchmark.py` runs all 10 questions, compares generated Cypher to gold (exact match is too strict — use "executes and returns the same row set"), logs hit/miss per question, prints a table.
- Do NOT tune the prompt until after the first run. Record the first-pass numbers.
- Target first pass: 6/10 executable, 4/10 semantically correct. Iterate to 8/10.
- **Learning Checkpoint:** Why record first-pass numbers before tuning? What epistemic mistake does skipping this step lead to?

### Task 7 — Demo script for the CEO
- `demo.py` is a terminal or notebook walkthrough of 5 questions chosen to tell a story: simple → one-hop → UBO → risk traversal → open-ended risk summary with auto-chart.
- Every answer prints: the question, the generated Cypher, the result table, the NL summary, and a link to the rendered chart.
- This is what you screen-share in the 20-minute meeting.
- **Learning Checkpoint:** Why does the demo show the generated Cypher and not hide it? What concern of the CEO does this address? (Hint: explainability, auditability, compliance.)

### Task 8 — Memo (the one that matters)
`MEMO.md` — same format, but this memo is the one you put in front of the CEO.
Problem: "AI-G Data requires text-to-graph-query. We don't have it yet."
Approach: schema-aware prompting + tool calling + safety validator + result-to-chart composition.
Trade-offs: LLM errors, self-hosted-model reliability vs. public-API reliability (and why that trade is worth it here), cost, query cost guard trade-offs, need for human-in-the-loop on write operations.
Result: benchmark numbers from Task 6, three screenshots.
Next step: what v2 looks like — fine-tuning on real anonymized query logs, caching, a "did you mean" clarification loop, multi-turn follow-up ("now filter that to 2023"), integration with the document router so ingested documents immediately become queryable.

## What success looks like
You sit down with the CEO for 20 minutes. You type 5 questions into your demo. He sees the generated Cypher, the result, and the auto-rendered chart or subgraph for each. You end the meeting by handing him a one-page memo and asking one question: *"What would v2 of this need to do for you to put it in front of a client?"* That single question reframes you from intern to collaborator, and his answer is the spec for the next phase of your engagement — which is when conversations about extended scope, contracts, and yes, possibly equity, become real.
