# Jira Manager — Project CLAUDE.md

This project contains the Jira MCP server. Agents are global (`~/.claude/agents/`), knowledge is in the Jira skill (`~/.claude/skills/jira/SKILL.md`).

## Quick Start

When the user says **"Analyze ticket PROJ-1234"** → delegate to **jira-ticket-analyzer**
When the user asks for **content output** (KB article, 5-question analysis) → delegate to **jira-content-creator**
When the user wants to **create/copy/update tickets** → delegate to **jira-ticket-manager**

## JQL Fast Path (Direct Search)

When the user says **"Search for..."** — prefer this direct approach over agent delegation. Avoids LLM roundtrips and MCP startup overhead:

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

## Available MCP Tools

| Tool | Purpose |
|------|---------|
| `get_jira_issue` | Fetch one ticket's full details |
| `search_jira_issues` | Search with JQL |
| `create_jira_issue` | Create a new ticket |
| `update_jira_issue` | Update fields, transition status, add comments |
| `copy_jira_issue` | Clone an existing ticket |
| `get_custom_fields` | List custom field IDs by name |
| `log_work_on_issue` | Log work time on a ticket |
| `get_worklogs_by_date` | Get work logs for a date range |
| `save_to_file` | Save content to `output/` |

## Project Structure

```
src/jira_mcp_server.py   — MCP server (registered globally in ~/.claude.json)
output/                   — Generated analyses and content
.claude/agents/           — Project-specific agents only (jira-api-developer)
```

## Access Control

Only **jira-ticket-manager** may write to Jira. All other agents are read-only.

## Knowledge References

- **Field mappings, templates, custom fields:** `~/.claude/skills/jira/SKILL.md`
- **Agent definitions:** `~/.claude/agents/agent-jira-*.md`
