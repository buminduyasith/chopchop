---
name: review
description: Review code changes before they are committed or merged, in any git repo. A fresh reviewer reads the pending changes (new files too), a branch, or a chopchop task's changes, and checks bugs, tests, fit with the repo's own style and code, safety, and fit with the task and spec. Each finding is sorted into fix now, park (a different direction, never applied) or stop (a person decides). --fix applies only the fix-now items. Use when the user asks to review code, review my changes, check before I commit, review a branch, or runs review.
argument-hint: "[T02] [--branch [base]] [--repo path] [--fix]"
---

# Review

Review a change before it is committed or merged. The reviewer is a fresh agent: it sees the
change, the task and the repo's rules, not the conversation that made the change.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_review.py`. Run it with `python3`. It needs
the `tasks` skill folder next to it, and for a task id the `code` skill folder too.

## What the user typed

| You see | Do |
| --- | --- |
| nothing | Review the pending changes in the repo you are in. |
| `T02` | Review T02's pending changes, also against its task file and the spec. |
| `--branch [base]` | Review this branch against `base` (for a task: its feature branch). |
| `--repo path` | Review that repo instead. |
| `--fix` | Also apply the fix-now findings, then review once more. |

## 1. Pack

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_review.py --pack [T02] [--branch [base]] [--repo path]
```

It writes `pack.md` (what to read) and `diff.patch`, and names the findings file. Exit 1 means
there is nothing to review: say so and stop. Without a task its files live inside `.git/`, so
they never show up in the change.

## 2. Review

Start one `chopchop:code-reviewer` agent. Give it only: "Review the change in `<pack.md path>`."
If `chopchop.yaml` sets `auto.reviewer_model`, pass that as the agent's model. Wait for its one
line reply.

## 3. Sort

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_review.py --sort <findings path>
```

It puts each finding in fix, park or stop, and checks the reviewer's groups against the task:
a fix outside the task's files, or in a file the task must not change, is parked. A finding of
a different direction (another approach, a changed contract or rule, a new library) is always
parked. Exit 1 means there is a stop finding.

## 4. Reply

Short, grouped:

1. **Stop** first, if any: what and where, and that a person must decide.
2. **Fix now**: one line each, `file:line`, what, and the fix.
3. **Park**: one line each. Say these are ideas that change the direction, so they are not
   done. They belong with the lead, not in this change.

Without `--fix`, end there.

## 5. Fix (only with --fix)

- Apply the fix-now items only. Never a parked one, never a stop one.
- Stay inside the change. For a task, stay inside its `touches`.
- Run the checks: `python3 ${CLAUDE_SKILL_DIR}/../code/scripts/chopchop_code.py T02 --verify` for a
  task, or the repo's own test command.
- Then pack, review and sort once more (round 2). Report what was fixed and what is left.

## Safety rules

- Never commit, push, stash or reset. The review is of pending work and leaves it pending.
- Never apply a parked finding, even when it looks better.
- Never ask for, store or print secrets. If the diff holds one, say where, not what.
