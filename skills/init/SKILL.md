---
name: init
description: Set up chopchop for a team. Asks a few questions and writes _chopchop/chopchop.yaml with the base branch, the code repos, and each repo's code style file (found, written for them from the code, or none). Use when the user runs init, says set up, configure or init chopchop, wants to change repos, styles or the base branch, or when another chopchop skill finds no chopchop.yaml. Safe to run again; it keeps a backup.
argument-hint: "(no arguments)"
---

# Init

Set chopchop up in a few questions, then write `_chopchop/chopchop.yaml`. Keep chat short: ask with
the question tool, not in long text. Never ask for tokens or passwords.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_init.py`. Run it with `python3` from the
user's project folder.

## 1. Look

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_init.py --detect --json
```

It finds the git repos here and next to this one, their branches, style files and guides,
and any `chopchop.yaml` that already exists. If one exists, say in one line that you will update
it (a backup is kept) and make its current values the recommended answers.

## 2. First questions

Ask these three in one go with the question tool. Put the recommended option first, with
"(Recommended)" at the end of its label.

1. **Where should chopchop keep its files?** Use `workspace_options`. Recommend the shared
   folder next to all the repos when there is more than one repo, otherwise the one inside
   this repo.
2. **Which branch do you work from?** `suggested_base` first, then the other branches from
   `base_candidates`. Feature branches are cut from it, and only people merge back into it.
3. **Which repos does this team work in?** (multi-select) The current repo first, then the
   others found. The tool shows at most four options: if there are more, name the rest in
   the question text and say "pick Other to type more names".
Use `suggested_team` as the team name without asking. The user can change it later.

## 3. Code style, one question per repo

Ask in one go, up to four repos per call: **"Code style for <repo>?"**

- "Use `<file>`", for each style file found in that repo (up to two). Recommend it when found.
- "Write one from the code": recommend this when none was found.
- "None, follow the existing code".

The user can pick Other and type a path. It can be relative to the repo, relative to
`_chopchop/`, or absolute.

**For "Write one from the code"**, do this for each such repo:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_init.py --style-skeleton <repo> --repo-path <path> --workspace <_chopchop path>
```

Then fill in every section of `_chopchop/styles/<repo>.md`. Read the repo's guides, its
formatter and linter configs, and four or five real files from different layers, plus two
tests. Write short rules that you actually saw, each with a file to look at. Do not invent
rules. Mark anything unsure with "(check)". Use `styles/<repo>.md` as that repo's style.

## 4. Write

Put the answers in a temp file:

```json
{"workspace": "/work/_chopchop", "team": "payments", "base_branch": "dev",
 "repos": [{"name": "payments-api", "path": "/work/payments-api", "style": ["docs/code-style.md"]},
           {"name": "payments-web", "path": "/work/payments-web", "style": []}]}
```

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_init.py --write <answers.json>
```

If it fails, fix the answer it names (often a style path) and run it again.

## 5. Learn the repos (one more question)

Ask: **"Learn each repo's build, test and PR steps now?"**

- "Yes, now (Recommended)"
- "Later, on the first task"

On yes, for each repo run:

```
python3 ${CLAUDE_SKILL_DIR}/../code/scripts/chopchop_code.py --profile <repo>
```

Check and fill in each profile the way `/chopchop:code` step 2 says: the commands, the rules,
and how PRs are opened. Show them together and ask once whether they are right. On yes,
run `--profile <repo> --confirm` for each.

## 6. Reply

Keep it short:

1. Where `chopchop.yaml` is, and the backup if there was one.
2. A table: repo, path, code style.
3. The base branch.
4. For style files you wrote: ask the team to read them once. Suggest moving a good one into
   its repo later and pointing `style:` at it.
5. Next step: `/chopchop:stories PAY-120` to bring in an epic's stories, or
   `/chopchop:tasks <design files>` to cut tasks.

## Rules

- Never ask for, show or store tokens or passwords.
- Do not change code repos. Style files you write go in `_chopchop/styles/`. The only change in
  a repo is the `_chopchop/` line in `.gitignore` when the folder sits inside that repo.
  Mention it.
- Running init again changes only what the user answers. It keeps extra settings and saves
  `chopchop.yaml.bak`.
