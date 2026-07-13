# Project 7 — Document Understanding Router

**[Load EUREKA_MASTER_CONTEXT.md before starting]**

**Updated for the private-model constraint (see EUREKA_MASTER_CONTEXT §4):** the vision-language steps below now target a self-hosted **Llama 3.2 Vision** model instead of Claude/GPT-4o. Real document content (IDs, ownership charts, scanned reports) never leaves Eureka's own infrastructure. AWS Textract remains in the pipeline for forms/tables since it's cloud infra rather than a competing AI vendor — but Task 7's memo should flag that choice explicitly and let the founder weigh in.

## Goal
Build a service that takes any document/image uploaded to Eureka's platform and returns normalized JSON ready for graph ingestion. This replaces the naive "just run OCR" framing with a proper router.

## Why this framing, not plain OCR
Tesseract handles clean printed text. Eureka receives scanned annual reports with mixed text + tables + charts, photographs of ID documents, screenshots of news articles, and hand-drawn UBO/ownership diagrams. No single engine handles all of these. The right architecture is a classifier that dispatches each input to the engine best suited for it, then a fusion step that merges outputs into one schema.

## Architecture
```
input (image/pdf)
    │
    ▼
[1] classifier  ──►  {form_like, chart_like, hybrid_report, id_document, hand_drawn}
    │
    ▼
[2] router
    ├── form_like / id_document     → AWS Textract (key-value + tables)
    ├── chart_like / hand_drawn     → self-hosted Llama 3.2 Vision (structured JSON out)
    └── hybrid_report               → Textract + VLM, fused
    │
    ▼
[3] normalizer  ──►  canonical JSON schema (entities, relationships, metadata, provenance)
    │
    ▼
[4] evaluator   ──►  compare against a 10-doc gold set, print precision/recall per field
```

## Tasks

### Task 1 — Repo setup and canonical schema
- Scaffold `doc_router/` with `classifier.py`, `engines/`, `normalizer.py`, `eval/`, `tests/`.
- Define the canonical JSON schema in `schema.py` using **pydantic**. Fields: `entities[]` (type, name, aliases, identifiers), `relationships[]` (src, dst, kind, weight, evidence_span), `source_metadata`, `confidence`, `engine_used`.
- Create a `.env.example` listing `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`.
- **Learning Checkpoint:** Why is a canonical schema defined *before* any engine is written? What goes wrong if we let each engine define its own output format?

### Task 2 — Document classifier
- Implement a cheap two-stage classifier: (a) heuristic based on file type + resolution + text-density, (b) fallback to a small VLM call asking the self-hosted Llama 3.2 Vision model to label the image into one of the 5 categories.
- Write `classify(image_bytes) -> DocumentType` with an explicit confidence score.
- Add 10 sample images to `tests/fixtures/` covering all 5 categories and write classification unit tests.
- **Learning Checkpoint:** Why run a heuristic stage before calling a VLM? Estimate the cost difference per 1000 documents (for a self-hosted model this is compute/latency cost, not per-call API billing — explain how that changes the calculus vs. a hosted API).

### Task 3 — AWS Textract engine
- Wrap Textract in `engines/textract_engine.py` with a single `extract(image_bytes) -> RawExtraction` function.
- Use Textract's **AnalyzeDocument** with `FORMS` and `TABLES` features. Handle the async path for multi-page PDFs.
- Map Textract's key-value blocks and table cells into the canonical schema via `normalizer.py`.
- **Learning Checkpoint:** What does Textract return that naive Tesseract does not? Name two specific block types and why they matter for KYC.

### Task 4 — Vision-language model engine
- Wrap self-hosted **Llama 3.2 Vision** (served via Ollama or vLLM) in `engines/vlm_engine.py`. Point the client at a local endpoint (e.g. `http://localhost:11434`), configured via `.env`, never at a public API host.
- **Critical:** use Llama's tool-calling support (via Ollama's OpenAI-compatible `/v1/chat/completions` tool-calling API) to force structured JSON output. Define a tool called `record_document_contents` whose input schema matches the canonical `RawExtraction`. Never parse free-form text.
- Open-weight vision models are less consistent at honoring tool schemas than Claude/GPT-4o. Add a validation + retry loop: if the returned JSON fails to parse against `RawExtraction`, feed the validation error back to the model once before falling back to a lower-confidence partial result.
- Write the system prompt so the model is told it is looking at KYC-relevant material and should extract entities, relationships, and any numeric data visible in charts.
- Test on a pie chart, an org chart, and a hand-drawn ownership diagram.
- **Learning Checkpoint:** Why is tool use / structured output more reliable than "please respond in JSON"? What specific failure modes does it eliminate? Separately: what did you observe about Llama 3.2 Vision's tool-calling reliability compared to what you've read about Claude/GPT-4o — and how did your retry loop compensate?

### Task 5 — Fusion for hybrid documents
- For `hybrid_report`, run both engines, then merge: Textract wins on tables and key-value pairs, the VLM wins on chart interpretation and diagram semantics.
- Implement conflict resolution: if both engines emit an entity with overlapping spans, prefer higher-confidence, record both in `provenance`.
- **Learning Checkpoint:** Give one concrete example where Textract and the VLM would disagree, and explain which should win and why.

### Task 6 — Evaluation harness
- Build a 10-document gold set in `eval/gold/` (hand-label entities and relationships in YAML).
- Write `eval/run_eval.py` that prints per-field precision, recall, and F1 against gold, broken down by document type.
- Target: ≥0.8 F1 on `form_like`, ≥0.6 on `chart_like` for the first pass. Not higher — honesty about limits is more credible than inflated numbers.
- **Learning Checkpoint:** Why break down metrics by document type instead of reporting one overall number? What decision does each number drive?

### Task 7 — Memo
Write `MEMO.md` in the format in EUREKA_MASTER_CONTEXT §7: Problem / Approach / Trade-offs / Result / Next step. One page. This is the artifact you show the CEO, not the code.

## What success looks like
The CEO can hand you a photo of a hand-drawn ownership chart, a scanned annual report page, and an ID document, and your service returns three JSON blobs ready to become nodes and edges in Neo4j — with honest confidence scores and provenance on every field.
