# Stories JSON

Get the epic and its stories with whatever the team already uses (a connected tool, a CLI,
an export or text the user pastes), then write them in this shape and run
`chopchop_stories.py --ingest <file>`. The script and every later skill only ever see this shape,
never a tracker's own format. All text fields are Markdown.

```json
{"epic": {"id": "PAY-120", "title": "Refunds for customers", "description": "..."},
 "stories": [{"id": "PAY-121", "title": "Customer can request a refund", "acceptance_criteria": "..."}]}
```

Keep the stories in the tracker's order. Copy the text as it is: do not summarise or fix it.

## One story (or the epic)

```json
{
  "id": "PAY-121",                      // required, the tracker's id
  "provider": "tracker-mcp",            // where it came from: the tool or CLI you used (free text)
  "url": "https://tracker.example.com/browse/PAY-121",
  "type": "Story",
  "title": "Customer can request a refund",   // required
  "status": "Ready for Dev",
  "priority": "High",
  "assignee": "A. Perera",              // display name or null
  "reporter": "B. Silva",
  "labels": ["payments"],
  "components": ["refunds"],
  "fix_versions": ["2026.10"],
  "story_points": 5,                    // number or null
  "parent": "PAY-120",                  // epic / parent id or null
  "created": "2026-09-10T09:00:00.000+0530",
  "updated": "2026-09-23T10:02:11.000+0530",
  "description": "Markdown text",
  "acceptance_criteria": "Markdown, or null when the tracker has no separate field",
  "subtasks":    [{"id": "PAY-140", "title": "...", "status": "Done"}],
  "links":       [{"relation": "is blocked by", "id": "PAY-99", "title": "...", "status": "To Do"}],
  "attachments": [{"name": "flow.png", "url": "https://...", "mime": "image/png", "size": 48213}],
  "comments":    [{"author": "B. Silva", "created": "2026-09-17T12:40:00.000+0530", "body": "Markdown"}],
  "extra":       {"Business Value": "Markdown or plain value"}
}
```

Missing keys are filled with defaults (`null`, `""`, `[]` or `{}`), so a minimal issue is
`{"id": "X-1", "title": "..."}`.

## What counts as a change

| Group | Fields | Effect on re-sync |
| --- | --- | --- |
| Content | title, type, description, acceptance_criteria, extra, attachment names, comments | reported as **Changed**, naming the parts that changed |
| Meta | status, priority, assignee, labels, components, fix_versions, story_points, subtasks, links | reported as **Status** (with old and new status) or **Details**, not a requirement change |
