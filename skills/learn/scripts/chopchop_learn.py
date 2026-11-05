#!/usr/bin/env python3
"""Learn: build and refresh the system map of every repo in chopchop.yaml.

Usage
  chopchop_learn.py --prepare [--repo NAME ...] [--json]   what each explorer should read, and what changed
  chopchop_learn.py --write UPDATE.json [UPDATE.json ...]  check helper updates, merge, write the map
  chopchop_learn.py --status [--json]                      how fresh the map is

The map is _chopchop/system/system-map.json, with system-map.md beside it for people.
--prepare gives each repo a mode:
  full     the map has never read it (or its commit is gone): read the whole repo
  refresh  the map read it before: read only the changed files listed
  fresh    nothing changed since the map read it: skip it
  missing  the path is not a git repo

An update covers one or more repos. See the learn skill's SCHEMA.md for its shape. The script
fills commit, owners (from CODEOWNERS), hotspots (from git log) and ADRs by itself.

Needs the tasks skill next to it. Standard library only. Python 3.8+.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_SCRIPTS = HERE.parents[1] / "tasks" / "scripts"
if not (TASKS_SCRIPTS / "chopchoplib" / "systemmap.py").is_file():
    sys.exit("Error: learn needs the tasks skill next to it (%s not found)." % TASKS_SCRIPTS)
sys.path.insert(0, str(TASKS_SCRIPTS))

from chopchoplib import systemmap  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace, load_config  # noqa: E402

WORK_DIR = "work"


class UsageError(Exception):
    pass


def repos(cfg, ws):
    raw = cfg.get("repos")
    if not isinstance(raw, dict) or not raw:
        raise UsageError("chopchop.yaml has no repos. Run /chopchop:init first.")
    out = {}
    for name, v in raw.items():
        path = Path(str((v.get("path") if isinstance(v, dict) else v) or ".")).expanduser()
        out[str(name)] = path if path.is_absolute() else (Path(ws).parent / path).resolve()
    return out


def prepare(ws, cfg, only=None):
    paths = repos(cfg, ws)
    if only:
        unknown = [r for r in only if r not in paths]
        if unknown:
            raise UsageError("Not in chopchop.yaml: %s. Repos: %s" % (", ".join(unknown), ", ".join(paths)))
    m = systemmap.load(ws) or systemmap.empty()
    work = Path(ws) / systemmap.SYSTEM_DIR / WORK_DIR
    out = []
    for name, path in paths.items():
        if only and name not in only:
            continue
        fact = systemmap.repo_facts(name, path, m["repos"].get(name))
        fact["update_file"] = str(work / ("%s.json" % name))
        out.append(fact)
    return {"workspace": str(ws), "map": str(systemmap.path_of(ws)), "map_exists": systemmap.path_of(ws).is_file(),
            "work": str(work), "repos": out,
            "to_read": [f["name"] for f in out if f["mode"] in ("full", "refresh")]}


def write(ws, cfg, files):
    paths = repos(cfg, ws)
    current = systemmap.load(ws) or systemmap.empty()
    merged, notes = current, []
    for f in files:
        try:
            update = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise UsageError("Cannot read %s: %s" % (f, e))
        errors, warnings = systemmap.validate(update, set(paths), merged)
        if errors:
            raise UsageError("%s has problems, nothing was written:\n  - %s" % (f, "\n  - ".join(errors)))
        facts = {name: systemmap.repo_facts(name, paths[name], merged["repos"].get(name))
                 for name in update.get("repos") or {}}
        merged = systemmap.merge(merged, update, facts)
        notes += ["%s: %s" % (Path(f).name, w) for w in warnings]
    path = systemmap.save(ws, merged)
    return {"map": str(path), "md": str(path.parent / systemmap.MD_FILE), "warnings": notes,
            "repos": len(merged["repos"]), "nodes": len(merged["nodes"]), "links": len(merged["links"])}


def status(ws, cfg):
    paths = repos(cfg, ws)
    m = systemmap.load(ws)
    rows = []
    for name, path in paths.items():
        known = (m or {}).get("repos", {}).get(name)
        fact = systemmap.repo_facts(name, path, known)
        rows.append({"repo": name, "mode": fact["mode"], "learned": (known or {}).get("learned"),
                     "behind": fact.get("behind"), "changed": fact.get("changed_count", 0),
                     "owners": (known or {}).get("owners") or (fact.get("owners") or {}).get("repo", [])})
    stale = [r["repo"] for r in rows if r["mode"] != "fresh"]
    return {"map_exists": m is not None, "updated": (m or {}).get("updated"), "repos": rows, "stale": stale}


def print_prepare(d):
    print("Map:      %s" % (d["map"] if d["map_exists"] else "none yet, every repo is a full read"))
    for f in d["repos"]:
        extra = ""
        if f["mode"] == "refresh":
            extra = "%d changed file(s) since %s" % (f["changed_count"], (f.get("map_commit") or "")[:7])
        elif f["mode"] == "full" and f.get("files") is not None:
            extra = "%d files (%s)" % (f["files"], ", ".join(f.get("languages") or []))
        elif f["mode"] == "missing":
            extra = "not a git repo: %s" % f["path"]
        owners = ", ".join((f.get("owners") or {}).get("repo") or []) or "no CODEOWNERS"
        print("Repo:     %-20s %-8s %s%s" % (f["name"], f["mode"], extra,
                                          "" if f["mode"] == "missing" else " · owners: %s" % owners))
    if d["to_read"]:
        print("Read:     %s (one explorer each, up to agents.max at once)" % ", ".join(d["to_read"]))
    else:
        print("Read:     nothing, the map is fresh")


def main(argv=None):
    p = argparse.ArgumentParser(prog="chopchop_learn.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("--prepare", action="store_true", help="what to read in each repo")
    p.add_argument("--write", nargs="+", metavar="UPDATE_JSON", help="merge helper updates into the map")
    p.add_argument("--status", action="store_true", help="how fresh the map is")
    p.add_argument("--repo", action="append", help="only this repo (with --prepare); can repeat")
    p.add_argument("--workspace", help="the _chopchop folder (default: found from here)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)
    ws = find_workspace(args.workspace)
    try:
        cfg = load_config(ws)
        if args.prepare:
            d = prepare(ws, cfg, args.repo)
            print(json.dumps(d, indent=2)) if args.json else print_prepare(d)
        elif args.write:
            d = write(ws, cfg, args.write)
            if args.json:
                print(json.dumps(d, indent=2))
            else:
                print("Map:      %s (%d repos, %d parts, %d links)" % (d["map"], d["repos"], d["nodes"], d["links"]))
                print("Read it:  %s" % d["md"])
                for w in d["warnings"]:
                    print("Warning:  %s" % w)
        elif args.status:
            d = status(ws, cfg)
            if args.json:
                print(json.dumps(d, indent=2))
            else:
                print("Map:      %s" % ("updated %s" % d["updated"] if d["map_exists"] else "none yet. Run /chopchop:learn."))
                for r in d["repos"]:
                    print("Repo:     %-20s %-8s%s" % (r["repo"], r["mode"],
                                                     " (%d commits behind, %d files changed)" % (r["behind"] or 0, r["changed"])
                                                     if r["mode"] == "refresh" else ""))
        else:
            raise UsageError("Use --prepare, --write or --status. See --help.")
    except (UsageError, ConfigError, ValueError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
