"""Initialize the synthetic Project 9 graph on Neo4j AuraDB Free."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parent


def load_project_env(env_path: Path | None = None) -> bool:
    """Load ``.env`` from the project root when present (never committed)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    path = env_path or (PROJECT_ROOT / ".env")
    if not path.exists():
        return False
    load_dotenv(path)
    return True


@dataclass(frozen=True)
class AuraSettings:
    uri: str
    user: str
    password: str
    database: str = "neo4j"


def load_settings(
    environment: Mapping[str, str] | None = None,
) -> AuraSettings:
    """Load Aura credentials without accepting an unencrypted Bolt endpoint."""
    values = environment or os.environ
    required = ("NEO4J_URI", "NEO4J_PASSWORD")
    missing = [name for name in required if not values.get(name, "").strip()]
    user = (
        values.get("NEO4J_USERNAME", "").strip()
        or values.get("NEO4J_USER", "").strip()
    )
    if not user:
        missing.append("NEO4J_USERNAME (or NEO4J_USER)")
    if missing:
        raise ValueError("Missing AuraDB settings: " + ", ".join(missing))

    uri = values["NEO4J_URI"].strip()
    parsed = urlparse(uri)
    if parsed.scheme != "neo4j+s" or not parsed.hostname:
        raise ValueError("NEO4J_URI must be an encrypted neo4j+s:// AuraDB URI")
    if not parsed.hostname.endswith(".databases.neo4j.io"):
        raise ValueError("NEO4J_URI must point to a Neo4j AuraDB managed host")
    return AuraSettings(
        uri=uri,
        user=user,
        password=values["NEO4J_PASSWORD"],
        database=values.get("NEO4J_DATABASE", "neo4j").strip() or "neo4j",
    )


def split_cypher_statements(source: str) -> list[str]:
    """Split a Cypher script on code semicolons, preserving comments and strings."""
    statements: list[str] = []
    current: list[str] = []
    state = "code"
    quote = ""
    index = 0
    while index < len(source):
        char = source[index]
        pair = source[index : index + 2]
        if state == "line_comment":
            current.append(char)
            if char == "\n":
                state = "code"
            index += 1
            continue
        if state == "block_comment":
            current.append(char)
            if pair == "*/":
                current.append("/")
                index += 2
                state = "code"
            else:
                index += 1
            continue
        if state == "quote":
            current.append(char)
            if char == "\\" and index + 1 < len(source):
                current.append(source[index + 1])
                index += 2
            elif char == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    current.append(source[index + 1])
                    index += 2
                else:
                    state = "code"
                    index += 1
            else:
                index += 1
            continue

        if pair == "//":
            current.extend(("/", "/"))
            index += 2
            state = "line_comment"
        elif pair == "/*":
            current.extend(("/", "*"))
            index += 2
            state = "block_comment"
        elif char in {"'", '"', "`"}:
            current.append(char)
            quote = char
            state = "quote"
            index += 1
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
        else:
            current.append(char)
            index += 1

    if state in {"quote", "block_comment"}:
        raise ValueError("Cypher script contains an unterminated string or comment")
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def initialize(
    driver: Any,
    *,
    database: str = "neo4j",
    schema_path: Path = ROOT / "schema.cypher",
    seed_path: Path = ROOT / "seed.cypher",
) -> None:
    """Apply the idempotent schema first, then the synthetic seed."""
    statements = [
        *split_cypher_statements(schema_path.read_text()),
        *split_cypher_statements(seed_path.read_text()),
    ]
    with driver.session(database=database) as session:
        for statement in statements:
            session.run(statement).consume()


def verify_counts(driver: Any, *, database: str = "neo4j") -> tuple[int, int]:
    """Verify the designed fixture size so partial imports fail loudly."""
    with driver.session(database=database) as session:
        nodes = session.run(
            "MATCH (n) RETURN count(n) AS count"
        ).single(strict=True)["count"]
        relationships = session.run(
            "MATCH ()-[r]->() RETURN count(r) AS count"
        ).single(strict=True)["count"]
    if (nodes, relationships) != (80, 150):
        raise RuntimeError(
            "Expected 80 nodes and 150 relationships after AuraDB setup; "
            f"found {nodes} nodes and {relationships} relationships"
        )
    return nodes, relationships


def main() -> None:
    """Connect, initialize, and verify without printing credentials."""
    from neo4j import GraphDatabase

    load_project_env()
    settings = load_settings()
    driver = GraphDatabase.driver(
        settings.uri,
        auth=(settings.user, settings.password),
    )
    try:
        driver.verify_connectivity()
        initialize(driver, database=settings.database)
        nodes, relationships = verify_counts(
            driver,
            database=settings.database,
        )
    finally:
        driver.close()
    print(
        "AuraDB synthetic KYC graph initialized: "
        f"{nodes} nodes, {relationships} relationships."
    )
    print("Do not upload real KYC, PII, client, or regulated data to AuraDB Free.")


if __name__ == "__main__":
    main()
