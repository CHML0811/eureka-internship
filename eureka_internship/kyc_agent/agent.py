"""Schema-aware natural-language to Cypher KYC workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from common.llm import ChatMessage, LLM, ToolDefinition
from kyc_agent.executor import CypherExecutor, InMemoryExecutor
from kyc_agent.interpreter import ResultInterpreter
from kyc_agent.models import AgentResult, CypherRequest
from kyc_agent.validator import CypherValidationError, CypherValidator


class CypherGenerator(Protocol):
    async def generate(
        self, question: str, feedback: str | None = None
    ) -> CypherRequest: ...


class RunCypherArguments(BaseModel):
    """Strict arguments for the model's only graph-query tool."""

    model_config = ConfigDict(extra="forbid")
    query: str
    explanation: str


SCHEMA_SUMMARY = """
Node labels:
Person(name, role, is_pep, risk_score)
Company(name, entity_type, status)
Address(address_id, street, city)
SanctionsEntry(entry_id, program, status)
CourtCase(case_id, filed_year, status)
NewsArticle(article_id, headline, published, severity)
Jurisdiction(name, risk_level)

Core relationships:
OWNS(percent), DIRECTOR_OF, RESIDES_AT, REGISTERED_AT, INVOLVED_IN,
MENTIONED_IN, MATCHED_TO, SUBJECT_TO.
""".strip()

FEW_SHOTS = (
    (
        "Who is the CEO of Company X?",
        "MATCH (p:Person)-[:DIRECTOR_OF]->(c:Company {name: 'Company X'}) "
        "WHERE p.role = 'CEO' RETURN p.name AS ceo LIMIT 20",
    ),
    (
        "What companies does Person A directly own?",
        "MATCH (p:Person {name: 'Person A'})-[r:OWNS]->(c:Company) "
        "RETURN c.name AS company, r.percent AS percent LIMIT 50",
    ),
    (
        "Who is the ultimate beneficial owner of Company X?",
        "MATCH path=(p:Person)-[:OWNS*1..5]->(c:Company {name: 'Company X'}) "
        "RETURN p.name AS ubo, [n IN nodes(path) | n.name] AS ownership_path "
        "LIMIT 20",
    ),
)


def _few_shot_text() -> str:
    return "\n\n".join(
        f"Few-shot question: {question}\nFew-shot Cypher: {cypher}"
        for question, cypher in FEW_SHOTS
    )


class LLMCypherGenerator:
    """Use ``common.llm`` tool calling with a cached live graph schema."""

    def __init__(
        self,
        llm: LLM,
        *,
        schema_loader: Callable[[], str] | None = None,
    ) -> None:
        self.llm = llm
        self.schema_loader = schema_loader or (lambda: SCHEMA_SUMMARY)
        self._schema: str | None = self.schema_loader()
        self._tool = ToolDefinition.from_model(
            name="run_cypher",
            description="Submit one read-only Cypher query and explain its intent.",
            arguments_model=RunCypherArguments,
        )

    def _load_schema(self) -> str:
        if self._schema is None:
            self._schema = self.schema_loader()
        return self._schema

    async def generate(
        self, question: str, feedback: str | None = None
    ) -> CypherRequest:
        prompt = (
            "Generate exactly one read-only Cypher query using the run_cypher tool. "
            "Never use CREATE, MERGE, DELETE, SET, REMOVE, DROP, UNION, or admin "
            "commands. Always include LIMIT <= 200. Bound variable paths at 5 hops. "
            "Use only this live schema:\n"
            f"{self._load_schema()}\n\n{_few_shot_text()}"
        )
        messages = [
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content=question),
        ]
        if feedback:
            messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        "The validator rejected the previous query for this exact "
                        f"reason: {feedback}. Simplify and try once more."
                    ),
                )
            )
        response = await self.llm.complete(
            messages,
            tools=[self._tool],
            temperature=0.0,
        )
        calls = [call for call in response.tool_calls if call.name == "run_cypher"]
        if len(calls) != 1:
            raise ValueError("LLM must make exactly one run_cypher tool call")
        arguments = RunCypherArguments.model_validate(calls[0].arguments)
        return CypherRequest(
            question=question,
            query=arguments.query,
            explanation=arguments.explanation,
        )


class MockCypherGenerator:
    """Deterministic semantic implementation of the ten literal benchmark intents."""

    async def generate(
        self, question: str, feedback: str | None = None
    ) -> CypherRequest:
        del feedback
        text = question.lower()
        params: dict[str, Any]
        if "who is the ceo" in text:
            query = (
                "MATCH (p:Person)-[:DIRECTOR_OF]->(c:Company {name:$company}) "
                "WHERE p.role=$role RETURN p.name AS ceo LIMIT 20"
            )
            params = {"company": "Company X", "role": "CEO"}
        elif "directly own" in text:
            query = (
                "MATCH (p:Person {name:$person})-[r:OWNS]->(c:Company) "
                "RETURN c.name AS company, r.percent AS percent LIMIT 50"
            )
            params = {"person": "Person A"}
        elif "ultimate beneficial owner" in text:
            query = (
                "MATCH path=(p:Person)-[:OWNS*1..5]->"
                "(c:Company {name:$company}) "
                "RETURN p.name AS ubo, [n IN nodes(path)|n.name] AS ownership_path "
                "LIMIT 20"
            )
            params = {"company": "Company X"}
        elif "court cases" in text and "per year" in text:
            query = (
                "MATCH (c:Company {name:$company})-[:INVOLVED_IN]->(cc:CourtCase) "
                "RETURN cc.filed_year AS year, count(cc) AS cases "
                "ORDER BY year LIMIT 50"
            )
            params = {"company": "Company X"}
        elif "more than 25%" in text:
            query = (
                "MATCH path=(p:Person)-[:OWNS*1..5]->(c:Company) "
                "WHERE any(r IN relationships(path) WHERE r.percent>$percent) "
                "RETURN DISTINCT p.name AS person, c.name AS company LIMIT 100"
            )
            params = {"percent": 25}
        elif "sanctioned entity" in text:
            query = (
                "MATCH path=(c:Company {name:$company})-[*1..3]-"
                "(s:SanctionsEntry) RETURN s.entry_id AS entity, "
                "s.program AS sanctions_program, length(path) AS hops LIMIT 50"
            )
            params = {"company": "Company X"}
        elif "also peps" in text:
            query = (
                "MATCH (p:Person)-[:DIRECTOR_OF]->"
                "(c:Company {name:$company}) WHERE p.is_pep=$is_pep "
                "RETURN p.name AS director, p.role AS role LIMIT 50"
            )
            params = {"company": "Company X", "is_pep": True}
        elif "same news article" in text:
            query = (
                "MATCH (c:Company {name:$company})-[:MENTIONED_IN]->"
                "(a:NewsArticle)<-[:MENTIONED_IN]-(entity) "
                "RETURN a.headline AS article, entity.name AS entity LIMIT 100"
            )
            params = {"company": "Company X"}
        elif "high-risk jurisdictions" in text:
            query = (
                "MATCH (p:Person {name:$person})-[:OWNS*1..5]->(c:Company)"
                "-[:REGISTERED_AT]->(a:Address)-[:SUBJECT_TO]->(j:Jurisdiction) "
                "WHERE j.risk_level=$risk RETURN DISTINCT c.name AS company, "
                "j.name AS jurisdiction LIMIT 100"
            )
            params = {"person": "Person A", "risk": "high"}
        elif "risk profile" in text:
            query = (
                "MATCH (c:Company {name:$company}) "
                "OPTIONAL MATCH (c)-[:MATCHED_TO]->(s:SanctionsEntry) "
                "OPTIONAL MATCH (c)-[:INVOLVED_IN]->(cc:CourtCase) "
                "OPTIONAL MATCH (c)-[:MENTIONED_IN]->(a:NewsArticle) "
                "OPTIONAL MATCH (c)-[:REGISTERED_AT]->(:Address)"
                "-[:SUBJECT_TO]->(j:Jurisdiction) "
                "RETURN c.name AS company, count(DISTINCT s) AS sanctions_hits, "
                "count(DISTINCT cc) AS court_cases, count(DISTINCT a) AS news_hits, "
                "collect(DISTINCT j.risk_level) AS jurisdiction_risks LIMIT 20"
            )
            params = {"company": "Company X"}
        else:
            query = "MATCH (c:Company {name:$company}) RETURN c.name AS company LIMIT 20"
            params = {"company": "Company X"}
        return CypherRequest(question, query, params, "Deterministic offline intent")


class KYCGraphAgent:
    def __init__(
        self,
        *,
        generator: CypherGenerator | None = None,
        llm: LLM | None = None,
        executor: CypherExecutor | None = None,
        validator: CypherValidator | None = None,
        interpreter: ResultInterpreter | None = None,
    ) -> None:
        if generator is not None and llm is not None:
            raise ValueError("Supply either generator or llm, not both")
        if generator is None:
            if llm is None:
                raise ValueError("An LLM or Cypher generator is required")
            resolved_executor = executor or InMemoryExecutor.default()
            generator = LLMCypherGenerator(
                llm, schema_loader=resolved_executor.load_schema
            )
            executor = resolved_executor
        self.generator = generator
        self.executor = executor or InMemoryExecutor.default()
        self.validator = validator or CypherValidator(
            explain_hook=self.executor.explain
        )
        self.interpreter = interpreter or ResultInterpreter()

    async def ask(self, question: str) -> AgentResult:
        feedback: str | None = None
        generated: CypherRequest
        for attempt in range(2):
            generated = await self.generator.generate(question, feedback)
            try:
                validated = self.validator.validate(
                    generated.query, generated.parameters
                )
                break
            except CypherValidationError as exc:
                if attempt == 1:
                    raise
                feedback = str(exc)
        request = CypherRequest(
            question,
            validated.query,
            validated.parameters,
            generated.explanation,
        )
        rows = self.executor.execute(request.query, request.parameters)
        interpreted = self.interpreter.interpret(question, rows)
        return AgentResult(
            request=request,
            rows=rows,
            summary=interpreted.summary,
            chart_handoff=interpreted.chart_handoff,
        )
