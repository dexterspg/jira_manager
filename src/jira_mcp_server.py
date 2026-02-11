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


def _jira_post(endpoint: str, json_data: dict) -> dict:
    """Make an authenticated POST request to Jira REST API."""
    url = f"{JIRA_BASE_URL}/rest/api/3/{endpoint}"
    resp = requests.post(url, headers=_jira_headers(), json=json_data, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------- Tools ----------


@mcp.tool()
def search_jira_issues(jql: str, max_results: int = 20) -> str:
    """Search Jira issues using a JQL query.

    Args:
        jql: A JQL query string (e.g. 'project = LAE AND assignee = currentUser()')
        max_results: Maximum number of results to return (default 20, max 100)
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    max_results = min(max_results, 100)
    try:
        # Use the new /rest/api/3/search/jql endpoint with POST
        url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status", "priority", "assignee", "reporter", "updated", "issuetype", "project"],
        }
        resp = requests.post(url, headers=_jira_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
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
        priority_obj = fields.get("priority")
        priority = priority_obj.get("name", "None") if priority_obj else "None"
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
            "fields": "summary,description,status,priority,assignee,reporter,created,updated,issuetype,project,labels,components,fixVersions,comment,resolution,resolutiondate,issuelinks,attachment",
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
    resolution = fields.get("resolution")

    # Convert Atlassian Document Format to plain text
    desc_text = _adf_to_text(desc) if desc else "No description"

    lines = [
        f"# {key}: {fields.get('summary', '')}",
        f"**URL:** {JIRA_BASE_URL}/browse/{key}",
        f"**Type:** {fields.get('issuetype', {}).get('name', '')}",
        f"**Status:** {fields.get('status', {}).get('name', '')}",
        f"**Priority:** {fields.get('priority', {}).get('name', '')}",
        f"**Resolution:** {resolution.get('name', 'Unresolved') if resolution else 'Unresolved'}",
        f"**Resolution Date:** {fields.get('resolutiondate', 'N/A') or 'N/A'}",
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

    # Include ALL comments
    comments_data = fields.get("comment", {}).get("comments", [])
    if comments_data:
        lines.append(f"\n## Comments ({len(comments_data)} total)")
        for c in comments_data:
            author = c.get("author", {}).get("displayName", "Unknown")
            created = c.get("created", "")[:16]
            body = _adf_to_text(c.get("body")) if c.get("body") else ""
            lines.append(f"\n**{author}** ({created}):\n{body}")

    # Include linked issues with summary details
    issue_links = fields.get("issuelinks", [])
    if issue_links:
        lines.append(f"\n## Linked Issues ({len(issue_links)})")
        for link in issue_links:
            link_type = link.get("type", {}).get("name", "Related")
            if "outwardIssue" in link:
                linked = link["outwardIssue"]
                direction = link.get("type", {}).get("outward", "relates to")
            elif "inwardIssue" in link:
                linked = link["inwardIssue"]
                direction = link.get("type", {}).get("inward", "relates to")
            else:
                continue
            linked_key = linked.get("key", "")
            linked_summary = linked.get("fields", {}).get("summary", "")
            linked_status = linked.get("fields", {}).get("status", {}).get("name", "")
            linked_type = linked.get("fields", {}).get("issuetype", {}).get("name", "")
            lines.append(f"- **{linked_key}** ({linked_type} | {linked_status}) — {direction}")
            lines.append(f"  {linked_summary}")

    # Include attachments
    attachments = fields.get("attachment", [])
    if attachments:
        lines.append(f"\n## Attachments ({len(attachments)})")
        for att in attachments:
            att_name = att.get("filename", "unknown")
            att_size = att.get("size", 0)
            att_author = att.get("author", {}).get("displayName", "Unknown")
            att_created = att.get("created", "")[:10]
            lines.append(f"- **{att_name}** ({att_size} bytes) — uploaded by {att_author} on {att_created}")

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

    if node_type == "mention":
        attrs = node.get("attrs", {})
        return attrs.get("text", "")
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
def create_jira_issue(
    project_key: str,
    summary: str,
    issue_type: str = "Task",
    description: str = "",
    priority: str = "",
    assignee_id: str = "",
    labels: list[str] | None = None,
) -> str:
    """Create a new Jira issue.

    Args:
        project_key: The project key (e.g. 'LAE')
        summary: Issue summary/title
        issue_type: Issue type name (e.g. 'Task', 'Bug', 'Story'). Default 'Task'
        description: Plain text description (converted to Atlassian Document Format)
        priority: Priority name (e.g. 'High', 'Medium', 'Low'). Leave empty for project default
        assignee_id: Atlassian account ID of the assignee. Leave empty for unassigned
        labels: List of label strings to apply
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    fields: dict = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }

    if description:
        fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
        }

    if priority:
        fields["priority"] = {"name": priority}
    if assignee_id:
        fields["assignee"] = {"accountId": assignee_id}
    if labels:
        fields["labels"] = labels

    try:
        data = _jira_post("issue", {"fields": fields})
    except requests.HTTPError as e:
        return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    new_key = data.get("key", "")
    return f"Issue created: **{new_key}** — {JIRA_BASE_URL}/browse/{new_key}"


@mcp.tool()
def copy_jira_issue(
    source_issue_key: str,
    target_project_key: str = "",
    summary_override: str = "",
    description_override: str = "",
    issue_type_override: str = "",
) -> str:
    """Copy (clone) an existing Jira issue into a new issue.

    Fetches the source issue and creates a new issue with the same fields.
    Optionally override the target project, summary, description, or issue type.

    Args:
        source_issue_key: The issue key to copy from (e.g. 'LAE-123')
        target_project_key: Target project key. Leave empty to use same project as source
        summary_override: Override the summary. Leave empty to copy original (prefixed with '[Copy] ')
        description_override: Override the description. Leave empty to copy original
        issue_type_override: Override the issue type. Leave empty to copy original
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    # Fetch source issue
    try:
        source = _jira_get(f"issue/{source_issue_key}", params={
            "fields": "summary,description,issuetype,project,priority,labels,components",
        })
    except requests.HTTPError as e:
        return f"Error fetching source issue: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    src_fields = source.get("fields", {})

    project_key = target_project_key or src_fields.get("project", {}).get("key", "")
    summary = summary_override or f"[Copy] {src_fields.get('summary', '')}"
    issue_type = issue_type_override or src_fields.get("issuetype", {}).get("name", "Task")

    fields: dict = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }

    # Copy description (already in ADF) or use override
    if description_override:
        fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": description_override}]}],
        }
    elif src_fields.get("description"):
        fields["description"] = src_fields["description"]

    priority = src_fields.get("priority")
    if priority:
        fields["priority"] = {"name": priority.get("name", "")}

    labels = src_fields.get("labels", [])
    if labels:
        fields["labels"] = labels

    components = src_fields.get("components", [])
    if components:
        fields["components"] = [{"name": c.get("name", "")} for c in components]

    try:
        data = _jira_post("issue", {"fields": fields})
    except requests.HTTPError as e:
        return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    new_key = data.get("key", "")
    return f"Issue copied: **{source_issue_key}** → **{new_key}** — {JIRA_BASE_URL}/browse/{new_key}"


@mcp.tool()
def save_to_file(filename: str, content: str, output_dir: str = "") -> str:
    """Save content to a file in the output/ directory.

    Args:
        filename: Name of the file to save (e.g. 'PROJ-123-analysis.md')
        content: The content to write to the file
        output_dir: Optional directory to save to. If omitted, saves to the default output/ directory.
    """
    safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_")
    if not safe_name:
        return "Error: Invalid filename"

    if output_dir:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = OUTPUT_DIR

    filepath = target_dir / safe_name
    filepath.write_text(content, encoding="utf-8")
    return f"File saved successfully: {filepath}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
