# Writing the spec

The spec is long because a feature has many parts. It must still be easy to read. A developer
new to the repo, a QA engineer and a lead should all find their part fast.

## Rules

- Start every section with `**In short:**` and one or two lines. A reader can stop there.
- Short sentences, one idea each, active voice. Most sentences under 20 words.
- One name per thing. Define it once in section 2, then use only that name.
- Explain every term a new developer would not know.
- Show before you describe: the repo's own code, a real value, an example.
- Use tables for lists of files, fields, tests and steps.
- Code names in backticks, with the repo and path when it helps.
- No length cap. Write what the reader needs. Cut every sentence that says nothing.
- No placeholders (TBD, TODO, "handle errors", "add tests"). An unknown is a question with an
  owner.
- No long dashes. Use a comma, a full stop or a colon.
- Plain words: "use", not "utilize" or "leverage". "For example", not "e.g.".

## The prose sections

| # | Section | What goes in |
| --- | --- | --- |
| 1 | Summary | What we build, for whom, what done looks like. A link to the design. |
| 2 | Words we use | A table: Word, What it means here. |
| 3 | What changes | Added, Changed, Removed, compared with today. Behavior, not code. |
| 5 | How it works today | Today's nearest flow, step by step, each fact cited. The closest feature to copy. |
| 8 | Flows, step by step | Each message of the main flow with the file and function that handles it. |
| 10 | Data | Schema change in the repo's migration style, backfill, indexes, undo. Or "None." |
| 12 | Security, speed and running it | Who may do what and where it is checked. Limits and timeouts with numbers. Logs, metrics, flags, config. |
| 13 | Shared rules | What every task agrees on. Then Always, Ask first, Never. |
| 19 | Rollout and undo | Release order across repos, flags, what to watch, how to roll back each step. |

The other sections are generated from spec.json. Change spec.json and build again.

## A good section 8 line

> 3. The API checks the 30 day window and saves the refund as pending.
> `RefundService.request` in `payments-api/src/refunds/RefundService.java` does both; it calls
> the existing `orders.findOwned` first, so a stranger gets 403.
