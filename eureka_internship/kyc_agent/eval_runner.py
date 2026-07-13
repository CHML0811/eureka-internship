"""Integration-focused benchmark runner for the deterministic Project 9 corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from kyc_agent.agent import KYCGraphAgent, MockCypherGenerator
from kyc_agent.aura_setup import load_project_env
from kyc_agent.executor import InMemoryExecutor, Neo4jExecutor


def load_benchmark(path: Path) -> dict[str, Any]:
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("Non-JSON YAML requires the optional PyYAML package") from exc
        return yaml.safe_load(text)


def executor_from_env(use_neo4j: bool) -> InMemoryExecutor | Neo4jExecutor:
    if not use_neo4j:
        return InMemoryExecutor.default()
    uri = os.getenv("NEO4J_URI", "").strip()
    password = os.getenv("NEO4J_PASSWORD")
    missing = []
    if not uri:
        missing.append("NEO4J_URI")
    if not password:
        missing.append("NEO4J_PASSWORD")
    user = (
        os.getenv("NEO4J_USERNAME", "").strip()
        or os.getenv("NEO4J_USER", "").strip()
    )
    if not user:
        missing.append("NEO4J_USERNAME (or NEO4J_USER)")
    if missing:
        raise RuntimeError("Missing live Neo4j settings: " + ", ".join(missing))
    assert password is not None
    return Neo4jExecutor(
        uri,
        user,
        password,
        database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )


async def evaluate(*, use_neo4j: bool = False) -> dict[str, Any]:
    benchmark = load_benchmark(Path(__file__).with_name("benchmark.yaml"))
    executor = executor_from_env(use_neo4j)
    agent = KYCGraphAgent(generator=MockCypherGenerator(), executor=executor)
    cases: list[dict[str, Any]] = []
    try:
        for item in benchmark["questions"]:
            try:
                result = await agent.ask(item["question"])
                cases.append(
                    {
                        "id": item["id"],
                        "valid_and_executed": True,
                        "nonempty": bool(result.rows),
                        "expected_answer": item["expected_answer"],
                    }
                )
            except (ValueError, RuntimeError) as exc:
                cases.append(
                    {
                        "id": item["id"],
                        "valid_and_executed": False,
                        "nonempty": False,
                        "error": str(exc),
                        "expected_answer": item["expected_answer"],
                    }
                )
    finally:
        close = getattr(executor, "close", None)
        if close:
            close()
    total = len(cases)
    return {
        "mode": "neo4j-integration" if use_neo4j else "offline-integration",
        "integration_only": True,
        "accuracy_claim": (
            "None. These metrics test pipeline integration and deterministic fixtures; "
            "they do not measure real-model semantic accuracy."
        ),
        "metrics": {
            "valid_execution_rate": sum(
                case["valid_and_executed"] for case in cases
            )
            / total,
            "nonempty_result_rate": sum(case["nonempty"] for case in cases) / total,
        },
        "cases": cases,
    }


def main() -> None:
    load_project_env()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--neo4j",
        action="store_true",
        help="Use NEO4J_URI/USER/PASSWORD instead of the in-memory executor.",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(evaluate(use_neo4j=args.neo4j)), indent=2))


if __name__ == "__main__":
    main()
