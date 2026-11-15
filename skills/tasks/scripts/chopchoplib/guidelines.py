"""The team's code guidelines: one file of rules for every repo.

It lives at _chopchop/guidelines.md (or where `guidelines:` in chopchop.yaml points). Init
writes it with headings and examples inside comments, as placeholders. The spec writer and
the developer agents follow it. A repo's own style file wins when the two disagree.

A file with only headings, comments and empty bullets has no rules yet: active() returns None
for it, so agents are told to ignore it instead of guessing at the examples.
"""

import re
from pathlib import Path

FILE = "guidelines.md"

TEMPLATE = """# Code guidelines for every repo

<!--
chopchop: the team's code guidelines. One file, for every repo.

Write the rules your team wants in ALL repos here. The spec writer and the developer agents
(code, auto, the reviewer and the PR comment fixer) read this file and follow it.

- Write short rules, one per line, under the headings below. Delete the headings you do not need.
- A rule for one repo only goes in that repo's style file (repos.<name>.style in chopchop.yaml).
  When the two disagree, the repo's style file wins, because it is more specific.
- Everything between these comment marks is ignored. The examples are only ideas: copy a line
  out of the comment to make it a rule.
- While this file has only headings and comments, chopchop treats it as empty, and agents
  follow each repo's style file and its existing code.
-->

## General

<!--
- Keep functions small, with one job each.
- Add no new library without the lead's OK.
-->

## Naming

<!--
- Booleans start with is, has or can.
- Use the words the stories use, not new ones.
-->

## Errors and logging

<!--
- Never swallow an error: log it with context, then return or throw a clear error.
- Never log secrets, tokens or personal data.
-->

## Tests

<!--
- Every new public method gets a unit test.
- Test names say the behavior, like returns_404_when_order_is_missing.
-->

## Security

<!--
- Check all input where it enters the system.
-->

## Do not

<!--
- No commented-out code.
- No TODO without a ticket key.
-->
"""


def path(ws, cfg=None):
    """Where the guidelines file is: `guidelines:` in chopchop.yaml (absolute, or relative to
    _chopchop/), else _chopchop/guidelines.md."""
    raw = (cfg or {}).get("guidelines") if isinstance(cfg, dict) else None
    p = Path(str(raw)).expanduser() if raw else Path(FILE)
    return p if p.is_absolute() else Path(ws) / p


def has_rules(text):
    """True when the file says something beyond its placeholders: a line that is not a heading,
    a comment, a blank line or an empty bullet."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or re.fullmatch(r"[-*+]\s*(\[ \])?", line):
            continue
        return True
    return False


def info(ws, cfg=None):
    """{"path", "exists", "filled"} for the guidelines file."""
    p = path(ws, cfg)
    exists = p.is_file()
    filled = exists and has_rules(p.read_text(encoding="utf-8", errors="replace"))
    return {"path": str(p), "exists": exists, "filled": filled}


def active(ws, cfg=None):
    """The guidelines file path when it has real rules, else None (missing or placeholders only)."""
    i = info(ws, cfg)
    return i["path"] if i["filled"] else None


def describe(i):
    """One line for a person or an agent: what to do with the guidelines file."""
    if i["filled"]:
        return "%s (team rules for every repo: follow them; a repo's style file wins if they disagree)" % i["path"]
    if i["exists"]:
        return "%s has only placeholders, so there are no team rules yet: ignore it" % i["path"]
    return "none. /chopchop:init adds %s for rules that apply to every repo" % FILE


def ensure(ws):
    """Write the placeholder file when there is none. Never overwrites. Returns True if written."""
    p = Path(ws) / FILE
    if p.exists():
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(TEMPLATE, encoding="utf-8")
    return True
