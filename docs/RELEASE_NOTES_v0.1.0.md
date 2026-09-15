# Market & Trend Intelligence Agent v0.1.0

**Initial public release** of an autonomous AI pipeline that turns RSS and JSON news sources into structured market intelligence.

---

## Highlights

- **Async end-to-end pipeline** — ingestion → analysis → distribution inside a single `asyncio` event loop.
- **Anthropic Claude tool calling** — every analysis is produced through the `submit_analysis` tool and validated with Pydantic v2.
- **Persistent deduplication** — SQLite `StateStore` with an `analyzed_at` marker, so failed analyses are retried instead of being lost.
- **Resilient networking** — bounded concurrency and exponential backoff with jitter for both Anthropic and distribution calls.
- **Notion integration** — creates structured pages in a target database with configurable property names.
- **Telegram alerts** — sends high-impact items in `MarkdownV2` when `impact_score >= TELEGRAM_MIN_IMPACT_SCORE`.
- **Setup utilities** — scripts to create, update, and inspect Notion databases.

---

## What's Included

| Module | Responsibility |
| --- | --- |
| `main.py` | Async entrypoint: `ingest → analyze → distribute`. |
| `config.py` | Pydantic settings, environment aliases, logging. |
| `ingest.py` | RSS/JSON ingestion, HTML sanitization, deduplication. |
| `analyzer.py` | Anthropic async client, tool calling, retries, correction. |
| `distribute.py` | Notion page creation and Telegram alerts. |
| `storage.py` | SQLite state store for cross-run deduplication. |
| `models/schemas.py` | `ArticleAnalysis`, `AnalysisFailure`, validators. |
| `create_notion_database.py` | Creates a ready-to-use Notion database. |
| `update_notion_database.py` | Adds missing properties to an existing database. |
| `list_notion_pages.py` | Lists pages shared with the Notion integration. |

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.11+ |
| Async runtime | `asyncio`, `Semaphore`, `gather` |
| Configuration | `pydantic-settings`, `python-dotenv` |
| HTTP | `httpx` (sync and async) |
| RSS / HTML | `xml.etree.ElementTree`, `BeautifulSoup4` |
| LLM | Anthropic Claude via `AsyncAnthropic` |
| Structured output | Anthropic tool calling (`submit_analysis`) |
| Validation | Pydantic v2 |
| Persistence | SQLite |
| Integrations | Notion REST API, Telegram Bot API |
| Testing | `pytest`, `pytest-asyncio` |
| CI | GitHub Actions |

---

## Getting Started

```bash
git clone https://github.com/SergeyGer/Market-Trend-Agent.git
cd Market-Trend-Agent

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# fill in ANTHROPIC_API_KEY and source URLs
python main.py
```

Run the test suite:

```bash
pip install pytest pytest-asyncio
pytest -q
```

---

## Notion Setup

If you already have a database, align its schema in place:

```bash
python update_notion_database.py
```

To create a fresh database inside a shared page:

```bash
python create_notion_database.py --parent-page-id <PAGE_ID>
```

Then set `NOTION_DATABASE_ID` in `.env` to the printed database ID.

---

## Verification

A successful end-to-end run ends with:

```text
Pipeline complete | analyzed=<n> failures=<m> notion=<n> telegram=<m>
```

---

## Known Limitations

- Notion property names must match the configured `NOTION_PROP_*` values; use `update_notion_database.py` to align an existing database.
- Only Anthropic models are supported as the analysis provider.
- No built-in scheduler — use cron, Task Scheduler, or GitHub Actions.
- Telegram alerts are sent only for items at or above the configured impact threshold.

---

## Roadmap

- Expand the `pytest` suite to cover analyzer retries and distribution error paths.
- Add a Docker image and a scheduled GitHub Actions workflow.
- Add Slack, Discord, and email notification channels.
- Add a web dashboard for browsing aggregated intelligence.

---

## License

MIT. See [LICENSE](../LICENSE) for details.
