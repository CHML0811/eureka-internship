# EUREKA_MASTER_CONTEXT.md

> Cowork loads this file before touching any project in `eureka_internship/`.
> It encodes who the startup is, what the product does, what the founder cares about, and what "good" looks like for an intern.

---

## 1. The startup in one paragraph

Eureka is a Hong Kong–based KYC / AML compliance platform built around a **graph database** of entities (companies, people, addresses, court cases, sanctions hits, news mentions) sourced from CRIF and public records. Their current product ("AI-G") lets compliance officers visualize relationships and risks as an interactive graph. Their stated next generation ("AI-G Data") is **"talk to the database for deep analysis"** — natural language in, graph query + summary + visualization out. That gap between today's product and the AI-G Data vision is where this internship creates value.

## 2. The founder profile (relationship strategy)

- CEO: 20+ years structured finance / banking compliance background, PhD from MIT, award-driven, technically literate but not an ML researcher.
- He responds to: working demos, crisp one-page memos, correct use of domain vocabulary (UBO, PEP, STR, FATF).
- He does NOT respond to: enthusiasm without artifacts, generic AI buzzwords, long Slack messages.
- Interns rarely get equity. Interns who ship something the founder demos to a client get offers, references, and long-term access — which is the actual prize at a pre-revenue stage.

## 3. What the professor asked for (literal), and what it actually means

**Literal ask #1:** "Build an OCR to read pictures and graphics uploaded to the platform."
**Real deliverable:** A document-understanding *router* that classifies the input (clean form vs. chart/diagram vs. hybrid report), dispatches to the right engine (AWS Textract for forms/tables, a vision-language model for charts/diagrams/hand-drawn org charts), and normalizes output to JSON the graph database can ingest. Classical OCR alone fails on half their real inputs.

**Literal ask #2:** "Generate pie / time series / mind map / distribution charts in chat output. Core concept: LLM emits a graph description language (Mermaid), frontend renders it."
**Real deliverable:** A chart-generation router. Mermaid is the right tool for flowcharts / sequence / mind maps / ER diagrams / state machines. Mermaid is the WRONG tool for pie / bar / line / time series / distribution / scatter — use **Vega-Lite JSON** for those (LLMs produce it reliably under structured output / tool calling). One prompt, two renderers, LLM picks the format.

**Unstated flagship (the real leverage move):** Text-to-Cypher. Their roadmap slide says the 6th-generation target is "can we talk with the database for a deep analysis?" Prototyping even a toy version of this over a small KYC graph demonstrates the next step of their own roadmap. This is the thing the founder will remember.

## 4. Tech stack assumptions (verify in week 1, update this file)

**Updated after reviewing the Eureka pitch deck (slides 2, 38, 41).** The deck itself draws a hard line between two lanes: **Public LLM** (ChatGPT, xAI, Claude, Perplexity) and **Private LLM** (DeepSeek, Llama). Slide 38 goes further and splits "External Data + ChatGPT + Owned Model" from "Internal Data + LLM" — internal/sensitive data is explicitly kept off the public-API path. This is not a style preference; it's the founder's compliance posture. KYC data (entity names, ownership %, sanctions hits, transaction flows, ID documents) is exactly the kind of data a compliance-first founder does not want leaving his infrastructure to a third-party AI vendor. **Every project in this internship must be built on the private lane, not the public one.**

- Graph DB: **Neo4j** (assumed from the visualization style; confirm on day 1)
- Query language: **Cypher**
- Backend: assume **Python** (FastAPI) unless told otherwise
- LLM provider: **self-hosted, open-weight Llama** (Llama 3.1/3.3 for text + tool calling), served locally via **Ollama** (dev) or **vLLM** (closer-to-production). No KYC data is ever sent to Anthropic, OpenAI, or any other public AI vendor's API. Public LLM APIs (Claude, GPT-4o) may only be used against synthetic or already-public data (e.g. drafting boilerplate, non-sensitive test fixtures) — never against real entity/document data, and never as part of the shipped pipeline.
- Vision: **Llama 3.2 Vision** (self-hosted) for diagram/chart/hand-drawn-org-chart understanding; **AWS Textract** for forms and tables. Note: Textract is cloud infrastructure, not a competing foundation-model vendor, but it's still third-party — flag this explicitly in the Project 7 memo as a trade-off the founder should sign off on (self-hosting a forms/OCR engine is a valid v2 ask if he pushes back).
- Frontend chart renderers: **Mermaid.js** + **Vega-Lite** (via `vega-embed`)
- Existing graph visualization on their platform: likely **Cytoscape.js** or **vis.js**
- Tool-calling note: open-weight Llama models are less reliable at structured tool calling than Claude/GPT-4o out of the box. Budget extra time in every "Learning Checkpoint" around retries, schema validation, and fallback prompting — this reliability gap is itself something worth surfacing in each memo's Trade-offs section.

## 5. Domain vocabulary the intern must use correctly

| Term | Meaning | Why it matters |
|---|---|---|
| KYC | Know Your Customer | The whole point of the product |
| AML | Anti-Money-Laundering | Regulatory driver for KYC |
| UBO | Ultimate Beneficial Owner | The person at the top of an ownership chain; graph traversal problem |
| PEP | Politically Exposed Person | High-risk category; screening lists |
| STR / SAR | Suspicious Transaction / Activity Report | Regulatory filing |
| FATF | Financial Action Task Force | Global AML standard-setter; "40 Recommendations" |
| Sanctions screening | Matching entities against OFAC / UN / EU / HKMA lists | Core feature of any KYC tool |
| Adverse media | Negative news mentions tied to an entity | Risk signal, often unstructured text |
| Enhanced Due Diligence (EDD) | Deeper investigation for high-risk clients | Where the graph product shines |

Before starting project 9, skim FATF's 40 Recommendations summary and the Wolfsberg Group FAQ on beneficial ownership. 90 minutes total.

## 6. Skills prioritization (what to practice, in order)

1. **Cypher + Neo4j basics** — free GraphAcademy "Cypher Fundamentals" course, one weekend
2. **LLM tool calling / structured outputs** — practice against a self-hosted Llama model (Ollama's OpenAI-compatible tool-calling API is the fastest path). Optionally skim the Anthropic/OpenAI tool-use docs for concepts, but the code you ship talks to the local model, not their APIs.
3. **Vision-language prompting** for getting reliable JSON from an image
4. **Vega-Lite and Mermaid** as output targets — one day each
5. **KYC/AML domain literacy** — FATF + Wolfsberg, one afternoon
6. **RAG over structured + unstructured** — last, only if time allows

## 7. Global rules for Cowork on these projects

- **One task at a time.** User says "Run Task N" — Cowork runs only that task and stops at its Learning Checkpoint.
- **Show the plan before writing code.** For any task involving more than one file, Cowork outputs a short plan (files to create/edit, key functions, expected I/O) and waits for approval.
- **Learning Checkpoints are mandatory.** Each task ends with 2–4 questions the user must answer in their own words before the next task starts. These are not optional — the point of this internship is to actually learn the stack, not to ship code the user doesn't understand.
- **No secrets in code.** API keys live in `.env`, never in source. If Cowork sees a hardcoded key it must refuse and refactor.
- **No sensitive data to public AI vendors.** Any code path that touches real entity data, document contents, or KYC graph data must call the self-hosted Llama model, never Anthropic/OpenAI/other public APIs. If a task's instructions still reference Claude or GPT-4o for a step that processes real data, treat that as a stale instruction and flag it before writing code — don't silently comply.
- **Every project ends with a one-page memo** (`MEMO.md`) written in the banker format the founder likes: Problem / Approach / Trade-offs / Result / Next step. Maximum one page.
- **Domain vocabulary must be used correctly** in all comments, docstrings, and memos. If Cowork is unsure what a term means, it asks.

## 8. "Done" criteria for the whole internship

By the end of the engagement the intern should have:
- A working document-understanding service that handles at least 3 real input types end-to-end.
- A chat-integrated chart generator that renders Mermaid and Vega-Lite with LLM tool calling.
- A text-to-Cypher agent that answers at least 5 realistic KYC questions over a seeded toy graph, with safety validation on the generated queries.
- Three one-page memos, one per project, suitable to hand the CEO.
- One 20-minute demo booked directly with the CEO once project 9 works end-to-end. This meeting is the relationship inflection point.
