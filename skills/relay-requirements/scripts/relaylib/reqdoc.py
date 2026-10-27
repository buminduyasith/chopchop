"""Render requirement.md (one file per feature, every story as it is in the tracker)
and work out what changed since the last sync.

The script owns the whole file and rewrites it on resync. The only things carried
over from the old file are the creation date and the Sync history section.

Each story heading is followed by a hidden marker with short hashes of its parts:

  ## PAY-121 Customer can request a refund
  <!-- relay:story {"id": "PAY-121", "status": "To Do", "h": {"t": "...", "d": "...", ...}} -->

On resync the new hashes are compared with the old ones, so the report can say
which part of a story changed without keeping a second copy of the data.
"""

import difflib
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import mdconv
from .features import parse_front_matter, render_front_matter

FORMAT = 1
HISTORY_HEADING = "## Sync history"

# Parts that describe WHAT to build. A change here is a requirement change.
CONTENT_PARTS = {
    "t": ("title", lambda i: i["title"]),
    "d": ("description", lambda i: i["description"]),
    "ac": ("acceptance criteria", lambda i: i["acceptance_criteria"]),
    "x": ("other fields", lambda i: [i["type"], i["extra"],
                                     [[a.get("name"), a.get("size")] for a in i["attachments"]]]),
    "c": ("comments", lambda i: [[c.get("author"), c.get("created"), c.get("body")] for c in i["comments"]]),
}
# Parts that describe the ticket's state. Updated quietly, not a requirement change.
META = lambda i: [i["status"], i["priority"], i["assignee"], i["labels"], i["components"],  # noqa: E731
                  i["fix_versions"], i["story_points"], i["subtasks"], i["links"]]

MARKER_RE = re.compile(r"^## (\S+)(?: (.*))?\n<!-- relay:(story|epic) (\{.*?\}) -->$", re.M)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def hashes(issue):
    h = {code: _hash(get(issue)) for code, (_, get) in CONTENT_PARTS.items()}
    h["m"] = _hash(META(issue))
    return h


def marker(kind, issue):
    data = {"id": issue["id"], "status": issue["status"], "h": hashes(issue)}
    # "--" would end the HTML comment early
    return "<!-- relay:%s %s -->" % (kind, json.dumps(data, ensure_ascii=False).replace("--", "-\\u002d"))


# --------------------------------------------------------------------------- read the old file


def read_existing(path):
    """Returns None or {"meta", "items": {id: {kind, title, status, h}}, "history": str, "text"}."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = parse_front_matter(text)
    items = {}
    for m in MARKER_RE.finditer(_without_code(body)):
        try:
            data = json.loads(m.group(4))
        except ValueError:
            continue
        items[data.get("id") or m.group(1)] = {"kind": m.group(3), "title": (m.group(2) or "").strip(),
                                              "status": data.get("status"), "h": data.get("h") or {}}
    history = ""
    at = body.rfind("\n" + HISTORY_HEADING + "\n")
    if at >= 0:
        history = body[at + len(HISTORY_HEADING) + 2:].strip()
    return {"meta": meta, "items": items, "history": history, "text": text}


def _without_code(body):
    """Blank out fenced code blocks, so marker-like text a story quotes is never read as a marker.
    Keeps every character position, so match offsets still point into the original body."""
    out, fence = [], None
    for line in body.split("\n"):
        stripped = line.lstrip()
        if fence is None and stripped[:3] in ("```", "~~~"):
            fence = stripped[:3]
            out.append(" " * len(line))
        elif fence is not None:
            if stripped.startswith(fence):
                fence = None
            out.append(" " * len(line))
        else:
            out.append(line)
    return "\n".join(out)


def sections(text):
    """{id: the rendered section of the epic or a story, without its hidden marker}."""
    _, body = parse_front_matter(text)
    masked = _without_code(body)
    marks = list(MARKER_RE.finditer(masked))
    stop = masked.rfind("\n" + HISTORY_HEADING + "\n")
    stop = stop if stop >= 0 else len(body)
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else stop
        if m.group(3) == "epic":
            cut = masked.find("\n## Stories (", m.start(), end)
            end = cut if cut >= 0 else end
        lines = body[m.start():end].split("\n")
        lines = [lines[0]] + lines[2:]
        while lines and lines[-1].strip() in ("", "---"):
            lines.pop()
        out[m.group(1)] = "\n".join(lines)
    return out


def text_diff(old, new, limit=80):
    """A short unified diff (1 line of context) of one section, for the agent to explain."""
    lines = list(difflib.unified_diff(old.split("\n"), new.split("\n"), lineterm="", n=1))[2:]
    if len(lines) > limit:
        lines = lines[:limit] + ["... (%d more lines, see the file)" % (len(lines) - limit)]
    return "\n".join(lines)


def excerpt(text, limit=40):
    lines = text.split("\n")
    return "\n".join(lines[:limit] + (["... (see the file)"] if len(lines) > limit else []))


def attach_details(diff, old_text, new_text):
    """Add before/after text to a compare() result, so a reader can see what changed."""
    old_sec, new_sec = sections(old_text), sections(new_text)
    for c in diff["changed"]:
        c["diff"] = text_diff(old_sec.get(c["id"], ""), new_sec.get(c["id"], ""))
    for a in diff["added"]:
        a["text"] = excerpt(new_sec.get(a["id"], ""))
    for x in diff["removed"]:
        x["text"] = excerpt(old_sec.get(x["id"], ""))
    if diff["epic"]:
        eid = diff["epic"]["id"]
        diff["epic"]["diff"] = text_diff(old_sec.get(eid, ""), new_sec.get(eid, ""))
    return diff


# --------------------------------------------------------------------------- compare


def compare(old, epic, stories):
    """What changed between the old file and the fresh tracker data."""
    old_items = (old or {}).get("items") or {}
    r = {"added": [], "changed": [], "status": [], "removed": [], "unchanged": [], "epic": None}

    def diff(prev, issue):
        now = hashes(issue)
        parts = [CONTENT_PARTS[c][0] for c in CONTENT_PARTS if prev["h"].get(c) != now[c]]
        meta = prev["h"].get("m") != now["m"]
        return parts, meta

    if old and epic["id"] in old_items:
        parts, meta = diff(old_items[epic["id"]], epic)
        if parts or meta:
            r["epic"] = {"id": epic["id"], "parts": parts, "meta_only": not parts}

    for s in stories:
        prev = old_items.get(s["id"])
        if not prev or prev["kind"] != "story":
            r["added"].append({"id": s["id"], "title": s["title"]})
            continue
        parts, meta = diff(prev, s)
        if parts:
            entry = {"id": s["id"], "title": s["title"], "parts": parts}
            if prev.get("status") != s["status"]:
                entry["from"], entry["to"] = prev.get("status"), s["status"]
            r["changed"].append(entry)
        elif meta:
            entry = {"id": s["id"], "title": s["title"]}
            if prev.get("status") != s["status"]:
                entry["from"], entry["to"] = prev.get("status"), s["status"]
            r["status"].append(entry)
        else:
            r["unchanged"].append(s["id"])

    have = {s["id"] for s in stories}
    for sid, prev in old_items.items():
        if prev["kind"] == "story" and sid not in have:
            r["removed"].append({"id": sid, "title": prev["title"]})
    return r


def has_changes(r):
    return bool(r["added"] or r["changed"] or r["status"] or r["removed"] or r["epic"])


def describe_parts(change):
    text = ", ".join(change["parts"])
    if "to" in change:
        text += "; status %s to %s" % (change["from"] or "none", change["to"] or "none")
    return text


def history_entry(r, first, date):
    if first:
        n = len(r["added"])
        return "- **%s** first sync: %d %s" % (date, n, "story" if n == 1 else "stories")
    lines = ["- **%s** resync" % date]
    if r["epic"]:
        lines.append("  - Epic: %s" % (", ".join(r["epic"]["parts"]) + " changed" if r["epic"]["parts"]
                                       else "status or details changed"))
    for a in r["added"]:
        lines.append("  - Added: %s %s" % (a["id"], a["title"]))
    for c in r["changed"]:
        lines.append("  - Changed: %s %s (%s)" % (c["id"], c["title"], describe_parts(c)))
    for s in r["status"]:
        if "to" in s:
            lines.append("  - Status: %s %s (%s to %s)" % (s["id"], s["title"], s["from"] or "none", s["to"] or "none"))
        else:
            lines.append("  - Details: %s %s (assignee, points, labels or links)" % (s["id"], s["title"]))
    for x in r["removed"]:
        lines.append("  - Removed from epic: %s %s" % (x["id"], x["title"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- render


def _cell(value):
    return str(value if value not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def _join(values):
    return ", ".join(str(v) for v in values or [] if v not in (None, ""))


def _size(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit)).replace(".0 ", " ")
        n /= 1024.0


def _facts(issue, keys):
    labels = {"type": "Type", "status": "Status", "priority": "Priority", "story_points": "Points",
              "assignee": "Assignee", "reporter": "Reporter", "labels": "Labels",
              "components": "Components", "fix_versions": "Fix versions"}
    parts = []
    for key in keys:
        value = issue.get(key)
        value = _join(value) if isinstance(value, list) else value
        if value not in (None, ""):
            parts.append("**%s:** %s" % (labels[key], value))
    if issue.get("url"):
        provider = issue.get("provider")
        label = "Open in %s" % provider.capitalize() if provider and provider != "file" else "Open"
        parts.append("[%s](%s)" % (label, issue["url"]))
    return " · ".join(parts)


def _body(md, levels):
    return mdconv.demote_headings(md.strip(), levels) if md and md.strip() else ""


def render_story(s):
    out = ["## %s %s" % (s["id"], s["title"] or "(no title)"), marker("story", s), "",
           _facts(s, ("type", "status", "priority", "story_points", "assignee", "labels", "components",
                      "fix_versions")), ""]
    out += ["### Description", "", _body(s["description"], 3) or "_No description._", ""]
    if s["acceptance_criteria"]:
        out += ["### Acceptance criteria", "", _body(s["acceptance_criteria"], 3), ""]
    for label, value in (s["extra"] or {}).items():
        if value not in (None, ""):
            out += ["### %s" % label, "", _body(str(value), 3), ""]
    if s["subtasks"]:
        out += ["### Sub-tasks", ""] + ["- %s %s (%s)" % (t.get("id"), t.get("title") or "", t.get("status") or "?")
                                         for t in s["subtasks"]] + [""]
    if s["links"]:
        out += ["### Links", ""] + ["- %s %s %s%s" % (l.get("relation") or "relates to", l.get("id"),
                                                      l.get("title") or "",
                                                      " (%s)" % l["status"] if l.get("status") else "")
                                    for l in s["links"]] + [""]
    if s["attachments"]:
        out += ["### Attachments", ""]
        for a in s["attachments"]:
            size = _size(a.get("size"))
            name = a.get("name") or "file"
            out.append("- [%s](%s)%s" % (name, a["url"], " (%s)" % size if size else "") if a.get("url")
                       else "- %s%s" % (name, " (%s)" % size if size else ""))
        out.append("")
    if s["comments"]:
        out += ["### Comments", ""]
        for c in s["comments"]:
            when = (c.get("created") or "")[:10]
            out.append("**%s**%s" % (c.get("author") or "Someone", ", " + when if when else ""))
            out.append("")
            out.append(mdconv.demote_headings(c.get("body") or "", 3).strip() or "_(empty)_")
            out.append("")
    return "\n".join(out).rstrip()


def render(feature_number, epic, stories, synced, created, history):
    meta = {
        "feature": "%03d" % feature_number,
        "epic": epic["id"],
        "title": epic["title"],
        "provider": epic.get("provider"),
        "source": epic.get("url"),
        "stories": len(stories),
        "created": created,
        "synced": synced,
        "format": FORMAT,
    }
    out = [render_front_matter(meta).rstrip(), "",
           "# %s" % (epic["title"] or epic["id"]), "",
           "> Synced from %s by Relay. Do not edit: the next resync rewrites this file. "
           "Put your notes in `notes.md` next to it." % (
               "[%s](%s)" % (epic["id"], epic["url"]) if epic.get("url") else epic["id"]), "",
           "## %s %s" % (epic["id"], epic["title"] or ""), marker("epic", epic), "",
           _facts(epic, ("type", "status", "priority", "assignee", "reporter", "labels", "components",
                         "fix_versions")), "",
           _body(epic["description"], 2) or "_No description._", ""]
    if epic["acceptance_criteria"]:
        out += ["### Acceptance criteria", "", _body(epic["acceptance_criteria"], 3), ""]

    out += ["## Stories (%d)" % len(stories), ""]
    if stories:
        out += ["| Story | Title | Type | Status | Points | Assignee |", "| --- | --- | --- | --- | --- | --- |"]
        out += ["| %s | %s | %s | %s | %s | %s |" % tuple(_cell(v) for v in (
            s["id"], s["title"], s["type"], s["status"], s["story_points"], s["assignee"])) for s in stories]
    else:
        out.append("_The epic has no stories yet._")
    out.append("")

    for s in stories:
        out += ["---", "", render_story(s), ""]

    out += ["---", "", HISTORY_HEADING, "", history.strip() or "_None yet._", ""]
    return "\n".join(out)


def write_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))
