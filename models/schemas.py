"""Strict Pydantic models for AI analysis output."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ArticleCategory = Literal[
    "AI/LLM",
    "Macro/VC",
    "Competitor Move",
    "Infrastructure",
    "Irrelevant",
]

SUMMARY_MAX_WORDS: int = 60
BULLET_PREFIX_RE: re.Pattern[str] = re.compile(r"^(\*|-|\d+\.)\s", re.MULTILINE)


class ArticleAnalysis(BaseModel):
    """Validated structured output from the Anthropic analyzer."""

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    category: ArticleCategory
    impact_score: int = Field(ge=1, le=5)
    metrics_extracted: str
    summary_markdown: str = Field(min_length=1)

    @field_validator("title", "url", "summary_markdown", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("metrics_extracted", mode="before")
    @classmethod
    def _normalize_metrics(cls, value: object) -> str:
        if value is None:
            return "None"
        text = str(value).strip()
        return text if text else "None"

    @field_validator("summary_markdown")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        value = value.strip()
        words = value.split()
        if len(words) > SUMMARY_MAX_WORDS:
            value = " ".join(words[:SUMMARY_MAX_WORDS])
        if not value:
            value = "- No summary available"
        if not BULLET_PREFIX_RE.search(value):
            value = f"- {value}"
        return value


class AnalysisFailure(BaseModel):
    """Structured error-log item when analysis or validation fails."""

    title: str
    url: str
    source: str = ""
    error_type: Literal["api_error", "json_parse_error", "validation_error"] = "validation_error"
    error_message: str
    raw_response: str | None = None

    @field_validator("title", "url", "source", "error_message", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


AnalysisResult = ArticleAnalysis | AnalysisFailure
