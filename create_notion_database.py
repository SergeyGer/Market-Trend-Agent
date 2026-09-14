"""Create a Notion database with the properties expected by Market Trend Agent.

Usage:
    python create_notion_database.py --parent-page-id <PAGE_ID>

The parent page must be shared with your Notion integration, otherwise the
Notion API will return 404.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
from dotenv import load_dotenv

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

CATEGORY_OPTIONS = [
    {"name": "AI/LLM", "color": "blue"},
    {"name": "Macro/VC", "color": "green"},
    {"name": "Competitor Move", "color": "orange"},
    {"name": "Infrastructure", "color": "purple"},
    {"name": "Irrelevant", "color": "gray"},
]


def build_database_payload(parent_page_id: str, title: str) -> dict:
    return {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": {
            "Title": {"title": {}},
            "Category": {"select": {"options": CATEGORY_OPTIONS}},
            "Impact Score": {"number": {"format": "number"}},
            "Metrics": {"rich_text": {}},
            "URL": {"url": {}},
        },
    }


def create_database(
    api_key: str,
    parent_page_id: str,
    title: str,
) -> dict:
    payload = build_database_payload(parent_page_id, title)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{NOTION_API_BASE}/databases",
            headers=headers,
            json=payload,
        )
        if response.is_error:
            raise RuntimeError(
                f"Notion HTTP {response.status_code}: {response.text}"
            )
        data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Notion returned a non-object JSON response")
    return data


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parent-page-id",
        default=os.getenv("NOTION_PARENT_PAGE_ID", ""),
        help="Notion page ID where the database will be created.",
    )
    parser.add_argument(
        "--title",
        default="Market Trend Agent",
        help="Title of the new database.",
    )
    args = parser.parse_args()

    api_key = os.getenv("NOTION_API_KEY", "")
    if not api_key:
        print("NOTION_API_KEY is not set", file=sys.stderr)
        return 1

    if not args.parent_page_id:
        print(
            "Parent page ID is required. Pass --parent-page-id "
            "or set NOTION_PARENT_PAGE_ID.",
            file=sys.stderr,
        )
        return 1

    try:
        data = create_database(api_key, args.parent_page_id, args.title)
    except (httpx.HTTPError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1

    database_id = data.get("id", "")
    print(f"Created database: {database_id}")
    print("Add this line to your .env:")
    print(f"NOTION_DATABASE_ID={database_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())