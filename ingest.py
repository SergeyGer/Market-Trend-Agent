"""Ingestion manager: fetch RSS/JSON sources, sanitize HTML, deduplicate articles."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from config import Settings, get_settings
from storage import StateStore

logger = logging.getLogger(__name__)

STRIP_TAGS: frozenset[str] = frozenset({"script", "style", "iframe", "img"})
WHITESPACE_RE: re.Pattern[str] = re.compile(r"\s+")

RSS_ITEM_TAGS: frozenset[str] = frozenset({"item", "entry"})
RSS_TITLE_TAGS: frozenset[str] = frozenset({"title"})
RSS_LINK_TAGS: frozenset[str] = frozenset({"link"})
RSS_CONTENT_TAGS: frozenset[str] = frozenset(
    {"description", "content", "summary", "content:encoded"}
)

JSON_TITLE_KEYS: frozenset[str] = frozenset(
    {"title", "headline", "name"}
)
JSON_URL_KEYS: frozenset[str] = frozenset(
    {"url", "link", "permalink", "href", "web_url"}
)
JSON_CONTENT_KEYS: frozenset[str] = frozenset(
    {
        "content",
        "description",
        "summary",
        "body",
        "text",
        "content_html",
        "content_text",
        "excerpt",
    }
)
JSON_ITEMS_KEYS: frozenset[str] = frozenset(
    {"items", "articles", "posts", "entries", "results", "data", "news"}
)


class IngestionError(Exception):
    """Raised when ingestion of a single source fails irrecoverably."""


@dataclass(frozen=True, slots=True)
class RawArticle:
    """Normalized article payload ready for AI analysis."""

    title: str
    url: str
    content: str
    source: str


@dataclass
class IngestionManager:
    """Aggregate and preprocess articles from RSS feeds and JSON endpoints."""

    settings: Settings = field(default_factory=get_settings)
    _seen_hashes: set[str] = field(default_factory=set, init=False, repr=False)
    _state_store: StateStore | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Open the persistent state store when a DB path is configured."""
        if self.settings.state_db_path:
            self._state_store = StateStore(self.settings.state_db_path)

    def close(self) -> None:
        """Close the underlying state store if one was created."""
        if self._state_store is not None:
            self._state_store.close()

    def ingest_all(self) -> list[RawArticle]:
        """Fetch all configured sources, sanitize content, and deduplicate."""
        articles: list[RawArticle] = []

        with httpx.Client(
            timeout=self.settings.http_timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; MarketTrendAgent/1.0; "
                    "+https://example.com/bot)"
                )
            },
        ) as client:
            for feed_url in self.settings.rss_feeds:
                try:
                    fetched = self._ingest_rss_feed(client, feed_url)
                    articles.extend(self._deduplicate(fetched))
                except IngestionError as exc:
                    logger.error("RSS ingestion failed for %s: %s", feed_url, exc)

            for endpoint_url in self.settings.json_endpoints:
                try:
                    fetched = self._ingest_json_endpoint(client, endpoint_url)
                    articles.extend(self._deduplicate(fetched))
                except IngestionError as exc:
                    logger.error(
                        "JSON ingestion failed for %s: %s", endpoint_url, exc
                    )

        logger.info("Ingestion complete: %d unique articles", len(articles))
        return articles

    def _ingest_rss_feed(
        self, client: httpx.Client, feed_url: str
    ) -> list[RawArticle]:
        response_text = self._fetch_with_retry(client, feed_url)
        return self._parse_rss(response_text, feed_url)

    def _ingest_json_endpoint(
        self, client: httpx.Client, endpoint_url: str
    ) -> list[RawArticle]:
        response_text = self._fetch_with_retry(client, endpoint_url)
        try:
            payload: Any = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise IngestionError(f"Invalid JSON from {endpoint_url}") from exc
        return self._parse_json_payload(payload, endpoint_url)

    def _fetch_with_retry(self, client: httpx.Client, url: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self.settings.http_max_retries + 1):
            try:
                response = client.get(url)
                response.raise_for_status()
                return response.text
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning(
                    "Fetch attempt %d/%d failed for %s: %s",
                    attempt,
                    self.settings.http_max_retries,
                    url,
                    exc,
                )

        raise IngestionError(
            f"Failed to fetch {url} after {self.settings.http_max_retries} attempts"
        ) from last_error

    def _parse_rss(self, xml_content: str, source_url: str) -> list[RawArticle]:
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            raise IngestionError(f"Malformed RSS/Atom XML from {source_url}") from exc

        articles: list[RawArticle] = []
        for element in root.iter():
            local_tag = self._local_name(element.tag)
            if local_tag not in RSS_ITEM_TAGS:
                continue

            title = self._extract_rss_field(element, RSS_TITLE_TAGS)
            url = self._extract_rss_link(element)
            raw_body = self._extract_rss_field(element, RSS_CONTENT_TAGS)

            if not title and not url:
                continue

            articles.append(
                self._build_article(
                    title=title or "Untitled",
                    url=url or source_url,
                    raw_content=raw_body,
                    source=source_url,
                )
            )

        if not articles:
            logger.warning("No articles parsed from RSS feed: %s", source_url)

        return articles

    def _parse_json_payload(
        self, payload: Any, source_url: str
    ) -> list[RawArticle]:
        items = self._extract_json_items(payload)
        articles: list[RawArticle] = []

        for item in items:
            if not isinstance(item, dict):
                continue

            title = self._first_string(item, JSON_TITLE_KEYS)
            url = self._first_string(item, JSON_URL_KEYS)
            raw_content = self._first_string(item, JSON_CONTENT_KEYS)

            nested = item.get("fields")
            if isinstance(nested, dict):
                title = title or self._first_string(nested, JSON_TITLE_KEYS)
                url = url or self._first_string(nested, JSON_URL_KEYS)
                raw_content = raw_content or self._first_string(
                    nested, JSON_CONTENT_KEYS
                )

            if not title and not url:
                continue

            articles.append(
                self._build_article(
                    title=title or "Untitled",
                    url=url or source_url,
                    raw_content=raw_content,
                    source=source_url,
                )
            )

        if not articles:
            logger.warning("No articles parsed from JSON endpoint: %s", source_url)

        return articles

    def _build_article(
        self,
        title: str,
        url: str,
        raw_content: str,
        source: str,
    ) -> RawArticle:
        cleaned_title = sanitize_html(title)
        cleaned_content = sanitize_html(raw_content)
        truncated_content = truncate_to_max_words(
            cleaned_content, self.settings.max_words
        )
        return RawArticle(
            title=cleaned_title,
            url=url.strip(),
            content=truncated_content,
            source=source,
        )

    def _deduplicate(self, articles: Iterable[RawArticle]) -> list[RawArticle]:
        unique: list[RawArticle] = []
        for article in articles:
            digest = self._article_hash(article)
            if digest in self._seen_hashes:
                logger.debug(
                    "Skipping duplicate article: %s",
                    article.url or article.title,
                )
                continue
            if self._state_store is not None and self._state_store.is_analyzed(digest):
                logger.debug(
                    "Skipping previously-seen article: %s",
                    article.url or article.title,
                )
                continue
            self._seen_hashes.add(digest)
            if self._state_store is not None:
                self._state_store.mark_seen(
                    digest, article.url, article.title, article.source
                )
            unique.append(article)
        return unique

    def mark_analyzed(self, article: RawArticle) -> None:
        """Record that an article was successfully analyzed."""
        if self._state_store is not None:
            digest = self._article_hash(article)
            self._state_store.mark_analyzed(digest)

    @staticmethod
    def _article_hash(article: RawArticle) -> str:
        key = (article.url.strip().lower() or article.title.strip().lower()).encode(
            "utf-8"
        )
        return hashlib.sha256(key).hexdigest()

    @staticmethod
    def _local_name(tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", maxsplit=1)[-1].lower()
        return tag.lower()

    def _extract_rss_field(
        self, item_element: ET.Element, candidate_tags: frozenset[str]
    ) -> str:
        for child in item_element:
            local_tag = self._local_name(child.tag)
            if local_tag in candidate_tags and child.text:
                return child.text.strip()
            if local_tag in candidate_tags:
                encoded = child.find("{*}encoded")
                if encoded is not None and encoded.text:
                    return encoded.text.strip()
        return ""

    def _extract_rss_link(self, item_element: ET.Element) -> str:
        for child in item_element:
            local_tag = self._local_name(child.tag)
            if local_tag != "link":
                continue
            href = child.attrib.get("href")
            if href:
                return href.strip()
            if child.text:
                return child.text.strip()
        return ""

    def _extract_json_items(self, payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            return []

        for key in JSON_ITEMS_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested_items = self._extract_json_items(value)
                if nested_items:
                    return nested_items

        return []

    @staticmethod
    def _first_string(data: dict[str, Any], keys: frozenset[str]) -> str:
        for key, value in data.items():
            if key.lower() not in keys:
                continue
            extracted = IngestionManager._coerce_to_string(value)
            if extracted:
                return extracted
        return ""

    @staticmethod
    def _coerce_to_string(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for nested_key in ("rendered", "plain", "text", "value", "html"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str) and nested_value.strip():
                    return nested_value.strip()
            for nested_value in value.values():
                if isinstance(nested_value, str) and nested_value.strip():
                    return nested_value.strip()
        if isinstance(value, list):
            for item in value:
                coerced = IngestionManager._coerce_to_string(item)
                if coerced:
                    return coerced
        return ""


def sanitize_html(raw: str) -> str:
    """Strip hostile/noisy HTML and return plain text."""
    if not raw or not raw.strip():
        return ""

    soup = BeautifulSoup(raw, "html.parser")

    for element in soup.find_all(STRIP_TAGS):
        element.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for element in soup.find_all(True):
        if not isinstance(element, Tag):
            continue
        if element.name in STRIP_TAGS:
            element.decompose()

    text = _extract_visible_text(soup)
    return WHITESPACE_RE.sub(" ", text).strip()


def _extract_visible_text(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        parent = node.parent
        if parent is not None and getattr(parent, "name", None) in STRIP_TAGS:
            return ""
        return str(node)

    if not isinstance(node, Tag):
        return ""

    if node.name in STRIP_TAGS:
        return ""

    parts: list[str] = []
    for child in node.children:
        extracted = _extract_visible_text(child)
        if extracted:
            parts.append(extracted)

    if node.name in {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
        return " ".join(parts) + " "

    return " ".join(parts)


def truncate_to_max_words(text: str, max_words: int) -> str:
    """Trim text to a word-count ceiling using a fast heuristic."""
    if max_words <= 0:
        return ""

    words = text.split()
    if len(words) <= max_words:
        return text

    return " ".join(words[:max_words])
