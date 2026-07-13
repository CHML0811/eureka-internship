from __future__ import annotations

from pathlib import Path

import os

import pytest

from kyc_agent.aura_setup import (
    AuraSettings,
    initialize,
    load_project_env,
    load_settings,
    split_cypher_statements,
    verify_counts,
)


def test_load_project_env_reads_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NEO4J_URI=neo4j+s://example.databases.neo4j.io\n"
        "NEO4J_USERNAME=neo4j\n"
        "NEO4J_PASSWORD=secret-value\n"
    )
    for key in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.delenv(key, raising=False)

    assert load_project_env(env_file) is True
    assert os.environ["NEO4J_URI"] == "neo4j+s://example.databases.neo4j.io"
    assert os.environ["NEO4J_USERNAME"] == "neo4j"
    assert os.environ["NEO4J_PASSWORD"] == "secret-value"


def test_load_project_env_missing_file_returns_false(tmp_path: Path) -> None:
    assert load_project_env(tmp_path / "missing.env") is False


def test_aura_settings_require_encrypted_managed_uri() -> None:
    environment = {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "secret-value",
    }

    with pytest.raises(ValueError, match="neo4j\\+s"):
        load_settings(environment)


def test_aura_settings_require_all_credentials() -> None:
    with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
        load_settings(
            {
                "NEO4J_URI": "neo4j+s://example.databases.neo4j.io",
                "NEO4J_USER": "neo4j",
            }
        )


def test_aura_settings_accept_official_username_variable() -> None:
    settings = load_settings(
        {
            "NEO4J_URI": "neo4j+s://example.databases.neo4j.io",
            "NEO4J_USERNAME": "neo4j",
            "NEO4J_PASSWORD": "secret-value",
        }
    )

    assert settings.user == "neo4j"


def test_aura_settings_reject_non_aura_managed_host() -> None:
    with pytest.raises(ValueError, match="managed host"):
        load_settings(
            {
                "NEO4J_URI": "neo4j+s://custom.internal.example.com",
                "NEO4J_USER": "neo4j",
                "NEO4J_PASSWORD": "secret-value",
            }
        )


def test_split_cypher_preserves_semicolons_inside_strings() -> None:
    statements = split_cypher_statements(
        "CREATE (n {note: 'one;two'}); // comment\nMATCH (n) RETURN n;"
    )

    assert statements == [
        "CREATE (n {note: 'one;two'})",
        "// comment\nMATCH (n) RETURN n",
    ]


def test_initialize_reuses_schema_then_seed_files(tmp_path: Path) -> None:
    schema = tmp_path / "schema.cypher"
    seed = tmp_path / "seed.cypher"
    schema.write_text("CREATE CONSTRAINT demo IF NOT EXISTS FOR (n:X) REQUIRE n.id IS UNIQUE;")
    seed.write_text("MERGE (:X {id: 1}); MERGE (:X {id: 2});")
    driver = RecordingDriver()

    initialize(driver, schema_path=schema, seed_path=seed)

    assert driver.queries == [
        "CREATE CONSTRAINT demo IF NOT EXISTS FOR (n:X) REQUIRE n.id IS UNIQUE",
        "MERGE (:X {id: 1})",
        "MERGE (:X {id: 2})",
    ]


def test_verify_counts_requires_exact_demo_fixture_size() -> None:
    driver = RecordingDriver(nodes=80, relationships=150)
    assert verify_counts(driver) == (80, 150)

    with pytest.raises(RuntimeError, match="80 nodes and 150 relationships"):
        verify_counts(RecordingDriver(nodes=79, relationships=150))


class Record:
    def __init__(self, value: int) -> None:
        self.value = value

    def single(self, *, strict: bool = False) -> dict[str, int]:
        del strict
        return {"count": self.value}

    def consume(self) -> None:
        return None


class Session:
    def __init__(self, driver: "RecordingDriver") -> None:
        self.driver = driver

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def run(self, query: str) -> Record:
        if query == "MATCH (n) RETURN count(n) AS count":
            return Record(self.driver.nodes)
        if query == "MATCH ()-[r]->() RETURN count(r) AS count":
            return Record(self.driver.relationships)
        self.driver.queries.append(query)
        return Record(0)


class RecordingDriver:
    def __init__(self, *, nodes: int = 80, relationships: int = 150) -> None:
        self.nodes = nodes
        self.relationships = relationships
        self.queries: list[str] = []

    def session(self, *, database: str = "neo4j") -> Session:
        assert database
        return Session(self)
