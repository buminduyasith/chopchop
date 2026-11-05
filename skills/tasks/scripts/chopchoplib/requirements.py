"""Stories and acceptance criteria from a requirement.md written by the stories skill.

Ids look like PAY-121 for a story and PAY-121.AC2 for its second acceptance criterion.
check, design and spec all read requirements through here.
"""

import re
from pathlib import Path

from .features import parse_front_matter

STORY_RE = re.compile(r"^## (\S+)(?: (.*))?\n<!-- chopchop:(story|epic) .*?-->$", re.M)


def section(block, title):
    m = re.search(r"(?m)^### %s[ \t]*\n" % re.escape(title), block)
    if not m:
        return None, None
    rest = block[m.end():]
    end = re.search(r"(?m)^(### |## |---\s*$)", rest)
    return rest[:end.start() if end else len(rest)].strip(), m.end()


def split_items(text):
    """Bullets or numbered lines become items; otherwise each paragraph is one."""
    lines = text.split("\n")
    items, cur = [], None
    for line in lines:
        m = re.match(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$", line)
        if m:
            if cur:
                items.append(cur)
            cur = m.group(1).strip()
        elif cur is not None and line.strip() and line[:1] in " \t":
            cur += " " + line.strip()
        elif cur is not None and line.strip():
            items.append(cur)
            cur = None
    if cur:
        items.append(cur)
    if items:
        return items
    return [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def requirement_items(path):
    """Stories and their acceptance criteria from a requirement.md written by the stories skill."""
    text = Path(path).read_text(encoding="utf-8")
    _, body = parse_front_matter(text)
    offset = text.count("\n", 0, len(text) - len(body))
    heads = list(STORY_RE.finditer(body))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        block = body[m.start():end]
        line = offset + body.count("\n", 0, m.start()) + 1
        sid, title, kind = m.group(1), (m.group(2) or "").strip(), m.group(3)
        desc, _ = section(block, "Description")
        if kind == "epic":
            desc = block[m.end() - m.start():].split("\n## ", 1)[0]
            desc = re.sub(r"(?s)### Acceptance criteria.*", "", desc).strip()
        out.append({"id": sid, "kind": kind, "title": title, "text": (desc or "")[:1500],
                    "source": "%s:%d" % (Path(path).name, line)})
        ac, at = section(block, "Acceptance criteria")
        if ac:
            ac_line = offset + body.count("\n", 0, m.start() + at) + 1
            for n, item in enumerate(split_items(ac), 1):
                out.append({"id": "%s.AC%d" % (sid, n), "kind": "ac", "title": title, "text": item,
                            "source": "%s:%d" % (Path(path).name, ac_line)})
    return out


def story_ids(items):
    """Only the stories (no epic, no ACs)."""
    return [r["id"] for r in items if r["kind"] == "story"]
