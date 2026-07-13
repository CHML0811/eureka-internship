# Document Understanding Router

## Problem

Eureka receives clean forms, ID photographs, mixed annual-report pages, charts,
and hand-drawn ownership diagrams. Plain OCR cannot recover table structure,
chart meaning, or UBO relationships consistently, and incompatible engine
outputs would create silent graph-ingestion errors.

## Approach

The service first applies deterministic image-layout heuristics and can delegate
ambiguous cases to an injected private classifier. Forms and IDs route to AWS
Textract; charts and hand-drawn diagrams route to self-hosted Llama 3.2 Vision;
hybrid reports run both. Every engine result is validated and normalized into
one Pydantic contract for Neo4j nodes and edges. VLM extraction is forced
through the `record_document_contents` tool and receives one corrective retry.
Hybrid fusion deduplicates overlapping entities, selects the higher-confidence
value, remaps relationship IDs, and retains per-field provenance.

## Trade-offs

AWS Textract provides `KEY_VALUE_SET`, `CELL`, and relationship blocks that
naive OCR does not, but document content leaves Eureka-controlled
infrastructure for AWS. This third-party processing choice requires founder,
security, residency, retention, and DPA sign-off; a self-hosted OCR/forms engine
is the v2 alternative. Open-weight vision tool calling is less reliable than
leading hosted models, so schema validation, one retry, and an explicit
low-confidence partial result are required. Deterministic heuristics save model
latency but uncertain real-world layouts still need calibration.

## Result

Project 7 now runs end-to-end with safe mock defaults, synchronous image and
asynchronous multi-page PDF Textract paths, private VLM extraction, canonical
normalization, hybrid provenance, tamper-evident source hashes, ten generated
fixture images, and ten hand-labeled YAML records. Evaluation output is clearly
marked **mock/synthetic**; it is integration evidence, not a production
accuracy claim.

## Next step

Obtain privacy sign-off for Textract, then benchmark 30–50 de-identified,
representative documents by type. Tune classifier thresholds, measure field
F1 and VLM retry rates, perform STR/SAR audit-trace review, and decide whether
AWS or a self-hosted forms stack should enter a controlled production pilot.
