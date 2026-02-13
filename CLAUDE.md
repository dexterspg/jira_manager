# Jira Ticket Analyzer

## Quick Start

When the user says **"Analyze ticket PROJ-1234"** (or any variation like "look at", "review", "check"):

1. Delegate directly to the **content-creator** agent — it fetches ticket data and produces the 5-question analysis in a single pass
2. The content-creator saves the result to `output/{TICKET-KEY}-analysis.md` using `save_to_file`
3. Display the analysis to the user

When the user asks for **general ticket info** (not a 5-question analysis):

1. Delegate to the **ticket-analyzer** agent for raw ticket data and findings

When the user says **"Search for..."** or asks about tickets:

1. Build a JQL query from their natural language request
2. Call `search_jira_issues` with the JQL query
3. Summarize the results

When the user wants to **create, copy, update, or manage tickets**:

1. Delegate to the **ticket-manager** agent

## Available MCP Tools

| Tool | Purpose | Example |
|------|---------|---------|
| `get_jira_issue` | Fetch one ticket's full details (all comments, linked issues, attachments) | `get_jira_issue("LAE-123")` |
| `search_jira_issues` | Search with JQL | `search_jira_issues("project = LAE AND status = Open")` |
| `create_jira_issue` | Create a new ticket | `create_jira_issue("LAE", "Fix login bug", "Bug")` |
| `update_jira_issue` | Update fields, transition status, or add comments on an existing ticket | `update_jira_issue("LAE-123", priority="High", custom_fields={"customfield_10100": "value"})` |
| `copy_jira_issue` | Clone an existing ticket | `copy_jira_issue("LAE-123", target_project_key="OTHER")` |
| `save_to_file` | Save content to `output/` | `save_to_file("LAE-123-analysis.md", content)` |

## Project Structure

```
src/jira_mcp_server.py       — MCP server (Jira REST API tools + file saving)
templates/                    — Reference templates (content-creator has template embedded)
output/                       — Generated analyses and content
.claude/agents/               — Specialized subagents
```

## Subagents

### Analysis & Content

- **content-creator** (purple) — Self-sufficient: fetches ticket data via `get_jira_issue` and produces the final 5-question analysis in one pass. Also generates KB articles, release notes, and other content formats.
- **ticket-analyzer** (blue) — General-purpose ticket data gathering and analysis. Use when the user needs raw ticket info, patterns across tickets, or ad-hoc investigation (not the 5-question analysis).

### Operations

- **ticket-manager** (green) — Creates, copies, updates, and manages Jira tickets using `create_jira_issue`, `update_jira_issue`, and `copy_jira_issue`.

### Utility

- **jql-query-builder** (yellow) — Complex JQL query construction and iterative search refinement
- **jira-api-developer** (cyan) — Maintain and extend the MCP server (read-only — cannot create/update/copy tickets)

## Access Control

Only the **ticket-manager** agent may write to Jira. All other agents are read-only.

| Agent | `get_jira_issue` | `search_jira_issues` | `create_jira_issue` | `update_jira_issue` | `copy_jira_issue` | `save_to_file` |
|-------|:-:|:-:|:-:|:-:|:-:|:-:|
| **content-creator** | R | | | | | W |
| **ticket-analyzer** | R | R | | | | |
| **jql-query-builder** | | R | | | | |
| **jira-api-developer** | R | R | | | | W |
| **ticket-manager** | R | R | W | W | W | |

R = read, W = write. Empty = not permitted. Agents without permission MUST redirect users to **ticket-manager** for write operations.

## Analysis Format

Every ticket analysis and Resolution Path field (`customfield_12000`) **MUST** use exactly these 5 questions:

1. **What was the issue and its impact?**
2. **What caused the issue?**
3. **What troubleshooting steps should be taken?**
4. **What resolution or workaround was applied?**
5. **How can this be prevented in the future?**

Do NOT rephrase, reorder, or substitute these questions. Use them exactly as written above.

Each question gets detailed, technical answers incorporating all relevant information from the ticket's description, resolution path, comments, and attached files.
