"""Distribution layer: Notion page creation and Telegram alerts."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from config import Settings, get_settings
from models.schemas import AnalysisFailure, AnalysisResult, ArticleAnalysis

logger = logging.getLogger(__name__)

NOTION_API_BASE: str = "https://api.notion.com/v1"
NOTION_VERSION: str = "2022-06-28"
TELEGRAM_API_BASE: str = "https://api.telegram.org"
NOTION_RICH_TEXT_LIMIT: int = 2000

MARKDOWN_V2_ESCAPE_RE: re.Pattern[str] = re.compile(r"([_*\[\]()~`>#+\-=|{}.!])")
BULLET_LINE_RE: re.Pattern[str] = re.compile(r"^(\*|-|\d+\.)\s+(.*)")


class DistributionError(Exception):
    """Raised when a distribution target cannot be reached."""


@dataclass(frozen=True, slots=True)
class DistributionOutcome:
    """Result of distributing a single analysis."""

    notion_page_id: str | None = None
    telegram_sent: bool = False
    errors: tuple[str, ...] = ()


@dataclass
class DistributionManager:
    """Push validated analyses to Notion and high-impact alerts to Telegram."""

    settings: Settings = field(default_factory=get_settings)

    async def distribute(self, result: AnalysisResult) -> DistributionOutcome:
        """Distribute a single analysis or skip failures."""
        if isinstance(result, AnalysisFailure):
            logger.warning(
                "Skipping distribution for failed analysis '%s': %s",
                result.title,
                result.error_message,
            )
            return DistributionOutcome(errors=(result.error_message,))

        return await self._distribute_analysis(result)

    async def distribute_batch(
        self, results: list[AnalysisResult]
    ) -> list[DistributionOutcome]:
        """Distribute multiple analysis results concurrently."""
        semaphore = asyncio.Semaphore(self.settings.analysis_concurrency)

        async def _run(result: AnalysisResult) -> DistributionOutcome:
            async with semaphore:
                return await self.distribute(result)

        return list(await asyncio.gather(*(_run(result) for result in results)))

    async def _distribute_analysis(
        self, analysis: ArticleAnalysis
    ) -> DistributionOutcome:
        errors: list[str] = []
        notion_page_id: str | None = None
        telegram_sent = False

        try:
            notion_page_id = await self._create_notion_page(analysis)
            logger.info(
                "Created Notion page for '%s': %s", analysis.title, notion_page_id
            )
        except DistributionError as exc:
            message = f"Notion error: {exc}"
            logger.error(message)
            errors.append(message)

        if analysis.impact_score >= self.settings.telegram_min_impact_score:
            try:
                await self._send_telegram_alert(analysis)
                telegram_sent = True
                logger.info(
                    "Telegram alert sent for '%s' (impact=%d)",
                    analysis.title,
                    analysis.impact_score,
                )
            except DistributionError as exc:
                message = f"Telegram error: {exc}"
                logger.error(message)
                errors.append(message)
        else:
            logger.debug(
                "Skipping Telegram for '%s' (impact=%d < %d)",
                analysis.title,
                analysis.impact_score,
                self.settings.telegram_min_impact_score,
            )

        return DistributionOutcome(
            notion_page_id=notion_page_id,
            telegram_sent=telegram_sent,
            errors=tuple(errors),
        )

    async def _create_notion_page(self, analysis: ArticleAnalysis) -> str:
        if not self.settings.notion_api_key:
            raise DistributionError("NOTION_API_KEY is not configured")
        if not self.settings.notion_database_id:
            raise DistributionError("NOTION_DATABASE_ID is not configured")

        payload = {
            "parent": {"database_id": self.settings.notion_database_id},
            "properties": self._build_notion_properties(analysis),
            "children": self._build_notion_body_blocks(analysis.summary_markdown),
        }

        response_data = await self._request_with_retry(
            method="POST",
            url=f"{NOTION_API_BASE}/pages",
            headers=self._notion_headers(),
            json_body=payload,
            service_name="Notion",
        )
        page_id = response_data.get("id")
        if not isinstance(page_id, str) or not page_id:
            raise DistributionError("Notion response missing page id")
        return page_id

    def _build_notion_properties(self, analysis: ArticleAnalysis) -> dict[str, Any]:
        return {
            self.settings.notion_prop_title: {
                "title": [
                    {
                        "text": {
                            "content": self._truncate_text(
                                analysis.title, NOTION_RICH_TEXT_LIMIT
                            )
                        }
                    }
                ]
            },
            self.settings.notion_prop_category: {
                "select": {"name": analysis.category}
            },
            self.settings.notion_prop_impact: {
                "number": analysis.impact_score
            },
            self.settings.notion_prop_metrics: {
                "rich_text": self._notion_rich_text_chunks(analysis.metrics_extracted)
            },
            self.settings.notion_prop_url: {
                "url": analysis.url
            },
        }

    def _build_notion_body_blocks(self, summary_markdown: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []

        for line in summary_markdown.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            bullet_match = BULLET_LINE_RE.match(stripped)
            if bullet_match:
                blocks.append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": self._notion_rich_text_chunks(
                                bullet_match.group(2)
                            )
                        },
                    }
                )
                continue

            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": self._notion_rich_text_chunks(stripped)
                    },
                }
            )

        if not blocks:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": self._notion_rich_text_chunks(summary_markdown)
                    },
                }
            )

        return blocks

    async def _send_telegram_alert(self, analysis: ArticleAnalysis) -> None:
        if not self.settings.telegram_bot_token:
            raise DistributionError("TELEGRAM_BOT_TOKEN is not configured")
        if not self.settings.telegram_chat_id:
            raise DistributionError("TELEGRAM_CHAT_ID is not configured")

        message = self._format_telegram_message(analysis)
        url = (
            f"{TELEGRAM_API_BASE}/bot{self.settings.telegram_bot_token}/sendMessage"
        )
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": message,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }

        await self._request_with_retry(
            method="POST",
            url=url,
            headers={"Content-Type": "application/json"},
            json_body=payload,
            service_name="Telegram",
        )

    def _format_telegram_message(self, analysis: ArticleAnalysis) -> str:
        title = escape_markdown_v2(analysis.title)
        category = escape_markdown_v2(analysis.category)
        metrics = escape_markdown_v2(analysis.metrics_extracted)
        impact = escape_markdown_v2(str(analysis.impact_score))
        url = escape_markdown_v2(analysis.url)

        summary_lines: list[str] = []
        for line in analysis.summary_markdown.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            bullet_match = BULLET_LINE_RE.match(stripped)
            text = bullet_match.group(2) if bullet_match else stripped
            summary_lines.append(f"\u2022 {escape_markdown_v2(text)}")

        summary_block = "\n".join(summary_lines)
        return (
            f"*\U0001F514 High\\-Impact Alert*\n\n"
            f"*{title}*\n"
            f"*Category:* {category}\n"
            f"*Impact:* {impact}/5\n"
            f"*Metrics:* {metrics}\n\n"
            f"{summary_block}\n\n"
            f"[Read article]({url})"
        )

    def _notion_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.notion_api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any],
        service_name: str,
    ) -> dict[str, Any]:
        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=self.settings.http_timeout) as client:
            for attempt in range(1, self.settings.http_max_retries + 1):
                try:
                    response = await client.request(
                        method, url, headers=headers, json=json_body
                    )
                    if response.is_error:
                        body = response.text.strip()
                        # Retry only transient errors; surface 4xx body immediately.
                        if (
                            response.status_code == 429
                            or response.status_code >= 500
                        ):
                            response.raise_for_status()
                        raise DistributionError(
                            f"{service_name} HTTP {response.status_code}: "
                            f"{body[:500]}"
                        )
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict):
                        raise DistributionError(
                            f"{service_name} returned non-object JSON response"
                        )
                    return data
                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    last_error = exc
                    delay = self.settings.http_backoff_base * (2 ** (attempt - 1))
                    delay += random.uniform(0, 0.5)
                    logger.warning(
                        "%s attempt %d/%d failed: %s | retrying in %.2fs",
                        service_name,
                        attempt,
                        self.settings.http_max_retries,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)

        raise DistributionError(
            f"{service_name} request failed after "
            f"{self.settings.http_max_retries} attempts: {last_error}"
        ) from last_error

    @staticmethod
    def _notion_rich_text_chunks(text: str) -> list[dict[str, Any]]:
        content = text.strip() or "None"
        chunks: list[dict[str, Any]] = []
        start = 0
        while start < len(content):
            chunk = content[start : start + NOTION_RICH_TEXT_LIMIT]
            chunks.append({"text": {"content": chunk}})
            start += NOTION_RICH_TEXT_LIMIT
        return chunks

    @staticmethod
    def _truncate_text(text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return MARKDOWN_V2_ESCAPE_RE.sub(r"\\\1", text)
