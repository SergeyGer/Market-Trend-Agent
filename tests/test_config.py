"""Tests for settings parsing."""

from __future__ import annotations

from config import Settings


def test_csv_values_are_split() -> None:
    settings = Settings(
        _env_file=None,
        RSS_FEED_URLS="https://a.example/feed, https://b.example/feed",
        JSON_ENDPOINT_URLS="https://c.example/api",
    )
    assert settings.rss_feeds == [
        "https://a.example/feed",
        "https://b.example/feed",
    ]
    assert settings.json_endpoints == ["https://c.example/api"]
