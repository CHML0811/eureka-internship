"""Map mock, Textract, and VLM payloads into the canonical contract."""

from __future__ import annotations

from typing import Any

from doc_router.schema import (
    Entity,
    EntityType,
    ExtractionResult,
    ProvenanceRecord,
    RawExtraction,
    Relationship,
    SourceMetadata,
)


def _relationship_ids(block: dict[str, Any], kind: str) -> list[str]:
    for relationship in block.get("Relationships", []):
        if relationship.get("Type") == kind:
            return list(relationship.get("Ids", []))
    return []


def _block_text(
    block: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> tuple[str, float]:
    words = [by_id[item] for item in _relationship_ids(block, "CHILD") if item in by_id]
    text = " ".join(
        word.get("Text", "")
        for word in words
        if word.get("BlockType") in {"WORD", "SELECTION_ELEMENT"}
    ).strip()
    confidences = [
        float(word.get("Confidence", 0)) / 100
        for word in words
        if word.get("Confidence") is not None
    ]
    return text, (sum(confidences) / len(confidences) if confidences else 0.8)


def _normalize_textract(raw: RawExtraction) -> tuple[list[Entity], list[Relationship]]:
    blocks = list(raw.raw_data.get("Blocks", []))
    by_id = {block["Id"]: block for block in blocks if block.get("Id")}
    candidates: list[tuple[str, float, str]] = []
    for block in blocks:
        block_type = block.get("BlockType")
        if block_type == "KEY_VALUE_SET" and "KEY" in block.get("EntityTypes", []):
            key_text, _ = _block_text(block, by_id)
            for value_id in _relationship_ids(block, "VALUE"):
                value = by_id.get(value_id, {})
                text, confidence = _block_text(value, by_id)
                if text:
                    evidence = f"{key_text}: {text}" if key_text else text
                    candidates.append((text, confidence, evidence))
        elif block_type == "CELL":
            text, confidence = _block_text(block, by_id)
            if text:
                candidates.append((text, confidence, text))

    entities = [
        Entity(
            entity_id=f"e{index}",
            type=EntityType.UNKNOWN,
            name=text,
            raw_text_span=evidence,
            confidence=confidence,
        )
        for index, (text, confidence, evidence) in enumerate(candidates, 1)
    ]
    return entities, []


def _normalize_canonical(raw: RawExtraction) -> tuple[list[Entity], list[Relationship]]:
    data = raw.raw_data.get("result", raw.raw_data)
    entities = [Entity.model_validate(item) for item in data.get("entities", [])]
    relationships = [
        Relationship.model_validate(item) for item in data.get("relationships", [])
    ]
    return entities, relationships


def normalize(
    raw: RawExtraction,
    source_meta: SourceMetadata,
) -> ExtractionResult:
    """Translate one engine response and attach per-field audit provenance."""
    if raw.engine_name == "textract" and "Blocks" in raw.raw_data:
        entities, relationships = _normalize_textract(raw)
    elif raw.engine_name in {"vlm", "mock", "textract"}:
        entities, relationships = _normalize_canonical(raw)
    else:
        raise ValueError(f"Unsupported extraction engine: {raw.engine_name!r}")

    provenance = [
        ProvenanceRecord(
            field_ref=item.entity_id,
            engine=raw.engine_name,
            confidence=item.confidence,
        )
        for item in entities
    ] + [
        ProvenanceRecord(
            field_ref=item.relationship_id,
            engine=raw.engine_name,
            confidence=item.confidence,
        )
        for item in relationships
    ]
    return ExtractionResult(
        entities=entities,
        relationships=relationships,
        source_metadata=source_meta,
        confidence=raw.confidence,
        engine_used=raw.engine_name,
        provenance=provenance,
    )
