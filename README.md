# Relay

A stack-agnostic harness that takes BA stories to reviewed, merged code, with a small team
of people and AI agents working on one feature in parallel.

- Design: [docs/relay-design-local.html](docs/relay-design-local.html) (open in a browser)
- This repo is a Claude Code plugin called `relay`. Skills live in `skills/`.

## The flow

```
/relay-requirements PAY-120     Jira epic      -> requirements/requirement.md
/relay-tasks design.md          design files   -> tasks T01, T02 ... + feature branch + board
/relay-code T02                 one task       -> task branch, tests, code, push, PR
/relay-code --done T02          a person says it is done
```

| Skill | Status | What it does |
| --- | --- | --- |
| `relay-requirements` | ready | Copies a tracker epic and its stories into `requirement.md`, as they are. Resyncs and explains what changed. |
| `relay-tasks` | ready | Cuts design or spec files into small tasks (one repo, one PR, unit tests only). Creates the feature branch after you approve it. Shows the board. |
| `relay-code` | ready | Builds one task: claims it, cuts its branch, learns the repo, writes tests and code, runs the checks, then pushes and opens the PR with what the team already uses. |

## The `_relay` folder

```
_relay/
├── relay.yaml                       team settings (no secrets)
├── repos/
│   └── payments-api.md              how to build, test, code and open PRs in that repo
└── 001-PAY-120-refunds/             one folder per feature
    ├── requirements/requirement.md  from Jira
    ├── design/                      copies of the design files you gave
    └── tasks/
        ├── plan.md                  waves, graph, branches
        ├── status.md  board.html    the board (generated)
        ├── changelog.md             changes found while building
        └── T01-refund-contracts.md  one file per task
```

## Commands

### `/relay-requirements`

| You type | What it does |
| --- | --- |
| `PAY-120` (or a Jira link) | New feature folder `001-PAY-120-<title>` with every story. If it exists, resyncs it. |
| `PAY-120 --name refunds` | Same, with your folder name. |
| `-rs 1` / `-rs PAY-120` / `-rs refund` / `-rs all` | Resync and explain what changed. |
| `--list` | All features. |
| `--doctor` | Check config, env vars and the Jira connection. |

### `/relay-tasks`

| You type | What it does |
| --- | --- |
| `design.md specs/` | Copies the design in, cuts the tasks, checks them, suggests the feature branch. |
| (you say yes to the branch) | Creates `feature/PAY-120-refunds` from the base branch in each repo and pushes it. |
| `--status` | Writes `status.md` and `board.html` and opens the board. |
| `--set T02 in-review` | Moves a task: `todo`, `in-progress`, `in-review`, `done`. |
| `--list` | All features with their task counts. |

Options: `--name <short-name>` (new feature), `--feature <number|epic|name>` (existing one),
`--epic PAY-120`, `--branch-name <name>`, `--no-push`.

### `/relay-code`

| You type | What it does |
| --- | --- |
| `T02` | The whole job in one go: claims it, cuts its branch, codes it with unit tests, runs build, lint and tests, pushes, opens the PR, sets in-review. |
| `T02 -p` | Preview: explains what it will build, which files, which tests, how the PR will be opened. Changes nothing. Waits for your OK. |
| `--done T02` | Marks it done. Done is always set by a person. |
| (nothing) | Tasks you can start now. |

It only stops to ask when the task is blocked or unclear, a check keeps failing, or it
finds no way to open the PR.

The first time a repo is used, relay-code drafts `_relay/repos/<repo>.md` from the repo's
CLAUDE.md, AGENTS.md, CONTRIBUTING.md, README, CI file, build files and tests: the build,
lint and test commands, the coding rules, and how PRs are opened there. It uses the draft
right away and asks you once, at the end, to confirm it.

**Code style.** Give a repo its own style file in `relay.yaml` (`style:`, one file or a
list). Relay always codes and writes tests by it, and it wins over everything else. Without
one, Relay follows the repo's guides and the style of the existing code.

**Relay holds no logins.** It pushes with your own git setup and opens the PR with what the
team already has: the way the profile names, a connected tool (for example an Atlassian,
Bitbucket or GitHub MCP server), or a CLI that is already logged in. If there is none, it
asks you to open the PR and send the link.

## `relay.yaml`

```yaml
team: payments

# The branch you work from. Feature branches are cut from it. Only a person merges back.
base_branch: dev

# Code repos: name: path (relative to the folder that holds _relay/, or absolute).
repos:
  payments-api: ../payments-api
  payments-web:                       # long form
    path: ../payments-web
    style: docs/code-style.md         # the repo's own code style (relative to the repo, or absolute)

branches:
  feature: "feature/{key}-{slug}"     # {key} = epic key, or the feature number
  task: "feature/{key}/{task}-{slug}"

tracker:                              # for relay-requirements
  provider: jira
  mode: rest                          # rest | mcp
  url: ${RELAY_TRACKER_URL}
  email: ${RELAY_TRACKER_EMAIL:-}
  token: ${RELAY_TRACKER_TOKEN}
```

`${VAR}` values come from environment variables. Secrets never go in the file.

## Environment variables

Only relay-requirements needs any, and only in REST mode (in MCP mode it uses the connected
Atlassian server instead):

```sh
export RELAY_TRACKER_URL=https://yourcompany.atlassian.net
export RELAY_TRACKER_EMAIL=you@company.com     # Jira Cloud only
export RELAY_TRACKER_TOKEN=...                 # Jira API token (Cloud) or PAT (Server/DC)
```

## Safety rules

- Relay pushes only branches it created, with your own git login: the feature branch (once,
  after you approve it) and each task's own branch. Never the base branch or main. Never
  force-push.
- Relay never asks for, stores or sets up logins, tokens or tools.
- Task PRs go into the feature branch. Relay never merges anything.
- Relay never resolves merge conflicts and never stashes or discards your changes.
- Done is always set by a person.

## Try it

```sh
cd /path/to/your/code-repo
claude --plugin-dir /path/to/agent-harness
```

Then `/relay:relay-requirements PAY-120`, `/relay:relay-tasks <design>`, `/relay:relay-code`.

Or copy the skill folders into a repo's `.claude/skills/`. `relay-requirements` and
`relay-tasks` work on their own. `relay-code` needs `relay-tasks` next to it.

Every script also works without an agent, for example:

```sh
python3 skills/relay-tasks/scripts/relay_tasks.py --status 1
python3 skills/relay-code/scripts/relay_code.py T02 --preview
python3 skills/relay-code/scripts/relay_code.py --ready
```

## Other trackers

Jira is built in (Cloud and Server/DC, over REST or through an MCP server). Adding another
tracker means adding one folder. See
[skills/relay-requirements/providers/README.md](skills/relay-requirements/providers/README.md).

## Tests

```sh
(cd skills/relay-requirements && python3 -m unittest discover -s tests)
(cd skills/relay-tasks && python3 -m unittest discover -s tests)
(cd skills/relay-code && python3 -m unittest discover -s tests)
```

Standard library only, Python 3.8+. The tests use a fake Jira server and local git repos,
so no account is needed.
