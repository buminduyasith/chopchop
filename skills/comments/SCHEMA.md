# The files of `/chopchop:comments`

## Summary

- **What:** the shapes of the files the comments script reads and writes.
- **Where:** `<feature>/work/comments/`, or `_chopchop/prs/<owner>-<repo>-<number>/work/comments/` for a PR with no feature.
- **You write two of them:** the ingest file (when `gh` cannot read the PR) and the triage answer (the triager agent).
- **The script writes the rest.** The dashboard and `chopchoplib/stage.py` read them, so the shapes are fixed.

```
work/comments/
  prs.json          the PRs and their state                      (script)
  threads.json      every review comment, one thread each        (script)
  triage.json       the explanation, the groups, the decisions   (script, from the triager's answer)
  pack.md           what the triager reads                       (script)
  triage-in.json    the triager's answer                         (triager)
  replies.md        the reply drafts                             (script)
  fix/plan.json     the fix batches                              (script)
  fix/B1/brief.md   what the builder reads                       (script)
  fix/B1/report.json  what the builder did                       (builder)
comments.md         the report for people, in the feature folder (script)
```

All times are local time, like `2026-11-14T10:00:00`. A host time such as `2026-11-14T09:00:00Z`
is changed to local time when it comes in.

## Ids

| Thing | Id | Example |
| --- | --- | --- |
| PR | `<repo>#<number>`. `repo` is the name in `chopchop.yaml`, else the repo's own name. | `shop-api#12` |
| Thread | `<PR id>:<kind letter><number on the host>`. `r` a review thread (the number of its first comment), `v` a review summary, `c` a PR comment. | `shop-api#12:r2001` |
| Group | `G1`, `G2`, ... A group keeps its id. | `G1` |
| Batch | `B1`, `B2`, ... | `B1` |

For another host, any thread id works as long as it starts with the PR id and a colon, and
stays the same on every fetch.

## The ingest file (`--ingest <file>`)

Use it when `gh` cannot read the PR: Azure DevOps, GitLab, Bitbucket, or no `gh` login. Fetch
the PR and its comments with a connected tool, write this file, and pass it. It has the same
shapes as `prs.json` and `threads.json`.

```json
{"me": "bumindu",
 "prs": [{"url": "https://gitlab.com/shop/shop-api/-/merge_requests/12", "repo": "shop-api", "title": "Refund requests",
          "state": "open", "draft": false, "head": "feature/IDEA-1/build", "base": "feature/IDEA-1-refunds",
          "author": "bumindu", "review": "changes-requested"}],
 "threads": [{"id": "shop-api#12:r2001", "pr": "shop-api#12", "kind": "inline",
              "file": "src/services/refundService.js", "line": 42, "hunk": "@@ -40,6 +40,9 @@ ...",
              "author": "asha", "bot": false, "created": "2026-11-14T09:00:00Z", "updated": "2026-11-14T09:30:00Z",
              "resolved": false, "outdated": false, "url": "https://gitlab.com/...#note_2001",
              "body": "This lets a refund of 0 through.",
              "replies": [{"author": "bumindu", "body": "Looking at it.", "created": "2026-11-14T09:30:00Z"}]}]}
```

| Field | Rule |
| --- | --- |
| `me` | Your login on that host. Optional, but give it: a thread whose last word is yours is not new. |
| `prs[].url` | Needed. The PR link. The host, the repo and the number are read from it. |
| `prs[].state` | Needed. `open`, `merged` or `closed`. |
| `prs[].repo` | The chopchop name of the repo. Default: the name in the link. |
| `prs[].review` | `approved`, `changes-requested`, `commented` or `none` (default). |
| `prs[].title`, `head`, `base`, `author`, `draft` | Give them when the tool has them. `head` is needed to read the code and to commit a fix. |
| `threads[].id` | Needed. Starts with the PR id and a colon. Unique, and the same on every fetch. |
| `threads[].pr` | Needed. The id of a PR in this file. |
| `threads[].kind` | Needed. `inline` (on a line), `review` (a review's summary text), `general` (a PR comment). |
| `threads[].author`, `body`, `created` | Needed. The first comment of the thread, as written. |
| `threads[].file`, `line` | `file` is needed for `inline`: the path in the repo. `line` is a number or null. |
| `threads[].hunk` | The diff the comment was written on, when the tool gives it. |
| `threads[].resolved`, `outdated`, `bot` | `true` or `false`. Default `false`. |
| `threads[].replies` | The later comments of the thread, oldest first: `author`, `body`, `created`. |

Rules:

- A file is a full picture of each PR in it. Its threads replace the stored threads of that PR.
  Threads of other PRs stay.
- Any other field is an error, so a typo does not pass (`path` is not `file`).
- Every problem is listed in one run. Nothing is stored until the file is right.
- A PR the feature does not know yet is added. With no `--feature` and no feature that knows
  the link, the PR gets its own store under `_chopchop/prs/`.
- After you post a reply with your own tool, fetch and ingest again. chopchop sees that the
  last word is yours and marks the thread replied.

## What is left out, and what counts as settled

Both `--fetch` and `--ingest` do this, so the list holds review comments only:

- **Left out:** a thread where only the PR's author (or you) wrote. There is nothing to answer.
- **Left out:** a status report from a CI bot: a `general` comment from a known bot (coverage,
  deploy previews, dependency bots), or from any bot when the text starts with a hidden
  `<!-- marker -->` (the bot rewrites that comment on every push). A bot's comment on a line is
  always kept. In `chopchop.yaml`, `comments.ignore: [login]` leaves out more, and
  `comments.keep: [login]` keeps a bot's reports.
- **Settled:** `resolved` is true when the thread is resolved on the host, or when its PR is
  merged or closed. A settled thread is never new.

## `prs.json`

```json
{"prs": [{"id": "shop-api#12", "repo": "shop-api", "host": "github", "slug": "owner/shop-api", "number": 12,
          "url": "https://github.com/owner/shop-api/pull/12", "title": "Refund requests", "state": "open",
          "draft": false, "head": "feature/IDEA-1/build", "base": "feature/IDEA-1-refunds", "author": "bumindu",
          "review": "changes-requested", "fetched": "2026-11-14T10:00:00", "threads": 7}],
 "watch": {"on": true, "since": "2026-11-14T10:00:00", "last": "2026-11-14T10:05:00"}}
```

`host` is `github`, `gitlab`, `bitbucket` or `azure`. `fetched` is null until the PR was read
once. A PR added with `--pr <link> --path <folder>` also has `path`: where its repo is checked out.
`watch.last` is the last time `--wait` looked.

## `threads.json`

```json
{"fetched": "2026-11-14T10:00:00",
 "threads": [{"id": "shop-api#12:r2001", "pr": "shop-api#12", "repo": "shop-api", "kind": "inline",
              "file": "src/services/refundService.js", "line": 42, "hunk": "@@ -40,6 +40,9 @@ ...",
              "author": "asha", "bot": false, "created": "2026-11-14T09:00:00", "updated": "2026-11-14T09:30:00",
              "resolved": false, "outdated": false, "url": "https://github.com/...#discussion_r2001",
              "body": "This lets a refund of 0 through.",
              "replies": [{"author": "bumindu", "body": "...", "created": "..."}], "hash": "9f2c..."}]}
```

- A review thread is one thread with replies. `line` is the line now, or the first line it was
  written on when the diff changed since (`outdated`).
- `hunk` is the `@@` line and the last 12 lines of the diff. The commented line is the last one.
- `hash` is the sha1 of the body and every reply body, in order. Each text is trimmed, and the
  texts are joined with a newline and the byte `0x1e`. A new reply or an edit changes it.

A thread is **new** when it is not settled, and it has no triage item or the item's `hash`
differs from the thread's. An outdated thread that is not settled still counts: a reviewer can
answer on code that has changed.

## The triage answer (`--triage <file>`)

The triager writes `triage-in.json`. Only the comments in the pack need an item.

```json
{"items": {"shop-api#12:r2001": {
    "plain": "A refund of 0 passes the check.", "verdict": "real", "priority": "high", "group": "G1",
    "why": "Line 42 compares with >= 0, and rule R-2 says more than 0.",
    "evidence": ["shop-api/src/services/refundService.js:42"],
    "fix": "Compare with > 0 and add the test refuses_zero_refund.",
    "impact": "Only this check. The web form already blocks 0.",
    "reply": "Good catch. The check now refuses 0, and there is a test for it."}},
 "groups": [{"id": "G1", "title": "Zero and negative amounts pass",
    "plain": "Two comments say the amount check is too loose.",
    "threads": ["shop-api#12:r2001", "shop-web#7:r3110"], "verdict": "real", "priority": "high",
    "fix": "Tighten the check in the service and mirror it in the form.", "impact": "Service and form.",
    "files": ["shop-api/src/validators/amount.js"]}]}
```

| Field | Rule |
| --- | --- |
| `items.<id>` | The id of a thread in `threads.json`. |
| `plain`, `why` | Needed. Simple English. |
| `verdict` | `real`, `false-positive`, `negotiable`, `question`, `praise` or `outdated`. |
| `priority` | `high`, `medium` or `low`. |
| `group` | Needed. A group in this file, or an existing group. Every thread is in exactly one group. |
| `evidence` | A list of `repo/path:line`. At least one for `real` and `false-positive`. |
| `fix`, `impact` | Needed for `real`. Else text or null. |
| `reply` | Needed, except for `praise` and `outdated`. |
| `groups[].id` | `G1`, `G2`, ... An existing id changes that group. A new id needs at least one thread. |
| `groups[].title`, `plain`, `verdict`, `priority` | Needed. `fix` and `impact` are needed for `real`. |
| `groups[].threads` | The thread ids in the group. It must list every item that names the group. |
| `groups[].files` | Optional. Files the fix changes, as `repo/path`, that no comment of the group sits on. |

The script refuses the file when a rule is broken, and says each problem in a line. Wording
(long sentences, long dashes, filler words) only gives warnings.

## `triage.json`

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

The script owns these fields:

| Field | Meaning |
| --- | --- |
| `decision` | The person's call: `fix`, `reply`, `skip`, or null. Set with `--decide`. |
| `state` | `triaged`, `fixing` (in a fix batch), `fixed`, `replied`, `closed` (the thread is settled). |
| `hash` | The thread's hash when it was explained. |
| `commit` | The commit that holds the fix. |
| `was` | Only when the comment changed after a decision: the old decision. The item is `triaged` again and `decision` is null. |
| `groups[].files` | The files of the group's comments as `repo/path`, plus the `files` the triager gave. |
| `groups[].order` | 1 is the most urgent. High before medium before low, then real, question, negotiable, false-positive. |
| `groups[].with` | Other groups that touch one of the same files. They are fixed together. |

A decision and a `fixed` or `replied` state stay when the thread's hash did not change.

## `fix/plan.json`

```json
{"made": "2026-11-14T10:20:00",
 "batches": [{"id": "B1", "pr": "shop-api#12", "repo": "shop-api", "branch": "feature/IDEA-1/build",
              "groups": ["G1", "G2"], "threads": ["shop-api#12:r2001", "shop-api#12:r2002"],
              "files": ["src/services/refundService.js"], "state": "planned", "commit": null,
              "brief": ".../fix/B1/brief.md", "report": ".../fix/B1/report.json", "path": "/code/shop-api"}]}
```

Groups that share a file are in one batch. A batch is for one PR, so a group with comments in
two repos gives two batches. `state` is `planned`, `committed` or `fixed`.

The builder's `report.json`:

```json
{"batch": "B1", "ok": true, "blocked": null, "files": ["src/services/refundService.js"],
 "tests": ["refuses_zero_refund"], "notes": "The check now refuses 0.", "commit": "fix: refuse zero refunds"}
```
