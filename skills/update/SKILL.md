---
name: update
description: Update the chopchop plugin to the latest version in place, without removing and installing it again, and optionally turn on automatic updates. Use when the user asks to update, upgrade or refresh chopchop, asks which version they have, or wants chopchop to update by itself.
argument-hint: "[--check | --auto on | --auto off]"
---

# Update

Bring chopchop up to date where it is installed. The script is
`${CLAUDE_SKILL_DIR}/scripts/chopchop_update.py`. Run it with `python3`.

| User types | Do this |
| --- | --- |
| nothing | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_update.py` |
| `--check` | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_update.py --check` |
| `--auto on` / `--auto off` | Ask first (step 3), then run it with that flag. |

## 1. Update

The script refreshes the chopchop marketplace from GitHub, then updates chopchop in every
scope it is installed in (user, project or local). It uses the Claude Code CLI
(`claude plugin marketplace update` and `claude plugin update`), so nothing is removed or
installed again.

## 2. Reply

One or two lines:

- **Updated:** "chopchop is updated from 0.4.0 to 0.5.0. Run `/reload-plugins` (or restart
  Claude Code) to use it." Then name what is new, if you can tell from the skills you see.
- **Already latest:** "chopchop is already on the latest version (0.5.0)."
- **Loaded with --plugin-dir:** say it comes from a folder: `git pull` there, then
  `/reload-plugins`.
- **Failed:** show the error in plain words. If the `claude` command is not found, tell them
  to run `/plugin marketplace update chopchop`, then open `/plugin`, go to the Installed
  tab, pick chopchop and choose "Update now".

You cannot run `/reload-plugins` yourself. Ask the user to run it.

## 3. Auto-update (only when asked, or offer it once)

After an update, if `--check` shows auto-update is off, offer it once in one line: "Want
chopchop to update by itself? Claude Code would check in the background and tell you when a
new version is ready."

Only on a clear yes, run `--auto on`. It changes the user's Claude settings (it writes
`autoUpdate: true` for the chopchop marketplace and keeps a `settings.json.bak`). To stop
it, `--auto off`.

## Rules

- Never remove or reinstall the plugin to update it.
- Never change Claude settings unless the user said yes to auto-update.
- Never use `-y` or accept commands on the user's behalf.
