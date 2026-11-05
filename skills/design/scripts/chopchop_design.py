#!/usr/bin/env python3
"""Design: options.md, design.md and feature.html for one feature, ready for a lead to approve.

Usage
  chopchop_design.py --prepare [REF] [--json]        everything the run needs, and what is missing
  chopchop_design.py --plan SIZE --repos a,b [--no-choices]   how many helpers this job gets
  chopchop_design.py --helpers --max 3 --model inherit --effort inherit   save helper settings
  chopchop_design.py --scaffold [REF] [--size medium] [--title "..."]     start design.md
  chopchop_design.py --options [REF]                 check work/options.json and write options.md
  chopchop_design.py --failures [REF] [--json]       the failure questions each arrow must answer
  chopchop_design.py --build [REF] [--json]          check, draw, lint and write the page
  chopchop_design.py --pick 2=B [REF] [--by you|lead|chopchop]   change one choice, then build
  chopchop_design.py --approve NAME --result approved|conditions|changes [--note TEXT ...] [REF]
  chopchop_design.py --status [REF]                  where the design stands
  chopchop_design.py --open [REF]                    open feature.html

REF is a feature (number, epic key or part of the name). With one feature it can be left out.

Files, in _chopchop/<feature>/:
  design/design.md          for leads: 12 fixed sections (chopchop writes it, the script fills 4 blocks)
  design/options.md         the choices (the script writes it from work/options.json)
  design/architecture.json  the high-level design (written with the diagram skill)
  design/flow.json          the main flow, with failure answers (written with the diagram skill)
  work/options.json         the choices as data (the architect helper writes it)
  work/answers.json         the questions asked and the answers
  feature.html              the page: design, choices and slides

--build exits 0 when the design is ready for review, 1 when something blocks the approval
request (it says what), and 2 when an input file is broken.

Needs the tasks skill next to it. Standard library only. Python 3.8+.
"""

import argparse
import json
import shutil
import sys
import webbrowser
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE.parents[1] / "tasks"
if not (TASKS / "scripts" / "chopchoplib" / "designdoc.py").is_file():
    sys.exit("Error: design needs the tasks skill next to it (%s not found)." % TASKS)
sys.path.insert(0, str(TASKS / "scripts"))

from chopchoplib import cite, designdoc, diagrams, features, helpers, options, page, systemmap  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace, load_config  # noqa: E402
from chopchoplib.features import FeatureError, parse_front_matter, render_front_matter  # noqa: E402
from chopchoplib.requirements import requirement_items, story_ids  # noqa: E402

DESIGN_TEMPLATE = HERE.parent / "templates" / "design.md"
PAGE_TEMPLATE = TASKS / "templates" / "feature.html"
TEAM_DECISIONS = "team-decisions.md"
RESULTS = {"approved": "approved", "conditions": "approved-with-conditions", "changes": "changes-needed"}


class UsageError(Exception):
    pass


class Inputs(Exception):
    """An input file is broken: exit 2."""


# --------------------------------------------------------------------------- places


class Paths:
    def __init__(self, feature):
        self.feature = feature
        self.design_dir = feature.path / "design"
        self.work = feature.path / "work"
        self.design = self.design_dir / "design.md"
        self.options_md = self.design_dir / "options.md"
        self.arch = self.design_dir / "architecture.json"
        self.flow = self.design_dir / "flow.json"
        self.options = self.work / "options.json"
        self.answers = self.work / "answers.json"
        self.reports = self.work / "reports"
        self.build = self.work / "build.json"
        self.approved = self.work / "approved"
        self.page = feature.path / page.PAGE_FILE

    def as_dict(self):
        return {k: str(v) for k, v in vars(self).items() if isinstance(v, Path)}


def repo_dirs(cfg, ws):
    raw = cfg.get("repos")
    out = {}
    if isinstance(raw, dict):
        for name, v in raw.items():
            p = Path(str((v.get("path") if isinstance(v, dict) else v) or ".")).expanduser()
            out[str(name)] = p if p.is_absolute() else (Path(ws).parent / p).resolve()
    return out


def load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise Inputs("%s (%s) is not valid JSON: %s" % (what, path, e))


def requirements(feature):
    if not feature.file.is_file():
        return [], []
    items = requirement_items(feature.file)
    return items, story_ids(items)


def read_design(paths):
    if not paths.design.is_file():
        return None, None
    text = paths.design.read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    return meta, body


def write_design(paths, meta, body):
    paths.design.write_text(render_front_matter(meta) + body.lstrip("\n"), encoding="utf-8")


# --------------------------------------------------------------------------- prepare


def prepare(ws, cfg, ref):
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    items, stories = requirements(feature)
    s = helpers.settings(cfg)
    smap = systemmap.load(ws)
    repos = repo_dirs(cfg, ws)
    stale = []
    for name, path in repos.items():
        fact = systemmap.repo_facts(name, path, (smap or {}).get("repos", {}).get(name))
        if fact["mode"] != "fresh":
            stale.append({"repo": name, "mode": fact["mode"], "changed": fact.get("changed_count", 0)})
    meta, _ = read_design(paths)
    opts = load_json(paths.options, "work/options.json")
    team = Path(ws) / TEAM_DECISIONS
    return {
        "feature": feature.as_dict(),
        "workspace": str(ws),
        "requirements": {"file": str(feature.file) if feature.file.is_file() else None, "stories": stories,
                         "items": [{"id": r["id"], "kind": r["kind"], "text": r["text"][:300]} for r in items]},
        "repos": {k: str(v) for k, v in repos.items()},
        "helpers": dict(s, ask=not s["set"],
                        calls={r: helpers.for_role(s, r) for r in helpers.ROLES}),
        "system_map": {"exists": smap is not None, "updated": (smap or {}).get("updated"),
                       "stale": stale, "file": str(systemmap.path_of(ws)),
                       "md": str(systemmap.path_of(ws).with_name(systemmap.MD_FILE))},
        "team_decisions": {"file": str(team), "exists": team.is_file(),
                           "text": team.read_text(encoding="utf-8")[:6000] if team.is_file() else ""},
        "design": {"exists": meta is not None, "status": (meta or {}).get("status"), "size": (meta or {}).get("size"),
                   "version": (meta or {}).get("version"), "changed_since_approval": (meta or {}).get("changed_since_approval")},
        "options": {"exists": opts is not None, "unpicked": options.unpicked(opts) if opts else []},
        "diagrams": {"architecture": paths.arch.is_file(), "flow": paths.flow.is_file()},
        "answers": {"exists": paths.answers.is_file()},
        "files": paths.as_dict(),
        "templates": {"design": str(DESIGN_TEMPLATE)},
    }


def print_prepare(d):
    f = d["feature"]
    print("Feature:  %s" % f["folder"])
    req = d["requirements"]
    print("Stories:  %s" % (", ".join(req["stories"]) if req["stories"] else
                            "none. Write the rules you understood as stories (R1, R2) and ingest them first."))
    h = d["helpers"]
    print("Helpers:  %s" % ("not set yet: ask the 3 helper questions once" if h["ask"] else
                            "max %d, model %s, effort %s" % (h["max"], h["model"], h["effort"])))
    for p in h["problems"]:
        print("Warning:  %s" % p)
    sm = d["system_map"]
    if not sm["exists"]:
        print("Map:      no system map yet: build it first (learn)")
    elif sm["stale"]:
        print("Map:      refresh %s" % ", ".join("%s (%s)" % (s["repo"], s["mode"]) for s in sm["stale"]))
    else:
        print("Map:      fresh")
    des = d["design"]
    print("Design:   %s" % ("%s, size %s, version %s" % (des["status"], des["size"], des["version"]) if des["exists"]
                            else "not started"))
    if d["options"]["exists"] and d["options"]["unpicked"]:
        print("Choices:  not picked yet: %s" % ", ".join(str(n) for n in d["options"]["unpicked"]))
    print("Team:     %s" % (d["team_decisions"]["file"] if d["team_decisions"]["exists"] else "no team-decisions.md yet"))


# --------------------------------------------------------------------------- scaffold


def scaffold(ws, ref, size, title):
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    if size not in helpers.SIZES:
        raise UsageError("--size must be one of %s" % ", ".join(helpers.SIZES))
    paths.design_dir.mkdir(parents=True, exist_ok=True)
    paths.reports.mkdir(parents=True, exist_ok=True)
    if paths.design.exists():
        return {"design": str(paths.design), "created": False}
    meta, body = parse_front_matter(DESIGN_TEMPLATE.read_text(encoding="utf-8"))
    title = title or feature.meta.get("title") or feature.slug.replace("-", " ")
    meta = {"title": title, "status": "draft", "size": size, "version": 1,
            "created": date.today().isoformat(), "approved_by": None, "approved_on": None, "conditions": []}
    write_design(paths, meta, body.replace("{{title}}", title))
    return {"design": str(paths.design), "created": True}


# --------------------------------------------------------------------------- build


def write_options(ws, ref):
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    opts = load_json(paths.options, "work/options.json")
    if opts is None:
        raise UsageError("No work/options.json yet.")
    e, w = options.validate(opts)
    if e:
        raise Inputs("work/options.json has problems:\n  - " + "\n  - ".join(e))
    paths.design_dir.mkdir(parents=True, exist_ok=True)
    paths.options_md.write_text(options.render(opts, feature.name), encoding="utf-8")
    return {"options": str(paths.options_md), "warnings": w, "unpicked": options.unpicked(opts)}


def lead_and_assumptions(opts, answers):
    lead = options.lead_items(opts) if opts else []
    assumed = options.assumptions(opts) if opts else []
    for rnd in (answers or {}).get("rounds") or []:
        for q in rnd.get("questions") or []:
            if q.get("assumed"):
                assumed.append("%s %s" % (q.get("q", "").strip(), q.get("a", "").strip()))
    return lead, assumed


def approval_block(meta, who, lead, assumed):
    st = meta.get("status") or "draft"
    lines = ["**Status:** %s" % designdoc.STATUS_TEXT.get(st, st)]
    if meta.get("changed_since_approval"):
        lines[0] += " Changed since the last approval: approve it again."
    lines += ["", "**Who must approve:**", ""]
    lines += ["- %s (%s)" % (a["who"], a["why"]) for a in who] or ["- Not known yet: the high-level design has no new or changed repo."]
    lines += ["", "**For the lead:**", ""]
    lines += ["- %s%s" % (i["text"], " Owner: %s." % i["owner"] if i.get("owner") else "") for i in lead] or ["- None."]
    lines += ["", "**Assumptions to confirm:**", ""]
    lines += ["- %s" % a for a in assumed] or ["- None. Every choice was picked by a person."]
    if st.startswith("approved"):
        lines += ["", "**Approved:** by %s on %s." % (meta.get("approved_by"), meta.get("approved_on"))]
        for c in meta.get("conditions") or []:
            lines.append("- Condition: %s" % c)
    elif st == "changes-needed":
        lines += ["", "**Changes needed:**", ""] + ["- %s" % c for c in meta.get("conditions") or []]
    return "\n".join(lines)


ARCH_LEGEND = ("Green is new. Amber is changed. White is the same, shown for context. Dashed is outside the system. "
               "Each box with a name on top is one repo.")


def arch_block(arch):
    return "```mermaid\n%s\n```\n\n_%s_" % (diagrams.architecture_mermaid(arch), ARCH_LEGEND)


def flow_block(flow, arch):
    return "```mermaid\n%s\n```\n\n%s\n\nFailure answers for every message:\n\n%s" % (
        diagrams.flow_mermaid(flow, arch), "\n".join(diagrams.caption(flow)), diagrams.failure_table(flow))


def collect_cites(*texts):
    seen, out = set(), []
    for t in texts:
        for c in cite.find(t):
            if c["raw"] not in seen:
                seen.add(c["raw"])
                out.append(c)
    return out


def build(ws, cfg, ref):
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    meta, body = read_design(paths)
    if meta is None:
        raise UsageError("No design.md yet. Run --scaffold first.")
    items, stories = requirements(feature)
    known = {r["id"] for r in items}
    repos = repo_dirs(cfg, ws)
    errors, warnings = [], []

    opts = load_json(paths.options, "work/options.json")
    if opts is not None:
        e, w = options.validate(opts)
        if e:
            raise Inputs("work/options.json has problems:\n  - " + "\n  - ".join(e))
        warnings += ["options: %s" % x for x in w]
        unpicked = options.unpicked(opts)
        if unpicked:
            errors.append("choice %s not picked yet. Ask, or pick with --pick." % ", ".join(str(n) for n in unpicked))
    arch = load_json(paths.arch, "design/architecture.json")
    flow = load_json(paths.flow, "design/flow.json")
    if arch is not None:
        e, w = diagrams.validate_architecture(arch, set(repos))
        if e:
            raise Inputs("design/architecture.json has problems:\n  - " + "\n  - ".join(e))
        warnings += ["high-level design: %s" % x for x in w + diagrams.layout_problems(arch)[1]]
    else:
        errors.append("no design/architecture.json yet: draw it with the diagram skill")
    if flow is not None:
        e, w = diagrams.validate_flow(flow, arch, stories, known)
        if e:
            raise Inputs("design/flow.json has problems:\n  - " + "\n  - ".join(e))
        warnings += ["flow: %s" % x for x in w]
    else:
        errors.append("no design/flow.json yet: draw it with the diagram skill")
    answers = load_json(paths.answers, "work/answers.json")
    smap = systemmap.load(ws)

    # citations: fix what moved, then check again for the page
    opt_text = json.dumps(opts) if opts else ""
    results = cite.check_all(collect_cites(body, opt_text), repos)
    body, fixed_design = cite.fix_text(body, results)
    fixed_opts = 0
    if opts is not None:
        new_text, fixed_opts = cite.fix_text(json.dumps(opts, ensure_ascii=False), results)
        if fixed_opts:
            opts = json.loads(new_text)
            paths.options.write_text(json.dumps(options.strip(opts), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    first = cite.summary(results)
    if fixed_design or fixed_opts:
        results = cite.check_all(collect_cites(body, json.dumps(opts) if opts else ""), repos)
    for r in results:
        if r["status"] == "gone":
            errors.append("citation %s is gone: %s" % (r["raw"], r["note"]))
        elif r["status"] == "changed":
            warnings.append("citation %s: %s. Re-read it and fix the sentence." % (r["raw"], r["note"]))
        elif r["status"] == "unknown":
            warnings.append("citation %s cannot be checked: %s" % (r["raw"], r["note"]))
        else:
            continue

    lead, assumed = lead_and_assumptions(opts, answers)
    who = page.approvers(arch, smap, lead, repos)
    if opts is not None:
        paths.options_md.write_text(options.render(opts, feature.name), encoding="utf-8")
    missing_blocks = []
    blocks = {"decisions": options.decisions_table(opts) if opts else "None. No choices file yet.",
              "approval": approval_block(meta, who, lead, assumed)}
    if arch is not None:
        blocks["architecture"] = arch_block(arch)
    if flow is not None:
        blocks["flow"] = flow_block(flow, arch)
    for name, content in blocks.items():
        body, found = designdoc.fill(body, name, content)
        if not found:
            missing_blocks.append(name)
    gaps = diagrams.missing(flow) if flow else []
    for g in gaps:
        errors.append("message %s (%s) has no answer for: %s" % (g["n"], g["say"], g["ask"]))
    lint_e, lint_w = designdoc.lint(body, meta.get("size"), stories)
    errors += lint_e
    warnings += lint_w
    write_design(paths, meta, body)

    report = {"ready": not errors, "errors": errors, "warnings": warnings,
              "citations": {"found": len(results), "first_check": first, "fixed": fixed_design + fixed_opts,
                            "now": cite.summary(results)},
              "failures": {"answered": len(diagrams.failures(flow)) - len(gaps) if flow else 0, "missing": len(gaps)},
              "words": designdoc.words(body.split("\n## " + designdoc.APPENDIX)[0]),
              "budget": designdoc.BUDGETS.get(meta.get("size") or "medium"),
              "status": meta.get("status"), "page": str(paths.page), "design": str(paths.design),
              "options": str(paths.options_md) if opts is not None else None}
    paths.work.mkdir(parents=True, exist_ok=True)
    paths.build.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    options_md = paths.options_md.read_text(encoding="utf-8") if paths.options_md.is_file() else ""
    counts = (len(stories), len([r for r in items if r["kind"] == "ac"])) if items else None
    data = page.build(feature, meta, body, options_md, opts, arch, flow, results,
                      diagrams.failures(flow) if flow else [], report, counts, who, lead, assumed)
    paths.page.write_text(page.render(PAGE_TEMPLATE.read_text(encoding="utf-8"), data), encoding="utf-8")
    return report


def print_report(r):
    print("Design:   %s (%d words, budget %d)" % (r["design"], r["words"], r["budget"]))
    if r["options"]:
        print("Choices:  %s" % r["options"])
    c = r["citations"]
    print("Cites:    %d checked: %s%s" % (c["found"], ", ".join("%d %s" % (n, s) for s, n in c["now"].items() if n) or "none",
                                         ", %d fixed" % c["fixed"] if c["fixed"] else ""))
    print("Failures: %d answered, %d missing" % (r["failures"]["answered"], r["failures"]["missing"]))
    print("Page:     %s" % r["page"])
    for e in r["errors"]:
        print("Blocks:   %s" % e)
    for w in r["warnings"]:
        print("Warning:  %s" % w)
    print("Result:   %s" % ("ready for review" if r["ready"] else "%d thing(s) block the approval request" % len(r["errors"])))


# --------------------------------------------------------------------------- pick and approve


def do_pick(ws, cfg, ref, spec, by):
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    opts = load_json(paths.options, "work/options.json")
    if opts is None:
        raise UsageError("No work/options.json yet, so there is nothing to pick.")
    try:
        c = options.pick(opts, spec, by)
    except ValueError as e:
        raise UsageError(str(e))
    paths.options.write_text(json.dumps(options.strip(opts), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    meta, body = read_design(paths)
    if meta and str(meta.get("status") or "").startswith("approved"):
        meta["changed_since_approval"] = True
        write_design(paths, meta, body)
    return c


def approve(ws, cfg, ref, name, result, notes):
    if result not in RESULTS:
        raise UsageError("--result must be approved, conditions or changes")
    if not name or not name.strip():
        raise UsageError("--approve needs the name of the person who decided")
    if result == "conditions" and not notes:
        raise UsageError("approved with conditions needs at least one --note with a condition")
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    if result != "changes":
        report = build(ws, cfg, ref)
        if not report["ready"]:
            raise UsageError("The design is not ready for approval:\n  - " + "\n  - ".join(report["errors"]))
    meta, body = read_design(paths)
    if meta is None:
        raise UsageError("No design.md yet.")
    was = meta.get("status")
    meta.update(status=RESULTS[result], approved_by=name.strip(), approved_on=date.today().isoformat(),
                conditions=list(notes or []), changed_since_approval=False)
    if result == "changes":
        meta.update(approved_by=None, approved_on=None)
    elif was and str(was).startswith("approved") or meta.get("approved_once"):
        meta["version"] = int(meta.get("version") or 1) + 1
    if result != "changes":
        meta["approved_once"] = True
    write_design(paths, meta, body)
    if result != "changes":
        paths.approved.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(paths.design), str(paths.approved / ("design-v%s.md" % meta["version"])))
    report = build(ws, cfg, ref)
    return {"status": meta["status"], "by": name.strip(), "on": meta["approved_on"], "version": meta["version"],
            "conditions": meta["conditions"], "page": report["page"]}


def status(ws, cfg, ref):
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    meta, _ = read_design(paths)
    last = load_json(paths.build, "work/build.json") or {}
    opts = load_json(paths.options, "work/options.json")
    return {"feature": feature.name, "design": meta, "ready": last.get("ready"), "blocks": last.get("errors") or [],
            "unpicked": options.unpicked(opts) if opts else [], "page": str(paths.page) if paths.page.exists() else None}


# --------------------------------------------------------------------------- main


def main(argv=None):
    p = argparse.ArgumentParser(prog="chopchop_design.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("ref", nargs="?", default=None, help="the feature: number, epic key or part of the name")
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--plan", metavar="SIZE", help="small, medium or large")
    p.add_argument("--repos", help="repos the feature changes, comma separated (with --plan)")
    p.add_argument("--no-choices", action="store_true", help="no real choices, so no architect (with --plan)")
    p.add_argument("--helpers", action="store_true", help="save helper settings in chopchop.yaml")
    p.add_argument("--max", type=int)
    p.add_argument("--model")
    p.add_argument("--effort")
    p.add_argument("--scaffold", action="store_true")
    p.add_argument("--size", default="medium")
    p.add_argument("--title")
    p.add_argument("--options", action="store_true", help="check work/options.json and write options.md")
    p.add_argument("--failures", action="store_true")
    p.add_argument("--build", action="store_true")
    p.add_argument("--pick", metavar="N=X")
    p.add_argument("--by", default="you", help="who picked: you, lead or chopchop")
    p.add_argument("--approve", metavar="NAME")
    p.add_argument("--result", help="approved, conditions or changes")
    p.add_argument("--note", action="append", help="a condition, or a change needed; can repeat")
    p.add_argument("--status", action="store_true")
    p.add_argument("--open", action="store_true")
    p.add_argument("--workspace", help="the _chopchop folder (default: found from here)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    ws = find_workspace(args.workspace)
    try:
        cfg = load_config(ws)
        out = None
        if args.prepare:
            out = prepare(ws, cfg, args.ref)
            if not args.json:
                print_prepare(out)
                return 0
        elif args.plan:
            names = [r.strip() for r in (args.repos or "").split(",") if r.strip()]
            try:
                out = helpers.plan(args.plan, names, helpers.settings(cfg), choices=not args.no_choices)
            except ValueError as e:
                raise UsageError(str(e))
            out["calls"] = {r: helpers.for_role(helpers.settings(cfg), r) for r in helpers.ROLES}
            if not args.json:
                print(out["line"])
                return 0
        elif args.helpers:
            s = helpers.settings(cfg)
            try:
                path = helpers.write_block(cfg["_path"], args.max if args.max is not None else s["max"],
                                           args.model or s["model"], args.effort or s["effort"], s["roles"])
            except ValueError as e:
                raise UsageError(str(e))
            out = {"config": path, "backup": path + ".bak"}
            if not args.json:
                print("Saved:    helper settings in %s (old file kept as %s)" % (path, out["backup"]))
                return 0
        elif args.scaffold:
            out = scaffold(ws, args.ref, args.size, args.title)
            if not args.json:
                print("Design:   %s%s" % (out["design"], "" if out["created"] else " (already there, left as it is)"))
                return 0
        elif args.options:
            out = write_options(ws, args.ref)
            if not args.json:
                print("Choices:  %s" % out["options"])
                for w in out["warnings"]:
                    print("Warning:  %s" % w)
                if out["unpicked"]:
                    print("Pick:     choice %s not picked yet" % ", ".join(str(n) for n in out["unpicked"]))
                return 0
        elif args.failures:
            feature = features.resolve(ws, args.ref)
            flow = load_json(Paths(feature).flow, "design/flow.json")
            if flow is None:
                raise UsageError("No design/flow.json yet.")
            out = diagrams.failures(flow)
            if not args.json:
                for r in out:
                    mark = {"missing": "MISSING", "suggested": "suggested", "risk": "risk", "answered": "ok"}[r["state"]]
                    print("%-3s %-28s %-8s %-9s %s" % (r["n"], diagrams.mlabel(r["say"])[:28], r["question"], mark,
                                                       r["answer"] or r["ask"]))
                return 0
        elif args.build:
            out = build(ws, cfg, args.ref)
            if not args.json:
                print_report(out)
            else:
                print(json.dumps(out, indent=2))
            return 0 if out["ready"] else 1
        elif args.pick:
            c = do_pick(ws, cfg, args.ref, args.pick, args.by)
            print("Picked:   choice %s = %s (%s)" % (args.pick.split("=")[0].strip(), c["picked"], args.by))
            out = build(ws, cfg, args.ref)
            if not args.json:
                print_report(out)
            else:
                print(json.dumps(out, indent=2))
            return 0 if out["ready"] else 1
        elif args.approve:
            out = approve(ws, cfg, args.ref, args.approve, args.result, args.note)
            if not args.json:
                print("Design:   %s by %s on %s (version %s)" % (out["status"], out["by"], out["on"], out["version"]))
                for c in out["conditions"]:
                    print("Note:     %s" % c)
                print("Page:     %s" % out["page"])
                return 0
        elif args.status:
            out = status(ws, cfg, args.ref)
            if not args.json:
                meta = out["design"] or {}
                print("Feature:  %s" % out["feature"])
                print("Design:   %s" % (meta.get("status") or "not started"))
                print("Ready:    %s" % {True: "yes", False: "no", None: "not built yet"}[out["ready"]])
                for b in out["blocks"]:
                    print("Blocks:   %s" % b)
                if out["page"]:
                    print("Page:     %s" % out["page"])
                return 0
        elif args.open:
            feature = features.resolve(ws, args.ref)
            pg = Paths(feature).page
            if not pg.exists():
                raise UsageError("No feature.html yet. Run --build first.")
            webbrowser.open(pg.resolve().as_uri())
            print("Opened:   %s" % pg)
            return 0
        else:
            raise UsageError("Use --prepare, --scaffold, --build, --pick, --approve, --status or --open. See --help.")
        print(json.dumps(out, indent=2, default=str))
        return 0
    except Inputs as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except (UsageError, ConfigError, FeatureError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
