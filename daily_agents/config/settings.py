"""
Application Settings
~~~~~~~~~~~~~~~~~~~~
Centralized configuration management using Pydantic BaseSettings.
All values are loaded from environment variables or a .env file.

References:
  - REQ-CFG-001: All config via environment variables
  - REQ-CFG-002: Required env vars (JWT_SECRET_KEY, DB_ENCRYPTION_KEY, LLM key)
  - REQ-CFG-003: Optional config with sensible defaults
  - REQ-SEC-002: Encryption key via DB_ENCRYPTION_KEY
  - REQ-SEC-003: JWT secret via JWT_SECRET_KEY
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Security (Required) ─────────────────────────────────────────
    jwt_secret_key: str = ""
    db_encryption_key: str = ""

    # ── LLM Providers (at least one required) ───────────────────────
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # ── LLM Settings ────────────────────────────────────────────────
    default_model: str = "gpt-4o"
    default_temperature: float = 0.0
    max_iterations: int = 10

    # ── Database ────────────────────────────────────────────────────
    database_url: str = ""  # Empty → SQLite dev mode

    # ── JWT ──────────────────────────────────────────────────────────
    jwt_expire_minutes: int = 43200  # 30 days
    jwt_algorithm: str = "HS256"

    # ── CORS ─────────────────────────────────────────────────────────
    allowed_origins: str = "http://localhost:3000,http://localhost:8080"

    # ── Microsoft Teams Bot ──────────────────────────────────────────
    teams_tenant_id: Optional[str] = None
    teams_client_id: Optional[str] = None
    teams_client_secret: Optional[str] = None
    teams_bot_user_id: Optional[str] = None

    # ── Azure Speech ─────────────────────────────────────────────────
    azure_speech_key: Optional[str] = None
    azure_speech_region: Optional[str] = None

    # ── Email (SMTP) ─────────────────────────────────────────────────
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_email: Optional[str] = None
    sender_password: Optional[str] = None

    # ── Application ──────────────────────────────────────────────────
    base_url: str = "http://localhost:8000"
    debug: bool = False

    # ── LangSmith Tracing ────────────────────────────────────────────
    langchain_tracing_v2: bool = False
    langchain_api_key: Optional[str] = None
    langchain_project: str = "daily-agents"

    # ── Performance ──────────────────────────────────────────────────
    thread_pool_workers: int = 10  # REQ-PERF-001
    uvicorn_workers: int = 4       # REQ-PERF-002
    http_client_timeout: int = 30  # REQ-PERF-003

    # ── Validators ───────────────────────────────────────────────────

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def _ensure_jwt_secret(cls, v: str) -> str:
        """Generate a JWT secret if none is provided (dev convenience)."""
        if not v:
            generated = secrets.token_urlsafe(64)
            print(
                "⚠️  JWT_SECRET_KEY not set — generated a temporary key. "
                "Set JWT_SECRET_KEY in .env for production."
            )
            return generated
        return v

    @field_validator("db_encryption_key", mode="before")
    @classmethod
    def _ensure_encryption_key(cls, v: str) -> str:
        """Generate a Fernet key if none is provided (dev convenience)."""
        if not v:
            generated = Fernet.generate_key().decode()
            print(
                "⚠️  DB_ENCRYPTION_KEY not set — generated a temporary key. "
                "Set DB_ENCRYPTION_KEY in .env for production."
            )
            return generated
        return v

    # ── Computed properties ──────────────────────────────────────────

    @property
    def cors_origins(self) -> list[str]:
        """Parse comma-separated allowed origins into a list."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def effective_database_url(self) -> str:
        """Return the configured DB URL, falling back to SQLite for dev."""
        if self.database_url:
            return self.database_url
        # Default: SQLite file in project root
        db_path = os.path.join(os.getcwd(), "daily_agents_dev.db")
        return f"sqlite:///{db_path}"

    @property
    def is_sqlite(self) -> bool:
        """Check if we're using SQLite (dev mode)."""
        return self.effective_database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
