#!/usr/bin/env python3
"""Spec: the full plan to build, test and finish a feature, from its design and the code.

Usage
  chopchop_spec.py --prepare [REF] [--json]          everything the run needs, and what is missing
  chopchop_spec.py --plan SIZE --repos a,b           how many helpers this job gets
  chopchop_spec.py --scaffold [REF]                  start spec/spec.md and spec/spec.json
  chopchop_spec.py --build [REF] [--json]            check, fill the generated sections, lint, update the page
  chopchop_spec.py --status [REF] [--json]           what is planned, built and proved
  chopchop_spec.py --sign M1 --by NAME [REF]         a person signs a manual check or a manual journey
  chopchop_spec.py --done --by NAME [REF]            a person sets the feature to done, when everything is proved
  chopchop_spec.py --open [REF]                      open feature.html

REF is a feature (number, epic key or part of the name). With one feature it can be left out.

Files, in _chopchop/<feature>/:
  spec/spec.md      for people: 21 sections in 4 parts (chopchop writes the words, the script fills 13 blocks)
  spec/spec.json    the facts: rules, files, code, contracts, tests, journeys, packages
  work/proof.json   manual checks and journeys a person signed
  work/verify/      test results /chopchop:code saves for each task

--build exits 0 when the spec is ready to cut tasks, 1 when something blocks it (it says what),
and 2 when an input file is broken.

Needs the tasks skill next to it. Standard library only. Python 3.8+.
"""

import argparse
import json
import re
import sys
import webbrowser
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE.parents[1] / "tasks"
if not (TASKS / "scripts" / "chopchoplib" / "specdata.py").is_file():
    sys.exit("Error: spec needs the tasks skill next to it (%s not found)." % TASKS)
sys.path.insert(0, str(TASKS / "scripts"))

from chopchoplib import cite, designdoc, diagrams, features, helpers, mdhtml, page, specdata  # noqa: E402
from chopchoplib import tasks as tasklib  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace, load_config  # noqa: E402
from chopchoplib.features import FeatureError, parse_front_matter, render_front_matter  # noqa: E402
from chopchoplib.requirements import requirement_items, story_ids  # noqa: E402

SPEC_TEMPLATE = HERE.parent / "templates" / "spec.md"
PAGE_TEMPLATE = TASKS / "templates" / "feature.html"
SKELETON = {"version": 1, "title": "", "rules": [], "out_of_scope": [], "repos": {}, "contracts": [],
            "packages": [], "journeys": [], "checks": [], "questions": [], "assumptions": []}


class UsageError(Exception):
    pass


class Inputs(Exception):
    """An input file is broken: exit 2."""


# --------------------------------------------------------------------------- places


class Paths:
    def __init__(self, feature):
        self.feature = feature
        self.dir = feature.path / specdata.SPEC_DIR
        self.md = self.dir / specdata.SPEC_MD
        self.json = self.dir / specdata.SPEC_JSON
        self.work = feature.path / "work"
        self.proof = self.work / specdata.PROOF_FILE
        self.verify = self.work / specdata.VERIFY_DIR
        self.report = self.work / "spec-build.json"
        self.design = feature.path / "design" / "design.md"
        self.flow = feature.path / "design" / "flow.json"
        self.arch = feature.path / "design" / "architecture.json"
        self.options = self.work / "options.json"
        self.tasks = feature.path / tasklib.TASKS_DIR
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


def read_md(path):
    if not path.is_file():
        return None, None
    return parse_front_matter(path.read_text(encoding="utf-8"))


def write_md(path, meta, body):
    path.write_text(render_front_matter(meta) + body.lstrip("\n"), encoding="utf-8")


def load_verify(paths):
    out = {}
    if paths.verify.is_dir():
        for f in sorted(paths.verify.glob("T*.json")):
            try:
                out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    return out


def load_tasks(paths):
    return tasklib.load_tasks(paths.tasks) if paths.tasks.is_dir() else []


def profiles(ws, names):
    out = {}
    for name in names:
        p = Path(ws) / "repos" / ("%s.md" % name)
        out[name] = {"file": str(p), "exists": p.is_file()}
    return out


# --------------------------------------------------------------------------- prepare and scaffold


def prepare(ws, cfg, ref):
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    items, stories = requirements(feature)
    dmeta, _ = read_md(paths.design)
    smeta, _ = read_md(paths.md)
    repos = repo_dirs(cfg, ws)
    s = helpers.settings(cfg)
    styles = cfg.get("repos") if isinstance(cfg.get("repos"), dict) else {}
    tasks_found = load_tasks(paths)
    return {
        "feature": feature.as_dict(),
        "workspace": str(ws),
        "requirements": {"file": str(feature.file) if feature.file.is_file() else None, "stories": stories,
                         "items": [{"id": r["id"], "kind": r["kind"], "text": r["text"][:300]} for r in items]},
        "design": {"exists": dmeta is not None, "status": (dmeta or {}).get("status"), "size": (dmeta or {}).get("size"),
                   "version": (dmeta or {}).get("version"), "approved": str((dmeta or {}).get("status") or "").startswith("approved"),
                   "files": {"design": paths.design.is_file(), "architecture": paths.arch.is_file(),
                             "flow": paths.flow.is_file(), "options": paths.options.is_file()}},
        "spec": {"exists": paths.json.is_file(), "status": (smeta or {}).get("status")},
        "tasks": {"count": len(tasks_found)},
        "repos": {k: str(v) for k, v in repos.items()},
        "profiles": profiles(ws, list(repos)),
        "styles": {k: (v.get("style") if isinstance(v, dict) else None) for k, v in styles.items()},
        "reports": sorted(str(p) for p in (paths.work / "reports").glob("*")) if (paths.work / "reports").is_dir() else [],
        "helpers": dict(s, ask=not s["set"], calls={r: helpers.for_role(s, r) for r in helpers.ROLES}),
        "files": paths.as_dict(),
        "templates": {"spec": str(SPEC_TEMPLATE)},
    }


def print_prepare(d):
    print("Feature:  %s" % d["feature"]["folder"])
    des = d["design"]
    if not des["exists"]:
        print("Design:   none yet. Run /chopchop:design first: the spec is built from an approved design.")
    else:
        print("Design:   %s%s" % (des["status"], "" if des["approved"] else ". Not approved yet: say so, and go on."))
        gone = [k for k, v in des["files"].items() if not v]
        if gone:
            print("Missing:  design %s" % ", ".join(gone))
    print("Stories:  %s" % (", ".join(d["requirements"]["stories"]) or "none"))
    print("Spec:     %s" % ("%s (%s)" % (d["files"]["json"], d["spec"]["status"]) if d["spec"]["exists"] else "not started"))
    no_profile = [k for k, v in d["profiles"].items() if not v["exists"]]
    if no_profile:
        print("Profiles: missing for %s. Make them with /chopchop:code --profile <repo>, so tests have run commands."
              % ", ".join(no_profile))
    h = d["helpers"]
    print("Helpers:  %s" % ("not set yet: ask the 3 helper questions once" if h["ask"] else
                            "max %d, model %s, effort %s" % (h["max"], h["model"], h["effort"])))
    if d["tasks"]["count"]:
        print("Tasks:    %d already cut. A changed spec does not rewrite them." % d["tasks"]["count"])


def scaffold(ws, ref):
    feature = features.resolve(ws, ref)
    paths = Paths(feature)
    paths.dir.mkdir(parents=True, exist_ok=True)
    dmeta, _ = read_md(paths.design)
    title = (dmeta or {}).get("title") or feature.meta.get("title") or feature.name
    made = []
    if not paths.md.is_file():
        body = SPEC_TEMPLATE.read_text(encoding="utf-8").replace("{{title}}", title)
        meta = {"title": title, "status": "draft", "design_version": (dmeta or {}).get("version"),
                "design_status": (dmeta or {}).get("status"), "created": date.today().isoformat()}
        write_md(paths.md, meta, body)
        made.append(str(paths.md))
    if not paths.json.is_file():
        paths.json.write_text(json.dumps(dict(SKELETON, title=title), indent=2) + "\n", encoding="utf-8")
        made.append(str(paths.json))
    return {"spec": str(paths.md), "data": str(paths.json), "created": made}


# --------------------------------------------------------------------------- build


def context(ws, cfg, feature):
    paths = Paths(feature)
    items, stories = requirements(feature)
    spec = load_json(paths.json, "spec/spec.json")
    if spec is None:
        raise UsageError("No spec/spec.json yet. Run --scaffold, then write it.")
    return {"paths": paths, "items": items, "stories": stories, "known": {r["id"] for r in items},
            "spec": spec, "flow": load_json(paths.flow, "design/flow.json"),
            "opts": load_json(paths.options, "work/options.json"), "repos": repo_dirs(cfg, ws),
            "tasks": load_tasks(paths), "verify": load_verify(paths), "proof": load_json(paths.proof, "work/proof.json") or {}}


def fill_blocks(body, spec, ctx, results, st, meta):
    task_of = st["task_of"]
    blocks = {
        "rules": specdata.render_rules(spec),
        "files": specdata.render_files(spec),
        "fit": specdata.render_fit(spec, results),
        "contracts": specdata.render_contracts(spec),
        "failures": specdata.render_failures(spec, ctx["flow"]),
        "packages": specdata.render_packages(spec, results, task_of),
        "unit": specdata.render_tests(spec, "unit"),
        "integration": specdata.render_tests(spec, "integration"),
        "journeys": specdata.render_journeys(spec, task_of),
        "checks": specdata.render_checks(spec),
        "done": specdata.render_done(st, meta),
        "decisions": specdata.render_decisions(spec, ctx["opts"]),
        "trace": specdata.render_trace(spec, st),
    }
    for name, content in blocks.items():
        body, _ = designdoc.fill(body, name, content)
    return body


def update_page(ctx, spec, body, st, meta, results):
    paths = ctx["paths"]
    data = page.read_data(paths.page)
    if data is None:
        return None
    html = mdhtml.convert(body)
    svg = diagrams.file_map_svg(spec)
    if svg:
        html = page._swap(html, diagrams.file_map_mermaid(spec), svg)
    data["spec"] = page.spec_part(html, specdata.counts(spec), st, meta)
    data.setdefault("cites", {}).update(page.cite_data(results))
    data["stages"] = page.spec_stages(data.get("stages") or [], st, meta)
    data["generated"] = page.now()
    paths.page.write_text(page.render(PAGE_TEMPLATE.read_text(encoding="utf-8"), data), encoding="utf-8")
    return str(paths.page)


def build(ws, cfg, ref):
    feature = features.resolve(ws, ref)
    ctx = context(ws, cfg, feature)
    paths, spec = ctx["paths"], ctx["spec"]
    meta, body = read_md(paths.md)
    if meta is None:
        raise UsageError("No spec/spec.md yet. Run --scaffold first.")
    errors, warnings = specdata.validate(spec, ctx["stories"], ctx["known"], set(ctx["repos"]) or None, ctx["flow"])
    dmeta, _ = read_md(paths.design)
    if dmeta is None:
        warnings.append("there is no design.md. The spec should come from an approved design.")
    elif not str(dmeta.get("status") or "").startswith("approved"):
        warnings.append("the design is %s, not approved yet. Tell the lead the spec may change." % (dmeta.get("status") or "a draft"))
    elif meta.get("design_version") and dmeta.get("version") and str(meta["design_version"]) != str(dmeta["version"]):
        warnings.append("the design changed (version %s, the spec was written from %s). Check what it changes."
                        % (dmeta["version"], meta["design_version"]))

    # citations: in spec.json (code to copy, reuse) and in spec.md
    found = specdata.cites(spec)
    raws = {c["raw"] for c in found}
    found += [c for c in cite.find(re.sub(r"(?s)<!--.*?-->", "", body)) if c["raw"] not in raws]
    results = cite.check_all(found, ctx["repos"])
    moved = 0
    if results:
        raw_json = paths.json.read_text(encoding="utf-8")
        new_json, n1 = cite.fix_text(raw_json, results)
        body, n2 = cite.fix_text(body, results)
        moved = n1 + n2
        if n1:
            paths.json.write_text(new_json, encoding="utf-8")
            spec = json.loads(new_json)
            for r in results:
                fixed = cite.fixed_raw(r)
                if fixed:
                    r["raw"] = fixed
    for r in results:
        if r["status"] == "gone":
            errors.append("citation %s: %s. Read the code again and fix it." % (r["raw"], r["note"]))
        elif r["status"] == "changed":
            warnings.append("citation %s: %s. Re-read it and fix the code to copy or the sketch." % (r["raw"], r["note"]))
        elif r["status"] == "unknown" and r["note"]:
            warnings.append("citation %s: %s" % (r["raw"], r["note"]))
    errors += specdata.reuse_problems(spec, results)
    e2, w2 = specdata.file_problems(spec, ctx["repos"])
    errors += e2
    warnings += w2

    st = specdata.status(spec, ctx["tasks"], ctx["verify"], ctx["proof"])
    body = fill_blocks(body, spec, ctx, results, st, meta)
    le, lw = specdata.lint(body)
    errors += le
    warnings += lw

    if meta.get("status") != "done":
        meta["status"] = "building" if ctx["tasks"] and not errors else ("ready" if not errors else "draft")
    meta["updated"] = date.today().isoformat()
    meta["design_version"] = meta.get("design_version") or (dmeta or {}).get("version")
    write_md(paths.md, meta, body)
    pg = update_page(ctx, spec, body, st, meta, results)
    if pg is None:
        warnings.append("no feature.html yet, so the Spec tab was not added. Build the design page first.")
    report = {"feature": feature.name, "ready": not errors, "status": meta["status"], "errors": errors,
              "warnings": warnings, "counts": specdata.counts(spec), "cites": cite.summary(results),
              "moved_fixed": moved, "proof": {"proved": st["proved"], "total": st["total"]},
              "spec": str(paths.md), "data": str(paths.json), "page": pg}
    paths.work.mkdir(parents=True, exist_ok=True)
    paths.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def print_report(r):
    c = r["counts"]
    print("Spec:     %s" % r["spec"])
    print("Size:     %d rules, %d packages in %d repos, %d files, %d tests, %d journeys, %d manual checks"
          % (c["rules"], c["packages"], c["repos"], c["files"], c["tests"], c["journeys"], c["checks"]))
    cs = r["cites"]
    print("Cites:    %d checked: %s" % (sum(cs.values()), ", ".join("%d %s" % (v, k) for k, v in cs.items() if v) or "none"))
    if r["moved_fixed"]:
        print("Fixed:    %d citations that moved" % r["moved_fixed"])
    print("Proof:    %d of %d proved" % (r["proof"]["proved"], r["proof"]["total"]))
    if r["page"]:
        print("Page:     %s (Spec tab)" % r["page"])
    for e in r["errors"]:
        print("Error:    %s" % e)
    for w in r["warnings"]:
        print("Warning:  %s" % w)
    print("Result:   %s" % ("ready. Next: /chopchop:tasks" if r["ready"] else
                            "%d thing(s) block it. Fix them and build again." % len(r["errors"])))


# --------------------------------------------------------------------------- status, sign, done


def status(ws, cfg, ref):
    feature = features.resolve(ws, ref)
    ctx = context(ws, cfg, feature)
    meta, body = read_md(ctx["paths"].md)
    st = specdata.status(ctx["spec"], ctx["tasks"], ctx["verify"], ctx["proof"])
    if meta is not None:
        body, _ = designdoc.fill(body, "done", specdata.render_done(st, meta))
        body, _ = designdoc.fill(body, "trace", specdata.render_trace(ctx["spec"], st))
        write_md(ctx["paths"].md, meta, body)
        data = page.read_data(ctx["paths"].page)
        if data is not None and data.get("spec"):
            data["spec"] = page.spec_part(page._swap(mdhtml.convert(body), diagrams.file_map_mermaid(ctx["spec"]),
                                                     diagrams.file_map_svg(ctx["spec"])), specdata.counts(ctx["spec"]), st, meta)
            data["stages"] = page.spec_stages(data.get("stages") or [], st, meta)
            ctx["paths"].page.write_text(page.render(PAGE_TEMPLATE.read_text(encoding="utf-8"), data), encoding="utf-8")
    st.pop("task_of", None)
    return dict(st, feature=feature.name, status=(meta or {}).get("status"))


def print_status(st):
    print("Feature:  %s · spec %s" % (st["feature"], st["status"] or "not started"))
    print("Tasks:    %d of %d done" % (st["tasks"]["done"], st["tasks"]["total"]))
    print("Proof:    %d of %d proved" % (st["proved"], st["total"]))
    for i in st["items"]:
        if i["state"] != "proved":
            print("  %-8s %-34s %-8s %s" % (i["kind"], str(i["id"])[:34], specdata.STATE_TEXT[i["state"]], i["how"]))
    if st["open_questions"]:
        print("Open:     %d question(s)" % st["open_questions"])
    print("Done:     %s" % ("set" if st["status"] == "done" else
                            "ready for a person to set (--done --by NAME)" if st["ready_for_done"] else "not yet"))


def sign(ws, cfg, ref, item, by):
    if not by:
        raise UsageError("Say who signs: --by NAME.")
    feature = features.resolve(ws, ref)
    ctx = context(ws, cfg, feature)
    spec = ctx["spec"]
    manual = {m["id"] for m in specdata._items(spec, "checks")} | \
             {j["id"] for j in specdata._items(spec, "journeys") if isinstance(j.get("manual"), dict)}
    if item not in manual:
        raise UsageError("%s is not a manual check or a manual journey. Signable: %s" % (item, ", ".join(sorted(manual)) or "none"))
    proof = ctx["proof"] if isinstance(ctx["proof"], dict) else {}
    proof.setdefault("signed", {})[item] = {"by": by, "on": date.today().isoformat()}
    ctx["paths"].work.mkdir(parents=True, exist_ok=True)
    ctx["paths"].proof.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    return status(ws, cfg, ref)


def done(ws, cfg, ref, by):
    if not by:
        raise UsageError("Say who sets it: --by NAME. Only a person sets a feature to done.")
    feature = features.resolve(ws, ref)
    ctx = context(ws, cfg, feature)
    st = specdata.status(ctx["spec"], ctx["tasks"], ctx["verify"], ctx["proof"])
    if not st["ready_for_done"]:
        left = ["%s %s (%s)" % (i["kind"], i["id"], specdata.STATE_TEXT[i["state"]]) for i in st["items"] if i["state"] != "proved"]
        raise UsageError("Not everything is proved yet:\n  - " + "\n  - ".join(left or ["an open question blocks it"]))
    meta, body = read_md(ctx["paths"].md)
    meta.update(status="done", done_by=by, done_on=date.today().isoformat())
    write_md(ctx["paths"].md, meta, body)
    return status(ws, cfg, ref)


# --------------------------------------------------------------------------- main


def main(argv=None):
    p = argparse.ArgumentParser(prog="chopchop_spec.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("ref", nargs="?", default=None, help="the feature: number, epic key or part of the name")
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--plan", metavar="SIZE", help="small, medium or large")
    p.add_argument("--repos", help="repos the feature changes, comma separated (with --plan)")
    p.add_argument("--scaffold", action="store_true")
    p.add_argument("--build", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--sign", metavar="ID", help="a manual check (M1) or manual journey (J2)")
    p.add_argument("--done", action="store_true")
    p.add_argument("--by", help="who signs, or who sets done")
    p.add_argument("--open", action="store_true")
    p.add_argument("--workspace", help="the _chopchop folder (default: found from here)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        ws = find_workspace(args.workspace)
        cfg = load_config(ws)
        if args.prepare:
            out = prepare(ws, cfg, args.ref)
            if not args.json:
                print_prepare(out)
                return 0
        elif args.plan:
            names = [r.strip() for r in (args.repos or "").split(",") if r.strip()]
            try:
                out = helpers.plan(args.plan, names, helpers.settings(cfg), choices=False)
            except ValueError as e:
                raise UsageError(str(e))
            out["calls"] = {r: helpers.for_role(helpers.settings(cfg), r) for r in helpers.ROLES}
            if not args.json:
                print(out["line"])
                return 0
        elif args.scaffold:
            out = scaffold(ws, args.ref)
            if not args.json:
                print("Spec:     %s" % out["spec"])
                print("Data:     %s" % out["data"])
                if not out["created"]:
                    print("Note:     both were already there, left as they are")
                return 0
        elif args.build:
            out = build(ws, cfg, args.ref)
            if args.json:
                print(json.dumps(out, indent=2))
            else:
                print_report(out)
            return 0 if out["ready"] else 1
        elif args.status or args.sign or args.done:
            if args.sign:
                out = sign(ws, cfg, args.ref, args.sign, args.by)
            elif args.done:
                out = done(ws, cfg, args.ref, args.by)
            else:
                out = status(ws, cfg, args.ref)
            if not args.json:
                print_status(out)
                return 0
        elif args.open:
            pg = Paths(features.resolve(ws, args.ref)).page
            if not pg.exists():
                raise UsageError("No feature.html yet. Build the design first.")
            webbrowser.open(pg.resolve().as_uri())
            print("Opened:   %s" % pg)
            return 0
        else:
            raise UsageError("Use --prepare, --scaffold, --build, --status, --sign, --done or --open. See --help.")
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
