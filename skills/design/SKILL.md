---
name: design
description: Turn the approved brief, or an idea and the feature's stories, into a short design a lead can approve. Reads the brief and the grooming answers first, learns the existing system, asks at most 2 short rounds of questions with answers to pick, keeps every real choice in options.md, draws a high-level design and a main flow with the diagram skill, checks every claim against the code, and writes design.md in Markdown with a Summary on top, plus a short review message to send the lead. Use when the user runs design, wants a design, a technical design or a solution for a feature or an idea, wants to change a choice, has feedback from a lead, or wants to record an approval. --auto does it with no design questions.
argument-hint: "<idea, file or image> [--auto] | \"lead's notes\" | --pick 2=B | --approve \"Name\" | --open"
---

# Design

Write the design a lead approves before anyone builds. You do the thinking: what the developer
wants, how the system works today, the real choices, the words. A script does what must be the
same every time: it checks the files, draws the diagrams, checks every citation against the
code, lints the text and prints the review message. Everything it writes is Markdown. The live
dashboard (`/chopchop:dashboard`) shows it, so there is no page to build.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_design.py`. Run it with `python3` from the
user's project folder. It needs the `tasks` skill folder next to it. The file shapes are in
`${CLAUDE_SKILL_DIR}/SCHEMA.md`. Read the three references before you write:
`references/questions.md`, `references/writing.md` and `references/diagrams.md`. The two
diagrams follow the diagram skill (`${CLAUDE_SKILL_DIR}/../diagram/SKILL.md`).

| User types | Do this |
| --- | --- |
| an idea, a file, or a pasted image | Steps 1 to 11. |
| the same, with `--auto` | Steps 1 to 11 with no design questions: see "--auto" below. With no helper settings yet, the recommended ones are saved (step 2). |
| nothing | Go on from where the last run stopped (`--prepare` shows it). |
| text, when the feature already has a design | It is feedback, such as a lead's notes: see "Feedback". Say in your first line how you read it. |
| `--pick 2=B` | `chopchop_design.py --pick 2=B`, then fix the prose the pick touches and build again. |
| `--approve "Name"` | See "Approve". |
| `--open` | `chopchop_design.py --open`. It starts the dashboard and prints its link. With no dashboard skill it prints the path of design.md. |

## 1. Load

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_design.py --prepare --json
```

- **No stories** (`requirements.stories` is empty): write what the idea asks for as rules in
  the stories shape, with the epic id `IDEA-<next feature number>` and story ids `R1`, `R2`,
  and so on, each with acceptance criteria. Ingest them with
  `python3 ${CLAUDE_SKILL_DIR}/../stories/scripts/chopchop_stories.py --ingest <file> --name <short-name>`.
  You confirm them in round 1.
- **More than one feature**: the script asks which one. Pick the one that matches the idea,
  or ask.
- **A brief or grooming notes** (`brief.exists`, `grooming.exists`, the `Brief:` and
  `Grooming:` lines): read `requirements/brief.md` and `requirements/grooming.md` first, before
  anything else. Three rules:
  - The brief wins on **what to build**. Something the brief puts out of scope stays out, even
    when a story mentions it.
  - `requirements/requirement.md` wins on **exact wording**: a limit, a message text, a name.
  - An answer in grooming is a **decision already made**. Never ask it again, in round 1 or
    round 2. Use it, and cite it as "grooming Q3" where the design leans on it.
  A brief that is not approved yet: say so in one line, and go on.

## 2. Helper settings (first time only)

If `helpers.ask` is true, this team has never set them (an older `chopchop.yaml` has no
`agents:` block). Never tell the user to run init again. Ask these three once, in one
question call, before any helper starts, and save the answers. A helper started with no
settings runs on the chat's own model, which can be the most expensive one.

**With `--auto`, ask nothing:** save the recommended answers
(`--helpers --max 3 --model inherit --effort inherit`), then say in one line that you did and
how to change them (run init again, or edit `agents:` in `chopchop.yaml`).

1. "How many helpers can chopchop run at the same time?" 3 (Recommended), 5, 1, "0, no helpers".
2. "Which model should helpers use?" "Same as this chat (<name the model you run on>)
   (Recommended)", Sonnet, Opus, Haiku. Say in the description that explorers mostly read
   code, so a smaller model costs less and works well for them.
3. "How hard should helpers think?" "Default (Recommended)", medium, high, xhigh.

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_design.py --helpers --max 3 --model inherit --effort inherit
```

"Same as this chat" and "Default" are `inherit`. It adds only the `agents:` block and keeps a
`.bak`. Then say the saved settings in one line, and how to change them later: run init
again, or edit `agents:` in `chopchop.yaml`.

## 3. The system map

If `system_map.exists` is false, or `system_map.stale` lists repos, follow the learn skill
(`${CLAUDE_SKILL_DIR}/../learn/SKILL.md`, steps 1, 3 and 4) for those repos first. A refresh
reads only what changed, so it is quick. Then read `system_map.md`.

## 4. Quick look

Read the brief and the grooming notes when there are any, the stories, the idea (text, file or
image: a whiteboard photo is a first sketch), the area of the system map the idea touches,
`team-decisions.md`, and similar past features.
No helpers yet. Then decide the size:

| Size | Signs |
| --- | --- |
| small | 1 repo, up to 3 stories, no new table or API, no real choice |
| medium | 2 repos, or a new API or table |
| large | 3 or more repos, money, login, personal data or a migration |

Say it back in 5 to 8 lines: the outcome, who it is for, what success looks like, what is out
of scope, what would make it wrong even if it works, and your guesses with a confidence level.

## 5. Round 1: intent (skip with --auto)

Follow `references/questions.md`. At most 4 questions, in one question call, each with your
guess first. Ask only what the brief, the grooming answers, the code, the stories, the config
and past decisions cannot answer. After a grooming interview this round is often empty: skip
it and say so. If you can already predict the answers, skip the round and say so. Save every
question and answer in `work/answers.json` (shape in SCHEMA.md).

## 6. Deep read

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_design.py --plan <size> --repos <repo1,repo2> [--no-choices]
```

Say its line to the user, such as "Using 4 helpers: 2 explorers (payments-api, web-app),
1 architect, 1 reviewer. They run on sonnet, effort high." Then start one `chopchop:explorer` per repo, at most `agents.max` at
the same time, with `model` and `effort` from `--prepare` (`helpers.calls`). Leave a value out
when it is null. For a small feature, read the code yourself.

Each explorer gets: mode feature, the repo and path, the idea in 3 lines, the round 1 answers,
the stories, the paths of the brief and the grooming notes when they exist, and the report
path `work/reports/<repo>.md`. It replies with a short summary.

## 7. options.md

For medium and large features, start one `chopchop:architect` with the stories, the answers,
the paths of the brief and the grooming notes when they exist, the explorer report paths, the
system map path and the output path `work/options.json`. For a small feature, write
`work/options.json` yourself. A question grooming already answered is never a choice.

The existing pattern wins by default. A choice the code already answers is a pattern line,
not a choice. At most 4 choices: if there are more, offer to split the feature before you go on.

## 8. Round 2: picks (skip with --auto)

Ask the choices from `work/options.json` in one question call. Each option's label is its
title, the recommended one first with "(Recommended)". The description says its fit and its
cost. Put the option's sketch in `preview` when it has one. Add "Stop, I want to read
options.md first" as the last option of the first question.

- "Stop": run `chopchop_design.py --options` so `options.md` exists, tell the user its path,
  and end the run.
  The next `/chopchop:design` goes on from the picks.
- A pick that differs from yours: say your concern once, in one line, record it in
  `concern`, put the person's own reason in `picked_reason`, and re-check the choices that depend on it.
- "You decide": pick yours with `picked_by: "chopchop"`. It shows as an assumption.

Write the picks into `work/options.json` (`picked`, `picked_by`).

## 9. Write

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_design.py --scaffold --size <size>
```

Then follow the diagram skill (`${CLAUDE_SKILL_DIR}/../diagram/SKILL.md`) to write
`design/architecture.json` (the high-level design: parts and repos, no steps) and
`design/flow.json` (the main flow: numbered messages and failure answers), and run its
`--draw` until it is clean. Then write the prose of `design/design.md`, following
`references/writing.md`. Do not edit the four generated blocks: the script fills them.
Section 1 is the Summary of the file: a busy reader stops there, so it must stand alone.

Answer the failure questions for every message:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_design.py --failures
```

Answer from the code and the patterns, with the same retry, timeout and idempotency rules the
code already uses. When the code does not answer one, write your best suggestion as
`{"text": "...", "suggested": true}`. The lead confirms it. Leave it `null` only when you
have no good suggestion: that blocks the approval request, so say it in the reply.

## 10. Build

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_design.py --build
```

Exit 0 means ready for review. Exit 1 lists what blocks it: fix each one and build again, at
most 2 rounds, then tell the user what is left. Exit 2 means an input file is broken. A
citation marked `changed` means the code changed after it was read: read it again, fix the
sentence and the citation. `moved` citations are fixed by the script.

When it is ready, the build prints a `Message:` block: a few plain lines for the lead (the ask,
the size, the key choices, the questions for the lead, who must approve). It is also in
`work/build.json` as `message`.

## 11. Mock lead review

Start one `chopchop:reviewer` with lens `mock-lead` (for large features, also `risk`). Give it
the paths of design.md, options.md, architecture.json, flow.json and the system map. It returns the
hardest questions a lead would ask, each with a short answer and where the design should say
it. Fix real gaps in the design. Write the questions and answers under
`## Likely questions`, one `###` heading each. Then build again.

For medium and large features, then follow the check skill on this feature
(`${CLAUDE_SKILL_DIR}/../check/SKILL.md`), so `check.md` compares the design with the stories.

## 12. Reply

Short. The ask in one line, the picks (and any assumptions), what still needs the lead,
and next steps:

- The review message from the build, word for word, as a quote (each line starting with `> `),
  never in a code block: the user copies it into chat or email for the lead.
- Where to read it: the dashboard link (`/chopchop:design --open` prints it), Design tab. The
  file is `design/design.md`.
- After the review: `/chopchop:design --approve "Name"`.
- Then `/chopchop:spec`: the full plan to build it. It can start while the lead reviews.
  Tasks are cut from the spec, not from the design.

## --auto

No design questions. Skip steps 5 and 8: take your guesses and your recommended picks, with
`picked_by: "chopchop"` and `"assumed": true` in answers.json. Everything else runs the same,
including the mock lead review. The approval block and the review message list
every assumption for the lead to confirm. `--auto` asks nothing at all: with no helper settings
yet, step 2 saves the recommended ones.

## Feedback

When the feature already has a design and the user gives text (a lead's notes, review
comments): read it against the design. If a note changes a choice, run `--pick N=X --by lead`.
Change the prose the notes touch, build again, and reply with what changed, one line each. If
a note asks for something new that needs research, say so and do the deep read for that part
only.

## Approve

A person always decides. Ask one question: "How did the review end?" with "Approved",
"Approved with conditions" and "Changes needed". For conditions or changes, ask the user to
type them. Then:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_design.py --approve "Name" --result approved|conditions|changes [--note "..."]
```

It refuses to record an approval while something blocks the design. "Changes needed" then
waits for feedback (above).

## Rules

- Never ask what the code, the stories, the config or past decisions answer. At most 2 rounds.
- Every sentence about today's code ends with a citation: `repo/path:line@commit`, using the
  commit you read. Explorers return them for you.
- Plain, simple English, with no long dashes. See `references/writing.md`. This holds for the
  files, your questions and your replies.
- Markdown only. Never write HTML, slides or a page.
- Never ask what the brief or the grooming answers already say.
- Never change code, commit, push or open PRs. This skill writes only in `_chopchop/`.
- Never ask for, store or copy secrets.
