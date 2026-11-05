---
name: learn
description: Build or refresh the system map, so chopchop knows the whole system before it designs. It maps every repo in chopchop.yaml with helpers: APIs, events, tables, outside systems, who owns what, the patterns each repo follows, and how the parts connect, each with a citation of the code. Later runs read only what git diff says changed. Use when the user runs learn, asks chopchop to learn or map the system, after a big change in a repo, or when design says the map is missing or old.
argument-hint: "[repo ...]"
---

# Learn

Map the whole system once, then keep it fresh. The map is
`_chopchop/system/system-map.json`, and `system-map.md` beside it is the version people read.
`/chopchop:design` reads it before every design, so it knows what exists, who owns it and
what talks to what.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_learn.py`. Run it with `python3` from the
user's project folder. It needs the `tasks` skill folder next to it.

| User types | Do this |
| --- | --- |
| nothing | Every repo that is new or changed. |
| `payments-api web-app` | Only those repos (`--repo` for each). |

## 1. Look

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_learn.py --prepare --json
```

Each repo gets a mode:
- `full`: never read. Read the whole repo.
- `refresh`: read before. Read only the `changed` files, plus what they touch.
- `fresh`: nothing changed. Skip it.
- `missing`: the path is not a git repo. Tell the user and skip it.

It also gives each repo's `owners` (from CODEOWNERS), `candidates` (OpenAPI, proto, GraphQL,
AsyncAPI, migrations, ADRs, guides), `languages` and the `update_file` to write. If every
repo is fresh, say "The system map is up to date." and stop.

## 2. Helper settings (first time only)

If `chopchop.yaml` has no `agents:` block, ask the 3 helper questions once, before any
helper starts, as the design skill does in its step 2 (also when design runs with `--auto`),
and save them with its script:
`python3 ${CLAUDE_SKILL_DIR}/../design/scripts/chopchop_design.py --helpers --max N --model M --effort E`.

## 3. Read the repos

Use one `chopchop:explorer` helper per repo to read, at most `agents.max` at the same time.
With `agents.max: 0`, or with only one repo to read, read it yourself. Tell the user the plan
in one line first, such as "Reading 4 repos with 3 explorers at a time."

Pass `model` and `effort` on each call from the settings (`calls.explorer` in
`chopchop_design.py --prepare --json`). Leave a value out when it is `inherit`. Give each
explorer this brief, filled in:

> Mode: system. Repo: `<name>` at `<path>`. Mode for this repo: `<full or refresh>`.
> Changed files: `<list, for refresh>`. Read first: `<candidates>`.
> Write the update JSON to `<update_file>` in the shape of
> `${CLAUDE_SKILL_DIR}/SCHEMA.md`, then reply with a 5 line summary.

Explorers write their own files and reply with a short summary only. Do not paste their
files into the chat.

## 4. Merge

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_learn.py --write <update files>
```

If it says an update has problems, send the problems back to that explorer (or fix the file
yourself) and run it again. It never writes a broken map.

## 5. Reply

Two or three lines: how many repos, parts and links, anything surprising (a service nobody
mentioned that listens to an event, a repo with no CODEOWNERS), and the path to
`system-map.md`. People can fix an entry in the JSON and mark it `"source": "person"`.
chopchop never overwrites those.

## Rules

- Read only. Never change code, never run builds or tests, never push.
- Every pattern, part and link should carry a citation: `repo/path:line@commit`. The commit
  is the repo's HEAD when you read it.
- Never read or copy secrets. Skip `.env` files, key files and anything that looks like a
  credential.
