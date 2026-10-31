#!/usr/bin/env python3
"""Relay tasks: cut a design into small tasks and track them in _relay/<NNN-feature>/tasks/.

Usage (the same words you type after /relay-tasks)
  relay_tasks.py --new design.md specs/ --name refunds   new feature 00N-refunds, design copied in
  relay_tasks.py --new design.md --feature 1             add or refresh the design of feature 001
  relay_tasks.py --check 1                               check the task files, refresh plan and board
  relay_tasks.py --branch 1                              show the feature branch Relay suggests
  relay_tasks.py --branch 1 --create                     create it in every repo the tasks use, and push
  relay_tasks.py --status 1 [--open]                     write status.md and board.html (and open it)
  relay_tasks.py --set T02 in-review --feature 1 [--owner dev-b] [--pr URL]
  relay_tasks.py --list                                  list features and their tasks
  relay_tasks.py --init --base dev [--repo api=../api]   create _relay/relay.yaml
  relay_tasks.py --base dev | --repo api=../api          save the base branch or a repo in relay.yaml

A feature is a number (1, 001), an epic key (PAY-120) or part of the folder name. With only one
feature you can leave it out. Options: --json (machine-readable), --workspace PATH (the _relay folder).

Standard library only. Python 3.8+.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from relaylib import board, features, gitops, tasks  # noqa: E402
from relaylib.config import ConfigError, find_workspace, git_toplevel, load_config  # noqa: E402
from relaylib.features import FeatureError, parse_front_matter, render_front_matter  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parents[1]
SOURCES_FILE = "SOURCES.md"


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------- config


def load_cfg(ws):
    try:
        return load_config(ws)
    except ConfigError:
        if (Path(ws) / "relay.yaml").exists():
            raise
        return {}


def repos_of(cfg, ws):
    """{name: path} from relay.yaml. Falls back to the repo that holds _relay/.

    A repo is either `name: path` or a map with `path:`."""
    repos = cfg.get("repos")
    if isinstance(repos, dict) and repos:
        return {str(k): str((v.get("path") if isinstance(v, dict) else v) or ".") for k, v in repos.items()}, True
    top = git_toplevel(Path(ws).parent) or Path(ws).parent
    return {Path(top).name: "."}, False


def repo_dir(ws, path):
    p = Path(path).expanduser()
    return p if p.is_absolute() else (Path(ws).parent / p).resolve()


def set_scalar(cfg_path, key, value):
    text = cfg_path.read_text(encoding="utf-8")
    line = "%s: %s" % (key, value)
    if re.search(r"(?m)^%s\s*:.*$" % re.escape(key), text):
        text = re.sub(r"(?m)^%s\s*:.*$" % re.escape(key), lambda m: line, text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n" + line + "\n"
    cfg_path.write_text(text, encoding="utf-8")


def set_repo(cfg_path, name, path):
    lines = cfg_path.read_text(encoding="utf-8").split("\n")
    entry = "  %s: %s" % (name, path)
    head = next((i for i, l in enumerate(lines) if re.match(r"^repos\s*:", l)), None)
    if head is None:
        lines = [l for l in lines]
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "repos:", entry, ""]
    else:
        lines[head] = "repos:"
        end = head + 1
        while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
            end += 1
        while end > head + 1 and not lines[end - 1].strip():
            end -= 1
        hit = next((i for i in range(head + 1, end)
                    if re.match(r"^\s+%s\s*:" % re.escape(name), lines[i])), None)
        if hit is not None:
            if not lines[hit].split(":", 1)[1].strip():
                raise UsageError("repos.%s has more settings than a path. Edit it in relay.yaml by hand." % name)
            lines[hit] = entry
        else:
            lines.insert(end, entry)
    cfg_path.write_text("\n".join(lines), encoding="utf-8")


def parse_repo_args(values):
    out = []
    for v in values or []:
        if "=" not in v:
            raise UsageError("--repo needs name=path, for example payments-api=../payments-api")
        name, path = v.split("=", 1)
        if not re.match(r"^[A-Za-z0-9_.-]+$", name.strip()):
            raise UsageError("Repo name '%s' may only use letters, numbers, dot, dash and underscore." % name)
        out.append((name.strip(), path.strip() or "."))
    return out


# --------------------------------------------------------------------------- feature files


def tasks_dir(feature):
    return feature.path / tasks.TASKS_DIR


def read_plan(feature, cfg):
    path = tasks_dir(feature) / tasks.PLAN_FILE
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    meta, _ = parse_front_matter(text)
    meta.setdefault("feature", feature.name)
    meta.setdefault("feature_branch", None)
    return meta, text


def read_sources(feature):
    path = feature.path / tasks.DESIGN_DIR / SOURCES_FILE
    meta = features.read_front_matter(path)
    return meta.get("files") or []


def write_sources(feature, files):
    lines = [render_front_matter({"files": files}).rstrip(), "",
             "# Design sources", "",
             "_Written by Relay. These files are copies. Change the original, then run "
             "`/relay-tasks --new <files> --feature %03d` again._" % feature.number, "",
             "| File | Copied from | Copied at |", "| --- | --- | --- |"]
    for f in files:
        lines.append("| [%s](%s) | `%s` | %s |" % (f["file"], f["file"], f["from"], f["copied"][:16].replace("T", " ")))
    path = feature.path / tasks.DESIGN_DIR / SOURCES_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def collect_inputs(inputs):
    """[(source path, name inside design/)]. Folders keep their inner layout."""
    pairs = []
    for raw in inputs:
        src = Path(raw).expanduser().resolve()
        if src.is_file():
            pairs.append((src, src.name))
        elif src.is_dir():
            for f in sorted(src.rglob("*")):
                rel = f.relative_to(src)
                if f.is_file() and not any(part.startswith(".") for part in rel.parts):
                    pairs.append((f, rel.as_posix()))
        else:
            raise UsageError("Design input not found: %s" % raw)
    seen = {}
    for src, name in pairs:
        if name == SOURCES_FILE:
            raise UsageError("%s uses the name %s, which Relay keeps for itself. Rename it." % (src, name))
        if name in seen and seen[name] != src:
            raise UsageError("Two inputs would both be copied as design/%s:\n  %s\n  %s\nRename one."
                             % (name, seen[name], src))
        seen[name] = src
    if not pairs:
        raise UsageError("No design files found in: %s" % ", ".join(inputs))
    return list(dict(((n, (s, n)) for s, n in pairs)).values())


def copy_design(feature, inputs):
    design = feature.path / tasks.DESIGN_DIR
    design.mkdir(parents=True, exist_ok=True)
    known = {f["file"]: f for f in read_sources(feature)}
    report = []
    for src, name in collect_inputs(inputs):
        target = design / name
        digest = sha(src)
        old = known.get(name)
        if target.exists() and target.resolve() == src:
            status = "unchanged"
        elif target.exists() and sha(target) == digest:
            status = "unchanged"
        else:
            status = "changed" if target.exists() else "added"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(src), str(target))
        if status != "unchanged" or not old:
            known[name] = {"file": name, "from": str(src), "sha256": digest, "copied": board.now()}
        report.append({"file": name, "from": str(src), "status": status})
    write_sources(feature, sorted(known.values(), key=lambda f: f["file"]))
    return report


def ensure_tasks_dir(feature):
    d = tasks_dir(feature)
    d.mkdir(parents=True, exist_ok=True)
    log = d / tasks.CHANGELOG_FILE
    if not log.exists():
        log.write_text(tasks.CHANGELOG_TEMPLATE.format(feature=feature.name), encoding="utf-8")
    return d


def refresh(ws, feature, cfg):
    """Rewrite the parts Relay owns: ## Branch in each task, plan.md, status.md, board.html."""
    d = ensure_tasks_dir(feature)
    found = tasks.load_tasks(d)
    plan_meta, plan_text = read_plan(feature, cfg)
    repos, _ = repos_of(cfg, ws)
    patterns = cfg.get("branches") if isinstance(cfg.get("branches"), dict) else None
    fbranch = plan_meta.get("feature_branch")
    branches = {}
    for t in found:
        branch = tasks.task_branch_name(feature, t, patterns)
        branches[t.id] = branch
        section = tasks.branch_section(t, fbranch, branch, repos.get(t.get("repo"), None))
        t.body = tasks.replace_section(t.body, "Branch", section)
        t.save()

    base = plan_meta.get("base_branch") or cfg.get("base_branch")
    board.write_if_changed(d / tasks.PLAN_FILE, board.render_plan(
        feature, found, plan_meta, read_sources(feature), board.read_notes(plan_text), base))
    board.write_if_changed(d / tasks.STATUS_FILE, board.render_status(feature, found))
    template = (SKILL_DIR / "templates" / "board.html").read_text(encoding="utf-8")
    changelog = tasks.read_changelog(d / tasks.CHANGELOG_FILE)
    data = board.board_data(feature, found, plan_meta, changelog, branches, base)
    (d / tasks.BOARD_FILE).write_text(board.render_board(template, data), encoding="utf-8")
    return found, plan_meta


def rel(ws, path):
    try:
        return str(Path(path).relative_to(Path(ws).parent))
    except ValueError:
        return str(path)


def emit(args, data, lines):
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("\n".join(lines))


# --------------------------------------------------------------------------- commands


def cmd_new(args, ws):
    cfg = load_cfg(ws)
    if args.feature is not None and args.name:
        raise UsageError("Use --feature for an existing feature or --name for a new one, not both.")
    created = False
    if args.feature is not None:
        feature = features.resolve(ws, args.feature)
    elif args.name:
        epic = features.normalize_key(args.epic) if args.epic else None
        if args.epic and not epic:
            raise UsageError("'%s' does not look like an epic key (for example PAY-120)." % args.epic)
        if epic and features.find_by_epic(ws, epic):
            raise UsageError("Epic %s already has a folder. Use --feature %s." % (epic, epic))
        number = features.next_number(ws)
        name = (features.folder_name(number, epic, args.name) if epic
                else "%03d-%s" % (number, features.slugify(args.name)))
        if name.endswith("-"):
            raise UsageError("--name '%s' has no letters or numbers to use." % args.name)
        path = Path(ws) / name
        path.mkdir(parents=True)
        feature = features.Feature(path)
        created = True
    else:
        raise UsageError("Say which feature: --feature <number|epic|name> for an existing one, or "
                         "--name <short-name> for a new one. Run --list to see features.")

    report = copy_design(feature, args.new)
    ensure_tasks_dir(feature)
    plan_meta, _ = read_plan(feature, cfg)
    if created:
        plan_meta["title"] = args.name
        if epic:
            plan_meta["epic"] = epic
    plan_path = tasks_dir(feature) / tasks.PLAN_FILE
    if created or not plan_path.exists():
        plan_path.write_text(render_front_matter(plan_meta), encoding="utf-8")
    found, plan_meta = refresh(ws, feature, cfg)
    repos, configured = repos_of(cfg, ws)
    has_req = feature.file.exists()

    data = {"feature": feature.name, "created": created, "path": str(feature.path),
            "design": report, "design_dir": str(feature.path / tasks.DESIGN_DIR),
            "tasks_dir": str(tasks_dir(feature)), "tasks": len(found),
            "requirement": str(feature.file) if has_req else None,
            "base_branch": cfg.get("base_branch"), "repos": repos, "repos_configured": configured,
            "config": bool(cfg)}
    lines = ["Feature:  %s (%s)" % (feature.name, "new" if created else "existing")]
    for r in report:
        lines.append("Design:   %s/%s (%s)" % (tasks.DESIGN_DIR, r["file"], r["status"]))
    lines.append("Story:    %s" % (rel(ws, feature.file) if has_req else "no requirement.md (design only)"))
    lines.append("Tasks:    %s (%d task files)" % (rel(ws, tasks_dir(feature)), len(found)))
    lines.append("Base:     %s" % (cfg.get("base_branch") or "NOT SET. Ask the user, then run --base <branch>"))
    lines.append("Repos:    %s%s" % (", ".join("%s = %s" % kv for kv in repos.items()),
                                     "" if configured else "  (a guess. Confirm with the user, then run --repo name=path)"))
    if not cfg:
        lines.append("Config:   no relay.yaml yet. Run --init --base <branch>")
    changed = [r["file"] for r in report if r["status"] == "changed"]
    if changed and found:
        lines.append("Changed:  %s changed since the tasks were cut. Check which tasks it affects."
                     % ", ".join(changed))
    emit(args, data, lines)
    return 0


def cmd_check(args, ws):
    cfg = load_cfg(ws)
    feature = features.resolve(ws, args.check)
    found, _ = refresh(ws, feature, cfg)
    repos, configured = repos_of(cfg, ws)
    errors, warnings = tasks.check(found, list(repos) if configured else None)
    if not found:
        errors.append("No task files yet in %s" % rel(ws, tasks_dir(feature)))
    waves = sorted({t.get("wave") for t in found if isinstance(t.get("wave"), int)})
    data = {"feature": feature.name, "ok": not errors, "tasks": len(found), "waves": waves,
            "repos": sorted({str(t.get("repo")) for t in found if t.get("repo")}),
            "errors": errors, "warnings": warnings}
    lines = ["Check:    %s · %d tasks · waves %s · repos %s" % (
        feature.name, len(found), ", ".join(map(str, waves)) or "-", ", ".join(data["repos"]) or "-")]
    lines += ["Error:    %s" % e for e in errors]
    lines += ["Warning:  %s" % w for w in warnings]
    lines.append("Result:   %s" % ("OK" if not errors else "%d error(s). Fix the task files and run --check again."
                                   % len(errors)))
    emit(args, data, lines)
    return 0 if not errors else 1


def cmd_branch(args, ws):
    cfg = load_cfg(ws)
    feature = features.resolve(ws, args.branch)
    plan_meta, _ = read_plan(feature, cfg)
    base = args.base or plan_meta.get("base_branch") or cfg.get("base_branch")
    if not base:
        raise UsageError("Base branch is not set. Ask the user which branch they work from (for example "
                         "dev), then run --base <branch>.")
    patterns = cfg.get("branches") if isinstance(cfg.get("branches"), dict) else None
    current = plan_meta.get("feature_branch")
    name = args.branch_name or current or tasks.feature_branch_name(feature, patterns)
    if current and args.branch_name and args.branch_name != current:
        raise UsageError("This feature already uses %s. Relay does not rename it." % current)

    repos, configured = repos_of(cfg, ws)
    found = tasks.load_tasks(tasks_dir(feature))
    used = sorted({str(t.get("repo")) for t in found if t.get("repo")}) or sorted(repos)
    unknown = [r for r in used if r not in repos]
    if unknown:
        raise UsageError("Tasks use repos that are not in relay.yaml: %s. Add them with --repo name=path."
                         % ", ".join(unknown))
    problem = gitops.safe_name(name, base)
    if problem:
        raise UsageError(problem)

    results = []
    for r in used:
        path = repo_dir(ws, repos[r])
        if args.create:
            res = gitops.create_branch(path, name, base, push=not args.no_push)
        else:
            exists = gitops.is_repo(path) and (gitops.local_branch_exists(path, name) or
                                               (gitops.has_remote(path) and gitops.remote_branch_exists(path, name)))
            res = {"status": "exists" if exists else "planned",
                   "message": "already there" if exists else
                   ("will be created from origin/%s and pushed" % base if gitops.is_repo(path)
                    else "%s is not a git repo" % path)}
        res.update({"repo": r, "path": str(path)})
        results.append(res)

    ok = all(r["status"] != "failed" for r in results)
    if args.create and any(r["status"] in ("created", "exists") for r in results):
        plan_meta["base_branch"] = base
        plan_meta["feature_branch"] = name
        plan_meta["branch_repos"] = sorted(set(plan_meta.get("branch_repos") or []) |
                                           {r["repo"] for r in results if r["status"] in ("created", "exists")})
        plan_path = tasks_dir(feature) / tasks.PLAN_FILE
        _, text = read_plan(feature, cfg)
        _, body = parse_front_matter(text)
        tasks_dir(feature).mkdir(parents=True, exist_ok=True)
        plan_path.write_text(render_front_matter(plan_meta) + body, encoding="utf-8")
        refresh(ws, feature, cfg)

    data = {"feature": feature.name, "branch": name, "base": base, "created": bool(args.create),
            "ok": ok, "repos": results, "repos_configured": configured}
    lines = ["Feature:  %s" % feature.name,
             "Branch:   %s (from %s)" % (name, base)]
    for r in results:
        lines.append("Repo:     %-20s %-8s %s" % (r["repo"], r["status"], r["message"]))
    if not args.create:
        lines.append("Next:     ask the user to approve this name, then run --branch %03d --create" % feature.number)
    elif ok:
        lines.append("Done:     every task file now shows how to cut its branch from %s." % name)
    emit(args, data, lines)
    return 0 if ok else 1


def cmd_status(args, ws):
    cfg = load_cfg(ws)
    feature = features.resolve(ws, args.status)
    found, plan_meta = refresh(ws, feature, cfg)
    by_id = {t.id: t for t in found}
    path = tasks_dir(feature) / tasks.BOARD_FILE
    columns = {s: [t for t in found if t.get("status") == s] for s in tasks.STATUSES}
    data = {"feature": feature.name, "board": str(path), "status_md": str(tasks_dir(feature) / tasks.STATUS_FILE),
            "feature_branch": plan_meta.get("feature_branch"),
            "columns": {s: [{"id": t.id, "title": t.get("title"), "owner": t.get("owner"),
                             "waiting_on": tasks.waiting_on(t, by_id)} for t in ts] for s, ts in columns.items()}}
    lines = ["Feature:  %s · %d tasks · %d done" % (feature.name, len(found), len(columns["done"]))]
    for s in tasks.STATUSES:
        items = ["%s%s" % (t.id, " (waiting on %s)" % ", ".join(tasks.waiting_on(t, by_id))
                           if s == "todo" and tasks.waiting_on(t, by_id) else "") for t in columns[s]]
        lines.append("%-13s%s" % (tasks.STATUS_TITLES[s] + ":", ", ".join(items) or "-"))
    lines.append("Board:       %s" % rel(ws, path))
    emit(args, data, lines)
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


def cmd_set(args, ws):
    task_id, status = args.set
    task_id = task_id.upper()
    if status not in tasks.STATUSES:
        raise UsageError("Status must be one of: %s" % ", ".join(tasks.STATUSES))
    cfg = load_cfg(ws)
    feature = features.resolve(ws, args.feature or "")
    found = tasks.load_tasks(tasks_dir(feature))
    hit = [t for t in found if t.id == task_id]
    if not hit:
        raise UsageError("No task %s in %s. Tasks: %s" % (task_id, feature.name, ", ".join(t.id for t in found) or "none"))
    t = hit[0]
    old = t.get("status")
    t.meta["status"] = status
    if args.owner is not None:
        t.meta["owner"] = args.owner or None
    if args.pr is not None:
        t.meta["pr"] = args.pr or None
    t.save()
    refresh(ws, feature, cfg)
    by_id = {x.id: x for x in tasks.load_tasks(tasks_dir(feature))}
    waiting = tasks.waiting_on(by_id[task_id], by_id)
    data = {"feature": feature.name, "task": task_id, "from": old, "to": status, "waiting_on": waiting}
    lines = ["Task:     %s %s: %s -> %s" % (task_id, t.get("title"), old, status)]
    if status == "in-progress" and waiting:
        lines.append("Warning:  still waiting on %s" % ", ".join(waiting))
    emit(args, data, lines)
    return 0


def cmd_list(args, ws):
    rows = []
    for f in features.all_features(ws):
        found = tasks.load_tasks(tasks_dir(f))
        rows.append({"number": "%03d" % f.number, "folder": f.name, "epic": f.epic, "tasks": len(found),
                     "done": sum(1 for t in found if t.get("status") == "done")})
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("No features yet in %s" % ws)
        return 0
    print("  No.  Epic       Folder                                           Tasks")
    for r in rows:
        print("  %s  %-10s %-48s %s" % (r["number"], r["epic"] or "-", r["folder"],
                                       "%d (%d done)" % (r["tasks"], r["done"]) if r["tasks"] else "none yet"))
    return 0


def cmd_config(args, ws):
    cfg_path = Path(ws) / "relay.yaml"
    lines = []
    if args.init:
        ws.mkdir(parents=True, exist_ok=True)
        if cfg_path.exists():
            lines.append("Exists:   %s (left as is)" % cfg_path)
        else:
            top = git_toplevel(Path(ws).parent) or Path(ws).parent
            text = (SKILL_DIR / "templates" / "relay.yaml").read_text(encoding="utf-8")
            if args.repo:
                text = text.replace("  my-app: .\n", "")  # the user named the repos
            else:
                text = text.replace("my-app: .", "%s: ." % re.sub(r"[^A-Za-z0-9_.-]", "-", Path(top).name))
            cfg_path.write_text(text, encoding="utf-8")
            lines.append("Created:  %s" % cfg_path)
        lines += ignore_workspace(ws)
    if not cfg_path.exists():
        raise UsageError("No relay.yaml in %s. Run --init first." % ws)
    if args.base:
        set_scalar(cfg_path, "base_branch", args.base)
        lines.append("Saved:    base_branch: %s" % args.base)
    for name, path in parse_repo_args(args.repo):
        set_repo(cfg_path, name, path)
        lines.append("Saved:    repos.%s: %s" % (name, path))
    cfg = load_cfg(ws)
    if not cfg.get("base_branch"):
        lines.append("Next:     ask the user which branch they work from, then run --base <branch>")
    emit(args, {"config": str(cfg_path), "base_branch": cfg.get("base_branch"),
                "repos": repos_of(cfg, ws)[0]}, lines)
    return 0


def ignore_workspace(ws):
    top = git_toplevel(Path(ws).parent)
    if not top or Path(ws).name != "_relay" or Path(ws).parent.resolve() != top.resolve():
        return []
    gi = top / ".gitignore"
    current = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if re.search(r"(?m)^/?_relay/?\s*$", current):
        return ["Ignored:  _relay/ is already in .gitignore"]
    with gi.open("a", encoding="utf-8") as fh:
        fh.write(("" if current.endswith("\n") or not current else "\n") +
                 "\n# Relay workspace (kept out of the code)\n_relay/\n")
    return ["Updated:  %s (added _relay/)" % gi]


# --------------------------------------------------------------------------- main


def build_parser():
    p = argparse.ArgumentParser(prog="relay_tasks.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("--new", nargs="+", metavar="PATH", help="design or spec files or folders to copy in")
    p.add_argument("--name", help="short name for a new feature (with --new)")
    p.add_argument("--epic", help="epic key for a new feature (with --new --name)")
    p.add_argument("--feature", metavar="REF", help="which feature (with --new or --set)")
    p.add_argument("--check", nargs="?", const="", metavar="REF", help="check the task files")
    p.add_argument("--branch", nargs="?", const="", metavar="REF", help="show or create the feature branch")
    p.add_argument("--create", action="store_true", help="with --branch: create and push it")
    p.add_argument("--branch-name", help="with --branch: use this name instead of the suggested one")
    p.add_argument("--no-push", action="store_true", help="with --branch --create: do not push")
    p.add_argument("--status", nargs="?", const="", metavar="REF", help="write status.md and board.html")
    p.add_argument("--open", action="store_true", help="with --status: open the board in the browser")
    p.add_argument("--set", nargs=2, metavar=("TASK", "STATUS"), help="set a task's status")
    p.add_argument("--owner", help="with --set: who owns the task")
    p.add_argument("--pr", help="with --set: link to the PR")
    p.add_argument("--list", action="store_true", help="list features")
    p.add_argument("--init", action="store_true", help="create _relay/relay.yaml")
    p.add_argument("--base", help="save the base branch (for example dev) in relay.yaml")
    p.add_argument("--repo", action="append", metavar="NAME=PATH", help="save a code repo in relay.yaml")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="path to the _relay folder")
    return p


def pick_command(args):
    chosen = [name for name, on in (("new", args.new is not None), ("check", args.check is not None),
                                    ("branch", args.branch is not None), ("status", args.status is not None),
                                    ("set", args.set is not None), ("list", args.list)) if on]
    if len(chosen) > 1:
        raise UsageError("Use one of --%s at a time." % ", --".join(chosen))
    if chosen:
        if chosen[0] != "branch" and (args.init or args.repo):
            raise UsageError("Run --init / --base / --repo on their own.")
        return chosen[0]
    if args.init or args.base or args.repo:
        return "config"
    raise UsageError("Nothing to do. See --help.")


COMMANDS = {"new": cmd_new, "check": cmd_check, "branch": cmd_branch, "status": cmd_status,
            "set": cmd_set, "list": cmd_list, "config": cmd_config}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ws = find_workspace(args.workspace)
        return COMMANDS[pick_command(args)](args, ws)
    except (UsageError, ConfigError, FeatureError, gitops.GitError, ValueError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
