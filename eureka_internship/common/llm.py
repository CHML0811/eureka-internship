"""Provider-neutral LLM contract with mock and private Ollama implementations."""

from __future__ import annotations

import ipaddress
import json
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, runtime_checkable
from urllib.parse import urlparse

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from common.config import Settings


class ChatMessage(BaseModel):
    """A provider-neutral chat message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]]


class ToolDefinition(BaseModel):
    """JSON-schema description of a callable downstream tool."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_model(
        cls,
        *,
        name: str,
        arguments_model: type[BaseModel],
        description: str = "",
    ) -> "ToolDefinition":
        return cls(
            name=name,
            description=description,
            parameters=arguments_model.model_json_schema(),
        )


class ToolCall(BaseModel):
    """A structured tool invocation requested by an LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Normalized response returned by every LLM provider."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str


@runtime_checkable
class LLM(Protocol):
    """Contract consumed by document, chart, and graph workflows."""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse: ...


def _example_from_schema(
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any] | None = None,
) -> Any:
    """Build a stable, schema-valid-enough value for deterministic tool tests."""
    root = root_schema or schema
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    if "$ref" in schema:
        target: Any = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return _example_from_schema(target, root)

    for union_key in ("anyOf", "oneOf"):
        choices = schema.get(union_key)
        if choices:
            non_null = [
                choice for choice in choices if choice.get("type") != "null"
            ]
            return _example_from_schema(
                non_null[0] if non_null else choices[0],
                root,
            )

    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = schema.get("required", properties.keys())
        return {
            name: _example_from_schema(properties[name], root)
            for name in required
            if name in properties
        }
    if schema_type == "array":
        return []
    if schema_type == "integer":
        return schema.get("minimum", 0)
    if schema_type == "number":
        return schema.get("minimum", 0.0)
    if schema_type == "boolean":
        return False
    if schema_type == "null":
        return None
    return "mock-string"


class MockLLM:
    """Deterministic provider for offline development and downstream tests."""

    model = "mock"

    def __init__(self, responses: Sequence[LLMResponse] | None = None) -> None:
        self._responses = deque(responses or ())

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        del messages, temperature
        if self._responses:
            return self._responses.popleft()
        if tools:
            tool = tools[0]
            return LLMResponse(
                model=self.model,
                tool_calls=[
                    ToolCall(
                        id="mock-call-1",
                        name=tool.name,
                        arguments=_example_from_schema(tool.parameters),
                    )
                ],
            )
        return LLMResponse(content="mock-response", model=self.model)


def _is_private_ollama_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return False

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".local", ".internal")):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    if address.is_link_local:
        return False
    return address.is_private or address.is_loopback


class OllamaLLM:
    """OpenAI-compatible client restricted to private Ollama endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        client: Any | None = None,
    ) -> None:
        if not _is_private_ollama_url(base_url):
            raise ValueError(
                "Ollama base URL must use localhost or a private network host"
            )
        self.base_url = base_url
        self.model = model
        self._client = client or AsyncOpenAI(
            base_url=base_url,
            api_key="ollama-local",
        )

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolDefinition] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": temperature,
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]

        response = await self._client.chat.completions.create(**request)
        message = response.choices[0].message
        tool_calls = [
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=json.loads(call.function.arguments or "{}"),
            )
            for call in (message.tool_calls or ())
        ]
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            model=response.model or self.model,
        )


def create_llm(
    settings: Settings | None = None,
    *,
    client: Any | None = None,
) -> LLM:
    """Build the configured LLM without exposing a public-provider path."""
    resolved = settings or Settings.from_env()
    if resolved.llm_provider == "mock":
        return MockLLM()
    if resolved.llm_provider == "ollama":
        return OllamaLLM(
            base_url=resolved.local_llm_base_url,
            model=resolved.local_llm_model,
            client=client,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {resolved.llm_provider!r}")
