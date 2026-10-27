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

0. **Which epic?** For a new feature the user gives the epic key. For `-rs <ref>`, get it with
   `python3 scripts/relay_req.py --resolve <ref>` (prints the feature's `epic`). For `-rs all`,
   use `--list --json` and repeat these steps for each feature.
1. **Epic.** Get the epic issue with all fields and field names:
   `fields: ["*all"]`, `expand: "names"` (or the closest options the tool offers).
2. **Children.** Search with this JQL (Cloud). Ask for all fields again and page until done:
   `parent = <EPIC> AND issuetype not in subTaskIssueTypes() ORDER BY rank`
   On Jira Server / Data Center use `"Epic Link" = <EPIC>` instead of `parent = <EPIC>`.
3. **Save** the raw payloads, exactly as the tool returned them, to a temp file:

   ```json
   {
     "epic":   { ...raw epic issue... },
     "issues": [ { ...raw issue... }, { ... } ]
   }
   ```

   Each raw issue must have `key` and `fields`. Keep `names` if the tool returned it, since
   that is how the provider finds custom fields such as "Acceptance Criteria" by name.
   `issues` must hold **every** child of the epic. A story that is missing is reported as
   removed.
4. **Ingest:**

   ```
   python3 scripts/relay_req.py --ingest <file>
   ```

   It finds the feature by the epic key (or creates it, add `--name` for your own folder
   name) and prints the same report as a REST sync.

## If the payload is not raw Jira JSON

Some MCP tools return Markdown or a trimmed object instead of the REST shape. Then build
normalized issues yourself (see `../SCHEMA.md`), convert rich text to Markdown, and run
`--ingest <file> --format normalized`. Keep descriptions complete. Do not summarise them.
