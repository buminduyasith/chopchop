---
name: auto
description: Build a feature's tasks automatically, one task at a time. For each task a fresh builder agent writes the tests and code and runs the checks, a fresh reviewer reviews the pending changes, fixes that fit the spec are made, ideas that change the direction are parked, and the task is committed on one build branch per repo. At the end it pushes and opens one PR per repo into the feature branch, never into the base branch. Resumable from a new chat. Use when the user runs auto, wants to build all the tasks, build the feature automatically, run the tasks in a loop, or carry on an auto run.
argument-hint: "[feature] [--max N] [--only T01,T02] [--repo name] [--step | --wave] | --status | --resume | --retry T02"
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
| `--wave` | Pause after the last task of each wave and wait for the user's go. Pass to `--start`. `auto.pause: wave` in `chopchop.yaml` does the same for every run. |
| `--status` | `--status`, and show it. |
| `--resume` | `--status`, then carry on from its `Next:` line, in the loop of step 3. |
| `--stop T03 "why"` | `--stop T03 --why "..."`, only when the user says so. |
| `--retry T03` | `--retry T03 [--why "what they decided"]`, only when the user decided the stopped task goes on. See "A stopped task". |

## 1. Plan

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_auto.py --plan <ref> [--max N] [--only ...] [--repo ...]
```

Exit 1 means blocked.

- **No test command** for a repo: fix it yourself, do not stop. For each such repo run
  `python3 ${CLAUDE_SKILL_DIR}/../code/scripts/chopchop_code.py --profile <repo>`. It drafts
  `_chopchop/repos/<repo>.md` from the repo's build files and CI. Read the commands it found,
  check them against the repo's guides (CLAUDE.md, README, package.json, pyproject.toml, CI), and
  fix the front matter if one is wrong. A lint command that changes files (a `--fix`, or a tool
  whose config turns fixing on) must get its "check only" form. Then `--plan` again. Say the
  commands you used in one line, and ask the user at the end of the run to confirm the profile
  (`--profile <repo> --confirm`). Stop only when you cannot find a test command at all.

For the other blocks, tell the user each fix in one line and stop:
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

It creates or resumes one build branch per repo from the latest feature branch. Pass `--step`
or `--wave` here when the user asked for it. The plan's `Pause:` line says which one is on.

## 3. The loop

Repeat until `--next` says nothing is left. Each step prints a `Next:` line. Follow it.

1. `--next`. It prints the brief path.
2. Start one `chopchop:builder` agent: "Build the task in `<brief path>`." Wait for its line.
3. `--review T02`. Exit 1 means the task stopped: say its `Stopped:` line, go to 1. Otherwise
   it prints a pack path.
4. Start one `chopchop:code-reviewer` agent: "Review the change in `<pack path>`." If the
   script names a model, pass it as the agent's model. Do not repeat what the reviewer
   replies: its reply only tells you it is done.
5. `--sort T02`. Say the script's `Sorted:` line. That line, and the files the script wrote,
   are the only source for what the review found:
   - `Fix:` Send the builder the fix list with SendMessage: "Fix the items in `<fix path>`."
     If that builder is gone, start a new one: "Build the task in `<brief path>`. The work is
     already there. Fix the items in `<fix path>`." Then go to 3.
   - `Next: --commit` Go to 6.
   - Exit 1 means the task stopped. Go to 1.
6. `--commit T02`.
   - `Outside:` Ask the builder to undo those files. Only if the task truly needs them, it
     logs the change, and you run `--commit T02 --outside <files>`.
   - `Not allowed:` New code uses a name the task forbids. It wrote a fix list that names
     each `file:line`. Do as in 5, then go to 3. A forbidden name is still fine as an object
     key and in a comment: the list says so, and only its lines must change.
7. Say the `Commit:` and `Review:` lines. When the script prints a `Pause:` line (`--step`
   after each task, `--wave` after the last task of a wave), say it, stop and wait for the
   user. On their go, carry on with `--next`.

While the loop runs:
- Never read the code, the diff or the findings yourself, and never fix code yourself. That
  keeps the run cheap, and the reviewer independent.
- Relay the script's lines, never an agent's own words. A reviewer or a builder can say
  something the pack or the task never said. What you tell the user comes from `Sorted:`,
  `Commit:`, `Review:`, `Stopped:` and `--status`.
- Never apply a parked idea, and never ask an agent to.
- Stop a task with `--stop T02 --why "..."` when a builder reports a conflict or anything a
  person must decide that the script did not catch.
- Never commit, push or switch branches yourself. The script does.
- If this chat gets long, tell the user they can open a new chat and run `/chopchop:auto --resume`.

### A stopped task

A task stops when a person must decide: the builder could not build it as written, the checks
still fail, or the review found something serious. Its repo waits, its changes stay
uncommitted, and the other repos go on. The `Stopped:` and `Retry:` lines say why and how to
go on. Tell the user both, and ask what they decide. Never retry on your own.

When the user decides it goes on:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_auto.py --retry T02 [--why "what the person decided"]
```

- Its work is still in the repo: the task is `fixing` again, the repo is no longer paused, and
  the tasks that only waited for it are back in the queue. It prints a retry note. Start a new
  `chopchop:builder`: "Build the task in `<brief path>`. The work is already there. Follow
  `<retry note path>`." Then go to step 3 of the loop. If the user already fixed it by hand,
  run the brief's check command, then go to step 3.
- Nothing was built: the task is back in the queue. Carry on with `--next`.
- Another task is running: finish that one first. The script says so.

A retry gives the task its review rounds again. What the person decided goes into the next
review pack, so the reviewer does not raise it again.

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
4. Stopped tasks, what a person must decide, and that `--retry <task>` starts one again.
5. Next: a person reviews and merges the PRs. Done is set by a person.

## Settings

In `chopchop.yaml`, all optional:

```yaml
auto:
  rounds: 2          # review rounds per task, 1 to 3
  pr: draft          # draft, ready, or push (you open the PRs)
  pause: wave        # pause after each wave. Leave it out to run without stops
  reviewer_model:    # a model alias for the reviewer, or empty for the chat's own
```

## Safety rules

- Push only the build branches. Never the feature branch, the base branch or main. Never
  force-push. Never merge a PR.
- Never resolve merge conflicts. Never stash, reset or discard changes.
- Never ask for, store or set up logins or tokens.
- Change statuses only through the scripts. Done is always set by a person.
