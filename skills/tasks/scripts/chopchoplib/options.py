"""options.md: the real choices before the design, kept after you pick.

The architect helper writes work/options.json. The script checks it and writes
design/options.md in 7 fixed sections. Picks change with --pick 2=B and are never lost.

  {"understood": {"text": "...", "confidence": "high"},
   "follow": [{"text": "Refund status copies order cancel.", "cite": "payments-api/src/...:42@a1f9c2e"}],
   "leave":  [{"text": "CardClient has no retry wrapper.", "why": "...", "cite": "..."}],
   "choices": [{"kind": "conflict|decision", "question": "Where does refund status live?",
                "why": "one line: what the answer changes",
                "options": [{"key": "A", "title": "A new refunds table", "fit": "follows|bends|breaks",
                             "fit_note": "Follows order_cancellations",
                             "rows": {"Touches": "1 migration, 3 new files", "Undo": "Drop the table"},
                             "sketch": {feature map with boxes and steps, optional}}],
                "recommended": "A", "reason": "...",
                "picked": "A", "picked_by": "you|chopchop|lead", "concern": "..."}],
   "for_lead": [{"text": "...", "owner": "ledger team"}],
   "parked": [{"text": "...", "why": "..."}]}

Choices are numbered in the order they are shown: conflicts first, then decisions.
picked_by "chopchop" means nobody picked it (--auto, or "you decide"): it is an assumption.
"""

import re

from . import featuremap
from .cite import CITE_RE

KINDS = ["conflict", "decision"]
FITS = {"follows": "Follows", "bends": "Bends", "breaks": "Breaks"}
PICKERS = ["you", "chopchop", "lead"]
CONFIDENCE = ["high", "medium", "low"]
MAX_CHOICES = 4


def ordered(data):
    """Choices in display order: conflicts, then decisions. Each gets its number."""
    choices = [c for c in data.get("choices") or [] if isinstance(c, dict)]
    out = [c for c in choices if c.get("kind") == "conflict"] + [c for c in choices if c.get("kind") != "conflict"]
    for i, c in enumerate(out, 1):
        c["_n"] = i
    return out


def option(choice, key):
    return next((o for o in choice.get("options") or [] if o.get("key") == key), None)


def validate(data):
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ["options.json must be a JSON object"], []
    u = data.get("understood") or {}
    if not u.get("text"):
        errors.append("understood.text is missing: say the idea back in 3 to 5 lines")
    if u.get("confidence") and u["confidence"] not in CONFIDENCE:
        errors.append("understood.confidence must be one of %s" % ", ".join(CONFIDENCE))
    for section in ("follow", "leave"):
        for i, item in enumerate(data.get(section) or [], 1):
            if not isinstance(item, dict) or not item.get("text"):
                errors.append("%s[%d] needs text" % (section, i))
                continue
            if not item.get("cite"):
                errors.append("%s[%d] needs a citation of the code it describes: %s" % (section, i, item["text"][:60]))
            elif not CITE_RE.fullmatch(item["cite"]):
                errors.append("%s[%d].cite is not repo/path:line@commit" % (section, i))
            if section == "leave" and not item.get("why"):
                warnings.append("leave[%d] has no why" % i)
    choices = ordered(data)
    if len(choices) > MAX_CHOICES:
        errors.append("%d choices. At most %d: more means the feature is too big. Offer to split it."
                      % (len(choices), MAX_CHOICES))
    for c in choices:
        n = c["_n"]
        if c.get("kind") not in KINDS:
            errors.append("choice %d: kind must be conflict or decision" % n)
        if not c.get("question") or not str(c["question"]).rstrip().endswith("?"):
            errors.append("choice %d: question must be a full question that ends with ?" % n)
        opts = c.get("options") or []
        if not 2 <= len(opts) <= 3:
            errors.append("choice %d needs 2 or 3 options" % n)
        keys = [o.get("key") for o in opts if isinstance(o, dict)]
        if len(set(keys)) != len(keys) or not all(k and re.match(r"^[A-Z]$", str(k)) for k in keys):
            errors.append("choice %d: option keys must be single capital letters, A, B, C" % n)
        for o in opts:
            if not isinstance(o, dict):
                continue
            if not o.get("title"):
                errors.append("choice %d option %s needs a title" % (n, o.get("key")))
            if o.get("fit") not in FITS:
                errors.append("choice %d option %s: fit must be follows, bends or breaks" % (n, o.get("key")))
            elif o["fit"] != "follows" and not o.get("fit_note"):
                errors.append("choice %d option %s %s a pattern: fit_note must say which and why" % (n, o.get("key"), o["fit"]))
            if o.get("sketch"):
                errs, _ = featuremap.validate(dict(o["sketch"], title=o["sketch"].get("title") or o.get("title")))
                for e in errs:
                    if "failure" not in e and "line" not in e and "story" not in e:
                        errors.append("choice %d option %s sketch: %s" % (n, o.get("key"), e))
        if c.get("recommended") not in keys:
            errors.append("choice %d: recommended must be one of its option keys" % n)
        if not c.get("reason"):
            errors.append("choice %d: reason for chopchop's pick is missing" % n)
        if c.get("picked") is not None and c["picked"] not in keys:
            errors.append("choice %d: picked must be one of its option keys" % n)
        if c.get("picked") and c.get("picked_by") not in PICKERS:
            errors.append("choice %d: picked_by must be you, chopchop or lead" % n)
        if c.get("picked") and c.get("picked") != c.get("recommended") and not c.get("concern"):
            warnings.append("choice %d: your pick differs from chopchop's. Add chopchop's concern in one line." % n)
    for i, item in enumerate(data.get("for_lead") or [], 1):
        if not isinstance(item, dict) or not item.get("text"):
            errors.append("for_lead[%d] needs text" % i)
    for i, item in enumerate(data.get("parked") or [], 1):
        if not isinstance(item, dict) or not item.get("text"):
            errors.append("parked[%d] needs text" % i)
    return errors, warnings


def unpicked(data):
    return [c["_n"] for c in ordered(data) if not c.get("picked")]


def assumptions(data):
    """Picks nobody made: --auto, or 'you decide'."""
    out = []
    for c in ordered(data):
        if c.get("picked") and c.get("picked_by") == "chopchop":
            o = option(c, c["picked"]) or {}
            out.append("Choice %d: %s chopchop picked %s, %s." % (c["_n"], c["question"], c["picked"], o.get("title", "")))
    return out


def lead_items(data):
    """For the lead: what the architect listed, plus every picked option that breaks a pattern."""
    items = [dict(i) for i in data.get("for_lead") or [] if isinstance(i, dict)]
    for c in ordered(data):
        o = option(c, c.get("picked")) if c.get("picked") else None
        if o and o.get("fit") == "breaks":
            items.append({"text": "Choice %d picked %s, %s. It breaks a pattern: %s The lead must agree."
                          % (c["_n"], o["key"], o["title"], (o.get("fit_note") or "").rstrip(".") + "."),
                          "owner": "tech lead", "generated": True})
    return items


def pick(data, spec, by="you"):
    """spec: '2=B'. Returns the choice that changed."""
    m = re.match(r"^\s*(\d+)\s*=\s*([A-Za-z])\s*$", spec or "")
    if not m:
        raise ValueError("--pick needs NUMBER=LETTER, such as 2=B")
    n, key = int(m.group(1)), m.group(2).upper()
    choices = ordered(data)
    if not 1 <= n <= len(choices):
        raise ValueError("there is no choice %d. options.md has %d." % (n, len(choices)))
    c = choices[n - 1]
    if not option(c, key):
        raise ValueError("choice %d has no option %s. Options: %s" % (n, key, ", ".join(o["key"] for o in c["options"])))
    if by not in PICKERS:
        raise ValueError("--by must be you, chopchop or lead")
    c["picked"], c["picked_by"] = key, by
    if key == c.get("recommended"):
        c.pop("concern", None)
    return c


def strip(data):
    """The JSON to save: no helper keys."""
    for c in data.get("choices") or []:
        if isinstance(c, dict):
            c.pop("_n", None)
    return data


# --------------------------------------------------------------------------- markdown


def _cite(item):
    return " `%s`" % item["cite"] if item.get("cite") else ""


def _choice_md(c):
    n = c["_n"]
    opts = c.get("options") or []
    lines = ["### Choice %d: %s" % (n, c["question"]), ""]
    if c.get("why"):
        lines += ["Why it matters: %s" % c["why"], ""]
    head = "| |" + "".join(" %s. %s |" % (o["key"], o["title"].replace("|", "/")) for o in opts)
    lines += [head, "| --- |" + " --- |" * len(opts)]
    lines.append("| Fits existing code |" + "".join(
        " %s%s |" % (FITS.get(o.get("fit"), "?"), ": " + o["fit_note"].replace("|", "/") if o.get("fit_note") else "")
        for o in opts))
    names = []
    for o in opts:
        for k in (o.get("rows") or {}):
            if k not in names:
                names.append(k)
    for k in names:
        lines.append("| %s |" % k + "".join(" %s |" % str((o.get("rows") or {}).get(k, "-")).replace("|", "/") for o in opts))
    lines += ["", "chopchop's pick: **%s**. %s" % (c.get("recommended"), c.get("reason") or "")]
    if c.get("picked"):
        who = {"you": "your pick", "lead": "the lead's pick", "chopchop": "picked by chopchop, to confirm"}[c.get("picked_by") or "you"]
        lines.append("Picked: **%s** (%s)." % (c["picked"], who))
        if c["picked"] != c.get("recommended") and c.get("concern"):
            lines.append("chopchop's concern: %s" % c["concern"])
    else:
        lines.append("Picked: not yet.")
    for o in opts:
        if o.get("sketch"):
            sk = dict(o["sketch"])
            sk.setdefault("title", o["title"])
            lines += ["", "Sketch of %s:" % o["key"], "", "```mermaid", featuremap.sketch(sk), "```"]
    return lines + [""]


def render(data, feature_name):
    choices = ordered(data)
    conf = (data.get("understood") or {}).get("confidence")
    lines = ["# Options · %s" % feature_name, "",
             "_Written by chopchop from work/options.json. Change a pick with "
             "`/chopchop:design --pick 2=B`, or say it in chat. Options not picked stay here._", "",
             "## 1. What I understood", ""]
    if conf:
        lines += ["Confidence: %s" % conf, ""]
    lines += [(data.get("understood") or {}).get("text", "").strip(), "", "## 2. Patterns we follow", ""]
    lines += ["- %s%s" % (i["text"], _cite(i)) for i in data.get("follow") or []] or ["None."]
    lines += ["", "## 3. We leave alone", ""]
    lines += ["- %s%s%s" % (i["text"], " Why: %s" % i["why"] if i.get("why") else "", _cite(i))
              for i in data.get("leave") or []] or ["None."]
    lines += ["", "## 4. Conflicts", ""]
    conflicts = [c for c in choices if c.get("kind") == "conflict"]
    for c in conflicts:
        lines += _choice_md(c)
    if not conflicts:
        lines += ["None.", ""]
    lines += ["## 5. Decisions", ""]
    decisions = [c for c in choices if c.get("kind") != "conflict"]
    for c in decisions:
        lines += _choice_md(c)
    if not decisions:
        lines += ["None. The code already answers every choice.", ""]
    lines += ["## 6. For the lead", ""]
    lines += ["- %s%s" % (i["text"], " Owner: %s." % i["owner"] if i.get("owner") else "") for i in lead_items(data)] or ["None."]
    lines += ["", "## 7. Parked", ""]
    lines += ["- %s%s" % (i["text"], " Why: %s" % i["why"] if i.get("why") else "") for i in data.get("parked") or []] or ["None."]
    return "\n".join(lines).rstrip() + "\n"


def decisions_table(data):
    """design.md section 8: one row per choice, with the options not picked."""
    choices = ordered(data)
    if not choices:
        return "None. The code already answers every choice. See options.md."
    rows = ["| # | Choice | Picked | Why | Not picked |", "| --- | --- | --- | --- | --- |"]
    for c in choices:
        key = c.get("picked") or c.get("recommended")
        o = option(c, key) or {}
        others = "; ".join("%s. %s" % (x["key"], x["title"]) for x in c.get("options") or [] if x.get("key") != key)
        why = c.get("reason") or ""
        if c.get("picked") and c["picked"] != c.get("recommended"):
            why = "Picked by %s. chopchop picked %s: %s" % (
                "the lead" if c.get("picked_by") == "lead" else "the developer", c["recommended"],
                c.get("concern") or c.get("reason") or "")
        elif not c.get("picked"):
            why += " Not picked yet."
        elif c.get("picked_by") == "chopchop":
            why += " Assumed by chopchop: please confirm."
        rows.append("| %d | %s | %s. %s | %s | %s |" % (
            c["_n"], c["question"].replace("|", "/"), key, o.get("title", "").replace("|", "/"),
            why.strip().replace("|", "/"), others.replace("|", "/") or "-"))
    return "\n".join(rows)
