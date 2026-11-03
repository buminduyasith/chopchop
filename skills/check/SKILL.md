---
name: check
description: Find where a design or spec disagrees with the requirements. Reports conflicts, requirements the design misses, things the design adds that nobody asked for, and open questions, each with quotes from both sides, plus a coverage table. Works on a chopchop feature (its requirement.md and design/ folder) or on any requirement and design files. Use when the user asks to check, review or compare a design or spec against requirements or stories, find conflicts or gaps, or asks if a design is ready for tasks.
argument-hint: "[feature] [--req <files>] [--design <files>]"
---

# Check

Compare a design or spec with the requirements, and write down every place where they do not
agree. You do the reading and judging. A script finds the inputs, gives every requirement a
stable id, checks your findings and writes the report the same way every time.

The script is `${CLAUDE_SKILL_DIR}/scripts/relay_check.py`. Run it with `python3` from the
user's project folder. It needs the `tasks` skill folder next to it.

| User types | Compares |
| --- | --- |
| nothing, or a feature (`1`, `PAY-120`, `refund`) | the feature's `requirements/requirement.md` with its `design/` folder |
| `1 --design new-spec.md` | the feature's requirements with another design file |
| `--req brief.md stories/ --design design.md` | any files or folders, no feature needed |

The requirements can come from anywhere: stories pulled in by `/chopchop:stories`, a brief,
a PRD, a CSV export, notes. The design can be a design doc, an API spec, diagrams as text,
or several files.

## 1. Look

```
python3 ${CLAUDE_SKILL_DIR}/scripts/relay_check.py --prepare [feature] [--req ...] [--design ...] --json
```

It lists:
- `requirements`: the stories and acceptance criteria from a requirement.md, each with an
  id such as `PAY-121` or `PAY-121.AC2`. Use these ids exactly.
- `requirement_files`: other requirement files. Read them and give each requirement an id
  yourself (`R1`, `R2` ...), with a short quote and `file:line`.
- `design`: every design file with its headings and line numbers.
- `previous`: findings from the last check, if there was one.

## 2. Read everything

Read every requirement and every design file in full. Do not skim. For a file that is not
text (an image or a PDF), read it with the tools you have, or say you could not.

## 3. Compare

For each requirement, find where the design handles it, and decide:

- **covered:** the design clearly does what it asks.
- **partly:** the design handles some of it (for example, the happy path but not the limit
  or the error case).
- **missing:** nothing in the design handles it.

Then look for findings. Each one is one of four kinds:

| Kind | When | Example |
| --- | --- | --- |
| `conflict` | Both texts cannot be true at the same time. | The story says refunds within 30 days. The design blocks them after 14. |
| `missing` | A requirement, or an important part of one, has no design. | No design for "an admin can cancel a refund". |
| `extra` | The design adds behaviour no requirement asks for. | The design adds refund to a wallet. No story asks for it. |
| `question` | One side is unclear, so you cannot tell if they agree. | "Large refunds need approval". How large? |

Look hard at what usually goes wrong: numbers and limits, units (cents or decimals), time
windows and time zones, states and their names, who may do what (roles), error cases and
messages, required or optional fields, ordering, and what happens on retry or failure.

**Severity:**
- `high`: building the design as written gives the wrong result for users.
- `medium`: it will cause rework or a bug in an edge case.
- `low`: worth fixing, but nothing breaks.

**Rules:**
- Quote both sides word for word, short, with where they are (`design.md §4.2 (line 41)`).
- Report a conflict only when both cannot be true. If you are not sure, it is a question.
- One finding per problem. No wording or formatting nits.
- Say who can settle it in `ask`: the BA (requirement side), the design owner, or the tech
  lead.
- Give a short `fix` when the right answer is clear. Otherwise leave it out.
- Do not invent requirements. Only what the files say.

## 4. Write the report

Put the findings in a temp file, in the shape the script's `--help` shows:

```json
{"coverage": [{"req": "PAY-121.AC1", "status": "covered", "design": "refund-design.md §4.2"}],
 "findings": [{"kind": "conflict", "severity": "high", "req": "PAY-121.AC1",
               "req_quote": "Refunds are allowed within 30 days of payment.",
               "design": "refund-design.md §4.2 (line 41)",
               "design_quote": "Reject refund requests older than 14 days.",
               "problem": "The story allows 30 days, the design blocks after 14.",
               "fix": "Use 30 days in the design, or ask the BA to change the story.",
               "ask": "BA"}]}
```

For requirement files that are not a requirement.md, also add
`"requirements": [{"id": "R1", "text": "...", "source": "brief.md:12"}]`.

```
python3 ${CLAUDE_SKILL_DIR}/scripts/relay_check.py --write <findings.json> [feature] [--req ...] [--design ...]
```

With a feature, the report goes to `_chopchop/<feature>/check.md`. Without one, pass
`--out <file>` if the user wants a file, or show the printed report. If the script says a
finding has a problem, fix it and run it again.

## 5. Reply

Keep it short:

1. One line with the result, for example "Not ready: 2 conflicts and 1 important gap."
2. One bullet per conflict and high gap, most important first, in plain words with the real
   values: "Refund window: the story says 30 days, the design says 14. Ask the BA."
3. One line for the rest, grouped: "Also 2 extras and 1 question, see check.md."
4. Coverage: "11 of 13 requirements covered, 1 partly, 1 missing."
5. On a re-check, what was fixed and what is new.
6. The report path, and the next step: fix the design (or ask the BA), then run
   `/chopchop:check` again, or `/chopchop:tasks` when it is ready.

## Rules

- Never change the requirement or design files. Only report.
- The report is rewritten on every run. Notes belong somewhere else.
- If `_chopchop/style.md` exists, follow it in your reply.
