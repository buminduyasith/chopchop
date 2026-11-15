#!/usr/bin/env python3
"""Groom: check stories or an idea against the code, interview the developer, write the brief.

Usage
  chopchop_groom.py --idea "text" [--name short] [--title "..."]   start a feature from an idea
  chopchop_groom.py --prepare [REF] [--json]          everything the run needs, and where it stands
  chopchop_groom.py --mode locked|open [REF]          locked: never change the stories. open: suggest freely
  chopchop_groom.py --findings FILE [REF]             check the research, keep it, write grooming.md
  chopchop_groom.py --questions [dev|ba|all] [REF]    the open questions (ba: ready to paste)
  chopchop_groom.py --answer Q3 --text "..." [--by dev|ba] [--assume] [REF]
  chopchop_groom.py --answers FILE [REF]              many answers at once
  chopchop_groom.py --ask-ba Q3,Q4 [REF]              the developer does not know: hand these to the BA
  chopchop_groom.py --add-question --text "...?" --why "..." [--story ID] [--ask ba] [--options "a|b"] [--blocking]
  chopchop_groom.py --round [REF]                     count one interview round
  chopchop_groom.py --rules FILE [REF]                for an idea: write the agreed rules as stories R1, R2...
  chopchop_groom.py --brief [REF] [--json]            start brief.md, or check it
  chopchop_groom.py --approve "Name" [--note "..."] [REF]   a person approves the brief
  chopchop_groom.py --status [REF] [--json]

REF is a feature (number, epic key or part of the name). With one feature it can be left out.

Files, in _chopchop/<feature>/:
  requirements/requirement.md   the stories as the BA wrote them, or the idea as given (never edited here)
  requirements/grooming.md      what the code says about each story, every question and its answer
  requirements/brief.md         what we build, in simple English. A person approves it.
  work/groom/groom.json         the state behind grooming.md
  work/groom/reports/           one findings file per repo, from the groomer agents

--brief exits 0 when the brief is ready for approval, 1 when something blocks it, 2 on a broken input.

Needs the tasks and stories skills next to it. Standard library only. Python 3.8+.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
TASKS = SKILLS / "tasks"
if not (TASKS / "scripts" / "chopchoplib" / "stage.py").is_file():
    sys.exit("Error: groom needs the tasks skill next to it (%s not found)." % TASKS)
sys.path.insert(0, str(TASKS / "scripts"))

from chopchoplib import events, features, helpers, plain  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace, load_config  # noqa: E402
from chopchoplib.features import FeatureError, parse_front_matter, render_front_matter  # noqa: E402
from chopchoplib.requirements import requirement_items  # noqa: E402

STORIES_SCRIPT = SKILLS / "stories" / "scripts" / "chopchop_stories.py"
TEMPLATE = HERE.parent / "templates" / "brief.md"

MODES = ["locked", "open"]
FITS = ["yes", "change", "conflict", "unknown"]
FIT_TEXT = {"yes": "Fits", "change": "Needs a change", "conflict": "Conflicts", "unknown": "Not clear"}
SIZES = ["S", "M", "L"]
MAX_ROUNDS = 3
MAX_PER_ROUND = 4
BRIEF_HEADINGS = ["Summary", "What we build", "Who it is for and why", "In scope", "Out of scope", "Rules",
                  "Decisions from grooming", "Assumptions", "Open questions"]
BRIEF_MUST_FILL = ["Summary", "What we build", "In scope", "Out of scope", "Rules"]
BRIEF_BLOCKS = ["answers", "assumptions", "open"]
BRIEF_BUDGET = 700


class UsageError(Exception):
    pass


class Inputs(Exception):
    """An input file is broken: exit 2."""


# --------------------------------------------------------------------------- places


class Paths:
    def __init__(self, feature):
        self.feature = feature
        self.requirement = feature.file
        self.grooming = feature.path / "requirements" / "grooming.md"
        self.brief = feature.path / "requirements" / "brief.md"
        self.work = feature.path / "work" / "groom"
        self.state = self.work / "groom.json"
        self.findings = self.work / "findings.json"
        self.reports = self.work / "reports"

    def as_dict(self):
        return {k: str(v) for k, v in vars(self).items() if isinstance(v, Path)}


def now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def emit(args, data, lines):
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n".join(lines))


def default_mode(feature):
    epic = str(feature.epic or "")
    return "open" if not epic or epic.upper().startswith("IDEA") else "locked"


def load_state(paths):
    try:
        state = json.loads(paths.state.read_text(encoding="utf-8"))
    except OSError:
        state = None
    except ValueError as e:
        raise Inputs("%s is not valid JSON: %s" % (paths.state, e))
    if not isinstance(state, dict):
        state = {"version": 1, "mode": default_mode(paths.feature), "rounds": 0, "stories": [], "questions": [],
                 "suggestions": [], "risks": [], "summary": [], "researched": None}
    for key, empty in (("stories", []), ("questions", []), ("suggestions", []), ("risks", []), ("summary", [])):
        if not isinstance(state.get(key), list):
            state[key] = empty
    state.setdefault("mode", default_mode(paths.feature))
    state.setdefault("rounds", 0)
    return state


def save_state(paths, state):
    paths.work.mkdir(parents=True, exist_ok=True)
    tmp = paths.state.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(paths.state)
    write_grooming(paths, state)


def requirement_ids(paths):
    """(items, story ids, epic id). items is [] when requirement.md has no stories yet."""
    try:
        items = requirement_items(paths.requirement) if paths.requirement.is_file() else []
    except (OSError, ValueError):
        items = []
    stories = [r["id"] for r in items if r["kind"] == "story"]
    return items, stories, paths.feature.epic


def repo_dirs(cfg, ws):
    out = {}
    repos = cfg.get("repos") if isinstance(cfg.get("repos"), dict) else {}
    for name, value in repos.items():
        raw = value.get("path") if isinstance(value, dict) else value
        if not raw:
            continue
        p = Path(str(raw)).expanduser()
        out[name] = str(p if p.is_absolute() else (Path(ws).parent / p).resolve())
    return out


# --------------------------------------------------------------------------- questions


def qkey(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def open_questions(state, ask=None):
    return [q for q in state["questions"] if q.get("state") == "open" and (ask is None or q.get("ask") == ask)]


def find_question(state, qid):
    qid = qid.strip().upper()
    for q in state["questions"]:
        if q["id"].upper() == qid:
            return q
    raise UsageError("No question %s. Questions: %s" % (qid, ", ".join(q["id"] for q in state["questions"]) or "none yet"))


def next_qid(state):
    used = [int(m.group(1)) for q in state["questions"] for m in [re.match(r"^Q(\d+)$", q.get("id", ""))] if m]
    return "Q%d" % (max(used or [0]) + 1)


def clean_question(raw, where, known_ids, problems):
    if not isinstance(raw, dict):
        problems.append("%s must be an object" % where)
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        problems.append("%s needs text: the question in one sentence" % where)
        return None
    if not text.endswith("?"):
        problems.append("%s must end with a question mark: %s" % (where, text[:60]))
    why = str(raw.get("why") or "").strip()
    if not why:
        problems.append("%s needs why: what in the code or the story makes this matter" % where)
    ask = str(raw.get("ask") or "dev").lower()
    if ask not in ("dev", "ba"):
        problems.append("%s: ask must be dev or ba (got %s)" % (where, ask))
        ask = "dev"
    options = raw.get("options") or []
    if not isinstance(options, list) or len(options) > 4:
        problems.append("%s: options must be a list of at most 4 short answers" % where)
        options = []
    story = raw.get("story") or None
    if story and known_ids and str(story) not in known_ids:
        problems.append("%s: story '%s' is not in requirement.md" % (where, story))
    return {"text": text, "why": why, "story": str(story) if story else None,
            "options": [str(o).strip() for o in options if str(o).strip()],
            "blocking": bool(raw.get("blocking")), "ask": ask,
            "guess": str(raw.get("guess")).strip() if raw.get("guess") else None}


def add_question(state, q):
    """Add a question, or return the one already there with the same words."""
    key = qkey(q["text"])
    for old in state["questions"]:
        if qkey(old["text"]) == key:
            if old.get("state") == "open":
                for field in ("why", "story", "options", "blocking", "guess"):
                    if q.get(field) not in (None, "", []):
                        old[field] = q[field]
            return old, False
    q = dict(q, id=next_qid(state), state="open", answer=None, by=None, on=None)
    state["questions"].append(q)
    return q, True


# --------------------------------------------------------------------------- grooming.md


def counts(state):
    qs = state["questions"]
    return {"questions": len(qs), "open_dev": len(open_questions(state, "dev")), "open_ba": len(open_questions(state, "ba")),
            "answered": sum(1 for q in qs if q.get("state") == "answered"),
            "assumed": sum(1 for q in qs if q.get("state") == "assumed"),
            "blocking": sum(1 for q in qs if q.get("state") == "open" and q.get("blocking"))}


def groom_status(state, paths):
    c = counts(state)
    if paths.brief.is_file():
        return "briefed"
    if not state.get("researched"):
        return "researching"
    if c["open_dev"]:
        return "questions"
    if c["open_ba"]:
        return "waiting-ba"
    return "ready"


def _cell(value):
    return str(value if value not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def question_lines(q, with_answer=True):
    tags = [t for t in (q.get("story"), "must answer before the brief" if q.get("blocking") else None) if t]
    lines = ["### %s %s" % (q["id"], q["text"]), ""]
    if tags:
        lines.append("_%s_" % " · ".join(tags))
        lines.append("")
    if q.get("why"):
        lines.append("Why it matters: %s" % q["why"])
    if q.get("options"):
        lines.append("")
        lines.append("Possible answers: %s" % " / ".join(q["options"]))
    if q.get("guess") and q.get("state") == "open":
        lines.append("")
        lines.append("Our guess: %s" % q["guess"])
    if with_answer and q.get("answer"):
        who = {"dev": "the developer", "ba": "the BA", "chopchop": "chopchop (an assumption)"}.get(q.get("by"), q.get("by") or "")
        lines.append("")
        lines.append("**Answer:** %s" % q["answer"])
        lines.append("")
        lines.append("_By %s on %s._" % (who, (q.get("on") or "")[:10]))
    lines.append("")
    return lines


def ba_text(state, title):
    """The open BA questions as plain text a person can paste into chat or mail."""
    qs = open_questions(state, "ba")
    if not qs:
        return ""
    lines = ["Questions about: %s" % title, ""]
    for n, q in enumerate(qs, 1):
        head = "%d. %s" % (n, q["text"])
        if q.get("story"):
            head += " (%s)" % q["story"]
        lines.append(head)
        if q.get("why"):
            lines.append("   Why we ask: %s" % q["why"])
        if q.get("options"):
            lines.append("   Possible answers: %s" % " / ".join(q["options"]))
        lines.append("   Ref: %s" % q["id"])
    return "\n".join(lines)


def write_grooming(paths, state):
    feature = paths.feature
    c = counts(state)
    status = groom_status(state, paths)
    title = feature.meta.get("title") or feature.slug.replace("-", " ")
    fit_counts = {f: sum(1 for s in state["stories"] if s.get("fits") == f) for f in FITS}
    meta = {"title": title, "mode": state["mode"], "status": status, "questions": c["questions"],
            "open_dev": c["open_dev"], "open_ba": c["open_ba"], "rounds": state.get("rounds", 0), "updated": now()}

    nxt = {"researching": "The agents read the code.", "questions": "Answer the questions below.",
           "waiting-ba": "Send the BA questions and paste the answers back.",
           "ready": "Write the brief.", "briefed": "The brief is written. See brief.md."}[status]
    fit_line = ", ".join("%d %s" % (fit_counts[f], FIT_TEXT[f].lower()) for f in FITS if fit_counts[f]) or "not checked yet"
    points = [("What", state["summary"][0] if state["summary"] else title),
              ("Mode", "locked. The stories stay as the BA wrote them. Ideas become questions." if state["mode"] == "locked"
               else "open. This is our own idea, so suggestions are welcome."),
              ("Fit with the code", "%d stories: %s." % (len(state["stories"]), fit_line) if state["stories"] else fit_line + "."),
              ("Questions", "%d in all: %d wait for you, %d wait for the BA, %d answered, %d assumed."
               % (c["questions"], c["open_dev"], c["open_ba"], c["answered"], c["assumed"])),
              ("Next", nxt)]
    points += state["summary"][1:4]
    lines = ["# Grooming · %s" % title, "",
             "_Written by chopchop. Do not edit. Answers go in through `/chopchop:groom`._", "",
             plain.summary_block(points)]

    lines += ["## Stories against the code", ""]
    if state["stories"]:
        lines += ["| Story | Fit | Size | What it touches |", "| --- | --- | --- | --- |"]
        for s in state["stories"]:
            lines.append("| %s | %s | %s | %s |" % (_cell(s["id"]), FIT_TEXT.get(s.get("fits"), "-"), _cell(s.get("size")),
                                                  _cell("; ".join(s.get("touches") or []))))
        lines.append("")
        for s in state["stories"]:
            lines += ["### %s" % s["id"], "", s.get("plain") or "", ""]
            for label, key in (("Clashes with what exists", "conflicts"), ("Work nobody wrote down", "hidden")):
                if s.get(key):
                    lines.append("**%s:**" % label)
                    lines += ["- %s" % x for x in s[key]]
                    lines.append("")
            if s.get("evidence"):
                lines.append("Code read: %s" % ", ".join("`%s`" % e for e in s["evidence"]))
                lines.append("")
    else:
        lines += ["_Not checked yet._", ""]

    dev, ba = open_questions(state, "dev"), open_questions(state, "ba")
    lines += ["## Questions for you", ""]
    if dev:
        for q in dev:
            lines += question_lines(q)
    else:
        lines += ["_None open._", ""]
    lines += ["## Questions for the BA", ""]
    if ba:
        lines += ["Send these to the BA. `/chopchop:groom` prints them ready to paste, and takes the answers back.", ""]
        for q in ba:
            lines += question_lines(q)
    else:
        lines += ["_None open._", ""]
    done = [q for q in state["questions"] if q.get("state") in ("answered", "assumed")]
    lines += ["## Answered", ""]
    if done:
        for q in done:
            lines += question_lines(q)
    else:
        lines += ["_Nothing yet._", ""]
    lines += ["## %s" % ("Ideas to raise with the BA" if state["mode"] == "locked" else "Suggestions"), ""]
    if state["suggestions"]:
        for s in state["suggestions"]:
            lines.append("- %s%s" % (s["text"], " Why: %s" % s["why"] if s.get("why") else ""))
        lines.append("")
    else:
        lines += ["_None._", ""]
    lines += ["## Risks", ""]
    lines += (["- %s" % r for r in state["risks"]] + [""]) if state["risks"] else ["_None found._", ""]

    paths.grooming.parent.mkdir(parents=True, exist_ok=True)
    text = render_front_matter(meta) + "\n".join(lines).rstrip("\n") + "\n"
    old = paths.grooming.read_text(encoding="utf-8") if paths.grooming.is_file() else ""
    # Only the time stamp changing is not a change worth a new file.
    if re.sub(r'(?m)^updated: .*$', "", old) != re.sub(r'(?m)^updated: .*$', "", text):
        paths.grooming.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- commands


def get(ws, ref):
    feature = features.resolve(ws, ref or "")
    return feature, Paths(feature)


def cmd_idea(args, ws):
    text = args.idea.strip()
    if len(text.split()) < 2:
        raise UsageError("Say the idea in a few words, for example: --idea \"let customers ask for a refund\"")
    number = features.next_number(ws)
    title = (args.title or re.split(r"(?<=[.!?])\s", text)[0]).strip().rstrip(".")
    if len(title) > 70:
        title = " ".join(title.split()[:10])
    title = title[:1].upper() + title[1:]
    data = {"epic": {"id": "IDEA-%d" % number, "title": title, "description": text, "provider": "idea", "type": "Idea"},
            "stories": []}
    ws.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
        tmp = fh.name
    cmd = [sys.executable, str(STORIES_SCRIPT), "--ingest", tmp, "--json", "--workspace", str(ws)]
    if args.name:
        cmd += ["--name", args.name]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
    if out.returncode != 0:
        raise UsageError("Could not create the feature: %s" % (out.stderr.strip() or out.stdout.strip()))
    report = json.loads(out.stdout)
    feature, paths = get(ws, report["number"])
    state = load_state(paths)
    state["mode"] = "open"
    state["idea"] = {"text": text, "title": title}
    save_state(paths, state)
    events.log(feature, "groom", "Started from an idea: %s" % title)
    emit(args, {"feature": feature.name, "number": feature.number, "epic": feature.epic, "file": str(paths.requirement),
                "mode": "open"},
         ["Feature:  %s  (new, from an idea)" % feature.name, "File:     %s" % paths.requirement,
          "Mode:     open. Suggestions are welcome.", "Next:     --prepare %d" % feature.number])
    return 0


def cmd_rules(args, ws):
    """An idea has no stories. Once the rules are agreed, write them as stories R1, R2... so later steps have ids."""
    feature, paths = get(ws, args.ref)
    epic = str(feature.epic or "")
    if not epic.upper().startswith("IDEA"):
        raise UsageError("%s comes from the tracker (%s). Its stories are the BA's: --rules is only for ideas."
                         % (feature.name, epic or "no epic"))
    try:
        rows = json.loads(Path(args.rules).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Inputs("Cannot read %s: %s" % (args.rules, e))
    if isinstance(rows, dict):
        rows = rows.get("rules")
    if not isinstance(rows, list) or not rows:
        raise Inputs('--rules needs a JSON list like [{"id": "R1", "title": "...", "acceptance_criteria": "- ...\\n- ..."}]')
    stories, seen = [], set()
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict) or not str(r.get("title") or "").strip():
            raise Inputs("rules[%d] needs a title: the rule in one short sentence" % i)
        rid = str(r.get("id") or "R%d" % i).strip().upper()
        if not re.match(r"^R\d+$", rid) or rid in seen:
            raise Inputs("rules[%d]: the id must be R1, R2 and so on, each used once (got %s)" % (i, rid))
        seen.add(rid)
        ac = r.get("acceptance_criteria")
        if isinstance(ac, list):
            ac = "\n".join("- %s" % a for a in ac)
        stories.append({"id": rid, "title": str(r["title"]).strip(), "type": "Rule", "provider": "idea", "parent": epic,
                        "description": str(r.get("description") or "").strip(), "acceptance_criteria": ac or None})
    state = load_state(paths)
    idea = state.get("idea") or {}
    data = {"epic": {"id": epic, "title": idea.get("title") or feature.meta.get("title") or feature.slug,
                     "description": idea.get("text") or "", "provider": "idea", "type": "Idea"}, "stories": stories}
    if not data["epic"]["description"]:
        raise UsageError("The idea text is not saved for %s, so the rules cannot be added safely." % feature.name)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
        tmp = fh.name
    try:
        out = subprocess.run([sys.executable, str(STORIES_SCRIPT), "--ingest", tmp, "--json", "--workspace", str(ws)],
                             capture_output=True, text=True, timeout=60)
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
    if out.returncode != 0:
        raise UsageError("Could not write the rules: %s" % (out.stderr.strip() or out.stdout.strip()))
    events.log(feature, "groom", "%d rule(s) written as stories: %s" % (len(stories), ", ".join(s["id"] for s in stories)))
    emit(args, {"feature": feature.name, "rules": [s["id"] for s in stories], "file": str(paths.requirement)},
         ["Rules:    %s written to %s" % (", ".join(s["id"] for s in stories), paths.requirement),
          "Next:     use these ids in the brief (In scope, Rules), then --brief"])
    return 0


def prepare(ws, cfg, ref):
    feature, paths = get(ws, ref)
    state = load_state(paths)
    items, stories, epic = requirement_ids(paths)
    s = helpers.settings(cfg)
    repos = repo_dirs(cfg, ws)
    system_md = Path(ws) / "system" / "system-map.md"
    c = counts(state)
    brief_meta = features.read_front_matter(paths.brief) if paths.brief.is_file() else None
    return {
        "feature": feature.name, "number": feature.number, "epic": epic,
        "title": feature.meta.get("title") or feature.slug.replace("-", " "),
        "mode": state["mode"], "status": groom_status(state, paths), "rounds": state.get("rounds", 0),
        "rounds_left": max(0, MAX_ROUNDS - int(state.get("rounds", 0))), "per_round": MAX_PER_ROUND,
        "requirement": {"exists": paths.requirement.is_file(), "stories": stories, "items": items},
        "repos": repos, "system_map": {"exists": system_md.is_file(), "md": str(system_md)},
        "helpers": {"ask": not s["set"], "max": s["max"], "calls": {"groomer": helpers.for_role(s, "explorer")},
                    "line": helpers.describe(s)},
        "researched": state.get("researched"), "counts": c,
        "brief": {"exists": paths.brief.is_file(), "status": (brief_meta or {}).get("status")},
        "files": paths.as_dict(), "template": str(TEMPLATE),
    }


def cmd_prepare(args, ws):
    cfg = load_config(ws)
    d = prepare(ws, cfg, args.ref)
    c = d["counts"]
    lines = ["Feature:  %s" % d["feature"],
             "Mode:     %s" % ("locked: never change the stories, every idea is a question" if d["mode"] == "locked"
                               else "open: our own idea, suggestions are welcome"),
             "Stories:  %s" % (", ".join(d["requirement"]["stories"]) or "none yet (an idea)"),
             "Repos:    %s" % (", ".join(d["repos"]) or "none in chopchop.yaml"),
             "Map:      %s" % (d["system_map"]["md"] if d["system_map"]["exists"] else "no system map yet: run the learn skill first"),
             "Research: %s" % ("done %s" % d["researched"][:16].replace("T", " ") if d["researched"] else "not done"),
             "Questions: %d open for the developer, %d open for the BA, %d answered, %d assumed"
             % (c["open_dev"], c["open_ba"], c["answered"], c["assumed"]),
             "Rounds:   %d of %d used" % (d["rounds"], MAX_ROUNDS),
             "Brief:    %s" % (d["brief"]["status"] or "written" if d["brief"]["exists"] else "not written"),
             "Reports:  %s" % d["files"]["reports"],
             "Findings: %s" % d["files"]["findings"]]
    if not d["researched"]:
        nxt = "start one chopchop:groomer per repo, merge their reports into the findings file, then --findings <file>"
    elif c["open_dev"] and d["rounds_left"]:
        nxt = "ask the developer the open questions (--questions dev), then save the answers"
    elif c["open_dev"]:
        nxt = "no rounds left: hand the open questions to the BA (--ask-ba) or assume them (--answer Qn --assume)"
    elif not d["brief"]["exists"]:
        nxt = "--brief to start brief.md" + (" (%d BA question(s) stay open)" % c["open_ba"] if c["open_ba"] else "")
    elif d["brief"]["status"] != "approved":
        nxt = "--brief to check it, then a person approves: --approve \"Name\""
    else:
        nxt = "nothing. The brief is approved. The design comes next."
    lines.append("Next:     %s" % nxt)
    emit(args, dict(d, next=nxt), lines)
    return 0


def cmd_mode(args, ws):
    feature, paths = get(ws, args.ref)
    if args.mode not in MODES:
        raise UsageError("--mode must be locked or open")
    state = load_state(paths)
    state["mode"] = args.mode
    save_state(paths, state)
    emit(args, {"mode": args.mode}, ["Mode:     %s" % args.mode])
    return 0


def validate_findings(data, known, state):
    problems, warnings = [], []
    if not isinstance(data, dict):
        return ["the findings file must be a JSON object"], warnings, [], []
    stories_out = []
    seen = set()
    for i, s in enumerate(data.get("stories") or [], 1):
        where = "stories[%d]" % i
        if not isinstance(s, dict) or not s.get("id"):
            problems.append("%s needs an id" % where)
            continue
        sid = str(s["id"])
        if known and sid not in known:
            problems.append("%s: '%s' is not in requirement.md (known: %s)" % (where, sid, ", ".join(known)))
        if sid in seen:
            problems.append("%s: '%s' is listed twice. Merge the repos' findings into one entry." % (where, sid))
        seen.add(sid)
        fits = str(s.get("fits") or "unknown").lower()
        if fits not in FITS:
            problems.append("%s: fits must be one of %s" % (where, ", ".join(FITS)))
        if not str(s.get("plain") or "").strip():
            problems.append("%s needs plain: what the code says about this story, in one to three short sentences" % where)
        size = s.get("size")
        if size not in (None, "") and str(size).upper() not in SIZES:
            problems.append("%s: size must be S, M or L" % where)
        if fits in ("yes", "change", "conflict") and not s.get("evidence"):
            warnings.append("%s has no evidence. A claim about the code needs a citation." % sid)
        stories_out.append({"id": sid, "fits": fits, "plain": str(s.get("plain") or "").strip(),
                            "touches": [str(x) for x in s.get("touches") or []],
                            "evidence": [str(x) for x in s.get("evidence") or []],
                            "conflicts": [str(x) for x in s.get("conflicts") or []],
                            "hidden": [str(x) for x in s.get("hidden") or []],
                            "size": str(size).upper() if size else None})
    questions = []
    for i, q in enumerate(data.get("questions") or [], 1):
        clean = clean_question(q, "questions[%d]" % i, known, problems)
        if clean:
            questions.append(clean)
            for w in plain.lint_text(clean["text"])[1]:
                warnings.append("question %d: %s" % (i, w))
    for key in ("suggestions", "risks", "summary"):
        if data.get(key) is not None and not isinstance(data.get(key), list):
            problems.append("%s must be a list" % key)
    return problems, warnings, stories_out, questions


def cmd_findings(args, ws):
    feature, paths = get(ws, args.ref)
    try:
        data = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Inputs("Cannot read %s: %s" % (args.findings, e))
    state = load_state(paths)
    items, stories, epic = requirement_ids(paths)
    known = stories + ([epic] if epic else [])
    problems, warnings, stories_out, questions = validate_findings(data, known, state)
    if problems:
        raise Inputs("The findings need fixes:\n  - " + "\n  - ".join(problems))
    missing = [s for s in stories if s not in {x["id"] for x in stories_out}]
    if missing:
        warnings.append("no finding for %s. Every story should be checked against the code." % ", ".join(missing))
    state["stories"] = stories_out
    added = 0
    for q in questions:
        _, new = add_question(state, q)
        added += 1 if new else 0
    sug = []
    for s in data.get("suggestions") or []:
        if isinstance(s, dict) and s.get("text"):
            sug.append({"text": str(s["text"]).strip(), "why": str(s.get("why") or "").strip() or None,
                        "story": s.get("story") or None})
        elif isinstance(s, str) and s.strip():
            sug.append({"text": s.strip(), "why": None, "story": None})
    state["suggestions"] = sug
    state["risks"] = [str(r).strip() for r in data.get("risks") or [] if str(r).strip()]
    state["summary"] = [str(r).strip() for r in data.get("summary") or [] if str(r).strip()]
    state["researched"] = now()
    save_state(paths, state)
    c = counts(state)
    fit = {f: sum(1 for s in stories_out if s["fits"] == f) for f in FITS}
    events.log(feature, "groom", "Checked %d stories against the code: %s. %d new question(s)." % (
        len(stories_out), ", ".join("%d %s" % (fit[f], FIT_TEXT[f].lower()) for f in FITS if fit[f]) or "nothing to check", added))
    lines = ["Feature:  %s" % feature.name,
             "Stories:  %d checked: %s" % (len(stories_out), ", ".join("%d %s" % (fit[f], FIT_TEXT[f].lower())
                                                                       for f in FITS if fit[f]) or "none"),
             "Questions: %d new · %d open for the developer · %d open for the BA" % (added, c["open_dev"], c["open_ba"]),
             "Wrote:    %s" % paths.grooming]
    lines += ["Warning:  %s" % w for w in warnings]
    lines.append("Next:     %s" % ("--questions dev, and ask them" if c["open_dev"] else
                                   "--questions ba, and give them to the user" if c["open_ba"] else "--brief"))
    emit(args, {"feature": feature.name, "stories": len(stories_out), "fit": fit, "new_questions": added,
                "counts": c, "warnings": warnings, "grooming": str(paths.grooming)}, lines)
    return 0


def cmd_questions(args, ws):
    feature, paths = get(ws, args.ref)
    state = load_state(paths)
    who = (args.questions or "all").lower()
    if who not in ("dev", "ba", "all"):
        raise UsageError("--questions takes dev, ba or all")
    title = feature.meta.get("title") or feature.slug
    qs = open_questions(state, None if who == "all" else who)
    qs = sorted(qs, key=lambda q: (not q.get("blocking"), int(re.sub(r"\D", "", q["id"]) or 0)))
    left = max(0, MAX_ROUNDS - int(state.get("rounds", 0)))
    data = {"feature": feature.name, "mode": state["mode"], "who": who, "questions": qs,
            "this_round": qs[:MAX_PER_ROUND] if who == "dev" else qs, "rounds_left": left,
            "paste": ba_text(state, title) if who in ("ba", "all") else ""}
    if who == "ba":
        lines = [data["paste"] or "No open questions for the BA."]
        if data["paste"]:
            lines += ["", "Next:     give this text to the user to send. Answers come back with --answer Qn --text \"...\" --by ba"]
    else:
        lines = ["Open:     %d question(s)%s" % (len(qs), "" if who == "all" else " for the %s" % ("developer" if who == "dev" else "BA"))]
        for q in qs:
            lines.append("  %s [%s%s] %s" % (q["id"], q["ask"], ", must answer" if q.get("blocking") else "", q["text"]))
            if q.get("options"):
                lines.append("       answers: %s" % " / ".join(q["options"]))
            if q.get("guess"):
                lines.append("       guess: %s" % q["guess"])
        if who == "dev" and qs:
            lines.append("Rounds:   %d left. Ask at most %d now: %s" % (left, MAX_PER_ROUND, ", ".join(q["id"] for q in qs[:MAX_PER_ROUND])))
    emit(args, data, lines)
    return 0


def set_answer(state, qid, text, by, assume):
    q = find_question(state, qid)
    text = (text or "").strip()
    if not text:
        raise UsageError("%s needs --text: the answer in the person's own words" % q["id"])
    q["answer"] = text
    q["by"] = "chopchop" if assume else by
    q["on"] = now()
    q["state"] = "assumed" if assume else "answered"
    return q


def cmd_answer(args, ws):
    feature, paths = get(ws, args.ref)
    state = load_state(paths)
    by = (args.by or "dev").lower()
    if by not in ("dev", "ba", "chopchop"):
        raise UsageError("--by must be dev or ba")
    q = set_answer(state, args.answer, args.text, by, args.assume)
    save_state(paths, state)
    touch_brief(paths)
    events.log(feature, "answer", "%s %s: %s" % (q["id"], "assumed" if args.assume else "answered by the %s" %
                                                 ("BA" if by == "ba" else "developer"), q["answer"][:120]))
    c = counts(state)
    emit(args, {"question": q, "counts": c},
         ["Saved:    %s %s" % (q["id"], q["state"]),
          "Open:     %d for the developer, %d for the BA" % (c["open_dev"], c["open_ba"]),
          "Next:     %s" % ("--questions dev" if c["open_dev"] else "--questions ba" if c["open_ba"] else "--brief")])
    return 0


def cmd_answers(args, ws):
    feature, paths = get(ws, args.ref)
    try:
        rows = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Inputs("Cannot read %s: %s" % (args.answers, e))
    if isinstance(rows, dict):
        rows = rows.get("answers")
    if not isinstance(rows, list):
        raise Inputs('--answers needs a JSON list like [{"id": "Q1", "text": "...", "by": "dev"}, {"id": "Q2", "ask": "ba"}]')
    state = load_state(paths)
    done = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict) or not r.get("id"):
            raise Inputs("answers[%d] needs an id" % i)
        if str(r.get("ask") or "").lower() == "ba":
            q = find_question(state, str(r["id"]))
            q["ask"] = "ba"
            done.append("%s to the BA" % q["id"])
            continue
        by = str(r.get("by") or "dev").lower()
        q = set_answer(state, str(r["id"]), r.get("text"), by if by in ("dev", "ba") else "dev", bool(r.get("assume")))
        done.append("%s %s" % (q["id"], q["state"]))
        events.log(feature, "answer", "%s %s: %s" % (q["id"], q["state"], q["answer"][:120]))
    save_state(paths, state)
    touch_brief(paths)
    c = counts(state)
    emit(args, {"saved": done, "counts": c},
         ["Saved:    %s" % ", ".join(done),
          "Open:     %d for the developer, %d for the BA" % (c["open_dev"], c["open_ba"]),
          "Next:     %s" % ("--questions dev" if c["open_dev"] else "--questions ba" if c["open_ba"] else "--brief")])
    return 0


def cmd_ask_ba(args, ws):
    feature, paths = get(ws, args.ref)
    state = load_state(paths)
    moved = []
    for qid in [p for p in re.split(r"[,\s]+", args.ask_ba) if p]:
        q = find_question(state, qid)
        if q.get("state") != "open":
            raise UsageError("%s is already %s." % (q["id"], q.get("state")))
        q["ask"] = "ba"
        moved.append(q["id"])
    save_state(paths, state)
    events.log(feature, "question", "%s handed to the BA" % ", ".join(moved))
    c = counts(state)
    emit(args, {"moved": moved, "counts": c},
         ["Moved:    %s to the BA list" % ", ".join(moved),
          "Next:     %s" % ("--questions dev" if c["open_dev"] else "--questions ba, and give them to the user")])
    return 0


def cmd_add_question(args, ws):
    feature, paths = get(ws, args.ref)
    state = load_state(paths)
    _, stories, epic = requirement_ids(paths)
    problems = []
    raw = {"text": args.text, "why": args.why, "story": args.story, "ask": args.ask or "dev",
           "options": [o.strip() for o in (args.options or "").split("|") if o.strip()], "blocking": args.blocking}
    q = clean_question(raw, "the question", stories + ([epic] if epic else []), problems)
    if problems:
        raise UsageError("; ".join(problems))
    q, new = add_question(state, q)
    save_state(paths, state)
    if new:
        events.log(feature, "question", "%s added: %s" % (q["id"], q["text"]))
    emit(args, {"question": q, "new": new}, ["%s:    %s %s" % ("Added" if new else "Known", q["id"], q["text"])])
    return 0


def cmd_round(args, ws):
    feature, paths = get(ws, args.ref)
    state = load_state(paths)
    state["rounds"] = int(state.get("rounds", 0)) + 1
    save_state(paths, state)
    left = max(0, MAX_ROUNDS - state["rounds"])
    emit(args, {"rounds": state["rounds"], "left": left}, ["Rounds:   %d used, %d left" % (state["rounds"], left)])
    return 0


# --------------------------------------------------------------------------- brief.md


def block_re(name):
    return re.compile(r"(<!-- chopchop:%s -->)(.*?)(<!-- /chopchop:%s -->)" % (name, name), re.S)


def brief_sections(body):
    heads = list(re.finditer(r"(?m)^## (.+?)\s*$", body))
    out = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        out[m.group(1).strip()] = body[m.end():end].strip("\n")
    return out, [m.group(1).strip() for m in heads]


def brief_blocks(state):
    done = [q for q in state["questions"] if q.get("state") == "answered"]
    assumed = [q for q in state["questions"] if q.get("state") == "assumed"]
    still = open_questions(state)
    if done:
        answers = ["| Question | Answer | Who |", "| --- | --- | --- |"] + [
            "| %s %s | %s | %s |" % (q["id"], _cell(q["text"]), _cell(q["answer"]),
                                    {"dev": "developer", "ba": "BA"}.get(q.get("by"), _cell(q.get("by")))) for q in done]
    else:
        answers = ["None."]
    assumptions = ["- %s %s We assume: %s" % (q["id"], q["text"], q["answer"]) for q in assumed] or ["None."]
    open_ = ["- %s %s (waits for %s)" % (q["id"], q["text"], "the BA" if q.get("ask") == "ba" else "the developer")
             for q in still] or ["None."]
    return {"answers": "\n".join(answers), "assumptions": "\n".join(assumptions), "open": "\n".join(open_)}


def fill_brief(body, state):
    for name, content in brief_blocks(state).items():
        pat = block_re(name)
        if pat.search(body):
            body = pat.sub(lambda m, c=content: m.group(1) + "\n" + c + "\n" + m.group(3), body, count=1)
    return body


def drop_guides(body):
    """Remove the template's writing hints once a section has words of its own. The chopchop marks stay."""
    secs, _ = brief_sections(body)

    def keep(m):
        if re.match(r"<!-- /?chopchop:", m.group(0)):
            return m.group(0)
        start = body.rfind("\n## ", 0, m.start())
        head = body[start + 4:body.find("\n", start + 1)].strip() if start >= 0 else None
        text = re.sub(r"(?s)<!--.*?-->", "", secs.get(head, "") if head else body[:m.start()]).strip()
        filled = bool(text) if head else bool(secs)  # the guide above the first heading goes once any section exists
        return "" if filled else m.group(0)
    out = re.sub(r"(?s)<!--.*?-->[ \t]*\n?", keep, body)
    return re.sub(r"\n{3,}", "\n\n", out)


def body_hash(body):
    return hashlib.sha1(re.sub(r"\s+", " ", body).strip().encode("utf-8")).hexdigest()[:12]


def touch_brief(paths):
    """Refill the generated parts of brief.md after an answer changed. Marks an approved brief as changed."""
    if not paths.brief.is_file():
        return
    meta, body = parse_front_matter(paths.brief.read_text(encoding="utf-8"))
    new = fill_brief(body, load_state(paths))
    if new == body:
        return
    if str(meta.get("status") or "") == "approved" and meta.get("hash") and meta["hash"] != body_hash(new):
        meta["changed_since_approval"] = True
    paths.brief.write_text(render_front_matter(meta) + new, encoding="utf-8")


def check_brief(paths, state):
    """Returns (meta, body, errors, warnings). Fills the generated blocks first."""
    meta, body = parse_front_matter(paths.brief.read_text(encoding="utf-8"))
    body = fill_brief(body, state)
    errors, warnings = plain.lint(body, need_summary=True, name="brief.md")
    secs, order = brief_sections(body)
    missing = [h for h in BRIEF_HEADINGS if h not in secs]
    if missing:
        errors.append("brief.md is missing the heading(s): %s" % ", ".join("## " + h for h in missing))
    for h in BRIEF_MUST_FILL:
        text = re.sub(r"(?s)<!--.*?-->", "", secs.get(h, "")).strip()
        if h in secs and not text:
            errors.append('"## %s" is empty. Write it, or "None." when there is nothing to say.' % h)
    for name in BRIEF_BLOCKS:
        if not block_re(name).search(body):
            errors.append("the generated block chopchop:%s is missing. Put back:\n<!-- chopchop:%s -->\n<!-- /chopchop:%s -->"
                          % (name, name, name))
    _, stories, _ = requirement_ids(paths)
    scope = secs.get("In scope", "") + "\n" + secs.get("Out of scope", "")
    for sid in stories:
        if not re.search(r"(?<![\w-])%s(?!\d)" % re.escape(sid), scope):
            msg = "story %s is not under In scope or Out of scope" % sid
            if state["mode"] == "locked":
                errors.append(msg + ". In locked mode every story from the BA must be placed.")
            else:
                warnings.append(msg)
    blocking = [q["id"] for q in open_questions(state) if q.get("blocking")]
    if blocking:
        errors.append("%s must be answered before the brief: answer, hand to the BA and wait, or assume with "
                      "--answer Qn --assume --text \"...\"" % ", ".join(blocking))
    n = plain.words(body)
    if n > BRIEF_BUDGET:
        warnings.append("%d words. Keep the brief under %d: detail belongs in the design and the spec." % (n, BRIEF_BUDGET))
    return meta, body, errors, warnings


def cmd_brief(args, ws):
    feature, paths = get(ws, args.ref)
    state = load_state(paths)
    title = feature.meta.get("title") or feature.slug.replace("-", " ")
    if not paths.brief.is_file():
        meta = {"title": title, "status": "draft", "mode": state["mode"], "version": 1, "created": date.today().isoformat(),
                "approved_by": None, "approved_on": None, "changed_since_approval": False, "hash": None}
        _, body = parse_front_matter(TEMPLATE.read_text(encoding="utf-8"))
        body = fill_brief(body.replace("{{title}}", title), state)
        paths.brief.parent.mkdir(parents=True, exist_ok=True)
        paths.brief.write_text(render_front_matter(meta) + body, encoding="utf-8")
        write_grooming(paths, state)
        events.log(feature, "brief", "Brief started")
        emit(args, {"brief": str(paths.brief), "created": True, "ready": False},
             ["Brief:    %s (started from the template)" % paths.brief,
              "Next:     write each section in simple English, then --brief again to check it"])
        return 1
    meta, body, errors, warnings = check_brief(paths, state)
    body = drop_guides(body)
    if str(meta.get("status") or "") == "approved" and meta.get("hash") and meta["hash"] != body_hash(body):
        meta["changed_since_approval"] = True
    meta["mode"] = state["mode"]
    meta["updated"] = date.today().isoformat()
    paths.brief.write_text(render_front_matter(meta) + body, encoding="utf-8")
    ready = not errors
    report = {"feature": feature.name, "brief": str(paths.brief), "created": False, "ready": ready,
              "status": meta.get("status"), "errors": errors, "warnings": warnings,
              "changed_since_approval": bool(meta.get("changed_since_approval"))}
    lines = ["Brief:    %s" % paths.brief]
    lines += ["Error:    %s" % e for e in errors]
    lines += ["Warning:  %s" % w for w in warnings]
    lines.append("Result:   %s" % ("ready for approval" if ready else "%d thing(s) block the approval" % len(errors)))
    if ready and str(meta.get("status")) == "approved" and not meta.get("changed_since_approval"):
        lines.append("Next:     nothing. It is approved. The design comes next.")
    elif ready:
        lines.append("Next:     a person reads it and approves: --approve \"Name\"")
    else:
        lines.append("Next:     fix the errors, then --brief again")
    emit(args, report, lines)
    return 0 if ready else 1


def cmd_approve(args, ws):
    feature, paths = get(ws, args.ref)
    name = (args.approve or "").strip()
    if not name:
        raise UsageError("Who approves? --approve \"Name\"")
    if not paths.brief.is_file():
        raise UsageError("No brief.md yet. Run --brief first.")
    state = load_state(paths)
    meta, body, errors, _ = check_brief(paths, state)
    if errors:
        raise UsageError("The brief is not ready for approval:\n  - " + "\n  - ".join(errors))
    was = meta.get("status")
    if was == "approved" or meta.get("changed_since_approval"):
        meta["version"] = int(meta.get("version") or 1) + (1 if meta.get("changed_since_approval") else 0)
    meta.update(status="approved", approved_by=name, approved_on=date.today().isoformat(),
                changed_since_approval=False, hash=body_hash(body), notes=list(args.note or []))
    paths.brief.write_text(render_front_matter(meta) + body, encoding="utf-8")
    write_grooming(paths, state)
    events.log(feature, "approve", "Brief approved by %s" % name, by=name)
    emit(args, {"status": "approved", "by": name, "on": meta["approved_on"], "version": meta["version"]},
         ["Brief:    approved by %s on %s (version %s)" % (name, meta["approved_on"], meta["version"]),
          "Next:     the design. /chopchop:run %d goes on." % feature.number])
    return 0


def cmd_status(args, ws):
    feature, paths = get(ws, args.ref)
    state = load_state(paths)
    c = counts(state)
    meta = features.read_front_matter(paths.brief) if paths.brief.is_file() else {}
    status = groom_status(state, paths)
    data = {"feature": feature.name, "mode": state["mode"], "status": status, "counts": c, "rounds": state.get("rounds", 0),
            "brief": meta.get("status"), "approved_by": meta.get("approved_by"),
            "changed_since_approval": bool(meta.get("changed_since_approval"))}
    brief = "not written"
    if paths.brief.is_file():
        brief = "%s%s" % (meta.get("status") or "draft", " by %s on %s" % (meta["approved_by"], meta.get("approved_on"))
                          if meta.get("approved_by") else "")
        if meta.get("changed_since_approval"):
            brief += " · changed since the approval: approve it again"
    emit(args, data,
         ["Feature:  %s · %s mode" % (feature.name, state["mode"]),
          "Grooming: %s" % status,
          "Questions: %d in all · %d for the developer · %d for the BA · %d answered · %d assumed"
          % (c["questions"], c["open_dev"], c["open_ba"], c["answered"], c["assumed"]),
          "Brief:    %s" % brief])
    return 0


# --------------------------------------------------------------------------- main


def build_parser():
    p = argparse.ArgumentParser(prog="chopchop_groom.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("ref", nargs="?", default=None, help="the feature: number, epic key or part of the name")
    p.add_argument("--idea", metavar="TEXT", help="start a feature from an idea")
    p.add_argument("--name", help="with --idea: a short folder name")
    p.add_argument("--title", help="with --idea: the feature's title (default: the first sentence)")
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--mode", metavar="MODE", help="locked or open")
    p.add_argument("--findings", metavar="FILE", help="the merged research, as JSON")
    p.add_argument("--rules", metavar="FILE", help="for an idea: the agreed rules, written as stories R1, R2...")
    p.add_argument("--questions", nargs="?", const="all", metavar="WHO", help="dev, ba or all")
    p.add_argument("--answer", metavar="ID", help="a question id, with --text")
    p.add_argument("--text", help="the answer, or the question with --add-question")
    p.add_argument("--by", help="dev or ba")
    p.add_argument("--assume", action="store_true", help="with --answer: nobody answered, this is our assumption")
    p.add_argument("--answers", metavar="FILE", help="many answers, as JSON")
    p.add_argument("--ask-ba", dest="ask_ba", metavar="IDS", help="hand questions to the BA: Q3,Q4")
    p.add_argument("--add-question", dest="add_question", action="store_true")
    p.add_argument("--why", help="with --add-question: why it matters")
    p.add_argument("--story", help="with --add-question: the story it is about")
    p.add_argument("--ask", help="with --add-question: dev or ba")
    p.add_argument("--options", help='with --add-question: possible answers, "a|b|c"')
    p.add_argument("--blocking", action="store_true", help="with --add-question: must be answered before the brief")
    p.add_argument("--round", action="store_true", help="count one interview round")
    p.add_argument("--brief", action="store_true")
    p.add_argument("--approve", metavar="NAME")
    p.add_argument("--note", action="append", help="with --approve: a note; can repeat")
    p.add_argument("--status", action="store_true")
    p.add_argument("--workspace", help="the _chopchop folder (default: found from here)")
    p.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    ws = find_workspace(args.workspace)
    try:
        if args.idea:
            return cmd_idea(args, ws)
        if args.prepare:
            return cmd_prepare(args, ws)
        if args.mode:
            return cmd_mode(args, ws)
        if args.findings:
            return cmd_findings(args, ws)
        if args.rules:
            return cmd_rules(args, ws)
        if args.answers:
            return cmd_answers(args, ws)
        if args.answer:
            return cmd_answer(args, ws)
        if args.ask_ba:
            return cmd_ask_ba(args, ws)
        if args.add_question:
            return cmd_add_question(args, ws)
        if args.round:
            return cmd_round(args, ws)
        if args.questions:
            return cmd_questions(args, ws)
        if args.brief:
            return cmd_brief(args, ws)
        if args.approve is not None:
            return cmd_approve(args, ws)
        if args.status:
            return cmd_status(args, ws)
        return cmd_prepare(args, ws)
    except Inputs as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except (UsageError, FeatureError, ConfigError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
