"""feature.html: one page per feature that grows with it.

Release 1 fills the design, choices and slides tabs. The page is a fixed template
(templates/feature.html) with the data put in as JSON, like board.html.
"""

import html
import json
import re
from datetime import datetime
from pathlib import Path

from . import designdoc, diagrams, mdhtml, options, systemmap
from .cite import short

DATA_MARK = "/*__CHOPCHOP_FEATURE__*/null"
PAGE_FILE = "feature.html"


def now():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def approvers(arch, smap, lead, repo_dirs=None):
    """Who must say yes: the owners of each repo the feature changes, and the owners named for the lead.

    Owners come from the system map, or straight from the repo's CODEOWNERS when the map has none."""
    out = []
    for repo in diagrams.repos_touched(arch or {}):
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


def _say_choices(opts):
    """What to say for each choice: the pick and why, then what we did not pick and why."""
    out = []
    for c in options.ordered(opts or {}):
        key = c.get("picked") or c.get("recommended")
        o = options.option(c, key) or {}
        line = "%s We picked %s. %s" % (c["question"], o.get("title", key), c.get("reason") or "")
        if c.get("picked") and c["picked"] != c.get("recommended"):
            line = "%s We picked %s. chopchop suggested %s: %s" % (
                c["question"], o.get("title", key), c.get("recommended"), c.get("concern") or "")
        out.append(line.strip())
        for x in c.get("options") or []:
            if x.get("key") != key:
                out.append("Not %s: %s" % (x["title"], x.get("fit_note") or "it costs more for the same result."))
    return out


def slides(body, arch, flow, opts, meta, who, lead, assumed):
    """About 11 slides from the 12 sections, then backup slides with the likely questions.

    Every slide has "say": what the presenter says, as short lines. It starts with the
    section's <!-- talk: --> note, then points taken from the section itself."""
    sec = {n: t for n, _, t in designdoc.sections(body) if n}
    title = meta.get("title") or (arch or {}).get("title") or "Design"
    msgs = (flow or {}).get("messages") or []
    gaps = diagrams.missing(flow or {})
    out = []

    def add(t, bullets, say, ask="", svg="", qa=None, backup=False):
        say = [s for s in say if s]
        out.append({"title": t, "bullets": [b for b in bullets if b][:6], "say": say, "notes": " ".join(say),
                    "ask": ask, "svg": svg, "qa": qa or [], "backup": backup})

    def talk(n):
        return [designdoc.talk(sec.get(n, ""))]

    ask = designdoc.ask_line(sec.get(1, ""))
    size = designdoc.size_line(sec.get(1, ""))
    first = [size]
    if who:
        first.append("Who must approve: " + "; ".join(a["who"] for a in who))
    if assumed:
        first.append("%d choice%s picked by chopchop, to confirm today." % (len(assumed), "" if len(assumed) == 1 else "s"))
    add(title, first + designdoc.bullets(sec.get(1, ""), 2),
        talk(1) + ["Start with the ask, so everyone knows what to decide today: %s" % ask if ask else "",
                   "Size: %s" % size if size else "",
                   "Who must approve: %s." % "; ".join(a["who"] for a in who) if who else ""],
        ask)
    parts = []
    for n in (arch or {}).get("nodes") or []:
        if n.get("status") in ("new", "changed"):
            parts.append("%s is %s%s." % (n["name"], n["status"], " (%s)" % n["repo"] if n.get("repo") else ""))
    add("High-level design", [],
        talk(2) + ["Start from the left: who uses it, then each repo's part, then what it talks to outside."] + parts +
        ["Green is new, amber is changed. Each named box is one repo and one team."],
        svg=diagrams.architecture_svg(arch) if arch else "")
    add("Why", designdoc.bullets(sec.get(3, "")), talk(3) + ["Why now: " + b for b in designdoc.bullets(sec.get(3, ""), 3)])
    add("Scope", designdoc.bullets(sec.get(4, "")), talk(4) + designdoc.bullets(sec.get(4, ""), 4))
    answered = len(diagrams.failures(flow or {})) - len(gaps)
    walk = ["%s. %s%s" % (m.get("n"), m.get("line") or m.get("say"), " (only if %s)" % m["if"] if m.get("if") else "")
            for m in msgs]
    add("Main flow and errors", [] if flow else designdoc.bullets(sec.get(5, ""), 4),
        talk(5) + ["Read the numbers from top to bottom. Amber messages happen only when their condition is true."] + walk +
        ["Every message says what happens when it fails, is slow, runs twice or gets the wrong caller: "
         "%d answers%s." % (answered, ", %d still missing" % len(gaps) if gaps else "")],
        svg=diagrams.flow_svg(flow, arch) if flow else "")
    data_points = designdoc.bullets(sec.get(6, ""), 3) + designdoc.bullets(sec.get(7, ""), 3)
    add("Data and contracts", data_points, talk(6) + talk(7) + data_points)
    add("Key decisions", _choice_lines(opts),
        talk(8) + _say_choices(opts) + ["Ask: does anyone see a reason to switch?"])
    why_not = []
    for c in options.ordered(opts or {}):
        key = c.get("picked") or c.get("recommended")
        picked = (options.option(c, key) or {}).get("title", key)
        for o in c.get("options") or []:
            if o.get("key") != key:
                note = o.get("fit_note") or c.get("reason") or ""
                why_not.append(("Why not %s?" % o["title"].rstrip("?"), "We picked %s. %s" % (picked, note)))
    if why_not:
        add("Options we did not pick", [],
            ["Each option was weighed in options.md. Read the one-line answer for each.",
             "If the lead prefers one, run /chopchop:design --pick N=X after the meeting."],
            qa=why_not[:6])
    risk_points = designdoc.bullets(sec.get(9, ""), 3) + designdoc.bullets(sec.get(10, ""), 3)
    add("Impact, rollout and risks", risk_points, talk(9) + talk(10) + risk_points)
    add("How we prove it", designdoc.bullets(sec.get(11, "")), talk(11) + designdoc.bullets(sec.get(11, ""), 4))
    closing = ["For %s: %s" % (i.get("owner") or "the lead", i["text"]) for i in lead or []][:3]
    closing += ["Assumed: " + a for a in assumed][:2]
    add("Questions and approval", closing + designdoc.bullets(sec.get(12, ""), 2),
        talk(12) + closing + ["Ask for the decision now: approved, approved with conditions, or changes needed.",
                              "Write down any condition. Record it with /chopchop:design --approve \"Name\"."],
        "Decision: approved, approved with conditions, or changes needed.")
    qs = designdoc.questions(body)
    pages = [qs[i:i + 3] for i in range(0, len(qs), 3)]
    for i, group in enumerate(pages, 1):
        add("Backup: likely questions%s" % (" (%d of %d)" % (i, len(pages)) if len(pages) > 1 else ""), [],
            ["Show only if someone asks."] + ["%s %s" % (q, a) for q, a in group], qa=group, backup=True)
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


def _swap(doc_html, mermaid_src, svg):
    src = '<div class="diagram"><pre class="mermaid">%s</pre></div>' % html.escape(mermaid_src, quote=False)
    return doc_html.replace(src, '<div class="diagram drawn">%s</div>' % svg, 1)


def with_drawings(doc_html, arch, flow, opts=None):
    """The page shows chopchop's own drawings. design.md keeps the Mermaid copies for GitHub and editors."""
    if arch:
        doc_html = _swap(doc_html, diagrams.architecture_mermaid(arch), diagrams.architecture_svg(arch))
    if flow:
        doc_html = _swap(doc_html, diagrams.flow_mermaid(flow, arch), diagrams.flow_svg(flow, arch))
    for c in options.ordered(opts or {}):
        for o in c.get("options") or []:
            if o.get("sketch"):
                sk = dict(o["sketch"])
                sk.setdefault("title", o["title"])
                doc_html = _swap(doc_html, diagrams.architecture_mermaid(sk), diagrams.architecture_svg(sk))
    return doc_html


def cite_data(results):
    from .cite import snippet
    out = {}
    for r in results:
        snip = snippet(r)
        out[r["raw"]] = {"status": r["status"], "note": r["note"], "path": "%s/%s" % (r["repo"], r["path"]),
                         "short": short(r), "lines": snip["lines"], "masked": snip["masked"], "cut": snip["cut"]}
    return out


def build(feature, meta, body, options_md, opts, arch, flow, cite_results, failure_rows, report,
          req_counts, who, lead, assumed, tasks_count=None):
    return {
        "generated": now(),
        "feature": {"name": feature.name, "number": "%03d" % feature.number, "epic": feature.epic,
                    "title": meta.get("title") or feature.meta.get("title") or feature.name},
        "stages": stages(req_counts, meta, tasks_count),
        "design": {"status": meta.get("status") or "draft", "status_text": designdoc.STATUS_TEXT.get(meta.get("status") or "draft"),
                   "approved_by": meta.get("approved_by"), "approved_on": meta.get("approved_on"),
                   "conditions": meta.get("conditions") or [], "version": meta.get("version"),
                   "size": meta.get("size"), "html": with_drawings(mdhtml.convert(body), arch, flow)},
        "options_html": with_drawings(mdhtml.convert(options_md), None, None, opts) if options_md else "",
        "failures": failure_rows,
        "slides": slides(body, arch, flow, opts, dict(meta, epic=feature.epic), who, lead, assumed),
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


# --------------------------------------------------------------------------- the spec on the page


def read_data(path):
    """The data a written feature.html carries, or None."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def spec_stages(stages_list, st, meta, has_spec=True):
    """Set the spec, build, proof and done stages from the spec's status."""
    out = [dict(s) for s in stages_list]
    by = {s["key"]: s for s in out}
    status = (meta or {}).get("status") or "draft"
    if "spec" in by and has_spec:
        by["spec"].update(state="ok" if status in ("ready", "building", "done") else "now",
                          text={"draft": "Draft", "ready": "Ready", "building": "Ready", "done": "Ready"}.get(status, "Draft"))
    tasks_n = st["tasks"]["total"]
    if "build" in by and tasks_n:
        done = st["tasks"]["done"]
        by["build"].update(state="ok" if done == tasks_n else "now", text="%d of %d tasks done" % (done, tasks_n))
    if "proof" in by and st["total"]:
        by["proof"].update(state="ok" if st["proved"] == st["total"] else ("now" if st["proved"] else "todo"),
                           text="%d of %d proved" % (st["proved"], st["total"]))
    if "done" in by:
        if status == "done":
            by["done"].update(state="ok", text="Done, set by %s" % meta.get("done_by"))
        elif st["ready_for_done"]:
            by["done"].update(state="now", text="Ready for a person to set")
    return out


def spec_part(spec_html, counts, st, meta):
    return {"html": spec_html, "status": (meta or {}).get("status") or "draft",
            "chips": [
                {"label": "rules", "value": str(counts["rules"])},
                {"label": "packages, %d repos" % counts["repos"], "value": str(counts["packages"])},
                {"label": "files", "value": str(counts["files"])},
                {"label": "unit and integration tests", "value": str(counts["tests"])},
                {"label": "e2e journeys", "value": str(counts["journeys"])},
                {"label": "proved", "value": "%d/%d" % (st["proved"], st["total"]),
                 "state": "ok" if st["total"] and st["proved"] == st["total"] else ("now" if st["proved"] else "")},
            ]}


def carry_over(data, old):
    """Keep what other commands put on the page (the spec, its stages) when design rebuilds it."""
    if not old:
        return data
    if old.get("spec"):
        data["spec"] = old["spec"]
        for c in (old.get("cites") or {}):
            data["cites"].setdefault(c, old["cites"][c])
    keep = {s["key"]: s for s in old.get("stages") or [] if s.get("key") in ("spec", "build", "proof", "done")}
    data["stages"] = [keep.get(s["key"], s) if s["key"] != "build" or keep.get("build", {}).get("state") != "todo" else s
                      for s in data["stages"]]
    return data
