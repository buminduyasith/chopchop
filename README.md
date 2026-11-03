# chopchop

A Claude Code plugin that cuts big features into small, bite-size tasks and builds each one
end to end. A small team of people and AI agents can work on one feature in parallel, and
every PR stays small enough for a person to review in one sitting.

```
stories  ->  check the design  ->  tasks (one repo, one PR each)  ->  code, unit tests, PR  ->  a person merges
```

chopchop holds no logins and talks to no tracker or git host by itself. It uses what your
team already has in the session: a connected tool (an MCP server), a CLI that is already
logged in, or a file you give it. If there is nothing, it asks you.

## Install

In Claude Code:

```
/plugin marketplace add buminduyasith/chopchop
/plugin install chopchop@chopchop
```

From a shell: `claude plugin marketplace add buminduyasith/chopchop`, then
`claude plugin install chopchop@chopchop`. Add `--scope project` to share it with everyone
who opens a repo.

## Quick start

| Step | Command | Who | How often |
| --- | --- | --- | --- |
| 1. Set up | `/chopchop:init` | one person | once per team |
| 2. Stories | `/chopchop:stories PAY-120` | lead | per epic (optional) |
| 3. Check | `/chopchop:check 1 --design docs/design.md` | lead | per design change |
| 4. Tasks | `/chopchop:tasks docs/design.md` | lead | per feature |
| 5. Board | `/chopchop:tasks --status` | anyone | any time |
| 6. Build | `/chopchop:code T02` | developer | per task |
| 7. Done | `/chopchop:code --done T02` | developer | per task |

1. **`/chopchop:init`** looks at your repos and asks a few questions, with click options:
   - where to keep its files
   - the base branch you work from
   - which repos the team works in
   - each repo's code style: use the style file it found, write one from the code, or none

   It writes `_chopchop/chopchop.yaml` and can also learn each repo's build, test and PR
   steps.
2. **`/chopchop:stories PAY-120`** copies an epic and its stories, as they are, into
   `requirement.md`, from whatever tracker tool you have. Run `-rs 1` later to see what
   changed.
3. **`/chopchop:check 1 --design docs/design.md`** compares the design with the
   requirements and lists conflicts, gaps, extras and questions, with quotes from both sides
   and a coverage table. `/chopchop:check --req <files> --design <files>` works on any
   files, with no feature.
4. **`/chopchop:tasks <design files or folder>`** copies the design in and cuts it into small
   tasks in waves: contracts first, then slices that run in parallel. It checks them and
   suggests a feature branch. Say yes, and it creates and pushes the branch.
5. **`/chopchop:code T02`** does one task in one go: claims it, cuts its branch, writes the
   unit tests and code in the repo's style, runs build, lint and tests, pushes, opens the PR
   your team's usual way, and sets it to in-review. `T02 -p` only previews the plan.
6. **`/chopchop:code --done T02`**: a person marks it done after the merge.

## Commands

### `/chopchop:init`

| You type | What it does |
| --- | --- |
| (nothing) | Asks where to keep the files, the base branch, the repos, and each repo's code style. Writes `chopchop.yaml`. Offers to learn each repo's build, test and PR steps. |

Run it again any time. It keeps what you did not change and saves `chopchop.yaml.bak`.

### `/chopchop:stories`

| You type | What it does |
| --- | --- |
| `PAY-120` (or a link) | Gets the epic and its stories with your existing tool, and writes `NNN-PAY-120-<title>/requirements/requirement.md`. If the epic already has a folder, it updates it and explains what changed. |
| `PAY-120 --name refunds` | Same, with your own folder name. |
| `-rs 1` / `-rs PAY-120` / `-rs all` | Fetches again and explains what changed. |
| `--list` | All features. |

### `/chopchop:tasks`

| You type | What it does |
| --- | --- |
| `design.md specs/` | Copies the design in, cuts the tasks, checks them, suggests the feature branch. On your yes, creates and pushes it in each repo. |
| `--status` | Writes `status.md` and `board.html`, and opens the board. |
| `--set T02 in-review` | Moves a task: `todo`, `in-progress`, `in-review`, `done`. |
| `--list` | All features with their task counts. |

Every task fits one repo and one PR, can be tested with unit tests alone, and depends only
on an earlier wave. A script checks this every time.

### `/chopchop:check`

| You type | What it does |
| --- | --- |
| (nothing) or a feature (`1`, `PAY-120`) | Compares the feature's `requirement.md` with its `design/` and writes `check.md`. |
| `1 --design new-spec.md` | The feature's requirements against another design file. |
| `--req brief.md stories/ --design design.md` | Any requirement and design files, no feature needed. |

Each finding is a **conflict** (both cannot be true), **missing** (a requirement with no
design), **extra** (design nobody asked for) or **question** (unclear), with a severity,
quotes from both sides, a fix and who to ask. Every story and acceptance criterion gets a
stable id (`PAY-121.AC2`), and a re-check shows what was fixed and what is new.
`/chopchop:tasks` warns you when the last check was not ready.

### `/chopchop:code`

| You type | What it does |
| --- | --- |
| `T02` | The whole job in one go, up to an open PR. |
| `T02 -p` | Preview: what it will build, which files and tests, which style, how the PR will be opened. Changes nothing. |
| `--done T02` | Marks it done. Done is always set by a person. |
| (nothing) | Tasks you can start now. |

It stops to ask only when a task is blocked or unclear, a check keeps failing, or it finds
no way to open the PR.

## How it codes

In this order, the first one wins:

1. The repo's own **style file(s)** from `chopchop.yaml` (`style:`).
2. The repo's guides: `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`.
3. The repo **profile** (`_chopchop/repos/<repo>.md`), drafted from the code, CI and build
   files the first time, then confirmed once by a person.
4. The existing code nearby.

## The `_chopchop` folder

```
_chopchop/
├── chopchop.yaml                    team settings (no secrets), written by /chopchop:init
├── styles/payments-web.md           a code style written from the code (optional)
├── repos/payments-api.md            how to build, test and open PRs in that repo
└── 001-PAY-120-refunds/             one folder per feature
    ├── requirements/requirement.md  the epic and its stories
    ├── design/                      copies of the design files you gave
    ├── check.md                     design vs requirements (from /chopchop:check)
    └── tasks/
        ├── plan.md                  waves, graph, branches
        ├── status.md  board.html    the board (generated)
        ├── changelog.md             changes found while building
        └── T01-refund-contracts.md  one file per task
```

## `chopchop.yaml`

```yaml
team: payments
base_branch: dev                      # feature branches are cut from it; only people merge back

repos:                                # path is relative to the folder that holds _chopchop/
  payments-api:
    path: ../payments-api
    style: docs/code-style.md         # relative to the repo, to _chopchop/, or absolute; a list works too
  payments-web: ../payments-web       # no style: follows the existing code

branches:
  feature: "feature/{key}-{slug}"     # {key} = epic key, or the feature number
  task: "feature/{key}/{task}-{slug}"
```

## Safety rules

- It pushes only branches it created, with your own git login: the feature branch (once,
  after you say yes) and each task's own branch. Never the base branch or main. Never
  force-push.
- Task PRs go into the feature branch. It never merges anything.
- It never resolves merge conflicts and never stashes or discards your changes.
- It never asks for, stores or sets up logins, tokens or tools.
- Done is always set by a person.

## Without the plugin

Copy the folders in `skills/` into a repo's `.claude/skills/`. `stories` and `tasks` work on
their own. `check`, `code` and `init` need `tasks` next to them. Every script also runs without an
agent, for example:

```sh
python3 skills/init/scripts/relay_init.py --detect
python3 skills/tasks/scripts/relay_tasks.py --status 1
python3 skills/code/scripts/relay_code.py T02 --preview
```

## Develop

```sh
claude --plugin-dir .                 # try local changes; /reload-plugins after each edit
claude plugin validate . --strict
(cd skills/stories && python3 -m unittest discover -s tests)
(cd skills/tasks && python3 -m unittest discover -s tests)
(cd skills/code && python3 -m unittest discover -s tests)
(cd skills/init && python3 -m unittest discover -s tests)
(cd skills/check && python3 -m unittest discover -s tests)
```

Standard library only, Python 3.8+. The tests use local git repos, so no account is needed.
To release, bump `version` in `.claude-plugin/plugin.json`: installed copies update only when
it changes.

## License

MIT. See [LICENSE](LICENSE).
