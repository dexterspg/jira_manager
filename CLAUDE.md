# Jira Ticket Analyzer

## Quick Start

When the user says **"Analyze ticket PROJ-1234"** (or any variation like "look at", "review", "check"):

1. Delegate to the **ticket-analyzer** agent to fetch full ticket data and gather raw findings
2. Pass the raw data to the **content-creator** agent, which reads `templates/content-creator-five-questions.md` and produces the final 5-question analysis
3. The content-creator saves the result to `output/{TICKET-KEY}-analysis.md` using `save_to_file`
4. Display the analysis to the user

When the user says **"Search for..."** or asks about tickets:

1. Build a JQL query from their natural language request
2. Call `search_jira_issues` with the JQL query
3. Summarize the results

## Available MCP Tools

| Tool | Purpose | Example |
|------|---------|---------|
| `get_jira_issue` | Fetch one ticket's full details | `get_jira_issue("LAE-123")` |
| `search_jira_issues` | Search with JQL | `search_jira_issues("project = LAE AND status = Open")` |
| `save_to_file` | Save content to `output/` | `save_to_file("LAE-123-analysis.md", content)` |

## Project Structure

```
src/jira_mcp_server.py       — MCP server (Jira REST API tools + file saving)
templates/content-creator-five-questions.md  — 5-question analysis template (owned by content-creator)
output/                       — Generated analyses and content
.claude/agents/               — Specialized subagents
```

## Subagents

### Analysis Workflow (ticket-analyzer → content-creator)

- **ticket-analyzer** (blue) — Fetches and analyzes raw ticket data. Responds to whatever it's asked — does not own the template or produce final documents. Used by the content-creator to gather data for the 5 questions.
- **content-creator** (purple) — Owns the 5-question template. Communicates the questions to ticket-analyzer, takes the raw data back, and produces the final detailed analysis document. Also generates KB articles, release notes, and other content formats.

### Utility Agents

- **jql-query-builder** (yellow) — Complex JQL query construction and iterative search refinement
- **jira-api-developer** (green) — Maintain and extend the MCP server

## Analysis Format

Every ticket analysis follows the 5-question format from `templates/content-creator-five-questions.md`:
1. What was the issue and its impact?
2. What caused the issue?
3. What troubleshooting steps should be taken?
4. What resolution or workaround was applied?
5. How can this be prevented in the future?

Each question gets detailed, technical answers incorporating all relevant information from the ticket's description, resolution path, comments, and attached files.
