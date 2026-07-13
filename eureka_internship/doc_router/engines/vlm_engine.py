"""Structured extraction through the shared private LLM contract."""

from __future__ import annotations

import base64
from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from common.config import Settings
from common.llm import ChatMessage, LLM, ToolDefinition, create_llm
from doc_router.schema import Entity, RawExtraction, Relationship

TOOL_NAME = "record_document_contents"
ALLOWED_MEDIA_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)
SYSTEM_PROMPT = """You analyze private KYC documents inside Eureka infrastructure.
Identify people, companies, addresses, identifiers, ownership and other graph
relationships, plus numeric chart values. Call record_document_contents exactly
once. Preserve verbatim evidence spans and calibrated confidence. Never invent
missing identifiers."""


class CanonicalDocumentContents(BaseModel):
    """The fully specified nested payload required from the vision model."""

    entities: list[Entity]
    relationships: list[Relationship]


class RecordDocumentContents(BaseModel):
    """Tool arguments that validate more strictly than RawExtraction.raw_data."""

    engine_name: Literal["vlm"]
    raw_data: CanonicalDocumentContents
    confidence: float = Field(ge=0.0, le=1.0)


class VLMEngine:
    """Force canonical tool output, with one corrective validation retry."""

    def __init__(self, *, llm: LLM | None = None) -> None:
        if llm is None:
            settings = Settings.from_env()
            llm = create_llm(
                replace(settings, local_llm_model=settings.local_vlm_model)
            )
        self.llm = llm
        self.tool = ToolDefinition.from_model(
            name=TOOL_NAME,
            arguments_model=RecordDocumentContents,
            description="Record structured KYC-relevant document contents.",
        )

    async def extract(
        self, image_bytes: bytes, *, media_type: str = "image/png"
    ) -> RawExtraction:
        if media_type not in ALLOWED_MEDIA_TYPES:
            raise ValueError(f"Unsupported media type: {media_type!r}")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "Extract this document."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{encoded}"
                        },
                    },
                ],
            ),
        ]
        errors: list[str] = []
        for attempt in range(2):
            response = await self.llm.complete(
                messages, tools=[self.tool], temperature=0.0
            )
            try:
                call = next(
                    item for item in response.tool_calls if item.name == TOOL_NAME
                )
                contents = RecordDocumentContents.model_validate(call.arguments)
                return RawExtraction(
                    engine_name="vlm",
                    raw_data=contents.raw_data.model_dump(mode="json"),
                    confidence=contents.confidence,
                )
            except (StopIteration, ValidationError, ValueError) as exc:
                error = (
                    "No record_document_contents tool call was returned"
                    if isinstance(exc, StopIteration)
                    else str(exc)
                )
                errors.append(error)
                if attempt == 0:
                    messages.extend(
                        [
                            ChatMessage(
                                role="assistant",
                                content=response.content
                                or "Invalid structured tool output.",
                            ),
                            ChatMessage(
                                role="user",
                                content=(
                                    "Validation failed. Call the tool again with "
                                    f"schema-valid arguments. Error: {error}"
                                ),
                            ),
                        ]
                    )
        return RawExtraction(
            engine_name="vlm",
            raw_data={
                "entities": [],
                "relationships": [],
                "validation_errors": len(errors),
            },
            confidence=0.2,
        )


async def extract(image_bytes: bytes, *, llm: LLM | None = None) -> RawExtraction:
    """Convenience entry point backed by the configured private VLM."""
    return await VLMEngine(llm=llm).extract(image_bytes)
