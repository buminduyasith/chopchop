---
name: diagram
description: Draw a feature's two design diagrams well, the same way every time. The high-level design shows the parts, the repo each lives in and what talks to what (a structure, never steps). The main flow shows the numbered messages in time order, with a failure answer for each. Writes design/architecture.json and design/flow.json, checks the layout (no line through a box, no shared cells, no part inside another repo's group, no step numbers on the structure), and draws a static SVG for feature.html plus Mermaid for design.md. Use when the design skill reaches its write step, or when the user asks to draw, fix, redo or explain an architecture diagram, a high-level design, a sequence diagram or a flow diagram.
argument-hint: "[feature] [--arch FILE] [--flow FILE]"
---

# Diagram

Two pictures carry a design. You decide what is in them and where each part sits. A script
checks the placement, routes the lines and draws them. Never draw either picture by hand, in
SVG or in Mermaid: the page and design.md must show the same thing.

| Picture | File | Answers | Looks like |
| --- | --- | --- | --- |
| High-level design | `design/architecture.json` | What parts are there, which repo owns each, what talks to what | Boxes grouped by repo, labeled lines, no numbers |
| Main flow | `design/flow.json` | In what order things happen, and what happens when each step goes wrong | A sequence: lanes, numbered arrows, replies dashed |

If you catch yourself numbering the lines of the high-level design, stop: that is the flow.
The high-level design is a map of the parts. The flow is the trip through them.

The file format, with a full example, is in `references/format.md`. Read it before you write
either file.

## 1. List the parts

From the picks in `design/options.md`, the system map (`_chopchop/system/system-map.json`)
and what the helpers read in the code, list every part the feature touches:

- People who start or receive something (customer, support agent).
- Screens, APIs, services, jobs, tables, topics, libraries the feature adds or changes.
- Parts that stay the same but the reader needs for context: take them from the system map,
  so they are real. Leave out parts the feature does not touch.
- Outside systems (card provider, email provider).

At most 14 parts. More than that: merge small parts of one repo into one box ("Refund
service" for an API and its handler).

For each part: `status` is `new`, `changed`, `same` or `external`. `repo` is the repo it
lives in (people and outside systems have none). `note` is 1 to 4 words that say what
changes ("Refund button", "POST /refunds", "every minute").

## 2. Place the parts (the high-level design)

Place each part on a grid by its connections. Rows go down, columns go right. Use at most 5
columns. More parts means more rows, not more columns.

1. **The main path reads left to right.** People in column 0, then the screen, then the API
   or service, then what the service calls.
2. **Stores sit under their owner.** A table goes one row under the part that writes it, in
   the same column. A second reader of that table sits next to it, not across the picture.
3. **Topics and queues sit between the producer and the consumer.**
4. **Outside systems go to the right edge or the top row**, near the part that calls them.
5. **One repo, one block.** A repo's parts fill one block of next-door cells. No other part
   may sit inside that block. The script draws a named box around each repo.
6. **Leave a corridor for links that go back.** A link back to a person (an email, a
   notification) needs an empty row or column to travel through. Do not fill it.
7. **A part that only one other part uses sits next to it.**

Then link the parts. One link per pair. The label says what moves along it, in 1 to 4 words:
"POST refunds", "reads pending", "refund.done". Never a step number, never "then". `kind` is
`call`, `data` (read or write a store), `event`, or `external` (to an outside system).

## 3. Write the flow

The flow is the main story in time order, then the 1 to 3 error paths that matter most.

- `participants`: the parts the flow passes, by their architecture ids, in the same left to
  right order as the high-level design. At most 8.
- `messages`: numbered 1, 2, 3 with no gaps. 6 to 14 is a good size.
- Each message has `say` (2 to 6 words on the arrow), `line` (one plain sentence), `kind`,
  and the `stories` it serves.
- An answer back is `kind: "reply"`. It is drawn dashed and needs no failure answers.
- A message that only happens in one case gets `"if": "older than 30 days"`. It is drawn in
  amber with the condition on it. Use this for the error paths.
- Every story in requirement.md has a message, or sits in `out_of_scope`.

Each message kind must answer its failure questions (fails, slow, twice, caller). The table
is in `references/format.md`. Answer from the code: the same retry, timeout and idempotency
rules it already uses. When the code does not say, write your suggestion as
`{"text": "...", "suggested": true}` for the lead to confirm.

## 4. Check and draw

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_diagram.py --draw [REF]
```

It checks both files, then writes `work/diagrams.html` with both pictures. Exit 0 is clean.
Exit 1 lists problems, each with its fix:

| Problem | Fix |
| --- | --- |
| A line cannot avoid a part | Move one end, or open a corridor (an empty row or column) |
| Two parts in one cell | Move one to a free cell next to its closest link |
| A part inside another repo's group | Move it outside that block of rows and columns |
| Two groups overlap | Give each repo its own block |
| A link label is a step number | Say what the link carries. The order goes in flow.json |
| Too wide | Fewer columns, more rows |

Fix and run it again, at most 3 rounds. Then fix the warnings that are cheap to fix. Missing
failure answers do not stop the drawing, but they block the design's approval request.

Do not open the preview in a browser just to look: the checks cover lines through parts,
crossings, overlaps and width. Open it (`--open`) only when the user asks to see it.

`--mermaid` prints the Mermaid copies. You rarely need it: the design build writes them into
design.md by itself.

## 5. Outside a feature

The same rules work for any diagram the user asks for:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_diagram.py --draw --arch path/architecture.json --flow path/flow.json --out path/
```

## 6. Reply

Three lines at most: what each picture shows, what is still missing (failure answers,
warnings you left), and the preview path.
