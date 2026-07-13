"""Evaluation runner for the explicitly synthetic Project 7 integration set."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import yaml

from common.llm import MockLLM
from doc_router.engines.textract_engine import TextractEngine
from doc_router.engines.vlm_engine import VLMEngine
from doc_router.fixture_generator import generate_fixture
from doc_router.router import DocumentRouter
from doc_router.schema import ExtractionResult


def _scores(predicted: set[tuple[Any, ...]], gold: set[tuple[Any, ...]]) -> dict[str, float]:
    true_positive = len(predicted & gold)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(gold) if gold else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def _sets(payload: dict[str, Any]) -> tuple[set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    entities = {
        (item.get("type", "unknown"), " ".join(item["name"].casefold().split()))
        for item in payload.get("entities", [])
    }
    names = {
        item.get("entity_id"): " ".join(item["name"].casefold().split())
        for item in payload.get("entities", [])
    }
    relationships = {
        (
            names.get(item["src"], item["src"]),
            names.get(item["dst"], item["dst"]),
            item["kind"],
            item.get("weight"),
        )
        for item in payload.get("relationships", [])
    }
    return entities, relationships


def evaluate(
    *,
    gold_dir: Path,
    predictions: dict[str, ExtractionResult | dict[str, Any]],
) -> dict[str, Any]:
    """Compute exact-match extraction metrics overall and by document type."""
    accumulators: dict[str, dict[str, list[set[tuple[Any, ...]]]]] = {}
    overall = {
        "entities": [set(), set()],
        "relationships": [set(), set()],
    }
    for path in sorted(gold_dir.glob("*.yaml")):
        gold = yaml.safe_load(path.read_text())
        prediction = predictions.get(path.stem)
        predicted_payload = (
            prediction.model_dump(mode="json")
            if isinstance(prediction, ExtractionResult)
            else prediction or {}
        )
        predicted_sets = _sets(predicted_payload)
        gold_sets = _sets(gold)
        document_type = gold["document_type"]
        bucket = accumulators.setdefault(
            document_type,
            {"entities": [set(), set()], "relationships": [set(), set()]},
        )
        for index, field in enumerate(("entities", "relationships")):
            tagged_predicted = {(path.stem, *item) for item in predicted_sets[index]}
            tagged_gold = {(path.stem, *item) for item in gold_sets[index]}
            overall[field][0].update(tagged_predicted)
            overall[field][1].update(tagged_gold)
            bucket[field][0].update(tagged_predicted)
            bucket[field][1].update(tagged_gold)
    return {
        "dataset": "mock/synthetic",
        "documents": len(list(gold_dir.glob("*.yaml"))),
        "overall": {
            field: _scores(values[0], values[1])
            for field, values in overall.items()
        },
        "by_document_type": {
            kind: {
                field: _scores(values[0], values[1])
                for field, values in fields.items()
            }
            for kind, fields in accumulators.items()
        },
    }


async def run_synthetic_eval(gold_dir: Path) -> dict[str, Any]:
    """Exercise the complete offline router before scoring gold extractions."""
    router = DocumentRouter(
        textract=TextractEngine(provider="mock"),
        vlm=VLMEngine(llm=MockLLM()),
    )
    predictions: dict[str, ExtractionResult] = {}
    for path in sorted(gold_dir.glob("*.yaml")):
        gold = yaml.safe_load(path.read_text())
        predictions[path.stem] = await router.route(
            generate_fixture(gold["fixture"]), filename=f"{gold['fixture']}.png"
        )
    report = evaluate(gold_dir=gold_dir, predictions=predictions)
    report["integration_mode"] = "mock/synthetic (no production accuracy claim)"
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gold-dir", type=Path, default=Path(__file__).with_name("gold")
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_synthetic_eval(args.gold_dir)), indent=2))


if __name__ == "__main__":
    main()
