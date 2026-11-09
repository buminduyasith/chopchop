# chopchop

A Claude Code plugin that cuts big features into small, bite-size tasks and builds each one
end to end. A small team of people and AI agents can work on one feature in parallel, and
every PR stays small enough for a person to review in one sitting.

```
learn the system  ->  stories  ->  design (a lead approves)  ->  spec  ->  tasks (one repo, one PR each)  ->  code, unit tests, PR  ->  prove  ->  done
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

### Update

No need to remove and install again:

```
/chopchop:update              get the latest version, then run /reload-plugins
/chopchop:update --auto on    let Claude Code update chopchop by itself from now on
```

Auto-update is off by default for marketplaces that are not official. With it on, Claude
Code checks in the background and tells you when a new version is ready. Without the
plugin's own command: `claude plugin marketplace update chopchop`, then
`claude plugin update chopchop@chopchop`.

## Quick start

| Step | Command | Who | How often |
| --- | --- | --- | --- |
| 1. Set up | `/chopchop:init` | one person | once per team |
| 2. Learn | `/chopchop:learn` | one person | once, then it refreshes itself |
| 3. Stories | `/chopchop:stories PAY-120` | lead | per epic (optional) |
| 4. Design | `/chopchop:design refunds for card payments` | developer | per feature |
| 5. Approve | `/chopchop:design --approve "Asha"` | developer, after the review | per feature |
| 6. Spec | `/chopchop:spec 1` | developer | per feature |
| 7. Check | `/chopchop:check 1` | lead | per design or spec change |
| 8. Tasks | `/chopchop:tasks 1` | lead | per feature |
| 9. Board | `/chopchop:tasks --status` | anyone | any time |
| 10. Build | `/chopchop:code T02` | developer | per task |
| 11. Task done | `/chopchop:code --done T02` | developer | per task |
| 12. Feature done | `/chopchop:spec --done --by "Asha"` | lead | per feature |
| Update | `/chopchop:update` | everyone | when a new version is out |

1. **`/chopchop:init`** looks at your repos and asks a few questions, with click options:
   - where to keep its files
   - the base branch you work from
   - which repos the team works in
   - each repo's code style: use the style file it found, write one from the code, or none

   - how many helpers (subagents) chopchop may run at once, with which model and effort

   It writes `_chopchop/chopchop.yaml` and can also map the system and learn each repo's
   build, test and PR steps.
2. **`/chopchop:learn`** maps every repo: APIs, events, tables, outside systems, owners from
   CODEOWNERS, the patterns each repo follows, and how they connect. Later runs read only
   what git diff says changed.
3. **`/chopchop:stories PAY-120`** copies an epic and its stories, as they are, into
   `requirement.md`, from whatever tracker tool you have. Run `-rs 1` later to see what
   changed.
4. **`/chopchop:design <idea>`** asks at most 2 short rounds of questions, with answers to
   pick, and writes a short design a lead can approve: a high-level design of the parts and a
   main flow of the steps,
   the real choices kept in `options.md`, failure answers for every arrow, and a citation of
   the code for every claim. It also writes `feature.html`: the design, the choices, slides
   with speaker notes, and a review message to paste into chat. `--auto` asks nothing.
5. **`/chopchop:spec 1`** turns the approved design into the full plan to build it, in
   simple English with no length cap: the rules with examples, every file per repo, the real
   code to copy, the existing methods to reuse, a sketch of the new code in the repo's own
   style, every unit test by name, the end-to-end journeys, and work packages. It checks all
   of it against the code, and tracks each test from planned to built to proved.
6. **`/chopchop:check 1`** compares the design with the
   requirements and lists conflicts, gaps, extras and questions, with quotes from both sides
   and a coverage table. `/chopchop:check --req <files> --design <files>` works on any
   files, with no feature.
7. **`/chopchop:tasks 1`** cuts the spec into tasks, one per work package, in waves:
   contracts first, then slices that run in parallel, then one prove task per end-to-end
   journey. Each task carries its rules, contract, code to copy and test names. It suggests
   a feature branch. Say yes, and it creates and pushes the branch. It also takes design or
   spec files you hand it: `/chopchop:tasks <files or folder>`.
8. **`/chopchop:code T02`** does one task in one go: claims it, cuts its branch, writes the
   unit tests and code in the repo's style, runs build, lint and tests, pushes, opens the PR
   your team's usual way, and sets it to in-review. `T02 -p` only previews the plan.
9. **`/chopchop:code --done T02`**: a person marks it done after the merge.
10. **`/chopchop:spec --done --by "Asha"`**: a person sets the whole feature to done, only
    when every test, journey and manual check is proved.

## Commands

### `/chopchop:init`

| You type | What it does |
| --- | --- |
| (nothing) | Asks where to keep the files, the base branch, the repos, each repo's code style, and the helper settings. Writes `chopchop.yaml`. Offers to map the system and learn each repo's build, test and PR steps. |

Run it again any time. It keeps what you did not change and saves `chopchop.yaml.bak`.

### `/chopchop:learn`

| You type | What it does |
| --- | --- |
| (nothing) | Maps every new or changed repo with one explorer each, and writes `_chopchop/system/system-map.json` and `system-map.md`. |
| `payments-api web-app` | Only those repos. |

People can fix an entry in the JSON and mark it `"source": "person"`. chopchop never
overwrites it. `/chopchop:design` refreshes the map by itself before it designs.

### `/chopchop:design`

| You type | What it does |
| --- | --- |
| an idea, a file, or a pasted image | Learns the area, asks round 1 (intent), reads the code with helpers, writes `options.md`, asks round 2 (your picks), then draws the high-level design and the main flow (the diagram skill) and writes `design.md` and `feature.html`. |
| the same, with `--auto` | No questions. Every pick it makes is listed as an assumption for the lead. |
| (nothing) | Goes on from where it stopped. |
| `"the lead's notes"` | When a design exists: changes it from the feedback and says what changed. |
| `--pick 2=B` | Changes one choice in `options.md` and rewrites the design. No new research. |
| `--approve "Asha"` | Records approved, approved with conditions, or changes needed. A person decides. |
| `--open` | Opens `feature.html`. |

`design.md` has 12 fixed sections, always in the same order, for a 10 minute read. A build
step checks it: every story is in scope or out of scope, every message on the main flow
answers what happens when it fails, is slow, runs twice or gets the wrong caller, every
citation still matches the code, and the English stays plain. Missing helper settings are
asked once, the first time, so there is no need to run init again.

### `/chopchop:spec`

| You type | What it does |
| --- | --- |
| (nothing) or a feature | Reads the code in each repo, asks only what the code cannot answer, writes `spec.md` and `spec.json`, checks them against the code and adds a Spec tab to `feature.html`. |
| the same, with `--auto` | No questions. Every guess is listed as an assumption. |
| `--status` | What is planned, built (its task is merged) and proved (its checks passed). |
| `--sign M1 --by "Asha"` | A person signs a manual check. |
| `--done --by "Asha"` | A person sets the feature to done, when everything is proved. |

`spec.md` has 21 sections in 4 parts: Understand (anyone, 10 minutes), Build, Prove, and Ship
and track. Each section starts with an "In short" line. Code in the spec comes from the repo:
every piece of code to copy is cited and checked, every reused method must exist where it is
cited, new files go next to similar files, and test names follow the repo's own naming.

### `/chopchop:diagram`

Design uses it for its two pictures, and you can run it on its own to draw or fix one.

| Picture | Shows | Looks like |
| --- | --- | --- |
| High-level design (`architecture.json`) | the parts, the repo each lives in, what talks to what | boxes grouped by repo, labeled lines, no numbers |
| Main flow (`flow.json`) | the steps in time order, the error paths, a failure answer per step | a sequence: lanes, numbered arrows, dashed replies |

You (or Claude) place each part on a grid. A script checks it (no line through a box, no part
inside another repo's group, no step numbers on the structure), draws a clean picture for
`feature.html` and writes the Mermaid copy for `design.md`.

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

### `/chopchop:update`

| You type | What it does |
| --- | --- |
| (nothing) | Refreshes the chopchop marketplace and updates chopchop in every scope it is installed in. Then run `/reload-plugins`. |
| `--check` | Shows the installed version and whether auto-update is on. |
| `--auto on` / `--auto off` | Turns Claude Code's auto-update for chopchop on or off (asks first, since it changes your Claude settings). |

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
├── team-decisions.md                decisions every feature follows (optional)
├── system/system-map.json  .md      the whole system, from /chopchop:learn
├── styles/payments-web.md           a code style written from the code (optional)
├── repos/payments-api.md            how to build, test and open PRs in that repo
└── 001-PAY-120-refunds/             one folder per feature
    ├── requirements/requirement.md  the epic and its stories
    ├── design/                      design.md, options.md, architecture.json, flow.json
    ├── spec/                        spec.md (for people) and spec.json (the facts tasks are cut from)
    ├── work/                        answers, helper reports, approved copies, test results
    ├── feature.html                 the page: design, choices, spec, slides, review message
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

agents:                               # helpers (subagents); asked once
  max: 3                              # most at the same time; 0 = none. A small job uses fewer
  model: inherit                      # inherit, sonnet, opus, haiku or fable
  effort: inherit                     # inherit, low, medium, high, xhigh or max
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

Copy the folders in `skills/` into a repo's `.claude/skills/`, and `agents/` into
`.claude/agents/` (`update` is only for the plugin). `stories` and `tasks` work on their own.
`check`, `code`, `init`, `learn`, `diagram`, `design` and `spec` need `tasks` next to them. `design` also needs `diagram`. Every script also runs
without an agent, for example:

```sh
python3 skills/init/scripts/chopchop_init.py --detect
python3 skills/tasks/scripts/chopchop_tasks.py --status 1
python3 skills/code/scripts/chopchop_code.py T02 --preview
python3 skills/design/scripts/chopchop_design.py --build 1
```

## Try it on the sample

```sh
python3 evals/sample-project/setup.py --to /tmp/refunds
cd /tmp/refunds && claude
```

Then run `/chopchop:learn` and `/chopchop:design refunds for card payments`. The sample has 4
small repos and a few traps: two error styles, a ledger service nobody mentions, and code that
changed after it was cited.

## Develop

```sh
claude --plugin-dir .                 # try local changes; /reload-plugins after each edit
claude plugin validate . --strict
(cd skills/stories && python3 -m unittest discover -s tests)
(cd skills/tasks && python3 -m unittest discover -s tests)
(cd skills/code && python3 -m unittest discover -s tests)
(cd skills/init && python3 -m unittest discover -s tests)
(cd skills/check && python3 -m unittest discover -s tests)
(cd skills/update && python3 -m unittest discover -s tests)
(cd skills/learn && python3 -m unittest discover -s tests)
(cd skills/design && python3 -m unittest discover -s tests)
(cd skills/diagram && python3 -m unittest discover -s tests)
(cd skills/spec && python3 -m unittest discover -s tests)
claude plugin eval . --scaffold       # agent evals on the sample project (slow: real runs)
```

Standard library only, Python 3.8+. The tests use local git repos, so no account is needed.
To release, bump `version` in `.claude-plugin/plugin.json`: installed copies update only when
it changes.

## License

MIT. See [LICENSE](LICENSE).
