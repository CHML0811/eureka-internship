"""Cheap visual document classification with an injectable private VLM fallback."""

from __future__ import annotations

import base64
import inspect
import struct
import zlib
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from common.llm import ChatMessage, LLM, ToolDefinition, create_llm

from doc_router.schema import DocumentType

Classification = tuple[DocumentType, float]
Fallback = Callable[[bytes], Classification | Awaitable[Classification]]
_DEFAULT_FALLBACK = object()


class ClassificationArguments(BaseModel):
    """Structured output for the uncertain-image classification fallback."""

    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)


class LLMDocumentClassifier:
    """Classify ambiguous images through the configured private vision model."""

    def __init__(self, llm: LLM | None = None) -> None:
        self.llm = llm or create_llm()
        self.tool = ToolDefinition.from_model(
            name="classify_document",
            description="Classify a private KYC document image.",
            arguments_model=ClassificationArguments,
        )

    async def __call__(self, image_bytes: bytes) -> Classification:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = await self.llm.complete(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "Classify the image as exactly one of: form_like, "
                        "chart_like, hybrid_report, id_document, hand_drawn. "
                        "Call classify_document once with calibrated confidence."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "Classify this document."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{encoded}"
                            },
                        },
                    ],
                ),
            ],
            tools=[self.tool],
            temperature=0.0,
        )
        call = next(
            (
                item
                for item in response.tool_calls
                if item.name == "classify_document"
            ),
            None,
        )
        if call is None:
            return DocumentType.HYBRID_REPORT, 0.2
        result = ClassificationArguments.model_validate(call.arguments)
        return result.document_type, result.confidence


def _decode_grayscale_png(data: bytes) -> tuple[int, int, bytes] | None:
    """Decode the non-interlaced, filter-0 grayscale PNG subset used in fixtures."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset, width, height, compressed = 8, 0, 0, bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += length + 12
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if (depth, color, interlace) != (8, 0, 0):
                return None
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    try:
        rows = zlib.decompress(bytes(compressed))
    except zlib.error:
        return None
    stride = width + 1
    if not width or len(rows) != stride * height:
        return None
    if any(rows[index * stride] != 0 for index in range(height)):
        return None
    pixels = b"".join(
        rows[index * stride + 1 : (index + 1) * stride] for index in range(height)
    )
    return width, height, pixels


class DocumentClassifier:
    """Classify obvious layouts locally and delegate ambiguous images."""

    def __init__(
        self,
        fallback: Fallback | None | object = _DEFAULT_FALLBACK,
    ) -> None:
        self.fallback: Fallback | None = (
            LLMDocumentClassifier()
            if fallback is _DEFAULT_FALLBACK
            else fallback  # type: ignore[assignment]
        )

    def _heuristic(self, image_bytes: bytes) -> Classification | None:
        decoded = _decode_grayscale_png(image_bytes)
        if decoded:
            width, height, pixels = decoded
            ink = [value < 128 for value in pixels]
            density = sum(ink) / len(ink)
            row_density = [
                sum(ink[y * width : (y + 1) * width]) / width
                for y in range(height)
            ]
            strong_rows = sum(value >= 0.65 for value in row_density)
            aspect = width / height

            if aspect >= 1.45 and density >= 0.03:
                return DocumentType.ID_DOCUMENT, 0.94
            if aspect <= 0.8 and strong_rows >= 4 and density < 0.14:
                return DocumentType.FORM_LIKE, 0.92
            if aspect <= 0.8 and strong_rows >= 3 and density >= 0.14:
                return DocumentType.HYBRID_REPORT, 0.9
            if 0.8 < aspect < 1.35 and density >= 0.12:
                return DocumentType.CHART_LIKE, 0.88
            if 0.8 < aspect < 1.35 and 0.002 <= density < 0.12:
                return DocumentType.HAND_DRAWN, 0.84
        return None

    def classify(self, image_bytes: bytes) -> Classification:
        result = self._heuristic(image_bytes)
        if result is not None:
            return result
        if self.fallback is not None:
            fallback_result = self.fallback(image_bytes)
            if inspect.isawaitable(fallback_result):
                raise RuntimeError(
                    "Async classification fallback requires classify_async()"
                )
            document_type, confidence = fallback_result
            return DocumentType(document_type), max(0.0, min(float(confidence), 1.0))
        return DocumentType.HYBRID_REPORT, 0.35

    async def classify_async(self, image_bytes: bytes) -> Classification:
        result = self._heuristic(image_bytes)
        if result is not None:
            return result
        if self.fallback is None:
            return DocumentType.HYBRID_REPORT, 0.35
        fallback_result = self.fallback(image_bytes)
        if inspect.isawaitable(fallback_result):
            fallback_result = await fallback_result
        document_type, confidence = fallback_result
        return DocumentType(document_type), max(0.0, min(float(confidence), 1.0))


def classify(
    image_bytes: bytes, fallback: Fallback | None = None
) -> Classification:
    """Compatibility function for callers that do not need a classifier object."""
    return DocumentClassifier(fallback=fallback).classify(image_bytes)
