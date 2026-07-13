# Document Understanding Router

Offline-first Project 7 implementation. It classifies a document, dispatches it
to Textract, a private VLM, or both, and returns the canonical `ExtractionResult`
from `schema.py`.

## Quick start

Run from `eureka_internship/`:

```bash
./.venv/bin/python -m pytest doc_router/tests/test_project7.py -q
./.venv/bin/python -m doc_router.eval.run_eval
```

Minimal service usage:

```python
import asyncio
from pathlib import Path

from doc_router.router import DocumentRouter

document = Path("form.png").read_bytes()
result = asyncio.run(DocumentRouter().route(document, filename="form.png"))
print(result.model_dump_json(indent=2))
```

Defaults are safe and deterministic: `TEXTRACT_PROVIDER=mock` and
`LLM_PROVIDER=mock`. For real forms, set `TEXTRACT_PROVIDER=aws`, configure the
normal AWS credential chain, and inject a private S3 uploader into
`TextractEngine` for PDFs together with its exact `allowed_pdf_bucket`; PDF
analysis refuses unapproved bucket names. For real vision extraction, set
`LLM_PROVIDER=ollama`, `LOCAL_LLM_BASE_URL` to a localhost/private-network
OpenAI-compatible endpoint, and `LOCAL_VLM_MODEL=llama3.2-vision`.

No public-model path exists. Image bytes are embedded only in requests sent
through the shared `common.llm` private-endpoint guard. The included 10-image
fixture set is generated in memory, and all evaluation labels and metrics are
explicitly mock/synthetic.
