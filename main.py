"""Market & Trend Intelligence Agent entrypoint."""

from __future__ import annotations

import asyncio
import logging
import sys

from analyzer import ArticleAnalyzer, AnalyzerError
from config import configure_logging, get_settings
from distribute import DistributionManager
from ingest import IngestionManager
from models.schemas import AnalysisFailure, ArticleAnalysis

logger = logging.getLogger(__name__)


async def main() -> int:
    """Run ingest -> analyze -> distribute pipeline."""
    settings = get_settings()
    configure_logging(settings)

    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY is required")
        return 1

    ingestion_manager = IngestionManager(settings=settings)
    try:
        articles = ingestion_manager.ingest_all()
        if not articles:
            logger.warning("No articles ingested; exiting")
            return 0

        try:
            analyzer = ArticleAnalyzer(settings=settings)
        except AnalyzerError as exc:
            logger.error("Analyzer initialization failed: %s", exc)
            return 1

        results = await analyzer.analyze_batch(articles)

        for article, result in zip(articles, results):
            if isinstance(result, ArticleAnalysis):
                ingestion_manager.mark_analyzed(article)

        outcomes = await DistributionManager(settings=settings).distribute_batch(results)

        success_count = sum(1 for item in results if isinstance(item, ArticleAnalysis))
        failure_count = sum(1 for item in results if isinstance(item, AnalysisFailure))
        notion_count = sum(1 for outcome in outcomes if outcome.notion_page_id)
        telegram_count = sum(1 for outcome in outcomes if outcome.telegram_sent)

        logger.info(
            "Pipeline complete | analyzed=%d failures=%d notion=%d telegram=%d",
            success_count,
            failure_count,
            notion_count,
            telegram_count,
        )
        return 0
    finally:
        ingestion_manager.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
