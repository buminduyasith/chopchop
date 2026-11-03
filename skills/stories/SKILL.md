---
name: stories
description: Copy an epic and all its stories, as they are, into the chopchop workspace as one requirement.md, from whatever tracker the team uses. Use when the user gives an epic id or link, asks to fetch, sync or resync requirements or stories, says a story changed, or passes -rs. Creates _chopchop/<NNN-EPIC-name>/requirements/requirement.md and updates it on resync.
argument-hint: "<epic id or link> [--name <folder>] | -rs [<number|epic|name>|all] | --list"
---

# Stories

Copy an epic and all its stories into one Markdown file, without changing the text. You get
the stories with what the team already has. A script writes the file and works out what
changed, so the result is the same every time.

```
_chopchop/
├── chopchop.yaml
├── 001-PAY-120-refunds-for-customers/
│   └── requirements/requirement.md
└── 002-LOY-1-loyalty-points/
    └── requirements/requirement.md
```

Later stages add their own subfolder to the same feature folder (`design/`, `tasks/`), so a
number always means the same feature.

The script is `${CLAUDE_SKILL_DIR}/scripts/relay_req.py`. Run it with `python3` from the
user's project folder (it finds `_chopchop/` from there). If there is no `chopchop.yaml` yet,
run `/chopchop:init` first.

| User typed | What happens |
| --- | --- |
| `PAY-120` (or a link) | Steps 1 to 3: a new feature folder, or a resync if the epic already has one. |
| `PAY-120 --name refunds` | Same, named `NNN-PAY-120-refunds` (new features only). |
| `-rs 1` / `-rs PAY-120` / `-rs refund` / `-rs all` | Resync: `-rs <ref> --json` says which epic(s) to fetch, then steps 1 to 3 for each. |
| `-rs` | Resyncs the only feature. With several, the script lists them: ask which one. |
| `--list` or nothing | `--list`, then ask for an epic or a feature to resync. |

## 1. Get the epic and its stories

Use the first way that works. Do not set anything up:

1. **A tool connected to this session** that reads the team's tracker (for example an MCP
   server for their issue tracker). Look at the tools you have.
2. **A CLI that is already installed and logged in**, if the repo's guides mention one.
3. **A file the user gives** (an export, a CSV, a Markdown or text file), or text they
   paste into the chat.

If none works, ask the user: "How can I read epic PAY-120? You can connect your tracker's
tool, or paste or attach the epic and its stories." Never ask for a token or password.

Get the epic and every story under it, in the tracker's order: title, description,
acceptance criteria, status, and the other fields `${CLAUDE_SKILL_DIR}/SCHEMA.md` lists, plus
the link to each one. Copy the text as it is. Turn rich text into Markdown, but do not
summarise or fix it.

## 2. Write it

Write the JSON to a temp file in the shape of `SCHEMA.md` (set `provider` to the tool or
way you used), then run:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/relay_req.py --ingest <file> --diff [--name <folder>]
```

It creates the feature, or updates the one this epic already has. `--diff` adds the before
and after text under every change, so you can explain it in step 3. Add `--dry-run` when
the user only asks "what changed?" without wanting the file updated.

## 3. Reply

**New feature:** one or two lines. The folder, the file path, how many stories, and the
next step ("read it through, then run the design skill").

**Resync with no changes:** one line. "Nothing changed in the tracker since <date>. The
file is the same."

**Resync with changes:** explain what changed so the user gets the idea without opening the
file. Read the before and after text under each change in the report, then write:

1. **One sentence first** with the big picture. For example: "The BA tightened the refund
   window and added one new story. One story was taken out."
2. **One short bullet per story**, most important first:
   - Say what is different in everyday words, with the real values: "Refund window is now
     14 days (was 30)", not "acceptance criteria changed".
   - Say what it means for the team when that is clear: "the button logic and its tests
     need the new limit".
   - New story: one line on what it asks for. Removed story: say it is out of this epic now.
3. **Status moves** (for example To Do to Ready) go in one short line at the end, grouped.
   They are not requirement changes, so keep them small.
4. If a change looks unclear or conflicts with another story, say so in one line, as a
   question to ask the BA. Do not guess.

Keep it simple: short sentences, no jargon, no diff symbols, no hashes. Do not repeat
whole stories. If more than about 8 stories changed, group them ("6 stories got small
wording fixes") and give detail only for the ones that change behaviour.

Example, from a resync where PAY-121's criteria changed, PAY-124 was added and PAY-123 left
the epic:

> Feature 001 (refunds) is updated. The refund rules got stricter, there is one new
> story, and one story was taken out.
>
> - **PAY-121 Request a refund:** customers now have **14 days** to ask (was 30), and they
>   must **give a reason**. The minimum amount is the same.
> - **PAY-124 Refund to wallet (new):** customers can take the refund as wallet credit
>   instead of money back to the card. It must show up within 1 minute.
> - **PAY-123 Partial refunds (removed):** no longer part of this epic.
>
> Status: PAY-121 moved from In Progress to Ready.
>
> Question for the BA: does the 14-day window also apply to wallet refunds?

Also mention any warnings in plain words.

Explain the changes, but do not rewrite or summarise the stories in the file. The file is
the copy of the tracker. Analysis and design come in later skills.

## Rules

- Never edit `requirement.md` by hand. A resync rewrites it. Notes go in `notes.md` in the
  same folder, which the script never touches.
- The tracker is the source of truth. This skill never writes back to it.
- If the script fails, show the error and the fix. Do not work around it by writing the file
  yourself.
- Never ask for, store or set up tokens, logins or tools. Use what is already there.
- If `_chopchop/style.md` exists, follow it in your reply.
