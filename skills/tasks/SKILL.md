---
name: tasks
description: Cut a design or spec (one file, many files or a folder) into small, independent tasks that each fit one PR in one repo, then track them on a board. Use when the user gives design or spec files and asks for tasks, a plan or a work breakdown, asks for the task board or status (--status), or sets a task's status (--set). Writes _chopchop/<NNN-feature>/design/ and tasks/, and creates the feature branch after the user approves it.
argument-hint: "<design files or folder> [--name <short-name> | --feature <ref>] | --status [<ref>] | --set <task> <status>"
---

# Tasks

Turn a design into tasks that people (or agents) can build in parallel. Each task is one
PR in one repo, big enough to matter, small enough to review in one sitting, and tested
with unit tests only.

```
_chopchop/
├── chopchop.yaml
└── 001-PAY-120-refunds/
    ├── requirements/requirement.md   from stories (optional)
    ├── design/                       copies of the files the user gave
    └── tasks/
        ├── plan.md                   waves, graph, branches (script writes)
        ├── status.md                 board as Markdown (script writes)
        ├── board.html                board as a page (script writes)
        ├── changelog.md              changes found while building
        ├── T01-refund-contracts.md   one task (you write it)
        └── T02-refund-api.md
```

A script does everything that must be the same every time: copying, checks, branches,
status and the board. You do the thinking: reading the design and the code, and cutting the
tasks. The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py`. Run it with `python3`
from the user's project folder.

## What the user typed

| User typed | Do this |
| --- | --- |
| files or a folder | Steps 1 to 6 below. |
| `--status [ref]` | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py --status <ref> --open`, then reply with one line per column. |
| `--set T02 in-review` | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py --set T02 in-review --feature <ref>`. Statuses: `todo`, `in-progress`, `in-review`, `done`. |
| `--list` or nothing | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py --list`, then ask what they want. |

`ref` is a feature number (1, 001), an epic key (PAY-120) or part of the folder name. With
only one feature it can be left out.

## 1. Setup (first run only)

If the script says there is no `chopchop.yaml` or no base branch, run `/chopchop:init` first. It asks for the repos, the base branch and code styles in one go. After that,
you never ask again.

## 2. Copy the design in

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py --new <files or folders> --name <short-name>       # new feature
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py --new <files or folders> --feature <ref>           # existing feature
```

Use `--feature` when the work belongs to a feature that already exists (for example one made
by stories). Add `--epic PAY-120` to `--name` when there is an epic but no
requirement yet. If you are not sure which, run `--list` and ask.

If tasks already exist and a design file shows `(changed)`, do not rewrite any task. Tell
the user which files changed and ask what to do.

## 3. Read before you cut

- Every file in `design/`, and `requirements/requirement.md` if it is there.
- The code in each repo (read only): folder layout, where similar features live, how tests
  are written and run. You need real file paths for `touches`, and real test names.
- The repo's code style file, if `chopchop.yaml` sets `repos.<name>.style`. Name files and
  tests the way it says.
- `check.md` in the feature folder, if `/chopchop:check` was run. If its result is "not
  ready", tell the user the open conflicts first and ask whether to cut tasks anyway. If
  there is no check yet, suggest running `/chopchop:check` first.
- If the design is unclear or two parts disagree, stop and ask. Do not guess.

## 4. Cut the tasks

Write one file per task in `tasks/`, named `T01-short-name.md`, using
`${CLAUDE_SKILL_DIR}/templates/task.md` as the shape. Number tasks in wave order.

**Rules for every task**

1. **One repo, one PR.** Never two repos in one task. When the feature crosses repos (api
   and web), each side is its own task. They meet at a contract written in the design: the
   API task builds it, the web task codes against it with a mock.
2. **It has weight.** It delivers something a reviewer can call done by reading its tests.
   A lone DTO, enum or single method is never a task. Fold it into the task that uses it.
   The one exception is a contract that two or more tasks need.
3. **One sitting to review.** Size `S` (about half a day) or `M` (about a day). Roughly 4 to
   12 files and 150 to 500 changed lines, tests included. Anything bigger: split it.
4. **Unit tests only.** `## Done when` names each unit test and what it proves. The tests
   must pass with only this task's dependencies merged. Mock or fake everything else. No
   end-to-end tests in tasks.
5. **Few dependencies.** Use waves:
   - Wave 0: contracts. One task per repo with all the shared types, interfaces, schemas,
     migrations and stubs that others code against. Small, so it merges first.
   - Wave 1: slices. Each depends only on wave 0. They all run in parallel.
   - Wave 2: wiring, only when something must join the slices. Usually none.
   A task may only depend on an earlier wave. No chains inside a wave.
6. **No clashes.** Two tasks in the same wave and repo may not touch the same file. List
   every file or folder in `touches` (globs are fine).
7. **It stands alone.** `## Context` quotes the parts of the design it needs, word for word,
   with where they come from. A builder reads one task file and the code, nothing else.
8. **Say what not to change.** Contracts from wave 0, shared files, other tasks' areas.

Leave `## Branch` as it is in the template. The script fills it in.

## 5. Check

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py --check <ref>
```

Fix every error and run it again until the result is OK. Fix warnings too, unless you have
a reason. Then say the reason in the reply.

## 6. Show the plan and the branch

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py --branch <ref>
```

Reply with:

1. One line: how many tasks, waves and repos.
2. A short table: task, title, repo, wave, size, depends on.
3. Questions you still have about the design, if any.
4. The branch it suggests, for example "`feature/PAY-120-refunds` from `dev` in payments-api
   and payments-web. Create it?"

Only when the user says yes:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_tasks.py --branch <ref> --create
```

That creates the branch in each repo, pushes it, and writes the exact branch commands into
every task file. If the user wants another name, pass `--branch-name <name>`. Then run
`--status <ref> --open` so they see the board.

## Safety rules

- Only push the new feature branch chopchop just created. Never push to the base branch, main,
  or any branch that already exists. Never merge, never force-push, never check out.
- Task PRs go into the feature branch. Only a person merges anything.
- Never edit `plan.md` (except its `## Notes`), `status.md`, `board.html` or any `## Branch`
  section by hand. The script rewrites them.
- Change a status only with `--set`.
- `changelog.md` is for changes found while building. Add entries in the format at the top
  of the file. Never delete old entries.
- If `_chopchop/style.md` exists, follow it.
