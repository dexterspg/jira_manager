# Code Review: jira_manager Project

**Reviewer:** Claude Opus 4.6 (agent-quality-guardian)  
**Date:** 2026-02-13  
**Scope:** Full project review — all agents, MCP server, templates, configuration  
**Trigger:** Post-incident review after Resolution Path field was populated with wrong 5-question format

---

## Critical (Must Fix)

### C-1: SECURITY — Live API Token Committed in `.env` File

**File:** `C:\workarea\jira_manager\.env` (line 3)

The `.env` file contains a live Jira API token in plaintext:

```
JIRA_API_TOKEN=ATATT3xFfGF0ay5Mi_0xP64VFgpNRb5DMDRG2VtjTJp9E_ZB_TIy2fHm8XLegGUOLp2qBZkX2J0I8AkKepghAHZiyRniK_QuZIawB1Ns-BlFS-T_YaQZWAg5glZpZuH-v_ZWqZ2C-mhQYVVR8dZY9QR-Vej0B2iT67YdZSxemNUrQq86BnNSAfU=78432CBA
```

While `.env` IS listed in `.gitignore` and was never committed to git history (confirmed), the `.env` file is still sitting on disk with the full Jira API token plus user email. This token grants full REST API access to the Nakisa Jira instance. If this workspace is ever shared, backed up to an unencrypted location, or copied without sanitization, credentials are exposed.

**Recommendation:**
- Rotate the API token immediately (this review document now also contains it in the readable file).
- Consider using a credential manager or vault instead of plaintext `.env`.
- Add a pre-commit hook that scans for secrets (e.g., `detect-secrets` or `gitleaks`).

---

### C-2: `get_jira_issue` Does NOT Fetch Custom Fields (Including Resolution Path)

**File:** `C:\workarea\jira_manager\src\jira_mcp_server.py` (lines 133-135)

The `get_jira_issue` function explicitly lists which fields to fetch:

```python
data = _jira_get(f"issue/{issue_key}", params={
    "fields": "summary,description,status,priority,assignee,reporter,created,updated,issuetype,project,labels,components,fixVersions,comment,resolution,resolutiondate,issuelinks,attachment",
})
```

This hardcoded field list does NOT include `customfield_12000` (Resolution Path) or any other custom fields. This means:

1. The **content-creator** agent cannot see the current Resolution Path when analyzing a ticket — it has no way to verify what is already written there.
2. The **ticket-manager** agent cannot read-then-verify the Resolution Path after writing to it.
3. The **ticket-analyzer** agent's description says it should "Extract data from the ticket's resolution path" but the underlying API call never retrieves it.
4. Any agent trying to "incorporate all relevant information from the ticket's Resolution Path" (as stated in the content-creator template) is working with incomplete data.

This is the exact same root cause class as the original bug — a gap in the data pipeline that silently produces wrong/incomplete output.

**Recommendation:**
- Either remove the explicit `fields` parameter (to fetch all fields), or add `customfield_12000` (and other known custom fields like `customfield_13981` for Customer Commitment) to the field list.
- After the data is fetched, render the Resolution Path value in the output text (like how comments and linked issues are rendered).
- Add a section like `## Resolution Path` to the formatted output so agents can see what is currently stored.

---

### C-3: `get_jira_issue` Output Does Not Render Custom Fields Even If Fetched

**File:** `C:\workarea\jira_manager\src\jira_mcp_server.py` (lines 141-223)

Even if custom fields were added to the `fields` parameter, the output formatting code (lines 152-222) only renders a fixed set of known fields (summary, status, priority, description, comments, linked issues, attachments). There is zero handling for custom fields in the output. Any custom field data retrieved by the API would be silently discarded.

**Recommendation:**
- Add a `## Custom Fields` section to the output that iterates over any `customfield_*` keys in the response and renders their values.
- At minimum, explicitly render known important custom fields: Resolution Path (`customfield_12000`), Customer Commitment (`customfield_13981`).

---

### C-4: content-creator Agent Has NO Reference to `customfield_12000` or Resolution Path Field

**File:** `C:\workarea\jira_manager\.claude\agents\agent-content-creator.md`

The content-creator agent is described as "self-sufficient" and is responsible for producing the 5-question analysis. However, it has:
- No mention of `customfield_12000`
- No mention of "Resolution Path" as a Jira field
- No instruction to READ the existing Resolution Path before generating analysis
- No instruction to WRITE the analysis back to the Resolution Path field

The template in `C:\workarea\jira_manager\templates\content-creator-five-questions.md` (line 44) mentions "incorporating all relevant information from the ticket's Resolution Path" — but the agent has no way to access that data because `get_jira_issue` does not fetch it (see C-2).

The content-creator generates a markdown file in `output/` but has no connection to actually pushing that content into the Jira ticket's Resolution Path field. This creates a disconnect: analysis is generated locally but never persists to the ticket unless someone manually invokes the ticket-manager as a separate step.

**Recommendation:**
- Add instructions to the content-creator to either (a) call the ticket-manager to write the analysis to `customfield_12000`, or (b) document that a manual second step is required.
- Add the 5-question enforcement language from CLAUDE.md into the content-creator agent so it cannot deviate.

---

## Major (Should Fix)

### M-1: `jira-api-developer` Agent Has Stale Tool List

**File:** `C:\workarea\jira_manager\.claude\agents\agent-jira-api-developer.md` (lines 12-14)

The jira-api-developer agent lists only 3 available MCP tools:
```
- get_jira_issue
- search_jira_issues
- save_to_file
```

But the actual MCP server (`jira_mcp_server.py`) has 6 tools:
1. `search_jira_issues`
2. `get_jira_issue`
3. `create_jira_issue`
4. `update_jira_issue`
5. `copy_jira_issue`
6. `get_custom_fields`

This agent is responsible for maintaining the MCP server. If it does not know 3 of the 6 tools exist, it may inadvertently break them during modifications, or fail to apply necessary changes across all tools.

**Recommendation:**
- Update the agent to list all 6 tools with brief descriptions.
- Consider generating this list programmatically or adding a note to update the agent whenever the server is modified.

---

### M-2: ticket-analyzer Agent Description Contradicts Its Capabilities

**File:** `C:\workarea\jira_manager\.claude\agents\agent-ticket-analyzer.md` (line 3 and line 13)

The YAML frontmatter says:
```
description: "Analyze Jira tickets using the prompt template and generate structured reports"
```

But the body (line 17) says:
```
Return the raw gathered data and findings — do not format it into a final document
```

The description says "generate structured reports" but the instructions say "do not format it into a final document." This is contradictory and could confuse the agent about its role.

Additionally, line 13 says "Extract data from the ticket's description, resolution path, comments, custom fields" — but the underlying `get_jira_issue` API does not return custom fields (see C-2), making this instruction impossible to follow.

**Recommendation:**
- Fix the YAML description to match the actual role: data gathering and raw analysis, not structured report generation.
- Either ensure `get_jira_issue` returns custom fields, or remove the reference to "resolution path" and "custom fields" from this agent's instructions.

---

### M-3: `article_creator.md` Template Is Completely Disconnected from the Project

**File:** `C:\workarea\jira_manager\templates\article_creator.md`

This template defines a Knowledge Base article format with sections: Title, Issue Overview, Cause of the Issue, Troubleshooting Steps Taken, Resolution & Fix, Prevention & Best Practices.

However:
1. No agent references `article_creator.md` by filename.
2. The content-creator agent mentions "Knowledge base articles" as a supported format (line 73) but has no instructions or template for producing them — it only has the embedded 5-question template.
3. The KB article template uses a DIFFERENT structure than the 5-question format (5 sections with different names vs. 5 questions). This creates the same class of inconsistency that caused the original bug.

**Recommendation:**
- Either integrate this template into the content-creator agent with clear instructions on when to use each format (5-question vs. KB article), or remove it to avoid confusion.
- If both formats are needed, add explicit instructions distinguishing when to use each one.

---

### M-4: `save_to_file` Tool Allows Arbitrary Directory Traversal

**File:** `C:\workarea\jira_manager\src\jira_mcp_server.py` (lines 590-611)

The `save_to_file` function accepts an `output_dir` parameter:

```python
if output_dir:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
```

This allows writing files to ANY directory on the filesystem. There is no validation that `output_dir` is within the project directory. An agent (or a prompt injection through ticket content) could potentially write files to arbitrary locations.

The filename sanitization (line 599) only strips non-alphanumeric characters — it does not prevent path traversal in the `output_dir` parameter.

**Recommendation:**
- Validate that `output_dir` resolves to a path within the project root.
- Use `Path.resolve()` and check that it starts with the project root before writing.

---

### M-5: `description` Parameter in `create_jira_issue` and `update_jira_issue` Wraps All Text in a Single Paragraph

**Files:** `C:\workarea\jira_manager\src\jira_mcp_server.py` (lines 299-303, 363-368)

When a description (or Resolution Path content via `custom_fields`) is passed as a plain text string, the `create_jira_issue` and `update_jira_issue` functions convert it to ADF as a single paragraph:

```python
fields["description"] = {
    "type": "doc",
    "version": 1,
    "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
}
```

Multi-paragraph content (like the 5-question analysis with headers and bullet points) will be rendered as a single flat block of text in Jira, losing all formatting. If an agent passes the Resolution Path content through the `description` parameter (or wraps it in ADF the same way via `custom_fields`), the output in Jira will be unreadable.

**Recommendation:**
- Add a helper function to convert multi-line plain text to proper ADF with paragraph breaks.
- Or document clearly that agents must construct their own ADF when passing rich content to `custom_fields`.

---

### M-6: No Error Handling for Missing or Empty `.env` Credentials at Startup

**File:** `C:\workarea\jira_manager\src\jira_mcp_server.py` (lines 17-19)

Credentials are loaded at module level with empty string defaults:

```python
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
```

Each tool function individually checks if credentials are present and returns an error string. But the server starts up successfully with no credentials, and errors are only discovered when a tool is called. The `_jira_headers()` function will happily generate a Base64 token from an empty email and empty API token, leading to confusing 401 errors instead of clear configuration messages.

**Recommendation:**
- Add a startup validation that logs a clear warning if credentials are missing.
- Consider failing fast at startup if the server cannot function without credentials.

---

## Minor (Consider)

### m-1: CLAUDE.md Does Not Reference the `templates/` Directory for KB Articles

**File:** `C:\workarea\jira_manager\CLAUDE.md` (line 40)

The project structure section says:
```
templates/    — Reference templates (content-creator has template embedded)
```

This implies templates are only for reference since the content-creator has its own embedded copy. But there are TWO templates: `content-creator-five-questions.md` (the 5-question format) and `article_creator.md` (KB article format). Neither is referenced by any agent by filename. This creates drift risk: if someone updates the template file but not the embedded copy in the agent, they diverge silently.

**Recommendation:**
- Either have agents reference the template files as the single source of truth, or delete the template files and keep everything embedded in agents.
- Do not maintain two copies of the same content.

---

### m-2: `search_jira_issues` Uses POST to a Non-Standard Endpoint

**File:** `C:\workarea\jira_manager\src\jira_mcp_server.py` (lines 78-86)

The search function uses `POST /rest/api/3/search/jql` instead of the standard `GET /rest/api/3/search`. The code has a comment saying "Use the new /rest/api/3/search/jql endpoint with POST." While this works in Jira Cloud, the standard `GET /rest/api/3/search` endpoint is more widely compatible and documented. The code does not bypass the `_jira_post` helper (it uses raw `requests.post`), creating inconsistency with other API calls.

**Recommendation:**
- Use the `_jira_post` helper for consistency, or document why this endpoint was chosen.

---

### m-3: `.env.example` Uses Different Config Key Than `.env`

**File:** `C:\workarea\jira_manager\.env.example` (line 8) vs `C:\workarea\jira_manager\.env` (line 6)

The `.env.example` has:
```
WEB_UI_BASE_URL=https://your-target-app.example.com
```

The `docs/product-requirements.md` repeatedly references `WEB_UI_TARGET_URL` (not `WEB_UI_BASE_URL`). The actual config code in `src/automation/config.py` uses `WEB_UI_BASE_URL`. This naming inconsistency between documentation and code could confuse developers setting up the project.

**Recommendation:**
- Standardize on one name (`WEB_UI_BASE_URL`) across all documentation.

---

### m-4: No Tests Exist for Any Component

There are no test files anywhere in the project. The `docs/product-requirements.md` specifies ">80% code coverage" (NFR-005) and describes a testing strategy with unit tests, integration tests, and manual tests. None of these exist.

The MCP server has no tests for:
- ADF-to-text conversion edge cases
- Error handling paths
- Custom field handling
- Filename sanitization

**Recommendation:**
- Add unit tests, particularly for `_adf_to_text`, `save_to_file` sanitization, and credential validation.

---

### m-5: `_adf_to_text` Does Not Handle Tables, Media, or Inline Cards

**File:** `C:\workarea\jira_manager\src\jira_mcp_server.py` (lines 226-264)

The ADF-to-text converter handles: text, mentions, hardBreak, paragraph, heading, bulletList, orderedList, codeBlock. It does NOT handle: tables, media, mediaGroup, inlineCard, blockCard, panel, expand, rule, emoji, status, date, or placeholder nodes. These will silently produce empty strings, losing data.

Jira tickets frequently contain tables (especially in Resolution Path fields with troubleshooting steps) and inline cards (links to other issues). This data loss means agents are making decisions on incomplete information.

**Recommendation:**
- Add handling for at least `table`, `tableRow`, `tableCell`, `inlineCard`, and `panel` node types.
- For unhandled types, fall back to recursively processing `content` children (which the code does), but add a log warning so missing types are visible.

---

### m-6: `copy_jira_issue` Has Potential Unbound Variable `data`

**File:** `C:\workarea\jira_manager\src\jira_mcp_server.py` (lines 525-551)

```python
for attempt in range(max_retries):
    try:
        data = _jira_post("issue", {"fields": fields})
        break
    except requests.HTTPError as e:
        ...
        return f"Jira API error: ..."
    except requests.RequestException as e:
        return f"Connection error: {e}"

new_key = data.get("key", "")  # <-- 'data' may be unbound
```

If all 3 retry attempts fail with a 400 error that has parseable `bad_fields`, the loop completes without either (a) breaking with `data` set, or (b) returning an error. In that edge case, `data` would be unbound and line 550 would raise `NameError`.

**Recommendation:**
- Add a fallback after the loop: `else: return "Failed after {max_retries} retries"`.

---

### m-7: Inconsistent Color Labeling in CLAUDE.md Subagents Section

**File:** `C:\workarea\jira_manager\CLAUDE.md` (lines 54, 58-59)

The ticket-manager is labeled `(green)` and the jira-api-developer is also labeled `(green)`. Two agents with the same color defeats the purpose of color-coding for visual differentiation.

---

## Well Done

1. **The 5-question fix in CLAUDE.md and ticket-manager is solid.** The enforcement language ("MUST", "Do NOT rephrase, reorder, or substitute") is clear and unambiguous. The exact questions are spelled out verbatim in both locations.

2. **The content-creator agent has a well-structured embedded template.** The sub-bullet guidance under each question (e.g., "Include the specific error or symptom reported", "State the Root Cause clearly") provides strong guardrails for content quality.

3. **The MCP server code is clean and well-organized.** Helper functions (`_jira_headers`, `_jira_get`, `_jira_post`, `_jira_put`) provide good abstraction. Error handling with `try/except` on HTTP and connection errors is consistent across all tools.

4. **The `copy_jira_issue` retry logic with field stripping is clever.** The approach of removing problematic fields from the Jira error response and retrying is pragmatic and handles real-world Jira API quirks well.

5. **The `save_to_file` filename sanitization strips dangerous characters.** While the `output_dir` parameter needs path validation (see M-4), the filename itself is properly sanitized.

6. **The automation module (`src/automation/`) is well-structured.** Clean separation of concerns between config, browser session lifecycle, and navigation logic. The `BrowserSession` context manager pattern ensures proper resource cleanup.

7. **The sample output (`LAE-43941-five-questions.md`) demonstrates high-quality analysis.** It correctly uses the exact 5-question format with thorough technical detail, showing the template works when properly enforced.

---

## Summary of Findings

| Severity | Count | Key Theme |
|----------|-------|-----------|
| Critical | 4 | Security credential exposure; custom fields not fetched/rendered; content-creator disconnected from Resolution Path |
| Major | 6 | Stale agent docs; disconnected template; directory traversal; ADF formatting loss; missing startup validation |
| Minor | 7 | Duplicate templates; no tests; ADF gaps; unbound variable; naming inconsistencies |

**Root Pattern:** The original bug (wrong 5-question format) was caused by a **broken chain of trust between components**. This review found the same pattern is pervasive:
- Templates exist in `templates/` but are not referenced by agents
- Agents reference capabilities (custom fields, Resolution Path) that the API does not support
- The content-creator generates analysis but has no path to persist it to Jira
- The jira-api-developer agent does not know about half the tools it maintains
- Documentation references config keys that differ from the actual code

The fix applied for the original bug (adding the 5-question template to the ticket-manager) was correct but addressed only ONE link in the broken chain. The other links (API not fetching custom fields, content-creator not reading/writing Resolution Path, template files diverging from embedded copies) remain broken and could produce similar failures.
