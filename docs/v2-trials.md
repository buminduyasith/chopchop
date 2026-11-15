# chopchop v2 trials

## Summary

- **What:** v2 run end to end by a real agent (headless `claude -p`, Sonnet, `--auto`) on three setups: the shop sample (2 Node repos), humanize (a real Python library), and two real public PRs (read only).
- **Result:** both features went from an idea to pushed, tested commits. Every gate stopped for a person. Every stop was for a real reason. 10 problems found and fixed.
- **Evals:** all 5 cases score 1.00. **Unit tests:** 237 in 16 skills, all pass.
- **Updated:** 2026-11-15.

## Setup

| Trial | Code | Remote | Feature |
| --- | --- | --- | --- |
| A | shop-api and shop-web (Node, from `chopchop-trial`) | local bare repos under `/tmp` | Refund requests for delivered orders |
| B | `python-humanize/humanize`, 749 tests pass | local bare repo under `/tmp` | `humanize.bitrate()` |
| C | `cli/cli#12942`, `django/django#22014` | read only with `gh` | explain the review comments |

Each stage is a new headless session, like a new chat: `docs/handoff/run_stage.sh`.

## Stages

| Stage | Time | Cost | Result |
| --- | --- | --- | --- |
| A1 run an idea, groom, brief | 125 s | $0.78 | Pass. Brief ready, stopped at the brief gate. Found the two trap modules. 4 assumptions, 2 BA questions. Ran learn first. |
| A2 approve brief, design | | | Pass. Brief approved by Trial Dev. Design written, mock lead found 5 gaps and they were fixed. Stopped for the lead with a review message. |
| B1 run an idea, groom, brief | 69 s | $0.36 | Pass. One rule set (R1 to R3), 4 assumptions, stopped at the brief gate. |
| B2 approve brief, design | | | Pass. Stopped for the lead. It refused to take the developer's "approve" as the lead's yes. |
| A3 lead approves, spec | 388 s | $1.72 | Pass. Cold read and test-gap reviews found gaps, fixed in the spec (7 more tests). Two fair open questions (no timeout on cancel today, who signs manual journeys). Stopped at the spec gate. |
| A4 approve spec, tasks, build | 33 s | $0.21 | Stopped early: neither repo had a profile, so the build had no test command. 6 tasks in 3 waves and both feature branches were made. Fixed (problem 5), then A5. |
| A5 build (profiles drafted by auto) | 428 s | $1.73 | Correct stop. T01, T03, T04 committed. T02 and T06 stopped: the repo lint caps test files at 250 and 200 lines, and the tasks did not allow a second test file. Nothing pushed half done. |
| A6 person allows a second test file | | | Pass. Retries worked, change logged as C-001 and C-002, T05 built. 6 of 6 committed and pushed. shop-api `npm run check`: 93 pass (48 before). shop-web: 73 pass (44 before), lint clean. Neither trap module imported or copied. One leftover for a person: 3 compact tests in T05 to fit the cap. |
| B3 lead approves, spec | 146 s | $0.60 | Pass. 3 rules, 13 named tests, 11 of 11 citations current. Cold read asked 10 questions, all fixed. |
| B4 approve spec, tasks, build | 147 s | $0.53 | Correct stop. The review asked to translate the whole message, which broke the task's own test. The builder undid its try and asked a person to choose. Nothing committed. |
| B5 person picks A, retry | 74 s | $0.32 | Pass. `--retry` worked, the second review was clean, T01 committed and pushed. Full suite on the build branch: 787 passed (749 before, 38 new). `bitrate(1500000)` is "1.5 Mbps". |
| C1 triage two real PRs | 136 s | $0.57 | Pass. cli: 9 comments, 5 groups (6 real, 3 outdated). django: 9 comments, 6 groups. Every real verdict cites lines at the PR head. Nothing posted, nothing committed. |

## Problems found and fixed

| # | Problem | Fix |
| --- | --- | --- |
| 1 | A feature started from an idea got the whole first sentence as its title. | `skills/groom/SKILL.md` now passes `--title "<3 to 6 words>"`. |
| 2 | Group file lists in `comments.md` showed one file twice: `cli/pkg/...` and `pkg/...`. The triager left out the repo name. | `commentslib/triage.py` `regroup()` adds the group's repo when a file has none. Re-merged trial C: each file now shows once. |
| 3 | `design --build` warned about `payments-api/src/payouts/PayoutJob.java`: an example citation inside a hidden instruction comment of the template. | `collect_cites()` in `chopchop_design.py` drops HTML comments first, like the spec already did. |
| 4 | After a push-only run (`auto.pr: push`) the step said "Next: push and open the PRs" though the branch was pushed. | `stage.py` now says it waits on you to open the PR when every repo is pushed. |
| 5 | The build stopped when a repo had no profile, even with `--auto`. | `skills/auto/SKILL.md`: draft the profile with `code --profile`, check the commands, use a check-only lint, and go on. Ask the person to confirm the profile at the end. |
| 6 | humanize's lint (`ruff check .`) would have changed files, because its config sets `fix = true`. | Covered by the same rule in problem 5: a lint must be check only. The trial used `ruff check --no-fix`. |
| 7 | The spec did not know the repo lint caps test files at 250 and 200 lines, so tasks overflowed them. | `agents/explorer.md` (spec mode) and `skills/spec/references/code.md` now read lint limits with their numbers and plan a new test file when an old one would overflow. |
| 8 | `--auto` still asked the one-time helper questions on a fresh team, so a headless run did nothing (eval run-gate). | design, groom, spec and learn: with `--auto`, save the recommended helper settings and say how to change them. |
| 9 | The brief kept the template's writing hints after the sections were filled (eval groom-auto). | `chopchop_groom.py --brief` drops a section's hint once the section has words. Test added. |
| 10 | Asked to explain review comments from a file, the model did it itself and never used the comments skill (eval comments-triage). | The skill description now says to use it for any request about review comments, including exported files. |
| 11 | After the dashboard server restarted, an open page kept the open feature's old data. | `dashboard.html`: on reconnect it fetches the open feature and the home list again. Tested by restarting with a change made while the server was down. |

## Evals

Run with `claude plugin eval`, model Sonnet, one run each, no baseline arm.

| Case | First run | After fixes | What the first run showed |
| --- | --- | --- | --- |
| groom-auto | 0.58 | 1.00 | Template hints left in the brief (fix 9). Two graders were unfair: regex flags the engine does not accept, and a judge asked to check limits it could not see. |
| run-gate | 0.17 | 1.00 | `--auto` asked the helper questions (fix 8). The grader only allowed one right ending: a stop on a blocking BA question is also right. |
| comments-triage (new) | 0.22 | 1.00 | The comments skill did not fire for comments in a file (fix 10). |
| design-auto | 0.67 | 1.00 | The design was right. One regex grader could not run, and one judge had to check a 19k-character file in one go: split into 3 exact checks and a writing-only judge. |
| learn-system | 0.60 | 1.00 | One regex grader used `(?s)`, which the engine does not accept. |

Grader lessons: use `flags: m`, not `(?m)`. Give an LLM judge every fact it must check, in the grader itself. Use `--judge-model sonnet` for long files.

## Dashboard changes after the user looked at it

- Links name the feature by its folder (`#/f/001-IDEA-1-refund-requests/tasks`). Old number links still work.
- Code is coloured like VS Code (Dark+, Light+ in the light theme), with the language shown. Checked on trial A: 33 of 33 spec code blocks coloured, keyword and string colours match VS Code.- **Changes** tab for the tech spec: a VS Code style file explorer per repo with A, M and D in git colours, filters,
  search, and a side panel with the reason, the packages and the tasks for each file. Checked on trial A: 22 files in
  2 repos, 1 new and 21 changed, each shown once although 6 of them are touched by two packages. `spec.md` section 6
  now has the same tree as text instead of the old Mermaid file map.

## Final check

- Unit tests: 237 in 16 skills, all pass. One old spec test expected the Mermaid file map in section 6. That map was
  replaced on purpose by the folder tree, so the test now checks the tree instead.
- `claude plugin validate . --strict`: passed.
- No long dashes in any file.
- Nothing is committed or pushed. The trial repos only push to local bare repos under `/tmp`.
- **No plain text boxes.** The spec's file tree in `spec.md` is now a nested list (and the explorer on the dashboard
  Spec page). The BA questions in `grooming.md` are a list, reviewer comments in `comments.md` are quotes, and the
  Review tab shows them with a side bar instead of a grey box. `plain.lint()` warns about any code block with no
  language or with `text`, and the writing guides say only real code goes in a code block.
