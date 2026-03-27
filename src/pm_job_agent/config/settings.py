"""Environment-backed settings (no secrets in code paths — only loaded from env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_context_path: Path = Field(
        default=Path("private/agent-context.md"),
        description="Markdown file with career context for scoring and generation.",
    )

    openai_api_key: Optional[SecretStr] = None
    anthropic_api_key: Optional[SecretStr] = None
    google_api_key: Optional[SecretStr] = None

    default_llm_provider: str = Field(
        default="stub",
        description="stub | openai | anthropic | gemini (only stub implemented in Phase 1 slice).",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
