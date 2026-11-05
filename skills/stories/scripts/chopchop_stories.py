#!/usr/bin/env python3
"""Stories: copy an epic and its stories into _chopchop/<NNN-feature>/requirements/requirement.md.

The agent gets the stories with whatever the team already has (a connected tool, a CLI, an
export, or text the user pastes), writes them as JSON in the shape of SCHEMA.md, and this
script writes the file and says what changed. It never talks to a tracker itself.

Usage
  chopchop_stories.py --ingest stories.json [--name refunds]   create the feature, or update it if the epic exists
  chopchop_stories.py -rs [<number|epic|name>|all]             which epic(s) to fetch again, as JSON
  chopchop_stories.py --resolve <ref>                          one feature as JSON
  chopchop_stories.py --list                                   all features

stories.json: {"epic": {"id": "PAY-120", "title": "..."}, "stories": [{"id": "PAY-121", ...}, ...]}

Options: --dry-run (write nothing), --diff (show before/after text), --json (machine-readable),
--workspace PATH (the _chopchop folder, default: found from the current folder).

Standard library only. Python 3.8+.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chopchoplib import features, reqdoc, schema  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace  # noqa: E402
from chopchoplib.features import FeatureError  # noqa: E402


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------- sync


def sync_feature(ws, epic, stories, name=None, dry_run=False, warnings=()):
    """Write or update requirement.md for one epic. Returns a report dict."""
    if not epic:
        raise UsageError("No epic to sync.")
    stories = [s for s in stories if s["id"] != epic["id"]]
    feature = features.find_by_epic(ws, epic["id"])
    created_folder = feature is None
    if feature:
        number, fdir = feature.number, feature.path
        if name:
            warnings = list(warnings) + ["--name ignored: %s already exists as %s." % (epic["id"], fdir.name)]
    else:
        number = features.next_number(ws)
        fdir = ws / features.folder_name(number, epic["id"], name or epic["title"])
        if fdir.exists():
            raise UsageError("Folder %s already exists but is not linked to %s." % (fdir, epic["id"]))
    path = fdir / features.REQUIREMENTS_DIR / features.REQUIREMENT_FILE

    old = reqdoc.read_existing(path)
    diff = reqdoc.compare(old, epic, stories)
    first = old is None
    synced = reqdoc.now_iso()
    old_meta = (old or {}).get("meta") or {}
    created = old_meta.get("created") or synced

    history = (old or {}).get("history") or ""
    if history.strip() == "_None yet._":
        history = ""
    if first or reqdoc.has_changes(diff):
        history = (reqdoc.history_entry(diff, first, synced[:10]) + "\n" + history).strip()
        action = "created" if first else "updated"
    else:
        # Nothing changed in the tracker. Leave the file alone unless its layout is out of date
        # or someone edited it by hand.
        same = reqdoc.render(number, epic, stories, old_meta.get("synced") or synced, created, history)
        action = "unchanged" if same == old["text"] else "rewritten"

    new_text = reqdoc.render(number, epic, stories, synced, created, history)
    if old and action == "updated":
        reqdoc.attach_details(diff, old["text"], new_text)
    if action != "unchanged" and not dry_run:
        reqdoc.write_atomic(path, new_text)

    return {
        "feature": fdir.name, "number": "%03d" % number, "path": str(path), "epic": epic["id"],
        "title": epic["title"], "action": action, "created_folder": created_folder and not dry_run,
        "dry_run": dry_run, "stories": len(stories), "last_synced": old_meta.get("synced"),
        "changes": diff, "warnings": list(warnings),
    }


def _indented(text):
    return ["          " + line for line in text.split("\n") if line.strip()]


def print_report(r, ws, details=False):
    try:
        where = Path(r["path"]).relative_to(ws.parent)
    except ValueError:
        where = r["path"]
    d = r["changes"]
    verb = {"created": "new feature", "updated": "updated", "unchanged": "no changes",
            "rewritten": "file rewritten (no tracker changes)"}[r["action"]]
    lines = ["Feature:  %s  (%s)" % (r["feature"], verb),
             "File:     %s" % where,
             "Epic:     %s %s" % (r["epic"], r["title"])]
    if r["action"] == "created":
        lines.append("Stories:  %d" % r["stories"])
    else:
        lines.append("Stories:  %d total · %d added · %d changed · %d status/details · %d removed · %d unchanged" % (
            r["stories"], len(d["added"]), len(d["changed"]), len(d["status"]), len(d["removed"]),
            len(d["unchanged"])))
        if d["epic"]:
            lines.append("Epic:     %s" % (", ".join(d["epic"]["parts"]) + " changed" if d["epic"]["parts"]
                                           else "status or details changed"))
            if details and d["epic"].get("diff"):
                lines += _indented(d["epic"]["diff"])
        for a in d["added"]:
            lines.append("Added:    %s %s" % (a["id"], a["title"]))
            if details and a.get("text"):
                lines += _indented(a["text"])
        for c in d["changed"]:
            lines.append("Changed:  %s %s (%s)" % (c["id"], c["title"], reqdoc.describe_parts(c)))
            if details and c.get("diff"):
                lines += _indented(c["diff"])
        for s in d["status"]:
            lines.append("Status:   %s %s (%s)" % (s["id"], s["title"], "%s to %s" % (s["from"], s["to"])
                                                    if "to" in s else "details"))
        for x in d["removed"]:
            lines.append("Removed:  %s %s (no longer in the epic)" % (x["id"], x["title"]))
            if details and x.get("text"):
                lines += _indented(x["text"])
        if r["action"] == "unchanged":
            lines.append("Note:     nothing changed in the tracker since %s. File left as is." %
                         (r["last_synced"] or "the last sync")[:16].replace("T", " "))
        if r["action"] == "rewritten":
            lines.append("Note:     the file did not match what chopchop writes (hand edits or an older layout). "
                         "It was rewritten. Keep notes in notes.md.")
    for w in r["warnings"]:
        lines.append("Warning:  %s" % w)
    if r["dry_run"]:
        lines.append("Dry run:  nothing was written.")
    print("\n".join(lines))


def output(reports, args, ws):
    if args.json:
        print(json.dumps(reports if len(reports) != 1 else reports[0], indent=2, ensure_ascii=False))
        return
    for i, r in enumerate(reports):
        if i:
            print()
        print_report(r, ws, details=args.diff)


# --------------------------------------------------------------------------- commands


def cmd_ingest(args, ws):
    try:
        raw = json.loads(Path(args.ingest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise UsageError("Cannot read %s: %s" % (args.ingest, e))
    stories = raw.get("stories", raw.get("issues")) if isinstance(raw, dict) else None
    if not isinstance(raw, dict) or not isinstance(raw.get("epic"), dict) or not isinstance(stories, list):
        raise UsageError('--ingest needs a JSON file shaped like {"epic": {...}, "stories": [...]}. See SCHEMA.md.')
    try:
        epic = schema.normalize(raw["epic"])
        items = [schema.normalize(i) for i in stories]
    except ValueError as e:
        raise UsageError("Bad story in %s: %s" % (args.ingest, e))
    ws.mkdir(parents=True, exist_ok=True)
    output([sync_feature(ws, epic, items, name=args.name, dry_run=args.dry_run)], args, ws)
    return 0


def target(f):
    if not f.epic:
        raise FeatureError("%s has no epic in its requirement.md, so there is nothing to fetch again." % f.name)
    items = (reqdoc.read_existing(f.file) or {}).get("items") or {}
    return {"number": "%03d" % f.number, "folder": f.name, "epic": f.epic, "title": f.meta.get("title"),
            "source": f.meta.get("source"), "from": f.meta.get("provider"), "synced": f.meta.get("synced"),
            "stories": [i for i, item in items.items() if item["kind"] != "epic" and i != f.epic]}


def cmd_resync(args, ws):
    ref = args.resync or ""
    found = features.all_features(ws) if ref.lower() == "all" else [features.resolve(ws, ref)]
    if not found:
        raise FeatureError("No features yet. Ingest an epic first.")
    rows = [target(f) for f in found]
    if args.json:
        print(json.dumps(rows if len(rows) != 1 else rows[0], indent=2, ensure_ascii=False))
        return 0
    for r in rows:
        print("Fetch:    %s %s  (feature %s, last synced %s)" % (r["epic"], r["title"] or "", r["folder"],
                                                              (r["synced"] or "never")[:10]))
        if r["source"]:
            print("From:     %s" % r["source"])
    print("Next:     get the epic and its stories again the same way, then --ingest the JSON.")
    return 0


def cmd_list(args, ws):
    found = features.all_features(ws)
    if args.json:
        print(json.dumps([f.as_dict() for f in found], indent=2, ensure_ascii=False))
        return 0
    if not found:
        print("No features yet in %s" % ws)
        return 0
    print("  No.  Epic       Folder                                           Stories, last sync")
    print(features.table(found))
    for number, names in features.duplicate_numbers(found).items():
        print("Warning:  number %03d is used by %s. Use the epic key to pick one, and renumber one folder."
              % (number, ", ".join(names)))
    return 0


def cmd_resolve(args, ws):
    print(json.dumps(features.resolve(ws, args.resolve).as_dict(), indent=2, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------- main


def build_parser():
    p = argparse.ArgumentParser(prog="chopchop_stories.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("--ingest", metavar="FILE", help="write requirement.md from a stories JSON file")
    p.add_argument("--name", help="with --ingest: folder name for a new feature (default: from the epic title)")
    p.add_argument("-rs", "--resync", nargs="?", const="", metavar="REF",
                   help="which epic(s) to fetch again: number, epic key, part of the name, or 'all'")
    p.add_argument("--resolve", metavar="REF", help="print one feature as JSON")
    p.add_argument("--list", action="store_true", help="list features")
    p.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    p.add_argument("--json", action="store_true", help="machine-readable output (always has the before/after text)")
    p.add_argument("--diff", action="store_true", help="show the before/after text of each change")
    p.add_argument("--workspace", help="path to the _chopchop folder")
    return p


def pick_command(args):
    chosen = [name for name, on in (("ingest", args.ingest is not None), ("resync", args.resync is not None),
                                    ("resolve", args.resolve is not None), ("list", args.list)) if on]
    if len(chosen) > 1:
        raise UsageError("Use one of --%s at a time." % ", --".join(chosen))
    if not chosen:
        raise UsageError("Give --ingest <file>, -rs <feature> or --list. See --help.")
    return chosen[0]


COMMANDS = {"ingest": cmd_ingest, "resync": cmd_resync, "list": cmd_list, "resolve": cmd_resolve}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ws = find_workspace(args.workspace)
        return COMMANDS[pick_command(args)](args, ws)
    except (UsageError, ConfigError, FeatureError, ValueError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
