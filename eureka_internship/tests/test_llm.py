from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from common.config import Settings
from common.llm import (
    ChatMessage,
    LLMResponse,
    MockLLM,
    OllamaLLM,
    ToolCall,
    ToolDefinition,
    create_llm,
)


class ExtractionArguments(BaseModel):
    document_id: str
    entities: list[str]


class CypherParameters(BaseModel):
    tenant_id: str


class CypherArguments(BaseModel):
    query: str
    parameters: CypherParameters


def test_env_example_uses_offline_first_provider_defaults() -> None:
    env_example = Path(__file__).parents[1] / ".env.example"
    values = dict(
        line.split("=", 1)
        for line in env_example.read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )

    assert values["LLM_PROVIDER"] == "mock"
    assert values["TEXTRACT_PROVIDER"] == "mock"
    assert values["LOCAL_LLM_BASE_URL"] == "http://localhost:11434/v1"
    assert values["LOCAL_LLM_MODEL"]
    assert values["LOCAL_VLM_MODEL"]
    assert "OPENAI_API_KEY" not in values
    assert "ANTHROPIC_API_KEY" not in values


def test_settings_preserve_existing_local_model_environment_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("TEXTRACT_PROVIDER", "aws")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://10.0.0.8:11434/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "local-text")
    monkeypatch.setenv("LOCAL_VLM_MODEL", "local-vision")

    settings = Settings.from_env()

    assert settings.llm_provider == "ollama"
    assert settings.textract_provider == "aws"
    assert settings.local_llm_base_url == "http://10.0.0.8:11434/v1"
    assert settings.local_llm_model == "local-text"
    assert settings.local_vlm_model == "local-vision"


def test_mock_llm_returns_deterministic_structured_tool_calls() -> None:
    tool = ToolDefinition.from_model(
        name="extract_document",
        description="Extract document entities",
        arguments_model=ExtractionArguments,
    )
    messages = [ChatMessage(role="user", content="Extract this private document")]

    first = asyncio.run(MockLLM().complete(messages, tools=[tool]))
    second = asyncio.run(MockLLM().complete(messages, tools=[tool]))

    assert first == second
    assert first.tool_calls == [
        ToolCall(
            id="mock-call-1",
            name="extract_document",
            arguments={"document_id": "mock-string", "entities": []},
        )
    ]
    ExtractionArguments.model_validate(first.tool_calls[0].arguments)


def test_mock_llm_can_supply_deterministic_downstream_responses() -> None:
    expected = LLMResponse(content="MATCH (n) RETURN n", model="mock")
    llm = MockLLM(responses=[expected])

    actual = asyncio.run(
        llm.complete([ChatMessage(role="user", content="Generate Cypher")])
    )

    assert actual == expected


def test_mock_llm_resolves_nested_tool_argument_schemas() -> None:
    tool = ToolDefinition.from_model(
        name="run_cypher",
        arguments_model=CypherArguments,
    )

    response = asyncio.run(MockLLM().complete([], tools=[tool]))

    validated = CypherArguments.model_validate(response.tool_calls[0].arguments)
    assert validated.parameters.tenant_id == "mock-string"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://8.8.8.8/v1",
        "http://example.com/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://100.64.0.1/v1",
        "http://[fe80::1]/v1",
    ],
)
def test_ollama_rejects_public_hosts(url: str) -> None:
    with pytest.raises(ValueError, match="private"):
        OllamaLLM(base_url=url, model="llama3.1")


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://[::1]:11434/v1",
        "http://10.1.2.3:11434/v1",
        "http://192.168.1.2:11434/v1",
        "http://ollama.internal:11434/v1",
    ],
)
def test_ollama_accepts_local_and_private_hosts(url: str) -> None:
    llm = OllamaLLM(base_url=url, model="llama3.1", client=object())

    assert llm.base_url == url


def test_factory_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    assert isinstance(create_llm(), MockLLM)


def test_factory_builds_ollama_from_preserved_environment_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "qwen-local")

    llm = create_llm(client=object())

    assert isinstance(llm, OllamaLLM)
    assert llm.base_url == "http://localhost:11434/v1"
    assert llm.model == "qwen-local"


def test_factory_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "public-cloud")

    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        create_llm()
