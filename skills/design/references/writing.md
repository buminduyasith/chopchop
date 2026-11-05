# Writing the design

Leads read it in about 10 minutes. Developers who do not speak English as a first language
read it too. Write so a tired person understands it on the first read.

## Simple English

- Up to 20 words for a step, up to 25 for any other sentence.
- One idea per sentence. Active voice: say who does what. Present tense.
- Everyday words: "use", not "utilize". "Help", not "facilitate". "Start", not "initiate".
- One name per thing, everywhere. If it is the "refund job" once, it is never the "worker".
- Numbers, not adjectives: "under 300 ms", not "fast". "5 tries", not "a few".
- No idioms, no metaphors, no "e.g.", "i.e." or "etc.".
- No long dashes. Use a comma, a full stop or a colon.
- Lists, tables and diagrams before paragraphs.
- Every sentence about today's code ends with its citation:
  `payments-api/src/payouts/PayoutJob.java:35-40@a1f9c2e`.

The build warns about long sentences and the words above, and blocks long dashes.

## Budget

| Size | Words (sections 1 to 12) |
| --- | --- |
| small | 500 |
| medium | 1,300 |
| large | 1,800 |

Tables, code, diagrams, generated blocks and the Likely questions do not count. Over budget,
cut: detail belongs in the spec.

## The 12 sections

| # | Section | What goes in |
| --- | --- | --- |
| 1 | Summary and the ask | 3 to 5 lines, then `**The ask:**` (the one decision the lead makes) and `**Size:**` (repos, about how many tasks, waves). |
| 2 | High-level design | Generated from architecture.json (the diagram skill). Write nothing else here. |
| 3 | Why | 3 to 6 bullets. Facts only, each fact about today's code with a citation. |
| 4 | Scope | In scope with story ids. Out of scope with the parked ideas. Every story id is in one of the two. |
| 5 | Main flow and errors | One or two sentences. The sequence and the failure table are generated from flow.json (the diagram skill). |
| 6 | Data changes | One table: table, change, columns, migration. Or "None." |
| 7 | Contract changes | One table: API or event, between which repos, new or changed, breaking or not. Or "None." |
| 8 | Key decisions | Generated from options.json. |
| 9 | Impact and rollout | Who else is affected (from the system map), flags, release order, how to roll back. |
| 10 | Risks | Up to 5 rows: the risk and what we do about it. Accepted risks name the person. |
| 11 | How we prove it | Test counts by level (unit, integration, e2e, manual). E2E journeys by name. |
| 12 | Questions, assumptions, approval | Open questions with an owner. The rest is generated. |

Then `## Likely questions`: one `###` heading per question from the mock lead review, and a
one or two line answer. Add a "Why not ...?" for each option not picked.

A section with nothing to say keeps its heading and says "None." Leads always know where to look.

## Speaker notes

Each section can carry notes for its slide:

```
<!-- talk: Walk the numbers. Stop at step 3: the 30 day rule lives there. -->
```

2 or 3 short lines, the way the developer would say it out loud. Never shown in the document.
