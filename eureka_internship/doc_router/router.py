"""End-to-end orchestration service for document understanding."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

from doc_router.classifier import DocumentClassifier
from doc_router.engines.hybrid_engine import fuse
from doc_router.engines.textract_engine import TextractEngine
from doc_router.engines.vlm_engine import VLMEngine
from doc_router.normalizer import normalize
from doc_router.schema import DocumentType, ExtractionResult, SourceMetadata


class DocumentRouter:
    """Classify, dispatch, normalize, and preserve source integrity metadata."""

    def __init__(
        self,
        *,
        classifier: DocumentClassifier | None = None,
        textract: TextractEngine | None = None,
        vlm: VLMEngine | None = None,
    ) -> None:
        self.classifier = classifier or DocumentClassifier()
        self.textract = textract or TextractEngine()
        self.vlm = vlm or VLMEngine()

    async def route(
        self, document_bytes: bytes, *, filename: str | None = None
    ) -> ExtractionResult:
        document_type, classification_confidence = (
            await self.classifier.classify_async(document_bytes)
        )
        metadata = SourceMetadata(
            filename=filename,
            document_type=document_type,
            sha256_hash=hashlib.sha256(document_bytes).hexdigest(),
            ingested_at=datetime.now(timezone.utc).isoformat(),
        )
        if document_type in {DocumentType.FORM_LIKE, DocumentType.ID_DOCUMENT}:
            raw = await asyncio.to_thread(
                self.textract.extract, document_bytes, filename=filename
            )
            result = normalize(
                raw, metadata
            )
        elif document_type in {DocumentType.CHART_LIKE, DocumentType.HAND_DRAWN}:
            result = normalize(await self.vlm.extract(document_bytes), metadata)
        else:
            textract_raw, vlm_raw = await asyncio.gather(
                asyncio.to_thread(
                    self.textract.extract, document_bytes, filename=filename
                ),
                self.vlm.extract(document_bytes),
            )
            textract_result = normalize(textract_raw, metadata)
            vlm_result = normalize(vlm_raw, metadata)
            result = fuse(textract_result, vlm_result)
        return result.model_copy(
            update={
                "confidence": min(result.confidence, classification_confidence)
            }
        )


async def route(
    document_bytes: bytes, *, filename: str | None = None
) -> ExtractionResult:
    """Route with safe environment-backed defaults."""
    return await DocumentRouter().route(document_bytes, filename=filename)
