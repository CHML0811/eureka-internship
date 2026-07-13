from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from common.llm import LLMResponse, ToolCall
from chart_router.tools import RENDER_CHART, RENDER_GRAPH
from kyc_agent.agent import (
    KYCGraphAgent,
    LLMCypherGenerator,
    MockCypherGenerator,
    RunCypherArguments,
)
from kyc_agent.demo import main as demo_main
from kyc_agent.executor import InMemoryExecutor, Neo4jExecutor
from kyc_agent.eval_runner import executor_from_env
from kyc_agent.interpreter import ResultInterpreter
from kyc_agent.validator import CypherValidationError, CypherValidator

ROOT = Path(__file__).parents[1]
LABELS = {
    "Person",
    "Company",
    "Address",
    "SanctionsEntry",
    "CourtCase",
    "NewsArticle",
    "Jurisdiction",
}
RELATIONSHIPS = {
    "OWNS",
    "DIRECTOR_OF",
    "RESIDES_AT",
    "REGISTERED_AT",
    "INVOLVED_IN",
    "MENTIONED_IN",
    "MATCHED_TO",
    "SUBJECT_TO",
}
QUESTIONS = [
    "Who is the CEO of Company X?",
    "What companies does Person A directly own?",
    "Who is the ultimate beneficial owner of Company X?",
    "How many court cases has Company X been involved in per year?",
    "Which people own more than 25% of any company directly or indirectly?",
    "Does Company X have any connection within 3 hops to a sanctioned entity?",
    "Which directors of Company X are also PEPs?",
    "Show me all entities mentioned in the same news article as Company X.",
    "List all companies registered in high-risk jurisdictions that are owned by Person A.",
    "Summarize the risk profile of Company X.",
]


def test_schema_and_seed_use_literal_brief_vocabulary() -> None:
    schema = (ROOT / "schema.cypher").read_text()
    seed = (ROOT / "seed.cypher").read_text()
    for label in LABELS:
        assert f":{label}" in schema
        assert f":{label}" in seed
    for relationship in RELATIONSHIPS:
        assert relationship in seed
    assert "percent" in seed
    for obsolete in (":PEP", ":Country", ":Sanction)", ":AdverseMedia", ":RiskClass"):
        assert obsolete not in schema + seed


def test_benchmark_uses_exact_ten_questions_and_parameterized_gold() -> None:
    benchmark = json.loads((ROOT / "benchmark.yaml").read_text())
    assert [item["question"] for item in benchmark["questions"]] == QUESTIONS
    assert all("$" in item["gold_cypher"] for item in benchmark["questions"])
    assert all(item["expected_answer"] for item in benchmark["questions"])
    assert "(owner)" not in benchmark["questions"][2]["gold_cypher"]


def test_validator_rejects_union_and_allows_schema_introspection() -> None:
    validator = CypherValidator()
    with pytest.raises(CypherValidationError, match="UNION"):
        validator.validate("MATCH (n) RETURN n UNION MATCH (m) RETURN m")
    schema_query = validator.validate(
        "CALL db.schema.visualization() YIELD nodes, relationships "
        "RETURN nodes, relationships"
    )
    assert schema_query.query.endswith("LIMIT 200")


def test_validator_still_enforces_read_only_limits_and_paths() -> None:
    validator = CypherValidator()
    safe = "MATCH (n) WHERE n.note='CREATE UNION' // DELETE\nRETURN n"
    assert validator.validate(safe).query.endswith("LIMIT 200")
    for query in (
        "MATCH (n) DELETE n",
        "MATCH p=(a)-[*]->(b) RETURN p",
        "MATCH p=(a)-[*1..6]->(b) RETURN p",
        "CALL apoc.load.json('https://example.com') YIELD value RETURN value",
    ):
        with pytest.raises(CypherValidationError):
            validator.validate(query)


def test_explain_refusal_becomes_retryable_validation_error() -> None:
    def reject_cost(query: str, parameters: dict[str, object]) -> None:
        raise RuntimeError("estimated cost exceeds threshold")

    validator = CypherValidator(explain_hook=reject_cost)
    with pytest.raises(CypherValidationError, match="estimated cost"):
        validator.validate("MATCH (n) RETURN n LIMIT 10")


def test_llm_generator_uses_typed_tool_three_fewshots_and_cached_schema() -> None:
    calls: list[dict[str, Any]] = []
    schema_loads = 0

    class RecordingLLM:
        async def complete(self, messages: Any, **kwargs: Any) -> LLMResponse:
            calls.append({"messages": messages, **kwargs})
            return LLMResponse(
                model="mock",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="run_cypher",
                        arguments={
                            "query": "MATCH (c:Company) RETURN c.name LIMIT 20",
                            "explanation": "Read company names.",
                        },
                    )
                ],
            )

    def load_schema() -> str:
        nonlocal schema_loads
        schema_loads += 1
        return "(:Person)-[:OWNS]->(:Company)"

    generator = LLMCypherGenerator(RecordingLLM(), schema_loader=load_schema)
    first = asyncio.run(generator.generate(QUESTIONS[0]))
    asyncio.run(generator.generate(QUESTIONS[1]))

    assert first.explanation == "Read company names."
    assert schema_loads == 1
    assert calls[0]["tools"][0].name == "run_cypher"
    assert calls[0]["tools"][0].parameters == RunCypherArguments.model_json_schema()
    prompt = calls[0]["messages"][0].content
    assert prompt.count("Few-shot question:") == 3
    assert "(:Person)-[:OWNS]->(:Company)" in prompt


def test_agent_feeds_validation_error_back_and_retries_exactly_once() -> None:
    feedback_seen: list[str | None] = []

    class RetryingGenerator:
        async def generate(
            self, question: str, feedback: str | None = None
        ) -> Any:
            feedback_seen.append(feedback)
            query = (
                "MATCH (n) DELETE n"
                if feedback is None
                else "MATCH (n) RETURN n LIMIT 10"
            )
            from kyc_agent.models import CypherRequest

            return CypherRequest(question, query, {}, "Retry test")

    agent = KYCGraphAgent(
        generator=RetryingGenerator(), executor=InMemoryExecutor.default()
    )
    result = asyncio.run(agent.ask("test retry"))
    assert result.rows
    assert len(feedback_seen) == 2
    assert "DELETE" in (feedback_seen[1] or "")


def test_agent_stops_after_one_retry() -> None:
    calls = 0

    class AlwaysUnsafe:
        async def generate(
            self, question: str, feedback: str | None = None
        ) -> Any:
            nonlocal calls
            calls += 1
            from kyc_agent.models import CypherRequest

            return CypherRequest(question, "MATCH (n) DELETE n")

    agent = KYCGraphAgent(generator=AlwaysUnsafe(), executor=InMemoryExecutor())
    with pytest.raises(CypherValidationError):
        asyncio.run(agent.ask("unsafe"))
    assert calls == 2


def test_live_schema_loading_and_explain_prefix_are_cached_and_normalized() -> None:
    queries: list[str] = []

    class Record(dict):
        def data(self) -> dict[str, Any]:
            return dict(self)

    class Result(list):
        def consume(self) -> None:
            return None

    class Session:
        def __enter__(self) -> "Session":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def run(self, query: object, parameters: dict[str, object]) -> Result:
            queries.append(str(query))
            if "db.schema.visualization" in str(query):
                return Result(
                    [
                        Record(
                            nodes=[{"labels": ["Person"]}, {"labels": ["Company"]}],
                            relationships=[{"type": "OWNS"}],
                        )
                    ]
                )
            return Result()

    class Driver:
        def session(self, **kwargs: object) -> Session:
            assert kwargs["default_access_mode"] == "READ"
            return Session()

        def close(self) -> None:
            return None

    executor = Neo4jExecutor("bolt://unused", "user", "pass", driver=Driver())
    first = executor.load_schema()
    second = executor.load_schema()
    executor.explain("MATCH (n) RETURN n LIMIT 10", {})
    executor.explain("explain\nMATCH (n) RETURN n LIMIT 10", {})

    assert first == second
    assert "Person" in first and "OWNS" in first
    assert sum("db.schema.visualization" in query for query in queries) == 1
    assert queries[-2].startswith("EXPLAIN MATCH")
    assert queries[-1].lower().startswith("explain\nmatch")


def test_semantic_mock_covers_literal_brief_questions() -> None:
    generated = [
        asyncio.run(MockCypherGenerator().generate(question)).query
        for question in QUESTIONS
    ]
    assert len(set(generated)) == 10
    assert ":SanctionsEntry" in generated[5]
    assert "is_pep" in generated[6]
    assert ":NewsArticle" in generated[7]
    assert ":Jurisdiction" in generated[8]


def test_result_interpreter_hands_off_project_8_renderer_contracts() -> None:
    interpreter = ResultInterpreter()
    time_series = interpreter.interpret(
        QUESTIONS[3],
        [{"year": 2024, "cases": 2}, {"year": 2025, "cases": 3}],
    )
    ownership = interpreter.interpret(
        QUESTIONS[2],
        [
            {
                "ubo": "Person A",
                "ownership_path": ["Person A", "Holding Ltd", "Company X"],
            }
        ],
    )

    assert time_series.chart_handoff["tool_name"] == RENDER_CHART
    assert "vega_lite_spec" in time_series.chart_handoff["arguments"]
    assert ownership.chart_handoff["tool_name"] == RENDER_GRAPH
    assert ownership.chart_handoff["arguments"]["nodes"]
    assert ownership.chart_handoff["arguments"]["edges"]


def test_demo_hides_parameters_and_rows_unless_verbose(capsys: Any) -> None:
    asyncio.run(demo_main(verbose=False))
    normal = capsys.readouterr().out
    assert "Cypher:" in normal
    assert "Parameters:" not in normal
    assert "Rows:" not in normal

    asyncio.run(demo_main(verbose=True))
    verbose = capsys.readouterr().out
    assert "Parameters:" in verbose
    assert "Rows:" in verbose


def test_live_evaluator_accepts_official_aura_username_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_executor(uri: str, user: str, password: str, **kwargs: Any) -> object:
        captured.update(
            uri=uri,
            user=user,
            password=password,
            database=kwargs["database"],
        )
        return object()

    monkeypatch.setenv(
        "NEO4J_URI", " neo4j+s://example.databases.neo4j.io "
    )
    monkeypatch.setenv("NEO4J_USERNAME", " neo4j ")
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.setenv("NEO4J_PASSWORD", "secret-value")
    monkeypatch.setattr(
        "kyc_agent.eval_runner.Neo4jExecutor",
        fake_executor,
    )

    executor_from_env(True)

    assert captured["user"] == "neo4j"
    assert captured["uri"] == "neo4j+s://example.databases.neo4j.io"
