#!/usr/bin/env python3
"""Relay requirements: sync a tracker epic into _relay/<NNN-feature>/requirements/requirement.md.

Usage (the same words you type after /relay-requirements)
  relay_req.py PAY-120                 create 001-PAY-120-<epic-title> (or resync it if it exists)
  relay_req.py PAY-120 --name refunds  ... named 001-PAY-120-refunds
  relay_req.py -rs 1                   resync feature 001 (also: 01, PAY-120, part of the name)
  relay_req.py -rs                     resync the only feature, or list them if there are many
  relay_req.py -rs all                 resync every feature
  relay_req.py --list                  list features
  relay_req.py --init | --doctor       set up _relay/relay.yaml | check config and connection

MCP mode (the agent fetches with MCP tools instead of the REST API)
  relay_req.py --resolve 1             print the feature's epic key as JSON
  relay_req.py --ingest issues.json    sync from {"epic": {...}, "issues": [...]} (raw tracker JSON)

Options: --dry-run (write nothing), --diff (show before/after text), --json (machine-readable),
--rest (ignore mode: mcp), --workspace PATH (the _relay folder, default: found from the current folder).

Standard library only. Python 3.8+.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relaylib import features, providers, reqdoc, schema  # noqa: E402
from relaylib.config import ConfigError, find_workspace, git_toplevel, load_config, tracker_config  # noqa: E402
from relaylib.features import FeatureError  # noqa: E402
from relaylib.provider_base import ProviderError  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parents[1]


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
            lines.append("Note:     the file did not match what Relay writes (hand edits or an older layout). "
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


# --------------------------------------------------------------------------- tracker


def load_tracker(ws, need_rest, force_rest=False):
    cfg = load_config(ws)
    tracker = dict(tracker_config(cfg))
    tracker["_workspace"] = str(ws)
    if need_rest and (tracker.get("mode") or "rest") == "mcp" and not force_rest:
        raise UsageError("tracker.mode is 'mcp' in relay.yaml, so the agent fetches with MCP tools and runs "
                         "--ingest (see providers/%s/MCP.md). Add --rest to use the REST API anyway."
                         % tracker["provider"])
    if cfg["_missing_env"]:
        print("Warning:  env vars not set: %s" % ", ".join(cfg["_missing_env"]), file=sys.stderr)
    return providers.load(tracker, ws)


def fetch(provider, epic_key):
    epic = provider.get_issue(epic_key)
    stories = [s for s in provider.get_epic_children(epic_key) if s["id"] != epic_key]
    if not stories:
        provider.warn("%s has no child issues. Is it an epic?" % epic_key)
    return epic, stories


# --------------------------------------------------------------------------- commands


def cmd_sync(args, ws):
    key = features.normalize_key(args.epic)
    if not key:
        raise UsageError("'%s' does not look like an epic key (for example PAY-120)." % args.epic)
    provider = load_tracker(ws, need_rest=True, force_rest=args.rest)
    epic, stories = fetch(provider, key)
    output([sync_feature(ws, epic, stories, name=args.name, dry_run=args.dry_run,
                         warnings=provider.warnings)], args, ws)
    return 0


def cmd_resync(args, ws):
    ref = args.resync if args.resync is not None else ""
    if not ref and args.epic:
        ref = args.epic
    if ref.lower() == "all":
        targets = features.all_features(ws)
        if not targets:
            raise FeatureError("No features yet. Create one with an epic id, e.g. PAY-120.")
    else:
        targets = [features.resolve(ws, ref)]
    for t in targets:
        if not t.epic:
            raise FeatureError("%s has no epic in its requirement.md. Run it again with the epic key." % t.name)

    provider = load_tracker(ws, need_rest=True, force_rest=args.rest)
    reports, failed = [], []
    for t in targets:
        try:
            epic, stories = fetch(provider, t.epic)
            reports.append(sync_feature(ws, epic, stories, dry_run=args.dry_run, warnings=provider.warnings))
        except ProviderError as e:
            if len(targets) == 1:
                raise
            failed.append("%s (%s): %s" % (t.name, t.epic, e))
        provider.warnings = []
    output(reports, args, ws)
    for f in failed:
        print("Failed:   %s" % f, file=sys.stderr)
    return 1 if failed else 0


def cmd_ingest(args, ws):
    raw = json.loads(Path(args.ingest).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("epic"), dict) or not isinstance(raw.get("issues"), list):
        raise UsageError('--ingest needs a JSON file shaped like {"epic": {...}, "issues": [...]}.')
    cfg = load_config(ws)
    tracker = dict(tracker_config(cfg))
    tracker["_workspace"] = str(ws)
    warnings = []
    if args.format == "raw":
        provider = providers.load(tracker, ws)
        convert = provider.normalize_raw
    else:
        provider = None

        def convert(item):
            return schema.normalize(item, tracker.get("provider"))
    try:
        epic = convert(raw["epic"])
        stories = [convert(i) for i in raw["issues"]]
    except (ValueError, KeyError) as e:
        raise UsageError("Bad issue in %s: %s" % (args.ingest, e))
    if provider:
        warnings = provider.warnings
    output([sync_feature(ws, epic, stories, name=args.name, dry_run=args.dry_run, warnings=warnings)], args, ws)
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


def cmd_init(args, ws):
    ws.mkdir(parents=True, exist_ok=True)
    cfg_path = ws / "relay.yaml"
    if cfg_path.exists():
        print("Exists:   %s (left as is)" % cfg_path)
    else:
        template = (SKILL_DIR / "templates" / "relay.yaml").read_text(encoding="utf-8")
        cfg_path.write_text(template.replace("provider: jira", "provider: %s" % args.provider, 1), encoding="utf-8")
        print("Created:  %s" % cfg_path)

    top = git_toplevel(ws.parent)
    if top and ws.name == "_relay" and ws.parent.resolve() == top.resolve():
        gi = top / ".gitignore"
        current = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if not re.search(r"(?m)^/?_relay/?\s*$", current):
            with gi.open("a", encoding="utf-8") as fh:
                fh.write(("" if current.endswith("\n") or not current else "\n") +
                         "\n# Relay workspace (shared separately, never part of the code)\n_relay/\n")
            print("Updated:  %s (added _relay/)" % gi)
        else:
            print("Ignored:  _relay/ is already in .gitignore")
    print("\nNext: set these environment variables (never put tokens in relay.yaml):")
    print("  export RELAY_TRACKER_URL=https://yourcompany.atlassian.net")
    print("  export RELAY_TRACKER_EMAIL=you@company.com     # Jira Cloud only")
    print("  export RELAY_TRACKER_TOKEN=...                 # API token (Cloud) or PAT (Server/DC)")
    print("Then run: relay_req.py --doctor")
    return 0


def cmd_doctor(args, ws):
    ok = True
    print("Workspace: %s%s" % (ws, "" if ws.is_dir() else "  (missing, run --init)"))
    try:
        cfg = load_config(ws)
        tracker = dict(tracker_config(cfg))
        tracker["_workspace"] = str(ws)
    except ConfigError as e:
        print("Config:    FAIL  %s" % e)
        return 1
    print("Config:    ok    %s" % cfg["_path"])
    print("Provider:  %s (mode: %s)" % (tracker.get("provider"), tracker.get("mode") or "rest"))
    if cfg["_missing_env"]:
        ok = False
        print("Env vars:  FAIL  not set: %s" % ", ".join(cfg["_missing_env"]))
    else:
        print("Env vars:  ok")
    if (tracker.get("mode") or "rest") == "mcp":
        print("Connect:   skipped (mcp mode: the agent fetches with MCP tools, then runs --ingest)")
        return 0 if ok else 1
    try:
        provider = providers.load(tracker, ws)
        print("Connect:   ok    %s" % provider.ping())
        for w in provider.warnings:
            print("Warning:   %s" % w)
    except ProviderError as e:
        ok = False
        print("Connect:   FAIL  %s" % e)
    return 0 if ok else 1


# --------------------------------------------------------------------------- main


def build_parser():
    p = argparse.ArgumentParser(prog="relay_req.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("epic", nargs="?", help="epic key or link, e.g. PAY-120")
    p.add_argument("-rs", "--resync", nargs="?", const="", metavar="REF",
                   help="resync a feature: number, epic key, part of the name, or 'all'")
    p.add_argument("--name", help="folder name for a new feature (default: from the epic title)")
    p.add_argument("--list", action="store_true", help="list features")
    p.add_argument("--resolve", metavar="REF", help="print one feature as JSON (for MCP mode)")
    p.add_argument("--ingest", metavar="FILE", help="sync from a JSON file (for MCP mode)")
    p.add_argument("--format", choices=["raw", "normalized"], default="raw",
                   help="--ingest input: raw tracker JSON (default) or normalized (providers/SCHEMA.md)")
    p.add_argument("--init", action="store_true", help="create _relay/relay.yaml")
    p.add_argument("--provider", default="jira", help="provider for --init")
    p.add_argument("--doctor", action="store_true", help="check config, env vars and the connection")
    p.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    p.add_argument("--json", action="store_true", help="machine-readable output (always has the before/after text)")
    p.add_argument("--diff", action="store_true", help="show the before/after text of each change")
    p.add_argument("--rest", action="store_true", help="use the REST API even when tracker.mode is mcp")
    p.add_argument("--workspace", help="path to the _relay folder")
    return p


def pick_command(args):
    chosen = [name for name, on in (("init", args.init), ("doctor", args.doctor), ("list", args.list),
                                    ("resolve", args.resolve is not None), ("ingest", args.ingest is not None),
                                    ("resync", args.resync is not None)) if on]
    if len(chosen) > 1:
        raise UsageError("Use one of --%s at a time." % ", --".join(chosen))
    if chosen:
        return chosen[0]
    if args.epic:
        return "sync"
    raise UsageError("Give an epic key (PAY-120), -rs <feature>, or --list. See --help.")


COMMANDS = {"sync": cmd_sync, "resync": cmd_resync, "ingest": cmd_ingest, "list": cmd_list,
            "resolve": cmd_resolve, "init": cmd_init, "doctor": cmd_doctor}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ws = find_workspace(args.workspace)
        return COMMANDS[pick_command(args)](args, ws)
    except (UsageError, ConfigError, ProviderError, FeatureError, ValueError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
