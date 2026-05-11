import logging
import os
from base64 import b64encode
from pathlib import Path
from datetime import datetime, timezone, timedelta
import re

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load credentials from .env at project root
ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")

# Initialize MCP server
mcp = FastMCP("jira_gemini")

def _jira_headers() -> dict:
    token = b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def _jira_get(endpoint: str, params: dict | None = None) -> dict:
    url = f"{JIRA_BASE_URL}/rest/api/3/{endpoint}"
    resp = requests.get(url, headers=_jira_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()

def _jira_post(endpoint: str, json_data: dict) -> dict:
    url = f"{JIRA_BASE_URL}/rest/api/3/{endpoint}"
    resp = requests.post(url, headers=_jira_headers(), json=json_data, timeout=30)
    resp.raise_for_status()
    return resp.json()

@mcp.tool()
def get_raw_worklogs(start_date: str, end_date: str, projects: list[str] | None = None) -> list[dict]:
    if projects is None:
        projects = ["LAE", "NCS"]
    jql = f"project in ({', '.join(projects)}) AND worklogDate >= {start_date} AND worklogDate <= {end_date}"
    payload = {"jql": jql, "maxResults": 1000, "fields": ["key"]}
    search_data = _jira_post("search/jql", payload)
    issues = search_data.get("issues", [])
    all_logs = []
    for issue in issues:
        key = issue["key"]
        try:
            worklog_data = _jira_get(f"issue/{key}/worklog")
            for log in worklog_data.get("worklogs", []):
                started = log.get("started", "")[:10]
                if start_date <= started <= end_date:
                    all_logs.append({
                        "ticket": key,
                        "author": log.get("author", {}).get("displayName", "Unknown"),
                        "accountId": log.get("author", {}).get("accountId", ""),
                        "date": started,
                        "timeSpent": log.get("timeSpent", "0"),
                        "timeSpentSeconds": log.get("timeSpentSeconds", 0)
                    })
        except: continue
    return all_logs

@mcp.tool()
def get_member_ticket_counts(start_date: str, end_date: str, members_jql: list[str], projects: list[str] | None = None) -> dict:
    if projects is None:
        projects = ["LAE", "NCS"]
    proj_str = f"project in ({', '.join(projects)})"
    results = {}
    for member in members_jql:
        jql_resolved = f"{proj_str} AND resolved >= '{start_date}' AND resolved <= '{end_date}' AND assignee = {member}"
        jql_updated = f"{proj_str} AND updated >= '{start_date}' AND updated <= '{end_date}' AND assignee = {member}"
        try:
            res_data = _jira_post("search/jql", {"jql": jql_resolved, "maxResults": 0})
            upd_data = _jira_post("search/jql", {"jql": jql_updated, "maxResults": 0})
            results[member] = {"resolved": res_data.get("total", 0), "updated": upd_data.get("total", 0)}
        except: results[member] = {"resolved": 0, "updated": 0}
    return results

@mcp.tool()
def search_jira_issues(jql: str, max_results: int = 50) -> dict:
    payload = {"jql": jql, "maxResults": min(max_results, 100), "fields": ["summary", "status", "priority", "assignee", "reporter", "created", "updated", "project", "fixVersions", "versions", "customfield_13981"]}
    return _jira_post("search/jql", payload)

@mcp.tool()
def get_jira_issue(issue_key: str) -> dict:
    return _jira_get(f"issue/{issue_key}")

if __name__ == '__main__':
    mcp.run(transport='stdio')
