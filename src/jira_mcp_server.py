import logging
import os
import zipfile
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
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

# Initialize MCP server — name must match the config key in ~/.claude/settings.json
# so tools register consistently as mcp__jira__* in every session
mcp = FastMCP("jira")


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
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "status", "priority", "assignee", "reporter", "created", "updated", "project", "fixVersions", "versions"],
        }
        data = _jira_post("search/jql", payload)
    except requests.HTTPError as e:
        return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    issues = data.get("issues", [])
    is_last = data.get("isLast", True)

    if not issues:
        return f"No results found for JQL: {jql}"

    count_label = f"{len(issues)} issue(s)" + ("" if is_last else "+")
    lines = [f"Found {count_label}:\n"]
    for issue in issues:
        key = issue["key"]
        fields = issue["fields"]
        summary = fields.get("summary", "")
        status = fields.get("status", {}).get("name", "Unknown")
        priority_obj = fields.get("priority")
        priority = priority_obj.get("name", "None") if priority_obj else "None"
        assignee = fields.get("assignee", {})
        assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
        reporter = fields.get("reporter", {})
        reporter_name = reporter.get("displayName", "Unknown") if reporter else "Unknown"
        created = fields.get("created", "")[:10]
        updated = fields.get("updated", "")[:10]
        fix_versions = ", ".join(v.get("name", "") for v in fields.get("fixVersions", [])) or "N/A"
        affect_versions = ", ".join(v.get("name", "") for v in fields.get("versions", [])) or "N/A"
        url = f"{JIRA_BASE_URL}/browse/{key}"

        lines.append(f"#: {issues.index(issue) + 1}")
        lines.append(f"Key:            {url}")
        lines.append(f"Status:         {status}")
        lines.append(f"Priority:       {priority}")
        lines.append(f"Reporter:       {reporter_name}")
        lines.append(f"Assignee:       {assignee_name}")
        lines.append(f"Fix Version:    {fix_versions}")
        lines.append(f"Affect Version: {affect_versions}")
        lines.append(f"Summary:        {summary}")
        lines.append(f"Created:        {created}")
        lines.append(f"Updated:        {updated}\n")

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
            "fields": "summary,description,status,priority,assignee,reporter,created,updated,issuetype,project,labels,components,fixVersions,versions,comment,resolution,resolutiondate,issuelinks,attachment,customfield_12000,customfield_13981",
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

    affect_versions = fields.get("versions", [])
    if affect_versions:
        lines.append(f"**Affect Versions:** {', '.join(v.get('name', '') for v in affect_versions)}")

    customer_commitment = fields.get("customfield_13981")
    if customer_commitment:
        values = [item.get("value", "") for item in customer_commitment if isinstance(item, dict)]
        if values:
            lines.append(f"**Customer Commitment:** {', '.join(values)}")

    # Resolution Path (customfield_12000)
    resolution_path = fields.get("customfield_12000")
    if resolution_path:
        resolution_path_text = _adf_to_text(resolution_path) if isinstance(resolution_path, dict) else str(resolution_path)
        lines.append(f"\n## Resolution Path\n{resolution_path_text}")

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


def _strip_media_from_adf(node: dict | None) -> dict | None:
    """Remove mediaSingle, mediaGroup, and media nodes from ADF.

    Jira rejects descriptions with media nodes that reference files from another
    issue. Call this before creating a copy of a ticket's description.
    """
    if not isinstance(node, dict):
        return node
    if node.get("type") in ("mediaSingle", "mediaGroup", "media"):
        return None
    content = node.get("content")
    if content:
        cleaned = [_strip_media_from_adf(c) for c in content if _strip_media_from_adf(c) is not None]
        node = {**node, "content": cleaned}
    return node


def _resolve_version_ids(project_key: str, version_names: list[str]) -> list[dict]:
    """Resolve version name strings to {id: ...} dicts for the Jira API.

    Jira version names can have leading/trailing spaces in the system but not
    in user input. This looks up the actual ID so name mismatches don't fail.
    Falls back to {name: ...} if lookup fails.
    """
    try:
        versions = _jira_get(f"project/{project_key}/versions")
        name_to_id: dict[str, str] = {v["name"].strip(): v["id"] for v in versions}
        result = []
        for name in version_names:
            stripped = name.strip()
            if stripped in name_to_id:
                result.append({"id": name_to_id[stripped]})
            else:
                # Partial match fallback
                match = next((vid for vname, vid in name_to_id.items() if stripped in vname or vname in stripped), None)
                result.append({"id": match} if match else {"name": name})
        return result
    except Exception:
        return [{"name": v} for v in version_names]


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
    description_adf: dict | None = None,
    priority: str = "",
    assignee_id: str = "",
    reporter_id: str = "",
    labels: list[str] | None = None,
    fix_versions: list[str] | None = None,
    affect_versions: list[str] | None = None,
    custom_fields: dict | None = None,
) -> str:
    """Create a new Jira issue.

    Args:
        project_key: The project key (e.g. 'LAE')
        summary: Issue summary/title
        issue_type: Issue type name (e.g. 'Task', 'Bug', 'Story'). Default 'Task'
        description: Plain text description (converted to Atlassian Document Format)
        description_adf: Raw ADF dict for the description. Use this instead of description when you need mentions or rich formatting. If provided, description is ignored.
        priority: Priority name (e.g. 'High', 'Medium', 'Low'). Leave empty for project default
        assignee_id: Atlassian account ID of the assignee. Leave empty for unassigned
        reporter_id: Atlassian account ID for the reporter. Leave empty for default
        labels: List of label strings to apply
        fix_versions: List of version name strings (e.g. ['1.0', '1.1']). Leave as None to skip
        affect_versions: List of version name strings (e.g. ['1.0']). Leave as None to skip
        custom_fields: Dictionary of custom field IDs to values (e.g. {"customfield_10100": "value"}). Values are passed directly to the Jira API.
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    fields: dict = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }

    if description_adf:
        fields["description"] = description_adf
    elif description:
        fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
        }

    if priority:
        fields["priority"] = {"name": priority}
    if assignee_id:
        fields["assignee"] = {"accountId": assignee_id}
    if reporter_id:
        fields["reporter"] = {"accountId": reporter_id}
    if labels:
        fields["labels"] = labels
    if fix_versions is not None:
        fields["fixVersions"] = _resolve_version_ids(project_key, fix_versions)
    if affect_versions is not None:
        fields["versions"] = _resolve_version_ids(project_key, affect_versions)
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
    reporter_id: str = "",
    labels: list[str] | None = None,
    fix_versions: list[str] | None = None,
    affect_versions: list[str] | None = None,
    comment: str = "",
    comment_adf: dict | None = None,
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
        reporter_id: Atlassian account ID for the reporter. Leave empty to keep current
        labels: New list of labels (replaces all existing labels). Leave as None to keep current
        fix_versions: List of version name strings (e.g. ['1.0', '1.1']). Replaces all existing fix versions. Leave as None to keep current
        affect_versions: List of version name strings (e.g. ['1.0']). Replaces all existing affect versions. Leave as None to keep current
        comment: Add a plain text comment to the issue. Leave empty to skip
        comment_adf: Add a comment using raw ADF dict (supports mentions). Use instead of comment when you need @mentions or rich formatting. If provided, comment is ignored.
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
    if reporter_id:
        fields["reporter"] = {"accountId": reporter_id}
    if labels is not None:
        fields["labels"] = labels
    if fix_versions is not None or affect_versions is not None:
        issue_data = _jira_get(f"issue/{issue_key}", params={"fields": "project"})
        update_project_key = issue_data.get("fields", {}).get("project", {}).get("key", "")
        if fix_versions is not None:
            fields["fixVersions"] = _resolve_version_ids(update_project_key, fix_versions)
        if affect_versions is not None:
            fields["versions"] = _resolve_version_ids(update_project_key, affect_versions)
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
                (t for t in transitions.get("transitions", [])
                 if t["name"].lower() == status.lower() or t["to"]["name"].lower() == status.lower()),
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
    if comment_adf or comment:
        try:
            if comment_adf:
                comment_body = {"body": comment_adf}
            else:
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
    summary: str = "",
    description: str = "",
    description_adf: dict | None = None,
    issue_type: str = "",
    custom_fields: dict | None = None,
) -> str:
    """Copy (clone) an existing Jira issue into a new issue.

    Fetches the source issue and creates a new issue with the same fields.
    Media attachments embedded in the source description are automatically
    stripped to avoid Jira validation errors (files can be re-attached after).

    Args:
        source_issue_key: The issue key to copy from (e.g. 'LAE-123')
        target_project_key: Target project key. Leave empty to use same project as source
        summary: Override the summary. Leave empty to copy original (prefixed with '[Copy] ')
        description: Override description with plain text. Leave empty to copy original
        description_adf: Override description with raw ADF dict (supports mentions). Takes priority over description if both provided.
        issue_type: Override the issue type. Leave empty to copy original
        custom_fields: Dictionary of custom field IDs to values. Overrides source custom fields if same key.
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
    new_summary = summary or f"[Copy] {src_fields.get('summary', '')}"
    new_issue_type = issue_type or src_fields.get("issuetype", {}).get("name", "Task")

    fields: dict = {
        "project": {"key": project_key},
        "summary": new_summary,
        "issuetype": {"name": new_issue_type},
    }

    # Description: override takes priority, then copy source (stripping media nodes)
    if description_adf:
        fields["description"] = description_adf
    elif description:
        fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
        }
    elif src_fields.get("description"):
        # Strip media nodes — Jira rejects media refs from other issues during creation
        cleaned = _strip_media_from_adf(src_fields["description"])
        if cleaned:
            fields["description"] = cleaned

    priority = src_fields.get("priority")
    if priority:
        fields["priority"] = {"name": priority.get("name", "")}

    labels = src_fields.get("labels", [])
    if labels:
        fields["labels"] = labels

    components = src_fields.get("components", [])
    if components:
        fields["components"] = [{"name": c.get("name", "")} for c in components]

    # Use IDs (not names) for versions — names can have leading/trailing spaces in Jira
    fix_versions = src_fields.get("fixVersions", [])
    if fix_versions:
        fields["fixVersions"] = [{"id": v["id"]} for v in fix_versions if v.get("id")]

    affect_versions = src_fields.get("versions", [])
    if affect_versions:
        fields["versions"] = [{"id": v["id"]} for v in affect_versions if v.get("id")]

    # Carry over custom fields from source (customfield_XXXXX)
    # Skip fields that are read-only or cause errors during creation
    _SKIP_CUSTOM_FIELDS = {
        "customfield_10007",  # Rank (Lexorank — causes rankBeforeIssue/rankAfterIssue errors)
        "customfield_10019",  # Rank (alternate ID in some Jira instances)
        "customfield_10016",  # Sprint (managed by board)
    }
    for cf_key, value in src_fields.items():
        if not cf_key.startswith("customfield_") or value is None:
            continue
        if cf_key in _SKIP_CUSTOM_FIELDS:
            continue
        # Skip complex objects that are likely read-only (e.g., requestType, SLA)
        if isinstance(value, dict) and "requestType" in str(value):
            continue
        fields[cf_key] = value

    # Apply custom field overrides (these take priority over source values)
    if custom_fields:
        fields.update(custom_fields)

    # Attempt creation — if it fails due to invalid fields, strip them and retry
    max_retries = 3
    data = None
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

    if data is None:
        return f"Error: Failed to create copy of {source_issue_key} after {max_retries} retries"

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
        all_fields = _jira_get("field")
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
def log_work_on_issue(
    issue_key: str,
    time_spent: str,
    comment: str = "",
    started: str = "",
) -> str:
    """Log work time on a Jira issue (equivalent to the 'Log work' button in the UI).

    Args:
        issue_key: The Jira issue key (e.g. 'LAE-123')
        time_spent: Time spent in Jira duration format (e.g. '2h 30m', '1h', '30m', '1d')
        comment: Optional work description/comment
        started: Optional start datetime in ISO 8601 format (e.g. '2026-02-23T09:00:00.000+0000'). Defaults to now.
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    if not time_spent:
        return "Error: time_spent is required (e.g. '2h 30m', '1h', '30m')"

    payload: dict = {"timeSpent": time_spent}

    if started:
        payload["started"] = started
    else:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        # Jira requires offset format (+0000), not Z
        payload["started"] = now.strftime("%Y-%m-%dT%H:%M:%S.000+0000")

    if comment:
        payload["comment"] = {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}],
        }

    try:
        data = _jira_post(f"issue/{issue_key}/worklog", payload)
    except requests.HTTPError as e:
        return f"Jira API error: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    worklog_id = data.get("id", "")
    time_logged = data.get("timeSpent", time_spent)
    author = data.get("author", {}).get("displayName", "")
    started_out = data.get("started", "")[:16]

    return (
        f"Work logged on **{issue_key}** — {JIRA_BASE_URL}/browse/{issue_key}\n"
        f"- Time spent: {time_logged}\n"
        f"- Started: {started_out}\n"
        f"- Author: {author}\n"
        f"- Worklog ID: {worklog_id}"
    )


@mcp.tool()
def get_worklogs_by_date(start_date: str, end_date: str, assignee_names: list[str] | None = None, projects: list[str] | None = None, filter_by: str = "worklog") -> str:
    """Get work logs for a date range, optionally filtered by assignee names and projects.

    Args:
        start_date: Start date in YYYY-MM-DD format (e.g., '2026-02-20')
        end_date: End date in YYYY-MM-DD format (e.g., '2026-02-23')
        assignee_names: Optional list of assignee names to filter by (e.g., ['Abdul Ghani', 'Samra Ejaz'])
        projects: Optional list of project keys to search in (default: ['LAE', 'NCS'])
        filter_by: How to find candidate issues — 'worklog' (default) finds issues with worklogs logged in the date range; 'updated' finds issues updated in the date range that also have worklogs in that range
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured. Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env"

    if projects is None:
        projects = ["LAE", "NCS"]

    date_field = "worklogDate" if filter_by == "worklog" else "updated"

    try:
        # Search for issues matching the date range
        payload = {
            "jql": f"project in ({', '.join(projects)}) AND {date_field} >= {start_date} AND {date_field} <= {end_date} ORDER BY updated DESC",
            "maxResults": 500,
            "fields": ["key"]
        }
        search_data = _jira_post("search/jql", payload)
        issues = search_data.get("issues", [])
    except requests.HTTPError as e:
        return f"Jira API error searching issues: {e.response.status_code} — {e.response.text[:500]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    if not issues:
        return f"No issues found updated between {start_date} and {end_date}"

    worklogs_by_person = {}
    worklogs_by_date = {}

    # Fetch worklogs for each issue
    for issue in issues:
        key = issue["key"]
        try:
            worklog_data = _jira_get(f"issue/{key}/worklog")
            worklogs = worklog_data.get("worklogs", [])

            for log in worklogs:
                author = log.get("author", {}).get("displayName", "Unknown")
                started = log.get("started", "")[:10]

                # Filter by date range
                if not (start_date <= started <= end_date):
                    continue

                # Filter by assignee names if provided
                if assignee_names and not any(name.lower() in author.lower() for name in assignee_names):
                    continue

                time_spent = log.get("timeSpent", "0")

                # Group by person
                if author not in worklogs_by_person:
                    worklogs_by_person[author] = []
                worklogs_by_person[author].append({
                    "ticket": key,
                    "date": started,
                    "time_spent": time_spent
                })

                # Group by date
                if started not in worklogs_by_date:
                    worklogs_by_date[started] = {}
                if author not in worklogs_by_date[started]:
                    worklogs_by_date[started][author] = []
                worklogs_by_date[started][author].append({
                    "ticket": key,
                    "time_spent": time_spent
                })
        except requests.HTTPError:
            pass  # Skip issues that fail
        except requests.RequestException:
            pass

    if not worklogs_by_person:
        return f"No work logs found for the specified criteria between {start_date} and {end_date}"

    # Format output by date
    lines = [f"# Work Logs: {start_date} to {end_date}\n"]

    for date in sorted(worklogs_by_date.keys(), reverse=True):
        lines.append(f"\n## {date}\n")
        for person in sorted(worklogs_by_date[date].keys()):
            logs = worklogs_by_date[date][person]
            lines.append(f"\n**{person}**")
            for log in logs:
                lines.append(f"- {log['ticket']}: {log['time_spent']}")

    return "\n".join(lines)


def _download_one_attachment(att: dict, target_dir: Path, extract_zips: bool) -> tuple[str, str | None]:
    """Download a single attachment and optionally extract if it's a zip.

    Returns (row_text, saved_path_or_None). Used by the parallel executor.
    """
    filename = att.get("filename", f"attachment-{att.get('id', '')}")
    att_id = att.get("id")
    target_path = target_dir / filename

    try:
        resp = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/attachment/content/{att_id}",
            headers={"Authorization": _jira_headers()["Authorization"]},
            allow_redirects=True,
            stream=True,
            timeout=120,
        )
        resp.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
    except requests.HTTPError as e:
        return (f"  FAIL: {filename} — HTTP {e.response.status_code}", None)
    except requests.RequestException as e:
        return (f"  FAIL: {filename} — {e}", None)

    size = target_path.stat().st_size
    if size == 0:
        return (f"  FAIL: {filename} — empty file (likely missing redirect follow)", None)
    with open(target_path, "rb") as f:
        head = f.read(200).lower()
    if b"<!doctype html" in head or b"<html" in head:
        return (f"  FAIL: {filename} — HTML response saved (auth/error page, {size} bytes)", None)

    row = f"  OK: {filename} ({size:,} bytes) -> {target_path}"

    if extract_zips and filename.lower().endswith(".zip"):
        extract_dir = target_dir / target_path.stem
        try:
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target_path) as zf:
                zf.extractall(extract_dir)
            row += f"\n         extracted -> {extract_dir}"
        except zipfile.BadZipFile:
            row += f"\n         WARN: could not extract — not a valid zip"
        except OSError as e:
            row += f"\n         WARN: extract failed — {e}"

    return (row, str(target_path))


@mcp.tool()
def download_jira_attachments(
    issue_key: str,
    output_dir: str,
    filename_filter: str = "",
    extract_zips: bool = True,
    max_workers: int = 4,
) -> str:
    """Download attachments from a Jira issue to a local directory.

    Centralizes the Jira attachment download protocol (REST API v3, follows
    redirect to S3, verifies each file is non-empty and not an HTML error page).
    Use this instead of curl + bash — auth, redirect handling, and verification
    are handled here. Downloads run in parallel and zip files are auto-extracted.

    Args:
        issue_key: The Jira issue key (e.g. 'LAE-44173')
        output_dir: Absolute directory path to save attachments to (created if missing)
        filename_filter: Optional case-insensitive substring filter — only
            attachments whose filename contains this substring are downloaded.
            Empty = all attachments.
        extract_zips: When True (default), .zip attachments are extracted into a
            sibling directory named after the zip (without the .zip suffix).
        max_workers: Parallel download workers (default 4). Set to 1 to force serial.

    Returns: A multi-line summary of OK / FAILED / SKIPPED rows per attachment,
    plus the absolute paths of successful downloads.
    """
    if not JIRA_BASE_URL or not JIRA_API_TOKEN:
        return "Error: Jira credentials not configured."

    target_dir = Path(output_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"Error: cannot create output_dir {output_dir}: {e}"

    try:
        data = _jira_get(f"issue/{issue_key}", params={"fields": "attachment"})
    except requests.HTTPError as e:
        return f"Jira API error fetching {issue_key}: {e.response.status_code} — {e.response.text[:300]}"
    except requests.RequestException as e:
        return f"Connection error: {e}"

    attachments = data.get("fields", {}).get("attachment", [])
    if not attachments:
        return f"No attachments on {issue_key}."

    needle = filename_filter.lower() if filename_filter else ""
    rows: list[str] = [f"Issue: {issue_key} — {len(attachments)} attachment(s) total"]
    saved_paths: list[str] = []

    # Partition into to-download vs filtered, preserving original order in output
    to_download: list[tuple[int, dict]] = []
    skip_rows: dict[int, str] = {}
    for idx, att in enumerate(attachments):
        filename = att.get("filename", f"attachment-{att.get('id', '')}")
        if needle and needle not in filename.lower():
            skip_rows[idx] = f"  SKIP: {filename} (filter mismatch)"
        else:
            to_download.append((idx, att))

    results: dict[int, tuple[str, str | None]] = {}
    if to_download:
        workers = max(1, min(max_workers, len(to_download)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_download_one_attachment, att, target_dir, extract_zips): idx
                for idx, att in to_download
            }
            for fut in futures:
                idx = futures[fut]
                results[idx] = fut.result()

    for idx in range(len(attachments)):
        if idx in skip_rows:
            rows.append(skip_rows[idx])
        else:
            row, saved = results[idx]
            rows.append(row)
            if saved:
                saved_paths.append(saved)

    rows.append("")
    rows.append(f"Saved {len(saved_paths)} file(s) to {target_dir}")
    return "\n".join(rows)


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
