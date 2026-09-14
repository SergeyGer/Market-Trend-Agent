"""Application configuration loaded from environment variables."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Centralized runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    notion_api_key: str = Field(default="", alias="NOTION_API_KEY")
    notion_database_id: str = Field(default="", alias="NOTION_DATABASE_ID")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    rss_feed_urls: str = Field(default="", alias="RSS_FEED_URLS")
    json_endpoint_urls: str = Field(default="", alias="JSON_ENDPOINT_URLS")

    notion_prop_title: str = Field(default="Title", alias="NOTION_PROP_TITLE")
    notion_prop_category: str = Field(default="Category", alias="NOTION_PROP_CATEGORY")
    notion_prop_impact: str = Field(default="Impact Score", alias="NOTION_PROP_IMPACT")
    notion_prop_metrics: str = Field(default="Metrics", alias="NOTION_PROP_METRICS")
    notion_prop_url: str = Field(default="URL", alias="NOTION_PROP_URL")

    log_level: LogLevel = Field(default="INFO", alias="LOG_LEVEL")

    http_timeout: float = 10.0
    http_max_retries: int = 3
    max_words: int = 2000
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    anthropic_temperature: float = 0.1
    telegram_min_impact_score: int = 4

    state_db_path: str = Field(default="market_trend_agent.db", alias="STATE_DB_PATH")
    analysis_concurrency: int = Field(default=4, alias="ANALYSIS_CONCURRENCY")
    http_backoff_base: float = Field(default=1.0, alias="HTTP_BACKOFF_BASE")
    correction_max_attempts: int = Field(default=1, alias="CORRECTION_MAX_ATTEMPTS")

    @field_validator("rss_feed_urls", "json_endpoint_urls", mode="before")
    @classmethod
    def _strip_value(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @property
    def rss_feeds(self) -> list[str]:
        return self._split_csv(self.rss_feed_urls)

    @property
    def json_endpoints(self) -> list[str]:
        return self._split_csv(self.json_endpoint_urls)

    @staticmethod
    def _split_csv(raw: str) -> list[str]:
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()


def configure_logging(settings: Settings | None = None) -> None:
    """Configure root logger."""
    resolved = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, resolved.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
