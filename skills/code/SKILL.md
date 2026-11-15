---
name: code
description: Build one chopchop task end to end in one go. Claim it, cut its branch from the feature branch, learn how the repo codes and tests, write the unit tests and code, run all the checks, push, and open a PR into the feature branch with the tools the team already uses. Use when the user gives a task id (T02) or asks to build, code or implement a task; --done marks a task done. Also use to fix review comments on a task's PR, or when the user asks what to work on next.
argument-hint: "<task-id> | --done <task-id>"
---

# Code

Take one task file from `_chopchop/<feature>/tasks/` and turn it into an open PR in one repo.

## What the user types

| User types | What happens |
| --- | --- |
| `T02` | The whole job, in one go: look, start, code, unit tests, checks, push, PR. |
| `--done T02` | Mark it done: `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_code.py --done T02`. |
| nothing | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_code.py --ready`, then ask which task. |

That is all the user needs. Everything below is steps you run yourself. There is no preview
to offer: the dashboard (`/chopchop:dashboard`) shows every task, its file and where it stands.

To build every task of a feature one by one, each reviewed before its commit, the user runs
`/chopchop:auto`. To review pending changes in any repo, `/chopchop:review`.

For `T02`, do not stop between steps. Stop and ask only when:
- the look step shows a `Blocked:` line
- the task is unclear or conflicts with the code
- the same check still fails after three tries
- there is no way to open the PR (step 7)

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_code.py`. Run it with `python3` from the
user's project folder. This skill needs the `tasks` skill folder next to it. If there is
no `chopchop.yaml` yet, run `/chopchop:init` first. Add `--feature <ref>` when the script
says the task id is in more than one feature.

## 1. Look

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_code.py T02 --preview
```

This is your own first step, not something to offer the user. It changes nothing: it prints
everything about the task, the repo, the branch and the profile. Read all of it. For a
`Blocked:` line, stop and tell the user the fix in one line:

- Waiting on another task: ask if they want to build against its contract now. If yes,
  add `--force` in step 4.
- Owned by someone else: ask before taking it over. If yes, add `--take` in step 4.
- Uncommitted changes in the repo: ask them to commit or stash. Never do it for them.
- No feature branch: they need `/chopchop:tasks --branch` first.

## 2. Learn the repo

How to code, in this order. The first one wins when they disagree:

1. **The style file(s) from `chopchop.yaml`** (`repos.<name>.style`, shown as `Style:` in the
   look step). This is the team's own code style. Read all of it and follow it every time,
   for code and tests. If a file is missing, the look step says `Blocked:`: ask the user to
   fix the path.
2. **The repo's own guides:** CLAUDE.md, AGENTS.md, CONTRIBUTING.md.
3. **The profile** at `_chopchop/repos/<repo>.md`: build, lint and test commands, how PRs are
   opened, and rules learned from the code.
4. **The code itself.** With no style file, copy how nearby code is written: structure,
   naming, errors, logging, tests.

If there is no profile, make one and keep going:

1. `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_code.py --profile <repo>` drafts it from the repo.
2. Read the guides it lists, the CI commands, two or three tests and a similar feature.
   CI shows how the team really tests, so trust it over guesses.
3. Fix the commands in the front matter if needed. Fill in `## Rules` with short, real
   rules: folders and layers, naming, errors, logging, test style, what to copy, what to
   avoid. Fill in `pr:` once you know how PRs are opened here (step 7).

Use the draft for this task. At the end, ask the user once to check it (step 7).

## 3. Read the task

- The task file: Summary, Goal, Context, Contract, Code, Files, Done when, Do not change,
  Heads-up.
- `## Code` (tasks cut from a spec): the folders, names, code to copy, existing methods to
  reuse and a sketch of the new code. Start from it. Check the cited code still looks the
  same; if it changed, follow the code and log the difference with `--log`.
- The `Change:` lines from the look step. They win over the task text.
- The files in `touches`, the contracts from the tasks it depends on, and nearby code.
- The design files only when the task's Context is not enough.

If the task is unclear or conflicts with the code, stop here and ask, with what you found.
Otherwise go straight on.

## 4. Start and build

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_code.py T02 --start
```

This sets the task to in-progress and creates the task branch from the feature branch (or
resumes it and brings in the latest feature branch). If that merge conflicts, it undoes it
and stops. Tell the user. Never resolve it yourself.

Then build:

- Write the unit tests from `## Done when` first, with the exact names it gives, then the
  code that makes them pass.
- Unit tests only. Mock or fake anything outside this task. No end-to-end tests.
- A prove task (`kind: prove`) is the exception: write the end-to-end test for its journey,
  step by step as the task says, and run it with the task's `e2e` command. If the journey
  fails because of app code, do not fix the app here: log it with `--log` and tell the user.
- Stay inside `touches`. Follow the style file, then the guides and profile, then nearby code.
- No new library unless the task says so.
- Commit as you go. Use the repo's commit style (`git log`) with the task id in the subject,
  for example `T02 add refund endpoint`. Never commit secrets or unrelated changes.

## 5. Check

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_code.py T02 --verify
```

It runs the profile's build, lint and test commands. Fix every failure and run it again.

## 6. Log changes

If you differed from the task or design, touched files outside `touches`, changed a contract
others use, or the user told you to do something another way:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_code.py T02 --log --change "amounts are cents, not decimals" --why "ledger needs exact values"
```

It finds the affected tasks and adds a heads-up to the todo ones. Mention the rest in your
reply (owners to tell, follow-up tasks to suggest).

## 7. Push and open the PR

Push only the task branch, with the user's own git setup. Never force-push:

```
git push -u origin <task branch>
```

Open the PR from the task branch into the feature branch, never the base branch. Look for
an existing way, in this order:

1. The profile's `pr:` line.
2. A tool connected to this session that can open PRs (for example an MCP server for the
   team's git host).
3. A CLI the repo's guides mention that is already installed and logged in.

Title `T02: <task title>`. Description: what changed and how it was tested, the task's
`## Done when` list, and this task's changelog entries.

If there is no way, ask the user. Never ask for a token, log in or install anything. Say:
"I pushed T02. Please open the PR from `<task branch>` into `<feature branch>` and send me
the link."

When the PR exists:

```
python3 ${CLAUDE_SKILL_DIR}/../tasks/scripts/chopchop_tasks.py --set T02 in-review --pr <url> --feature <ref>
```

Reply with:
- the PR link
- the checks that passed
- any changelog entries and who to tell
- if you made the repo profile in this run: the commands and the PR method, and ask "Is
  this right?". On yes, run `--profile <repo> --confirm`.

## Review comments

When the user asks to fix review comments on a task in review, run steps 4, 5 and 7 again
on the same branch:
- Read the comments with the same tool that opens PRs, or ask the user to paste them.
- After pushing, the PR is the same one, so skip `--set`.
- Reply with one line per comment: what you changed, or why you did not.

## Done

Done is always set by a person (`--done T02`). Never set it yourself.

## Safety rules

- Push only the task's own branch. Never the feature branch, the base branch or main.
  Never force-push. Never merge a PR.
- Never ask for, store or set up logins, tokens or tools. Use what is already there.
- Never resolve merge conflicts. Never stash, reset or discard the user's changes.
- Change statuses only through the scripts.
- If a script fails, show the error and the fix. Do not work around it.
- If `_chopchop/style.md` exists, follow it.
