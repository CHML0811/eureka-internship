"""Environment-backed configuration for offline-first providers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

LLMProviderName = Literal["mock", "ollama"]
TextractProviderName = Literal["mock", "aws"]


def _provider(
    variable: str,
    default: str,
    allowed: tuple[str, ...],
) -> str:
    value = os.getenv(variable, default).strip().lower()
    if value not in allowed:
        choices = "|".join(allowed)
        raise ValueError(f"{variable} must be one of {choices}; got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    """Provider settings with safe, runnable defaults."""

    llm_provider: LLMProviderName = "mock"
    textract_provider: TextractProviderName = "mock"
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "llama3.1"
    local_vlm_model: str = "llama3.2-vision"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            llm_provider=cast(
                LLMProviderName,
                _provider("LLM_PROVIDER", "mock", ("mock", "ollama")),
            ),
            textract_provider=cast(
                TextractProviderName,
                _provider("TEXTRACT_PROVIDER", "mock", ("mock", "aws")),
            ),
            local_llm_base_url=os.getenv(
                "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"
            ),
            local_llm_model=os.getenv("LOCAL_LLM_MODEL", "llama3.1"),
            local_vlm_model=os.getenv("LOCAL_VLM_MODEL", "llama3.2-vision"),
        )
