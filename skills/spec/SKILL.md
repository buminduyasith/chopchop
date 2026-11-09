---
name: spec
description: Turn an approved design into the full plan to build, test and finish a feature, written for people and for agents. Reads the code in each repo, then writes spec.md (21 sections in 4 parts, simple English, no length cap) and spec.json (rules with examples, every file, code to copy, existing methods to reuse, sketches of new code in the repo's own style, contracts, unit tests by name, end-to-end journeys, manual checks, and work packages that become tasks). Checks it against the code, and tracks each proof to done. Use when the user runs spec, wants a spec, a technical spec, an implementation plan or a build plan for a feature, wants to see what is built and proved, signs a manual check, or sets a feature to done. --auto asks nothing.
argument-hint: "[feature] [--auto] | --status | --sign M1 --by NAME | --done --by NAME | --open"
---

# Spec

The design decided what to build. The spec says exactly how: which files, which code to copy,
which tests prove it, and how we know it is done. Tasks are cut from the spec, never from the
design. Write it for two readers at once: a developer new to the repo, and an agent that will
build one package with nothing else open.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_spec.py`. Run it with `python3` from the
user's project folder. It needs the `tasks` skill folder next to it. Read these before you
write: `${CLAUDE_SKILL_DIR}/SCHEMA.md` (the spec.json shape), `references/code.md` (code that
fits the repo) and `references/writing.md` (words people can read).

## What the user typed

| You see | Do |
| --- | --- |
| nothing, or a feature | The whole run, steps 1 to 9. |
| `--auto` | The same, with no questions. Every guess goes in `assumptions`. |
| `"notes"` on an existing spec | Change the spec from the notes, build, and say what changed. |
| `--status` | `--status <ref>`: what is planned, built, proved. |
| `--sign M1 --by "Asha"` | Only when the user says that person checked it. Then `--status`. |
| `--done --by "Asha"` | Only when the user says to. A person sets done, never you. |
| `--open` | `--open <ref>`. |

## 1. Prepare

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_spec.py --prepare <ref> --json
```

- No design: stop. Say the spec is built from a design, and offer `/chopchop:design`.
- Design not approved: say so in one line, and go on. The lead can approve while you write.
- A repo with no profile (`_chopchop/repos/<repo>.md`): its tests have no run command. Offer
  to make it with `/chopchop:code --profile <repo>`, and use the commands it finds.
- Helper settings not set: ask the 3 helper questions once, the way the design skill does,
  even with `--auto`. Then `--plan <size> --repos <repos>` and say its line.

## 2. Read the code

The goal is code that looks like it was always there. For each repo the design changes, find:

1. **The nearest similar feature.** Its folders, file names, class and method names, how it
   checks the caller, handles errors, logs, saves, and how its tests look.
2. **The exact files** to create or change, and why each one.
3. **Existing methods and types to reuse**, with where they live. Never plan a new helper when
   one exists.
4. **The team's style file**, if `chopchop.yaml` sets `repos.<name>.style`, and the rules in it
   that apply.
5. **How tests are named and run**: the unit test command, and the e2e suite (CI files,
   package scripts, Makefile, README). Note the command and where you found it.
6. **Traps**: code that looks reusable but is the wrong pattern (the way options.md did not
   pick, something deprecated, another team's area).

Every fact about code is a citation: `repo/path:12-17@abc1234`, read at the repo's HEAD.
Reuse the design run's reports in `work/reports/` first. For medium and large features, start
one `chopchop:explorer` per repo in mode `spec`, with the repo, its style file and the output file.
For small ones, read it yourself. Save what you learn in `work/reports/spec-<repo>.md`.

## 3. Ask only when needed

Ask only what the code and the design cannot answer: the code disagrees with the design, or a
value is missing (a limit, a message text, test data, who signs a manual check). At most one
round, at most 4 questions, each with answers to pick and your pick first. With `--auto`, take
your pick and add it to `assumptions`. Never ask what you could look up.

If the code shows the design will not work, do not quietly change the plan. Say what you found,
show the option from options.md that fits better if there is one, and ask. With `--auto`, add a
blocking question for the lead.

## 4. Write spec.json

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_spec.py --scaffold <ref>
```

Fill `spec/spec.json` as `SCHEMA.md` says:

- **rules**: every story and AC becomes one or more rules. Each says what is possible, what
  shows it was met (with a real value), and at least one Given/When/Then example. Put the
  error cases in examples too.
- **repos**: per repo, where new files go, names copied from the neighbors, an example test
  name, the style rules that apply, and what not to do.
- **contracts**: every request, response, event, shared type or table that two packages share,
  with an exact example.
- **packages**: the build plan. Follow `references/code.md`, and these rules:
  - One repo per package. Size S (about half a day) or M (about a day): roughly 4 to 12
    files and 150 to 500 changed lines, tests included. Split anything bigger.
  - Wave 0 is contracts: the shared types, schemas, migrations and stubs others code
    against. Wave 1 is slices that run in parallel. Wave 2 joins slices, only if needed.
    A package depends only on earlier waves.
  - Two packages in the same wave and repo never touch the same file.
  - Each package has `copy` (the closest code), `reuse` (existing methods), `sketch` (the new
    code in the repo's style), `tests` (names in the repo's style, with values) and `run`.
  - Every failure answer in `design/flow.json` gets a test: put `"2.twice"` in that test's
    `failures`. A risk a person accepted needs no test.
- **journeys**: the end-to-end paths a user takes, 1 to 4 for most features. Steps in plain
  words (do, see), test data, the repo whose e2e suite runs it, the run command and the test
  file. A repo with no e2e suite: make it `manual` with the person who signs it.
- **checks**: manual checks only for what no test can do (a migration on a copy of real data,
  a look at an email). Each has steps and the person who signs.
- **questions** and **assumptions**: anything still open, with an owner. A blocking question
  stops the build.

## 5. Write spec.md

Write the prose sections (1, 2, 3, 5, 8, 10, 12, 13, 19) as `references/writing.md` says. Each
starts with `**In short:**` and one or two lines. There is no length cap: write what a new
developer needs, and nothing that says nothing. Do not edit the generated blocks.

## 6. Build

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_spec.py --build <ref>
```

It checks spec.json against the stories, the design's failure answers and the code (every
citation, every reused name, every file path), fills the 13 generated blocks, lints spec.md
and adds the Spec tab to feature.html. Exit 0 means ready. Exit 1 lists what blocks it: fix
each one and build again, at most 3 rounds, then tell the user what is left. Exit 2 means an
input file is broken.

## 7. Cold read

Start one `chopchop:reviewer` with lens `cold-read`. Give it only the path of spec.md and the
repo paths. It picks the two hardest packages and lists every question it would have to ask
before building them. For medium and large features, start a second one with lens
`test-gaps`: the inputs and failures no test covers. Fix the real gaps in spec.json or
spec.md. Questions only the user can answer go in `questions`. Build again. The goal is zero
cold-read questions.

## 8. Reply

Keep it short:

1. One line: rules, packages, repos, tests, journeys.
2. What is still open: questions, warnings you left, a design that is not approved yet.
3. The page: `feature.html`, Spec tab.
4. Next: `/chopchop:tasks <ref>` cuts one task per package, and one prove task per journey.

## Later

- `--status` shows what is planned, built (its task is merged) and proved (its checks passed).
  `/chopchop:code --verify` saves the results, so status needs nothing else.
- When the design changes after the spec, run the spec again. Keep every id. If tasks exist,
  do not rewrite them: tell the user which packages changed, and let the tasks skill decide.
- A person sets the feature to done with `--done --by NAME`, only when every proof passed.

## Safety rules

- Read only in the repos. Never change code, never run their tests, never push.
- Never ask for, store or put secrets in the spec. Code you copy is masked if it looks like a
  key or a password.
- Never sign a check or set done for a person.
