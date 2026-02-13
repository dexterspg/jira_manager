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


def _jira_put(endpoint: str, json_data: dict) -> None:
    """Make an authenticated PUT request to Jira REST API."""
    url = f"{JIRA_BASE_URL}/rest/api/3/{endpoint}"
    resp = requests.put(url, headers=_jira_headers(), json=json_data, timeout=30)
    resp.raise_for_status()


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
    custom_fields: dict | None = None,
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
        custom_fields: Dictionary of custom field IDs to values (e.g. {"customfield_10100": "value"}). Values are passed directly to the Jira API.
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
    if custom_fields:
        fields.update(custom_fields)

    try:
        data = _jira_post("issue", {"fields": fields})
    except requests.HTTPError as e:
        return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    new_key = data.get("key", "")
    return f"Issue created: **{new_key}** — {JIRA_BASE_URL}/browse/{new_key}"


@mcp.tool()
def update_jira_issue(
    issue_key: str,
    summary: str = "",
    description: str = "",
    status: str = "",
    priority: str = "",
    assignee_id: str = "",
    labels: list[str] | None = None,
    comment: str = "",
    custom_fields: dict | None = None,
) -> str:
    """Update an existing Jira issue's fields.

    Only provided fields are updated — omitted fields are left unchanged.
    To clear a field, pass an explicit empty/null value in custom_fields.

    Args:
        issue_key: The issue key to update (e.g. 'LAE-123')
        summary: New summary/title. Leave empty to keep current
        description: New plain text description (converted to ADF). Leave empty to keep current
        status: Target status name to transition to (e.g. 'In Progress', 'Done'). Leave empty to keep current
        priority: New priority name (e.g. 'High', 'Medium', 'Low'). Leave empty to keep current
        assignee_id: Atlassian account ID. Leave empty to keep current
        labels: New list of labels (replaces all existing labels). Leave as None to keep current
        comment: Add a comment to the issue. Leave empty to skip
        custom_fields: Dictionary of custom field IDs to values (e.g. {"customfield_10100": "value"}). Values are passed directly to the Jira API.
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    results = []

    # Build fields payload
    fields: dict = {}
    if summary:
        fields["summary"] = summary
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
    if labels is not None:
        fields["labels"] = labels
    if custom_fields:
        fields.update(custom_fields)

    # Update fields via PUT
    if fields:
        try:
            _jira_put(f"issue/{issue_key}", {"fields": fields})
            results.append(f"Fields updated: {', '.join(fields.keys())}")
        except requests.HTTPError as e:
            return f"Jira API error updating fields: {e.response.status_code} — {e.response.text[:500]}"
        except requests.RequestException as e:
            return f"Connection error: {e}"

    # Transition status if requested
    if status:
        try:
            transitions = _jira_get(f"issue/{issue_key}/transitions")
            match = next(
                (t for t in transitions.get("transitions", []) if t["name"].lower() == status.lower()),
                None,
            )
            if match:
                _jira_post(f"issue/{issue_key}/transitions", {"transition": {"id": match["id"]}})
                results.append(f"Status transitioned to: {status}")
            else:
                available = [t["name"] for t in transitions.get("transitions", [])]
                results.append(f"Status '{status}' not available. Available transitions: {', '.join(available)}")
        except requests.HTTPError as e:
            results.append(f"Error transitioning status: {e.response.status_code} — {e.response.text[:500]}")
        except requests.RequestException as e:
            results.append(f"Connection error during transition: {e}")

    # Add comment if requested
    if comment:
        try:
            comment_body = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}],
                }
            }
            _jira_post(f"issue/{issue_key}/comment", comment_body)
            results.append("Comment added")
        except requests.HTTPError as e:
            results.append(f"Error adding comment: {e.response.status_code} — {e.response.text[:500]}")
        except requests.RequestException as e:
            results.append(f"Connection error adding comment: {e}")

    if not results:
        return f"No changes specified for {issue_key}."

    return f"**{issue_key}** updated — {JIRA_BASE_URL}/browse/{issue_key}\n" + "\n".join(f"- {r}" for r in results)


@mcp.tool()
def copy_jira_issue(
    source_issue_key: str,
    target_project_key: str = "",
    summary_override: str = "",
    description_override: str = "",
    issue_type_override: str = "",
    custom_fields: dict | None = None,
) -> str:
    """Copy (clone) an existing Jira issue into a new issue.

    Fetches the source issue and creates a new issue with the same fields.
    Optionally override the target project, summary, description, or issue type.
    Custom fields from the source are automatically carried over. Use custom_fields to override or add additional custom fields.

    Args:
        source_issue_key: The issue key to copy from (e.g. 'LAE-123')
        target_project_key: Target project key. Leave empty to use same project as source
        summary_override: Override the summary. Leave empty to copy original (prefixed with '[Copy] ')
        description_override: Override the description. Leave empty to copy original
        issue_type_override: Override the issue type. Leave empty to copy original
        custom_fields: Dictionary of custom field IDs to values (e.g. {"customfield_10100": "value"}). Overrides source custom fields if same key. Values are passed directly to the Jira API.
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    # Fetch source issue (include all fields to capture custom fields)
    try:
        source = _jira_get(f"issue/{source_issue_key}")
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

    fix_versions = src_fields.get("fixVersions", [])
    if fix_versions:
        fields["fixVersions"] = [{"name": v.get("name", "")} for v in fix_versions]

    # Carry over custom fields from source (customfield_XXXXX)
    # Skip fields that are read-only or cause errors during creation
    _SKIP_CUSTOM_FIELDS = {
        "customfield_10007",  # Rank (Lexorank — causes rankBeforeIssue/rankAfterIssue errors)
        "customfield_10019",  # Rank (alternate ID in some Jira instances)
        "customfield_10016",  # Sprint (managed by board)
    }
    for key, value in src_fields.items():
        if not key.startswith("customfield_") or value is None:
            continue
        if key in _SKIP_CUSTOM_FIELDS:
            continue
        # Skip complex objects that are likely read-only (e.g., requestType, SLA)
        if isinstance(value, dict) and "requestType" in str(value):
            continue
        fields[key] = value

    # Apply custom field overrides (these take priority over source values)
    if custom_fields:
        fields.update(custom_fields)

    # Attempt creation — if it fails due to invalid fields, strip them and retry
    max_retries = 3
    for attempt in range(max_retries):
        try:
            data = _jira_post("issue", {"fields": fields})
            break
        except requests.HTTPError as e:
            if e.response.status_code == 400 and attempt < max_retries - 1:
                try:
                    err = e.response.json()
                    bad_fields = list(err.get("errors", {}).keys())
                    if bad_fields:
                        for bf in bad_fields:
                            # Remove by error key (e.g. "rankBeforeIssue")
                            fields.pop(bf, None)
                            # Also remove any customfield_ that might map to this error
                            to_remove = [k for k in fields if k.startswith("customfield_") and bf.lower() in str(fields[k]).lower()]
                            for k in to_remove:
                                fields.pop(k, None)
                        logger.info(f"Copy retry {attempt + 1}: removed fields {bad_fields}")
                        continue
                except (ValueError, KeyError):
                    pass
            return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
        except requests.RequestException as e:
            return f"Connection error: {e}"

    new_key = data.get("key", "")
    return f"Issue copied: **{source_issue_key}** → **{new_key}** — {JIRA_BASE_URL}/browse/{new_key}"


@mcp.tool()
def get_custom_fields(search: str = "") -> str:
    """List available Jira custom fields and their IDs.

    Args:
        search: Optional search string to filter fields by name (case-insensitive). Leave empty to list all custom fields.
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/field"
        resp = requests.get(url, headers=_jira_headers(), timeout=30)
        resp.raise_for_status()
        all_fields = resp.json()
    except requests.HTTPError as e:
        return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    custom = [f for f in all_fields if f.get("custom", False)]
    if search:
        search_lower = search.lower()
        custom = [f for f in custom if search_lower in f.get("name", "").lower()]

    if not custom:
        return f"No custom fields found matching '{search}'" if search else "No custom fields found"

    custom.sort(key=lambda f: f.get("name", ""))
    lines = [f"Found {len(custom)} custom field(s):\n"]
    for f in custom:
        lines.append(f"- **{f.get('name', '')}** — `{f.get('id', '')}` (type: {f.get('schema', {}).get('type', 'unknown')})")

    return "\n".join(lines)


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
