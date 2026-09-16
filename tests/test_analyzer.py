"""Tests for the Anthropic analyzer: tool parsing, retries, and validation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import pytest

from analyzer import TOOL_NAME, AnalyzerError, ArticleAnalyzer
from config import Settings
from ingest import RawArticle
from models.schemas import AnalysisFailure, ArticleAnalysis

VALID_PAYLOAD: dict[str, object] = {
    "title": "Test article",
    "url": "https://example.com/news",
    "category": "AI/LLM",
    "impact_score": 4,
    "metrics_extracted": "$1B",
    "summary_markdown": "- Point one",
}


def _make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "ANTHROPIC_API_KEY": "test-key",
        "STATE_DB_PATH": "",
        "HTTP_BACKOFF_BASE": 0.0,
        "CORRECTION_MAX_ATTEMPTS": 1,
        "ANALYSIS_CONCURRENCY": 2,
        "http_max_retries": 2,
        "anthropic_temperature": 0.1,
    }
    base.update(overrides)
    return Settings(**base)


def _article() -> RawArticle:
    return RawArticle(
        title="Test article",
        url="https://example.com/news",
        content="Some content about markets and AI.",
        source="https://example.com/feed",
    )


def _tool_message(payload: dict[str, object]) -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", name=TOOL_NAME, input=payload)
    return SimpleNamespace(content=[block])


def _text_message(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


class _FakeStatusError(anthropic.APIError):
    """Minimal APIError carrying an HTTP status for retry decisions."""

    def __init__(self, status_code: int, message: str = "boom") -> None:
        Exception.__init__(self, message)
        self.status_code = status_code


class _FakeMessages:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.messages = _FakeMessages(responses)


def _analyzer(responses: list[object], **overrides: object) -> ArticleAnalyzer:
    analyzer = ArticleAnalyzer(settings=_make_settings(**overrides))
    analyzer._client = _FakeClient(responses)  # type: ignore[assignment]
    return analyzer


def test_missing_api_key_raises() -> None:
    with pytest.raises(AnalyzerError):
        ArticleAnalyzer(settings=_make_settings(ANTHROPIC_API_KEY=""))


async def test_analyze_uses_tool_call_and_forwards_temperature() -> None:
    analyzer = _analyzer([_tool_message(VALID_PAYLOAD)])

    result = await analyzer.analyze(_article())

    assert isinstance(result, ArticleAnalysis)
    assert result.impact_score == 4
    call = analyzer._client.messages.calls[0]  # type: ignore[attr-defined]
    assert call["temperature"] == pytest.approx(0.1)
    assert call["tool_choice"] == {"type": "tool", "name": TOOL_NAME}


async def test_analyze_unwraps_nested_description_payload() -> None:
    analyzer = _analyzer([_tool_message({"description": VALID_PAYLOAD})])

    result = await analyzer.analyze(_article())

    assert isinstance(result, ArticleAnalysis)
    assert result.title == "Test article"


async def test_analyze_falls_back_to_fenced_json_text() -> None:
    text = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    analyzer = _analyzer([_text_message(text)])

    result = await analyzer.analyze(_article())

    assert isinstance(result, ArticleAnalysis)


async def test_analyze_requests_correction_on_invalid_payload() -> None:
    invalid = dict(VALID_PAYLOAD, impact_score=99)
    analyzer = _analyzer([_tool_message(invalid), _tool_message(VALID_PAYLOAD)])

    result = await analyzer.analyze(_article())

    assert isinstance(result, ArticleAnalysis)
    assert len(analyzer._client.messages.calls) == 2  # type: ignore[attr-defined]


async def test_analyze_returns_failure_on_non_retryable_error() -> None:
    analyzer = _analyzer([_FakeStatusError(400)])

    result = await analyzer.analyze(_article())

    assert isinstance(result, AnalysisFailure)
    assert result.error_type == "api_error"
    assert len(analyzer._client.messages.calls) == 1  # type: ignore[attr-defined]


async def test_analyze_retries_transient_error_then_succeeds() -> None:
    analyzer = _analyzer([_FakeStatusError(429), _tool_message(VALID_PAYLOAD)])

    result = await analyzer.analyze(_article())

    assert isinstance(result, ArticleAnalysis)
    assert len(analyzer._client.messages.calls) == 2  # type: ignore[attr-defined]


async def test_analyze_returns_failure_on_unparseable_text() -> None:
    analyzer = _analyzer([_text_message("not json at all")])

    result = await analyzer.analyze(_article())

    assert isinstance(result, AnalysisFailure)
    assert result.error_type == "json_parse_error"


async def test_analyze_batch_returns_aligned_results() -> None:
    analyzer = _analyzer([_tool_message(VALID_PAYLOAD), _tool_message(VALID_PAYLOAD)])

    results = await analyzer.analyze_batch([_article(), _article()])

    assert len(results) == 2
    assert all(isinstance(item, ArticleAnalysis) for item in results)
