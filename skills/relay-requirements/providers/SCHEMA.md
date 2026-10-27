# Normalized issue

Every provider returns issues in this shape. The sync, requirement.md and every later
Relay skill only ever see this shape, never the tracker's own format. All text fields are
Markdown.

```json
{
  "id": "PAY-121",                      // required, the tracker's key
  "provider": "jira",
  "url": "https://acme.atlassian.net/browse/PAY-121",
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
