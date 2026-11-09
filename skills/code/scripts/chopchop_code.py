#!/usr/bin/env python3
"""chopchop code: build one task, from claiming it to ready for a PR.

Usage
  chopchop_code.py                          tasks you can start now (same as --ready)
  chopchop_code.py T02 -p                   preview: everything about T02, changes nothing (also: T02 alone)
  chopchop_code.py T02 --start              claim T02 (in-progress) and create or resume its branch
  chopchop_code.py T02 --verify             run the repo's build, lint and test commands
  chopchop_code.py T02 --log --change "amounts are cents" [--why "..."] [--affects T03,T05]
  chopchop_code.py --done T02               mark T02 done (only a person decides this)
  chopchop_code.py --profile payments-api [--refresh | --confirm]   show, draft or confirm how a repo works

Pushing and opening the PR are done with what the team already uses. When the PR is open,
record it with tasks: chopchop_tasks.py --set T02 in-review --pr <url>.

Options: --feature REF (when the task id is in more than one feature), --force (start although
dependencies are not done), --take (take over a task someone else owns), --json, --workspace PATH.

Needs the tasks skill in the folder next to this one. Standard library only. Python 3.8+.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_SCRIPTS = HERE.parents[1] / "tasks" / "scripts"
if not (TASKS_SCRIPTS / "chopchop_tasks.py").is_file():
    sys.exit("Error: code needs the tasks skill next to it (%s not found)." % TASKS_SCRIPTS)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TASKS_SCRIPTS))

import chopchop_tasks  # noqa: E402
from codelib import changes, profile  # noqa: E402
from chopchoplib import features, gitops  # noqa: E402
from chopchoplib import tasks as tasklib  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace, load_config  # noqa: E402
from chopchoplib.features import FeatureError  # noqa: E402

COMMAND_TIMEOUT = 1800
KEEP = object()


class UsageError(Exception):
    pass


def emit(args, data, lines):
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n".join(lines))


def rel(ws, path):
    try:
        return str(Path(path).resolve().relative_to(Path(ws).resolve().parent))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------- lookup


def find_task(ws, task_id, feature_ref):
    task_id = (task_id or "").upper()
    if not re.match(r"^T\d+$", task_id):
        raise UsageError("'%s' is not a task id. Task ids look like T02." % task_id)
    pool = [features.resolve(ws, feature_ref)] if feature_ref else features.all_features(ws)
    hits = []
    for f in pool:
        for t in tasklib.load_tasks(f.path / tasklib.TASKS_DIR):
            if t.id == task_id:
                hits.append((f, t))
    if not hits:
        raise UsageError("No task %s%s. Run with no task id to see the tasks you can start."
                         % (task_id, " in %s" % pool[0].name if feature_ref else ""))
    if len(hits) > 1:
        raise UsageError("%s is in more than one feature: %s. Add --feature <number>."
                         % (task_id, ", ".join(f.name for f, _ in hits)))
    return hits[0]


def reload(feature, task_id):
    return next(t for t in tasklib.load_tasks(feature.path / tasklib.TASKS_DIR) if t.id == task_id)


def repo_of(ws, cfg, name):
    paths, _ = chopchop_tasks.repos_of(cfg, ws)
    if name not in paths:
        raise UsageError("Repo '%s' is not in chopchop.yaml. Add it with: /chopchop:tasks --repo %s=<path>" % (name, name))
    raw = (cfg.get("repos") or {}).get(name)
    return chopchop_tasks.repo_dir(ws, paths[name]), (raw if isinstance(raw, dict) else {})


def style_files(path, options, ws):
    """The repo's own code style files from chopchop.yaml (repos.<name>.style), in the order given.

    A path is absolute, relative to the repo, or relative to _chopchop/ (for example
    styles/payments-api.md made by init). Returns [{"file", "path", "exists"}]."""
    raw = options.get("style")
    items = raw if isinstance(raw, list) else [raw] if raw else []
    out = []
    for item in items:
        p = Path(str(item)).expanduser()
        if p.is_absolute():
            full = p
        else:
            full = next((b / p for b in (Path(path), Path(ws)) if (b / p).is_file()), Path(path) / p)
        out.append({"file": str(item), "path": str(full), "exists": full.is_file()})
    return out


def git(path, *args, check=False):
    code, out, err = gitops.git(path, *args)
    if check and code != 0:
        raise UsageError("git %s failed in %s: %s" % (" ".join(args), path, err or out))
    return code, out, err


def current_branch(path):
    return git(path, "branch", "--show-current")[1] if gitops.is_repo(path) else None


def dirty_files(path):
    """Changed tracked files. Untracked files are left alone."""
    out = git(path, "status", "--porcelain", "--untracked-files=no")[1]
    return [line[3:] for line in out.splitlines() if line.strip()]


def me(path=None):
    name = git(path or ".", "config", "user.name")[1] if path and gitops.is_repo(path) else ""
    return name or git(".", "config", "--global", "user.name")[1] or "unknown"


def set_status(ws, cfg, feature, task_id, status=KEEP, owner=KEEP, pr=KEEP):
    t = reload(feature, task_id)
    old = t.get("status")
    if status is not KEEP:
        t.meta["status"] = status
    if owner is not KEEP:
        t.meta["owner"] = owner
    if pr is not KEEP:
        t.meta["pr"] = pr
    t.save()
    chopchop_tasks.refresh(ws, feature, cfg)
    return old


# --------------------------------------------------------------------------- context


def context(ws, cfg, feature, task):
    """Everything about one task that the agent (or a person) needs before building it."""
    plan, _ = chopchop_tasks.read_plan(feature, cfg)
    patterns = cfg.get("branches") if isinstance(cfg.get("branches"), dict) else None
    all_tasks = tasklib.load_tasks(feature.path / tasklib.TASKS_DIR)
    by_id = {t.id: t for t in all_tasks}
    name = str(task.get("repo") or "")
    path, options = repo_of(ws, cfg, name)
    is_repo = gitops.is_repo(path)
    meta, _ = profile.load(ws, name)
    log = tasklib.read_changelog(feature.path / tasklib.TASKS_DIR / tasklib.CHANGELOG_FILE)
    heads = tasklib.find_section(task.body, changes.HEADS_UP)
    who = me(path if is_repo else None)

    ctx = {
        "task": task.id, "title": task.get("title"), "status": task.get("status"), "owner": task.get("owner"),
        "me": who, "wave": task.get("wave"), "size": task.get("size"),
        "touches": tasklib.as_list(task.get("touches")), "stories": tasklib.as_list(task.get("stories")),
        "pr": task.get("pr"), "feature": feature.name, "task_file": str(task.path),
        "design_dir": str(feature.path / tasklib.DESIGN_DIR),
        "requirement": str(feature.file) if feature.file.exists() else None,
        "changelog": str(feature.path / tasklib.TASKS_DIR / tasklib.CHANGELOG_FILE),
        "repo": name, "repo_path": str(path), "repo_ok": is_repo,
        "current_branch": current_branch(path) if is_repo else None,
        "dirty": dirty_files(path) if is_repo else [],
        "base_branch": plan.get("base_branch") or cfg.get("base_branch"),
        "feature_branch": plan.get("feature_branch"),
        "task_branch": tasklib.task_branch_name(feature, task, patterns),
        "depends_on": [{"id": d, "title": by_id[d].get("title") if d in by_id else None,
                        "status": by_id[d].get("status") if d in by_id else "missing"}
                       for d in tasklib.as_list(task.get("depends_on"))],
        "waiting_on": tasklib.waiting_on(task, by_id),
        "changes": [c for c in log if c["task"] == task.id or task.id in c["affects"]],
        "heads_up": heads[1].strip() if heads else "",
        "profile": {"path": str(profile.path_for(ws, name)), "exists": meta is not None,
                    "confirmed": bool(meta and meta.get("confirmed")),
                    "commands": {k: (meta or {}).get(k) for k in profile.COMMANDS},
                    "pr": (meta or {}).get("pr")},
        "guides": profile.guides(path) if is_repo else [],
        "style": style_files(path, options, ws),
    }
    ctx["blockers"], ctx["warnings"] = check_start(ctx)
    return ctx


def check_start(ctx):
    blockers, warnings = [], []
    if ctx["status"] == "done":
        blockers.append("%s is done. Ask before changing a finished task; a new task is usually better." % ctx["task"])
    if ctx["owner"] and ctx["owner"] != ctx["me"]:
        blockers.append("%s is owned by %s. Use --take only if they agree." % (ctx["task"], ctx["owner"]))
    if ctx["waiting_on"]:
        blockers.append("Waiting on %s (not done). Wait, or build against their contracts with --force."
                        % ", ".join(ctx["waiting_on"]))
    if not ctx["feature_branch"]:
        blockers.append("The feature branch is not created yet. Run /chopchop:tasks --branch first.")
    if not ctx["repo_ok"]:
        blockers.append("%s is not a git repo. Fix its path in chopchop.yaml." % ctx["repo_path"])
    if ctx["dirty"] and ctx["current_branch"] != ctx["task_branch"]:
        blockers.append("%s has uncommitted changes on %s: %s. Commit or stash them first."
                        % (ctx["repo"], ctx["current_branch"], ", ".join(ctx["dirty"][:5])))
    missing = [s["file"] for s in ctx["style"] if not s["exists"]]
    if missing:
        blockers.append("Style file %s from chopchop.yaml (repos.%s.style) is not in the repo. Fix the path."
                        % (", ".join(missing), ctx["repo"]))
    if not ctx["profile"]["exists"]:
        warnings.append("No profile for %s yet. Run --profile %s." % (ctx["repo"], ctx["repo"]))
    elif not ctx["profile"]["confirmed"]:
        warnings.append("The %s profile is a draft. Confirm it with the user." % ctx["repo"])
    return blockers, warnings


def context_lines(ws, ctx, preview=False):
    deps = ", ".join("%s %s" % (d["id"], d["status"]) for d in ctx["depends_on"]) or "none"
    cmds = ctx["profile"]["commands"]
    if ctx["profile"]["exists"]:
        prof = "%s (%s) · %s" % (rel(ws, ctx["profile"]["path"]), "confirmed" if ctx["profile"]["confirmed"] else "DRAFT",
                                 " · ".join("%s: %s" % (k, v) for k, v in cmds.items() if v) or "no commands")
    else:
        prof = "missing. Run --profile %s" % ctx["repo"]
    if ctx["profile"]["exists"]:
        prs = "PRs:      %s" % (ctx["profile"]["pr"] or "not set in the profile. Find out how this team opens PRs.")
    else:
        prs = None
    lines = ["Task:     %s %s (%s, wave %s, size %s)" % (ctx["task"], ctx["title"], ctx["status"], ctx["wave"], ctx["size"]),
             "Feature:  %s" % ctx["feature"],
             "File:     %s" % rel(ws, ctx["task_file"]),
             "Owner:    %s (you are %s)" % (ctx["owner"] or "nobody", ctx["me"]),
             "Repo:     %s at %s%s" % (ctx["repo"], rel(ws, ctx["repo_path"]),
                                       ", on branch %s" % ctx["current_branch"] if ctx["current_branch"] else ""),
             "Branch:   %s <- from %s" % (ctx["task_branch"], ctx["feature_branch"] or "(no feature branch yet)"),
             "Depends:  %s" % deps,
             "Profile:  %s" % prof] + ([prs] if prs else []) + [
             "Style:    %s" % (", ".join(s["file"] for s in ctx["style"]) + " (from chopchop.yaml, always follow it)"
                                 if ctx["style"] else "not set in chopchop.yaml. Follow the code and the profile rules."),
             "Guides:   %s" % (", ".join(ctx["guides"]) or "none found"),
             "Design:   %s%s" % (rel(ws, ctx["design_dir"]),
                                 " · story: %s" % rel(ws, ctx["requirement"]) if ctx["requirement"] else "")]
    for c in ctx["changes"]:
        lines.append("Change:   %s (from %s, %s): %s" % (c["id"], c["task"] or "?", c["date"] or "?",
                                                         " / ".join(l for l in c["text"].splitlines() if l.strip())))
    if ctx["pr"]:
        lines.append("PR:       %s" % ctx["pr"])
    if preview and not ctx["blockers"]:
        resume = ctx["status"] in ("in-progress", "in-review")
        lines.append("Start:    will %s %s and set %s" % (
            "resume" if resume else "create", ctx["task_branch"],
            "status in-progress" if ctx["status"] == "todo" else "nothing new (status stays %s)" % ctx["status"]))
    lines += ["Blocked:  %s" % b for b in ctx["blockers"]]
    lines += ["Warning:  %s" % w for w in ctx["warnings"]]
    return lines


# --------------------------------------------------------------------------- commands


def cmd_ready(args, ws):
    cfg = load_config(ws)
    pool = [features.resolve(ws, args.feature)] if args.feature else features.all_features(ws)
    who = me(Path(ws).parent)
    rows = []
    for f in pool:
        all_tasks = tasklib.load_tasks(f.path / tasklib.TASKS_DIR)
        by_id = {t.id: t for t in all_tasks}
        for t in all_tasks:
            status, wait = t.get("status"), tasklib.waiting_on(t, by_id)
            if status == "todo":
                kind = "waiting" if wait else "ready"
            elif status in ("in-progress", "in-review") and t.get("owner") == who:
                kind = "yours"
            else:
                continue
            rows.append({"feature": f.name, "task": t.id, "title": t.get("title"), "repo": t.get("repo"),
                         "size": t.get("size"), "status": status, "kind": kind, "waiting_on": wait})
    lines = []
    for kind, head in (("yours", "Yours, still open"), ("ready", "Ready to start"), ("waiting", "Waiting")):
        group = [r for r in rows if r["kind"] == kind]
        if group:
            lines.append("%s:" % head)
            for r in group:
                extra = r["status"] if kind == "yours" else "waiting on %s" % ", ".join(r["waiting_on"]) if kind == "waiting" else ""
                lines.append("  %-4s %-40s %-14s %-2s %s  (%s)" % (r["task"], (r["title"] or "")[:40], r["repo"] or "?",
                                                                  r["size"] or "", extra, r["feature"]))
    if not lines:
        lines.append("Nothing to start. Every task is taken or done." if pool else "No features yet.")
    emit(args, {"me": who, "tasks": rows}, lines)
    return 0


def cmd_preview(args, ws):
    cfg = load_config(ws)
    feature, task = find_task(ws, args.task, args.feature)
    ctx = context(ws, cfg, feature, task)
    emit(args, ctx, context_lines(ws, ctx, preview=True))
    return 0


def cmd_start(args, ws):
    cfg = load_config(ws)
    feature, task = find_task(ws, args.task, args.feature)
    ctx = context(ws, cfg, feature, task)
    blockers = [b for b in ctx["blockers"]
                if not (args.force and b.startswith("Waiting on")) and not (args.take and "is owned by" in b)]
    if blockers:
        raise UsageError("Cannot start %s:\n  %s" % (task.id, "\n  ".join(blockers)))
    path, fb, tb = Path(ctx["repo_path"]), ctx["feature_branch"], ctx["task_branch"]
    problem = gitops.safe_name(tb, ctx["base_branch"] or "")
    if problem or tb == fb:
        raise UsageError(problem or "The task branch must not be the feature branch.")

    code, _, err = git(path, "fetch", "origin", fb)
    if code != 0:
        raise UsageError("Cannot fetch %s from origin in %s: %s" % (fb, ctx["repo"], err))
    git(path, "fetch", "origin", tb)  # fine when it does not exist yet
    remote_fb = "origin/%s" % fb
    if ctx["current_branch"] == tb:
        action = "already on"
    elif gitops.local_branch_exists(path, tb):
        git(path, "checkout", tb, check=True)
        action = "switched to"
    elif git(path, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/" + tb)[0] == 0:
        git(path, "checkout", "-b", tb, "--track", "origin/" + tb, check=True)
        action = "checked out"
    else:
        git(path, "checkout", "-b", tb, "--no-track", remote_fb, check=True)
        action = "created"

    merged = None
    if action != "created" and git(path, "merge-base", "--is-ancestor", remote_fb, "HEAD")[0] != 0:
        if dirty_files(path):
            raise UsageError("%s has new commits, but the task branch has uncommitted changes. Commit them, "
                             "then run --start again to bring them in." % fb)
        code, out, err = git(path, "merge", "--no-edit", remote_fb)
        if code != 0:
            conflicts = git(path, "diff", "--name-only", "--diff-filter=U")[1].split()
            git(path, "merge", "--abort")
            raise UsageError("Merging the latest %s into %s conflicts in: %s. The merge was undone. A person "
                             "must resolve this." % (fb, tb, ", ".join(conflicts) or err or out))
        merged = fb

    owner = ctx["me"] if (not ctx["owner"] or args.take) else KEEP
    status = "in-progress" if ctx["status"] == "todo" else KEEP
    old = set_status(ws, cfg, feature, task.id, status=status, owner=owner)
    ctx = context(ws, cfg, feature, reload(feature, task.id))
    lines = ["Branch:   %s %s (in %s)" % (action, tb, ctx["repo"])]
    if merged:
        lines.append("Merged:   the latest %s into it" % merged)
    lines.append("Status:   %s -> %s, owner %s" % (old, ctx["status"], ctx["owner"]))
    if args.force and ctx["waiting_on"]:
        lines.append("Warning:  started before %s is done. Code against the contracts and stub the rest."
                     % ", ".join(ctx["waiting_on"]))
    lines += [""] + context_lines(ws, ctx)
    ctx.update({"branch_action": action, "merged": merged})
    emit(args, ctx, lines)
    return 0


def cmd_verify(args, ws):
    cfg = load_config(ws)
    feature, task = find_task(ws, args.task, args.feature)
    path, _ = repo_of(ws, cfg, str(task.get("repo")))
    meta, _ = profile.load(ws, str(task.get("repo")))
    if meta is None:
        raise UsageError("No profile for %s, so chopchop does not know how to test it. Run --profile %s first."
                         % (task.get("repo"), task.get("repo")))
    results, lines = [], []
    steps = [(kind, meta.get(kind)) for kind in profile.COMMANDS]
    if task.get("kind") == "prove" and task.get("e2e"):
        steps.append(("e2e", task.get("e2e")))
    for kind, cmd in steps:
        if not cmd:
            continue
        if results and results[0]["step"] == "build" and not results[0]["ok"]:
            results.append({"step": kind, "command": cmd, "ok": None, "skipped": "build failed"})
            lines.append("%-6s skipped (build failed)" % kind)
            continue
        start = time.time()
        try:
            out = subprocess.run(cmd, shell=True, cwd=str(path), capture_output=True, text=True,
                                 timeout=COMMAND_TIMEOUT)
            ok, text = out.returncode == 0, (out.stdout or "") + (out.stderr or "")
        except subprocess.TimeoutExpired:
            ok, text = False, "Timed out after %d minutes." % (COMMAND_TIMEOUT // 60)
        tail = text.strip().splitlines()[-(5 if ok else 60):]
        results.append({"step": kind, "command": cmd, "ok": ok, "seconds": round(time.time() - start, 1),
                        "output_tail": "\n".join(tail)})
        lines.append("%-6s %s  `%s`  (%.1fs)" % (kind, "PASS" if ok else "FAIL", cmd, time.time() - start))
        if not ok:
            lines += ["         " + l for l in tail]
    if not results:
        raise UsageError("The %s profile has no build, lint or test command. Add them to %s."
                         % (task.get("repo"), rel(ws, profile.path_for(ws, task.get("repo")))))
    ok = all(r["ok"] for r in results if r["ok"] is not None) and not any(r.get("skipped") for r in results)
    if not meta.get("confirmed"):
        lines.append("Warning:  the profile is a draft. Confirm the commands with the user.")
    lines.append("Result:   %s" % ("all passed" if ok else "FAILED. Fix it and run --verify again."))
    save_verify(feature, task, path, ok, results)
    emit(args, {"task": task.id, "ok": ok, "results": results}, lines)
    return 0 if ok else 1


def save_verify(feature, task, repo_path, ok, results):
    """Keep the last check of a task, so /chopchop:spec --status can show what is proved."""
    out = feature.path / "work" / "verify"
    out.mkdir(parents=True, exist_ok=True)
    commit = git(repo_path, "rev-parse", "HEAD")[1].strip() if Path(repo_path).is_dir() else ""
    record = {"task": task.id, "ok": ok, "when": datetime.now().isoformat(timespec="seconds"), "commit": commit,
              "steps": [{"step": r["step"], "command": r["command"], "ok": r["ok"]} for r in results]}
    (out / ("%s.json" % task.id)).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def cmd_log(args, ws):
    cfg = load_config(ws)
    feature, task = find_task(ws, args.task, args.feature)
    affects = [a.strip().upper() for a in args.affects.split(",") if a.strip()] if args.affects else None
    all_tasks = tasklib.load_tasks(feature.path / tasklib.TASKS_DIR)
    mine = next(t for t in all_tasks if t.id == task.id)
    try:
        report = changes.log_change(feature.path / tasklib.TASKS_DIR, mine, all_tasks, args.change, args.why, affects)
    except ValueError as e:
        raise UsageError(str(e))
    chopchop_tasks.refresh(ws, feature, cfg)
    lines = ["Logged:   %s in %s" % (report["id"], rel(ws, feature.path / tasklib.TASKS_DIR / tasklib.CHANGELOG_FILE))]
    if report["updated"]:
        lines.append("Updated:  %s (todo: a heads-up was added to the task file)" % ", ".join(report["updated"]))
    for t in report["tell"]:
        lines.append("Tell:     %s is %s (owner %s). Let them know." % (t["task"], t["status"], t["owner"] or "nobody"))
    if report["follow_up"]:
        lines.append("Done:     %s already done. Suggest a follow-up task if it must change too."
                     % ", ".join(report["follow_up"]))
    if not (report["updated"] or report["tell"] or report["follow_up"]):
        lines.append("Affects:  no other task")
    emit(args, report, lines)
    return 0


def cmd_done(args, ws):
    cfg = load_config(ws)
    feature, task = find_task(ws, args.task, args.feature)
    old = set_status(ws, cfg, feature, task.id, status="done")
    by_id = {t.id: t for t in tasklib.load_tasks(feature.path / tasklib.TASKS_DIR)}
    unblocked = [t.id for t in by_id.values() if t.get("status") == "todo"
                 and task.id in tasklib.as_list(t.get("depends_on")) and not tasklib.waiting_on(t, by_id)]
    lines = ["Task:     %s %s: %s -> done" % (task.id, task.get("title"), old)]
    if unblocked:
        lines.append("Ready:    %s can start now" % ", ".join(unblocked))
    emit(args, {"task": task.id, "from": old, "to": "done", "unblocked": unblocked}, lines)
    return 0


def cmd_profile(args, ws):
    cfg = load_config(ws)
    name = args.profile
    path, _ = repo_of(ws, cfg, name)
    target = profile.path_for(ws, name)
    meta, _ = profile.load(ws, name)
    lines = []
    if args.confirm:
        if meta is None:
            raise UsageError("No profile for %s yet. Run --profile %s first." % (name, name))
        meta = profile.confirm(ws, name)
        lines.append("Confirmed: %s" % rel(ws, target))
    elif meta is None or args.refresh:
        if not gitops.is_repo(path):
            raise UsageError("%s is not a git repo. Fix its path in chopchop.yaml." % path)
        if meta and meta.get("confirmed") and args.refresh:
            lines.append("Note:     the confirmed profile was replaced by a new draft.")
        found = profile.detect(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(profile.render_draft(name, found), encoding="utf-8")
        meta, _ = profile.load(ws, name)
        lines.append("Drafted:  %s" % rel(ws, target))
        lines.append("Found:    guides %s · %d CI command(s) · %d example test(s)"
                     % (", ".join(found["guides"]) or "none", len(found["ci"]), len(found["tests"])))
    else:
        lines.append("Profile:  %s (%s)" % (rel(ws, target), "confirmed" if meta.get("confirmed") else "DRAFT"))
    for k in profile.COMMANDS:
        lines.append("%-9s %s" % (k + ":", meta.get(k) or "-"))
    if not meta.get("confirmed"):
        lines.append("Next:     check it against the guides, CI and code, fill in ## Rules, show the user, "
                     "then run --profile %s --confirm" % name)
    emit(args, {"repo": name, "path": str(target), "confirmed": bool(meta.get("confirmed")),
                "commands": {k: meta.get(k) for k in profile.COMMANDS}}, lines)
    return 0


# --------------------------------------------------------------------------- main


ACTIONS = ["preview", "start", "verify", "log", "done", "ready", "profile"]
NEEDS_TASK = {"preview", "start", "verify", "log", "done"}
VALUE_ACTIONS = {"profile"}


def build_parser():
    p = argparse.ArgumentParser(prog="chopchop_code.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("task", nargs="?", help="task id, e.g. T02")
    p.add_argument("-p", "--preview", action="store_true", help="show everything about the task, change nothing")
    p.add_argument("--start", action="store_true", help="claim the task and create or resume its branch")
    p.add_argument("--verify", action="store_true", help="run the repo's build, lint and test commands")
    p.add_argument("--log", action="store_true", help="log a change in changelog.md")
    p.add_argument("--change", help="with --log: what changed")
    p.add_argument("--why", help="with --log: why")
    p.add_argument("--affects", help="with --log: tasks it affects, e.g. T03,T05 (default: found for you)")
    p.add_argument("--done", action="store_true", help="mark the task done")
    p.add_argument("--ready", action="store_true", help="tasks you can start now")
    p.add_argument("--profile", metavar="REPO", help="show, draft or confirm how a repo builds and tests")
    p.add_argument("--refresh", action="store_true", help="with --profile: draft it again from the repo")
    p.add_argument("--confirm", action="store_true", help="with --profile: mark it checked by a person")
    p.add_argument("--feature", metavar="REF", help="feature number, epic key or name")
    p.add_argument("--force", action="store_true", help="with --start: start although dependencies are not done")
    p.add_argument("--take", action="store_true", help="with --start: take over a task someone else owns")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="path to the _chopchop folder")
    return p


def pick_command(args):
    chosen = [a for a in ACTIONS if (getattr(args, a) is not None if a in VALUE_ACTIONS else getattr(args, a))]
    if len(chosen) > 1:
        raise UsageError("Use one of --%s at a time." % ", --".join(c.replace("_", "-") for c in chosen))
    action = chosen[0] if chosen else ("preview" if args.task else "ready")
    if action in NEEDS_TASK and not args.task:
        raise UsageError("--%s needs a task id, e.g. T02." % action.replace("_", "-"))
    if action == "log" and not args.change:
        raise UsageError("--log needs --change \"what changed\".")
    return action


COMMANDS = {"preview": cmd_preview, "start": cmd_start, "verify": cmd_verify, "log": cmd_log, "done": cmd_done,
            "ready": cmd_ready, "profile": cmd_profile}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ws = find_workspace(args.workspace)
        return COMMANDS[pick_command(args)](args, ws)
    except (UsageError, ConfigError, FeatureError, gitops.GitError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
