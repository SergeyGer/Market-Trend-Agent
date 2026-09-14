"""List Notion pages available to the integration.

Usage:
    python list_notion_pages.py

The script uses NOTION_API_KEY from .env and calls the /v1/search endpoint.
If no pages are listed, share a page with the integration first:
    Open page in Notion -> Share -> invite the integration.
"""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def extract_title(page: dict) -> str:
    """Return the plain text of the page's first title property."""
    properties = page.get("properties", {})
    if not isinstance(properties, dict):
        return "(untitled)"
    for prop in properties.values():
        if not isinstance(prop, dict) or prop.get("type") != "title":
            continue
        title_list = prop.get("title", [])
        if not isinstance(title_list, list):
            continue
        return "".join(
            item.get("plain_text", "")
            for item in title_list
            if isinstance(item, dict)
        )
    return "(untitled)"


def main() -> int:
    load_dotenv()

    api_key = os.getenv("NOTION_API_KEY", "")
    if not api_key:
        print("NOTION_API_KEY is not set", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "filter": {"value": "page", "property": "object"},
        "page_size": 100,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{NOTION_API_BASE}/search",
            headers=headers,
            json=payload,
        )
        if response.is_error:
            print(
                f"Notion HTTP {response.status_code}: {response.text}",
                file=sys.stderr,
            )
            return 1
        data = response.json()

    results = data.get("results", [])
    if not results:
        print("No pages are shared with this integration.")
        print(
            "Open a page in Notion -> Share -> invite the integration, "
            "then run this script again."
        )
        return 0

    print("Pages shared with the integration:")
    for page in results:
        if not isinstance(page, dict):
            continue
        page_id = page.get("id", "")
        title = extract_title(page)
        print(f"  {page_id}  {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())