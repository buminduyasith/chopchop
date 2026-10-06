# Providers

A provider connects Relay to one tracker. Everything else (the sync, the story files,
the skill steps) stays the same no matter which tracker you use.

| Provider | Status | Notes |
| --- | --- | --- |
| `jira` | ready | Jira Cloud (REST v3) and Server / Data Center (REST v2). REST or MCP mode. |
| `file` | ready | Normalized JSON files in a folder. For teams with no tracker, demos and tests. |

## Two ways to plug in a tracker

**1. REST (a script).** Add `providers/<name>/provider.py`:

```python
from relaylib.provider_base import Provider, ProviderError
from relaylib.schema import normalize

def create(tracker_cfg):
    return MyProvider(tracker_cfg)

class MyProvider(Provider):
    name = "azure-boards"

    def ping(self):
        return "connected as ..."          # used by `doctor`

    def get_issue(self, key):
        # call the API; raise ProviderError("...", status=404) when missing
        return normalize({...}, self.name)  # shape: SCHEMA.md

    def get_epic_children(self, epic_key):
        return [normalize({...}, self.name) for ... in ...]

    # optional, lets MCP payloads be converted by your code:
    def normalize_raw(self, raw):
        return normalize({...}, self.name)
```

`tracker_cfg` is the `tracker:` block of `relay.yaml` with `${ENV}` values already filled in.
Put provider-specific options under `tracker.<name>:`. Helpers you can use:
`relaylib.http.request_json` (JSON over HTTP with retries) and `relaylib.mdconv`
(Atlassian Document Format and wiki markup to Markdown).

**2. MCP (instructions only).** Add `providers/<name>/MCP.md` that tells the agent which MCP
tools to call and how to map the result to `SCHEMA.md`. The agent writes a JSON file and runs
`relay_req.py ingest`. No Python needed.

A provider can have both files, like `jira/`.

## Where Relay looks for providers

1. `tracker.provider_path` in `relay.yaml` (a folder of your team's own providers)
2. `_relay/providers/<name>/` (shared through the spec repo, no fork of Relay needed)
3. the `providers/` folder that ships with this skill

## Checklist for a new provider

- [ ] `id` and `title` always set. Rich text converted to Markdown.
- [ ] `get_epic_children` excludes sub-tasks and the epic itself.
- [ ] Missing issue raises `ProviderError(status=404)` so the sync can report it as missing.
- [ ] Friendly errors for 401 and 403 that name the env var to check.
- [ ] `relay_req.py doctor` passes.
- [ ] A test in `tests/` with a fake server or saved payloads (see `test_jira.py`).
