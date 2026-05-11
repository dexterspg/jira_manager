# Jira Manager — Project Instructions & Skills

This project contains the Jira MCP server and associated workflows. It is the central hub for all Jira-related operations.

## Core Mandate: MCP Tools Only
**HARD RULE:** ALL Jira operations MUST use `mcp__jira__*` tools (or the local logic in `src/jira_mcp_server.py`). NEVER use any other Jira/Atlassian plugins.

---

## Available MCP Tools

The Jira MCP server (at `src/jira_mcp_server.py`) provides the following tools:

| Tool | Purpose |
|------|---------|
| `get_jira_issue` | Fetch one ticket's full details (including comments and links) |
| `search_jira_issues` | Search with JQL |
| `create_jira_issue` | Create a new ticket |
| `update_jira_issue` | Update fields, transition status, add comments |
| `copy_jira_issue` | Clone an existing ticket (automatically strips incompatible media) |
| `get_custom_fields` | List custom field IDs by name |
| `log_work_on_issue` | Log work time on a ticket |
| `get_worklogs_by_date` | Get work logs for a date range |
| `download_jira_attachments` | Download all (or filtered) attachments with auth & redirect handling |
| `save_to_file` | Save content to `output/` |

---

## JQL Fast Path (Direct Search)

For quick searches without full MCP overhead, use this direct logic from within the `jira_manager` directory:

```bash
cd /c/workarea/jira_manager && python -c "
from src.jira_mcp_server import _jira_post
payload = {'jql': '<JQL_HERE>', 'maxResults': 20, 'fields': ['summary','status','priority','assignee','reporter','updated','issuetype','project','fixVersions','versions']}
data = _jira_post('search/jql', payload)
issues = data.get('issues', [])
for issue in issues:
    f = issue['fields']
    key = issue['key']
    itype = f.get('issuetype',{}).get('name','')
    status = f.get('status',{}).get('name','')
    priority = f.get('priority',{}).get('name','') if f.get('priority') else 'None'
    summary = f.get('summary','')
    updated = f.get('updated','')[:10]
    assignee = f.get('assignee',{}).get('displayName','') if f.get('assignee') else ''
    reporter = f.get('reporter',{}).get('displayName','') if f.get('reporter') else ''
    fix_ver = ', '.join(v.get('name','') for v in f.get('fixVersions',[])) or 'N/A'
    affect_ver = ', '.join(v.get('name','') for v in f.get('versions',[])) or 'N/A'
    url = 'https://nakisa.atlassian.net/browse/' + key
    print(f'#: {issues.index(issue) + 1}')
    print(f'Key:            {url}')
    print(f'Type:           {itype}')
    print(f'Status:         {status}')
    print(f'Priority:       {priority}')
    print(f'Reporter:       {reporter}')
    print(f'Assignee:       {assignee}')
    print(f'Fix Version:    {fix_ver}')
    print(f'Affect Version: {affect_ver}')
    print(f'Summary:        {summary}')
    print(f'Updated:        {updated}')
    print()
is_last = data.get('isLast', True)
print(f'--- {len(issues)} issues{\"\" if is_last else \" (more available)\"} ---')
" 2>/dev/null
```

---

## Jira Skill: Field Mappings & Conventions

### NCS → LAE Ticket Workflow
1. **Fetch** the NCS ticket.
2. **Present** proposed LAE ticket fields → **wait for user confirmation**.
3. **Create** LAE ticket (with ADF description).
4. **Fix** Assignee: Development (`customfield_13004`) to Dexter Pagkaliwangan (`60396b7af032740068924835`).
5. **Add comment** (reuse wording from similar tickets) → ADF mention for reporter.
6. **Present** Resolution Path draft (5-question format) → **wait for user confirmation**.
7. **Close** via transition 801 with Root Cause + Resolution Path.
8. **Log time** using `log_work_on_issue`.

### Confirmation Before Write Operations
**MANDATORY** for ALL write operations:
- Show a summary of proposed changes.
- Wait for explicit confirmation.
- Each content field (description, resolution path, comment) is a separate confirmation gate.

### Quick Reference: Custom Field Names
- **customer:** `"Customer Commitment"` (use exact match `=` not `~`).

### Common JQL Patterns
- `"Customer Commitment" = Fairprice AND assignee = "Lionel Malonga" AND status = Closed`

---

## Workflow: 5-Question Analysis Format
Every ticket analysis and Resolution Path field (`customfield_12000`) **MUST** use exactly these 5 questions:
1. **What was the issue and its impact?**
2. **What caused the issue?**
3. **What troubleshooting steps should be taken?**
4. **What resolution or workaround was applied?**
5. **How can this be prevented in the future?**

---

## LAE Ticket Conventions
- **Type:** Default to **Support Request**.
- **Assignee:** Default to **Dexter Pagkaliwangan** (`60396b7af032740068924835`).
- **Post-Action Corrections:** After every creation or transition, re-fetch and ensure **Assignee** and **Assignee: Development** (`customfield_13004`) are set to Dexter.

---

## Attachment Download Protocol
Use `download_jira_attachments` for auth, redirect handling, and verification.
- **Verification:** Ensure file size > 0 and NOT an HTML error page.

---

## MCP Server Configuration

### Gemini CLI (Project-Local)
The Gemini-specific configuration is located at `.gemini/settings.json`. Gemini CLI automatically loads this server when starting in this directory.

```json
{
  "mcpServers": {
    "jira": {
      "command": "python",
      "args": ["C:/workarea/jira_manager/src/jira_mcp_server.py"],
      "cwd": "C:/workarea/jira_manager"
    }
  }
}
```

### Claude (Project-Local)
Claude uses `.mcp.json` for project-local configuration.

```json
{
  "mcpServers": {
    "jira": {
      "command": "python",
      "args": ["src/jira_mcp_server.py"],
      "cwd": "C:/workarea/jira_manager"
    }
  }
}
```

### Troubleshooting
- **Tools not available in Gemini:** Run `/mcp list` to check status. Use `/mcp reload` if you changed the server code.
- **Python errors:** Ensure `requirements.txt` dependencies are installed (`pip install -r requirements.txt`).
