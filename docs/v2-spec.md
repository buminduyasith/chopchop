# chopchop v2 spec

## Summary

- **What:** one command (`/chopchop:run`) takes a Jira key or an idea and drives it to merged PRs. A live dashboard shows every feature. A new command explains PR review comments.
- **Why:** people should decide and review. Agents should read, build, test and fix.
- **How:** people approve three documents (brief, design, spec). Agents loop on build, review, fix, test, commit. Everything is Markdown, in simple English, with a Summary on top.
- **Status:** being built on branch `v2`, on top of 0.9.0.

## 1. The flow

```
Jira key or idea
   groom   agents read the stories and the code, then interview you      -> requirement.md, grooming.md
   brief   what we build, in simple English                 [you approve] -> brief.md
   design  for the lead, 10 minute read                [the lead approves] -> design.md
   spec    for the agents, every detail                     [you approve] -> spec.md, spec.json
   tasks   small tasks, one repo each                                      -> T01.md ...
   build   per task: build, review, fix, test, commit (fresh agent each)   -> commits, one PR per repo
   prs     review comments explained, grouped, fixed, answered             -> comments.md
   done    the PRs are merged
```

`chopchoplib/stage.py` reads the files and says which step a feature is on, who it waits for and what
is next. It keeps no state. `/chopchop:run` and the dashboard both use it.

## 2. Commands

| Command | What it does |
| --- | --- |
| `/chopchop:run <Jira key, link, idea or feature>` | The one command. Finds or creates the feature, starts the dashboard, does the next step, and stops only where a person must decide. |
| `/chopchop:run` | Carries on. With several features, it lists them with who each waits for. |
| `/chopchop:dashboard` | Starts the live dashboard and opens it. `--stop` stops it. `--status` says if it runs. |
| `/chopchop:comments [feature or PR link]` | Reads every review comment on the feature's PRs, explains each, groups similar ones, plans the fixes and drafts the replies. `--fix` fixes what you chose. `--watch` listens until the PRs are merged. |
| `/chopchop:groom`, `design`, `spec`, `tasks`, `auto`, `code`, `review`, `check`, `learn`, `init`, `update` | The single steps. `run` uses them. They still work on their own. |

No previews. `code T02 -p` and `tasks --status --open` are gone from the docs: the dashboard shows it.
`stories` stays as the low-level sync that `groom` uses.

## 3. Files per feature

```
_chopchop/001-PAY-120-refunds/
  requirements/requirement.md   the Jira stories word for word, or your idea as you gave it (never edited)
  requirements/grooming.md      what the agents found, every question and its answer
  requirements/brief.md         what we build, in simple English (a person approves it)
  design/design.md              for the lead (a person approves it)
  spec/spec.md  spec.json       for the agents (a person approves it)
  tasks/T01-*.md  plan.md  status.md  changelog.md
  comments.md                   the PR review report (generated)
  check.md
  work/                         answers, helper reports, auto.json, events.jsonl, groom/, comments/
```

No `feature.html`, no `board.html`. The dashboard renders the Markdown.

## 4. Rules for every file

1. **Markdown only.** No plain text boxes: a code block is only for real code, with its language. Lists,
   trees, messages and quotes are Markdown lists, tables and quotes.
2. **A Summary first.** Every `.md` chopchop writes has a `## Summary` (or `## 1. Summary...`) near
   the top: 2 to 5 short lines. `plain.summary()` reads it, `plain.summary_block()` writes it,
   `plain.lint()` checks it. Generated files always have one. A hand-written file without one fails
   its check.
3. **Simple English.** Short sentences (25 words or fewer), everyday words, no long dashes. This holds
   for files, chat replies and questions. `plain.lint()` warns.

## 5. `run`

Script: `skills/run/scripts/chopchop_run.py`.

| Call | Does |
| --- | --- |
| `--where "<text>"` | Says what the text is: a feature (number, key, name), a new Jira key or link, or a new idea. Prints the feature's step, who it waits for, and a `Next:` line. Starts the dashboard unless `dashboard.auto: false`. |
| `--where` (nothing) | The only feature, or a list of all features with who each waits for. |
| `--list` | Every feature: step and who it waits for. |
| `--approve <ref> <brief|design|spec> --by "Name" [--note ...]` | Records a person's yes, through the step's own script. |

The skill follows the `Next:` line by starting that step's skill, then asks `--where` again. It goes on
without asking while the next step needs no person. At a gate it stops, says in two lines what to read
(with the dashboard link) and how to say yes.

## 6. `groom`

Script: `skills/groom/scripts/chopchop_groom.py`. State: `work/groom/groom.json`.

1. **Source.** A Jira key: fetch like `stories` does and write `requirement.md`. An idea:
   `--idea "<text>"` makes feature `NNN-IDEA-N-<slug>` with the idea, as given, in `requirement.md`.
2. **Mode.** `locked` for tracker stories: never change what the BA wrote, every suggestion is a
   question. `open` for ideas: suggestions are welcome. `--locked` / `--open` override.
3. **Research.** One explorer per repo checks each story against the code: does it fit, what it
   touches, what it clashes with, hidden work, size, and questions. `--findings <file>` checks the
   merged findings and writes `grooming.md`.
4. **Interview.** At most 4 questions a round, at most 3 rounds, each with click answers and
   "I don't know, ask the BA". `--answer Q3 --text "..." --by dev|ba`, or `--ask-ba Q3`.
   `--auto` asks nothing: open questions go to the BA list or become assumptions.
5. **BA list.** `--questions ba` prints the open BA questions, ready to paste. Answers come back
   through `--answer ... --by ba`.
6. **Brief.** When no blocking question is open, write `brief.md` from the template and run `--brief`:
   it checks the Summary, simple English, and (locked mode) that every story and acceptance
   criterion id is in scope or out of scope.
7. **Approve.** `--approve "Name"` marks the brief approved.

`grooming.md` front matter: `mode`, `status`, `questions`, `open_dev`, `open_ba`, `updated`.
`brief.md` front matter: `title`, `status` (`draft`, `approved`), `approved_by`, `approved_on`,
`changed_since_approval`.

Question shape in `groom.json`:

```json
{"id": "Q3", "text": "Can a refund be partial?", "why": "The order model has one amount field.",
 "story": "PAY-121", "options": ["Yes", "No, full only"], "blocking": true, "ask": "dev",
 "state": "open", "answer": null, "by": null, "on": null}
```

`ask` is `dev` or `ba`. `state` is `open`, `answered` or `assumed`.

## 7. Dashboard

Script: `skills/dashboard/scripts/chopchop_dashboard.py`. Page: `skills/dashboard/assets/dashboard.html`.
Python standard library only. It listens on `127.0.0.1` only. It is read only.

| Call | Does |
| --- | --- |
| `--start [--port N] [--no-open]` | Starts the server in the background if it is not running. Prints the URL. Writes `_chopchop/.dashboard.json` (`pid`, `port`, `url`, `started`). |
| `--stop` | Stops it. |
| `--status` | Running or not, and the URL. |
| `--serve` | Runs in the foreground (what `--start` launches). |

HTTP:

| Path | Returns |
| --- | --- |
| `GET /` | the page |
| `GET /api/features` | every feature as `stage.read()` gives it, plus `updated` |
| `GET /api/feature/<n>` | that, plus `docs` (list), `tasks` (list with Summary lines), `events` (newest 200), `comments` (prs, threads, triage) |
| `GET /api/doc/<n>?path=design/design.md` | `{title, html, summary, updated, raw}`. Only files inside the feature folder. |
| `GET /api/stream` | server-sent events: `changed` with the feature numbers, whenever a file under `_chopchop/` changes |

The page:

- **Home:** one card per feature: title, key, the steps as a line that fills up, a task progress bar,
  a "waiting on you / the lead / the BA / the reviewers" badge and the Summary lines. Filter by text,
  step, and who it waits for.
- **Feature:** the steps on top. Tabs: Overview, Brief, Design, Spec, Changes, Tasks, Review, Activity.
  **Compare** puts Design and Spec side by side. Tasks is a board (todo, building, committed, in
  review, done). A click on a task opens its Markdown in a side panel.
- **Review tab:** see section 8.
- **Live:** the page listens on `/api/stream` and reloads only what changed.
- **Diagrams:** `design.md` diagrams are drawn on the server from `architecture.json` and
  `flow.json` (`chopchoplib/diagrams.py`), so they work offline. Other Mermaid blocks render in the
  browser with Mermaid loaded from a pinned CDN URL. Offline, they show as code.
- Links name a feature by its folder: `#/f/001-PAY-120-refunds/tasks`. A bare number (`#/f/1`) still works and
  turns into the named link once the page loads.
- **Changes** (tech spec only): every file the spec adds (A, green), changes (M, amber) or deletes (D, red), as
  one folder tree per repo, like an editor's file explorer with its git colours. No code. Filters for new, changed,
  deleted and test files, a search box, expand and collapse. A click on a file shows why it changes, its packages,
  and the tasks that change it with their state. `spec.md` section 6 has the same tree as text. Built from
  `packages[].files` in spec.json by `chopchoplib/changes.py`; a file two packages touch shows once.
- Code blocks are coloured like VS Code (Dark+ by default, Light+ in the light theme), with the language shown.
  highlight.js loads only on pages with code, from a pinned cdnjs link with an integrity hash. Offline, code
  stays plain.
- Dark by default, with a light toggle. Made for a laptop screen, and it still works in a narrow
  desktop pane (about 650 px wide). No phone layout.
- Documents fill the window height. **Compare** is a reading mode: the two panes sit side by side
  and take all the height left, with no page scroll around them.

## 8. `comments` (PR review)

Script: `skills/comments/scripts/chopchop_comments.py`. Agent: `agents/triager.md`. Store:
`<feature>/work/comments/` (or `_chopchop/prs/<slug>/work/comments/` for a PR with no feature).

| Call | Does |
| --- | --- |
| `--prs [ref]` | Finds the feature (given, or from the branch you are on, or the only one with PRs) and lists its PRs from `auto.json` and the task files. `--pr <url>` adds one. |
| `--fetch [ref]` | Reads PR state and every review comment with `gh` when it is installed and logged in. Writes `prs.json` and `threads.json`. Says what is new. For other hosts, the agent fetches with the team's tool and passes `--ingest <file>`. |
| `--pack [ref]` | Writes `pack.md` for the triager: each new thread with its code, the task and spec parts it touches, and likely similar threads. |
| `--triage <file>` | Checks the triager's JSON and merges it into `triage.json`. Keeps a person's decisions. Writes `comments.md`. |
| `--decide <id or group> fix|reply|skip` | Records the person's call. `--decide all-real fix` works too. |
| `--plan` | The fix batches in order. Groups that touch the same files go in one batch, so one fix never undoes another. Writes a brief per batch. |
| `--fixed <batch> --commit <sha>` | Marks a batch fixed. |
| `--replies` | The reply drafts, ready to paste. `--post` posts them with `gh`, only after the person says yes. |
| `--wait [--every 60] [--for 1800]` | Blocks until something new arrives or every PR is merged or closed, then says what. Exit 0 new, 2 all merged or closed, 3 nothing new in time. |
| `--status` | Counts: PRs, comments, new, needs your call, to fix, fixed, replied. |

Each comment gets, in simple English:

| Field | Meaning |
| --- | --- |
| `plain` | what the reviewer says, in one or two short sentences |
| `verdict` | `real` (a real problem), `false-positive` (the reviewer is mistaken), `negotiable` (fair, but not for this PR), `question`, `praise`, `outdated` |
| `priority` | `high`, `medium`, `low` |
| `why` | why chopchop thinks so, with the code it looked at |
| `evidence` | `repo/path:line` citations |
| `fix` | what we would change |
| `impact` | what else the fix touches, and the risk |
| `reply` | the reply we would post |
| `group` | comments with the same root cause share a group, across PRs and repos |
| `decision` | the person's call: `fix`, `reply`, `skip` |
| `state` | `triaged`, `fixing`, `fixed`, `replied`, `closed` |

### Files

`prs.json`

```json
{"prs": [{"id": "shop-api#12", "repo": "shop-api", "host": "github", "slug": "owner/shop-api", "number": 12,
          "url": "https://github.com/owner/shop-api/pull/12", "title": "Refund requests", "state": "open",
          "draft": false, "head": "feature/IDEA-1/build", "base": "feature/IDEA-1-refunds", "author": "bumindu",
          "review": "changes-requested", "fetched": "2026-11-14T10:00:00", "threads": 7}],
 "watch": {"on": true, "since": "2026-11-14T10:00:00", "last": "2026-11-14T10:05:00"}}
```

`state` is `open`, `merged` or `closed`. `review` is `approved`, `changes-requested`, `commented` or `none`.

`threads.json`

```json
{"fetched": "2026-11-14T10:00:00",
 "threads": [{"id": "shop-api#12:r2001", "pr": "shop-api#12", "repo": "shop-api", "kind": "inline",
              "file": "src/services/refundService.js", "line": 42, "hunk": "@@ -40,6 +40,9 @@ ...",
              "author": "asha", "bot": false, "created": "2026-11-14T09:00:00", "updated": "2026-11-14T09:30:00",
              "resolved": false, "outdated": false, "url": "https://github.com/...#discussion_r2001",
              "body": "This lets a refund of 0 through.", "replies": [{"author": "bumindu", "body": "...", "created": "..."}],
              "hash": "9f2c..."}]}
```

`kind` is `inline` (on a line), `review` (a review's summary text) or `general` (a PR comment).
`hash` is the sha1 of the body and replies: when it changes, the thread is new again.

`triage.json`

```json
{"updated": "2026-11-14T10:10:00",
 "items": {"shop-api#12:r2001": {"plain": "A refund of 0 passes the check.", "verdict": "real", "priority": "high",
            "group": "G1", "why": "Line 42 compares with >= 0, and rule R-2 says more than 0.",
            "evidence": ["shop-api/src/services/refundService.js:42"], "fix": "Compare with > 0 and add the test refuses_zero_refund.",
            "impact": "Only this check. The web form already blocks 0.", "reply": "Good catch. Fixed in the next commit, with a test.",
            "decision": null, "state": "triaged", "hash": "9f2c...", "commit": null}},
 "groups": [{"id": "G1", "title": "Zero and negative amounts pass", "plain": "Two comments say the amount check is too loose.",
             "threads": ["shop-api#12:r2001", "shop-web#7:r3110"], "verdict": "real", "priority": "high",
             "fix": "Tighten the check in the service and mirror it in the form.", "impact": "Service and form.",
             "files": ["shop-api/src/services/refundService.js", "shop-web/src/views/refundForm.js"], "order": 1, "with": []}]}
```

A thread is **new** when it has no item, or the item's `hash` differs from the thread's.

### Dashboard Review tab

- On top: PRs with state, and counts by verdict.
- Then the groups, most urgent first. Each group is a card: title, verdict, priority, the plain
  explanation, the fix, the impact, and its comments.
- Each comment: who said it, where (file and line, with a link), the original text, the plain
  explanation, why chopchop thinks so, the reply draft with a Copy button, and the person's decision.
- Filters: verdict, priority, PR, state, "needs my call".
- New comments that are not explained yet show at the top with "not explained yet".

### Safety

- Fixes are committed only on the PR's own branch, and only for comments a person chose.
- Replies are drafts. Posting needs the person's yes each time.
- Never opens, merges or closes a PR. Never force-pushes.

## 9. Changes to the existing skills

- **design, spec, tasks:** no `feature.html`, no `board.html`. `--open` opens the dashboard.
  `page.py`, the board page and both HTML templates go away. `status.md`, `plan.md`, `check.md`,
  `options.md`, task files and `changelog.md` get a Summary.
- **design:** reads `brief.md` and `grooming.md` when they exist. The brief wins on what to build.
- **spec:** `--approve "Name"` records a person's yes in `spec.md` (`approved_by`, `approved_on`).
  A later change sets `changed_since_approval`.
- **tasks:** a new `--from-spec` warns when the spec is not approved.
- **auto:** `--retry T02` restarts a stopped task. The forbid fix list names `file:line` and says that
  object keys and comments are fine. A commit or retry clears the repo's `paused`. The brief names the
  task's `forbid` words. `--plan --repos` rejects unknown repo names. `auto.pause: wave` (or `--wave`)
  pauses after each wave. When `comments --fetch` sees a PR merged, its tasks become `done`.
- **code:** `-p` is no longer offered to the user.
- **code-reviewer:** the no-false-claims rule also covers its one-line reply.
- **every script:** logs what it did with `events.log()`.

## 10. Activity log

`<feature>/work/events.jsonl`, one JSON object per line: `ts`, `kind`, `text`, and optional `task`,
`repo`, `by`. Written by `chopchoplib/events.py`. Kinds: groom, question, answer, brief, design, spec,
tasks, approve, run, build, review, fix, commit, stop, push, pr, comment, triage, reply, merge, done, note.

## 11. Tests and evals

- Unit tests next to every script (`unittest`, local git repos, no network, no account).
- `evals/`: `groom-auto`, `run-where`, `comments-triage` are new. `design-auto` no longer expects
  `feature.html`.
- Trials on real open source repos, and on real public PRs read with `gh` (read only).

## 12. Not in v2

Parallel waves in git worktrees, an overnight runner, writing status back to Jira, and approving from
the dashboard.
