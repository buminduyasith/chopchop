---
name: groom
description: Get a feature ready before anyone designs it. Takes a tracker epic (a Jira key or link) or a plain idea, checks every story against the real code with helper agents, then interviews the developer with a few short questions, each with answers to pick and an "ask the BA" choice. Questions the developer cannot answer become a ready-to-paste list for the BA. Ends with brief.md: what we build, in simple English, for a person to approve. Use when the user runs groom, gives an epic or an idea to start, says prepare for grooming, check the stories against the code, what should I ask in grooming, brings answers from the BA, or wants the brief. --auto asks nothing.
argument-hint: "<epic id, link or idea> [--auto] [--locked|--open] | <feature> (to carry on, or with the BA's answers) | --approve \"Name\""
---

# Groom

Find out what we are really asked to build, before the design. Agents read the stories and the
code. You ask the developer only what the code cannot answer. What the developer does not know
goes to the BA. The result is a short brief a person approves.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py`. Run it with `python3` from the
user's project folder. It needs the `tasks` and `stories` skill folders next to it. If there is
no `chopchop.yaml` yet, run `/chopchop:init` first.

**Simple English always**: in the files, in your replies and in every question. Short
sentences. Everyday words. No long dashes.

| User typed | Do this |
| --- | --- |
| an epic id or link (`PAY-120`) | Steps 1 to 7. Mode is `locked`. |
| an idea in words | Steps 1 to 7. Mode is `open`. |
| a feature that is already started, or nothing | `--prepare` shows where it stands. Go on from its `Next:` line. |
| the same, with text that reads like answers | They are answers, often from the BA. Step 5. |
| `--auto` | No questions. See "--auto". |
| `--locked` or `--open` | `--mode locked` or `--mode open`, then go on. |
| `--approve "Name"` | Step 7. |

## The two modes

- **locked** (stories from the tracker): the BA owns the words. Never change, drop or "improve"
  a story. Everything you would change becomes a question for the BA.
- **open** (the team's own idea): suggest better, simpler or safer ways, and let the developer
  pick.

## 1. Source

- **Epic id or link:** follow the stories skill, steps 1 and 2
  (`${CLAUDE_SKILL_DIR}/../stories/SKILL.md`): get the epic and its stories with the tool the
  team already has, and ingest them. The text is copied as it is.
- **Idea:**

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --idea "<the idea, in the user's own words>" --title "<3 to 6 words>" --name short-name
  ```

  The idea text is kept word for word. `--title` is a short name a person reads on the
  dashboard, like "Bitrate formatter" or "Refund requests".

  If the idea is very short (under about 25 words), ask one quick round first, with the
  question tool: who uses it, what "done" looks like, and what stays out for now. Put your
  guess first in each. This counts as a round (`--round`). Save the answers in step 4's way
  after the research.

## 2. Load

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --prepare <feature> --json
```

- `helpers.ask` is true: ask the three helper questions once (with `--auto`, save the recommended
  ones without asking), as the design skill's step 2 says
  (`${CLAUDE_SKILL_DIR}/../design/SKILL.md`), before any helper starts.
- `system_map.exists` is false: follow the learn skill first (`${CLAUDE_SKILL_DIR}/../learn/SKILL.md`).
- `researched` is set and the user gave no new stories: skip step 3.

## 3. Research: stories against the code

Say one line: "Checking N stories against <repos>." Then start one `chopchop:groomer` agent per
repo the stories could touch, at most `helpers.max` at once, with `model` and `effort` from
`helpers.calls.groomer` (leave a value out when it is null). With `helpers.max` 0, or one small
repo, read the code yourself in the same way.

Each groomer gets: the repo name and path, the requirement file path, the mode, the system map
path, and its report path `<files.reports>/<repo>.json`. It replies in a few lines.

Then merge the reports into one file at `files.findings`:

- One entry per story. When two repos report on the same story, join them: the worst `fits`
  wins (`conflict`, then `change`, then `unknown`, then `yes`), the biggest size wins, lists are
  joined.
- Drop questions that another report, a story, or `team-decisions.md` already answers. Merge
  questions that ask the same thing. Keep at most about 12, the sharpest first.
- `summary`: 1 to 3 short lines a person can read in ten seconds.
- In `locked` mode, turn every suggestion into a question for the BA or drop it.

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --findings <files.findings> <feature>
```

It checks the file, writes `grooming.md` and gives every question an id (Q1, Q2...). Exit 2
lists what to fix in the file.

## 4. Interview the developer (skip with --auto)

First say what you found in 4 to 6 short lines: how many stories fit, which need a change or
clash and why, and the hidden work. Then ask.

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --questions dev <feature> --json
```

- Ask `this_round` (at most 4 questions) in **one** question-tool call. Blocking ones come first.
- Each question: the text as it is, the why in the description, and its options as the answers.
  Put the guess first with "(Recommended)". Always add the option **"Not sure, ask the BA"**.
  The tool adds "Other" for a free answer. Keep to 4 options in all.
- Save the round in one go. Write a JSON file and run `--answers`:

  ```json
  [{"id": "Q1", "text": "Full refunds only for now.", "by": "dev"},
   {"id": "Q2", "ask": "ba"}]
  ```

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --answers <file> <feature>
  python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --round <feature>
  ```

  Save the answer in the person's own words. "Not sure, ask the BA" is `"ask": "ba"`.
- An answer can raise a new question. Add it with `--add-question --text "...?" --why "..."`
  (`--ask ba` when it is for the BA, `--blocking` when the brief needs it).
- At most 3 rounds. Stop sooner when no question for the developer is open, or when you can
  predict the next answers. When rounds run out, hand what is left to the BA (`--ask-ba Q7,Q8`)
  or, if the developer says "you decide", save your guess with `--answer Q7 --assume --text "..."`.
- "Whatever you think" is an assumption, not an answer: save it with `--assume`.

## 5. Questions for the BA

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --questions ba <feature>
```

Show the questions as a numbered list, never in a code block, so the user can copy them into
chat or mail, or read them out in the grooming meeting. Say: "Bring the answers back to me and I will go on."

- **No blocking question is open for the BA:** go on to step 6 now. The open ones are listed in
  the brief.
- **A blocking one is open:** stop here. The feature waits for the BA. If the user says "go on
  with your best guess", save each with `--answer Qn --assume --text "..."` and go on.

**When the answers come back** (the user pastes them, or says them): match each to its
question by the `Ref:` id or by meaning, and save with `--answers`, `"by": "ba"`. If an answer
is unclear or two answers clash, ask the user once. Then go on.

In `locked` mode, when the BA changed a story in the tracker instead of answering, sync it
again with the stories skill (`-rs <feature>`), and check the changed stories again (step 3).

## 6. The brief

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --brief <feature>
```

The first run starts `requirements/brief.md` from the template. Write each part from the
requirement, `grooming.md` and the answers:

- **Summary**: 3 to 5 short lines. What, for whom, why, what done looks like.
- **In scope / Out of scope**: one line per story, starting with its id. In `locked` mode every
  story is in one of the two.
- **Rules**: one rule per line with the id it comes from, with the BA's real numbers and limits.
  In `locked` mode do not soften or extend them.
- Do not write between the `chopchop:` marks. The script fills those from the answers.

**For an idea** (no stories yet): first write the agreed rules as a JSON list and run
`--rules <file> <feature>`. It stores them as stories R1, R2..., so the design and the spec have
ids to point at. Each rule: `{"id": "R1", "title": "...", "acceptance_criteria": ["...", "..."]}`.
Then use those ids in the brief.

Run `--brief` again. It checks the Summary, the simple English, the story ids, and that no
blocking question is open. Fix every `Error:` and the warnings that are fair, and run it again
until it says `ready for approval`.

## 7. Approve

Tell the user, short:

1. Where the brief is, and the 3 to 5 Summary lines.
2. What is in and what is out, in one line each.
3. Assumptions and open questions: how many, and the one that matters most.
4. "Read it, change what is wrong, and say **approve**."

A person approves. When the user says approve, or gives a name:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_groom.py --approve "<their name>" <feature>
```

Use the name they give. If they just say "approve", use their git name
(`git config user.name`), and say which name you used. Never approve by yourself.

Text after an approval ("change the limit to 14 days"): edit the brief, run `--brief`, and ask
for the approval again. The script marks a changed brief as "changed since the approval".

## --auto

No questions to the user. After step 3:

- A developer question with a guess: save the guess with `--answer Qn --assume --text "..."`.
- A developer question with no guess, and every business question: `--ask-ba`.
- Write the brief. A blocking BA question becomes an assumption in the brief, clearly marked,
  unless nothing sensible can be assumed. Then stop and say which question blocks it.
- Never approve. Say that a person must read and approve the brief.

## Reply

Keep it short. One line per step while you work. At the end: where the feature stands, who it
waits for, and the next step. If the dashboard is running, give its link: it shows the
grooming, the questions and the brief.

## Rules

- Never edit `requirement.md` by hand. It is the BA's text, or the idea as given.
- Never edit `grooming.md` by hand. Answers go in through the script.
- In `locked` mode never change what a story asks for. Ask.
- Never ask what the stories, the code, the config or a past decision already answers.
- Never ask for, store or set up tokens, logins or tools. Use what is already there.
- If the script fails, show the error and the fix. Do not work around it.
