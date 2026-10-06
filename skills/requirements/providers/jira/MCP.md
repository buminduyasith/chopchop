# Jira through MCP

Use this when `tracker.mode: mcp` in `relay.yaml`, or when REST auth fails and an
Atlassian MCP server is connected in this session.

Tool names differ between MCP servers. Look for tools that:

- list your Atlassian sites (to get the `cloudId`), e.g. `getAccessibleAtlassianResources`
- get one issue, e.g. `getJiraIssue`
- search with JQL, e.g. `searchJiraIssuesUsingJql`

If the server needs authentication first, run its authenticate tool and ask the user to
finish the login.

## Steps

1. **Epic.** Get the epic issue with all fields and field names:
   `fields: ["*all"]`, `expand: "names"` (or the closest options the tool offers).
2. **Children.** Search with this JQL (Cloud). Ask for all fields again and page until done:
   `parent = <EPIC> AND issuetype not in subTaskIssueTypes() ORDER BY rank`
   On Jira Server / Data Center use `"Epic Link" = <EPIC>` instead of `parent = <EPIC>`.
3. **Extra stories by id.** Get each one like the epic.
4. **Save** the raw payloads, exactly as the tool returned them, to a temp file:

   ```json
   {
     "epic":   { ...raw epic issue... },
     "issues": [ { ...raw issue... }, { ... } ]
   }
   ```

   Each raw issue must have `key` and `fields`. Keep `names` if the tool returned it, since
   that is how the provider finds custom fields such as "Acceptance Criteria" by name.
5. **Ingest:**

   ```
   python3 scripts/relay_req.py ingest --input <file> --format raw --epic <EPIC> --full
   ```

   - Drop `--full` if you did not fetch every child (removal detection needs the full list).
   - Add `--stories A,B` for stories that were asked for by id.
   - Add `--missing X` for ids the tool could not find.
   - For a story list with no epic: `--feature <name>` instead of `--epic`.

## If the payload is not raw Jira JSON

Some MCP tools return Markdown or a trimmed object instead of the REST shape. Then build
normalized issues yourself (see `../SCHEMA.md`), convert rich text to Markdown, and run
`ingest --format normalized`. Keep descriptions complete. Do not summarise them.
