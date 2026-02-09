import logging
import os
from base64 import b64encode
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Configure logging to stderr (never stdout for stdio MCP servers)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load credentials — .env is at project root (one level up from src/)
load_dotenv(Path(__file__).parent.parent / ".env")

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")

# Output directory — at project root (one level up from src/)
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Initialize MCP server
mcp = FastMCP("jira-ticket-analyzer")


def _jira_headers() -> dict:
    """Build auth headers for Jira REST API."""
    token = b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _jira_get(endpoint: str, params: dict | None = None) -> dict:
    """Make an authenticated GET request to Jira REST API."""
    url = f"{JIRA_BASE_URL}/rest/api/3/{endpoint}"
    resp = requests.get(url, headers=_jira_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------- Tools ----------


@mcp.tool()
def search_jira_issues(jql: str, max_results: int = 20) -> str:
    """Search Jira issues using a JQL query.

    Args:
        jql: A JQL query string (e.g. 'project = LAE AND assignee = currentUser()')
        max_results: Maximum number of results to return (default 20, max 50)
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    max_results = min(max_results, 50)
    try:
        data = _jira_get("search", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,assignee,reporter,updated,issuetype,project",
        })
    except requests.HTTPError as e:
        return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    total = data.get("total", 0)
    issues = data.get("issues", [])

    if not issues:
        return f"No results found for JQL: {jql}"

    lines = [f"Found {total} issue(s) (showing {len(issues)}):\n"]
    for issue in issues:
        key = issue["key"]
        fields = issue["fields"]
        summary = fields.get("summary", "")
        status = fields.get("status", {}).get("name", "Unknown")
        priority = fields.get("priority", {}).get("name", "None")
        issue_type = fields.get("issuetype", {}).get("name", "")
        assignee = fields.get("assignee", {})
        assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
        updated = fields.get("updated", "")[:10]
        project = fields.get("project", {}).get("key", "")
        url = f"{JIRA_BASE_URL}/browse/{key}"

        lines.append(f"- **{key}** ({issue_type} | {status} | {priority})")
        lines.append(f"  {summary}")
        lines.append(f"  Assignee: {assignee_name} | Updated: {updated}")
        lines.append(f"  {url}\n")

    return "\n".join(lines)


@mcp.tool()
def get_jira_issue(issue_key: str) -> str:
    """Get detailed information about a single Jira issue.

    Args:
        issue_key: The Jira issue key (e.g. 'LAE-123')
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    try:
        data = _jira_get(f"issue/{issue_key}", params={
            "fields": "summary,description,status,priority,assignee,reporter,created,updated,issuetype,project,labels,components,fixVersions,comment",
        })
    except requests.HTTPError as e:
        return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    fields = data.get("fields", {})
    key = data.get("key", issue_key)

    assignee = fields.get("assignee")
    reporter = fields.get("reporter")
    desc = fields.get("description")

    # Convert Atlassian Document Format to plain text
    desc_text = _adf_to_text(desc) if desc else "No description"

    lines = [
        f"# {key}: {fields.get('summary', '')}",
        f"**URL:** {JIRA_BASE_URL}/browse/{key}",
        f"**Type:** {fields.get('issuetype', {}).get('name', '')}",
        f"**Status:** {fields.get('status', {}).get('name', '')}",
        f"**Priority:** {fields.get('priority', {}).get('name', '')}",
        f"**Project:** {fields.get('project', {}).get('name', '')} ({fields.get('project', {}).get('key', '')})",
        f"**Assignee:** {assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'}",
        f"**Reporter:** {reporter.get('displayName', 'Unknown') if reporter else 'Unknown'}",
        f"**Created:** {fields.get('created', '')[:10]}",
        f"**Updated:** {fields.get('updated', '')[:10]}",
    ]

    labels = fields.get("labels", [])
    if labels:
        lines.append(f"**Labels:** {', '.join(labels)}")

    components = fields.get("components", [])
    if components:
        lines.append(f"**Components:** {', '.join(c.get('name', '') for c in components)}")

    fix_versions = fields.get("fixVersions", [])
    if fix_versions:
        lines.append(f"**Fix Versions:** {', '.join(v.get('name', '') for v in fix_versions)}")

    lines.append(f"\n## Description\n{desc_text}")

    # Include recent comments
    comments_data = fields.get("comment", {}).get("comments", [])
    if comments_data:
        lines.append(f"\n## Comments ({len(comments_data)})")
        for c in comments_data[-5:]:  # Last 5 comments
            author = c.get("author", {}).get("displayName", "Unknown")
            created = c.get("created", "")[:10]
            body = _adf_to_text(c.get("body")) if c.get("body") else ""
            lines.append(f"\n**{author}** ({created}):\n{body}")

    return "\n".join(lines)


def _adf_to_text(node: dict | list | None) -> str:
    """Convert Atlassian Document Format (ADF) to plain text."""
    if node is None:
        return ""
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return str(node)

    node_type = node.get("type", "")
    text = node.get("text", "")
    content = node.get("content", [])

    if text:
        return text
    if node_type == "hardBreak":
        return "\n"
    if node_type in ("paragraph", "heading"):
        return _adf_to_text(content) + "\n"
    if node_type == "bulletList":
        items = []
        for item in content:
            items.append("- " + _adf_to_text(item.get("content", [])).strip())
        return "\n".join(items) + "\n"
    if node_type == "orderedList":
        items = []
        for i, item in enumerate(content, 1):
            items.append(f"{i}. " + _adf_to_text(item.get("content", [])).strip())
        return "\n".join(items) + "\n"
    if node_type == "codeBlock":
        code = _adf_to_text(content)
        return f"```\n{code}```\n"

    return _adf_to_text(content)


@mcp.tool()
def save_to_file(filename: str, content: str) -> str:
    """Save content to a file in the output/ directory.

    Args:
        filename: Name of the file to save (e.g. 'PROJ-123-analysis.md')
        content: The content to write to the file
    """
    safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_")
    if not safe_name:
        return "Error: Invalid filename"

    filepath = OUTPUT_DIR / safe_name
    filepath.write_text(content, encoding="utf-8")
    return f"File saved successfully: {filepath}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
