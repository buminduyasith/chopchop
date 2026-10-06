---
name: requirements
description: Pull BA stories from the tracker (Jira today, any provider by config) into the Relay workspace and turn them into analysed requirements. Use when the user gives an epic id or a list of story ids, asks to fetch, sync, refresh or update requirements or stories, or says a story changed in Jira. Creates _relay/features/<feature>/requirements/ on the first run and updates it on later runs.
argument-hint: "<EPIC-ID> | <STORY-ID,...> --feature <name> | --feature <name> [--fresh] [--dry-run]"
---

# Requirements

Turn stories in the tracker into a requirements folder that people and agents can trust:
one file per story, acceptance criteria with stable IDs, open questions for the BA, and a
report of what changed since the last sync.

The work is split on purpose:

- **The script does the fetching and syncing.** Same result every time. It owns the front
  matter, the `Source` block and the index. It never touches your analysis or notes.
- **You (the agent) do the thinking.** Acceptance criteria, questions, summary, impact.

All paths below are relative to this skill's base directory. Run the script with `python3`.

```
python3 scripts/relay_req.py <command> ...
```

## 1. Read the request

Work out from the user's words:

| They gave | Run |
| --- | --- |
| An epic id (`PAY-120`) | `pull --epic PAY-120` |
| Story ids (`PAY-121, PAY-122`) | `pull --stories PAY-121,PAY-122 --feature <name>` |
| An epic plus extra stories | `pull --epic PAY-120 --stories PAY-200` |
| Only a feature name, or "refresh / sync" | `pull --feature <name>` (re-sync from the saved source) |
| One story to refresh in a feature | `pull --stories PAY-121 --feature <name>` |

Story lists need a feature name. If the user did not give one, run `features` to show what
exists, then ask: "Which feature should these stories go into? Pick one above or give a new
name (for example `refund-flow`)." Pasted Jira links are fine; the script takes the id from them.

Flags: `--fresh` rebuilds the story files from scratch (only `keep` blocks survive, and the
old version is in git history). Use it only when the user asks. `--dry-run` shows what would
change and writes nothing. Use it when the user asks "what changed?" without wanting an update.

## 2. Make sure the workspace is set up

Run `python3 scripts/relay_req.py doctor`.

- **No relay.yaml:** ask which tracker they use (default Jira) and whether they want REST or
  MCP (see below). Then run `init --provider <name>`. It creates `_relay/relay.yaml` at the
  root of the current git repo and adds `_relay/` to `.gitignore`. Show the user the
  environment variables it prints.
- **Env vars missing:** tell the user which ones and how to set them. **Never ask for a token
  in chat and never write one to a file.** Suggest they run `! export RELAY_TRACKER_TOKEN=...`
  or add it to their shell profile.
- **Connection fails:** show the error in plain words. If it is an auth error and an Atlassian
  MCP server is connected in this session, offer MCP mode as a way forward.

REST or MCP: REST (`mode: rest`) is the default. The script calls the API with a token.
MCP (`mode: mcp`) is for teams who already have the tracker's MCP server connected and do not
want a token on disk. Both end in the same sync.

## 3. Fetch and sync

**REST mode.** Run the `pull` command from step 1.

**MCP mode.** Follow `providers/<provider>/MCP.md`. In short: fetch the epic and every child
issue with the MCP tools, save the raw payloads to a temp JSON file, then run
`ingest --input <file> --format raw --epic <id> --full` (drop `--full` when you only fetched
some of the stories). If the MCP tool returns a shape the provider cannot read, map it to
`providers/SCHEMA.md` yourself and use `--format normalized`.

The script prints a summary. The full detail is in
`requirements/sync-report.md` (with diffs for changed stories) and
`requirements/.source/last-sync.json`.

## 4. Analyse each story in "Analyse:"

For every story id listed under **Analyse** (new, changed, or never analysed), open
`requirements/stories/<ID>.md`, read its `Source` block, and write the sections above it.
Read `reference/story-format.md` first; it has the rules and a full example. The short version:

- **Acceptance criteria.** One testable behaviour per line, ID `<STORY>.AC<n>`.
  - IDs never change and are never reused. Other files (design, tasks, tests) point at them.
  - Wording changed in the source: keep the ID, update the text, add `(changed YYYY-MM-DD)`.
  - New criterion: next unused number.
  - Criterion removed from the source: keep the line, strike it through, add `(removed YYYY-MM-DD)`.
  - No explicit criteria in the tracker: derive them from the description, mark each
    `(derived)`, and add a question asking the BA to confirm them.
  - Keep the BA's wording where it is already clear. Do not invent scope.
- **Open questions.** Gaps a developer would hit: unclear rules, missing error cases, limits,
  permissions, conflicts between the description and the comments. Also add each one to
  `requirements/questions.md` with a stable id (Q1, Q2...). Do not renumber old questions.
- **Comments count.** Decisions made in comments are requirements too. Reflect them in the
  criteria and cite the comment (author and date).
- Never edit inside `<!-- relay:... -->` blocks or `<!-- keep -->` blocks.

Then record the analysis so the story leaves the list:

```
python3 scripts/relay_req.py mark-analysed --feature <name> --stories PAY-121,PAY-122
```

Only mark a story after you have actually written its criteria.

For a big epic (more than about 8 stories to analyse), analyse in batches and tell the user
the progress between batches.

## 5. Changed and removed stories: find the impact

For each changed or removed story, search the feature folder for its AC ids:

```
grep -rn "PAY-121.AC" _relay/features/<name>/design _relay/features/<name>/tasks 2>/dev/null
```

Write what you find under `## Impact` in `requirements/sync-report.md`: which design sections
and tasks point at a changed or removed criterion. If `feature.yaml` shows the feature is past
the requirements stage, say clearly that the design or tasks may need an update. Do not change
the stage yourself.

## 6. Summary and reply

- Update `## Summary` in `requirements/overview.md` (outside the relay blocks): what the
  feature is for, who it serves, the main rules, what is out of scope. Five to ten lines.
- If `_relay/style.md` exists, follow it in everything you write.
- Reply to the user in this order: what was synced (counts), what changed and why it matters,
  the open questions for the BA (short list), and the next step (usually
  "review the stories, then run the design skill").

## Rules

- The tracker is the source of truth for the story text. The folder is the source of truth
  for the analysis. Never write back to the tracker from this skill.
- Never delete story files. Removed stories stay, marked removed.
- If the script fails, show the error and the fix in plain words. Do not work around it by
  writing story files by hand.
- To support another tracker, see `providers/README.md`. The skill steps do not change.
