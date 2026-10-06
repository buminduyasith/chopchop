#!/usr/bin/env python3
"""Relay requirements: pull stories from a tracker into _relay/features/<feature>/requirements/.

Commands
  init            create _relay/relay.yaml and add _relay/ to .gitignore
  doctor          check config, env vars and the tracker connection
  pull            fetch an epic and/or story ids from the tracker and sync them
  ingest          sync issues from a JSON file (used in MCP mode)
  mark-analysed   record that the agent has analysed stories (clears "needs analysis")
  features        list feature folders and their requirement status

Examples
  relay_req.py pull --epic PAY-120
  relay_req.py pull --stories PAY-121,PAY-122 --feature refund-flow
  relay_req.py pull --feature PAY-120              (re-sync from the saved source)
  relay_req.py ingest --input /tmp/issues.json --format raw --epic PAY-120 --full
  relay_req.py mark-analysed --feature PAY-120 --all

Standard library only. Python 3.8+.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relaylib import providers, schema  # noqa: E402
from relaylib.config import ConfigError, find_workspace, git_toplevel, load_config, tracker_config  # noqa: E402
from relaylib.provider_base import ProviderError  # noqa: E402
from relaylib import sync  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parents[1]


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------- helpers


def parse_ids(values):
    ids = []
    for value in values or []:
        for part in re.split(r"[\s,;]+", value.strip()):
            if not part:
                continue
            part = part.rstrip("/")
            if "://" in part:  # a pasted link: take the last path segment, drop the query
                part = part.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            if part not in ids:
                ids.append(part)
    return ids


def load_tracker(args):
    ws = find_workspace(args.workspace)
    cfg = load_config(ws)
    tracker = dict(tracker_config(cfg))
    tracker["_workspace"] = str(ws)
    return ws, cfg, tracker


def print_summary(report, rel_to=None):
    fdir = Path(report["feature_dir"])
    where = fdir
    if rel_to:
        try:
            where = fdir.relative_to(rel_to)
        except ValueError:
            pass
    lines = [
        "Feature:   %s%s" % (report["feature"], "  (new folder)" if report["created_feature"] else ""),
        "Folder:    %s" % where,
        "Source:    %s · %s" % (report["provider"], sync._describe_source(report["source"])),
        "Result:    %d new · %d changed · %d status-only · %d unchanged · %d removed" % (
            len(report["new"]), len(report["changed"]), len(report["meta"]),
            len(report["unchanged"]), len(report["removed"])),
    ]
    if report["missing"]:
        lines.append("Missing:   %s (not found in the tracker)" % ", ".join(report["missing"]))
    lines.append("Analyse:   %s" % (", ".join(report["needs_analysis"]) or "nothing, all stories are analysed"))
    for w in report.get("warnings") or []:
        lines.append("Warning:   %s" % w)
    if report["dry_run"]:
        lines.append("Dry run:   nothing was written.")
    else:
        lines.append("Report:    %s" % (where / "requirements" / "sync-report.md"))
    print("\n".join(lines))


# --------------------------------------------------------------------------- commands


def cmd_init(args):
    ws = find_workspace(args.workspace)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "features").mkdir(exist_ok=True)
    cfg_path = ws / "relay.yaml"
    if cfg_path.exists():
        print("Exists:    %s (left as is)" % cfg_path)
    else:
        template = (SKILL_DIR / "templates" / "relay.yaml").read_text(encoding="utf-8")
        cfg_path.write_text(template.replace("provider: jira", "provider: %s" % args.provider, 1), encoding="utf-8")
        print("Created:   %s" % cfg_path)

    top = git_toplevel(ws.parent)
    if top and ws.name == "_relay" and ws.parent.resolve() == top.resolve():
        gi = top / ".gitignore"
        current = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if not re.search(r"(?m)^/?_relay/?\s*$", current):
            with gi.open("a", encoding="utf-8") as fh:
                fh.write(("" if current.endswith("\n") or not current else "\n") +
                         "\n# Relay workspace (its own repo, never part of the code)\n_relay/\n")
            print("Updated:   %s (added _relay/)" % gi)
        else:
            print("Ignored:   _relay/ is already in .gitignore")
    print("\nNext: set these environment variables (never put tokens in relay.yaml):")
    print("  export RELAY_TRACKER_URL=https://yourcompany.atlassian.net")
    print("  export RELAY_TRACKER_EMAIL=you@company.com     # Jira Cloud only")
    print("  export RELAY_TRACKER_TOKEN=...                 # API token (Cloud) or PAT (Server/DC)")
    print("Then run: relay_req.py doctor")
    return 0


def cmd_doctor(args):
    ok = True
    ws = find_workspace(args.workspace)
    print("Workspace: %s%s" % (ws, "" if ws.is_dir() else "  (missing, run init)"))
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
        print("Connect:   skipped (mcp mode: the agent fetches with MCP tools, then runs ingest)")
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


def cmd_pull(args):
    ws, cfg, tracker = load_tracker(args)
    if (tracker.get("mode") or "rest") == "mcp" and not args.rest:
        raise UsageError("tracker.mode is 'mcp' in relay.yaml. Fetch with the MCP tools and run `ingest` "
                         "(see providers/%s/MCP.md), or pass --rest to use the REST API anyway." % tracker["provider"])
    if cfg["_missing_env"]:
        print("Warning:   env vars not set: %s" % ", ".join(cfg["_missing_env"]), file=sys.stderr)
    provider = providers.load(tracker, ws)

    epic_id = args.epic
    ids = parse_ids(args.stories)
    full_set = True
    if not epic_id and not ids:
        if not args.feature:
            raise UsageError("Give --epic, --stories, or --feature (to re-sync a feature from its saved source).")
        fdir = sync.resolve_feature(ws, feature=args.feature, must_exist=True)
        manifest = sync.load_manifest(fdir)
        if not manifest:
            raise UsageError("Feature '%s' has never been synced. Give --epic or --stories." % fdir.name)
        epic_id = manifest["source"].get("epic")
        ids = list(manifest["source"].get("ids") or [])
        args.feature = fdir.name
    elif ids and not epic_id:
        if not args.feature:
            raise UsageError("A list of stories needs a feature name: add --feature <name>.")
        # Only these stories are refreshed. Other stories already in the feature are left alone,
        # and the new ids are added to the feature's saved source for later re-syncs.
        full_set = False

    epic = provider.get_issue(epic_id) if epic_id else None
    fdir = sync.resolve_feature(ws, feature=args.feature, epic=epic_id,
                                epic_title=epic.get("title") if epic else None)

    issues, missing = [], []
    if epic_id:
        issues = [i for i in provider.get_epic_children(epic_id) if i["id"] != epic_id]
        if not issues:
            provider.warn("%s has no child issues. Is it an epic? For single stories use --stories." % epic_id)
        manifest = sync.load_manifest(fdir)
        if manifest:  # stories that were added to this feature by id earlier
            ids = list(dict.fromkeys(ids + list(manifest["source"].get("ids") or [])))
    have = {i["id"] for i in issues}
    todo = [k for k in ids if k not in have]
    if todo:
        found, missing = provider.get_issues(todo)
        issues.extend(found)

    report = sync.ingest(ws, fdir, epic, issues, {"epic": epic_id, "ids": parse_ids(args.stories)},
                         provider.name, fresh=args.fresh, dry_run=args.dry_run, full_set=full_set,
                         missing=missing, warnings=provider.warnings)
    output(report, args, ws)
    return 0


def cmd_ingest(args):
    ws, cfg, tracker = load_tracker(args)
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = {"issues": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("issues"), list):
        raise UsageError("--input must be a JSON list of issues, or {\"epic\": {...}, \"issues\": [...]}.")

    provider = None
    if args.format == "raw":
        provider = providers.load(tracker, ws)
        convert = provider.normalize_raw
    else:
        name = tracker.get("provider")

        def convert(item):
            return schema.normalize(item, name)

    try:
        epic = convert(raw["epic"]) if raw.get("epic") else None
        issues = [convert(i) for i in raw["issues"]]
    except (ValueError, KeyError) as e:
        raise UsageError("Bad issue in --input: %s" % e)
    epic_id = args.epic or (epic["id"] if epic else None)
    if epic and epic_id and epic["id"] != epic_id:
        raise UsageError("--epic %s does not match the epic in the file (%s)." % (epic_id, epic["id"]))
    issues = [i for i in issues if i["id"] != epic_id]
    if not epic_id and not args.feature:
        raise UsageError("Without an epic, add --feature <name>.")
    fdir = sync.resolve_feature(ws, feature=args.feature, epic=epic_id,
                                epic_title=epic.get("title") if epic else None)
    ids = parse_ids(args.stories) if args.stories else ([] if epic_id else [i["id"] for i in issues])
    report = sync.ingest(ws, fdir, epic, issues, {"epic": epic_id, "ids": ids},
                         tracker.get("provider"), fresh=args.fresh, dry_run=args.dry_run,
                         full_set=args.full, missing=parse_ids(args.missing),
                         warnings=provider.warnings if provider else [])
    output(report, args, ws)
    return 0


def cmd_mark(args):
    ws = find_workspace(args.workspace)
    fdir = sync.resolve_feature(ws, feature=args.feature, must_exist=True)
    if not args.all and not args.stories:
        raise UsageError("Give --stories A,B or --all.")
    ids = None if args.all else parse_ids(args.stories)
    done = sync.mark_analysed(fdir, ids)
    print("Marked analysed: %s" % (", ".join(done) or "nothing (already up to date)"))
    left = [m["id"] for m in sync.read_story_metas(fdir) if m.get("analysis") in ("pending", "stale")]
    print("Still to analyse: %s" % (", ".join(left) or "none"))
    return 0


def cmd_features(args):
    ws = find_workspace(args.workspace)
    root = ws / "features"
    if not root.is_dir() or not any(root.iterdir()):
        print("No features yet in %s" % root)
        return 0
    for fdir in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = sync.load_manifest(fdir) or {}
        metas = sync.read_story_metas(fdir)
        counts = {}
        for m in metas:
            counts[m.get("analysis") or "?"] = counts.get(m.get("analysis") or "?", 0) + 1
        stage = ""
        fy = fdir / "feature.yaml"
        if fy.exists():
            m = re.search(r"(?m)^stage:\s*([\w-]+)", fy.read_text(encoding="utf-8"))
            stage = m.group(1) if m else ""
        print("%-40s stage=%-13s stories=%-3d %s  last sync %s" % (
            fdir.name, stage or "?", len(metas),
            " ".join("%s=%d" % kv for kv in sorted(counts.items())) or "-",
            (manifest.get("last_sync") or "never")[:16].replace("T", " ")))
    return 0


def output(report, args, ws):
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_summary(report, rel_to=ws.parent)


# --------------------------------------------------------------------------- main


def build_parser():
    p = argparse.ArgumentParser(prog="relay_req.py", description=__doc__.split("\n")[0])
    p.add_argument("--workspace", help="path to the _relay folder (default: find it from the current folder)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create _relay/relay.yaml")
    s.add_argument("--provider", default="jira")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("doctor", help="check config and connection")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("pull", help="fetch from the tracker and sync")
    s.add_argument("--epic", help="epic id, e.g. PAY-120")
    s.add_argument("--stories", action="append", help="story ids, comma separated (repeatable)")
    s.add_argument("--feature", help="feature folder name (required for a story list)")
    s.add_argument("--fresh", action="store_true", help="rebuild story files from scratch (keep blocks survive)")
    s.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    s.add_argument("--rest", action="store_true", help="use REST even when tracker.mode is mcp")
    s.add_argument("--json", action="store_true", help="print the full report as JSON")
    s.set_defaults(func=cmd_pull)

    s = sub.add_parser("ingest", help="sync issues from a JSON file")
    s.add_argument("--input", required=True)
    s.add_argument("--format", choices=["normalized", "raw"], default="normalized",
                   help="raw = tracker payloads (e.g. from MCP), converted by the provider")
    s.add_argument("--epic")
    s.add_argument("--stories", action="append", help="ids that were requested by id (not via the epic)")
    s.add_argument("--feature")
    s.add_argument("--full", action="store_true", help="the file holds ALL of the epic's stories (enables removal detection)")
    s.add_argument("--missing", action="append", help="ids that were requested but not found")
    s.add_argument("--fresh", action="store_true")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("mark-analysed", help="clear 'needs analysis' after writing ACs")
    s.add_argument("--feature", required=True)
    s.add_argument("--stories", action="append")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_mark)

    s = sub.add_parser("features", help="list features")
    s.set_defaults(func=cmd_features)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (UsageError, ConfigError, ProviderError, ValueError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
