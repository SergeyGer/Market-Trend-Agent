"""Tests for the distribution layer: Notion pages and Telegram alerts."""

from __future__ import annotations

import httpx
import pytest

from config import Settings
from distribute import (
    DistributionError,
    DistributionManager,
    escape_markdown_v2,
)
from models.schemas import AnalysisFailure, ArticleAnalysis


def _make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "ANTHROPIC_API_KEY": "test-key",
        "NOTION_API_KEY": "notion-key",
        "NOTION_DATABASE_ID": "db-id",
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "TELEGRAM_CHAT_ID": "42",
        "STATE_DB_PATH": "",
        "HTTP_BACKOFF_BASE": 0.0,
        "TELEGRAM_MIN_IMPACT_SCORE": 4,
        "http_max_retries": 2,
    }
    base.update(overrides)
    return Settings(**base)


def _analysis(**overrides: object) -> ArticleAnalysis:
    data: dict[str, object] = {
        "title": "Big News",
        "url": "https://example.com/news",
        "category": "AI/LLM",
        "impact_score": 5,
        "metrics_extracted": "$1B",
        "summary_markdown": "- First point\n- Second point",
    }
    data.update(overrides)
    return ArticleAnalysis(**data)


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_data: object = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def raise_for_status(self) -> None:
        if self.is_error:
            request = httpx.Request("POST", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> object:
        return self._json_data


class _FakeAsyncClient:
    responses: list[object] = []
    requests: list[dict[str, object]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: object = None,
    ) -> object:
        _FakeAsyncClient.requests.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        item = _FakeAsyncClient.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> DistributionManager:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.requests = []
    return DistributionManager(settings=_make_settings())


async def test_distribute_skips_failed_analysis(manager: DistributionManager) -> None:
    failure = AnalysisFailure(
        title="t",
        url="https://example.com",
        source="s",
        error_type="api_error",
        error_message="boom",
    )

    outcome = await manager.distribute(failure)

    assert outcome.notion_page_id is None
    assert outcome.telegram_sent is False
    assert outcome.errors == ("boom",)
    assert _FakeAsyncClient.requests == []


async def test_create_notion_page_sends_expected_request(
    manager: DistributionManager,
) -> None:
    _FakeAsyncClient.responses = [_FakeResponse(200, json_data={"id": "page-1"})]

    page_id = await manager._create_notion_page(_analysis())

    assert page_id == "page-1"
    request = _FakeAsyncClient.requests[0]
    assert request["method"] == "POST"
    assert str(request["url"]).endswith("/pages")
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer notion-key"
    payload = request["json"]
    assert isinstance(payload, dict)
    properties = payload["properties"]
    assert isinstance(properties, dict)
    assert "Title" in properties
    assert "Impact Score" in properties


async def test_notion_4xx_surfaces_body_without_retry(
    manager: DistributionManager,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(400, text='{"message": "bad schema"}')
    ]

    with pytest.raises(DistributionError) as exc_info:
        await manager._create_notion_page(_analysis())

    message = str(exc_info.value)
    assert "400" in message
    assert "bad schema" in message
    assert len(_FakeAsyncClient.requests) == 1


async def test_transient_500_is_retried_then_succeeds(
    manager: DistributionManager,
) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(500, text="server error"),
        _FakeResponse(200, json_data={"id": "page-2"}),
    ]

    page_id = await manager._create_notion_page(_analysis())

    assert page_id == "page-2"
    assert len(_FakeAsyncClient.requests) == 2


async def test_request_fails_after_exhausting_retries(
    manager: DistributionManager,
) -> None:
    _FakeAsyncClient.responses = [
        httpx.ConnectError("boom"),
        httpx.ConnectError("boom"),
    ]

    with pytest.raises(DistributionError):
        await manager._create_notion_page(_analysis())

    assert len(_FakeAsyncClient.requests) == 2


async def test_missing_notion_config_raises() -> None:
    manager = DistributionManager(settings=_make_settings(NOTION_API_KEY=""))

    with pytest.raises(DistributionError):
        await manager._create_notion_page(_analysis())


async def test_send_telegram_alert_uses_markdownv2(
    manager: DistributionManager,
) -> None:
    _FakeAsyncClient.responses = [_FakeResponse(200, json_data={"ok": True})]

    await manager._send_telegram_alert(_analysis())

    request = _FakeAsyncClient.requests[0]
    payload = request["json"]
    assert isinstance(payload, dict)
    assert payload["parse_mode"] == "MarkdownV2"
    assert payload["chat_id"] == "42"


async def test_distribute_full_happy_path(manager: DistributionManager) -> None:
    _FakeAsyncClient.responses = [
        _FakeResponse(200, json_data={"id": "page-3"}),
        _FakeResponse(200, json_data={"ok": True}),
    ]

    outcome = await manager.distribute(_analysis(impact_score=5))

    assert outcome.notion_page_id == "page-3"
    assert outcome.telegram_sent is True
    assert outcome.errors == ()
    assert len(_FakeAsyncClient.requests) == 2


async def test_below_threshold_skips_telegram(manager: DistributionManager) -> None:
    _FakeAsyncClient.responses = [_FakeResponse(200, json_data={"id": "page-4"})]

    outcome = await manager.distribute(_analysis(impact_score=1))

    assert outcome.notion_page_id == "page-4"
    assert outcome.telegram_sent is False
    assert len(_FakeAsyncClient.requests) == 1


def test_format_telegram_message_escapes_markdown(
    manager: DistributionManager,
) -> None:
    message = manager._format_telegram_message(_analysis(title="A.B (x)"))

    assert "A\\.B \\(x\\)" in message


def test_build_notion_body_blocks_creates_bullets(
    manager: DistributionManager,
) -> None:
    blocks = manager._build_notion_body_blocks("- one\n- two\nplain line")

    assert [block["type"] for block in blocks] == [
        "bulleted_list_item",
        "bulleted_list_item",
        "paragraph",
    ]


def test_notion_rich_text_chunks_split_long_text(
    manager: DistributionManager,
) -> None:
    chunks = manager._notion_rich_text_chunks("x" * 4500)

    assert len(chunks) == 3


def test_escape_markdown_v2_escapes_specials() -> None:
    assert escape_markdown_v2("50% off!") == "50% off\\!"
