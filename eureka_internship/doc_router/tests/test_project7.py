from __future__ import annotations

import asyncio
import struct
import time
import zlib
from pathlib import Path

import pytest

from common.llm import LLMResponse, MockLLM, ToolCall
from doc_router.classifier import DocumentClassifier, LLMDocumentClassifier
from doc_router.engines.hybrid_engine import fuse
from doc_router.engines.textract_engine import TextractEngine
from doc_router.engines.vlm_engine import VLMEngine
from doc_router.eval.run_eval import evaluate
from doc_router.fixture_generator import generate_fixture
from doc_router.normalizer import normalize
from doc_router.router import DocumentRouter
from doc_router.schema import (
    DocumentType,
    Entity,
    EntityType,
    ExtractionResult,
    RawExtraction,
    Relationship,
    RelationshipKind,
    SourceMetadata,
    ProvenanceRecord,
)


def test_classifier_uses_deterministic_image_heuristics() -> None:
    expected = {
        "form_like_1": DocumentType.FORM_LIKE,
        "form_like_2": DocumentType.FORM_LIKE,
        "chart_like_1": DocumentType.CHART_LIKE,
        "chart_like_2": DocumentType.CHART_LIKE,
        "hybrid_report_1": DocumentType.HYBRID_REPORT,
        "hybrid_report_2": DocumentType.HYBRID_REPORT,
        "id_document_1": DocumentType.ID_DOCUMENT,
        "id_document_2": DocumentType.ID_DOCUMENT,
        "hand_drawn_1": DocumentType.HAND_DRAWN,
        "hand_drawn_2": DocumentType.HAND_DRAWN,
    }
    classifier = DocumentClassifier(fallback=None)

    for name, document_type in expected.items():
        result, confidence = classifier.classify(generate_fixture(name))
        assert result is document_type
        assert confidence >= 0.8


def test_classifier_calls_injectable_fallback_when_heuristics_uncertain() -> None:
    calls: list[bytes] = []

    def fallback(data: bytes) -> tuple[DocumentType, float]:
        calls.append(data)
        return DocumentType.HAND_DRAWN, 0.73

    blank = generate_fixture("uncertain")
    result = DocumentClassifier(fallback=fallback).classify(blank)

    assert result == (DocumentType.HAND_DRAWN, 0.73)
    assert calls == [blank]


def test_classifier_uses_structured_private_llm_for_uncertain_images() -> None:
    llm = MockLLM(
        [
            LLMResponse(
                model="mock",
                tool_calls=[
                    ToolCall(
                        id="classify",
                        name="classify_document",
                        arguments={
                            "document_type": "hand_drawn",
                            "confidence": 0.77,
                        },
                    )
                ],
            )
        ]
    )
    classifier = DocumentClassifier(fallback=LLMDocumentClassifier(llm=llm))

    result = asyncio.run(classifier.classify_async(generate_fixture("uncertain")))

    assert result == (DocumentType.HAND_DRAWN, 0.77)


def test_textract_mock_and_real_single_page_paths() -> None:
    mock = TextractEngine(provider="mock").extract(b"image", filename="form.png")
    assert mock.engine_name == "textract"
    assert mock.raw_data["mode"] == "mock"

    class Client:
        def analyze_document(self, **kwargs):
            assert kwargs["FeatureTypes"] == ["FORMS", "TABLES"]
            assert kwargs["Document"] == {"Bytes": b"image"}
            return {"Blocks": [{"BlockType": "WORD", "Text": "Eureka"}]}

    real = TextractEngine(provider="aws", client=Client()).extract(
        b"image", filename="form.png"
    )
    assert real.raw_data["Blocks"][0]["Text"] == "Eureka"


def test_textract_async_pdf_collects_all_pages() -> None:
    class Client:
        def start_document_analysis(self, **kwargs):
            assert kwargs["FeatureTypes"] == ["FORMS", "TABLES"]
            return {"JobId": "job-1"}

        def get_document_analysis(self, **kwargs):
            if kwargs.get("NextToken"):
                return {
                    "JobStatus": "SUCCEEDED",
                    "Blocks": [{"Id": "page-2"}],
                }
            return {
                "JobStatus": "SUCCEEDED",
                "Blocks": [{"Id": "page-1"}],
                "NextToken": "next",
            }

    uploaded: list[bytes] = []

    def upload(data: bytes, filename: str) -> dict[str, str]:
        uploaded.append(data)
        return {"S3Object": {"Bucket": "private", "Name": filename}}

    result = TextractEngine(
        provider="aws",
        client=Client(),
        pdf_uploader=upload,
        allowed_pdf_bucket="private",
        poll_interval=0,
    ).extract(b"%PDF-1.7", filename="report.pdf")

    assert uploaded == [b"%PDF-1.7"]
    assert [block["Id"] for block in result.raw_data["Blocks"]] == [
        "page-1",
        "page-2",
    ]


def test_textract_pdf_rejects_invalid_s3_upload_location() -> None:
    engine = TextractEngine(
        provider="aws",
        client=object(),
        pdf_uploader=lambda _data, _filename: {"Bucket": "missing-wrapper"},
        allowed_pdf_bucket="private",
    )

    with pytest.raises(ValueError, match="S3Object"):
        engine.extract(b"%PDF-1.7", filename="report.pdf")


def test_document_router_keeps_event_loop_responsive_during_textract() -> None:
    class FixedClassifier:
        async def classify_async(self, _: bytes) -> tuple[DocumentType, float]:
            return DocumentType.FORM_LIKE, 0.9

    class SlowTextract:
        def extract(self, _: bytes, *, filename: str | None = None) -> RawExtraction:
            del filename
            time.sleep(0.05)
            return RawExtraction(
                engine_name="textract",
                raw_data={"Blocks": []},
                confidence=0.9,
            )

    async def scenario() -> None:
        router = DocumentRouter(
            classifier=FixedClassifier(),  # type: ignore[arg-type]
            textract=SlowTextract(),  # type: ignore[arg-type]
        )
        task = asyncio.create_task(router.route(b"image", filename="form.png"))
        await asyncio.sleep(0.01)
        assert not task.done()
        await task

    asyncio.run(scenario())


def test_vlm_uses_tool_and_retries_validation_once() -> None:
    valid = {
        "engine_name": "vlm",
        "raw_data": {
            "entities": [
                {
                    "entity_id": "e1",
                    "type": "company",
                    "name": "Eureka",
                    "confidence": 0.9,
                }
            ],
            "relationships": [],
        },
        "confidence": 0.9,
    }
    llm = MockLLM(
        responses=[
            LLMResponse(
                model="mock",
                tool_calls=[
                    ToolCall(
                        id="bad", name="record_document_contents", arguments={"oops": 1}
                    )
                ],
            ),
            LLMResponse(
                model="mock",
                tool_calls=[
                    ToolCall(
                        id="good",
                        name="record_document_contents",
                        arguments=valid,
                    )
                ],
            ),
        ]
    )

    raw = asyncio.run(VLMEngine(llm=llm).extract(b"private-image"))

    assert raw.engine_name == "vlm"
    assert raw.raw_data["entities"][0]["name"] == "Eureka"


def test_vlm_returns_low_confidence_partial_after_failed_retry() -> None:
    bad_response = LLMResponse(content="not a tool call", model="mock")
    raw = asyncio.run(
        VLMEngine(llm=MockLLM([bad_response, bad_response])).extract(b"image")
    )
    assert raw == RawExtraction(
        engine_name="vlm",
        raw_data={"entities": [], "relationships": [], "validation_errors": 2},
        confidence=0.2,
    )


def test_vlm_rejects_unsupported_media_types_before_building_data_url() -> None:
    with pytest.raises(ValueError, match="Unsupported media type"):
        asyncio.run(
            VLMEngine(llm=MockLLM()).extract(
                b"image",
                media_type="text/html",
            )
        )


def test_vlm_retries_when_nested_canonical_contents_are_missing() -> None:
    invalid = {
        "engine_name": "vlm",
        "raw_data": {"unstructured": "not canonical"},
        "confidence": 0.99,
    }
    valid = {
        "engine_name": "vlm",
        "raw_data": {
            "entities": [
                {
                    "entity_id": "e1",
                    "type": "company",
                    "name": "Validated Ltd",
                }
            ],
            "relationships": [],
        },
        "confidence": 0.8,
    }
    llm = MockLLM(
        [
            LLMResponse(
                model="mock",
                tool_calls=[
                    ToolCall(
                        id="invalid",
                        name="record_document_contents",
                        arguments=invalid,
                    )
                ],
            ),
            LLMResponse(
                model="mock",
                tool_calls=[
                    ToolCall(
                        id="valid",
                        name="record_document_contents",
                        arguments=valid,
                    )
                ],
            ),
        ]
    )
    result = asyncio.run(VLMEngine(llm=llm).extract(b"image"))
    assert result.raw_data["entities"][0]["name"] == "Validated Ltd"


def test_normalizer_handles_canonical_and_textract_payloads() -> None:
    metadata = SourceMetadata(filename="form.png")
    canonical = RawExtraction(
        engine_name="vlm",
        raw_data={
            "entities": [
                {
                    "entity_id": "e1",
                    "type": "person",
                    "name": "Ada",
                    "confidence": 0.8,
                }
            ],
            "relationships": [],
        },
        confidence=0.8,
    )
    assert normalize(canonical, metadata).entities[0].name == "Ada"

    blocks = [
        {
            "Id": "k",
            "BlockType": "KEY_VALUE_SET",
            "EntityTypes": ["KEY"],
            "Relationships": [{"Type": "VALUE", "Ids": ["v"]}],
        },
        {
            "Id": "v",
            "BlockType": "KEY_VALUE_SET",
            "EntityTypes": ["VALUE"],
            "Relationships": [{"Type": "CHILD", "Ids": ["w2"]}],
        },
        {
            "Id": "w2",
            "BlockType": "WORD",
            "Text": "Eureka Ltd",
            "Confidence": 98,
        },
        {
            "Id": "c",
            "BlockType": "CELL",
            "RowIndex": 1,
            "ColumnIndex": 1,
            "Relationships": [{"Type": "CHILD", "Ids": ["w1"]}],
        },
        {
            "Id": "w1",
            "BlockType": "WORD",
            "Text": "Company",
            "Confidence": 99,
        },
    ]
    normalized = normalize(
        RawExtraction(
            engine_name="textract",
            raw_data={"Blocks": blocks},
            confidence=0.95,
        ),
        metadata,
    )
    assert {entity.name for entity in normalized.entities} == {
        "Eureka Ltd",
        "Company",
    }
    assert all(item.engine == "textract" for item in normalized.provenance)


def _result(
    engine: str, entity_name: str, confidence: float, relationship: bool = False
) -> ExtractionResult:
    return ExtractionResult(
        entities=[
            Entity(
                entity_id="e1",
                type=EntityType.COMPANY,
                name=entity_name,
                confidence=confidence,
            )
        ],
        relationships=(
            [
                Relationship(
                    relationship_id="r1",
                    src="e1",
                    dst="e1",
                    kind=RelationshipKind.ASSOCIATED_WITH,
                    confidence=confidence,
                )
            ]
            if relationship
            else []
        ),
        source_metadata=SourceMetadata(filename="report.pdf"),
        confidence=confidence,
        engine_used=engine,
    )


def test_hybrid_fusion_deduplicates_and_preserves_provenance() -> None:
    merged = fuse(
        _result("textract", "Eureka Ltd", 0.8),
        _result("vlm", "Eureka Ltd", 0.95, relationship=True),
    )
    assert len(merged.entities) == 1
    assert merged.entities[0].confidence == 0.95
    assert merged.engine_used == "textract+vlm"
    assert {record.engine for record in merged.provenance if record.field_ref == "e1"} == {
        "textract",
        "vlm",
    }
    assert merged.relationships[0].src == "e1"


def test_hybrid_provenance_uses_canonical_ids_when_engine_order_differs() -> None:
    textract = ExtractionResult(
        entities=[
            Entity(entity_id="e1", type=EntityType.PERSON, name="Alice"),
            Entity(entity_id="e2", type=EntityType.COMPANY, name="Bob Corp"),
        ],
        source_metadata=SourceMetadata(),
        engine_used="textract",
        provenance=[
            ProvenanceRecord(field_ref="e1", engine="textract", confidence=0.9)
        ],
    )
    vlm = ExtractionResult(
        entities=[
            Entity(entity_id="e1", type=EntityType.COMPANY, name="Bob Corp"),
            Entity(entity_id="e2", type=EntityType.PERSON, name="Alice"),
        ],
        source_metadata=SourceMetadata(),
        engine_used="vlm",
        provenance=[
            ProvenanceRecord(
                field_ref="e1",
                engine="vlm",
                confidence=0.9,
                notes="Bob source record",
            )
        ],
    )
    merged = fuse(textract, vlm)
    bob_id = next(item.entity_id for item in merged.entities if item.name == "Bob Corp")
    assert any(
        item.field_ref == bob_id and item.notes == "Bob source record"
        for item in merged.provenance
    )


def test_hybrid_fusion_does_not_duplicate_existing_entity_provenance() -> None:
    textract = _result("textract", "Eureka Ltd", 0.8)
    textract.provenance = [
        ProvenanceRecord(field_ref="e1", engine="textract", confidence=0.8)
    ]
    vlm = _result("vlm", "Eureka Ltd", 0.9)
    vlm.provenance = [
        ProvenanceRecord(field_ref="e1", engine="vlm", confidence=0.9)
    ]

    merged = fuse(textract, vlm)

    assert len(
        [record for record in merged.provenance if record.field_ref == "e1"]
    ) == 2


def test_router_dispatches_and_sets_tamper_evident_metadata() -> None:
    router = DocumentRouter(
        classifier=DocumentClassifier(fallback=None),
        textract=TextractEngine(provider="mock"),
        vlm=VLMEngine(llm=MockLLM()),
    )
    result = asyncio.run(
        router.route(generate_fixture("form_like_1"), filename="form.png")
    )
    assert result.engine_used == "textract"
    assert result.source_metadata.document_type is DocumentType.FORM_LIKE
    assert len(result.source_metadata.sha256_hash or "") == 64
    assert result.source_metadata.ingested_at


def test_gold_set_and_eval_report_are_explicitly_synthetic() -> None:
    gold_dir = Path(__file__).parents[1] / "eval" / "gold"
    report = evaluate(gold_dir=gold_dir, predictions={})

    assert len(list(gold_dir.glob("*.yaml"))) == 10
    assert report["dataset"] == "mock/synthetic"
    assert set(report["overall"]) == {"entities", "relationships"}
    assert all(
        {"precision", "recall", "f1"} <= metrics.keys()
        for metrics in report["overall"].values()
    )
