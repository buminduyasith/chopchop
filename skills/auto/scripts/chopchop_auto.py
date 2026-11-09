#!/usr/bin/env python3
"""chopchop auto: build a feature's tasks one at a time, each one reviewed before its commit.

Usage
  chopchop_auto.py --plan [REF] [--max N] [--only T01,T02] [--repo NAME]   what a run would do, changes nothing
  chopchop_auto.py --start [REF] [same options] [--step] [--new]          make the build branches and the run
  chopchop_auto.py --next                       pick the next task and write the builder's brief
  chopchop_auto.py --review T02                 check the build, then write the review pack
  chopchop_auto.py --sort T02                   sort the review: another fix round, commit, or stop
  chopchop_auto.py --commit T02 [--message M] [--outside a,b]   commit the task on the build branch
  chopchop_auto.py --stop T02 --why "..."       stop a task: its repo waits for a person, the others go on
  chopchop_auto.py --finish                     push each build branch and write its PR text
  chopchop_auto.py --pr REPO URL                record a repo's PR: its tasks go to in-review
  chopchop_auto.py --status                     where the run is, and the next step

One build branch per repo, cut from the feature branch, one commit per task. One PR per repo
into the feature branch, never into the base branch. The run lives in work/auto.json, so a new
chat carries on with --status. Options: --feature REF, --json, --workspace PATH.

Needs the code and tasks skills next to this one. Standard library only. Python 3.8+.
"""

import argparse
import json
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
CODE_SCRIPTS = SKILLS / "code" / "scripts"
for _need in (CODE_SCRIPTS / "chopchop_code.py", SKILLS / "tasks" / "scripts" / "chopchop_tasks.py"):
    if not _need.is_file():
        sys.exit("Error: auto needs the code and tasks skills next to it (%s not found)." % _need)
sys.path.insert(0, str(CODE_SCRIPTS))

import chopchop_code  # noqa: E402  (puts the tasks scripts on the path)
import chopchop_tasks  # noqa: E402
from codelib import profile  # noqa: E402
from chopchoplib import features, gitops, review  # noqa: E402
from chopchoplib import tasks as tasklib  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace, load_config  # noqa: E402
from chopchoplib.features import FeatureError  # noqa: E402

STATE_FILE = "auto.json"
RUN_DIR = "auto"
REPORT = "report.json"
ACTIVE = ("building", "reviewing", "fixing", "ready")
PR_MODES = ("draft", "ready", "push")
UsageError = chopchop_code.UsageError
KEEP = chopchop_code.KEEP
now = review.now


def emit(args, data, lines):
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n".join(lines))


def settings(cfg):
    raw = cfg.get("auto") if isinstance(cfg.get("auto"), dict) else {}
    try:
        rounds = int(raw.get("rounds") or 2)
    except (TypeError, ValueError):
        rounds = 2
    pr = str(raw.get("pr") or "draft").lower()
    return {"rounds": max(1, min(3, rounds)), "pr": pr if pr in PR_MODES else "draft",
            "reviewer_model": raw.get("reviewer_model") or None}


def ids(text):
    return [p.strip().upper() for p in (text or "").split(",") if p.strip()]


def q(path):
    return shlex.quote(str(path))


# --------------------------------------------------------------------------- the run


class Run:
    def __init__(self, ws, cfg, feature):
        self.ws, self.cfg, self.feature = ws, cfg, feature
        self.work = feature.path / "work"
        self.file = self.work / STATE_FILE
        self.state = json.loads(self.file.read_text(encoding="utf-8")) if self.file.is_file() else None

    def save(self):
        self.work.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.file)
        chopchop_tasks.refresh(self.ws, self.feature, self.cfg)  # the board shows the run

    def dir(self, tid):
        d = self.work / RUN_DIR / tid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def task(self, tid, states=None):
        tid = tid.upper()
        t = self.state["tasks"].get(tid)
        if t is None:
            raise UsageError("%s is not in this run. Runs: %s" % (tid, ", ".join(self.state["queue"])))
        if states and t["state"] not in states:
            raise UsageError("%s is %s, not %s. Next: %s" % (tid, t["state"], " or ".join(states), next_step(self)))
        return tid, t

    def task_file(self, tid):
        return chopchop_code.reload(self.feature, tid)

    def repo(self, t):
        return self.state["repos"][t["repo"]]

    def verify_cmd(self, tid):
        return "python3 %s %s --verify --feature %d --workspace %s" % (
            q(CODE_SCRIPTS / "chopchop_code.py"), tid, self.feature.number, q(self.ws))


def open_run(ws, args, need=True):
    cfg = load_config(ws)
    if args.feature:
        feature = features.resolve(ws, args.feature)
    else:
        runs = [f for f in features.all_features(ws) if (f.path / "work" / STATE_FILE).is_file()]
        if len(runs) > 1:
            raise UsageError("More than one feature has an auto run: %s. Add --feature <number>."
                             % ", ".join(f.name for f in runs))
        feature = runs[0] if runs else features.resolve(ws, "")
    run = Run(ws, cfg, feature)
    if need and not run.state:
        raise UsageError("No auto run for %s yet. Start one with --plan, then --start." % feature.name)
    return run


def own_pending(path, ws):
    """Pending changes in a repo, leaving out the chopchop workspace when it lives inside it."""
    items = review.pending(path)
    try:
        inside = Path(ws).resolve().relative_to(Path(path).resolve())
    except ValueError:
        return items
    prefix = str(inside).replace("\\", "/").rstrip("/") + "/"
    return [x for x in items if not (x["path"] + "/").startswith(prefix)]


def read_verify(feature, tid):
    f = feature.path / "work" / "verify" / ("%s.json" % tid)
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def read_report(run, tid):
    f = run.dir(tid) / REPORT
    if not f.is_file():
        raise UsageError("The builder wrote no report at %s. Ask it to finish, or start a new builder with %s."
                         % (f, run.dir(tid) / "brief.md"))
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        raise UsageError("%s is not valid JSON: %s" % (f, e))
    if not isinstance(data, dict) or str(data.get("task", tid)).upper() != tid:
        raise UsageError("%s is not a report for %s." % (f, tid))
    return data


# --------------------------------------------------------------------------- plan


def order(all_tasks):
    """Open tasks, each after the tasks it depends on, lower waves first."""
    open_ = [t for t in all_tasks if t.get("status") in ("todo", "in-progress")]
    names = {t.id for t in open_}

    def wave(t):
        try:
            return int(t.get("wave") or 0)
        except (TypeError, ValueError):
            return 0

    rest = sorted(open_, key=lambda t: (wave(t), tasklib._id_number(t.id)))
    out, placed = [], set()
    while rest:
        pick = next((t for t in rest if all(d in placed for d in tasklib.as_list(t.get("depends_on")) if d in names)), None)
        if pick is None:
            return out + rest  # a loop in depends_on: the tasks check reports it
        out.append(pick)
        placed.add(pick.id)
        rest.remove(pick)
    return out


def make_plan(ws, cfg, feature, args):
    all_tasks = tasklib.load_tasks(feature.path / tasklib.TASKS_DIR)
    if not all_tasks:
        raise UsageError("%s has no tasks yet. Cut them with /chopchop:tasks first." % feature.name)
    by_id = {t.id: t for t in all_tasks}
    plan_meta, _ = chopchop_tasks.read_plan(feature, cfg)
    fb = plan_meta.get("feature_branch")
    patterns = cfg.get("branches") if isinstance(cfg.get("branches"), dict) else None
    build = tasklib.build_branch_name(feature, patterns)
    only = ids(args.only)
    repo_paths, _ = chopchop_tasks.repos_of(cfg, ws)
    who = {}
    queue, left_out, warnings, blockers = [], [], [], []
    for t in order(all_tasks):
        name = str(t.get("repo") or "")
        if (only and t.id not in only) or (args.repo and name != args.repo):
            continue
        if name not in who:
            path = chopchop_tasks.repo_dir(ws, repo_paths[name]) if name in repo_paths else None
            who[name] = chopchop_code.me(path)
        why = None
        if t.get("owner") and t.get("owner") != who[name]:
            why = "owned by %s" % t.get("owner")
        for d in tasklib.as_list(t.get("depends_on")):
            dt = by_id.get(d)
            if why or (dt is not None and (dt.get("status") == "done" or d in queue)):
                continue
            if dt is not None and dt.get("repo") != name and dt.get("status") in ("in-progress", "in-review"):
                warnings.append("%s codes against the contract of %s (%s, %s)." % (t.id, d, dt.get("status"), dt.get("repo")))
                continue
            why = "needs %s (%s), which is not in this run" % (d, dt.get("status") if dt else "missing")
        if why:
            left_out.append({"task": t.id, "why": why})
        else:
            queue.append(t.id)
    if args.max:
        queue = queue[:args.max]
    if not queue:
        blockers.append("No task can run: every open task is left out, done or in review.")
    if not fb:
        blockers.append("The feature branch is not created yet. Run /chopchop:tasks --branch, then --create.")
    base = plan_meta.get("base_branch") or cfg.get("base_branch")
    problem = gitops.safe_name(build, base or "")
    if problem:
        blockers.append("Build branch: %s Set branches.build in chopchop.yaml." % problem)

    repos = {}
    for tid in queue:
        name = str(by_id[tid].get("repo") or "")
        if name in repos:
            continue
        try:
            path, options = chopchop_code.repo_of(ws, cfg, name)
        except UsageError as e:
            blockers.append(str(e))
            continue
        info = {"path": str(path), "build_branch": build, "feature_branch": fb, "online": False, "exists": False}
        repos[name] = info
        if not gitops.is_repo(path):
            blockers.append("%s is not a git repo (%s). Fix its path in chopchop.yaml." % (name, path))
            continue
        info["online"] = gitops.has_remote(path)
        info["exists"] = gitops.local_branch_exists(path, build) or (info["online"] and gitops.remote_branch_exists(path, build))
        dirty = own_pending(path, ws)
        if dirty:
            blockers.append("%s has uncommitted or new files: %s. Commit, stash or remove them first."
                            % (name, ", ".join(x["path"] for x in dirty[:5])))
        if fb and not (gitops.local_branch_exists(path, fb) or (info["online"] and gitops.remote_branch_exists(path, fb))):
            blockers.append("The feature branch %s is not in %s. Run /chopchop:tasks --branch --create." % (fb, name))
        if not info["online"]:
            warnings.append("%s has no origin remote, so its build branch will not be pushed." % name)
        meta, _ = profile.load(ws, name)
        if meta is None or not meta.get("test"):
            blockers.append("chopchop does not know how to test %s. Run /chopchop:code --profile %s first." % (name, name))
        elif not meta.get("confirmed"):
            warnings.append("The %s profile is a draft. Its commands decide if a task passes." % name)
        missing = [s["file"] for s in chopchop_code.style_files(path, options, ws) if not s["exists"]]
        if missing:
            blockers.append("Style file %s (repos.%s.style) is not there. Fix the path." % (", ".join(missing), name))
    return {"feature": feature.name, "queue": queue, "left_out": left_out, "repos": repos, "titles":
            {tid: by_id[tid].get("title") for tid in queue}, "task_repo": {tid: by_id[tid].get("repo") for tid in queue},
            "feature_branch": fb, "base_branch": base, "build_branch": build, "settings": settings(cfg),
            "blockers": blockers, "warnings": warnings}


def plan_lines(ws, plan):
    s = plan["settings"]
    lines = ["Feature:  %s" % plan["feature"],
             "Order:    %s" % (" -> ".join("%s (%s)" % (t, plan["task_repo"][t]) for t in plan["queue"]) or "nothing")]
    lines += ["Left out: %s %s" % (x["task"], x["why"]) for x in plan["left_out"]]
    for name, r in plan["repos"].items():
        lines.append("Repo:     %s · %s %s from %s · %s" % (
            name, "resume" if r["exists"] else "new", r["build_branch"], r["feature_branch"],
            "pushed at the end" if r["online"] else "not pushed (no remote)"))
    pr = {"draft": "one draft PR per repo", "ready": "one PR per repo", "push": "you open one PR per repo"}[s["pr"]]
    lines.append("Review:   up to %d rounds per task%s" % (s["rounds"], ", reviewer model %s" % s["reviewer_model"]
                                                            if s["reviewer_model"] else ""))
    lines.append("PRs:      %s, into %s. Never into %s." % (pr, plan["feature_branch"] or "the feature branch",
                                                         plan["base_branch"] or "the base branch"))
    lines += ["Blocked:  %s" % b for b in plan["blockers"]]
    lines += ["Warning:  %s" % w for w in plan["warnings"]]
    return lines


def cmd_plan(args, ws):
    cfg = load_config(ws)
    feature = features.resolve(ws, args.plan or args.feature or "")
    plan = make_plan(ws, cfg, feature, args)
    lines = plan_lines(ws, plan)
    lines.append("Next:     %s" % ("fix what is blocked, then --plan again" if plan["blockers"] else
                                   "show this to the user, ask once, then --start with the same options"))
    emit(args, plan, lines)
    return 1 if plan["blockers"] else 0


def open_build_branch(path, build, fb, online):
    """Create the build branch from the latest feature branch, or resume it and bring that in."""
    git = chopchop_code.git
    if online:
        code, _, err = git(path, "fetch", "origin", fb)
        if code != 0:
            raise UsageError("Cannot fetch %s from origin in %s: %s" % (fb, path, err))
        git(path, "fetch", "origin", build)  # fine when it does not exist yet
    start = "origin/%s" % fb if online else fb
    if chopchop_code.current_branch(path) == build:
        action = "already on"
    elif gitops.local_branch_exists(path, build):
        git(path, "checkout", "-q", build, check=True)
        action = "switched to"
    elif online and git(path, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/" + build)[0] == 0:
        git(path, "checkout", "-q", "-b", build, "--track", "origin/" + build, check=True)
        action = "checked out"
    else:
        git(path, "checkout", "-q", "-b", build, "--no-track", start, check=True)
        return "created"
    if git(path, "merge-base", "--is-ancestor", start, "HEAD")[0] != 0:
        code, out, err = git(path, "merge", "--no-edit", "-q", start)
        if code != 0:
            conflicts = git(path, "diff", "--name-only", "--diff-filter=U")[1].split()
            git(path, "merge", "--abort")
            raise UsageError("Bringing the latest %s into %s conflicts in: %s. The merge was undone. A person "
                             "must resolve it." % (fb, build, ", ".join(conflicts) or err or out))
        action += ", merged the latest %s" % fb
    return action


def cmd_start(args, ws):
    cfg = load_config(ws)
    feature = features.resolve(ws, args.start or args.feature or "")
    run = Run(ws, cfg, feature)
    if run.state and not args.new and not run.state.get("finished"):
        open_ = [tid for tid, t in run.state["tasks"].items() if t["state"] in ACTIVE + ("queued",)]
        if open_:
            raise UsageError("A run is going for %s (%s still open). Carry on with --status, or add --new to "
                             "drop it and start again." % (feature.name, ", ".join(open_)))
    plan = make_plan(ws, cfg, feature, args)
    if plan["blockers"]:
        emit(args, plan, plan_lines(ws, plan) + ["Next:     fix what is blocked, then --start again"])
        return 1
    lines = []
    for name, r in plan["repos"].items():
        action = open_build_branch(Path(r["path"]), r["build_branch"], r["feature_branch"], r["online"])
        lines.append("Branch:   %s %s in %s" % (action, r["build_branch"], name))
    s = plan["settings"]
    run.state = {
        "version": 1, "feature": feature.name, "started": now(), "by": chopchop_code.me(None), "finished": None,
        "feature_branch": plan["feature_branch"], "base_branch": plan["base_branch"],
        "options": {"rounds": s["rounds"], "pr": s["pr"], "reviewer_model": s["reviewer_model"],
                    "step": bool(args.step), "max": args.max, "only": ids(args.only), "repo": args.repo},
        "repos": {n: {"path": r["path"], "build_branch": r["build_branch"], "online": r["online"],
                      "paused": None, "pushed": None, "pr": None} for n, r in plan["repos"].items()},
        "queue": plan["queue"], "current": None,
        "tasks": {tid: {"title": plan["titles"][tid], "repo": plan["task_repo"][tid], "state": "queued", "round": 0,
                        "asked": [], "asked_total": 0, "parked": [], "left": [], "fixed": 0} for tid in plan["queue"]},
        "left_out": plan["left_out"],
    }
    run.save()
    lines += ["Run:      %d tasks: %s" % (len(plan["queue"]), ", ".join(plan["queue"])),
              "Saved:    %s" % run.file, "Next:     --next"]
    emit(args, run.state, lines)
    return 0


# --------------------------------------------------------------------------- the loop


def skip(t, why):
    t.update(state="skipped", why=why, ended=now())


def pick_next(run, by_id):
    st = run.state
    for tid in st["queue"]:
        t = st["tasks"][tid]
        if t["state"] != "queued":
            continue
        if tid not in by_id:
            skip(t, "the task file is gone")
            continue
        paused = run.repo(t).get("paused")
        if paused:
            skip(t, "%s waits for %s" % (t["repo"], paused["task"]))
            continue
        deps = [d for d in tasklib.as_list(by_id[tid].get("depends_on")) if d in st["tasks"]]
        bad = [d for d in deps if st["tasks"][d]["state"] in ("stopped", "skipped")]
        if bad:
            skip(t, "needs %s, which %s" % (bad[0], st["tasks"][bad[0]]["state"]))
            continue
        if all(st["tasks"][d]["state"] == "committed" for d in deps):
            return tid
    return None


def write_brief(run, tid, ctx):
    d = run.dir(tid)
    st = run.state
    r = run.repo(st["tasks"][tid])
    log = 'python3 %s %s --log --change "<what changed>" --why "<why>" --feature %d --workspace %s' % (
        q(CODE_SCRIPTS / "chopchop_code.py"), tid, run.feature.number, q(run.ws))
    lines = ["# Build %s · %s" % (tid, ctx["title"]), "",
             "Build this one task. This brief and the task file are all you need.", "",
             "- Repo: %s at `%s`, on branch `%s`. It is checked out. Stay on it." % (ctx["repo"], ctx["repo_path"], r["build_branch"]),
             "- Task file: `%s`. Read all of it, the `## Code` part first." % ctx["task_file"],
             "- Files you may touch: %s" % (", ".join("`%s`" % p for p in ctx["touches"]) or "not listed: keep the change small")]
    lines += ["- Style file (follow it first): `%s`" % s["path"] for s in ctx["style"]] or [
        "- Style: no style file. Follow the code next to yours, then the profile rules."]
    lines += ["- Guide: `%s`" % (Path(ctx["repo_path"]) / g) for g in ctx["guides"]]
    if ctx["profile"]["exists"]:
        lines.append("- Profile (commands and rules): `%s`" % ctx["profile"]["path"])
    lines += ["- Check: `%s`" % run.verify_cmd(tid),
              "- Log a small drift from the task: `%s`" % log, ""]
    if ctx["changes"]:
        lines += ["## Changes that affect this task", ""]
        lines += ["- %s (from %s): %s" % (c["id"], c["task"] or "?", " / ".join(l for l in c["text"].splitlines() if l.strip()))
                  for c in ctx["changes"]]
        lines.append("")
    if ctx["heads_up"]:
        lines += ["## Heads-up", "", ctx["heads_up"], ""]
    built = [(x, st["tasks"][x]) for x in st["queue"] if st["tasks"][x]["state"] == "committed"]
    if built:
        lines += ["## Built earlier in this run", ""]
        lines += ["- %s (%s, %s) %s: %s" % (x, b["repo"], b.get("commit"), b["title"], b.get("note") or "no note")
                  for x, b in built]
        lines.append("")
    example = {"task": tid, "ok": True, "blocked": None, "files": ["path/of/each/file/you/changed"],
               "tests": ["the_test_names_you_wrote"],
               "notes": "1 to 3 lines later tasks need: what you added and where.",
               "commit": "%s <subject in this repo's commit style>" % tid}
    lines += ["## When you finish", "", "Write `%s`:" % (d / REPORT), "", "```json",
              json.dumps(example, indent=2), "```", "",
              "`blocked` is null, or one line on why the task cannot be built as written. Then stop."]
    (d / "brief.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d / "brief.md"


def cmd_next(args, ws):
    run = open_run(ws, args)
    st = run.state
    if st.get("current"):
        cur = st["current"]
        raise UsageError("%s is still %s. Next: %s" % (cur, st["tasks"][cur]["state"], next_step(run)))
    by_id = {t.id: t for t in tasklib.load_tasks(run.feature.path / tasklib.TASKS_DIR)}
    tid = pick_next(run, by_id)
    if tid is None:
        run.save()
        skipped = [(x, st["tasks"][x]) for x in st["queue"] if st["tasks"][x]["state"] == "skipped"]
        lines = ["Next:     nothing left to build."]
        lines += ["Skipped:  %s: %s" % (x, t["why"]) for x, t in skipped]
        lines.append("Then:     --finish")
        emit(args, {"next": None, "skipped": [x for x, _ in skipped]}, lines)
        return 0
    t = st["tasks"][tid]
    r = run.repo(t)
    path = Path(r["path"])
    if chopchop_code.current_branch(path) != r["build_branch"]:
        if own_pending(path, ws):
            raise UsageError("%s has uncommitted changes and is not on %s. A person must look first." % (t["repo"], r["build_branch"]))
        chopchop_code.git(path, "checkout", "-q", r["build_branch"], check=True)
    dirty = own_pending(path, ws)
    if dirty:
        raise UsageError("%s has uncommitted changes: %s. Each task starts from a clean tree. Commit or stash them, "
                         "then --next again." % (t["repo"], ", ".join(x["path"] for x in dirty[:5])))
    task = by_id[tid]
    ctx = chopchop_code.context(ws, run.cfg, run.feature, task)
    chopchop_code.set_status(ws, run.cfg, run.feature, tid,
                             status="in-progress" if task.get("status") == "todo" else KEEP,
                             owner=ctx["me"] if not task.get("owner") else KEEP)
    t.update(state="building", since=now(), started=now())
    st["current"] = tid
    brief = write_brief(run, tid, ctx)
    run.save()
    data = {"task": tid, "repo": t["repo"], "brief": str(brief), "report": str(run.dir(tid) / REPORT)}
    lines = ["Task:     %s %s (%s)" % (tid, t["title"], t["repo"]),
             "Brief:    %s" % brief,
             "Next:     start chopchop:builder with the brief. When it is back: --review %s" % tid]
    emit(args, data, lines)
    return 0


def stop(run, tid, why, args):
    st = run.state
    t = st["tasks"][tid]
    r = run.repo(t)
    t.update(state="stopped", why=why, ended=now())
    r["paused"] = {"task": tid, "why": why}
    if st.get("current") == tid:
        st["current"] = None
    run.save()
    lines = ["Stopped:  %s: %s" % (tid, why),
             "Waits:    %s. Its changes stay uncommitted on %s for a person. The other repos go on."
             % (t["repo"], r["build_branch"]),
             "Next:     %s" % next_step(run)]
    emit(args, {"task": tid, "state": "stopped", "why": why}, lines)
    return 1


def cmd_review(args, ws):
    run = open_run(ws, args)
    tid, t = run.task(args.review, ("building", "fixing"))
    report = read_report(run, tid)
    if report.get("blocked"):
        return stop(run, tid, "the builder could not build it as written: %s" % report["blocked"], args)
    v = read_verify(run.feature, tid)
    if not v or str(v.get("when", "")) < t["since"]:
        raise UsageError("No check of %s since it was built. Run: %s, then --review %s again."
                         % (tid, run.verify_cmd(tid), tid))
    if not v.get("ok"):
        return stop(run, tid, "the checks still fail after the builder's tries", args)
    path = Path(run.repo(t)["path"])
    files = own_pending(path, ws)
    if not files:
        return stop(run, tid, "the builder changed nothing", args)
    task = run.task_file(tid)
    ctx = chopchop_code.context(ws, run.cfg, run.feature, task)
    t["round"] += 1
    info = {"repo": t["repo"], "repo_path": str(path), "mode": "pending", "base": None, "files": files,
            "round": t["round"], "task": review.task_rules(task), "task_file": str(task.path),
            "style": [s["path"] for s in ctx["style"] if s["exists"]],
            "guides": [str(path / g) for g in ctx["guides"]],
            "profile": ctx["profile"]["path"] if ctx["profile"]["exists"] else None,
            "parked": [review.one_line(p) for p in t["parked"]], "fixed_last": t["asked"]}
    pack = review.write_pack(run.dir(tid) / ("review-%d" % t["round"]), info, review.pending_diff(path, files))
    t.update(state="reviewing", pack=str(pack))
    run.save()
    model = run.state["options"].get("reviewer_model")
    data = {"task": tid, "round": t["round"], "pack": str(pack), "findings": str(pack.parent / review.FINDINGS),
            "reviewer_model": model}
    lines = ["Review:   %s round %d · %d files" % (tid, t["round"], len(files)),
             "Pack:     %s" % pack,
             "Next:     start chopchop:code-reviewer with the pack%s. When it is back: --sort %s"
             % (" (model: %s)" % model if model else "", tid)]
    emit(args, data, lines)
    return 0


def write_fix(path, tid, round_no, fixes, parked, verify):
    lines = ["# Fix %s · review round %d" % (tid, round_no), "",
             "Fix each item, inside the task's files. Then run the check again:", "", "`%s`" % verify, ""]
    lines += ["%d. %s" % (n, review.one_line(f)) for n, f in enumerate(fixes, 1)]
    if parked:
        lines += ["", "## Parked, do not do", "", "These change the direction. The spec decides, so leave them.", ""]
        lines += ["- %s" % review.one_line(p) for p in parked]
    lines += ["", "When the check passes, update `notes` in report.json if what you built changed."]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def ask_fix(run, tid, t, fixes, name):
    fix_file = run.dir(tid) / name
    write_fix(fix_file, tid, t["round"], fixes, t["parked"], run.verify_cmd(tid))
    t.update(state="fixing", since=now(), fix=str(fix_file), asked=[review.one_line(f) for f in fixes])
    t["asked_total"] += len(fixes)
    return fix_file


def cmd_sort(args, ws):
    run = open_run(ws, args)
    tid, t = run.task(args.sort, ("reviewing",))
    folder = Path(t["pack"]).parent
    info = json.loads((folder / review.PACK_JSON).read_text(encoding="utf-8"))
    result = review.sort(review.load_findings(folder / review.FINDINGS), info.get("task"),
                         [f["path"] for f in info.get("files", [])])
    (folder / review.SORTED).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    seen = {(p.get("file"), p["what"]) for p in t["parked"]}
    for p in result["park"]:
        if (p.get("file"), p["what"]) not in seen:
            t["parked"].append(dict(p, round=t["round"]))
    head = "Sorted:   %d fix, %d park, %d stop" % (len(result["fix"]), len(result["park"]), len(result["stop"]))
    if result["stop"]:
        if not args.json:
            print(head)
        return stop(run, tid, "the review found something a person must decide: %s" % review.one_line(result["stop"][0]), args)
    fixes = result["fix"]
    rounds = run.state["options"]["rounds"]
    data = {"task": tid, "round": t["round"], "fix": len(fixes), "park": len(result["park"])}
    if fixes and t["round"] < rounds:
        fix_file = ask_fix(run, tid, t, fixes, "fix-%d.md" % t["round"])
        run.save()
        lines = [head, "Fix:      %s" % fix_file,
                 "Next:     send the fix list to the same builder, or a new one with the brief. When it is back: --review %s" % tid]
        emit(args, dict(data, action="fix", fix_file=str(fix_file)), lines)
        return 0
    t["left"] = [review.one_line(f) for f in fixes]
    t["state"] = "ready"
    run.save()
    lines = [head]
    if fixes:
        lines.append("Left:     %d fix items, no rounds left. They go in the PR text for a person." % len(fixes))
    lines.append("Next:     --commit %s" % tid)
    emit(args, dict(data, action="commit"), lines)
    return 0


def cmd_commit(args, ws):
    run = open_run(ws, args)
    tid, t = run.task(args.commit, ("ready",))
    v = read_verify(run.feature, tid)
    if not v or not v.get("ok") or str(v.get("when", "")) < t["since"]:
        raise UsageError("%s has no passing check since its last change. Run: %s" % (tid, run.verify_cmd(tid)))
    r = run.repo(t)
    path = Path(r["path"])
    files = own_pending(path, ws)
    if not files:
        raise UsageError("Nothing to commit for %s in %s." % (tid, t["repo"]))
    rules = review.task_rules(run.task_file(tid))
    stray = review.outside([f["path"] for f in files], rules, ids_or_paths(args.outside))
    if stray:
        lines = ["Outside:  %s changed files its task does not list: %s" % (tid, ", ".join(stray)),
                 "Next:     ask the builder to undo them. If the task truly needs them, it logs the change with "
                 "--log, then --commit %s --outside %s" % (tid, ",".join(stray))]
        emit(args, {"task": tid, "outside": stray}, lines)
        return 1
    banned = review.banned_uses(review.pending_diff(path, files), rules)
    if banned:
        fixes = [{"file": "", "line": None, "kind": "scope", "severity": "medium",
                  "what": "The change uses %s, which the task says not to use" % n,
                  "fix": "Use what the task's Code part says instead."} for n in banned]
        fix_file = ask_fix(run, tid, t, fixes, "fix-not-allowed.md")
        run.save()
        lines = ["Not allowed: the change uses %s, which the task says not to use." % ", ".join(banned),
                 "Fix:      %s" % fix_file,
                 "Next:     send the fix list to the builder. When it is back: --review %s" % tid]
        emit(args, {"task": tid, "banned": banned, "fix_file": str(fix_file)}, lines)
        return 1
    report = read_report(run, tid)
    subject = (args.message or report.get("commit") or "%s %s" % (tid, t["title"])).strip().splitlines()[0]
    if tid not in subject:
        subject = "%s %s" % (tid, subject)
    git = chopchop_code.git
    git(path, "add", "-A", "--", *[f["path"] for f in files], check=True)
    code, out, err = git(path, "commit", "-q", "-m", subject)
    if code != 0:
        lines = ["Commit:   failed in %s: %s" % (t["repo"], (err or out).strip()[-1500:]),
                 "Next:     treat it like a failed check: send it to the builder, then --commit %s again" % tid]
        emit(args, {"task": tid, "error": err or out}, lines)
        return 1
    sha = git(path, "rev-parse", "--short", "HEAD")[1]
    t.update(state="committed", commit=sha, subject=subject, note=str(report.get("notes") or "").strip(),
             tests=report.get("tests") or [], ended=now(), fixed=max(0, t["asked_total"] - len(t["left"])))
    run.state["current"] = None
    run.save()
    lines = ["Commit:   %s %s on %s · %s" % (tid, sha, r["build_branch"], subject),
             "Review:   %d fixed, %d parked, %d left" % (t["fixed"], len(t["parked"]), len(t["left"]))]
    if run.state["options"].get("step"):
        lines.append("Pause:    --step is on. Show the user what %s did and wait for a go." % tid)
    lines.append("Next:     %s" % next_step(run))
    emit(args, {"task": tid, "commit": sha, "subject": subject, "fixed": t["fixed"], "parked": len(t["parked"]),
                "left": len(t["left"])}, lines)
    return 0


def ids_or_paths(text):
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def cmd_stop(args, ws):
    run = open_run(ws, args)
    if not (args.why or "").strip():
        raise UsageError('--stop needs --why "the reason".')
    tid, t = run.task(args.stop, ACTIVE + ("queued",))
    if t["state"] == "queued":
        skip(t, args.why.strip())
        run.save()
        emit(args, {"task": tid, "state": "skipped"}, ["Skipped:  %s: %s" % (tid, args.why.strip()),
                                                        "Next:     %s" % next_step(run)])
        return 0
    return stop(run, tid, args.why.strip(), args)


# --------------------------------------------------------------------------- finish


def feature_title(feature):
    return feature.meta.get("title") or feature.slug.replace("-", " ")


def pr_text(run, name, done):
    st, feature = run.state, run.feature
    title = "%s: %s (%s)" % (feature.epic or "%03d" % feature.number, feature_title(feature), name)
    tasks = st["tasks"]
    lines = ["# %s" % title, "",
             "Built by /chopchop:auto from the task files, one commit per task. Each task passed its checks and a "
             "review before its commit.", "", "## Tasks", ""]
    for tid in done:
        t = tasks[tid]
        lines.append("- **%s** %s · `%s` · review: %d fixed, %d parked" % (tid, t["title"], t["commit"], t["fixed"],
                                                                           len(t["parked"])))
        if t.get("note"):
            lines.append("  %s" % t["note"])
    parked = [(tid, p) for tid in done for p in tasks[tid]["parked"]]
    if parked:
        lines += ["", "## Review ideas not done (the spec decides)", "",
                  "These would change the direction, so they were not applied. Raise them with the lead.", ""]
        lines += ["- %s · %s" % (tid, review.one_line(p)) for tid, p in parked]
    left = [(tid, x) for tid in done for x in tasks[tid]["left"]]
    if left:
        lines += ["", "## Left for a person", "", "Found in the last review round, with no rounds left.", ""]
        lines += ["- %s · %s" % (tid, x) for tid, x in left]
    log = tasklib.read_changelog(feature.path / tasklib.TASKS_DIR / tasklib.CHANGELOG_FILE)
    changed = [c for c in log if c["task"] in done]
    if changed:
        lines += ["", "## Changes from the plan", ""]
        lines += ["- %s (%s): %s" % (c["id"], c["task"], " / ".join(l for l in c["text"].splitlines() if l.strip()))
                  for c in changed]
    steps = []
    for tid in done:
        for s in (read_verify(feature, tid) or {}).get("steps", []):
            if s.get("ok") and "`%s`" % s["command"] not in steps:
                steps.append("`%s`" % s["command"])
    if steps:
        lines += ["", "## How it was tested", ""] + ["- %s passed" % s for s in steps]
    other = [(x, t) for x, t in tasks.items() if t["repo"] == name and t["state"] in ("stopped", "skipped")]
    if other:
        lines += ["", "## Not in this PR", ""] + ["- %s %s: %s" % (x, t["state"], t.get("why")) for x, t in other]
    return title, "\n".join(lines) + "\n"


def cmd_finish(args, ws):
    run = open_run(ws, args)
    st = run.state
    if st.get("current"):
        cur = st["current"]
        raise UsageError("%s is still %s. Finish it or --stop it first. Next: %s" % (cur, st["tasks"][cur]["state"], next_step(run)))
    by_id = {t.id: t for t in tasklib.load_tasks(run.feature.path / tasklib.TASKS_DIR)}
    waiting = pick_next(run, by_id)
    if waiting:
        run.save()
        raise UsageError("%s can still be built. Run --next, or --stop %s --why \"...\" to leave it out." % (waiting, waiting))
    rows, lines = [], []
    for name, r in st["repos"].items():
        done = [x for x in st["queue"] if st["tasks"][x]["repo"] == name and st["tasks"][x]["state"] == "committed"]
        row = {"repo": name, "branch": r["build_branch"], "into": st["feature_branch"], "commits": len(done)}
        rows.append(row)
        if r.get("paused"):
            row["result"] = "not pushed: waits for %s (%s)" % (r["paused"]["task"], r["paused"]["why"])
        elif not done:
            row["result"] = "nothing committed"
        else:
            title, body = pr_text(run, name, done)
            pr_file = run.work / RUN_DIR / ("pr-%s.md" % name)
            pr_file.parent.mkdir(parents=True, exist_ok=True)
            pr_file.write_text(body, encoding="utf-8")
            row.update(title=title, pr_file=str(pr_file))
            if not r["online"]:
                row["result"] = "not pushed: no origin remote"
            else:
                code, out, err = chopchop_code.git(Path(r["path"]), "push", "-u", "origin", r["build_branch"])
                if code != 0:
                    row["result"] = "push failed: %s" % ((err or out).strip().splitlines() or ["no output"])[-1]
                else:
                    r["pushed"] = now()
                    row["result"] = "pushed"
        lines.append("%-14s %s · %s (%d commits)%s" % (name, row["result"], r["build_branch"], len(done),
                                                       " · PR text: %s" % row["pr_file"] if row.get("pr_file") else ""))
    if all(not r.get("paused") for r in st["repos"].values()):
        st["finished"] = now()
    run.save()
    mode = st["options"]["pr"]
    pushed = [x for x in rows if x.get("result") == "pushed"]
    if pushed and mode != "push":
        lines.append("PRs:      open a %sPR from each pushed build branch into %s, with the title and text from its PR "
                     "file. Then --pr <repo> <url>." % ("draft " if mode == "draft" else "", st["feature_branch"]))
    elif pushed:
        lines.append("PRs:      the user opens them (auto.pr is push). Give them the branches and the PR files.")
    emit(args, {"repos": rows, "pr_mode": mode}, lines)
    return 0


def cmd_pr(args, ws):
    run = open_run(ws, args)
    name, url = args.pr
    r = run.state["repos"].get(name)
    if r is None:
        raise UsageError("%s is not in this run. Repos: %s" % (name, ", ".join(run.state["repos"])))
    r["pr"] = url
    done = [x for x in run.state["queue"] if run.state["tasks"][x]["repo"] == name
            and run.state["tasks"][x]["state"] == "committed"]
    for tid in done:
        chopchop_code.set_status(ws, run.cfg, run.feature, tid, status="in-review", pr=url)
    run.save()
    emit(args, {"repo": name, "pr": url, "tasks": done},
         ["PR:       %s · %s" % (name, url), "Review:   %s now in review" % (", ".join(done) or "no task"),
          "Next:     %s" % next_step(run)])
    return 0


# --------------------------------------------------------------------------- status


def next_step(run):
    st = run.state
    cur = st.get("current")
    if cur:
        t = st["tasks"][cur]
        d = run.work / RUN_DIR / cur
        if t["state"] == "building":
            if (d / REPORT).is_file():
                return "--review %s" % cur
            return "start chopchop:builder with %s, then --review %s" % (d / "brief.md", cur)
        if t["state"] == "reviewing":
            if (Path(t["pack"]).parent / review.FINDINGS).is_file():
                return "--sort %s" % cur
            return "start chopchop:code-reviewer with %s, then --sort %s" % (t["pack"], cur)
        if t["state"] == "fixing":
            return "send %s to the builder, then --review %s" % (t["fix"], cur)
        return "--commit %s" % cur
    if any(t["state"] == "queued" for t in st["tasks"].values()):
        return "--next"
    unpushed = [n for n, r in st["repos"].items() if not r.get("pushed") and not r.get("paused") and any(
        t["repo"] == n and t["state"] == "committed" for t in st["tasks"].values())]
    if unpushed and not st.get("finished"):
        return "--finish"
    no_pr = [n for n, r in st["repos"].items() if r.get("pushed") and not r.get("pr")]
    if no_pr and st["options"]["pr"] != "push":
        return "open the PR for %s, then --pr <repo> <url>" % ", ".join(no_pr)
    paused = [r["paused"]["task"] for r in st["repos"].values() if r.get("paused")]
    if paused:
        return "a person decides on %s. Then plan a new run." % ", ".join(paused)
    return "nothing. The run is done. A person reviews and merges the PRs."


def cmd_status(args, ws):
    run = open_run(ws, args)
    st = run.state
    o = st["options"]
    lines = ["Run:      %s · started %s · up to %d review rounds · PR %s%s" % (
        st["feature"], st["started"], o["rounds"], o["pr"], " · step" if o.get("step") else "")]
    for name, r in st["repos"].items():
        n = sum(1 for t in st["tasks"].values() if t["repo"] == name and t["state"] == "committed")
        extra = " · waits for %s" % r["paused"]["task"] if r.get("paused") else ""
        extra += " · pushed" if r.get("pushed") else ""
        extra += " · PR %s" % r["pr"] if r.get("pr") else ""
        lines.append("Repo:     %s · %s · %d committed%s" % (name, r["build_branch"], n, extra))
    for tid in st["queue"]:
        t = st["tasks"][tid]
        if t["state"] == "committed":
            detail = "%s · %d fixed · %d parked%s" % (t["commit"], t["fixed"], len(t["parked"]),
                                                      " · %d left" % len(t["left"]) if t["left"] else "")
        elif t["state"] in ("stopped", "skipped"):
            detail = t.get("why") or ""
        elif t["round"]:
            detail = "round %d" % t["round"]
        else:
            detail = ""
        lines.append("  %-4s %-14s %-10s %s" % (tid, t["repo"], t["state"], detail))
    lines.append("Next:     %s" % next_step(run))
    emit(args, dict(st, next=next_step(run)), lines)
    return 0


# --------------------------------------------------------------------------- main


ACTIONS = ["plan", "start", "next", "review", "sort", "commit", "stop", "finish", "pr", "status"]


def build_parser():
    p = argparse.ArgumentParser(prog="chopchop_auto.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan", nargs="?", const="", metavar="REF", help="what a run would do, changes nothing")
    p.add_argument("--start", nargs="?", const="", metavar="REF", help="make the build branches and the run")
    p.add_argument("--next", action="store_true", help="pick the next task and write its brief")
    p.add_argument("--review", metavar="TASK", help="check the build, then write the review pack")
    p.add_argument("--sort", metavar="TASK", help="sort the review into fix, park and stop")
    p.add_argument("--commit", metavar="TASK", help="commit the task on its build branch")
    p.add_argument("--stop", metavar="TASK", help="stop a task (with --why)")
    p.add_argument("--finish", action="store_true", help="push the build branches and write the PR texts")
    p.add_argument("--pr", nargs=2, metavar=("REPO", "URL"), help="record a repo's PR")
    p.add_argument("--status", action="store_true", help="where the run is, and the next step")
    p.add_argument("--max", type=int, metavar="N", help="with --plan or --start: at most N tasks")
    p.add_argument("--only", metavar="IDS", help="with --plan or --start: only these tasks, e.g. T01,T02")
    p.add_argument("--repo", metavar="NAME", help="with --plan or --start: only this repo's tasks")
    p.add_argument("--step", action="store_true", help="with --start: pause after each task")
    p.add_argument("--new", action="store_true", help="with --start: drop an open run and start again")
    p.add_argument("--why", help="with --stop: the reason")
    p.add_argument("--message", help="with --commit: the commit subject")
    p.add_argument("--outside", metavar="FILES", help="with --commit: files outside the task that it may commit")
    p.add_argument("--feature", metavar="REF", help="feature number, epic key or name")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="path to the _chopchop folder")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    chosen = [a for a in ACTIONS if getattr(args, a) not in (None, False)]
    try:
        if len(chosen) != 1:
            raise UsageError("Use one of --%s." % ", --".join(ACTIONS))
        if args.max is not None and args.max < 1:
            raise UsageError("--max must be 1 or more.")
        ws = find_workspace(args.workspace)
        return globals()["cmd_" + chosen[0]](args, ws)
    except (UsageError, ConfigError, FeatureError, gitops.GitError, review.ReviewError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
