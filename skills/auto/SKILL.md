---
name: auto
description: Build a feature's tasks automatically, one task at a time. For each task a fresh builder agent writes the tests and code and runs the checks, a fresh reviewer reviews the pending changes, fixes that fit the spec are made, ideas that change the direction are parked, and the task is committed on one build branch per repo. At the end it pushes and opens one PR per repo into the feature branch, never into the base branch. Resumable from a new chat. Use when the user runs auto, wants to build all the tasks, build the feature automatically, run the tasks in a loop, or carry on an auto run.
argument-hint: "[feature] [--max N] [--only T01,T02] [--repo name] [--step] | --status | --resume"
---

# Auto

You are the conductor. Fresh agents build and review each task, and the script keeps the run
in `work/auto.json`. So your own context stays small: read only what the script and the agents
reply, and say one line per step.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_auto.py`. Run it with `python3` from the
user's project folder. It needs the `code` and `tasks` skill folders next to it.

## What the user typed

| You see | Do |
| --- | --- |
| nothing, or a feature | Steps 1 to 5. |
| `--max 3` | Only the next 3 tasks. Pass it to `--plan` and `--start`. |
| `--only T01,T02`, `--repo web-app` | Only those tasks, or that repo. Pass to `--plan` and `--start`. |
| `--step` | Pause after each commit and wait for the user's go. Pass to `--start`. |
| `--status` | `--status`, and show it. |
| `--resume` | `--status`, then carry on from its `Next:` line, in the loop of step 3. |
| `--stop T03 "why"` | `--stop T03 --why "..."`, only when the user says so. |

## 1. Plan

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_auto.py --plan <ref> [--max N] [--only ...] [--repo ...]
```

Exit 1 means blocked. Tell the user each fix in one line and stop:
- No test command: offer `/chopchop:code --profile <repo>`.
- Uncommitted files: ask them to commit or stash. Never do it for them.
- No feature branch: `/chopchop:tasks --branch`, then `--create`.

Otherwise show the plan in a few lines: the order, the build branch per repo, and where the
PRs go. Ask once: "Start?". That one yes covers the whole run: building, committing on the
build branches, pushing them and opening the PRs. If the user already said to go without
questions, do not ask.

## 2. Start

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_auto.py --start <ref> [same options] [--step]
```

It creates or resumes one build branch per repo from the latest feature branch.

## 3. The loop

Repeat until `--next` says nothing is left. Each step prints a `Next:` line. Follow it.

1. `--next`. It prints the brief path.
2. Start one `chopchop:builder` agent: "Build the task in `<brief path>`." Wait for its line.
3. `--review T02`. Exit 1 means the task stopped: say it in one line, go to 1. Otherwise it
   prints a pack path.
4. Start one `chopchop:code-reviewer` agent: "Review the change in `<pack path>`." If the
   script names a model, pass it as the agent's model.
5. `--sort T02`:
   - `Fix:` Send the builder the fix list with SendMessage: "Fix the items in `<fix path>`."
     If that builder is gone, start a new one: "Build the task in `<brief path>`. The work is
     already there. Fix the items in `<fix path>`." Then go to 3.
   - `Next: --commit` Go to 6.
   - Exit 1 means the task stopped. Go to 1.
6. `--commit T02`.
   - `Outside:` Ask the builder to undo those files. Only if the task truly needs them, it
     logs the change, and you run `--commit T02 --outside <files>`.
   - `Not allowed:` It wrote a fix list. Do as in 5, then go to 3.
7. Say the `Commit:` and `Review:` lines. With `--step`, stop and wait for the user.

While the loop runs:
- Never read the code, the diff or the findings yourself, and never fix code yourself. That
  keeps the run cheap, and the reviewer independent.
- Never apply a parked idea, and never ask an agent to.
- Stop a task with `--stop T02 --why "..."` when a builder reports a conflict or anything a
  person must decide that the script did not catch.
- Never commit, push or switch branches yourself. The script does.
- If this chat gets long, tell the user they can open a new chat and run `/chopchop:auto --resume`.

## 4. Finish

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_auto.py --finish
```

It pushes each build branch and writes a PR file per repo (title on the first line). For each
pushed repo, open the PR from the build branch into the feature branch, as a draft when the
script says draft, with that title and text. Use the way `/chopchop:code` does: the profile's
`pr:` line, a connected tool that opens PRs, or a CLI that is installed and logged in. Then:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_auto.py --pr <repo> <url>
```

No way to open it: ask the user to open it from `<build branch>` into `<feature branch>` and
send the link. Never ask for a token.

## 5. Reply

Short:
1. One line per task, from `--status`.
2. The PR links.
3. Parked ideas: how many, and that they are listed in the PR text for the lead.
4. Stopped tasks, and what a person must decide.
5. Next: a person reviews and merges the PRs. Done is set by a person.

## Safety rules

- Push only the build branches. Never the feature branch, the base branch or main. Never
  force-push. Never merge a PR.
- Never resolve merge conflicts. Never stash, reset or discard changes.
- Never ask for, store or set up logins or tokens.
- Change statuses only through the scripts. Done is always set by a person.
