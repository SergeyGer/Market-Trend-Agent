"""Shared pytest fixtures for the Market Trend Agent test suite."""

from __future__ import annotations

import pytest

from config import Settings


@pytest.fixture
def settings() -> Settings:
    """Return isolated settings that do not read .env or touch a real database."""
    return Settings(
        _env_file=None,
        ANTHROPIC_API_KEY="test-key",
        NOTION_API_KEY="",
        NOTION_DATABASE_ID="",
        TELEGRAM_BOT_TOKEN="",
        TELEGRAM_CHAT_ID="",
        STATE_DB_PATH="",
        TELEGRAM_MIN_IMPACT_SCORE=4,
        ANALYSIS_CONCURRENCY=2,
    )
