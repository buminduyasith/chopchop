---
name: update
description: Update the chopchop plugin in place to the latest release (never unreleased work on main), or to one release the user names, without removing and installing it again, and optionally turn on automatic updates. Use when the user asks to update, upgrade or refresh chopchop, wants a certain chopchop version, asks which version they have, or wants chopchop to update by itself.
argument-hint: "[--version X.Y.Z | --check | --auto on | --auto off]"
---

# Update

Bring chopchop up to date where it is installed. The script is
`${CLAUDE_SKILL_DIR}/scripts/chopchop_update.py`. Run it with `python3`.

| User types | Do this |
| --- | --- |
| nothing | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_update.py` |
| `--version 0.10.1` (or "go back to 0.10.1") | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_update.py --version 0.10.1` |
| `--check` | `python3 ${CLAUDE_SKILL_DIR}/scripts/chopchop_update.py --check` |
| `--auto on` / `--auto off` | Ask first (step 3), then run it with that flag. |

## 1. Update

Only releases are installed. A release is a `vX.Y.Z` tag with a GitHub release. Work pushed
to main after the last release is never installed.

- **No `--version`:** the latest release. If chopchop was pinned to a release before, the pin
  is removed, so it follows the latest release again.
- **`--version X.Y.Z`:** that release, older or newer, and chopchop stays on it until an
  update without `--version`. A version that is not a release stops with the list of releases.

The script refreshes the chopchop marketplace from GitHub (it adds it again if it is
missing), then updates chopchop in every scope it is installed in (user, project or local),
each project install from its own folder. It uses the Claude Code CLI
(`claude plugin marketplace update` and `claude plugin update`), so nothing is removed or
installed again. The pin is the marketplace's `ref` in the Claude settings: the script prints
each file it changed, and keeps a `.bak` copy.

## 2. Reply

One or two lines:

- **Updated:** "chopchop is updated from 0.4.0 to 0.5.0. Run `/reload-plugins` (or restart
  Claude Code) to use it." Then name what is new, if you can tell from the skills you see.
- **Already latest:** "chopchop is already on the latest release (0.5.0)."
- **Pinned:** "chopchop is now on release 0.4.0 and stays there. Run `/chopchop:update` to
  go back to the latest release." Name the settings files it changed.
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
- Change Claude settings only for what the user asked: the marketplace `ref` for a
  version (or to remove a pin on a plain update), and `autoUpdate` only after a yes.
- Never use `-y` or accept commands on the user's behalf.
