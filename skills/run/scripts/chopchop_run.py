#!/usr/bin/env python3
"""Run: the one command. Find or start a feature, say where it stands and what comes next.

Usage
  chopchop_run.py --where ["text"] [--json] [--no-dashboard]   what the text is, and the next step
  chopchop_run.py --list [--json]                              every feature and who it waits for
  chopchop_run.py --approve REF brief|design|spec --by "Name" [--result approved|conditions|changes] [--note "..."]

"text" can be a feature (number, epic key, part of its name), a tracker key or link that is not
here yet, or an idea in plain words. With no text: the only feature, or the list.

A feature moves through 8 steps: groom, brief, design, spec, tasks, build, review, done.
People decide at three of them: the brief (you), the design (the lead), the spec (you).
This script only reads the files and says where things stand. The skills do the work.

--where also starts the dashboard, unless chopchop.yaml says `dashboard: {auto: false}`.

Needs the tasks skill next to it. Standard library only. Python 3.8+.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
TASKS = SKILLS / "tasks"
if not (TASKS / "scripts" / "chopchoplib" / "stage.py").is_file():
    sys.exit("Error: run needs the tasks skill next to it (%s not found)." % TASKS)
sys.path.insert(0, str(TASKS / "scripts"))

from chopchoplib import events, features, stage  # noqa: E402
from chopchoplib.config import CONFIG_FILE, ConfigError, find_workspace, load_config  # noqa: E402
from chopchoplib.features import FeatureError  # noqa: E402

DASHBOARD = SKILLS / "dashboard" / "scripts" / "chopchop_dashboard.py"
SCRIPTS = {"brief": SKILLS / "groom" / "scripts" / "chopchop_groom.py",
           "design": SKILLS / "design" / "scripts" / "chopchop_design.py",
           "spec": SKILLS / "spec" / "scripts" / "chopchop_spec.py"}
RESULTS = ["approved", "conditions", "changes"]
ORDER = {"you": 0, "lead": 1, "ba": 2, "chopchop": 3, "reviewers": 4, None: 5}
SHORT_NAME_WORDS = 3


class UsageError(Exception):
    pass


def emit(args, data, lines):
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n".join(lines))


# --------------------------------------------------------------------------- what is the text


def strip_flags(text):
    """The words the user typed, without the flags a skill reads (--auto and friends)."""
    flags = re.findall(r"(?<!\S)--[a-z][\w-]*", text or "")
    clean = re.sub(r"(?<!\S)--[a-z][\w-]*", " ", text or "")
    return re.sub(r"\s+", " ", clean).strip().strip("\"'"), flags


def classify(ws, text):
    """Returns {"kind": feature|epic|idea|list|empty|choose, ...}."""
    found = features.all_features(ws)
    if not text:
        if not found:
            return {"kind": "empty"}
        if len(found) == 1:
            return {"kind": "feature", "feature": found[0]}
        return {"kind": "list", "features": found}

    key = features.normalize_key(text)
    if key:
        hit = features.find_by_epic(ws, key)
        if hit:
            return {"kind": "feature", "feature": hit}
        return {"kind": "epic", "key": key, "source": text}
    if "://" in text:
        return {"kind": "epic", "key": None, "source": text}
    if text.isdigit():
        hits = [f for f in found if f.number == int(text)]
        if hits:
            return {"kind": "feature", "feature": hits[0]}
        raise UsageError("No feature number %s. Use --list to see them, or give a tracker key or an idea." % text)

    exact = [f for f in found if f.name.lower() == text.lower()]
    if exact:
        return {"kind": "feature", "feature": exact[0]}
    # A few words that name one feature mean that feature. A sentence is a new idea.
    if len(text.split()) <= SHORT_NAME_WORDS:
        low = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        hits = [f for f in found if low and (low in f.name.lower() or
                                             low in re.sub(r"[^a-z0-9]+", "-", str(f.meta.get("title") or "").lower()))]
        if len(hits) == 1:
            return {"kind": "feature", "feature": hits[0]}
        if len(hits) > 1:
            return {"kind": "choose", "features": hits, "text": text}
        if len(text.split()) == 1:
            raise UsageError("'%s' is not a feature, a tracker key or a link. To start from an idea, say it in a "
                             "few words, for example: let customers ask for a refund." % text)
    return {"kind": "idea", "text": text}


# --------------------------------------------------------------------------- dashboard


def dashboard(ws, cfg, off=False):
    """Start the dashboard if it is not running. Returns its URL, or None. Never fails the command."""
    conf = cfg.get("dashboard") if isinstance(cfg.get("dashboard"), dict) else {}
    if off or conf.get("auto") is False or not DASHBOARD.is_file():
        return None
    base = [sys.executable, str(DASHBOARD), "--workspace", str(ws), "--json"]
    try:
        out = subprocess.run(base + ["--status"], capture_output=True, text=True, timeout=20)
        data = json.loads(out.stdout) if out.stdout.strip().startswith("{") else {}
        if data.get("running") and data.get("url"):
            return data["url"]
        cmd = base + ["--start"]
        if conf.get("open") is False:
            cmd.append("--no-open")
        if conf.get("port"):
            cmd += ["--port", str(conf["port"])]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        data = json.loads(out.stdout) if out.stdout.strip().startswith("{") else {}
        return data.get("url")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------------- where


def feature_view(feature, url):
    st = stage.read(feature)
    n = stage.STAGES.index(st["stage"]) + 1
    nxt = st.get("next") or {}
    lines = ["Kind:     feature",
             "Feature:  %s" % stage.line(st),
             "Step:     %s (%d of %d)" % (st["stage"], n, len(stage.STAGES))]
    if st["waiting_on"]:
        lines.append("Waiting:  on %s. %s" % (st["waiting_who"], st["waiting"]))
    gate = st["stage"] if st["stage"] in stage.GATES and st["waiting_on"] in ("you", "lead") else None
    if gate:
        lines.append("Gate:     a person must %s. When they say yes: --approve %d %s --by \"Name\"" % (
            nxt.get("say") or "approve the %s" % gate, feature.number, gate))
        lines.append("Read:     %s" % st["docs"].get(gate, ""))
    elif st["waiting_on"] == "ba":
        lines.append("Next:     the groom skill with `%d` shows the BA questions. Go on when the answers are in." % feature.number)
    elif nxt.get("skill"):
        lines.append("Next:     the %s skill with `%s`" % (nxt["skill"], nxt["args"]))
    else:
        lines.append("Next:     nothing. This feature is done.")
    if url:
        lines.append("Dashboard: %s#/f/%s" % (url.rstrip("/") + "/", quote(feature.name)))
    data = dict(st, kind="feature", gate=gate, dashboard=url,
                link="%s#/f/%s" % (url.rstrip("/") + "/", quote(feature.name)) if url else None)
    return data, lines


def cmd_where(args, ws):
    if not (ws / CONFIG_FILE).is_file():
        emit(args, {"kind": "setup", "workspace": str(ws)},
             ["Kind:     setup", "Setup:    no %s in %s yet." % (CONFIG_FILE, ws),
              "Next:     the init skill first, then run again with the same words"])
        return 0
    cfg = load_config(ws)
    text, flags = strip_flags(args.where or "")
    found = classify(ws, text)
    url = dashboard(ws, cfg, off=args.no_dashboard)
    kind = found["kind"]
    if kind == "feature":
        data, lines = feature_view(found["feature"], url)
        data["flags"] = flags
        emit(args, data, lines)
        return 0
    extra = ["Dashboard: %s" % url] if url else []
    if kind == "empty":
        emit(args, {"kind": kind, "dashboard": url},
             ["Kind:     empty", "Features: none yet.",
              "Next:     ask the user for a tracker key or an idea, then the groom skill with it"] + extra)
    elif kind == "epic":
        emit(args, {"kind": kind, "key": found["key"], "source": found["source"], "flags": flags, "dashboard": url},
             ["Kind:     new epic", "Epic:     %s (not here yet)" % (found["key"] or found["source"]),
              "Next:     the groom skill with `%s`" % found["source"]] + extra)
    elif kind == "idea":
        emit(args, {"kind": kind, "text": found["text"], "flags": flags, "dashboard": url},
             ["Kind:     new idea", "Idea:     %s" % found["text"],
              "Next:     the groom skill with the idea, word for word"] + extra)
    else:
        rows = sorted((stage.read(f) for f in found["features"]),
                      key=lambda s: (ORDER.get(s["waiting_on"], 5), s["number"]))
        head = "Which feature?" if kind == "list" else "'%s' fits more than one feature. Which one?" % found["text"]
        emit(args, {"kind": kind, "features": rows, "dashboard": url},
             ["Kind:     %s" % kind, head] + ["  " + stage.line(s) for s in rows] +
             ["Next:     ask the user which one, then --where <number>"] + extra)
    return 0


def cmd_list(args, ws):
    rows = sorted((stage.read(f) for f in features.all_features(ws)),
                  key=lambda s: (ORDER.get(s["waiting_on"], 5), s["number"]))
    lines = ["Features: %d" % len(rows)] + ["  " + stage.line(s) for s in rows]
    if not rows:
        lines = ["Features: none yet. Start one with a tracker key or an idea."]
    emit(args, {"features": rows}, lines)
    return 0


# --------------------------------------------------------------------------- approve


def cmd_approve(args, ws):
    ref, what = args.approve
    what = what.lower()
    if what not in SCRIPTS:
        raise UsageError("Approve what? One of: brief, design, spec.")
    name = (args.by or "").strip()
    if not name:
        raise UsageError("Who approves? Add --by \"Name\". A person decides, never chopchop.")
    feature = features.resolve(ws, ref)
    script = SCRIPTS[what]
    if not script.is_file():
        raise UsageError("The %s skill is not installed next to run (%s)." % (what, script))
    cmd = [sys.executable, str(script), str(feature.number), "--approve", name, "--workspace", str(ws)]
    if what == "design":
        result = (args.result or "approved").lower()
        if result not in RESULTS:
            raise UsageError("--result must be one of %s" % ", ".join(RESULTS))
        cmd += ["--result", result]
    elif args.result and args.result.lower() != "approved":
        raise UsageError("Only the design takes --result. For the %s: change it, then approve." % what)
    for note in args.note or []:
        cmd += ["--note", note]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.stdout.strip():
        print(out.stdout.rstrip("\n"))
    if out.returncode != 0:
        print(out.stderr.rstrip("\n") or "Error: the %s could not be approved." % what, file=sys.stderr)
        return out.returncode
    st = stage.read(features.resolve(ws, str(feature.number)))
    events.log(feature, "run", "Now at %s" % st["label"].lower())
    print("Now:      %s" % stage.line(st))
    return 0


# --------------------------------------------------------------------------- main


def build_parser():
    p = argparse.ArgumentParser(prog="chopchop_run.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("--where", nargs="?", const="", metavar="TEXT", help="a feature, a tracker key or link, or an idea")
    p.add_argument("--list", action="store_true", help="every feature and who it waits for")
    p.add_argument("--approve", nargs=2, metavar=("REF", "WHAT"), help="a person approves: brief, design or spec")
    p.add_argument("--by", help="with --approve: who approves")
    p.add_argument("--result", help="with --approve design: approved, conditions or changes")
    p.add_argument("--note", action="append", help="with --approve: a condition or a change needed; can repeat")
    p.add_argument("--no-dashboard", dest="no_dashboard", action="store_true", help="do not start the dashboard")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="the _chopchop folder (default: found from here)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    ws = find_workspace(args.workspace)
    try:
        if args.approve:
            return cmd_approve(args, ws)
        if args.list:
            return cmd_list(args, ws)
        return cmd_where(args, ws)
    except (UsageError, FeatureError, ConfigError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
