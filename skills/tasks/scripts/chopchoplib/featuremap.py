"""The feature map: the whole feature in one diagram, with numbered steps.

design/feature-map.json:

  {"version": 1, "title": "Refunds for card payments",
   "actors": [{"id": "customer", "name": "Customer"}],
   "boxes": [{"id": "api", "name": "Refund API", "repo": "payments-api", "status": "new", "kind": "api"},
             {"id": "psp", "name": "Card provider", "status": "external", "kind": "external"}],
   "steps": [{"n": 1, "from": "customer", "to": "page", "kind": "person", "say": "clicks Refund",
              "line": "The customer clicks Refund on the order page.", "stories": ["PAY-121"],
              "failure": {"twice": "The button turns off after the first click.",
                          "caller": "Only the order's owner sees the button."}}],
   "out_of_scope": ["PAY-123"]}

Each step's kind decides which failure questions it must answer. An answer is text,
{"text": "...", "suggested": true} for a suggestion to confirm, or
{"risk": "...", "accepted_by": "Name"} for a risk a person accepts. A missing answer blocks
the approval request.
"""

import re

STATUSES = ["new", "changed", "same", "external"]
BOX_KINDS = ["ui", "service", "api", "job", "table", "topic", "library", "external"]
STEP_KINDS = {
    "person": ["twice", "caller"],
    "call": ["fails", "slow", "twice", "caller"],
    "db": ["fails", "twice"],
    "event": ["fails", "twice"],
    "external": ["fails", "slow", "twice", "caller"],
    "message": ["fails"],
}
KIND_NAMES = {"person": "person to screen", "call": "call between parts", "db": "database write",
              "event": "event", "external": "outside system", "message": "message to a person"}
QUESTIONS = {
    "fails": "Fails: what does the user see, and what state is left behind?",
    "slow": "Slow: what is the timeout, and what happens after it?",
    "twice": "Runs twice: a double click, a retry, an event sent again. Is the result still right?",
    "caller": "Wrong caller: who may do this, and where is it checked?",
}
ANSWER_KEYS = ["fails", "slow", "twice", "caller"]
MAX_BOXES = 12
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
CLASSDEFS = [
    "classDef new fill:#d9f2e4,stroke:#1d6a51,color:#10231a",
    "classDef changed fill:#fbedd3,stroke:#9a5b00,color:#2b1c00",
    "classDef same fill:#ffffff,stroke:#8a948e,color:#1b2620",
    "classDef ext fill:#eef0f3,stroke:#6b7280,stroke-dasharray:4 3,color:#1f2937",
]
LEGEND = "Green is new. Amber is changed. White is the same, shown for context. Dashed is an outside system. Numbers show the order of steps. Each group is one repo."


def answer_state(value):
    """missing, answered, suggested or risk."""
    if value is None or value == "" or value == {}:
        return "missing"
    if isinstance(value, str):
        return "answered" if value.strip() else "missing"
    if isinstance(value, dict):
        if value.get("risk") and value.get("accepted_by"):
            return "risk"
        if value.get("text"):
            return "suggested" if value.get("suggested") else "answered"
    return "missing"


def answer_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("risk"):
            return "Accepted risk: %s (by %s)" % (value["risk"], value.get("accepted_by") or "nobody")
        return value.get("text") or ""
    return ""


# --------------------------------------------------------------------------- checks


def validate(fm, repo_names=None, story_ids=None, known_ids=None):
    """Returns (errors, warnings). story_ids: stories that need a step. known_ids: every valid id."""
    errors, warnings = [], []
    if not isinstance(fm, dict):
        return ["feature-map.json must be a JSON object"], []
    if not fm.get("title"):
        errors.append("title is missing")
    actors, boxes, steps = fm.get("actors") or [], fm.get("boxes") or [], fm.get("steps") or []
    ids = set()
    for kind, items in (("actor", actors), ("box", boxes)):
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict):
                errors.append("%s %d must be an object" % (kind, i))
                continue
            iid = str(item.get("id") or "")
            if not ID_RE.match(iid):
                errors.append("%s %d: id '%s' must start with a letter and use letters, numbers, - or _" % (kind, i, iid))
            if iid in ids:
                errors.append("id %s is used twice" % iid)
            ids.add(iid)
            if not item.get("name"):
                errors.append("%s %s needs a name" % (kind, iid))
            if kind == "box":
                if item.get("status") not in STATUSES:
                    errors.append("box %s: status must be one of %s" % (iid, ", ".join(STATUSES)))
                if item.get("kind") not in BOX_KINDS:
                    errors.append("box %s: kind must be one of %s" % (iid, ", ".join(BOX_KINDS)))
                if item.get("status") == "external":
                    if item.get("repo"):
                        warnings.append("box %s is outside the system, so it has no repo" % iid)
                elif not item.get("repo"):
                    errors.append("box %s needs the repo it lives in" % iid)
                elif repo_names is not None and item["repo"] not in repo_names and item.get("status") != "same":
                    warnings.append("box %s: repo %s is not in chopchop.yaml" % (iid, item["repo"]))
    if len(actors) + len(boxes) > MAX_BOXES:
        errors.append("%d boxes on the map. At most %d: group some parts into one box."
                      % (len(actors) + len(boxes), MAX_BOXES))
    if not steps:
        errors.append("the map has no steps")
    used = set()
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            errors.append("step %d must be an object" % i)
            continue
        if s.get("n") != i:
            errors.append("steps must be numbered 1, 2, 3 in order: step %d has n=%r" % (i, s.get("n")))
        for end in ("from", "to"):
            if s.get(end) not in ids:
                errors.append("step %d: %s '%s' is not an actor or a box" % (i, end, s.get(end)))
            used.add(s.get(end))
        if s.get("kind") not in STEP_KINDS:
            errors.append("step %d: kind must be one of %s" % (i, ", ".join(STEP_KINDS)))
        if not s.get("say"):
            errors.append("step %d needs say: 2 to 6 words for the arrow" % i)
        elif len(str(s["say"]).split()) > 6:
            warnings.append("step %d: say has more than 6 words. Keep the arrow short and put the rest in line." % i)
        if not s.get("line"):
            errors.append("step %d needs line: one plain sentence under the map" % i)
        for sid in s.get("stories") or []:
            if known_ids is not None and sid not in known_ids:
                errors.append("step %d: %s is not a story or AC id in requirement.md" % (i, sid))
        failure = s.get("failure") or {}
        if not isinstance(failure, dict):
            errors.append("step %d: failure must be an object" % i)
        else:
            for key in failure:
                if key not in ANSWER_KEYS:
                    errors.append("step %d: failure.%s is not a question. Use %s" % (i, key, ", ".join(ANSWER_KEYS)))
    for b in boxes:
        if isinstance(b, dict) and b.get("id") not in used:
            warnings.append("box %s is on no step. Give it a step or take it off the map." % b.get("id"))
    if story_ids:
        on_map = {sid.split(".AC")[0] for s in steps if isinstance(s, dict) for sid in s.get("stories") or []}
        out = set(fm.get("out_of_scope") or [])
        for sid in story_ids:
            if sid not in on_map and sid not in out:
                errors.append("story %s has no step on the feature map. Add a step, or list it in out_of_scope." % sid)
    return errors, warnings


def failures(fm):
    """Every question every step must answer, with its state."""
    rows = []
    for s in fm.get("steps") or []:
        if not isinstance(s, dict) or s.get("kind") not in STEP_KINDS:
            continue
        given = s.get("failure") or {}
        for key in ANSWER_KEYS:
            if key not in STEP_KINDS[s["kind"]]:
                continue
            value = given.get(key) if isinstance(given, dict) else None
            rows.append({"n": s.get("n"), "say": s.get("say"), "kind": s["kind"], "question": key,
                         "ask": QUESTIONS[key], "state": answer_state(value), "answer": answer_text(value)})
    return rows


def missing(fm):
    return [r for r in failures(fm) if r["state"] == "missing"]


def repos_touched(fm):
    return sorted({b["repo"] for b in fm.get("boxes") or [] if b.get("status") in ("new", "changed") and b.get("repo")})


# --------------------------------------------------------------------------- drawing


def _mid(iid):
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", str(iid))


def label(text):
    """Plain words only, so Mermaid never breaks on a label."""
    text = re.sub(r"[\[\]{}()<>|\"#;`\\]", " ", str(text or ""))
    text = text.replace("/", " ")
    return re.sub(r"\s+", " ", text).strip() or "x"


def mermaid(fm, mark_missing=True):
    """A flowchart: actors, one group per repo, outside systems, numbered arrows."""
    lines = ["flowchart LR"]
    for a in fm.get("actors") or []:
        lines.append("  %s([%s])" % (_mid(a["id"]), label(a["name"])))
    groups = {}
    for b in fm.get("boxes") or []:
        key = None if b.get("status") == "external" else b.get("repo")
        groups.setdefault(key, []).append(b)
    shapes = {"table": "[(%s)]", "topic": "{{%s}}", "job": "[[%s]]"}
    tags = {"new": " NEW", "changed": " CHANGED", "same": "", "external": ""}
    for repo in sorted(groups, key=lambda r: r or "~"):
        indent = "    " if repo else "  "
        if repo:
            lines.append("  subgraph g_%s[%s]" % (re.sub(r"[^A-Za-z0-9_]", "_", repo), label(repo)))
        for b in groups[repo]:
            text = label(b["name"]) + tags.get(b.get("status"), "")
            lines.append("%s%s%s" % (indent, _mid(b["id"]), shapes.get(b.get("kind"), "[%s]") % text))
        if repo:
            lines.append("  end")
    gaps = {r["n"] for r in missing(fm)} if mark_missing else set()
    for s in fm.get("steps") or []:
        say = "%s %s%s" % (s.get("n"), label(s.get("say")), " ⚠" if s.get("n") in gaps else "")
        arrow = "-.->" if s.get("kind") == "event" else "-->"
        lines.append("  %s %s|%s| %s" % (_mid(s["from"]), arrow, say, _mid(s["to"])))
    by_class = {"new": [], "changed": [], "same": [], "ext": []}
    for b in fm.get("boxes") or []:
        cls = "ext" if b.get("status") == "external" else b.get("status")
        if cls in by_class:
            by_class[cls].append(_mid(b["id"]))
    for cls, members in by_class.items():
        if members:
            lines.append("  class %s %s" % (",".join(members), cls))
    lines += ["  " + c for c in CLASSDEFS]
    return "\n".join(lines)


def caption(fm):
    """One numbered line per step, with its story ids."""
    out = []
    for s in fm.get("steps") or []:
        ids = ", ".join(s.get("stories") or [])
        out.append("%s. %s%s" % (s.get("n"), s.get("line") or s.get("say"), " _(%s)_" % ids if ids else ""))
    return out


def failure_table(fm):
    """Markdown: one row per arrow, one column per question. Not needed cells say so."""
    rows = ["| # | Arrow | Fails | Slow | Runs twice | Wrong caller |", "| --- | --- | --- | --- | --- | --- |"]
    for s in fm.get("steps") or []:
        if s.get("kind") not in STEP_KINDS:
            continue
        given = s.get("failure") or {}
        cells = []
        for key in ANSWER_KEYS:
            if key not in STEP_KINDS[s["kind"]]:
                cells.append("Not needed")
                continue
            value = given.get(key)
            state = answer_state(value)
            text = answer_text(value).replace("|", "\\|").replace("\n", " ")
            cells.append({"missing": "⚠ **No answer yet.**", "suggested": "_Suggested, confirm:_ " + text}.get(state, text))
        rows.append("| %s | %s _(%s)_ | %s |" % (s.get("n"), label(s.get("say")), KIND_NAMES[s["kind"]], " | ".join(cells)))
    return "\n".join(rows)


def sketch(fm):
    """A small diagram for an option in options.md: no failure marks."""
    return mermaid(fm, mark_missing=False)
