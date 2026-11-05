#!/usr/bin/env python3
"""Diagram: check and draw the two design diagrams of a feature.

Usage
  chopchop_diagram.py --check [REF] [--json]       check design/architecture.json and design/flow.json
  chopchop_diagram.py --draw [REF] [--open]        check, then write work/diagrams.html to look at
  chopchop_diagram.py --mermaid [REF]              print the Mermaid copies that go in design.md
  chopchop_diagram.py --check --arch FILE [--flow FILE]   any files, no feature needed

REF is a feature (number, epic key or part of the name). With one feature it can be left out.

The two pictures:
  architecture.json  the high-level design: the parts, the repo each lives in, what talks to what
  flow.json          the main flow in time order, with a failure answer for every message

--check and --draw exit 0 when both pictures are clean, 1 when a picture has a problem to fix
(each problem says the fix), and 2 when a file is missing or broken.

Needs the tasks skill next to it. Standard library only. Python 3.8+.
"""

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_SCRIPTS = HERE.parents[1] / "tasks" / "scripts"
if not (TASKS_SCRIPTS / "chopchoplib" / "diagrams.py").is_file():
    sys.exit("Error: diagram needs the tasks skill next to it (%s not found)." % TASKS_SCRIPTS)
sys.path.insert(0, str(TASKS_SCRIPTS))

from chopchoplib import diagrams, features  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace, load_config  # noqa: E402
from chopchoplib.features import FeatureError  # noqa: E402
from chopchoplib.requirements import requirement_items, story_ids  # noqa: E402

PREVIEW = "diagrams.html"


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------- inputs


def load(path):
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise UsageError("%s is not valid JSON: %s" % (path, e))


def sources(args):
    """The two files, plus what to check them against: repos, story ids and known ids."""
    if args.arch or args.flow:
        out = Path(args.out).expanduser() if args.out else Path(args.arch or args.flow).resolve().parent
        return {"arch": Path(args.arch) if args.arch else None, "flow": Path(args.flow) if args.flow else None,
                "repos": None, "stories": None, "known": None, "out": out}
    ws = find_workspace(args.workspace)
    cfg = load_config(ws)
    feature = features.resolve(ws, args.ref)
    items = requirement_items(feature.file) if feature.file.is_file() else []
    repos = cfg.get("repos")
    return {"arch": feature.path / "design" / "architecture.json", "flow": feature.path / "design" / "flow.json",
            "repos": set(repos) if isinstance(repos, dict) else None, "stories": story_ids(items) if items else None,
            "known": {r["id"] for r in items} if items else None, "out": feature.path / "work"}


# --------------------------------------------------------------------------- check


def check(src):
    arch, flow = load(src["arch"]), load(src["flow"])
    res = {"architecture": {"path": str(src["arch"] or ""), "errors": [], "warnings": []},
           "flow": {"path": str(src["flow"] or ""), "errors": [], "warnings": [], "unanswered": []}}
    a, f = res["architecture"], res["flow"]
    if arch is None:
        a["errors"].append("no architecture.json yet")
    else:
        a["errors"], a["warnings"] = diagrams.validate_architecture(arch, src["repos"])
        if not a["errors"]:
            a["warnings"] += diagrams.layout_problems(arch)[1]
    if flow is None:
        if src["flow"] is not None:
            f["errors"].append("no flow.json yet")
    else:
        f["errors"], f["warnings"] = diagrams.validate_flow(flow, arch if not a["errors"] else None,
                                                            src["stories"], src["known"])
        if not f["errors"]:
            f["unanswered"] = ["message %s (%s): %s" % (g["n"], g["say"], g["ask"]) for g in diagrams.missing(flow)]
    return arch, flow, res


def clean(res):
    return not res["architecture"]["errors"] and not res["flow"]["errors"]


def report(res):
    lines = []
    for name, r in (("High-level design", res["architecture"]), ("Flow", res["flow"])):
        if not r["path"]:
            continue
        state = "problems" if r["errors"] else "clean"
        lines.append("%s (%s): %s" % (name, r["path"], state))
        lines += ["  error: %s" % e for e in r["errors"]]
        lines += ["  warning: %s" % w for w in r["warnings"]]
        if r.get("unanswered"):
            lines.append("  %d failure answers still missing (the design build blocks on them):" % len(r["unanswered"]))
            lines += ["    %s" % u for u in r["unanswered"]]
    return "\n".join(lines)


# --------------------------------------------------------------------------- draw


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Diagrams</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700&display=swap" rel="stylesheet">
<style>
:root { --bg: #f3f6fb; --card: #fff; --ink: #0b1220; --muted: #556072; --line: #dde4ef; --blue: #1d4ed8; --bad: #b42318; --warn: #9a4b00; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.55 Inter, "Segoe UI", system-ui, sans-serif; }
main { max-width: 1320px; margin: 0 auto; padding: 28px 16px 48px; }
h1 { font: 700 26px/1.25 "Plus Jakarta Sans", Inter, sans-serif; margin: 0 0 18px; }
section { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 20px; margin: 0 0 20px; }
h2 { font: 700 19px/1.3 "Plus Jakarta Sans", Inter, sans-serif; margin: 0 0 12px; }
.pic { overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; background: #fcfdff; padding: 16px; }
.pic svg { display: block; margin: 0 auto; }
ul { margin: 12px 0 0; padding-left: 20px; color: var(--muted); }
li.e { color: var(--bad); } li.w { color: var(--warn); }
</style></head><body><main><h1>%(title)s</h1>%(body)s</main></body></html>
"""


def section(title, svg, r):
    items = ["<li class=\"e\">%s</li>" % html.escape(e) for e in r["errors"]]
    items += ["<li class=\"w\">%s</li>" % html.escape(w) for w in r["warnings"]]
    items += ["<li>Missing answer: %s</li>" % html.escape(u) for u in r.get("unanswered") or []]
    return "<section><h2>%s</h2>%s%s</section>" % (
        html.escape(title), "<div class=\"pic\">%s</div>" % svg if svg else "",
        "<ul>%s</ul>" % "".join(items) if items else "")


def draw(arch, flow, res, out):
    body = []
    a_ok = arch is not None and not res["architecture"]["errors"]
    body.append(section("High-level design", diagrams.architecture_svg(arch) if a_ok else "", res["architecture"]))
    if res["flow"]["path"]:
        f_ok = flow is not None and not res["flow"]["errors"]
        body.append(section("Main flow", diagrams.flow_svg(flow, arch if a_ok else None) if f_ok else "", res["flow"]))
    title = (arch or {}).get("title") or (flow or {}).get("title") or "Diagrams"
    out.mkdir(parents=True, exist_ok=True)
    path = out / PREVIEW
    path.write_text(PAGE % {"title": html.escape(title), "body": "".join(body)}, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- main


def main(argv=None):
    p = argparse.ArgumentParser(prog="chopchop_diagram.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("ref", nargs="?", help="feature: number, epic key or part of the name")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="check both pictures")
    g.add_argument("--draw", action="store_true", help="check, then write work/diagrams.html")
    g.add_argument("--mermaid", action="store_true", help="print the Mermaid copies")
    p.add_argument("--arch", help="an architecture.json outside a feature")
    p.add_argument("--flow", help="a flow.json outside a feature")
    p.add_argument("--out", help="where --draw writes diagrams.html when there is no feature")
    p.add_argument("--open", action="store_true", help="open diagrams.html after --draw")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="path to the _chopchop folder")
    args = p.parse_args(argv)
    try:
        src = sources(args)
        arch, flow, res = check(src)
        if args.mermaid:
            if not clean(res):
                print(report(res), file=sys.stderr)
                return 1
            print("```mermaid\n%s\n```" % diagrams.architecture_mermaid(arch))
            if flow is not None:
                print("\n```mermaid\n%s\n```" % diagrams.flow_mermaid(flow, arch))
            return 0
        if args.draw:
            path = draw(arch, flow, res, src["out"])
            res["preview"] = str(path)
            if args.open:
                webbrowser.open(path.resolve().as_uri())
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(report(res))
            if res.get("preview"):
                print("Preview: %s" % res["preview"])
        if (src["arch"] is not None and arch is None) or (src["flow"] is not None and flow is None):
            return 2
        return 0 if clean(res) else 1
    except (UsageError, ConfigError, FeatureError, OSError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
