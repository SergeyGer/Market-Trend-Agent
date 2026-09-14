"""Add missing properties to an existing Notion database.

The script updates the database referenced by NOTION_DATABASE_ID in .env so
that it matches the schema expected by Market Trend Agent:

    Title         -> title
    Category      -> select
    Impact Score  -> number
    Metrics       -> rich_text
    URL           -> url

Usage:
    python update_notion_database.py

The integration must already have access to the database, otherwise Notion
returns 404.
"""

from __future__ import annotations

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


def notion_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def fetch_schema(
    client: httpx.Client,
    api_key: str,
    database_id: str,
) -> dict[str, dict]:
    response = client.get(
        f"{NOTION_API_BASE}/databases/{database_id}",
        headers=notion_headers(api_key),
    )
    if response.is_error:
        raise RuntimeError(
            f"Notion HTTP {response.status_code}: {response.text}"
        )
    data = response.json()
    properties = data.get("properties", {})
    if not isinstance(properties, dict):
        raise RuntimeError("Notion database schema missing properties")
    return properties


def patch_database(
    client: httpx.Client,
    api_key: str,
    database_id: str,
    properties: dict,
) -> None:
    response = client.patch(
        f"{NOTION_API_BASE}/databases/{database_id}",
        headers=notion_headers(api_key),
        json={"properties": properties},
    )
    if response.is_error:
        raise RuntimeError(
            f"Notion HTTP {response.status_code}: {response.text}"
        )


def main() -> int:
    load_dotenv()

    api_key = os.getenv("NOTION_API_KEY", "")
    database_id = os.getenv("NOTION_DATABASE_ID", "")
    if not api_key:
        print("NOTION_API_KEY is not set", file=sys.stderr)
        return 1
    if not database_id:
        print("NOTION_DATABASE_ID is not set", file=sys.stderr)
        return 1

    with httpx.Client(timeout=30.0) as client:
        schema = fetch_schema(client, api_key, database_id)

        title_property = next(
            (
                name
                for name, prop in schema.items()
                if isinstance(prop, dict) and prop.get("type") == "title"
            ),
            None,
        )
        if title_property is None:
            print("No title property found in the database", file=sys.stderr)
            return 1

        if title_property != "Title":
            print(f"Renaming '{title_property}' -> 'Title'")
            patch_database(
                client,
                api_key,
                database_id,
                {title_property: {"name": "Title", "title": {}}},
            )
            schema = fetch_schema(client, api_key, database_id)

        additions: dict[str, object] = {}
        if "Category" not in schema:
            additions["Category"] = {"select": {"options": CATEGORY_OPTIONS}}
        if "Impact Score" not in schema:
            additions["Impact Score"] = {"number": {"format": "number"}}
        if "Metrics" not in schema:
            additions["Metrics"] = {"rich_text": {}}
        if "URL" not in schema:
            additions["URL"] = {"url": {}}

        if additions:
            print("Adding properties:", ", ".join(additions))
            patch_database(client, api_key, database_id, additions)
        else:
            print("All required properties already exist.")

    print("Database is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())