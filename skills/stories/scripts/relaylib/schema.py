"""The normalized issue shape shared by every provider. Documented in providers/SCHEMA.md."""

# Fields that describe WHAT to build. A change here means the story must be re-analysed.
CONTENT_FIELDS = ("title", "type", "description", "acceptance_criteria", "extra", "attachments")
# Fields that describe the ticket's state. Updated silently, listed in the report.
META_FIELDS = ("status", "priority", "assignee", "labels", "components", "fix_versions",
               "story_points", "parent", "subtasks", "links")

DEFAULTS = {
    "id": None,
    "provider": None,
    "url": None,
    "type": None,
    "title": "",
    "status": None,
    "priority": None,
    "assignee": None,
    "reporter": None,
    "labels": [],
    "components": [],
    "fix_versions": [],
    "story_points": None,
    "parent": None,
    "created": None,
    "updated": None,
    "description": "",
    "acceptance_criteria": None,
    "subtasks": [],
    "links": [],
    "attachments": [],
    "comments": [],
    "extra": {},
}


def normalize(issue, provider=None):
    """Fill defaults and check the minimum. Returns a new dict."""
    if not isinstance(issue, dict):
        raise ValueError("an issue must be an object, got %r" % type(issue).__name__)
    out = {}
    for key, default in DEFAULTS.items():
        value = issue.get(key, default)
        if value is None and isinstance(default, (list, dict)):
            value = type(default)()
        out[key] = value
    if not out["id"]:
        raise ValueError("an issue is missing 'id': %r" % (issue.get("title") or issue)[:80])
    out["id"] = str(out["id"]).strip()
    out["title"] = (out["title"] or "").strip()
    out["description"] = out["description"] or ""
    if provider and not out["provider"]:
        out["provider"] = provider
    return out
