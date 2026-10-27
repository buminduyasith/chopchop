---
name: relay-requirements
description: Sync a Jira epic (or any tracker, by config) into the Relay workspace as one requirement.md with every story as it is in the tracker. Use when the user gives an epic id, asks to fetch, sync or resync requirements, says a story changed in Jira, or passes -rs. Creates _relay/<NNN-EPIC-name>/requirements/requirement.md and updates it on resync.
argument-hint: "<EPIC-ID> [--name <folder>] | -rs [<number|epic|name>|all] | --list"
---

# Requirements sync

Copy an epic and all its stories from the tracker into one Markdown file, without changing
the text. A script does all the work so the result is the same every time. Your job is to
run it, handle setup, and tell the user what changed.

```
_relay/
├── relay.yaml
├── 001-PAY-120-refunds-for-customers/
│   └── requirements/requirement.md
└── 002-LOY-1-loyalty-points/
    └── requirements/requirement.md
```

Later stages add their own subfolder to the same feature folder (`design/`, `tasks/`), so a
number always means the same feature.

All script paths below are relative to this skill's base directory. Run it with `python3`
from the user's project folder (the script finds `_relay/` from there).

## 1. Run what the user asked

Pass the user's arguments straight through, plus `--diff`:

```
python3 scripts/relay_req.py $ARGUMENTS --diff
```

`--diff` adds the before and after text under every change, so you can explain it in step 3.

| User typed | What happens |
| --- | --- |
| `PAY-120` (or a Jira link) | Creates `NNN-<EPIC-KEY>-<epic-title>/requirements/requirement.md`. If the epic already has a folder, it resyncs that one instead. |
| `PAY-120 --name refunds` | Same, named `NNN-PAY-120-refunds` (new features only). |
| `-rs 1` / `-rs 001` / `-rs PAY-120` / `-rs refund` | Resyncs that feature. |
| `-rs` | Resyncs the only feature. If there are several, the script lists them: show the list and ask which one. |
| `-rs all` | Resyncs every feature. |
| `--list` | Lists features. |
| nothing | Run `--list`, then ask for an epic key or a feature to resync. |

Add `--dry-run` when the user only asks "what changed?" without wanting the file updated.

## 2. If setup is missing

The script stops with a clear error. Fix it in this order:

- **No relay.yaml:** ask which tracker they use (default Jira) and REST or MCP (see below).
  Run `--init --provider <name>`. It creates `_relay/relay.yaml` and adds `_relay/` to the
  code repo's `.gitignore`. Show the env vars it prints.
- **Env vars missing or auth fails:** run `--doctor` and explain the result in plain words.
  **Never ask for a token in chat and never write one to a file.** Suggest
  `! export RELAY_TRACKER_TOKEN=...` or their shell profile.
- **Connection fails and an Atlassian MCP server is connected:** offer MCP mode.

REST (`tracker.mode: rest`, the default) means the script calls the API with a token. MCP
(`mode: mcp`) means you fetch with the tracker's MCP tools and the script only writes the
file: follow `providers/<provider>/MCP.md`, which ends with `--ingest <file>`.

## 3. Reply

**New feature:** one or two lines. The folder, the file path, how many stories, and the
next step ("read it through, then run the design skill").

**Resync with no changes:** one line. "Nothing changed in Jira since <date>. The file is
the same."

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

Also mention any warnings in plain words. The common one is that the acceptance criteria
field was not found. Then tell them to set `tracker.jira.fields.acceptance_criteria` in
`relay.yaml`.

Explain the changes, but do not rewrite or summarise the stories in the file. The file is
the copy of the tracker. Analysis and design come in later skills.

## Rules

- Never edit `requirement.md` by hand. A resync rewrites it. Notes go in `notes.md` in the
  same folder, which the script never touches.
- The tracker is the source of truth. This skill never writes back to it.
- If the script fails, show the error and the fix. Do not work around it by writing the file
  yourself.
- To support another tracker, see `providers/README.md`. These steps do not change.
- If `_relay/style.md` exists, follow it in your reply.
