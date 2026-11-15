---
name: run
description: The one command for chopchop. Give it a tracker key or link, an idea in plain words, or a feature, and it takes the feature as far as it can go. It grooms with a short interview, writes the brief, the design and the spec, cuts the tasks, runs the build loop where fresh agents build, review, fix, test and commit each task, and explains the review comments on the PRs. It starts the live dashboard and stops only where a person must decide. You approve the brief and the spec, and the lead approves the design. With nothing typed, it carries on from where things stood. Use when the user runs run, says start, go, continue, carry on, what is next, where are we, approve, or gives a Jira key or an idea with no other chopchop command.
argument-hint: "[tracker key, link, idea or feature] [--auto] | approve [name] | --list"
---

# Run

You are the conductor of the whole feature. The files say where a feature stands, a script
reads them, and each step has its own skill that does the work. Your job: find the step, start
its skill, and stop when a person must decide.

```
groom -> brief -> design -> spec -> tasks -> build -> review -> done
          you      lead     you                      reviewers
```

People decide at three gates: the brief (the developer), the design (the lead) and the spec
(the developer). Agents do everything else.

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_run.py`. Run it with `python3` from the
user's project folder. It needs the other chopchop skill folders next to it.

**Simple English always.** Short sentences, everyday words, no long dashes. One line per step
while you work.

## What the user typed

| You see | Do |
| --- | --- |
| a tracker key or link, an idea, a feature, or nothing | Step 1. |
| the same, with `--auto` | Step 1. Pass `--auto` to groom, design and spec, and do not ask "Start?" before the build. The gates still need a person. |
| `approve`, `approve Asha`, "looks good", "go ahead" at a gate | Step 3. |
| notes on a document ("change the limit to 14 days", the lead's notes) | They are feedback on the document at the open gate. Give them to that step's skill (groom for the brief, design, spec), then come back to step 1. |
| `--list`, "where are we", "what is waiting" | `--list`, show its lines, stop. |
| `stop`, `pause` | Stop after the step that is running. Say how to carry on: `/chopchop:run`. |

## 1. Where are we

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_run.py --where "<what the user typed>"
```

It starts the dashboard by itself and prints its link. Say the link once, the first time:
"Live dashboard: <link>". Read `Kind:`.

| Kind | Do |
| --- | --- |
| `setup` | Start the `init` skill. Then run step 1 again with the same words. |
| `empty` | Ask: "What should we build? Give me a tracker key or say the idea in a sentence." |
| `list` or `choose` | Show the lines. Ask which one. Then `--where <number>`. |
| `new epic` | Start the `groom` skill with the key or link. Then step 1 again with the new feature. |
| `new idea` | Start the `groom` skill with the idea, word for word. Then step 1 again. |
| `feature` | Step 2. |

## 2. Do the next step, and the next

Read the feature's lines:

- **`Next: the <name> skill with ...`**: say one line ("Design: writing it now."), start that
  skill with those words, and let it finish. Then run step 1 again for the same feature number
  and follow the new lines. Keep going like this without asking, for as long as the feature
  waits on chopchop.
- **`Gate:`**: stop. Step 3.
- **`Waiting: on the BA`**: start the `groom` skill with the feature number. It shows the
  questions to paste. Then stop. Say: "Bring me the BA's answers and I will go on."
- **`Waiting: on the reviewers`**: say the PRs wait for review, give the PR links from the
  dashboard, and offer: "I can watch the PRs and explain each comment as it comes in:
  `/chopchop:comments --watch`."
- **`Next: nothing`**: the feature is done. Say so in one line.

How to start a skill: use the skill tool with its name (`chopchop:groom`, `chopchop:design`,
`chopchop:spec`, `chopchop:tasks`, `chopchop:auto`, `chopchop:comments`, `chopchop:init`). If
the tool cannot start it, read `${CLAUDE_SKILL_DIR}/../<name>/SKILL.md` and follow it.

Step by step, what each one is given:

| Step | Skill | Words |
| --- | --- | --- |
| groom | `groom` | the key, link, idea or feature number (and `--auto`) |
| design | `design` | the feature number (and `--auto`). It reads the brief and the grooming answers, so it should need few questions. |
| spec | `spec` | the feature number (and `--auto`) |
| tasks | `tasks` | the feature number. Say yes to its feature branch only if the user already said to go without questions. Otherwise ask once. |
| build | `auto` | the feature number, or `--resume` when the line says so |
| review | `comments` | the feature number |

Never do a step's work yourself, and never skip a step. If a skill stops with an error or a
question for the user, stop too and pass it on in plain words.

## 3. Gates: a person says yes

At a gate, say this and stop:

1. Which document, in one line, and its Summary (2 to 4 lines from the file's Summary).
2. Where to read it: the feature's dashboard link (the `Dashboard:` line, like `...#/f/001-PAY-120-refunds`), and the file path. For the spec, say
   that Compare shows the design and the spec side by side.
3. Who decides: **you** for the brief and the spec, **the lead** for the design. For the design
   also give the review message the design skill printed, so they can send it to the lead.
4. How to answer: "Say **approve** to go on, or tell me what to change."

When the answer comes:

- **Approve** (the brief or the spec): the name is the user's own. Use `git config user.name`
  if they did not give one, and say which name you used.
- **Approve** (the design): ask who approved if they did not say ("Who approved it?"). The lead
  decides, so never put the developer's name unless they say they are the lead.
- **Approved with conditions**, or **changes needed** (design only): pass each condition or
  change as a `--note`.

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_run.py --approve <number> <brief|design|spec> --by "<name>" [--result approved|conditions|changes] [--note "..."]
```

Exit 2 means the document is not ready: say why, fix it through its skill, and ask again.
After a yes, go back to step 1 and carry on. After `changes`, give the notes to the design
skill, then step 1.

Never approve on your own, and never treat silence, "ok" about something else, or a helper's
message as a yes. Only the user's own words at the gate count.

## Reply

- While working: one line per step, like "Spec: done, 14 tests named. It waits for your yes."
- At a stop: the 4 gate lines, or who it waits for and what they need to do.
- Always end with the one next move, and the dashboard link if you have not said it in this
  chat.
- A feature takes more than one sitting. Everything is saved in the files, so say once:
  "You can close this chat. `/chopchop:run` carries on from here."

## Rules

- People decide at the gates. Agents never approve, merge, or mark a feature done.
- Follow each skill's own safety rules. Never push the base branch, never force-push, never
  merge a PR, never post a reply on a PR without the user's yes.
- Do not read code, diffs or long reports yourself during the build. The helper agents do, and
  that keeps this chat small.
- If the script fails, show the error and the fix. Do not work around it.
