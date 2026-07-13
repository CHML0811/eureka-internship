"""Conflict-aware fusion for reports containing forms and diagrams."""

from __future__ import annotations

from doc_router.schema import (
    ExtractionResult,
    ProvenanceRecord,
    Relationship,
)


def _entity_key(name: str, entity_type: str) -> tuple[str, str]:
    normalized = " ".join(name.casefold().replace(".", "").split())
    return normalized, entity_type


def fuse(
    textract: ExtractionResult, vlm: ExtractionResult
) -> ExtractionResult:
    """Merge engines, preferring confidence while retaining both audit trails."""
    merged_entities = []
    key_to_index: dict[tuple[str, str], int] = {}
    id_maps: dict[str, dict[str, str]] = {"textract": {}, "vlm": {}}
    relationship_id_maps: dict[str, dict[str, str]] = {"textract": {}, "vlm": {}}
    provenance: list[ProvenanceRecord] = []

    for engine, result in (("textract", textract), ("vlm", vlm)):
        for entity in result.entities:
            key = _entity_key(entity.name, entity.type.value)
            if key not in key_to_index:
                canonical_id = f"e{len(merged_entities) + 1}"
                key_to_index[key] = len(merged_entities)
                merged_entities.append(
                    entity.model_copy(update={"entity_id": canonical_id})
                )
            else:
                index = key_to_index[key]
                canonical_id = merged_entities[index].entity_id
                if entity.confidence > merged_entities[index].confidence:
                    merged_entities[index] = entity.model_copy(
                        update={"entity_id": canonical_id}
                    )
            id_maps[engine][entity.entity_id] = canonical_id
            if not any(
                record.field_ref == entity.entity_id
                for record in result.provenance
            ):
                provenance.append(
                    ProvenanceRecord(
                        field_ref=canonical_id,
                        engine=engine,
                        confidence=entity.confidence,
                        notes="contributed to hybrid entity",
                    )
                )

    merged_relationships: list[Relationship] = []
    seen_relationships: set[tuple[str, str, str, float | None]] = set()
    for engine, result in (("textract", textract), ("vlm", vlm)):
        for relationship in result.relationships:
            source = id_maps[engine].get(relationship.src)
            destination = id_maps[engine].get(relationship.dst)
            if source is None or destination is None:
                continue
            key = (source, destination, relationship.kind.value, relationship.weight)
            if key in seen_relationships:
                continue
            seen_relationships.add(key)
            relationship_id = f"r{len(merged_relationships) + 1}"
            relationship_id_maps[engine][relationship.relationship_id] = relationship_id
            merged_relationships.append(
                relationship.model_copy(
                    update={
                        "relationship_id": relationship_id,
                        "src": source,
                        "dst": destination,
                    }
                )
            )
            if not any(
                record.field_ref == relationship.relationship_id
                for record in result.provenance
            ):
                provenance.append(
                    ProvenanceRecord(
                        field_ref=relationship_id,
                        engine=engine,
                        confidence=relationship.confidence,
                    )
                )

    for engine, result in (("textract", textract), ("vlm", vlm)):
        for record in result.provenance:
            canonical_id = id_maps[engine].get(
                record.field_ref,
                relationship_id_maps[engine].get(record.field_ref),
            )
            if canonical_id is not None:
                provenance.append(
                    record.model_copy(update={"field_ref": canonical_id})
                )

    return ExtractionResult(
        entities=merged_entities,
        relationships=merged_relationships,
        source_metadata=textract.source_metadata,
        confidence=(textract.confidence + vlm.confidence) / 2,
        engine_used="textract+vlm",
        provenance=provenance,
    )
