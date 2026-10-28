from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "Metamorphosis API"
    database_url: str = "sqlite:///./data/metamorphosis.db"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )
    log_level: str = "INFO"
    ai_provider: Literal["mock", "ollama"] = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    provider_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    provider_timeout_seconds: float = Field(default=90, gt=0, le=600)
    chat_context_tokens: int = Field(default=4096, ge=128, le=1_000_000)
    chat_reserved_output_tokens: int = Field(default=512, ge=1, le=100_000)
    chat_system_prompt: str = (
        "You are Metamorphosis, a helpful local AI assistant for software development, "
        "technical questions, and authorized security work. Be direct, accurate, and concise. "
        "Avoid moralizing; when you cannot help with a request, briefly explain why and offer "
        "a constructive alternative."
    )

    @model_validator(mode="after")
    def output_reservation_must_fit_context(self) -> "Settings":
        if self.chat_reserved_output_tokens >= self.chat_context_tokens:
            raise ValueError("CHAT_RESERVED_OUTPUT_TOKENS must be below CHAT_CONTEXT_TOKENS.")
        if not self.ollama_model.strip():
            raise ValueError("OLLAMA_MODEL cannot be blank.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
