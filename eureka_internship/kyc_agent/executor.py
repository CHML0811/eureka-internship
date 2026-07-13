"""Pluggable Cypher executors; the default demo requires no database."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CypherExecutor(Protocol):
    def execute(
        self, query: str, parameters: Mapping[str, Any]
    ) -> list[dict[str, Any]]: ...

    def explain(self, query: str, parameters: Mapping[str, Any]) -> None: ...

    def load_schema(self) -> str: ...


class InMemoryExecutor:
    """Deterministic fixture-backed executor for tests and offline demos."""

    def __init__(
        self,
        responses: Mapping[str, list[dict[str, Any]]] | None = None,
        *,
        schema: str | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._schema = schema or (
            "Nodes: Person, Company, Address, SanctionsEntry, CourtCase, "
            "NewsArticle, Jurisdiction. Relationships: OWNS(percent), DIRECTOR_OF, "
            "RESIDES_AT, REGISTERED_AT, INVOLVED_IN, MENTIONED_IN, MATCHED_TO, "
            "SUBJECT_TO."
        )

    @classmethod
    def default(cls) -> "InMemoryExecutor":
        return cls()

    def register(self, query: str, rows: list[dict[str, Any]]) -> None:
        self._responses[query] = [dict(row) for row in rows]

    def explain(self, query: str, parameters: Mapping[str, Any]) -> None:
        del query, parameters

    def load_schema(self) -> str:
        return self._schema

    def execute(
        self, query: str, parameters: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        if query in self._responses:
            return [dict(row) for row in self._responses[query]]
        lowered = query.lower()
        if "sanctions_hits" in lowered:
            return [
                {
                    "company": "Company X",
                    "sanctions_hits": 1,
                    "court_cases": 4,
                    "news_hits": 1,
                    "jurisdiction_risks": ["high"],
                }
            ]
        if " as ceo" in lowered:
            return [{"ceo": "Person A"}]
        if "r.percent as percent" in lowered:
            return [
                {"company": "Company X", "percent": 80},
                {"company": "Clean Nominee LLC", "percent": 80},
            ]
        if "ownership_path" in lowered:
            return [
                {
                    "ubo": "Person A",
                    "ownership_path": [
                        "Person A",
                        "Clean Nominee LLC",
                        "Clean Holdings LLC",
                        "Company X",
                    ],
                }
            ]
        if "relationships(path)" in lowered:
            return [
                {"person": "Person A", "company": "Company X"},
                {"person": "Elena Varga", "company": "Atlas Trading"},
            ]
        if "sanctionsentry" in lowered:
            return [
                {
                    "entity": "Company X",
                    "sanctions_program": "OFAC SDN",
                    "hops": 1,
                }
            ]
        if "is_pep" in lowered:
            return [
                {
                    "director": "Person A",
                    "role": "CEO",
                }
            ]
        if "newsarticle" in lowered:
            return [
                {
                    "article": "Offshore procurement network under investigation",
                    "entity": "Person A",
                }
            ]
        if "courtcase" in lowered:
            return [{"year": year, "cases": 1} for year in range(2020, 2024)]
        if "jurisdiction" in lowered:
            return [{"company": "Company X", "jurisdiction": "Khorasan"}]
        return [{"company": str(parameters.get("company", "Company X"))}]


class Neo4jExecutor:
    """Synchronous Neo4j executor with read transactions and a hard timeout."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        *,
        database: str = "neo4j",
        timeout_seconds: float = 5.0,
        driver: Any | None = None,
    ) -> None:
        query_factory: Any
        if driver is None:
            try:
                from neo4j import GraphDatabase, Query
            except ImportError as exc:  # pragma: no cover - integration only
                raise RuntimeError(
                    "Install the optional 'neo4j' package for live execution"
                ) from exc
            driver = GraphDatabase.driver(uri, auth=(user, password))
            query_factory = Query
        else:
            try:
                from neo4j import Query
            except ImportError:  # permits lightweight injected test drivers
                query_factory = lambda text, **kwargs: text
            else:
                query_factory = Query
        self.driver = driver
        self.database = database
        self.timeout_seconds = timeout_seconds
        self._query_factory = query_factory
        self._schema_cache: str | None = None

    def close(self) -> None:
        self.driver.close()

    def execute(
        self, query: str, parameters: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        with self.driver.session(
            database=self.database, default_access_mode="READ"
        ) as session:
            result = session.run(
                self._query_factory(query, timeout=self.timeout_seconds),
                dict(parameters),
            )
            return [record.data() for record in result]

    def explain(self, query: str, parameters: Mapping[str, Any]) -> None:
        normalized = query.lstrip()
        if not re.match(r"(?i)^EXPLAIN\b", normalized):
            normalized = "EXPLAIN " + normalized
        with self.driver.session(
            database=self.database, default_access_mode="READ"
        ) as session:
            session.run(
                self._query_factory(
                    normalized, timeout=self.timeout_seconds
                ),
                dict(parameters),
            ).consume()

    def load_schema(self) -> str:
        """Load and cache Neo4j's live visualization schema."""
        if self._schema_cache is not None:
            return self._schema_cache
        query = "CALL db.schema.visualization() YIELD nodes, relationships RETURN nodes, relationships"
        with self.driver.session(
            database=self.database, default_access_mode="READ"
        ) as session:
            records = session.run(
                self._query_factory(query, timeout=self.timeout_seconds),
                {},
            )
            labels: set[str] = set()
            relationship_types: set[str] = set()
            for record in records:
                data = record.data() if hasattr(record, "data") else dict(record)
                for node in data.get("nodes", ()):
                    if isinstance(node, Mapping):
                        node_labels = node.get("labels", ())
                    else:
                        node_labels = getattr(node, "labels", ())
                    labels.update(str(label) for label in node_labels)
                for relationship in data.get("relationships", ()):
                    if isinstance(relationship, Mapping):
                        rel_type = relationship.get("type")
                    else:
                        rel_type = getattr(relationship, "type", None)
                    if rel_type:
                        relationship_types.add(str(rel_type))
        self._schema_cache = (
            "Node labels: "
            + ", ".join(sorted(labels))
            + ". Relationships: "
            + ", ".join(sorted(relationship_types))
            + "."
        )
        return self._schema_cache
