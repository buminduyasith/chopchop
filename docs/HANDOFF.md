# chopchop v2: handoff

Written on 2026-11-14. Read this whole file before you touch anything.

## Summary

- **What:** chopchop is a Claude Code plugin (skills, agents, Python scripts). Version 2 adds one command (`/chopchop:run`), a grooming interview, a live dashboard and a PR review comment helper.
- **Where:** all work is in `/Users/buminduyasith/mydata/work/chopchop-v2` (git branch `v2`). Nothing is committed. Nothing is pushed.
- **Status:** about 80% built. All unit tests pass except one (it fails only because one file is missing). Nothing has been tried end to end with a real agent yet.
- **Your job:** finish the 10 pending steps in section 6, in order, and tick each "Done when".
- **Full design:** `docs/v2-spec.md` (short, read it right after this file).

## 0. Status on 2026-11-15: all 10 steps are done

Every step in section 6 was finished. The results are in `docs/v2-trials.md`: 3 trials (shop sample, humanize, two
real public PRs), 11 problems found and fixed, all 5 evals at 1.00, 237 unit tests passing. Since then the user asked
for, and got: feature names in dashboard links, VS Code code colours, and a Changes tab (the tech spec's files as a
folder tree per repo with git colours). The only thing left is the user's call: review and commit (nothing is
committed yet). The rest of this file is kept as the record of how the work was planned.

## 1. Rules you must follow

1. **Never commit, push, stash, reset or switch branches** unless the user says so in chat. All work stays as uncommitted changes on branch `v2`.
2. **Work only in** `/Users/buminduyasith/mydata/work/chopchop-v2`.
3. **Never touch** `/Users/buminduyasith/mydata/work/agent-harness` (the user's main checkout) or `/Users/buminduyasith/mydata/work/chopchop-trial` (read only, copy from it if you need it).
4. **Never create, comment on, merge or close a pull request on GitHub.** Reading public PRs with `gh` is fine. Read only.
5. **Python standard library only.** Code must run on Python 3.8: no `match`, no `X | Y` type syntax. Use `%` formatting, `argparse`, a `UsageError` that exits 2, short plain messages and a `Next:` hint. Copy the style of `skills/groom/scripts/chopchop_groom.py`.
6. **Simple English everywhere:** files, messages, questions. Short sentences (25 words or fewer). Everyday words.
7. **No long dashes** (the characters U+2013 and U+2014) in any file. Use a comma, a full stop or a colon. Tests fail on them.
8. **Every Markdown file chopchop writes starts with a `## Summary`.** Use `plain.summary_block()`.
9. **Markdown only.** No HTML pages except the one dashboard page.
10. **The dashboard is for a MacBook.** Dark by default. No phone layout. Documents fill the full window height.
11. **Never edit a test to make it pass** unless the test itself is wrong. Say why if you do.
12. When a script fails, read the error and fix the cause. Do not work around it.

## 2. What the user asked for (the goals)

Check every one of these at the end. They are the acceptance list.

| # | Goal | Where it lives |
| --- | --- | --- |
| G1 | People check the brief, the design and the spec. Agents loop only on build, review, fix, test, commit. | `stage.py`, `run`, `auto` |
| G2 | One command: `/chopchop:run <Jira key, link, or idea>` reads everything, does research and grooming, and interviews the user. | `skills/run`, `skills/groom` |
| G3 | A Jira requirement is **locked**: never change it, only ask questions. Our own idea is **open**: suggestions welcome. | `skills/groom` |
| G4 | Grooming: agents check each story against the real code, then interview the developer with a few questions. What the developer does not know becomes a ready-to-paste list for the BA. | `skills/groom`, `agents/groomer.md` |
| G5 | Two requirement files: `requirement.md` (Jira text word for word, or the idea as given) and `brief.md` (what we build, in simple English). | `skills/groom` |
| G6 | Design (for the lead), then a tech spec (for the agents), then tasks, then a status file that tells an agent which task is next. | `design`, `spec`, `tasks` (existing) |
| G7 | Each task runs in a fresh context: build, review by another agent, fix, test, commit. Not one PR per task: one PR per repo, with a pause after each wave if wanted. | `skills/auto` (existing, changed) |
| G8 | A live dashboard: all features, filter, real-time updates, click a task to read its Markdown with diagrams, design and spec side by side. | `skills/dashboard` |
| G9 | `/chopchop:dashboard` starts it, `--stop` stops it, and `/chopchop:run` starts it by default. | `skills/dashboard`, `skills/run` |
| G10 | Markdown only. No HTML for spec and design. No previews (`-p`). | done in the clean-up |
| G11 | Simple English in every file, chat reply and question. A Summary on top of every Markdown file. | `chopchoplib/plain.py` |
| G12 | PR review comments: one command finds the feature and its PRs, reads every comment, keeps listening until merge, groups similar comments across repos so fixes do not undo each other, and shows for each: plain explanation, priority, similar ones, the fix, what the fix touches, real problem or false positive and why, and the reply to send. Negotiable comments (not about this PR) get a reply too. | `skills/comments`, `agents/triager.md`, dashboard Review tab |
| G13 | Try the tool on real repos of different software, run the evals, fix what breaks. Do not create PRs on other people's repos. | section 6, steps 7 to 9 |
| G14 | Dashboard: dark by default, MacBook only, design and spec fill the whole height. | `skills/dashboard/assets/dashboard.html` |

## 3. How the repo is set up

- The user's real source is `~/mydata/work/agent-harness` (branch `main`, version 0.9.0). It had 21 uncommitted files.
- `~/mydata/work/chopchop-v2` is a git worktree of it on branch `v2`. Its first commit `ec3d322` is a snapshot of those 21 files. Everything after that is uncommitted.
- See all v2 changes with `git status --short` and `git diff` inside `chopchop-v2`.
- The installed plugin at `~/.claude/plugins/marketplaces/chopchop` is old (0.7.0). Ignore it.
- Version in `.claude-plugin/plugin.json` is now `0.10.0`.

Folder map:

```
chopchop-v2/
  README.md                       rewritten for v2
  docs/v2-spec.md                 the v2 design. File shapes for comments are in section 8.
  docs/HANDOFF.md                 this file
  docs/handoff/                   run_stage.sh, make_demo.py, two trial config files
  agents/                         architect, builder, code-reviewer, explorer, reviewer, groomer (new), triager (new)
  evals/                          design-auto, learn-system, groom-auto (new), run-gate (new), sample-project
  skills/<name>/SKILL.md          what the agent does
  skills/<name>/scripts/*.py      what must be the same every time
  skills/<name>/tests/            unittest
  skills/tasks/scripts/chopchoplib/   shared library. New: stage.py, plain.py, events.py
```

## 4. What is done

| Part | State | Files | Tests |
| --- | --- | --- | --- |
| Shared: stage tracker | done | `skills/tasks/scripts/chopchoplib/stage.py` | used by groom and run tests |
| Shared: Summary and simple English | done | `.../chopchoplib/plain.py` | used by many tests |
| Shared: activity log | done | `.../chopchoplib/events.py` | used by groom tests |
| `groom` | done, never run by a real agent | `skills/groom/` (SKILL.md, script, `templates/brief.md`, tests), `agents/groomer.md` | 14 pass |
| `run` | done, never run by a real agent | `skills/run/` (SKILL.md, script, tests) | 13 pass |
| Clean-up of old skills | done | `auto`, `design`, `spec`, `tasks`, `code`, `check`, `review`, `diagram`, `learn` | all pass |
| `comments` | code done, tests pass, never run by a real agent | `skills/comments/` (SKILL.md, SCHEMA.md, script, `commentslib/`, tests), `agents/triager.md` | 42 pass |
| `dashboard` | server and page written. **No SKILL.md. No tests.** Page only partly checked by eye. | `skills/dashboard/scripts/chopchop_dashboard.py`, `scripts/dashlib/` (data.py, md.py, watch.py), `assets/dashboard.html` | none yet |
| README, plugin.json, marketplace.json | done | | |
| Evals `groom-auto`, `run-gate` | written, never run | `evals/` | |

What the clean-up changed (all tested):

- No `feature.html`, no `board.html`, no slides. `--open` in design, spec, tasks and diagram starts the dashboard.
- Summary added to plan.md, status.md, changelog.md, task files, options.md, check.md, system-map.md, repo profiles, review packs, PR text.
- `design --prepare` prints the brief and grooming paths. The design skill reads them first.
- `spec --approve "Name"` records a person's yes. A later change sets `changed_since_approval`.
- `auto --retry T02` restarts a stopped task. `auto --wave` (or `auto.pause: wave`) pauses after each wave. The forbid fix list names `file:line`.
- `code`: the `-p` preview is no longer offered.
- Every script writes to the activity log with `events.log()`.

## 5. Where the two helpers stopped

Two helper agents were stopped by hand in the middle of their work.

**Dashboard helper.** It had written the server and the page, then made these changes from the user's feedback: dark by default, a "reading mode" for Compare (design and spec side by side, full height, steps and banner hidden), and removed phone rules. Its last steps were: "Render Mermaid in one look and darken drawings with a filter", then it was reading how `skills/run/scripts/chopchop_run.py` starts the dashboard. It had **not** written `skills/dashboard/SKILL.md` or any test. It had **not** done a final look at the page after its last edits. Treat the page as unverified.

**Comments helper.** It was on its very last step ("Final live check, lint, and Python 3.9 test run"). Code, SKILL.md, SCHEMA.md, the triager agent and 42 tests are in place and pass. It never sent its final report, so nobody has reviewed its work. It made a live read-only check on two public PRs: `https://github.com/django/django/pull/22014` and `https://github.com/cli/cli/pull/12942`.

## 6. Pending work, in order

Run every command from `/Users/buminduyasith/mydata/work/chopchop-v2` unless a step says otherwise.

### Step 1. Check that nothing is broken right now

```sh
cd /Users/buminduyasith/mydata/work/chopchop-v2
for s in stories tasks code init check update learn design diagram spec review auto groom run comments dashboard; do
  printf "%-10s " $s; (cd skills/$s && python3 -m unittest discover -s tests 2>&1 | tail -1)
done
```

Expected today: every line says `OK`, except `init` (`FAILED (failures=1)`) and `dashboard` (`NO TESTS RAN`). Steps 2 and 3 fix both.

**Done when:** you see exactly that.

### Step 2. Write `skills/dashboard/SKILL.md`

Copy the shape of `skills/auto/SKILL.md`. It must start with exactly:

```
---
name: dashboard
description: <one long sentence: what it does and when to use it>
argument-hint: "[--stop | --status]"
---
```

Content, in simple English:

- A "What the user typed" table: nothing (start and open), `--stop`, `--status`.
- The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_dashboard.py`. Run it with `python3` from the user's project folder.
- Step 1: `--start`. Say the `Dashboard:` link in one line. Say it updates by itself.
- Step 2: `--stop` stops it. `--status` says if it runs.
- What the page shows, in 5 short lines (home, a feature, Compare, tasks board, Review tab).
- Rules: it listens on `127.0.0.1` only, it is read only, it never sends files anywhere.

Check the real flags first: `python3 skills/dashboard/scripts/chopchop_dashboard.py --help`. Today they are `--start`, `--stop`, `--status`, `--serve`, `--port N`, `--no-open`, `--json`, `--workspace`.

**Done when:** `(cd skills/init && python3 -m unittest discover -s tests)` says `OK`. That test checks every `SKILL.md` starts with `---\nname: <folder>\n` and has no long dash.

### Step 3. Write the dashboard tests

File: `skills/dashboard/tests/test_dashboard.py`. Use `unittest`, no network. Copy the top of `skills/groom/tests/test_groom.py` for imports and for building a sample workspace with `evals/sample-project/setup.py`.

Tests to write:

1. **Markdown converter** (`skills/dashboard/scripts/dashlib/md.py`): headings, lists, a table, a fenced code block, a `mermaid` block becomes `<pre class="mermaid">`, and `<script>` in the input comes out escaped (never as a live tag).
2. **Path safety:** `/api/doc/<n>?path=../../chopchop.yaml` and an absolute path are refused. Only `.md` and `.json` inside the feature folder are served.
3. **API shapes** on a temp workspace: `/api/features` returns a list where each item has `number`, `title`, `stage`, `steps`, `waiting_on`, `tasks`. `/api/feature/1` has `docs`, `tasks`, `events`, `comments`.
4. **Start, status, stop** of a real server on a free port: `--start --no-open --json` gives a `url`. `--status --json` gives `"running": true` and the same `url`. `--stop` then makes `--status --json` say `"running": false`.
5. **Live stream:** connect to `/api/stream`, touch a file under the feature folder, and read a `changed` event within 5 seconds.
6. **Broken data:** a half-written `work/comments/triage.json` (invalid JSON) must not crash any route.

`skills/run/scripts/chopchop_run.py` (function `dashboard()`) reads `--status --json` and `--start --json`. It needs the keys `running` and `url`. Make sure test 4 pins those names.

**Done when:** `(cd skills/dashboard && python3 -m unittest discover -s tests)` says `OK` with at least 6 tests.

### Step 4. Look at the dashboard in a browser and fix what is wrong

Build a demo workspace:

```sh
D=/tmp/chopchop-dash-demo
rm -rf $D && mkdir -p $D
cp -R /Users/buminduyasith/mydata/work/chopchop-trial/_chopchop $D/_chopchop
python3 docs/handoff/make_demo.py $D/_chopchop          # adds review comments, events, a second feature
python3 skills/dashboard/scripts/chopchop_dashboard.py --start --no-open --workspace $D/_chopchop
```

If `make_demo.py` fails because of a folder name, open it and fix the feature folder name at the top to match `ls $D/_chopchop`.

Open the printed link. Check each line below at two window sizes: about 1440 by 900, and about 665 by 734 (the Claude built-in browser pane, where the user looks at it). If you use a fixed test size in a shared browser tab, reset it when you are done.

| Check | Must be true |
| --- | --- |
| Theme | Dark with no saved choice. The toggle switches to light and the choice survives a reload. |
| Home | One card per feature: title, key, steps, task progress, a "waiting on" badge, Summary lines. Filters by text, step and "waiting on" work. |
| Feature page | 8 steps on top, a plain "Waiting on" line, tabs: Overview, Brief, Design, Spec, Tasks, Review, Activity. |
| Compare | Design and spec side by side at both sizes. Each pane reaches the bottom of the window. The page itself does not scroll. Steps and banner are hidden. There is a clear way back. |
| Single document | Brief, Design and Spec use the full width and height. No inner scroll box. No big empty band at the bottom. |
| Diagrams | The two design diagrams show (drawn on the server). They are readable in dark. A ```mermaid block renders, or shows as code when offline. |
| Tasks | A board: Todo, Building, Committed, In review, Done. A click opens the task's Markdown in a side panel as tall as the window. |
| Review tab | PRs on top, groups by priority, each comment with: original text, plain explanation, verdict, why, fix, impact, reply draft with a working Copy button, the person's decision. A comment with no explanation shows as "not explained yet". Filters work. |
| Activity | Newest first, with a kind badge and time. |
| Live | Edit any `.md` in the demo folder. The page updates in about 2 seconds without a reload and keeps the scroll position. |
| Sideways scroll | None on the page at either size. Wide tables and diagrams scroll inside their own box. |
| Console | No errors in the browser console. |

Also check every route answers: `curl -s <url>/api/features`, `/api/feature/1`, `/api/doc/1?path=design/design.md`, `/api/prs`, `/api/system`.

Stop it when done: `python3 skills/dashboard/scripts/chopchop_dashboard.py --stop --workspace $D/_chopchop`.

**Done when:** every row in the table is true at both sizes, and step 3's tests still pass.

### Step 5. Review the comments tool

Nobody has reviewed this code. Read these and compare them with `docs/v2-spec.md` section 8:

1. `skills/comments/SKILL.md`: the user words `--fix`, `--watch` and `--replies` from `README.md` must each have a row in its "What the user typed" table. The loop must be: find PRs, fetch, pack, start one `chopchop:triager`, merge the triage, tell the user, record decisions, plan, fix per batch with `chopchop:builder` and `chopchop:code-reviewer`, commit, push, reply drafts, post only after a yes.
2. `skills/comments/SCHEMA.md`: the shapes of `prs.json`, `threads.json` and `triage.json` must match spec section 8 exactly, because `stage.comments_view()` and the dashboard read them.
3. `agents/triager.md`: it must say to decide on evidence, to be honest (never call a real problem a false positive to save work), to group by root cause across PRs and repos, and to write short simple replies.
4. Safety in `skills/comments/scripts/chopchop_comments.py`: `--post` refuses without `--yes`. `--push` never forces and refuses the base branch, `main` and `master`. `--commit` refuses when the repo is not on the PR's branch.

Run its tests: `(cd skills/comments && python3 -m unittest discover -s tests)`. Expect 42 tests, `OK`.

**Done when:** all 4 points are true, or fixed and tested.

### Step 6. Cross-checks between the parts

1. Every flag named in `README.md` exists. For each command table in the README, run the script with `--help` and compare. Fix the README or the SKILL.md, whichever is wrong.
2. `stage.py` reads `approved_by` and `changed_since_approval` from `spec.md` front matter. Confirm `spec --approve` writes exactly those keys: `grep -n "approved_by\|changed_since_approval" skills/spec/scripts/chopchop_spec.py`.
3. `python3 skills/run/scripts/chopchop_run.py --where "" --workspace /tmp/chopchop-dash-demo/_chopchop` prints a `Dashboard:` line with a link, and a second call does not start a second server.
4. `claude plugin validate . --strict` ends with `Validation passed` (a missing icon warning is fine).
5. No long dashes: `grep -rnP "[\x{2013}\x{2014}]" --include="*.md" --include="*.py" --include="*.html" --include="*.json" . | grep -v "\\\\u201"` prints nothing. Lines that only contain the escaped forms `–` or `—` inside Python are fine.
6. Run step 1 again. Every line must say `OK`.

**Done when:** all 6 are true.

### Step 7. Trial A: the shop sample (two Node repos)

Goal: run the whole flow with a real agent on real code and write down what breaks.

Set up (safe: every remote is a local folder):

```sh
T=/tmp/chopchop-trial-a
rm -rf $T && mkdir -p $T/remotes $T/_chopchop
SRC=/Users/buminduyasith/mydata/work/chopchop-trial/remotes
for r in shop-api shop-web; do
  git clone -q --bare $SRC/$r.git $T/remotes/$r.git
  (cd $T/remotes/$r.git && git remote remove origin 2>/dev/null; \
   for b in $(git for-each-ref --format='%(refname:short)' refs/heads | grep -v -x -e main -e develop); do git branch -q -D "$b"; done)
  git clone -q $T/remotes/$r.git $T/$r
  (cd $T/$r && git checkout -q develop && npm run check | tail -3)
done
cp docs/handoff/trial-a.chopchop.yaml $T/_chopchop/chopchop.yaml
```

Both `npm run check` runs must pass before you start. `git -C $T/shop-api remote -v` must show a path under `/tmp`, never GitHub.

Run it in stages. Each stage is a fresh headless session, like a new chat. `docs/handoff/run_stage.sh <trial dir> <stage name> "<prompt>"` does that and saves the output under `docs/handoff/trial-logs/`. Open the script first and check the plugin path in it. It uses `--permission-mode dontAsk` with a fixed tool list. In that mode the question tool is refused, so every prompt uses `--auto`.

| Stage | Prompt | Then check |
| --- | --- | --- |
| a1 | `/chopchop:run Refund requests for delivered orders. A customer can request a refund for one of their own orders when it is delivered, with a required reason. Support sees the request and approves or rejects it, with an optional note. The customer sees the refund status on the order page. --auto` | A new feature folder. `requirements/requirement.md`, `grooming.md`, `brief.md` exist. The brief has a Summary and `status: "draft"`. The reply asks for an approval and does not go on to the design. |
| a2 | `/chopchop:run approve. I am Trial Dev. Then carry on with --auto.` | `brief.md` says approved by Trial Dev. `design/design.md` exists with its two diagrams. The reply stops and asks for the lead. |
| a3 | `/chopchop:run The lead Trial Lead approved the design. Carry on with --auto.` | `design.md` approved by Trial Lead. `spec/spec.md` and `spec.json` exist. The reply stops and asks for the spec approval. |
| a4 | `/chopchop:run approve the spec, I am Trial Dev. Then cut the tasks, say yes to the feature branch, and build every task with --auto.` | `tasks/T*.md` exist, each with a Summary. `work/auto.json` shows every task `committed`. Both repos have a `feature/IDEA-1/build` branch with one commit per task. `npm run check` passes on those branches. Nothing imports or copies `src/utils/orderHelpers.js` or `src/legacy/ordersService.js` (the traps). |

After each stage also run:

```sh
python3 skills/run/scripts/chopchop_run.py --list --workspace $T/_chopchop
```

The step and "waiting on" must match the table. Start the dashboard on `$T/_chopchop` and look at the feature page too.

Write what happened in `docs/v2-trials.md` (start it with a `## Summary`): per stage the time, the cost from the log, what worked, and every problem with the file and the fix you made.

**Done when:** all four stages pass their checks, or each failure is fixed in the plugin and the stage passes on a second run.

### Step 8. Trial B: a real open source Python library

Goal: the same flow on software chopchop has never seen.

```sh
T=/tmp/chopchop-trial-b
rm -rf $T && mkdir -p $T/remotes $T/_chopchop
git clone -q --depth 60 https://github.com/python-humanize/humanize.git $T/src
git clone -q --bare $T/src $T/remotes/humanize.git && rm -rf $T/src
(cd $T/remotes/humanize.git && git remote remove origin 2>/dev/null)
git clone -q $T/remotes/humanize.git $T/humanize
git -C $T/humanize remote -v            # must show /tmp/..., never github.com
(cd $T && uv venv -q venv)
(cd $T/humanize && SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 VIRTUAL_ENV=$T/venv uv pip install -q -e ".[tests]")
$T/venv/bin/python -m pytest -q -x $T/humanize/tests | tail -2      # expect about 764 passed
cp docs/handoff/trial-b.chopchop.yaml $T/_chopchop/chopchop.yaml
```

The repo profile must use the venv. After the first stage, open `$T/_chopchop/repos/humanize.md` and set its test command to `/tmp/chopchop-trial-b/venv/bin/python -m pytest -q`. If the file does not exist yet, create it with `python3 skills/code/scripts/chopchop_code.py --profile humanize --workspace $T/_chopchop` and then edit the command.

Same four stages as trial A, with this first prompt:

`/chopchop:run Add humanize.bitrate(bits_per_second): it turns 1500000 into "1.5 Mbps", the same way naturalsize works for bytes. --auto`

Checks: the same as trial A, plus: the new function sits next to the similar ones, it is exported the way the others are, the tests follow the repo's own test style, and the whole test suite still passes.

**Done when:** the four stages pass, and the results are in `docs/v2-trials.md`.

### Step 9. Trial C: real PR review comments, read only

```sh
T=/tmp/chopchop-trial-c && rm -rf $T && mkdir -p $T/_chopchop && cd $T
C=/Users/buminduyasith/mydata/work/chopchop-v2/skills/comments/scripts/chopchop_comments.py
python3 $C --pr https://github.com/cli/cli/pull/12942 --workspace $T/_chopchop
python3 $C --fetch --workspace $T/_chopchop
python3 $C --pack --workspace $T/_chopchop
```

Then, in a Claude Code session started with `claude --plugin-dir /Users/buminduyasith/mydata/work/chopchop-v2` inside `$T`, type `/chopchop:comments https://github.com/cli/cli/pull/12942` and let it triage. **Tell it not to fix and not to post anything.** Do the same for `https://github.com/django/django/pull/22014`.

Check:

- `comments.md` exists, starts with a Summary, and lists every comment.
- Each comment has: a plain explanation, a verdict, a priority, a why with a code citation, a fix, an impact and a reply.
- Comments about the same thing share a group.
- The verdicts look fair when you read 5 of them against the real PR.
- The dashboard Review tab shows all of it (start the dashboard on `$T/_chopchop`).
- Nothing was posted on GitHub. `gh` was only used to read.

**Done when:** both PRs pass these checks and the results are in `docs/v2-trials.md`.

### Step 10. Evals, fixes and wrap-up

1. Run the evals. They are slow (10 to 30 minutes each) and cost tokens:

   ```sh
   claude plugin eval . --case groom-auto --scaffold --allow-tools Write Edit Bash
   claude plugin eval . --case run-gate --scaffold --allow-tools Write Edit Bash
   claude plugin eval . --case design-auto --scaffold --allow-tools Write Edit Bash
   claude plugin eval . --case learn-system --scaffold --allow-tools Write Edit Bash
   ```

   If a flag is refused, run `claude plugin eval --help` and adjust. Results land in `evals/results/<time>/report.html`. Read each failed grader, fix the skill text or the script, and run that case again.
2. Add one more eval, `evals/comments-triage/`: the scaffold builds a workspace with a fixture `threads.json` (reuse a fixture from `skills/comments/tests/`), the prompt asks to explain the review comments, and the graders check that `comments.md` exists, has a Summary, and that nothing was posted. Copy the file shapes from `evals/groom-auto/`.
3. Fix everything the trials and evals showed. After every fix, run the unit tests of the skill you touched.
4. Run step 1 one last time. Every line must say `OK`.
5. Go through the goals table in section 2 and write, per goal, "met" or what is missing, at the end of `docs/v2-trials.md`.
6. Tell the user what is done and what is not. **Ask before you commit.** If they say yes, suggested commits, in this order: shared library (stage, plain, events); clean-up of old skills; groom; run; dashboard; comments; README, docs, evals, version.

## 7. Decisions already made (do not reopen without the user)

| Decision | Why |
| --- | --- |
| The PR comment command is `/chopchop:comments`. | `/chopchop:review` already means the local code review. |
| `requirement.md` keeps its name and is the "source" file. | Many scripts read that name. `brief.md` and `grooming.md` are the new files next to it. |
| Three gates: brief (developer), design (lead), spec (developer). | The user wants people to check documents. Agents never approve. |
| The build keeps one PR per repo with one commit per task. `--wave` only pauses. | Fewer PRs for people to review, and reviewers can go commit by commit. |
| A merged PR marks its tasks done. | A person merges, so a person still decides. |
| Mermaid loads from a pinned CDN link in the browser. Design diagrams are drawn on the server. | No big library in the repo, and the main diagrams work offline. |
| The dashboard is read only. Approvals happen in chat. | Simpler and safer. |
| Version is 0.10.1. | Released as the v0.10.1 GitHub release. Only the user decides when to release. |

## 8. Known risks

- **No skill has been run by a real agent yet.** `groom`, `run` and `comments` are tested only as scripts. Expect wording problems in the SKILL.md files during the trials. That is what steps 7 to 9 are for.
- **Headless runs cannot ask questions.** That is why the trial prompts use `--auto`. The interview itself (step 4 of `skills/groom/SKILL.md`) must be tried once by hand in a normal Claude Code chat: start `claude --plugin-dir <chopchop-v2>` in a trial folder, type `/chopchop:groom <idea>` without `--auto`, and check that it asks at most 4 questions a round, each with a "Not sure, ask the BA" answer.
- **The dashboard page changed a lot at the end** and was not looked at after the last edits. Step 4 is not optional.
- **`/tmp` folders vanish on restart.** Every trial step above rebuilds its folder from scratch.
- **Costs.** A full trial took about 30 minutes and about 800k helper tokens in earlier runs. Run one trial at a time.

## 9. Quick reference

```sh
# where a feature stands
python3 skills/run/scripts/chopchop_run.py --list --workspace <ws>
python3 skills/run/scripts/chopchop_run.py --where "<text>" --no-dashboard --workspace <ws>

# grooming
python3 skills/groom/scripts/chopchop_groom.py --prepare <n> --workspace <ws>
python3 skills/groom/scripts/chopchop_groom.py --status <n> --workspace <ws>

# dashboard
python3 skills/dashboard/scripts/chopchop_dashboard.py --start --no-open --workspace <ws>
python3 skills/dashboard/scripts/chopchop_dashboard.py --stop --workspace <ws>

# PR comments
python3 skills/comments/scripts/chopchop_comments.py --status --workspace <ws>

# a sample workspace with 4 small repos and one feature
python3 evals/sample-project/setup.py --to /tmp/refunds

# try the plugin by hand
cd <a trial folder> && claude --plugin-dir /Users/buminduyasith/mydata/work/chopchop-v2
```

`<ws>` is the `_chopchop` folder. A feature moves through these steps, read from its files by `stage.py`:

```
groom -> brief -> design -> spec -> tasks -> build -> prs -> done
```
