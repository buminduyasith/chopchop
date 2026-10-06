# Story file format

Each story lives in `_relay/features/<feature>/requirements/stories/<ID>.md`.

## Who owns what

| Part | Owner | On re-sync |
| --- | --- | --- |
| Front matter keys `id` to `analysis` | script | rewritten |
| `analysed_hash`, `analysed`, any key you add | agent / people | kept |
| `# ID · Title` line | script | title kept in step with the tracker |
| `<!-- relay:banner -->` block | script | rewritten (New / Changed / Removed notice) |
| `## Acceptance criteria`, `## Open questions`, other headings you add | agent | **never touched** |
| `<!-- keep --> ... <!-- /keep -->` | people | never touched, survives `--fresh` too |
| `<!-- relay:source -->` block | script | rewritten from the tracker |

`analysis` in the front matter is one of:

- `pending`: never analysed
- `stale`: the source changed after the last analysis
- `done`: analysis matches the current source
- `removed`: the story left the epic

## Acceptance criteria rules

1. Format: `- **PAY-121.AC1** The refund button shows only for orders paid in the last 30 days.`
2. One testable behaviour per criterion. Split "A and B" into two criteria.
3. IDs are permanent. Never renumber, never reuse. Design, tasks and tests point at them.
4. Wording changed in the tracker: same ID, new text, append `(changed 2026-09-24)`.
5. New criterion in the tracker: next unused number.
6. Criterion removed in the tracker: `- ~~**PAY-121.AC4** old text~~ (removed 2026-09-24)`.
7. Derived from the description (the tracker had no explicit criteria): append `(derived)`
   and add an open question asking the BA to confirm.
8. A decision from a comment: append the source, e.g. `(from comment, A. Perera, 2026-09-19)`.
9. Given / When / Then is welcome when the BA wrote it that way. Do not force it.
10. Keep the BA's words where they are already clear. Do not add scope. If you think
    something is missing, ask in Open questions instead of adding a criterion.

Optional sub-headings under Acceptance criteria when a story is big:
`### Happy path`, `### Errors and limits`, `### Permissions`, `### Non-functional`.

## Open questions rules

- Ask what a developer would need to know to build and test it.
- Each question names the AC it is about, if any.
- Mirror every question into `requirements/questions.md` with a stable id (Q1, Q2...).
  In the story file, prefix the question with that id.
- When the BA answers: keep the question, add the answer and date, and update the criteria.

## Full example

```markdown
---
id: "PAY-121"
title: "Customer can request a refund"
type: "Story"
status: "Ready for Dev"
priority: "High"
assignee: null
story_points: 5
labels: ["payments"]
parent: "PAY-120"
url: "https://acme.atlassian.net/browse/PAY-121"
source_updated: "2026-09-23T10:02:11.000+0530"
synced: "2026-09-24T04:10:00Z"
sync_state: "changed"
source_hash: "9c1d0e6f2a7b4c11"
analysis: "done"
analysed_hash: "9c1d0e6f2a7b4c11"
analysed: "2026-09-24T04:12:30Z"
---
# PAY-121 · Customer can request a refund

<!-- relay:banner -->
<!-- /relay:banner -->

## Acceptance criteria

- **PAY-121.AC1** The refund button shows only for orders paid in the last 30 days, counted from the payment date. (from comment, BA, 2026-09-17)
- **PAY-121.AC2** A customer can refund part of an order. The minimum is 1.00. (changed 2026-09-24)
- **PAY-121.AC3** The customer gets an email when the refund is complete.
- ~~**PAY-121.AC4** Refunds over 500.00 need a manager's approval.~~ (removed 2026-09-24)
- **PAY-121.AC5** The refund total can never be more than the amount paid. (derived)

## Open questions

- **Q1** (AC1) Can a customer refund an order that is still being shipped?
- **Q2** (AC5) Please confirm AC5. The story implies it but does not say it.

## Notes

<!-- keep -->
Dev note: orders before 2024 have no payment date. Treat them as not refundable online.
<!-- /keep -->

<!-- relay:source -->
## Source
_From Jira [PAY-121](https://acme.atlassian.net/browse/PAY-121) · ... Replaced on every sync, do not edit here._
...
<!-- /relay:source -->
```
