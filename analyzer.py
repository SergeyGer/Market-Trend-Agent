"""Anthropic client orchestration with strict Pydantic JSON validation."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field

import anthropic
from anthropic import AsyncAnthropic
from pydantic import ValidationError

from config import Settings, get_settings
from ingest import RawArticle
from models.schemas import AnalysisFailure, AnalysisResult, ArticleAnalysis

logger = logging.getLogger(__name__)

JSON_FENCE_RE: re.Pattern[str] = re.compile(
    r"```(?:json)?\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)

TOOL_NAME: str = "submit_analysis"

SYSTEM_PROMPT: str = """You are a market and trend intelligence analyst.
Analyze the provided article and call the submit_analysis tool with a single
valid JSON object. Do not include prose, markdown fences, or comments outside
the tool call.

The JSON object MUST contain exactly these keys with these types and constraints:
{
  "title": "<string, article title>",
  "url": "<string, article URL>",
  "category": "<one of: AI/LLM | Macro/VC | Competitor Move | Infrastructure | Irrelevant>",
  "impact_score": <integer from 1 to 5, where 5 is highest strategic impact>,
  "metrics_extracted": "<string containing numbers or financial values found, or exactly None>",
  "summary_markdown": "<string, bulleted markdown summary, max 60 words, each bullet on its own line starting with - >"
}

Rules:
- category must be exactly one of the five allowed values.
- impact_score must be an integer between 1 and 5 inclusive.
- metrics_extracted must quote specific numbers, dollar amounts, percentages, or the literal string None.
- summary_markdown must use bullet lines starting with "- " and must not exceed 60 words total.
- Call submit_analysis with the JSON object as its single argument."""

USER_PROMPT_TEMPLATE: str = """Analyze this article for market and trend intelligence.

Source feed: {source}
Title: {title}
URL: {url}

Article content:
{content}

Call the submit_analysis tool now."""


class AnalyzerError(Exception):
    """Raised when the analyzer response cannot be interpreted."""


@dataclass
class ArticleAnalyzer:
    """Call Anthropic and validate structured analysis output."""

    settings: Settings = field(default_factory=get_settings)
    _client: AsyncAnthropic | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.settings.anthropic_api_key:
            raise AnalyzerError("ANTHROPIC_API_KEY is not configured")
        self._client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)

    async def analyze(self, article: RawArticle) -> AnalysisResult:
        """Analyze a single article; return validated output or a failure record."""
        raw_response: str | None = None
        try:
            payload, raw_response = await self._request_initial_payload(article)

            try:
                return ArticleAnalysis.model_validate(payload)
            except ValidationError as exc:
                if self.settings.correction_max_attempts <= 0:
                    raise

                logger.warning(
                    "Initial validation failed for %s; requesting correction: %s",
                    article.url,
                    exc,
                )
                payload, raw_response = await self._request_correction(
                    article,
                    self._format_validation_error(exc),
                )
                return ArticleAnalysis.model_validate(payload)

        except anthropic.APIError as exc:
            logger.error("Anthropic API error for %s: %s", article.url, exc)
            return self._build_failure(
                article=article,
                error_type="api_error",
                error_message=str(exc),
                raw_response=raw_response,
            )
        except json.JSONDecodeError as exc:
            logger.error("JSON parse error for %s: %s", article.url, exc)
            return self._build_failure(
                article=article,
                error_type="json_parse_error",
                error_message=f"Invalid JSON: {exc.msg}",
                raw_response=raw_response,
            )
        except AnalyzerError as exc:
            logger.error("Analyzer error for %s: %s", article.url, exc)
            return self._build_failure(
                article=article,
                error_type="api_error",
                error_message=str(exc),
                raw_response=raw_response,
            )
        except ValidationError as exc:
            logger.error("Validation error for %s: %s", article.url, exc)
            return self._build_failure(
                article=article,
                error_type="validation_error",
                error_message=self._format_validation_error(exc),
                raw_response=raw_response,
            )

    async def analyze_batch(
        self, articles: list[RawArticle]
    ) -> list[AnalysisResult]:
        """Analyze multiple articles concurrently with bounded parallelism."""
        semaphore = asyncio.Semaphore(self.settings.analysis_concurrency)

        async def _run(article: RawArticle) -> AnalysisResult:
            async with semaphore:
                return await self.analyze(article)

        results = list(await asyncio.gather(*(_run(article) for article in articles)))

        for result in results:
            if isinstance(result, ArticleAnalysis):
                logger.info(
                    "Analyzed '%s' | category=%s | impact=%d",
                    result.title,
                    result.category,
                    result.impact_score,
                )
            else:
                logger.warning(
                    "Analysis failed for '%s': %s",
                    result.title,
                    result.error_message,
                )

        return results

    async def _request_initial_payload(
        self, article: RawArticle
    ) -> tuple[dict[str, object], str]:
        """Request a structured analysis via tool use; fall back to JSON text."""
        user_prompt = USER_PROMPT_TEMPLATE.format(
            source=article.source,
            title=article.title,
            url=article.url,
            content=article.content,
        )

        message = await self._call_anthropic_with_backoff(
            article=article,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        tool_payload = self._extract_tool_input(message)
        if tool_payload is not None:
            return tool_payload, json.dumps(tool_payload)

        text = self._extract_text_content(message)
        return self._parse_json_response(text), text

    async def _request_correction(
        self,
        article: RawArticle,
        validation_errors: str,
    ) -> tuple[dict[str, object], str]:
        """Ask the model to correct a previously-invalid submission."""
        system = (
            "Your previous analysis submission failed schema validation. "
            "Read the validation errors and submit a corrected JSON object "
            "by calling the submit_analysis tool."
        )
        correction_prompt = (
            "Your previous analysis for the article below failed JSON schema "
            "validation.\n\n"
            f"Validation errors:\n{validation_errors}\n\n"
            "Review the article and submit a corrected structured analysis "
            "via the submit_analysis tool.\n\n"
            f"Source feed: {article.source}\n"
            f"Title: {article.title}\n"
            f"URL: {article.url}\n\n"
            "Article content:\n"
            f"{article.content}"
        )

        message = await self._call_anthropic_with_backoff(
            article=article,
            system=system,
            messages=[{"role": "user", "content": correction_prompt}],
        )

        tool_payload = self._extract_tool_input(message)
        if tool_payload is not None:
            return tool_payload, json.dumps(tool_payload)

        text = self._extract_text_content(message)
        return self._parse_json_response(text), text

    async def _call_anthropic_with_backoff(
        self,
        article: RawArticle,
        *,
        system: str,
        messages: list[dict[str, str]],
    ) -> anthropic.types.Message:
        if self._client is None:
            raise AnalyzerError("Anthropic client is not initialized")

        tools = self._analysis_tools()
        last_error: anthropic.APIError | None = None

        for attempt in range(1, self.settings.http_max_retries + 1):
            try:
                return await self._client.messages.create(
                    model=self.settings.anthropic_model,
                    max_tokens=1024,
                    system=system,
                    messages=messages,
                    tools=tools,
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                )
            except anthropic.APIError as exc:
                last_error = exc
                if not self._is_retryable_api_error(exc):
                    raise

                delay = self.settings.http_backoff_base * (2 ** (attempt - 1))
                delay += random.uniform(0, 0.5)
                logger.warning(
                    "Anthropic attempt %d/%d failed for %s: %s | retrying in %.2fs",
                    attempt,
                    self.settings.http_max_retries,
                    article.url,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    def _analysis_tools(self) -> list[dict[str, object]]:
        schema = ArticleAnalysis.model_json_schema()
        # Pydantic adds the model docstring as a top-level "description".
        # Some models then nest the entire payload under "description",
        # so remove it from the tool schema to avoid ambiguity.
        schema.pop("description", None)
        return [
            {
                "name": TOOL_NAME,
                "description": "Submit the structured market analysis result.",
                "input_schema": schema,
            }
        ]

    @staticmethod
    def _extract_tool_input(
        message: anthropic.types.Message,
    ) -> dict[str, object] | None:
        for block in message.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            if getattr(block, "name", None) != TOOL_NAME:
                continue
            input_data = getattr(block, "input", None)
            if isinstance(input_data, dict):
                return ArticleAnalyzer._normalize_tool_input(input_data)
        return None

    @staticmethod
    def _normalize_tool_input(
        input_data: dict[str, object],
    ) -> dict[str, object]:
        """Unwrap the occasional {"description": {...}} tool payload."""
        if set(input_data.keys()) == {"description"}:
            nested = input_data.get("description")
            if isinstance(nested, dict):
                return nested
        return input_data

    @staticmethod
    def _extract_text_content(message: anthropic.types.Message) -> str:
        parts: list[str] = []
        for block in message.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        if not parts:
            raise AnalyzerError("Anthropic response contained no text blocks")
        return "\n".join(parts).strip()

    @staticmethod
    def _parse_json_response(raw_response: str) -> dict[str, object]:
        text = raw_response.strip()
        fence_match = JSON_FENCE_RE.search(text)
        if fence_match:
            text = fence_match.group(1).strip()

        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise json.JSONDecodeError(
                "Expected JSON object at root",
                text,
                0,
            )
        return payload

    @staticmethod
    def _is_retryable_api_error(exc: anthropic.APIError) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            return True
        return status_code in {408, 429, 500, 502, 503, 504}

    @staticmethod
    def _format_validation_error(exc: ValidationError) -> str:
        details = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        return "; ".join(details)

    @staticmethod
    def _build_failure(
        article: RawArticle,
        error_type: str,
        error_message: str,
        raw_response: str | None = None,
    ) -> AnalysisFailure:
        return AnalysisFailure(
            title=article.title,
            url=article.url,
            source=article.source,
            error_type=error_type,
            error_message=error_message,
            raw_response=raw_response,
        )


def get_json_schema_hint() -> dict[str, object]:
    """Return the JSON schema used for strict response validation."""
    return ArticleAnalysis.model_json_schema()
