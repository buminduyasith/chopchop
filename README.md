# Relay

A stack-agnostic harness that takes BA stories to reviewed, merged code, with a small team
of people and AI agents working on one feature in parallel.

- Design: [docs/relay-design-local.html](docs/relay-design-local.html) (open in a browser)
- This repo is a Claude Code plugin called `relay`. Skills live in `skills/`.

## Skills

| Skill | Status | What it does |
| --- | --- | --- |
| `requirements` | ready | Pulls an epic or a list of stories from the tracker into `_relay/features/<feature>/requirements/`, then analyses them (ACs with stable IDs, open questions). Re-run to sync changes. |

## Try it

1. Load the plugin in a code repo (for this session only):

   ```sh
   cd /path/to/your/code-repo
   claude --plugin-dir /path/to/agent-harness
   ```

2. Set your Jira credentials (never put them in a file):

   ```sh
   export RELAY_TRACKER_URL=https://yourcompany.atlassian.net
   export RELAY_TRACKER_EMAIL=you@company.com      # Jira Cloud only
   export RELAY_TRACKER_TOKEN=...                  # API token (Cloud) or PAT (Server/DC)
   ```

3. In Claude Code:

   ```
   /relay:requirements PAY-120
   /relay:requirements PAY-121,PAY-122 --feature refund-flow
   /relay:requirements --feature PAY-120        # sync again later
   ```

   The first run offers to create `_relay/relay.yaml` and adds `_relay/` to `.gitignore`.

The script also works on its own, without an agent:

```sh
python3 skills/requirements/scripts/relay_req.py doctor
python3 skills/requirements/scripts/relay_req.py pull --epic PAY-120
```

## Other trackers

Jira is built in (Cloud and Server/DC, over REST or through an MCP server). Adding another
tracker means adding one folder. See
[skills/requirements/providers/README.md](skills/requirements/providers/README.md).

## Tests

```sh
cd skills/requirements && python3 -m unittest discover -s tests
```

Standard library only, Python 3.8+. The tests use a fake Jira server, so no account is needed.
