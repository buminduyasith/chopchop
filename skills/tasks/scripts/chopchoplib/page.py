"""feature.html: one page per feature that grows with it.

Release 1 fills the design, choices and slides tabs. The page is a fixed template
(templates/feature.html) with the data put in as JSON, like board.html.
"""

import json
from datetime import datetime

from . import designdoc, featuremap, mdhtml, options, systemmap
from .cite import short

DATA_MARK = "/*__CHOPCHOP_FEATURE__*/null"
PAGE_FILE = "feature.html"


def now():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def approvers(fm, smap, lead, repo_dirs=None):
    """Who must say yes: the owners of each repo the feature changes, and the owners named for the lead.

    Owners come from the system map, or straight from the repo's CODEOWNERS when the map has none."""
    out = []
    for repo in featuremap.repos_touched(fm or {}):
        owners = systemmap.owners_of(smap, repo)
        if not owners and repo_dirs and repo in repo_dirs:
            owners = systemmap.owners(repo_dirs[repo])["repo"]
        out.append({"who": ", ".join(owners) if owners else "%s owners (no CODEOWNERS found)" % repo,
                    "why": "%s changes" % repo})
    for item in lead or []:
        owner = item.get("owner")
        if owner and not any(a["who"] == owner for a in out):
            out.append({"who": owner, "why": "a question for the lead"})
    return out


def _choice_lines(opts):
    lines = []
    for c in options.ordered(opts or {}):
        key = c.get("picked") or c.get("recommended")
        o = options.option(c, key) or {}
        rest = [x["title"] for x in c.get("options") or [] if x.get("key") != key]
        lines.append("%s%s" % (o.get("title", key), ". Not picked: %s" % ", ".join(rest) if rest else ""))
    return lines


def slides(body, fm, opts, meta, who, lead, assumed):
    """About 10 slides from the 12 sections, plus a Why not slide per option not picked and the likely questions."""
    sec = {n: t for n, _, t in designdoc.sections(body) if n}
    title = meta.get("title") or (fm or {}).get("title") or "Design"
    steps = (fm or {}).get("steps") or []
    gaps = featuremap.missing(fm or {})
    out = []

    def add(t, bullets, notes="", ask="", diagram=""):
        out.append({"title": t, "bullets": [b for b in bullets if b][:6], "notes": notes, "ask": ask, "diagram": diagram})

    first = [designdoc.size_line(sec.get(1, ""))]
    if who:
        first.append("Who must approve: " + "; ".join(a["who"] for a in who))
    if assumed:
        first.append("%d choice%s picked by chopchop, to confirm today." % (len(assumed), "" if len(assumed) == 1 else "s"))
    add(title, first + designdoc.bullets(sec.get(1, ""), 2),
        designdoc.talk(sec.get(1, "")) or "Start with the ask, so the lead knows what to decide. Then give the size.",
        designdoc.ask_line(sec.get(1, "")))
    add("The whole feature in one picture",
        ["Follow the numbers 1 to %d." % len(steps) if steps else "",
         "Green is new, amber is changed. Each group is one repo and one team."],
        designdoc.talk(sec.get(2, "")) or "Walk the numbers out loud. Stop where a decision or a risk lives.",
        diagram=featuremap.mermaid(fm) if fm else "")
    add("Why", designdoc.bullets(sec.get(3, "")), designdoc.talk(sec.get(3, "")))
    add("Scope", designdoc.bullets(sec.get(4, "")), designdoc.talk(sec.get(4, "")))
    answered = len(featuremap.failures(fm or {})) - len(gaps)
    add("Main flow and errors",
        ["%d failure answers in place%s." % (answered, ", %d missing" % len(gaps) if gaps else "")] +
        designdoc.bullets(sec.get(5, ""), 3),
        designdoc.talk(sec.get(5, "")) or "Show the main path, then the error paths. Every arrow has an answer for fails, slow, runs twice and wrong caller.",
        diagram=designdoc.first_diagram(sec.get(5, "")))
    add("Data and contracts", designdoc.bullets(sec.get(6, ""), 3) + designdoc.bullets(sec.get(7, ""), 3),
        designdoc.talk(sec.get(6, "")) or designdoc.talk(sec.get(7, "")))
    add("Key decisions", _choice_lines(opts),
        designdoc.talk(sec.get(8, "")) or "For each decision, say the option not picked and why, in one line. Ask if anyone sees a reason to switch.")
    for c in options.ordered(opts or {}):
        key = c.get("picked") or c.get("recommended")
        for o in c.get("options") or []:
            if o.get("key") == key:
                continue
            rows = ["%s: %s" % (k, v) for k, v in (o.get("rows") or {}).items()]
            fit = "%s%s" % (options.FITS.get(o.get("fit"), ""), ": " + o["fit_note"] if o.get("fit_note") else "")
            add("Why not %s?" % o["title"].rstrip("?"), [fit] + rows[:3] + ["We picked %s. %s" % (key, c.get("reason") or "")],
                "From options.md, choice %d. Answer in one line. If the lead prefers it, run /chopchop:design --pick %d=%s."
                % (c["_n"], c["_n"], o["key"]))
    add("Impact, rollout and risks", designdoc.bullets(sec.get(9, ""), 3) + designdoc.bullets(sec.get(10, ""), 3),
        designdoc.talk(sec.get(9, "")) or designdoc.talk(sec.get(10, "")))
    add("How we prove it", designdoc.bullets(sec.get(11, "")), designdoc.talk(sec.get(11, "")))
    closing = ["For %s: %s" % (i.get("owner") or "the lead", i["text"]) for i in lead or []][:3]
    closing += ["Assumed: " + a for a in assumed][:2]
    add("Questions and approval", closing + designdoc.bullets(sec.get(12, ""), 2),
        designdoc.talk(sec.get(12, "")) or "Read the questions and assumptions. Ask for a decision now. If changes are needed, write them down and run /chopchop:design with the notes.",
        "Decision: approved, approved with conditions, or changes needed.")
    for q, a in designdoc.questions(body):
        add(q, [a], "A likely lead question, answered before the meeting.")
    return out


def review_message(meta, body, opts, who, lead, assumed):
    sec1 = designdoc.section_text(body, 1)
    lines = ["Design for review: %s%s" % (meta.get("title") or "", " (%s)" % meta["epic"] if meta.get("epic") else "")]
    if designdoc.ask_line(sec1):
        lines.append("The ask: %s" % designdoc.ask_line(sec1))
    if designdoc.size_line(sec1):
        lines.append("Size: %s" % designdoc.size_line(sec1))
    picks = _choice_lines(opts)
    if picks:
        lines.append("Key choices: %s." % "; ".join(p.split(". Not picked")[0] for p in picks))
    for item in lead or []:
        lines.append("For %s: %s" % (item.get("owner") or "the lead", item["text"]))
    if assumed:
        lines.append("Picked by chopchop, please confirm: %d choice%s." % (len(assumed), "" if len(assumed) == 1 else "s"))
    if who:
        lines.append("Who must approve: %s" % "; ".join(a["who"] for a in who))
    lines += ["Page: %s (attached)" % PAGE_FILE,
              "Please reply: approved, approved with conditions, or changes needed."]
    return "\n".join(lines)


def stages(req_counts, meta, tasks_count=None):
    st = meta.get("status") or "draft"
    design_text = {"draft": "Draft", "approved": "Approved", "approved-with-conditions": "Approved, with conditions",
                   "changes-needed": "Changes needed"}[st]
    return [
        {"key": "stories", "label": "Stories", "state": "ok" if req_counts else "todo",
         "text": "%d stories, %d ACs" % req_counts if req_counts else "None yet"},
        {"key": "design", "label": "Design", "state": "ok" if st.startswith("approved") else "now", "text": design_text},
        {"key": "spec", "label": "Spec", "state": "todo", "text": "Not started"},
        {"key": "build", "label": "Build", "state": "todo",
         "text": "%d tasks" % tasks_count if tasks_count else "Not started"},
        {"key": "proof", "label": "Proof", "state": "todo", "text": "Not started"},
        {"key": "done", "label": "Done", "state": "todo", "text": "Set by a person"},
    ]


def cite_data(results):
    from .cite import snippet
    out = {}
    for r in results:
        snip = snippet(r)
        out[r["raw"]] = {"status": r["status"], "note": r["note"], "path": "%s/%s" % (r["repo"], r["path"]),
                         "short": short(r), "lines": snip["lines"], "masked": snip["masked"], "cut": snip["cut"]}
    return out


def build(feature, meta, body, options_md, opts, fm, smap, cite_results, failure_rows, report,
          req_counts, who, lead, assumed, tasks_count=None):
    return {
        "generated": now(),
        "feature": {"name": feature.name, "number": "%03d" % feature.number, "epic": feature.epic,
                    "title": meta.get("title") or feature.meta.get("title") or feature.name},
        "stages": stages(req_counts, meta, tasks_count),
        "design": {"status": meta.get("status") or "draft", "status_text": designdoc.STATUS_TEXT.get(meta.get("status") or "draft"),
                   "approved_by": meta.get("approved_by"), "approved_on": meta.get("approved_on"),
                   "conditions": meta.get("conditions") or [], "version": meta.get("version"),
                   "size": meta.get("size"), "html": mdhtml.convert(body)},
        "options_html": mdhtml.convert(options_md) if options_md else "",
        "map": {"mermaid": featuremap.mermaid(fm) if fm else "", "caption": featuremap.caption(fm) if fm else [],
                "legend": featuremap.LEGEND},
        "failures": failure_rows,
        "slides": slides(body, fm, opts, dict(meta, epic=feature.epic), who, lead, assumed),
        "message": review_message(dict(meta, epic=feature.epic), body, opts, who, lead, assumed),
        "approvers": who,
        "assumptions": assumed,
        "cites": cite_data(cite_results),
        "report": report,
    }


def render(template_text, data):
    if DATA_MARK not in template_text:
        raise ValueError("the feature.html template has no data mark")
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    return template_text.replace(DATA_MARK, blob)
