"""Reviewer notes on a feature's documents: one JSON file per feature, one list per document.

  get(ws, n, path)          GET  /api/notes/<n>?path=   the list of one .md document, and its copy block
  save(ws, n, path, body)   POST /api/notes/<n>?path=   swap that list for the one in the body, then the same

The file is work/.dashboard-notes.json of the feature:

  {"version": 1, "docs": {"design/design.md": [note, ...]}}

A text note keeps where the text is (heading, quote, before, after, match). A diagram note keeps
the diagram, and maybe a box and its label. No line numbers.

This is the only file the dashboard writes. The watcher skips .dashboard names, so a save sends
no live update.
"""

import json
import os
import re
import threading
from pathlib import Path

from .data import ApiError, Refused, TooBig, find_feature, safe_path

NOTES_NAME = ".dashboard-notes.json"
MAX_NOTES, MAX_TEXT, MAX_QUOTE, MAX_SIDE = 200, 2000, 1000, 200
MAX_MATCH = 999
LIMITS = {"id": 40, "text": MAX_TEXT, "created": 40, "heading": 300, "quote": MAX_QUOTE,
          "before": MAX_SIDE, "after": MAX_SIDE, "diagram": 200, "box": 100, "label": 200}
KEYS = set(LIMITS) | {"match"}
TEXT_ONLY = ("quote", "before", "after", "match")
DIAGRAM_ONLY = ("diagram", "box", "label")
ID_RE = re.compile(r"n-[a-z0-9-]{1,36}")   # used with fullmatch, so a newline at the end is refused
BOX_RE = re.compile(r"[A-Za-z0-9_]{1,100}")
LOCK = threading.Lock()   # one lock over read, swap and write, for every feature: saves are rare and small


class BadType(ApiError):
    status = 415


def empty():
    return {"version": 1, "docs": {}}


def notes_file(feature):
    return Path(feature.path) / "work" / NOTES_NAME


def load(path, fix=False):
    """The notes file, or an empty one. A broken file is moved to .bad only on a save (fix=True), so a GET never writes."""
    path = Path(path)
    if not path.is_file():
        return empty()
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(got, dict) and isinstance(got.get("docs"), dict):
            return got
    except (OSError, ValueError):
        pass
    if fix:
        os.replace(str(path), str(path.with_name(NOTES_NAME + ".bad")))   # an older .bad is replaced
        return empty()
    return dict(empty(), broken=True)


# --------------------------------------------------------------------------- checks


def clean(body):
    """The note list from a request, checked field by field. Raises ApiError (400) or TooBig (413)."""
    notes = body.get("notes") if isinstance(body, dict) else None
    if not isinstance(notes, list):
        raise ApiError("Send {\"notes\": [...]}.")
    if len(notes) > MAX_NOTES:
        raise TooBig("Too many notes: %d per document at most." % MAX_NOTES)
    out, ids = [], set()
    for k, note in enumerate(notes, 1):
        note = clean_note(k, note)
        if note["id"] in ids:
            raise ApiError("Note %d: the id %s is used twice." % (k, note["id"]))
        ids.add(note["id"])
        out.append(note)
    return out


def clean_note(k, note):
    """One note, or ApiError naming it: "Note 3: the text is empty."."""
    def bad(why):
        return ApiError("Note %d: %s" % (k, why))

    if not isinstance(note, dict):
        raise bad("send an object.")
    extra = sorted(set(note) - KEYS)
    if extra:
        raise bad("unknown field %s." % extra[0])
    for key, limit in LIMITS.items():
        if key not in note:
            continue
        if not isinstance(note[key], str):
            raise bad("%s must be text." % key)
        if len(note[key]) > limit:
            raise bad("%s is too long: %d characters at most." % (key, limit))
    if not ID_RE.fullmatch(note.get("id") or ""):
        raise bad("the id must look like n-abc-1.")
    if not (note.get("text") or "").strip():
        raise bad("the text is empty.")
    is_text = "quote" in note
    is_diagram = "diagram" in note
    if is_text == is_diagram:
        raise bad("give a quote or a diagram, not both or neither.")
    if is_text:
        if not note["quote"].strip():
            raise bad("the quote is empty.")
        match = note.get("match")
        if not isinstance(match, int) or isinstance(match, bool) or not 0 <= match <= MAX_MATCH:
            raise bad("match must be a whole number from 0 to %d." % MAX_MATCH)
        wrong = [key for key in DIAGRAM_ONLY if key in note]
    else:
        if not note["diagram"].strip():
            raise bad("the diagram name is empty.")
        if "box" in note and not BOX_RE.fullmatch(note["box"]):
            raise bad("the box must be letters, digits or _.")
        wrong = [key for key in TEXT_ONLY if key in note]
    if wrong:
        raise bad("%s does not belong on a %s note." % (wrong[0], "text" if is_text else "diagram"))
    return {key: note[key] for key in note}


# --------------------------------------------------------------------------- the copy block


def one_line(text):
    return " ".join((text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def block(feature, doc, notes):
    """The plain text the reviewer pastes to the agent, exactly as in contract C-2. No notes: an empty string."""
    if not notes:
        return ""
    lines = ["Notes on _chopchop/%s/%s" % (Path(feature.path).name, doc),
             "Each note says where it is, the text I picked, and my note."]
    for k, note in enumerate(notes, 1):
        lines.append("")
        if "diagram" in note:
            where = 'diagram "%s"' % one_line(note["diagram"])
            if note.get("box"):
                where += ', box "%s" (%s)' % (one_line(note.get("label") or note["box"]), note["box"])
        else:
            where = one_line(note.get("heading")) or "the top of the document"
        lines.append("%d. At: %s" % (k, where))
        if "quote" in note:
            lines.append('   Text: "%s"' % one_line(note["quote"]))
        text = note.get("text", "").replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")
        lines.append("   Note: %s" % text[0])
        lines.extend("   " + line for line in text[1:])
    return "\n".join(lines)


# --------------------------------------------------------------------------- the routes


def doc_key(feature, doc):
    """The document's path as one fixed key: design//design.md and design/design.md are the same list."""
    target = safe_path(feature.path, doc)   # 403 or 404
    if target.suffix.lower() != ".md":
        raise Refused("Notes work on .md documents only.")
    return target.relative_to(Path(feature.path).resolve()).as_posix()


def listed(data, doc):
    notes = data["docs"].get(doc)
    return notes if isinstance(notes, list) else []


def get(ws, number, doc):
    feature = find_feature(ws, number)
    doc = doc_key(feature, doc)
    with LOCK:
        data = load(notes_file(feature))
    notes = listed(data, doc)
    out = {"path": doc, "notes": notes, "block": block(feature, doc, notes)}
    if data.get("broken"):
        out["warning"] = "The notes file is broken. The next save keeps a copy as .dashboard-notes.json.bad."
    return out


def save(ws, number, doc, body):
    feature = find_feature(ws, number)
    doc = doc_key(feature, doc)
    notes = clean(body)
    path = notes_file(feature)
    with LOCK:
        data = load(path, fix=True)
        if notes:
            data["docs"][doc] = notes
        else:
            data["docs"].pop(doc, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(NOTES_NAME + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
    return {"path": doc, "notes": notes, "block": block(feature, doc, notes)}
