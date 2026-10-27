# Relay

A stack-agnostic harness that takes BA stories to reviewed, merged code, with a small team
of people and AI agents working on one feature in parallel.

- Design: [docs/relay-design-local.html](docs/relay-design-local.html) (open in a browser)
- This repo is a Claude Code plugin called `relay`. Skills live in `skills/`.

## Skills

| Skill | Status | What it does |
| --- | --- | --- |
| `relay-requirements` | ready | Syncs a tracker epic into `_relay/<NNN-EPIC-name>/requirements/requirement.md`, every story as it is. `-rs` resyncs and reports what changed. |
| `relay-tasks` | ready | Cuts design or spec files into small tasks (one repo, one PR, unit tests only), creates the feature branch after you approve it, and shows a board. `--status` opens the board, `--set` moves a task. |

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
   /relay:relay-requirements PAY-120    # new feature 001-PAY-120-<epic-title>
   /relay:relay-requirements -rs 1      # resync it (or -rs PAY-120, -rs refund, -rs all)
   /relay:relay-requirements --list     # all features

   /relay:relay-tasks docs/refund-design.md specs/   # cut tasks from a design (files or folders)
   /relay:relay-tasks --status                       # open the board
   /relay:relay-tasks --set T02 in-review            # todo | in-progress | in-review | done
   ```

   Or copy `skills/relay-requirements/` (or `skills/relay-tasks/`) into a repo's
   `.claude/skills/` and use `/relay-requirements PAY-120` there. Each folder has everything
   its skill needs.

   The first run offers to create `_relay/relay.yaml` and adds `_relay/` to `.gitignore`.

   ```
   _relay/
   ├── relay.yaml                     base branch, repos, tracker
   └── 001-PAY-120-refunds/
       ├── requirements/requirement.md
       ├── design/                    copies of the design files you gave
       └── tasks/
           ├── plan.md  status.md  board.html  changelog.md
           ├── T01-refund-contracts.md
           └── T02-refund-api.md
   ```

   One folder per feature, one subfolder per stage, so a number always means one feature.

The script also works on its own, without an agent:

```sh
python3 skills/relay-requirements/scripts/relay_req.py --doctor
python3 skills/relay-requirements/scripts/relay_req.py PAY-120
python3 skills/relay-requirements/scripts/relay_req.py -rs 1
```

## Other trackers

Jira is built in (Cloud and Server/DC, over REST or through an MCP server). Adding another
tracker means adding one folder. See
[skills/relay-requirements/providers/README.md](skills/relay-requirements/providers/README.md).

## Tests

```sh
(cd skills/relay-requirements && python3 -m unittest discover -s tests)
(cd skills/relay-tasks && python3 -m unittest discover -s tests)
```

Standard library only, Python 3.8+. The tests use a fake Jira server, so no account is needed.
