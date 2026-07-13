"""
schema.py — Canonical extraction schema for Eureka's Document Understanding Router.

Every engine (Textract, VLM, hybrid) MUST normalize its output to these types.
This contract is defined first so no engine can invent its own format — a lesson
from KYC integration projects where mismatched field names across data sources
create silent data-quality bugs that only surface during sanctions screening or
UBO graph traversal.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Document classification
# ---------------------------------------------------------------------------

class DocumentType(str, Enum):
    """Five categories the classifier assigns to every incoming document."""
    FORM_LIKE = "form_like"           # Structured forms, ID documents, key-value tables
    CHART_LIKE = "chart_like"         # Pie charts, bar charts, time-series, scatter plots
    HYBRID_REPORT = "hybrid_report"   # Annual reports, KYC dossiers: text + tables + charts
    ID_DOCUMENT = "id_document"       # Passports, HKIDs, driver's licences
    HAND_DRAWN = "hand_drawn"         # Hand-drawn UBO / ownership / org charts


# ---------------------------------------------------------------------------
# Entity — a node that will become a Neo4j node
# ---------------------------------------------------------------------------

class EntityType(str, Enum):
    """High-level entity categories relevant to KYC / AML workflows."""
    PERSON = "person"           # Natural person; may be a UBO or PEP
    COMPANY = "company"         # Legal entity; subject to beneficial-ownership rules
    ADDRESS = "address"         # Physical or registered address
    COURT_CASE = "court_case"   # Legal proceedings — adverse media signal
    SANCTION = "sanction"       # Sanctions-list entry (OFAC, UN, EU, HKMA)
    NEWS_MENTION = "news_mention"  # Adverse media hit from a news article
    UNKNOWN = "unknown"         # Classifier could not determine type


class Entity(BaseModel):
    """
    A single extracted entity destined for a Neo4j node.

    `identifiers` is a free dict so we can store heterogeneous ID types without
    schema changes — e.g. {"hkid": "A123456(7)", "passport": "HK12345678",
    "company_reg": "HK-0001234"}.  Downstream graph ingestion maps these to
    node properties and unique constraints.
    """
    entity_id: str = Field(
        description="Stable local ID within this extraction (e.g. 'e1', 'e2')."
    )
    type: EntityType
    name: str
    aliases: list[str] = Field(
        default_factory=list,
        description="Alternative names / transliterations (important for CJK names).",
    )
    identifiers: dict[str, str] = Field(
        default_factory=dict,
        description="Map of identifier type → value (e.g. {'passport': 'HK123'}).",
    )
    raw_text_span: str | None = Field(
        default=None,
        description="Verbatim text from the source document that produced this entity.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Engine confidence in this entity (0.0–1.0).",
    )


# ---------------------------------------------------------------------------
# Relationship — a directed edge for the Neo4j graph
# ---------------------------------------------------------------------------

class RelationshipKind(str, Enum):
    """
    Edge types that matter for KYC / AML graph traversal.
    UBO resolution, PEP screening, and sanctions propagation all rely on these.
    """
    UBO_OF = "UBO_OF"                     # Person is Ultimate Beneficial Owner of company
    DIRECTOR_OF = "DIRECTOR_OF"           # Person holds director position
    SHAREHOLDER_OF = "SHAREHOLDER_OF"     # Ownership stake (see weight for percentage)
    SANCTIONED_BY = "SANCTIONED_BY"       # Entity appears on a sanctions list
    ASSOCIATED_WITH = "ASSOCIATED_WITH"   # Generic association (adverse media, etc.)
    LOCATED_AT = "LOCATED_AT"             # Entity registered / resident at address
    INVOLVED_IN = "INVOLVED_IN"           # Entity named in court case
    MENTIONED_IN = "MENTIONED_IN"         # Entity mentioned in news article
    UNKNOWN = "UNKNOWN"                   # Could not determine relationship type


class Relationship(BaseModel):
    """
    A directed relationship between two entities → Neo4j edge.

    `weight` carries semantically relevant numeric data: ownership percentage for
    SHAREHOLDER_OF, risk score for ASSOCIATED_WITH, etc.  Storing it here lets
    the graph run weighted traversals for EDD without schema changes.
    """
    relationship_id: str = Field(
        description="Stable local ID within this extraction (e.g. 'r1', 'r2')."
    )
    src: str = Field(description="entity_id of the source node.")
    dst: str = Field(description="entity_id of the destination node.")
    kind: RelationshipKind
    weight: float | None = Field(
        default=None,
        description=(
            "Numeric weight; semantics depend on kind. "
            "For SHAREHOLDER_OF: ownership percentage (0–100). "
            "For risk edges: score (0.0–1.0)."
        ),
    )
    evidence_span: str | None = Field(
        default=None,
        description="Verbatim text that evidences this relationship.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Engine confidence in this relationship (0.0–1.0).",
    )


# ---------------------------------------------------------------------------
# Source metadata — provenance for every extraction
# ---------------------------------------------------------------------------

class SourceMetadata(BaseModel):
    """
    Provenance record attached to every extraction result.

    Compliance auditors need to trace any graph node back to the document it
    came from — this is a hard requirement for STR / SAR documentation.
    """
    filename: str | None = None
    page_number: int | None = None
    document_type: DocumentType | None = None
    sha256_hash: str | None = Field(
        default=None,
        description="SHA-256 of the raw input bytes for tamper detection.",
    )
    ingested_at: str | None = Field(
        default=None,
        description="ISO-8601 UTC timestamp of when this document was processed.",
    )


# ---------------------------------------------------------------------------
# Raw extraction — intermediate output from a single engine
# ---------------------------------------------------------------------------

class RawExtraction(BaseModel):
    """
    Intermediate output type returned by each engine before normalization.
    Engines return this; the normalizer maps it to ExtractionResult.
    """
    engine_name: str
    raw_data: dict[str, Any] = Field(
        description="Engine-native output (Textract blocks, VLM JSON, etc.)."
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Provenance record — tracks which engine produced each field
# ---------------------------------------------------------------------------

class ProvenanceRecord(BaseModel):
    """
    Records which engine produced a given entity or relationship.
    Required for hybrid documents where Textract and the VLM both contribute.
    """
    field_ref: str = Field(
        description="entity_id or relationship_id this record applies to."
    )
    engine: str = Field(description="Engine that produced this field.")
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str | None = None


# ---------------------------------------------------------------------------
# ExtractionResult — the canonical top-level output of the whole pipeline
# ---------------------------------------------------------------------------

class ExtractionResult(BaseModel):
    """
    The single output type the Document Understanding Router exposes to callers.

    Downstream consumers (graph ingestion service, compliance UI) only ever see
    this type — they are fully decoupled from which engine(s) produced it.

    Fields map directly to Neo4j ingest:
      - entities[]      → CREATE (n:EntityType {…}) nodes
      - relationships[] → CREATE (a)-[:KIND {weight}]->(b) edges
      - source_metadata → attached as provenance properties on each node/edge
    """
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    source_metadata: SourceMetadata = Field(default_factory=SourceMetadata)
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Overall pipeline confidence for this extraction.",
    )
    engine_used: str = Field(
        description=(
            "Which engine(s) produced this result. "
            "Single engine: 'textract' or 'vlm'. "
            "Hybrid: 'textract+vlm'."
        ),
    )
    provenance: list[ProvenanceRecord] = Field(
        default_factory=list,
        description=(
            "Per-field provenance records. Required for hybrid results "
            "and any field where confidence < 0.9."
        ),
    )
