# Asking without a long quiz

The goal: find what the developer really has in mind before anything is written, so the
design is never a surprise at the end. Few questions, all with answers to pick.

## Before every question: can I find it?

Look in this order. If one of them answers it, do not ask. Use the answer, and say where it
came from.

1. The stories and acceptance criteria.
2. The code: the system map, the explorer reports, the repo's own files.
3. `chopchop.yaml` and the repo's guides (CLAUDE.md, AGENTS.md, README, CONTRIBUTING).
4. `_chopchop/team-decisions.md` and ADRs: past decisions.
5. Earlier answers in `work/answers.json`. Never ask the same thing twice.

## Never ask

- Which language, framework, database, queue or test tool. The repo says.
- Where tests live, how to build, how to run. The repo and CI say.
- The base branch or the repos. `chopchop.yaml` says.
- Anything a story already answers.
- "Do you want tests?", "Should it handle errors?", "Should it be secure?". The answer is
  always yes.
- How to do something the code already does one way. That is a pattern to follow.

## How to ask

- Use the question tool. One call per round, up to 4 questions. Never a wall of questions in
  chat.
- Every question ends with `?` and makes sense on its own.
- Put your guess first, with "(Recommended)" at the end of its label. Reacting to a guess is
  faster than inventing an answer.
- 2 to 4 options. Labels of 1 to 5 words. The description says what the option means for
  the feature, in one line.
- The tool always adds "Other", so people can type their own answer.
- Point at real code when it helps: "Should refunds work like order cancel
  (payments-api, src/orders/cancel)?"
- Use `multiSelect` for "which of these stay out for now?".
- In round 2, put an option's sketch in `preview`, as a small text drawing.

## Round 1: intent

After the quick look, before the deep read. Good topics, in order of value:

1. What matters most: ship soon with the smallest change, or a design we can grow?
2. What it should work like: a similar feature you found in the code.
3. What stays out for now: things the stories do not mention.
4. What would make it wrong, even if it works?
5. Who else is affected: a team or service the system map shows.

Skip the round when you can already predict the answers. Say "No questions: the stories and
the code answer everything." instead.

## Round 2: picks

Only the choices in `work/options.json`. Nothing else. This is the last question before
writing.

## Stop asking when

You can predict the answer to the next three questions you would ask. Then stop and write.

## Listen for

- "Whatever you think is best": pick your recommendation, record `picked_by: "chopchop"`,
  and say it is an assumption the lead will see.
- A pick that differs from yours: say your concern once, in one line. Then respect the pick.
- An answer that changes an earlier one: re-check what depends on it.

## Save

Write every question and answer to `work/answers.json` as soon as you have it, so a stopped
run loses nothing.
