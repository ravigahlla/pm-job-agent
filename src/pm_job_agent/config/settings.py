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

    search_profile_path: Path = Field(
        default=Path("private/search_profile.yaml"),
        description="YAML file with search titles, keywords, and target company tokens.",
    )

    output_dir: Path = Field(
        default=Path("outputs"),
        description="Directory where timestamped CSV run files are written.",
    )

    openai_api_key: Optional[SecretStr] = None
    anthropic_api_key: Optional[SecretStr] = None
    google_api_key: Optional[SecretStr] = None

    default_llm_provider: str = Field(
        default="stub",
        description="stub | anthropic | openai | gemini | ollama",
    )

    min_score_for_generation: float = Field(
        default=0.3,
        description=(
            "Jobs scoring at or above this threshold trigger resume note + cover letter generation. "
            "Range 0.0–1.0. Lower = more documents generated per run; higher = only strong matches."
        ),
    )

    # Model names — override via env vars (e.g. ANTHROPIC_MODEL=claude-opus-4-5) without code changes.
    anthropic_model: str = "claude-3-5-haiku-20241022"
    openai_model: str = "gpt-4o-mini"
    gemini_model: str = "gemini-1.5-flash"
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"


@lru_cache
def get_settings() -> Settings:
    return Settings()
