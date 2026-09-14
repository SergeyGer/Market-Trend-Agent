"""Tests for the Pydantic validation models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.schemas import SUMMARY_MAX_WORDS, ArticleAnalysis


def test_valid_analysis_is_accepted() -> None:
    analysis = ArticleAnalysis(
        title="Test article",
        url="https://example.com/news",
        category="AI/LLM",
        impact_score=4,
        metrics_extracted="$1B revenue",
        summary_markdown="- First point\n- Second point",
    )
    assert analysis.category == "AI/LLM"
    assert analysis.impact_score == 4
    assert analysis.metrics_extracted == "$1B revenue"


def test_invalid_category_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ArticleAnalysis(
            title="Test",
            url="https://example.com",
            category="NotACategory",  # type: ignore[arg-type]
            impact_score=1,
            metrics_extracted="None",
            summary_markdown="- ok",
        )


def test_summary_is_truncated_and_bulleted() -> None:
    analysis = ArticleAnalysis(
        title="Test",
        url="https://example.com",
        category="Irrelevant",
        impact_score=1,
        metrics_extracted="None",
        summary_markdown="word " * 200,
    )
    assert analysis.summary_markdown.startswith("- ")
    assert len(analysis.summary_markdown.split()) <= SUMMARY_MAX_WORDS + 1


def test_missing_metrics_normalizes_to_none() -> None:
    analysis = ArticleAnalysis(
        title="Test",
        url="https://example.com",
        category="Irrelevant",
        impact_score=1,
        metrics_extracted=None,  # type: ignore[arg-type]
        summary_markdown="- ok",
    )
    assert analysis.metrics_extracted == "None"
