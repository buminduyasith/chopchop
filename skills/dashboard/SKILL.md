---
name: dashboard
description: Start, stop or check the chopchop live dashboard, a local page that shows every feature, its step, who it waits for, the brief, design and spec (side by side with Compare), the task board, the PR review comments and the activity log, updated live as files change. Use when the user runs dashboard, asks to open, show, start or stop the dashboard or the board, wants to see progress, or asks for the link. /chopchop:run starts it by itself.
argument-hint: "[--stop | --status]"
---

# Dashboard

One live page for every feature in the `_chopchop` folder. It only reads files. It runs on this
machine only (`127.0.0.1`).

The script is `${CLAUDE_SKILL_DIR}/scripts/chopchop_dashboard.py`. Run it with `python3` from the
user's project folder. It needs the `tasks` skill folder next to it.

## What the user typed

| User typed | Do this |
| --- | --- |
| nothing | Step 1: start it and open it. |
| `--stop` | `--stop`. Say it stopped in one line. |
| `--status` | `--status`. Say if it runs, and the link. |

## 1. Start

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_dashboard.py --start
```

It is safe to run again: when the dashboard already runs, it prints the same link. When the
port is taken, it picks the next free one. Add `--no-open` when the user does not want a browser
window.

Say the `Dashboard:` link in one line, and that the page updates by itself.

## 2. Stop or check

```
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_dashboard.py --stop
python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_dashboard.py --status
```

## What the page shows

- **Home:** one card per feature: its step, its tasks, who it waits for, and its Summary.
- **A feature:** the steps on top, then Brief, Design, Spec, Changes, Tasks, Review and Activity.
- **Compare:** the design and the spec side by side, each the full height of the window.
- **Changes:** every file the spec adds, changes or deletes, as a folder tree per repo with git colours.
- **Tasks:** a board. A click on a task opens its Markdown with its diagrams.
- **Review:** every PR comment explained, grouped, with the fix and a reply draft.

## Rules

- It listens on `127.0.0.1` only and answers reads only. It never changes a file.
- It never sends workspace files anywhere.
- Approvals happen in chat, not on the page.
- If the script fails, show the error and the fix. Do not work around it.
