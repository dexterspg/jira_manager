import logging
import os
import re
from base64 import b64encode
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
EMAIL = os.getenv("JIRA_EMAIL", "")
API_TOKEN = os.getenv("JIRA_API_TOKEN", "")

mcp = FastMCP("confluence")


def _headers() -> dict:
    token = b64encode(f"{EMAIL}:{API_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(endpoint: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}/wiki/rest/api/{endpoint}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _storage_to_text(html: str) -> str:
    """Strip HTML/XML tags from Confluence storage format, returning plain text."""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _format_page(page: dict) -> str:
    page_id = page.get("id", "")
    title = page.get("title", "")
    space = page.get("space", {}).get("name", "")
    space_key = page.get("space", {}).get("key", "")
    version = page.get("version", {}).get("number", "")
    url = f"{BASE_URL}/wiki/spaces/{space_key}/pages/{page_id}"
    body_html = page.get("body", {}).get("storage", {}).get("value", "")
    body_text = _storage_to_text(body_html)
    ancestors = page.get("ancestors", [])
    breadcrumb = " > ".join(a.get("title", "") for a in ancestors)
    breadcrumb = f"{breadcrumb} > {title}" if breadcrumb else title

    lines = [
        f"# {title}",
        f"**URL:** {url}",
        f"**Space:** {space} ({space_key})",
        f"**Version:** {version}",
        f"**Path:** {breadcrumb}",
        f"\n## Content\n{body_text}",
    ]
    return "\n".join(lines)


@mcp.tool()
def get_confluence_page(page_id: str) -> str:
    """Get a Confluence page by its ID, including title, space, and full body content.

    Args:
        page_id: The Confluence page ID (numeric, found in the page URL)
    """
    if not BASE_URL or not API_TOKEN:
        return "Error: Confluence credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    try:
        data = _get(f"content/{page_id}", params={"expand": "body.storage,version,space,ancestors"})
    except requests.HTTPError as e:
        return f"Confluence API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    return _format_page(data)


@mcp.tool()
def search_confluence_pages(cql: str, max_results: int = 10) -> str:
    """Search Confluence pages using a CQL query.

    Args:
        cql: A CQL query string (e.g. 'space = "NLA" AND title ~ "script"')
        max_results: Maximum number of results to return (default 10, max 50)
    """
    if not BASE_URL or not API_TOKEN:
        return "Error: Confluence credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    max_results = min(max_results, 50)
    try:
        data = _get("content/search", params={"cql": cql, "limit": max_results, "expand": "space,version"})
    except requests.HTTPError as e:
        return f"Confluence API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    results = data.get("results", [])
    if not results:
        return f"No results found for CQL: {cql}"

    lines = [f"Found {len(results)} result(s):\n"]
    for i, page in enumerate(results, 1):
        page_id = page.get("id", "")
        title = page.get("title", "")
        space_key = page.get("space", {}).get("key", "")
        space_name = page.get("space", {}).get("name", "")
        version = page.get("version", {}).get("number", "")
        url = f"{BASE_URL}/wiki/spaces/{space_key}/pages/{page_id}"
        lines.append(f"**{i}. [{title}]({url})**")
        lines.append(f"- **Space:** {space_name} ({space_key}) | **Version:** {version} | **ID:** {page_id}\n")

    return "\n".join(lines)


@mcp.tool()
def get_confluence_page_by_title(title: str, space_key: str = "") -> str:
    """Find a Confluence page by title, optionally filtered by space key.

    Args:
        title: The page title to search for (exact match)
        space_key: Optional space key to narrow the search (e.g. 'NLA', 'NFS'). Leave empty to search all spaces.
    """
    if not BASE_URL or not API_TOKEN:
        return "Error: Confluence credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    params: dict = {"title": title, "expand": "body.storage,version,space,ancestors", "limit": 5}
    if space_key:
        params["spaceKey"] = space_key

    try:
        data = _get("content", params=params)
    except requests.HTTPError as e:
        return f"Confluence API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    results = data.get("results", [])
    if not results:
        suffix = f" in space '{space_key}'" if space_key else ""
        return f"No Confluence page found with title '{title}'{suffix}"

    if len(results) > 1:
        lines = [f"Found {len(results)} pages matching '{title}'. Showing all:\n"]
        for page in results:
            pid = page.get("id", "")
            ptitle = page.get("title", "")
            sk = page.get("space", {}).get("key", "")
            url = f"{BASE_URL}/wiki/spaces/{sk}/pages/{pid}"
            lines.append(f"- **{ptitle}** (ID: {pid}, Space: {sk}) — {url}")
        return "\n".join(lines)

    return _format_page(results[0])


if __name__ == "__main__":
    mcp.run(transport="stdio")
