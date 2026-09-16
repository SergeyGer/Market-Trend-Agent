"""Tests for ingestion helpers."""

from __future__ import annotations

from ingest import IngestionManager, RawArticle, sanitize_html, truncate_to_max_words


def test_sanitize_html_strips_scripts() -> None:
    html = "<p>Hello <script>alert('x')</script> world</p>"
    assert sanitize_html(html) == "Hello world"


def test_truncate_to_max_words() -> None:
    assert truncate_to_max_words("one two three four", 2) == "one two"
    assert truncate_to_max_words("short text", 10) == "short text"


def test_parse_rss_extracts_items(settings) -> None:
    xml = (
        '<?xml version="1.0"?>'
        "<rss><channel><item>"
        "<title>News title</title>"
        "<link>https://example.com/news</link>"
        "<description>Short description</description>"
        "</item></channel></rss>"
    )
    manager = IngestionManager(settings=settings)
    articles = manager._parse_rss(xml, "https://example.com/feed")
    assert len(articles) == 1
    assert articles[0].title == "News title"
    assert articles[0].url == "https://example.com/news"


def test_parse_json_payload(settings) -> None:
    payload = {
        "articles": [
            {"title": "T", "url": "https://example.com", "description": "D"},
        ]
    }
    manager = IngestionManager(settings=settings)
    articles = manager._parse_json_payload(payload, "https://example.com/api")
    assert len(articles) == 1
    assert articles[0].title == "T"


def test_deduplicate_in_memory(settings) -> None:
    manager = IngestionManager(settings=settings)
    article = RawArticle(
        title="T",
        url="https://example.com/1",
        content="c",
        source="s",
    )
    first = manager._deduplicate([article])
    second = manager._deduplicate([article])
    assert len(first) == 1
    assert len(second) == 0


def test_parse_rss_prefers_content_encoded(settings) -> None:
    xml = (
        '<?xml version="1.0"?>'
        '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        "<channel><item>"
        "<title>Full item</title>"
        "<link>https://example.com/full</link>"
        "<description>Short summary</description>"
        "<content:encoded>"
        "The full article body with substantially more detail than the summary."
        "</content:encoded>"
        "</item></channel></rss>"
    )
    manager = IngestionManager(settings=settings)
    articles = manager._parse_rss(xml, "https://example.com/feed")
    assert len(articles) == 1
    assert "full article body" in articles[0].content


def test_parse_rss_falls_back_to_description(settings) -> None:
    xml = (
        '<?xml version="1.0"?>'
        "<rss><channel><item>"
        "<title>Only summary</title>"
        "<link>https://example.com/sum</link>"
        "<description>Summary only content</description>"
        "</item></channel></rss>"
    )
    manager = IngestionManager(settings=settings)
    articles = manager._parse_rss(xml, "https://example.com/feed")
    assert articles[0].content == "Summary only content"
