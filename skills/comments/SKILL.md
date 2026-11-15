---
name: comments
description: Use for ANY request about pull request or merge request review comments, from GitHub, a link, or a file of comments another tool exported. Read every review comment on a feature's pull requests and explain each one in simple English. Finds the feature and its PRs by itself, groups comments that have the same root cause (across PRs and repos), says which are real problems, which are false positives and which are fair but not for this PR, plans the fixes so one fix never undoes another, and drafts the replies. --fix fixes what the person chose on the PR's own branch. --watch keeps listening until the PRs are merged. Use it even when the comments are in a file (it ingests them) and even for a few comments, because it keeps the state the dashboard shows. Use when the user asks to explain or answer review comments, PR comments, "address the review", "what did the reviewers say", "reply to the reviewers", "fix the review comments", or runs comments.
argument-hint: "[feature or PR link] [--fix] [--watch] | --status | --replies | --stop"
---

# Comments

You are the conductor. The script reads the PRs and keeps the state. A fresh triager agent
explains the comments. A fresh builder fixes what the person chose. So your own context stays
small: read only what the script and the agents reply, and say one line per step.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py`. Run it with `python3` from the
user's project folder. It needs the `tasks` skill folder next to it. Each call prints a `Next:`
line. Follow it.

Everything it knows is in one place: `<feature>/comments.md`, and the Review tab of the
dashboard. The file shapes are in [SCHEMA.md](SCHEMA.md).

## What the user typed

| You see | Do |
| --- | --- |
| nothing, or a feature | Steps 1 to 3. Then 4 and 5 for what the person chose. |
| a PR link | `--pr <link>` first, then steps 1 to 3 with that link as the ref. |
| `--fix` | Steps 1 to 5. The fix step runs for every comment the person chose to fix. |
| `--watch` | Steps 1 to 3, then step 6. |
| `--replies` | Step 5 only. |
| `--status` | `--status`, and show it. |
| `--stop` | Stop the background `--wait`, then `--watch off`. |

## 1. Find the PRs and read them

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --prs [ref]
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --fetch [ref]
```

`ref` is a feature (number, key, name) or a PR link. Leave it out and the script picks the
feature whose branch is checked out here, or the only feature that has PRs.

- `--prs` exit 2 with a list: ask the person which one, with the list as click answers.
- A PR link that belongs to no feature gets its own store: `--pr <link>`. Add `--path <folder>`
  when the repo is checked out and chopchop should read its code.
- `--fetch` exit 1: `gh` is missing, not logged in, or the PR is on another host. Fetch the
  PR state and its comments with a tool that is connected (Azure DevOps, GitLab, Bitbucket),
  write them to a file in the ingest shape from SCHEMA.md, then run `--ingest <file>`.
  Never ask for a token.
- Nothing new and no open call: say so in one line and stop, or go to step 6.

## 2. Explain

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --pack [ref]
```

It writes `pack.md` and names the answer file. Start one `chopchop:triager` agent. Give it only:
"Explain the review comments in `<pack.md path>`." Wait for its one line reply. Then:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --triage <answer file>
```

- Exit 2: it lists what is wrong with the answer. Send that list to the same triager and run
  `--triage` again. After 2 tries, tell the person.
- `Warning:` lines are about wording. Go on. If a reply has a long dash or a very long
  sentence, ask the triager to rewrite that reply.
- `Missing:` some comments have no answer yet. Run `--pack` again for them.

Never read the code or judge a comment yourself. That keeps the verdicts independent.

## 3. Tell the person

Short, in simple English:

1. How many comments, on how many PRs, and how many need their call.
2. The top 3 groups, one line each: what it is, the verdict, the priority (the `Top:` lines).
3. Where to read everything: the dashboard link (the Review tab shows every comment, the
   plain explanation, the verdict, the fix, what it touches and the reply draft) and
   `comments.md`. Get the link with
   `python3 ${CLAUDE_SKILL_DIR}/../dashboard/scripts/chopchop_dashboard.py --start`.

Then ask which to fix. Offer click answers: "Fix all real ones", "I will pick", "Reply only".
Record each answer:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --decide all-real fix
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --decide G2 reply
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --decide <thread id> skip
```

- The call is the person's. Never decide for them, also not with `--fix`.
- `fix` works for a real problem. For a negotiable comment or a question, add `--force` only
  when the person says to fix it anyway.
- A false positive cannot be fixed. If the person thinks the reviewer is right, run
  `--pack --again <id>` and step 2 again.

## 4. Fix (with --fix, or after the person chose)

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --plan
```

It cuts the fixes into batches. Comments that touch the same files are in one batch, so one
fix never undoes another. For each batch, in order:

1. Start one `chopchop:builder` agent: "Fix the review comments in `<brief path>`." Wait for
   its line.
2. Run the check commands the brief names, in the repo. If they fail, send the output to the
   builder. After 2 failed tries, leave the batch and tell the person.
3. Review the pending change with the review skill's script:
   `python3 ${CLAUDE_SKILL_DIR}/../review/scripts/chopchop_review.py --pack --repo <repo path>`.
   Start one `chopchop:code-reviewer` agent with that pack, then run the same script with
   `--sort <findings path>`. Send the fix-now findings to the builder once, and run the checks
   again. Never apply a parked finding. A stop finding: leave the batch and tell the person.
4. `--commit B1 --message "<subject>"`. Use the `commit` line from the builder's report.
   `Outside:` means files changed that the batch does not cover: ask the builder to undo them.
   Add `--outside <files>` only when the fix truly needs them.
5. `--push <repo>`, then `--fixed B1`.

The repo must be on the PR's own branch. If the script says it is not, ask the person to check
it out. Never switch branches, fix code or commit yourself.

## 5. Replies

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --replies
```

Show the drafts that are ready, each with who it answers. A reply to a fixed comment names
the commit. Ask: "Post these N replies?" Only after a yes:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --post --yes
```

`--post <ids> --yes` posts only some. Without `gh`, or on another host, the person pastes the
drafts, or you post them with the connected tool after their yes. A new yes is needed every time.

## 6. Watch (with --watch)

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --watch on
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_comments.py --wait --every 60 --for 1800
```

Start `--wait` as a background command and tell the person: chopchop is listening, and the
dashboard shows new comments live. When it ends:

| Exit | Means | Do |
| --- | --- | --- |
| 0 | New comments came in. | Step 2 for them, tell the person in one or two lines, then start `--wait` again. |
| 3 | Nothing new in that time. | Start `--wait` again. |
| 2 | Every PR is merged or closed. | Say so. The tasks of a merged PR are done now. Stop. |
| 1 | `gh` failed three times. | Say why in one line and stop. |

When the person says stop: stop the background command and run `--watch off`.

## Reply

Keep it short. Simple English, short sentences, no long dashes.

1. One line: comments, groups, and how many need a call.
2. The top groups, one line each.
3. What was fixed (commit), what was answered, what still waits for the reviewers.
4. The dashboard link and `comments.md`.

## Safety rules

- Never open, merge or close a PR. Never force-push. Never push to the base branch, main or master.
- A fix is committed only on the PR's own branch, and only for comments the person chose.
- Replies are drafts. Never post without the person's yes, each time. Never pass `--yes` on your own.
- Never resolve a review thread, react to a comment or dismiss a review.
- Never ask for, store or print logins or tokens.
- Change task statuses only through the scripts. A merged PR sets its tasks to done. A closed PR does not.
