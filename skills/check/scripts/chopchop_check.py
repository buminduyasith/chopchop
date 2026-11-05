#!/usr/bin/env python3
"""Check: find where a design or spec disagrees with the requirements.

Usage
  chopchop_check.py --prepare [REF] [--req PATH ...] [--design PATH ...]   what to compare, as JSON
  chopchop_check.py --write findings.json [REF] [--out FILE]               write the report

REF is a feature (number, epic key or part of the name). With a feature, requirements default
to requirements/requirement.md and design to design/, and the report goes to
_chopchop/<feature>/check.md. --req and --design add or replace inputs with any files or
folders. Without a feature, pass --out, or the report is printed.

findings.json:
  {"requirements": [{"id": "R1", "text": "...", "source": "brief.md:12"}],   # only for files the script cannot split
   "coverage": [{"req": "PAY-121.AC1", "status": "covered|partly|missing", "design": "design.md §4.2"}],
   "findings": [{"kind": "conflict|missing|extra|question", "severity": "high|medium|low",
                 "req": "PAY-121.AC2", "req_quote": "...", "design": "design.md §4.2 (line 41)",
                 "design_quote": "...", "problem": "...", "fix": "...", "ask": "BA|design owner|tech lead"}]}

Needs the tasks skill next to it. Standard library only. Python 3.8+.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_SCRIPTS = HERE.parents[1] / "tasks" / "scripts"
if not (TASKS_SCRIPTS / "chopchoplib" / "features.py").is_file():
    sys.exit("Error: check needs the tasks skill next to it (%s not found)." % TASKS_SCRIPTS)
sys.path.insert(0, str(TASKS_SCRIPTS))

from chopchoplib import features  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace  # noqa: E402
from chopchoplib.features import FeatureError, parse_front_matter, render_front_matter  # noqa: E402
from chopchoplib.requirements import STORY_RE, requirement_items, section, split_items  # noqa: E402,F401

REPORT = "check.md"
KINDS = {"conflict": "Conflicts", "missing": "Missing in the design", "extra": "Extra in the design",
         "question": "Questions"}
SEVERITIES = ["high", "medium", "low"]
STATUSES = ["covered", "partly", "missing"]
TEXT_EXT = {".md", ".markdown", ".txt", ".rst", ".adoc", ".yaml", ".yml", ".json", ".csv", ".html", ".xml",
            ".feature", ".puml", ".mmd", ".graphql", ".proto", ".sql"}


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------- inputs


def expand(paths):
    files = []
    for raw in paths:
        p = Path(raw).expanduser().resolve()
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.is_file() and f.name != "SOURCES.md"
                            and not any(part.startswith(".") for part in f.relative_to(p).parts))
        else:
            raise UsageError("Not found: %s" % raw)
    return files


def outline(path):
    """Headings with line numbers and section numbers, so findings can point at them."""
    p = Path(path)
    if p.suffix.lower() not in TEXT_EXT:
        return {"file": str(p), "lines": None, "headings": [], "note": "not a text file: read it another way"}
    lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
    heads, counters, fence = [], [0] * 6, False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            level = len(m.group(1))
            counters[level - 1] += 1
            counters[level:] = [0] * (6 - level)
            heads.append({"line": n, "level": level, "title": m.group(2)})
    return {"file": str(p), "lines": len(lines), "headings": heads}


def resolve_inputs(ws, ref, req, design):
    if ref is None and not req and not design:
        ref = ""  # the only feature, or a list to pick from
    feature = features.resolve(ws, ref) if ref is not None else None
    req_files, design_files = expand(req or []), expand(design or [])
    if feature:
        if not req and feature.file.exists():
            req_files = [feature.file]
        if not design and (feature.path / "design").is_dir():
            design_files = expand([feature.path / "design"])
    if not req_files:
        raise UsageError("No requirements to check. Give a feature that has requirements/requirement.md, "
                         "or --req <files or folder>.")
    if not design_files:
        raise UsageError("No design to check. Give a feature that has design/, or --design <files or folder>.")
    return feature, req_files, design_files


# --------------------------------------------------------------------------- report


def finding_key(f):
    return (f.get("kind"), (f.get("req") or "").upper(), (f.get("design") or "").split(" ")[0].lower())


def read_previous(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"(?s)<!-- chopchop:check (.*?) -->", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("-\\u002d", "--"))
    except ValueError:
        return None


def validate(data, known_ids):
    if not isinstance(data, dict):
        raise UsageError("findings must be a JSON object")
    extra = data.get("requirements") or []
    ids = set(known_ids) | {str(r.get("id")) for r in extra if isinstance(r, dict) and r.get("id")}
    problems = []
    for i, f in enumerate(data.get("findings") or [], 1):
        if f.get("kind") not in KINDS:
            problems.append("finding %d: kind must be one of %s" % (i, ", ".join(KINDS)))
        if f.get("severity") not in SEVERITIES:
            problems.append("finding %d: severity must be one of %s" % (i, ", ".join(SEVERITIES)))
        if not (f.get("problem") or "").strip():
            problems.append("finding %d: 'problem' is empty" % i)
        if f.get("kind") != "extra" and f.get("req") and ids and f["req"] not in ids:
            problems.append("finding %d: requirement '%s' is not a known id" % (i, f["req"]))
        if f.get("kind") == "extra" and not f.get("design"):
            problems.append("finding %d: an extra finding needs 'design'" % i)
        if f.get("kind") in ("conflict", "missing", "question") and not f.get("req"):
            problems.append("finding %d: a %s finding needs 'req'" % (i, f.get("kind")))
    for c in data.get("coverage") or []:
        if c.get("status") not in STATUSES:
            problems.append("coverage %s: status must be one of %s" % (c.get("req"), ", ".join(STATUSES)))
        if ids and c.get("req") not in ids:
            problems.append("coverage: '%s' is not a known requirement id" % c.get("req"))
    if problems:
        raise UsageError("findings.json has problems:\n  " + "\n  ".join(problems))
    return data


def quote(text):
    text = (text or "").strip()
    return "\n".join("> " + line for line in text.split("\n")) if text else "> _(not given)_"


def render(title, req_files, design_files, data, previous, base):
    today = date.today().isoformat()
    findings = data.get("findings") or []
    old = {finding_key(f): f for f in (previous or {}).get("findings") or []}
    for n, f in enumerate(findings, 1):
        f["id"] = "F%d" % n
        before = old.get(finding_key(f))
        f["since"] = (before.get("since") if before else None) or today
        f["new"] = bool(previous) and before is None
    new_keys = {finding_key(f) for f in findings}
    fixed = [f for k, f in old.items() if k not in new_keys]
    cov = data.get("coverage") or []
    counts = {k: sum(1 for f in findings if f["kind"] == k) for k in KINDS}
    cov_counts = {s: sum(1 for c in cov if c.get("status") == s) for s in STATUSES}
    blocking = counts["conflict"] + sum(1 for f in findings if f["kind"] == "missing" and f["severity"] == "high")
    result = "ready" if not blocking else "not ready"

    def rel(p):
        try:
            return str(Path(p).relative_to(base))
        except ValueError:
            return str(p)

    meta = {"checked": today, "result": result, "conflicts": counts["conflict"], "missing": counts["missing"],
            "extra": counts["extra"], "questions": counts["question"], "requirements": len(cov) or None}
    lines = [render_front_matter(meta).rstrip(), "", "# Check · %s" % title, "",
             "_Written by chopchop on %s. Run `/chopchop:check` again after fixing things._" % today, "",
             "- **Requirements:** %s" % ", ".join("`%s`" % rel(p) for p in req_files),
             "- **Design:** %s" % ", ".join("`%s`" % rel(p) for p in design_files), ""]
    if result == "ready":
        verdict = "**Result: ready.** No conflicts and nothing important missing."
        rest = counts["missing"] + counts["extra"] + counts["question"]
        if rest:
            verdict += " %d smaller point%s below." % (rest, "" if rest == 1 else "s")
    else:
        parts = []
        if counts["conflict"]:
            parts.append("%d conflict%s" % (counts["conflict"], "" if counts["conflict"] == 1 else "s"))
        high_missing = blocking - counts["conflict"]
        if high_missing:
            parts.append("%d important gap%s" % (high_missing, "" if high_missing == 1 else "s"))
        verdict = "**Result: not ready.** Fix %s before cutting tasks." % " and ".join(parts)
    lines += [verdict, "",
              "| Conflicts | Missing in design | Extra in design | Questions |", "| --- | --- | --- | --- |",
              "| %d | %d | %d | %d |" % (counts["conflict"], counts["missing"], counts["extra"], counts["question"]), ""]
    if cov:
        lines += ["Coverage: **%d of %d** requirements covered, %d partly, %d missing." % (
            cov_counts["covered"], len(cov), cov_counts["partly"], cov_counts["missing"]), ""]

    order = {s: i for i, s in enumerate(SEVERITIES)}
    for kind, heading in KINDS.items():
        group = sorted([f for f in findings if f["kind"] == kind], key=lambda f: order[f["severity"]])
        if not group:
            continue
        lines += ["## %s" % heading, ""]
        for f in group:
            where = " vs ".join(x for x in (f.get("req"), f.get("design")) if x)
            lines += ["### %s · %s · %s%s" % (f["id"], f["severity"], where,
                                              "  (new)" if f["new"] else ""), ""]
            if f.get("req"):
                lines += ["**Requirement** (%s):" % f["req"], "", quote(f.get("req_quote")), ""]
            if f.get("design"):
                lines += ["**Design** (%s):" % f["design"], "", quote(f.get("design_quote")), ""]
            lines += ["- **Problem:** %s" % f["problem"].strip()]
            if f.get("fix"):
                lines.append("- **Fix:** %s" % f["fix"].strip())
            if f.get("ask"):
                lines.append("- **Ask:** %s" % f["ask"].strip())
            if previous and not f["new"]:
                lines.append("- _Open since %s._" % f["since"])
            lines.append("")
    if cov:
        mark = {"covered": "covered", "partly": "partly", "missing": "**missing**"}
        lines += ["## Coverage", "", "| Requirement | Status | Design |", "| --- | --- | --- |"]
        for c in cov:
            lines.append("| %s | %s | %s |" % (c["req"], mark[c["status"]], (c.get("design") or "-").replace("|", "\\|")))
        lines.append("")
    if fixed:
        lines += ["## Fixed since the last check", ""]
        lines += ["- %s %s: %s" % (f.get("kind"), " vs ".join(x for x in (f.get("req"), f.get("design")) if x),
                                    f.get("problem")) for f in fixed]
        lines.append("")
    state = {"findings": [{k: f.get(k) for k in ("kind", "severity", "req", "design", "problem", "since")}
                          for f in findings]}
    lines += ["<!-- chopchop:check %s -->" % json.dumps(state, ensure_ascii=False).replace("--", "-\\u002d"), ""]
    return "\n".join(lines), {"result": result, "counts": counts, "coverage": cov_counts, "fixed": len(fixed),
                              "new": sum(1 for f in findings if f["new"])}


# --------------------------------------------------------------------------- commands


def cmd_prepare(args, ws):
    feature, req_files, design_files = resolve_inputs(ws, args.ref, args.req, args.design)
    reqs, other = [], []
    for f in req_files:
        if f.name == "requirement.md" and STORY_RE.search(f.read_text(encoding="utf-8")):
            reqs += requirement_items(f)
        else:
            other.append(outline(f))
    out = {"feature": feature.name if feature else None,
           "report": str(feature.path / REPORT) if feature else args.out,
           "requirements": reqs, "requirement_files": other,
           "design": [outline(f) for f in design_files],
           "previous": read_previous(feature.path / REPORT) if feature else (read_previous(args.out) if args.out else None)}
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    print("Feature:  %s" % (out["feature"] or "none (any files)"))
    print("Report:   %s" % (out["report"] or "printed (no --out)"))
    for f in req_files:
        print("Req:      %s" % f)
    if reqs:
        stories = [r for r in reqs if r["kind"] == "story"]
        print("Items:    %d stories, %d acceptance criteria (ids like %s)" % (
            len(stories), sum(1 for r in reqs if r["kind"] == "ac"), reqs[-1]["id"]))
    if other:
        print("Note:     %d requirement file(s) are not a requirement.md. Give their requirements ids yourself (R1, R2...)."
              % len(other))
    for d in out["design"]:
        print("Design:   %s (%s lines, %d headings)" % (d["file"], d["lines"] or "?", len(d["headings"])))
    if out["previous"]:
        print("Before:   %d finding(s) from the last check" % len(out["previous"].get("findings") or []))
    return 0


def cmd_write(args, ws):
    feature, req_files, design_files = resolve_inputs(ws, args.ref, args.req, args.design)
    data = json.loads(Path(args.write).read_text(encoding="utf-8"))
    known = []
    for f in req_files:
        if f.name == "requirement.md" and STORY_RE.search(f.read_text(encoding="utf-8")):
            known += [r["id"] for r in requirement_items(f)]
    data = validate(data, known)
    target = Path(args.out) if args.out else (feature.path / REPORT if feature else None)
    base = Path(ws).parent if feature else Path.cwd()
    title = feature.name if feature else "design vs requirements"
    text, summary = render(title, req_files, design_files, data, read_previous(target) if target else None, base)
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    if args.json:
        print(json.dumps(dict(summary, report=str(target) if target else None), indent=2))
    elif target:
        c = summary["counts"]
        print("Report:   %s" % target)
        print("Result:   %s · %d conflict(s), %d missing, %d extra, %d question(s)" % (
            summary["result"], c["conflict"], c["missing"], c["extra"], c["question"]))
        if summary["coverage"] and sum(summary["coverage"].values()):
            cv = summary["coverage"]
            print("Coverage: %d covered, %d partly, %d missing" % (cv["covered"], cv["partly"], cv["missing"]))
        if summary["fixed"] or summary["new"]:
            print("Since:    %d fixed, %d new since the last check" % (summary["fixed"], summary["new"]))
    else:
        print(text)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="chopchop_check.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("ref", nargs="?", help="feature: number, epic key or part of the name")
    p.add_argument("--prepare", action="store_true", help="list what to compare, as JSON with --json")
    p.add_argument("--write", metavar="FINDINGS_JSON", help="write the report from your findings")
    p.add_argument("--req", action="append", metavar="PATH", help="requirement files or folders (repeatable)")
    p.add_argument("--design", action="append", metavar="PATH", help="design or spec files or folders (repeatable)")
    p.add_argument("--out", help="where to write the report when there is no feature")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="path to the _chopchop folder")
    args = p.parse_args(argv)
    try:
        if args.prepare == bool(args.write):
            raise UsageError("Use --prepare or --write <findings.json>.")
        ws = find_workspace(args.workspace)
        return (cmd_prepare if args.prepare else cmd_write)(args, ws)
    except (UsageError, ConfigError, FeatureError, ValueError, OSError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
