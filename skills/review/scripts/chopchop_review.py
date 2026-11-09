#!/usr/bin/env python3
"""chopchop review: review a code change before it is committed or merged.

Usage
  chopchop_review.py --pack                    pending changes in this repo (new files too)
  chopchop_review.py --pack T02                the same, for a chopchop task: also checks the task's limits
  chopchop_review.py --pack --branch [BASE]    this branch against its base
  chopchop_review.py --pack --repo PATH        a repo other than the one you are in
  chopchop_review.py --sort FINDINGS           sort the reviewer's findings into fix, park and stop

The reviewer (the chopchop:code-reviewer agent) reads pack.md and writes findings.json next to
it. A task id needs a chopchop workspace and the code and tasks skills next to this one.
Without a task it works in any git repo and keeps its files inside .git/, so nothing shows up
in the change. Options: --feature REF, --json, --workspace PATH.

Standard library only. Python 3.8+.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
TASKS_SCRIPTS = SKILLS / "tasks" / "scripts"
CODE_SCRIPTS = SKILLS / "code" / "scripts"
if not (TASKS_SCRIPTS / "chopchoplib").is_dir():
    sys.exit("Error: review needs the tasks skill next to it (%s not found)." % TASKS_SCRIPTS)
sys.path.insert(0, str(TASKS_SCRIPTS))

from chopchoplib import review  # noqa: E402
from chopchoplib.config import ConfigError  # noqa: E402
from chopchoplib.features import FeatureError  # noqa: E402


class UsageError(Exception):
    pass


def emit(args, data, lines):
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n".join(lines))


def task_setup(args):
    """Repo, pack folders and limits for a chopchop task."""
    sys.path.insert(0, str(CODE_SCRIPTS))
    import chopchop_code
    from chopchoplib.config import find_workspace, load_config
    ws = find_workspace(args.workspace)
    cfg = load_config(ws)
    try:
        feature, task = chopchop_code.find_task(ws, args.task, args.feature)
        ctx = chopchop_code.context(ws, cfg, feature, task)
    except chopchop_code.UsageError as e:
        raise UsageError(str(e))
    repo = Path(ctx["repo_path"])
    if not ctx["repo_ok"]:
        raise UsageError("%s is not a git repo. Fix its path in chopchop.yaml." % repo)
    base = "origin/%s" % ctx["feature_branch"] if ctx["feature_branch"] else None
    extra = {"task": review.task_rules(task), "task_file": str(task.path),
             "style": [s["path"] for s in ctx["style"] if s["exists"]],
             "guides": [str(repo / g) for g in ctx["guides"]],
             "profile": ctx["profile"]["path"] if ctx["profile"]["exists"] else None}
    return repo, ctx["repo"], base, extra, lambda n: feature.path / "work" / "reviews" / ("%s-r%d" % (task.id, n))


def plain_setup(args):
    repo = review.toplevel(Path(args.repo or ".").expanduser().resolve())
    extra = {"task": None, "task_file": None, "style": [], "profile": None,
             "guides": [str(repo / g) for g in review.GUIDES if (repo / g).is_file()]}
    return repo, repo.name, None, extra, lambda n: review.git_dir(repo) / "chopchop-review" / ("r%d" % n)


def earlier(folder_of, n):
    """Parked ideas from every earlier round, and the fixes asked for in the last one."""
    parked, fixed = [], []
    for k in range(1, n):
        f = Path(folder_of(k)) / review.SORTED
        if f.is_file():
            data = json.loads(f.read_text(encoding="utf-8"))
            parked += [review.one_line(i) for i in data.get("park", [])]
            if k == n - 1:
                fixed = [review.one_line(i) for i in data.get("fix", [])]
    return sorted(set(parked)), fixed


def cmd_pack(args):
    repo, name, task_base, extra, folder_of = task_setup(args) if args.task else plain_setup(args)
    if args.branch is not None:
        base = args.branch or task_base or review.default_base(repo)
        files, diff = review.branch_changes(repo, base)
        mode = "branch"
    else:
        base, mode = None, "pending"
        files = review.pending(repo)
        diff = review.pending_diff(repo, files)
    if not files:
        print("Nothing to review: %s has no %s." % (name, "changes against %s" % base if base else "pending changes"))
        return 1
    n = review.next_round(folder_of)
    parked, fixed = earlier(folder_of, n)
    info = dict(extra, repo=name, repo_path=str(repo), mode=mode, base=base, files=files, round=n,
                parked=parked, fixed_last=fixed)
    pack = review.write_pack(folder_of(n), info, diff)
    folder = pack.parent
    data = {"pack": str(pack), "diff": str(folder / review.DIFF), "findings": str(folder / review.FINDINGS),
            "round": n, "files": files, "task": args.task}
    lines = ["Pack:     %s" % pack,
             "Diff:     %s (%d files, %d lines)" % (data["diff"], len(files), len(diff.splitlines())),
             "Findings: %s  (the reviewer writes them here)" % data["findings"],
             "Next:     start chopchop:code-reviewer with the pack, then --sort %s" % data["findings"]]
    emit(args, data, lines)
    return 0


def cmd_sort(args):
    path = Path(args.sort).expanduser().resolve()
    if path.is_dir():
        path = path / review.FINDINGS
    folder = path.parent
    info_file = folder / review.PACK_JSON
    info = json.loads(info_file.read_text(encoding="utf-8")) if info_file.is_file() else {}
    result = review.sort(review.load_findings(path), info.get("task"), [f["path"] for f in info.get("files", [])])
    (folder / review.SORTED).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = review.sort_lines(result) + ["Saved:    %s" % (folder / review.SORTED)]
    emit(args, result, lines)
    return 1 if result["stop"] else 0


def build_parser():
    p = argparse.ArgumentParser(prog="chopchop_review.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task", nargs="?", help="with --pack: a chopchop task id, e.g. T02")
    p.add_argument("--pack", action="store_true", help="write the review pack for the reviewer")
    p.add_argument("--sort", metavar="FINDINGS", help="sort the findings file into fix, park and stop")
    p.add_argument("--branch", nargs="?", const="", metavar="BASE", help="with --pack: review this branch against BASE")
    p.add_argument("--repo", metavar="PATH", help="with --pack: the repo to review (default: the one you are in)")
    p.add_argument("--feature", metavar="REF", help="feature number, epic key or name")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="path to the _chopchop folder")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.pack == bool(args.sort):
            raise UsageError("Use --pack or --sort.")
        if args.task:
            args.task = args.task.upper()
        return cmd_pack(args) if args.pack else cmd_sort(args)
    except (UsageError, review.ReviewError, ConfigError, FeatureError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
