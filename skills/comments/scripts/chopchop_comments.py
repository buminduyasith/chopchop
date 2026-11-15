#!/usr/bin/env python3
"""chopchop comments: explain the review comments on a feature's PRs, plan the fixes, draft the replies.

Usage
  chopchop_comments.py --prs [REF]                         find the feature and list its PRs
  chopchop_comments.py --pr URL [--repo NAME] [--path DIR] add a PR (to --feature REF, or as a loose PR)
  chopchop_comments.py --fetch [REF]                       read PR state and every review comment with gh
  chopchop_comments.py --ingest FILE                       take what another tool fetched (shape: SCHEMA.md)
  chopchop_comments.py --pack [REF] [--all] [--again IDS]  write pack.md for the triager
  chopchop_comments.py --triage FILE                       check the triager's answer, merge it, write comments.md
  chopchop_comments.py --decide TARGET fix|reply|skip      the person's call. TARGET: a thread id, G1, all-real, all
  chopchop_comments.py --plan                              cut the fix batches and write a brief for each
  chopchop_comments.py --commit B1 --message "..."         commit a batch on the PR's own branch
  chopchop_comments.py --push REPO                         push that branch to its upstream, never forced
  chopchop_comments.py --fixed B1 [--commit SHA]           mark a batch fixed
  chopchop_comments.py --replies                           the reply drafts, ready to paste
  chopchop_comments.py --post [IDS] --yes                  post replies with gh. Refuses without --yes
  chopchop_comments.py --wait [--every 60] [--for 1800]    block until a new comment arrives
  chopchop_comments.py --watch on|off                      the watch flag the dashboard shows
  chopchop_comments.py --status                            counts, and the next step

REF is a feature (number, key, part of the name), a PR link, or a loose PR folder name. With no REF:
the feature whose branch is checked out where you are, else the only one that has PRs.
--wait exits 0 when something is new, 2 when every PR is merged or closed, 3 when nothing came in time.
Options: --feature REF, --force, --outside FILES, --json, --workspace PATH.

It never opens, merges or closes a PR, and never force-pushes. Needs the tasks skill next to it.
Standard library only. Python 3.8+.
"""

import argparse
import json
import posixpath
import re
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
TASKS_SCRIPTS = SKILLS / "tasks" / "scripts"
if not (TASKS_SCRIPTS / "chopchoplib" / "events.py").is_file():
    sys.exit("Error: comments needs the tasks skill next to it (%s not found)." % TASKS_SCRIPTS)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TASKS_SCRIPTS))

from chopchoplib import events, features, gitops, review  # noqa: E402
from chopchoplib import tasks as tasklib  # noqa: E402
from chopchoplib.config import ConfigError, find_workspace, git_toplevel, load_config  # noqa: E402
from chopchoplib.features import FeatureError  # noqa: E402
from commentslib import hosts, report, schema, similar, store as storelib, triage  # noqa: E402
from commentslib.store import UsageError, now  # noqa: E402

REVIEW_SCRIPT = SKILLS / "review" / "scripts" / "chopchop_review.py"
AROUND = 12  # lines of code shown above and below a commented line
TEST_FILE = re.compile(r"(^test_.*\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$|Tests?\.(java|kt|cs)$|_spec\.rb$|Test\.php$)")
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs"}
GUIDES = ["CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md"]


def emit(args, data, lines):
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n".join(lines))


def plural(n, word):
    many = {"batch": "batches", "reply": "replies"}.get(word, word + "s")
    return "%d %s" % (n, word if n == 1 else many)


class Lock:
    """One writer at a time: --wait runs in the background while other calls change the same files."""

    def __init__(self, store):
        self.path, self.fh = store.dir / ".lock", None

    def __enter__(self):
        try:
            import fcntl
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(str(self.path), "a")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except (ImportError, OSError):
            self.fh = None
        return self

    def __exit__(self, *exc):
        if self.fh:
            self.fh.close()
        return False


# --------------------------------------------------------------------------- config and repos


def load_cfg(ws):
    """chopchop.yaml, or nothing: a loose PR works in a folder that has no workspace yet."""
    try:
        return load_config(ws)
    except ConfigError:
        if (Path(ws) / "chopchop.yaml").exists():
            raise
        return {}


def cfg_repos(cfg, ws):
    out = {}
    repos = cfg.get("repos")
    if isinstance(repos, dict):
        for name, value in repos.items():
            p = Path(str((value.get("path") if isinstance(value, dict) else value) or ".")).expanduser()
            out[str(name)] = p if p.is_absolute() else (Path(ws).parent / p).resolve()
    return out


def origin_is(path, slug):
    code, out, _ = gitops.git(path, "remote", "get-url", "origin")
    url = re.sub(r"\.git$", "", out.strip().lower())
    return code == 0 and bool(slug) and (url.endswith("/" + slug.lower()) or url.endswith(":" + slug.lower()))


def repo_path(store, cfg, pr):
    """Where the PR's repo is checked out on this machine, or None."""
    if pr.get("path"):
        return Path(pr["path"])
    r = (store.auto().get("repos") or {}).get(pr.get("repo"))
    if isinstance(r, dict) and r.get("path"):
        return Path(r["path"])
    known = cfg_repos(cfg, store.ws)
    if pr.get("repo") in known:
        return known[pr["repo"]]
    for base in (Path.cwd(), store.ws.parent):
        top = git_toplevel(base) if base.is_dir() else None
        if top and origin_is(top, pr.get("slug")):
            return top
    return None


def checkout(store, cfg, pr):
    """The repo path of a PR, or a UsageError that says how to tell chopchop where it is."""
    path = repo_path(store, cfg, pr)
    if path is None or not gitops.is_repo(path):
        raise UsageError("chopchop does not know where %s is checked out. Say where: --pr %s --path <folder>"
                         % (pr["repo"], pr["url"]))
    return Path(path)


def own_pending(path, ws):
    """Pending changes in a repo, leaving out the chopchop workspace when it lives inside it."""
    items = review.pending(path)
    try:
        inside = Path(ws).resolve().relative_to(Path(path).resolve())
    except ValueError:
        return items
    prefix = str(inside).replace("\\", "/").rstrip("/") + "/"
    return [x for x in items if not (x["path"] + "/").startswith(prefix)]


def unsafe_branch(name, base):
    if not name or name == base or name.lower() in gitops.PROTECTED:
        return "'%s' is %s. chopchop never commits or pushes there." % (
            name, "the PR's base branch" if name and name == base else "a protected branch")
    return None


def write_report(store):
    store.report.parent.mkdir(parents=True, exist_ok=True)
    store.report.write_text(report.render_report(store), encoding="utf-8")


def need_prs(store):
    if not store.prs["prs"]:
        raise UsageError("%s has no PR yet. Open the PRs with /chopchop:auto, or add one: --pr <link>." % store.name)


def targets_of(store, text):
    """Thread ids for a target: thread ids and group ids, split by commas."""
    threads, out = store.by_id(), []
    groups = {g["id"]: g for g in store.triage["groups"]}
    for part in [p.strip() for p in str(text or "").split(",") if p.strip()]:
        if part.upper() in groups:
            out += [t for t in groups[part.upper()]["threads"] if t in threads]
        elif part in threads:
            out.append(part)
        else:
            raise UsageError("'%s' is not a thread id or a group. Groups: %s. Thread ids are in comments.md."
                             % (part, ", ".join(groups) or "none yet"))
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------------- prs


def add_pr(store, cfg, url, repo=None, path=None):
    parsed = storelib.parse_pr_url(url)
    key = storelib.url_key(url)
    entry = next((p for p in store.prs["prs"] if storelib.url_key(p.get("url")) == key), None)
    added = entry is None
    if entry is None:
        entry = storelib.new_pr(parsed, repo or storelib.pick_repo_name(parsed, list(cfg_repos(cfg, store.ws))))
        if store.pr(entry["id"]):
            raise UsageError("%s is already the id of %s. Give this one another repo name: --repo <name>."
                             % (entry["id"], store.pr(entry["id"])["url"]))
        store.prs["prs"].append(entry)
    if path:
        full = Path(path).expanduser().resolve()
        if not gitops.is_repo(full):
            raise UsageError("%s is not a git repo." % full)
        entry["path"] = str(full)
    return entry, added


def cmd_pr(args, ws):
    cfg = load_cfg(ws)
    ref = args.feature or (args.prs or None)
    store = storelib.find_store(ws, ref) if ref else storelib.find_store(ws, args.pr, create=True)
    with Lock(store):
        store.reload()
        storelib.sync_prs(store, list(cfg_repos(cfg, ws)))
        entry, added = add_pr(store, cfg, args.pr, args.repo, args.path)
        store.save_prs()
    if added:
        events.log(store.root, "pr", "%s is watched for review comments." % entry["id"], repo=entry["repo"])
    lines = ["%s %s · %s" % ("Added:   " if added else "Known:   ", entry["id"], entry["url"]),
             "Store:    %s" % store.dir]
    if entry["host"] != "github":
        lines.append("Host:     %s. gh cannot read it: fetch with the team's tool, then --ingest <file>." % entry["host"])
    lines.append("Next:     --fetch %s" % store.ref)
    emit(args, {"pr": entry, "added": added, "store": str(store.dir), "ref": store.ref}, lines)
    return 0


def cmd_prs(args, store, cfg):
    added = storelib.sync_prs(store, list(cfg_repos(cfg, store.ws)))
    if added:
        store.save_prs()
    prs = store.prs["prs"]
    lines = ["Feature:  %s" % store.name]
    if not prs:
        lines += ["PRs:      none yet.", "Next:     open the PRs with /chopchop:auto, or add one: --pr <link>"]
        emit(args, {"store": store.name, "prs": []}, lines)
        return 1
    for p in prs:
        lines.append("PR:       %s · %s%s · %s%s" % (
            p["id"], p.get("state") or "?", "" if p.get("fetched") else " (not read yet)", p["url"],
            " · new here" if p["id"] in added else ""))
    lines.append("Next:     --fetch %s" % store.ref)
    emit(args, {"store": store.name, "ref": store.ref, "prs": prs, "added": added}, lines)
    return 0


# --------------------------------------------------------------------------- fetch and ingest


def read_host(store, cfg):
    """Read every GitHub PR that is not merged yet. Raises GhError before anything is stored."""
    todo = [p for p in store.prs["prs"] if p.get("host") == "github" and not (p.get("state") == "merged" and p.get("fetched"))]
    for server in sorted({hosts.server_of(p) for p in todo}):
        why = hosts.ready(server)
        if why:
            raise hosts.GhError("%s. Fetch the comments with another connected tool, then pass --ingest <file> "
                                "(the shape is in SCHEMA.md)." % why)
    rules = cfg.get("comments") if isinstance(cfg.get("comments"), dict) else {}
    snaps, me = [], None
    for p in todo:
        raw = hosts.fetch(p)
        fields, threads, left = hosts.normalise(p, raw, rules.get("ignore") or (), rules.get("keep") or ())
        me = me or raw.get("me")
        snaps.append({"id": p["id"], "fields": fields, "threads": threads, "left": left})
    return snaps, me


def mark_done(store, cfg, pr):
    """A merged PR finishes its tasks: the ones its auto run committed in that repo, and the ones that carry its link."""
    feature = store.feature
    if feature is None:
        events.log(store.root, "merge", "%s is merged." % pr["id"], repo=pr["repo"])
        return []
    key = storelib.url_key(pr["url"])
    auto = store.auto()
    ids = set()
    r = (auto.get("repos") or {}).get(pr["repo"])
    if isinstance(r, dict) and r.get("pr") and storelib.url_key(r["pr"]) == key:
        ids |= {tid for tid, t in (auto.get("tasks") or {}).items()
                if isinstance(t, dict) and t.get("repo") == pr["repo"] and t.get("state") == "committed"}
    found = tasklib.load_tasks(feature.path / tasklib.TASKS_DIR)
    ids |= {t.id for t in found if t.get("pr") and storelib.url_key(t.get("pr")) == key}
    done = []
    for t in found:
        if t.id in ids and t.get("status") != "done":
            t.meta["status"] = "done"
            t.save()
            done.append(t.id)
    if done:
        try:  # the same refresh /chopchop:code runs after a status change: plan.md and status.md
            import chopchop_tasks
            chopchop_tasks.refresh(store.ws, feature, cfg)
        except Exception:  # noqa: BLE001  the task files are already right
            pass
    events.log(feature, "merge", "%s is merged.%s" % (pr["id"], " Done: %s." % ", ".join(done) if done else ""),
               repo=pr["repo"])
    return done


def apply(store, cfg, snaps, me, write_threads=True):
    """Put fresh PR snapshots into the store and save. Returns what a person wants to hear about."""
    known = {t["id"] for t in store.new_threads()}
    before = json.dumps(store.threads["threads"], sort_keys=True)
    merged, left = [], {"own": 0, "bots": 0}
    for snap in snaps:
        pr = store.pr(snap["id"])
        if pr is None:
            continue
        was = pr.get("state") if pr.get("fetched") else None
        pr.update(snap["fields"], fetched=now(), threads=len(snap["threads"]))
        if pr["state"] == "merged" and was != "merged":
            merged.append(pr)
        store.threads["threads"] = [t for t in store.threads["threads"] if t["pr"] != pr["id"]] + snap["threads"]
        for k in left:
            left[k] += snap["left"].get(k, 0)
    order = {p["id"]: n for n, p in enumerate(store.prs["prs"])}
    store.threads["threads"].sort(key=lambda t: order.get(t["pr"], len(order)))
    changed = before != json.dumps(store.threads["threads"], sort_keys=True)
    ours = {me} if me else {p.get("author") for p in store.prs["prs"]}
    rec = triage.reconcile(store, ours)
    done = {pr["id"]: mark_done(store, cfg, pr) for pr in merged}
    store.save_prs()
    if changed or write_threads or not (store.dir / storelib.THREADS).is_file():
        store.threads["fetched"] = now()
        store.save_threads()
    if rec["closed"] or rec["replied"]:
        store.save_triage()
    new = store.new_threads()
    fresh = [t for t in new if t["id"] not in known]
    if fresh:
        events.log(store.root, "comment", "%s: %s" % (plural(len(fresh), "new review comment"),
                                                      ", ".join(t["id"] for t in fresh[:6])))
    if changed or rec["closed"] or rec["replied"] or merged or not store.report.is_file():
        write_report(store)
    return {"new": new, "fresh": fresh, "merged": done, "left": left, "closed": rec["closed"], "replied": rec["replied"]}


def fetch_lines(store, result):
    lines = []
    for p in store.prs["prs"]:
        mine = [t for t in store.threads["threads"] if t["pr"] == p["id"]]
        settled = sum(1 for t in mine if t.get("resolved"))
        lines.append("PR:       %s · %s%s · %s · %s%s%s" % (
            p["id"], p.get("state") or "?", ", draft" if p.get("draft") else "",
            report.REVIEW_WORDS.get(p.get("review"), "?"), plural(len(mine), "comment"),
            " (%d settled)" % settled if settled else "", "" if p.get("fetched") else " · not read yet"))
        if p.get("host") != "github" and not p.get("fetched"):
            lines.append("Host:     %s is on %s. gh cannot read it: fetch with the team's tool, then --ingest <file>."
                         % (p["id"], p.get("host")))
    left = result["left"]
    if left["own"] or left["bots"]:
        lines.append("Left out: %d by the author only, %d bot status report(s). They are not review comments."
                     % (left["own"], left["bots"]))
    for pid, done in result["merged"].items():
        lines.append("Merged:   %s is merged.%s" % (pid, " Done now: %s." % ", ".join(done) if done else ""))
    if result["replied"]:
        lines.append("Answered: %s. The last word there is yours." % ", ".join(result["replied"]))
    lines += ["New:      %s" % report.new_line(t) for t in result["new"]]
    return lines


def result_data(store, result):
    return {"store": store.name, "ref": store.ref, "prs": store.prs["prs"], "new": [t["id"] for t in result["new"]],
            "fresh": [t["id"] for t in result["fresh"]], "merged": result["merged"], "left_out": result["left"],
            "counts": triage.counts(store)}


def next_after_fetch(store, result):
    if result["new"]:
        return "--pack %s, then the triager, then --triage" % store.ref
    return next_step(store)


def cmd_fetch(args, ws):
    store, cfg = locate(args, ws, args.fetch or args.feature)
    with Lock(store):
        store.reload()
        if storelib.sync_prs(store, list(cfg_repos(cfg, ws))):
            store.save_prs()
    need_prs(store)
    snaps, me = read_host(store, cfg)
    if not any(p.get("host") == "github" for p in store.prs["prs"]):
        raise hosts.GhError("gh cannot read these PRs (%s). Fetch the comments with the team's tool, then pass "
                            "--ingest <file>. The shape is in SCHEMA.md."
                            % ", ".join(sorted({str(p.get("host")) for p in store.prs["prs"]})))
    with Lock(store):
        store.reload()
        result = apply(store, cfg, snaps, me)
    lines = ["Feature:  %s" % store.name] + fetch_lines(store, result)
    if not result["new"]:
        lines.append("New:      nothing new to explain.")
    lines.append("Next:     %s" % next_after_fetch(store, result))
    emit(args, result_data(store, result), lines)
    return 0


def cmd_ingest(args, ws):
    cfg = load_cfg(ws)
    path = Path(args.ingest).expanduser()
    if not path.is_file():
        raise UsageError("No file at %s." % path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise UsageError("%s is not valid JSON: %s" % (path, e))
    prs, threads, me, errors = schema.check_ingest(data, list(cfg_repos(cfg, ws)))
    if errors:
        raise UsageError("%s cannot be used. Fix these and run it again:\n  %s\nThe shape is in %s."
                         % (path, "\n  ".join(errors), HERE.parent / "SCHEMA.md"))
    store = storelib.find_store(ws, args.feature) if args.feature else storelib.find_store(ws, prs[0]["url"], create=True)
    with Lock(store):
        store.reload()
        storelib.sync_prs(store, list(cfg_repos(cfg, ws)))
        snaps, rename = [], {}
        for p in prs:
            entry, _ = add_pr(store, cfg, p["url"], p["repo"])
            rename[p["id"]] = entry["id"]
        rules = cfg.get("comments") if isinstance(cfg.get("comments"), dict) else {}
        for p in prs:
            pid = rename[p["id"]]
            mine = [dict(t, pr=pid, repo=store.pr(pid)["repo"], id=pid + t["id"][len(p["id"]):])
                    for t in threads if t["pr"] == p["id"]]
            kept, left = hosts.leave_out(mine, {me, p.get("author")} if me else {p.get("author")}, p["state"],
                                         rules.get("ignore") or (), rules.get("keep") or ())
            fields = {k: p[k] for k in ("title", "state", "draft", "head", "base", "author", "review")}
            fields["host"] = p["host"]
            snaps.append({"id": pid, "fields": fields, "threads": kept, "left": left})
        result = apply(store, cfg, snaps, me)
    lines = ["Feature:  %s" % store.name, "Ingest:   %s from %s" % (plural(len(threads), "comment"), path)]
    lines += fetch_lines(store, result)
    if not result["new"]:
        lines.append("New:      nothing new to explain.")
    lines.append("Next:     %s" % next_after_fetch(store, result))
    emit(args, result_data(store, result), lines)
    return 0


# --------------------------------------------------------------------------- pack


def read_code(path, pr, thread):
    """(numbered lines around the comment or None, a note on where they came from or why they are missing)."""
    file, line = thread.get("file"), thread.get("line")
    if not file:
        return None, ""
    if path is None or not gitops.is_repo(path):
        return None, "The code could not be read: there is no local checkout of %s. Use the diff above." % pr["repo"]
    head, text, source = pr.get("head"), None, None
    root = Path(path).resolve()
    target = (root / file).resolve()
    inside = str(target).startswith(str(root) + "/")
    if head and inside and storelib.current_branch(root) == head and target.is_file():
        text, source = target.read_text(encoding="utf-8", errors="replace"), "the checkout, on branch %s" % head
    if text is None and head:
        for ref in ("origin/%s" % head, head):
            code, out, _ = storelib.git_raw(root, "show", "%s:%s" % (ref, file))
            if code == 0:
                text, source = out, "git show %s" % ref
                break
    if text is None:
        if not head:
            return None, "The code could not be read: the PR's branch is not known yet. Run --fetch first."
        return None, ("The code could not be read: `%s` is not in branch `%s` of the checkout at `%s`. Fetch that "
                      "branch, or use the diff above." % (file, head, root))
    rows = text.split("\n")
    lo = max(1, (line or 1) - AROUND)
    hi = min(len(rows), (line or AROUND) + AROUND)
    body = "\n".join("%s%5d  %s" % (">" if n == line else " ", n, rows[n - 1]) for n in range(lo, hi + 1))
    note = "`%s` lines %d to %d, from %s" % (file, lo, hi, source)
    if thread.get("outdated"):
        note += "; the diff changed after the comment, so the line may have moved"
    return body, note


def spec_rules(store):
    data = storelib.read_json(store.root / "spec" / "spec.json")
    rules = data.get("rules") if isinstance(data, dict) else None
    return rules if isinstance(rules, list) else []


def pack_entries(store, cfg, targets):
    everything = store.threads["threads"]
    likeness = similar.similar_threads(targets, everything)
    rules = spec_rules(store)
    found = tasklib.load_tasks(store.root / tasklib.TASKS_DIR) if store.feature else []
    by_id, target_ids = store.by_id(), {t["id"] for t in targets}
    paths = {p["id"]: repo_path(store, cfg, p) for p in store.prs["prs"]}
    entries = []
    for t in targets:
        pr = store.pr(t["pr"]) or {"repo": t.get("repo"), "id": t["pr"]}
        code, note = read_code(paths.get(t["pr"]), pr, t)
        tasks = [{"id": x.id, "title": str(x.get("title") or ""), "file": str(x.path)} for x in found
                 if t.get("file") and str(x.get("repo")) == t.get("repo")
                 and any(tasklib.paths_overlap(t["file"], touch) for touch in tasklib.as_list(x.get("touches")))]
        alike = []
        for hit in likeness.get(t["id"], []):
            other = by_id[hit["id"]]
            item = store.current(other)
            if item:
                note_ = "already in %s (%s)" % (item.get("group"), item.get("verdict"))
            elif hit["id"] in target_ids:
                note_ = "also in this pack"
            else:
                note_ = "settled, not explained" if other.get("resolved") else "not explained yet"
            alike.append(dict(hit, note=note_))
        entries.append({"thread": t, "code": code, "code_note": note, "tasks": tasks,
                        "rules": similar.matching_rules(rules, t), "similar": alike,
                        "again": t["id"] in store.items})
    return entries, paths


def cmd_pack(args, store, cfg):
    need_prs(store)
    by_id = store.by_id()
    targets = store.new_threads()
    if args.all:
        targets = [t for t in store.threads["threads"] if store.current(t) is None]
    if args.again:
        wanted = {t["id"] for t in targets} | set(targets_of(store, args.again))
        targets = [t for t in store.threads["threads"] if t["id"] in wanted]
    if not targets:
        lines = ["Pack:     nothing new to explain in %s (%s, all explained or settled)."
                 % (store.name, plural(len(by_id), "comment")),
                 "Next:     %s" % next_step(store)]
        emit(args, {"pack": None, "threads": []}, lines)
        return 1
    out_file = store.dir / storelib.TRIAGE_IN
    if out_file.exists():
        out_file.unlink()  # the answer to an older pack
    entries, paths = pack_entries(store, cfg, targets)
    repos = {}
    for pid, path in paths.items():
        pr = store.pr(pid)
        if path is not None and gitops.is_repo(path):
            on = storelib.current_branch(path)
            repos[pid] = "repo at `%s`%s" % (path, ", on the PR's branch" if on and on == pr.get("head") else
                                             ", on branch `%s` (read the PR's code with `git show origin/%s:<path>`)"
                                             % (on, pr.get("head")))
    pack = store.dir / storelib.PACK
    pack.parent.mkdir(parents=True, exist_ok=True)
    pack.write_text(report.render_pack(store, entries, out_file, repos), encoding="utf-8")
    unread = sum(1 for e in entries if e["thread"].get("file") and not e["code"])
    lines = ["Pack:     %s (%s on %s)" % (pack, plural(len(entries), "comment"),
                                          plural(len({e["thread"]["pr"] for e in entries}), "PR")),
             "Similar:  %d of them look like another comment" % sum(1 for e in entries if e["similar"])]
    if unread:
        lines.append("Code:     %d could not be read from a local checkout. The triager works from the diff for those." % unread)
    lines += ["Answer:   %s  (the triager writes it)" % out_file,
              "Next:     start one chopchop:triager agent with the pack, then --triage %s" % out_file]
    emit(args, {"pack": str(pack), "answer": str(out_file), "threads": [e["thread"]["id"] for e in entries],
                "unread": unread}, lines)
    return 0


# --------------------------------------------------------------------------- triage and decide


def cmd_triage(args, store, cfg):
    path = Path(args.triage).expanduser()
    if not path.is_file():
        raise UsageError("No triage file at %s. The triager writes it. Start it with the pack: %s"
                         % (path, store.dir / storelib.PACK))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise UsageError("%s is not valid JSON: %s" % (path, e))
    threads = store.by_id()
    items, groups, errors, warnings = schema.check_triage(data, threads, store.triage)
    if errors:
        raise UsageError("The triage cannot be used. Ask the triager to fix these and write the file again:\n  %s"
                         % "\n  ".join(errors))
    seen = triage.merge(store, items, groups)
    triage.reconcile(store)
    store.save_triage()
    write_report(store)
    c = triage.counts(store)
    verdicts = {}
    for it in items.values():
        verdicts[it["verdict"]] = verdicts.get(it["verdict"], 0) + 1
    said = ", ".join("%d %s" % (n, v.replace("-", " ")) for v, n in sorted(verdicts.items(), key=lambda kv: triage.VER[kv[0]]))
    events.log(store.root, "triage", "%s explained: %s." % (plural(len(items), "review comment"), said))
    missing = [t["id"] for t in store.new_threads()]
    lines = ["Triage:   %s explained, now %s · %s" % (plural(len(items), "comment"),
                                                     plural(len(store.triage["groups"]), "group"), said)]
    if seen["again"]:
        lines.append("Again:    %s changed since the last look. The old decision is kept as a note, not as the call."
                     % ", ".join(seen["again"]))
    lines.append("Call:     %s your call (fix, reply or skip)" % ("%d need" % c["undecided"] if c["undecided"] != 1 else "1 needs"))
    for g in store.triage["groups"][:3]:
        lines.append("Top:      %s · %s · %s · %s (%s)%s" % (
            g["id"], g["priority"], report.VERDICT_WORDS.get(g["verdict"], g["verdict"]), report.clean(g["title"]),
            plural(len(g["threads"]), "comment"), " · same file as %s" % ", ".join(g["with"]) if g["with"] else ""))
    lines += ["Warning:  %s" % w for w in warnings[:12]]
    if len(warnings) > 12:
        lines.append("Warning:  and %d more wording warnings" % (len(warnings) - 12))
    if missing:
        lines.append("Missing:  %s still not explained: %s" % (plural(len(missing), "comment"), ", ".join(missing[:8])))
    lines += ["Report:   %s" % store.report,
              "Next:     %s" % ("--pack again for the missing ones" if missing else
                                "tell the person, ask which to fix, then --decide <id or group> fix|reply|skip")]
    emit(args, {"items": list(items), "groups": store.triage["groups"], "warnings": warnings, "missing": missing,
                "again": seen["again"], "counts": c, "report": str(store.report)}, lines)
    return 0


def cmd_decide(args, store, cfg):
    target, decision = args.decide[0].strip(), args.decide[1].strip().lower()
    if decision not in schema.DECISIONS:
        raise UsageError("The call must be fix, reply or skip (got '%s')." % decision)
    threads = store.by_id()
    bulk = target.lower() in ("all", "all-real")
    if bulk:
        ids = []
        for t in store.threads["threads"]:
            it = store.current(t)
            if it and not t.get("resolved") and it.get("state") in ("triaged", "fixing", "replied") and \
                    (it.get("verdict") == "real" if target.lower() == "all-real" else it.get("verdict") in triage.NEEDS_DECISION):
                ids.append(t["id"])
    else:
        ids = targets_of(store, target)
    done, left = [], []
    for tid in ids:
        t, it = threads[tid], store.current(threads[tid])
        if it is None:
            left.append((tid, "it is not explained yet, or it changed. Run --pack and the triager first"))
        elif t.get("resolved") or it.get("state") == "closed":
            left.append((tid, "it is settled"))
        elif it.get("state") == "fixed":
            left.append((tid, "it is already fixed"))
        elif decision == "fix" and it.get("verdict") in ("negotiable", "question") and not args.force:
            left.append((tid, "it is %s, not a real problem. Fix it only when the person insists: add --force"
                         % report.VERDICT_WORDS[it["verdict"]]))
        elif decision == "fix" and it.get("verdict") not in ("real", "negotiable", "question"):
            left.append((tid, "the verdict is '%s', so there is nothing to fix. If the reviewer is right after all, "
                              "ask for a new look: --pack --again %s" % (it.get("verdict"), tid)))
        else:
            it["decision"] = decision
            it.pop("was", None)
            if (decision != "fix" and it.get("state") == "fixing") or (decision == "fix" and it.get("state") == "replied"):
                it["state"] = "triaged"  # out of the fix plan, or back in after a reply
            done.append(tid)
    if not done and not bulk:
        raise UsageError("Nothing was decided:\n  %s" % "\n  ".join("%s: %s." % x for x in left))
    if done:
        store.save_triage()
        write_report(store)
        events.log(store.root, "comment", "Decision: %s for %s (%s)." % (decision, target, plural(len(done), "comment")),
                   by="you")
    c = triage.counts(store)
    lines = ["Decided:  %s · %s%s" % (decision, plural(len(done), "comment"), ": %s" % ", ".join(done) if done else "")]
    lines += ["Left:     %s: %s." % x for x in left]
    lines += ["Still:    %s your call" % ("%d need" % c["undecided"] if c["undecided"] != 1 else "1 needs"),
              "Next:     %s" % next_step(store)]
    emit(args, {"decision": decision, "decided": done, "left": [{"id": a, "why": b} for a, b in left], "counts": c}, lines)
    return 0 if done else 1


# --------------------------------------------------------------------------- plan, commit, push, fixed


def plan_file(store):
    return store.dir / storelib.FIX_DIR / storelib.PLAN


def load_plan(store):
    data = storelib.read_json(plan_file(store))
    return [b for b in (data or {}).get("batches") or [] if isinstance(b, dict)] if isinstance(data, dict) else []


def save_plan(store, batches):
    storelib.write_json(plan_file(store), {"made": now(), "batches": batches})


def batch_of(store, bid):
    batches = load_plan(store)
    batch = next((b for b in batches if str(b.get("id")).upper() == str(bid).upper()), None)
    if batch is None:
        raise UsageError("There is no batch %s. Batches: %s. Make them with --plan."
                         % (bid, ", ".join(str(b.get("id")) for b in batches) or "none yet"))
    return batches, batch


def profile_of(ws, repo):
    f = Path(ws) / "repos" / ("%s.md" % repo)
    return (features.read_front_matter(f), f) if f.is_file() else ({}, None)


def style_files(cfg, ws, repo, path):
    raw = (cfg.get("repos") or {}).get(repo) if isinstance(cfg.get("repos"), dict) else None
    raw = raw.get("style") if isinstance(raw, dict) else None
    out = []
    for item in (raw if isinstance(raw, list) else [raw] if raw else []):
        p = Path(str(item)).expanduser()
        full = p if p.is_absolute() else next((b / p for b in (Path(path), Path(ws)) if (b / p).is_file()), None)
        if full is not None and full.is_file():
            out.append(str(full))
    return out


def brief_info(store, cfg, batch, batches, path):
    meta, prof = profile_of(store.ws, batch["repo"])
    found = tasklib.load_tasks(store.root / tasklib.TASKS_DIR) if store.feature else []
    tasks = [{"id": t.id, "file": str(t.path)} for t in found if str(t.get("repo")) == batch["repo"] and any(
        tasklib.paths_overlap(f, touch) for f in batch["files"] for touch in tasklib.as_list(t.get("touches")))]
    folder = store.dir / storelib.FIX_DIR / batch["id"]
    return {"repo_path": str(path) if path else "not known: ask the person where %s is checked out" % batch["repo"],
            "report": str(folder / "report.json"), "check": [meta[k] for k in ("build", "lint", "test") if meta.get(k)],
            "style": style_files(cfg, store.ws, batch["repo"], path) if path else [],
            "guides": [str(Path(path) / g) for g in GUIDES if path and (Path(path) / g).is_file()],
            "profile": str(prof) if prof else None, "tasks": tasks,
            "others": [b for b in batches if b is not batch and b.get("state") == "planned"
                       and set(b["groups"]) & set(batch["groups"])]}


def cmd_plan(args, store, cfg):
    batches, warnings = triage.make_batches(store, load_plan(store))
    planned = [b for b in batches if b["state"] == "planned"]
    busy = {tid for b in batches if b["state"] in ("planned", "committed") for tid in b["threads"]}
    for tid, it in store.items.items():
        if tid in busy and it.get("state") == "triaged":
            it["state"] = "fixing"
        elif tid not in busy and it.get("state") == "fixing":
            it["state"] = "triaged"
    lines = ["Plan:     %s, most urgent first. Comments that touch the same files are in one batch."
             % plural(len(planned), "batch")]
    for b in planned:
        pr = store.pr(b["pr"])
        path = repo_path(store, cfg, pr)
        path = Path(path) if path is not None and gitops.is_repo(path) else None
        info = brief_info(store, cfg, b, planned, path)
        folder = store.dir / storelib.FIX_DIR / b["id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "brief.md").write_text(report.render_brief(store, b, info), encoding="utf-8")
        b.update(brief=str(folder / "brief.md"), report=info["report"], path=str(path) if path else None)
        lines += ["%-9s %s · %s · %s · %s · %s" % (b["id"] + ":", b["repo"], b["branch"] or "branch not known",
                                                  ", ".join(b["groups"]), plural(len(b["threads"]), "comment"),
                                                  plural(len(b["files"]), "file")),
                  "          Brief: %s" % b["brief"]]
        if path is None:
            warnings.append("chopchop does not know where %s is checked out. Say where: --pr %s --path <folder>"
                            % (b["repo"], pr["url"]))
        elif storelib.current_branch(path) != b["branch"]:
            warnings.append("%s is on branch %s, not on the PR's branch %s. A person checks it out before the fix."
                            % (b["repo"], storelib.current_branch(path), b["branch"]))
    save_plan(store, batches)
    store.save_triage()
    write_report(store)
    lines += ["Warning:  %s" % w for w in warnings]
    waiting = [b for b in batches if b["state"] == "committed"]
    lines += ["Waiting:  %s is committed. Push it, then --fixed %s" % (b["id"], b["id"]) for b in waiting]
    if not planned:
        lines[0] = "Plan:     nothing to fix. No open comment has the call 'fix'."
        lines.append("Next:     %s" % next_step(store))
        emit(args, {"batches": batches, "warnings": warnings}, lines)
        return 1
    events.log(store.root, "fix", "Fix plan: %s." % ", ".join("%s (%s, %s)" % (b["id"], b["repo"], ", ".join(b["groups"]))
                                                             for b in planned))
    first = planned[0]
    lines += ["Next:     for each batch, in order: start chopchop:builder with its brief, run the repo's checks, review "
              "the pending change (python3 %s --pack --repo %s), then --commit %s --message \"...\""
              % (REVIEW_SCRIPT, first.get("path") or "<repo>", first["id"])]
    emit(args, {"batches": batches, "warnings": warnings}, lines)
    return 0


def is_test(path):
    parts = path.split("/")
    return bool(TEST_FILE.search(parts[-1])) or bool(TEST_DIRS & {p.lower() for p in parts[:-1]})


def near(path, files):
    """True when a changed file is one of the batch's files, sits next to one, or is a test of one."""
    flat = re.sub(r"[^a-z0-9]", "", posixpath.basename(path).lower())
    for f in files:
        if path == f or posixpath.dirname(path) == posixpath.dirname(f):
            return True
        stem = re.sub(r"[^a-z0-9]", "", posixpath.basename(f).split(".")[0].lower())
        if len(stem) >= 3 and stem in flat and is_test(path):
            return True
    return False


def cmd_commit(args, store, cfg):
    batches, batch = batch_of(store, args.commit)
    if batch["state"] != "planned":
        raise UsageError("%s is already %s (commit %s). Next: --push %s, then --fixed %s."
                         % (batch["id"], batch["state"], batch.get("commit"), batch["repo"], batch["id"]))
    pr = store.pr(batch["pr"])
    if pr is None or pr.get("state") != "open":
        raise UsageError("%s is not open any more, so nothing is committed for it." % batch["pr"])
    path = checkout(store, cfg, pr)
    branch = storelib.current_branch(path)
    if not pr.get("head") or branch != pr["head"]:
        raise UsageError("%s is on branch %s, not on the PR's branch %s. A person checks that branch out first. "
                         "chopchop commits a fix only on the PR's own branch." % (batch["repo"], branch, pr.get("head")))
    problem = unsafe_branch(branch, pr.get("base"))
    if problem:
        raise UsageError(problem)
    done = storelib.read_json(store.dir / storelib.FIX_DIR / batch["id"] / "report.json") or {}
    if done.get("blocked"):
        emit(args, {"batch": batch["id"], "blocked": done["blocked"]},
             ["Blocked:  the builder could not make the fix as written: %s" % done["blocked"],
              "Next:     tell the person. Nothing was committed."])
        return 1
    files = own_pending(path, store.ws)
    if not files:
        raise UsageError("Nothing to commit for %s: %s has no pending change." % (batch["id"], batch["repo"]))
    allowed = [p.strip() for p in (args.outside or "").split(",") if p.strip()]
    stray = [f["path"] for f in files if batch["files"] and f["path"] not in allowed and not near(f["path"], batch["files"])]
    if stray:
        lines = ["Outside:  %s changed files that are not in or next to the batch's files: %s" % (batch["id"], ", ".join(stray)),
                 "Next:     ask the builder to undo them. If the fix truly needs them: --commit %s --message \"...\" --outside %s"
                 % (batch["id"], ",".join(stray))]
        emit(args, {"batch": batch["id"], "outside": stray}, lines)
        return 1
    message = (args.message or done.get("commit") or "").strip()
    if not message:
        raise UsageError('--commit %s needs --message "<subject in this repo\'s commit style>".' % batch["id"])
    code, out, err = gitops.git(path, "add", "-A", "--", *[f["path"] for f in files])
    if code == 0:
        code, out, err = gitops.git(path, "commit", "-q", "-m", message)
    if code != 0:
        emit(args, {"batch": batch["id"], "error": err or out},
             ["Commit:   failed in %s: %s" % (batch["repo"], (err or out).strip()[-1200:]),
              "Next:     treat it like a failed check: send it to the builder, then --commit %s again" % batch["id"]])
        return 1
    sha = gitops.git(path, "rev-parse", "--short", "HEAD")[1]
    batch.update(state="committed", commit=sha, subject=message.splitlines()[0])
    save_plan(store, batches)
    events.log(store.root, "commit", "%s committed on %s: %s" % (batch["id"], branch, batch["subject"]), repo=batch["repo"])
    lines = ["Commit:   %s %s on %s · %s · %s" % (batch["id"], sha, branch, plural(len(files), "file"), batch["subject"]),
             "Next:     --push %s, then --fixed %s" % (batch["repo"], batch["id"])]
    emit(args, {"batch": batch["id"], "commit": sha, "branch": branch, "files": [f["path"] for f in files]}, lines)
    return 0


def cmd_push(args, store, cfg):
    name = args.push
    prs = [p for p in store.prs["prs"] if p.get("repo") == name and p.get("state") == "open"]
    if not prs:
        raise UsageError("No open PR for repo '%s' here. Repos: %s." % (
            name, ", ".join(sorted({str(p.get("repo")) for p in store.prs["prs"]})) or "none"))
    path = checkout(store, cfg, prs[0])
    on = storelib.current_branch(path)
    pr = next((p for p in prs if p.get("head") == on), prs[0] if len(prs) == 1 else None)
    if pr is None:
        raise UsageError("%s has %d open PRs and none is on the branch that is checked out (%s)." % (name, len(prs), on))
    head = pr.get("head")
    if not head or not gitops.local_branch_exists(path, head):
        raise UsageError("The PR's branch %s is not in %s. Run --fetch, and check the branch out." % (head, path))
    remote = gitops.git(path, "config", "branch.%s.remote" % head)[1] or "origin"
    merge = gitops.git(path, "config", "branch.%s.merge" % head)[1] or "refs/heads/%s" % head
    dest = re.sub(r"^refs/heads/", "", merge)
    for branch in (head, dest):
        problem = unsafe_branch(branch, pr.get("base"))
        if problem:
            raise UsageError("Not pushed. %s" % problem)
    if not gitops.has_remote(path, remote):
        raise UsageError("%s has no remote '%s', so there is nowhere to push." % (name, remote))
    code, out, err = gitops.git(path, "push", remote, "refs/heads/%s:refs/heads/%s" % (head, dest))
    if code != 0:
        why = [l for l in (err or out).splitlines() if l.strip()]
        emit(args, {"repo": name, "pushed": False, "error": err or out},
             ["Push:     refused for %s (%s): %s" % (name, head, why[-1] if why else "no reason given"),
              "Next:     tell the person. The remote branch may have new commits. chopchop never force-pushes."])
        return 1
    sha = gitops.git(path, "rev-parse", "--short", head)[1]
    events.log(store.root, "push", "%s pushed to %s (%s)." % (head, remote, sha), repo=name)
    waiting = [b["id"] for b in load_plan(store) if b.get("state") == "committed" and b.get("repo") == name]
    lines = ["Push:     %s · %s -> %s/%s · now at %s" % (name, head, remote, dest, sha),
             "Next:     %s" % (" and ".join("--fixed %s" % b for b in waiting) if waiting else next_step(store))]
    emit(args, {"repo": name, "pushed": True, "branch": head, "remote": remote, "commit": sha}, lines)
    return 0


def cmd_fixed(args, store, cfg):
    batches, batch = batch_of(store, args.fixed)
    sha = (args.commit or batch.get("commit") or "").strip()
    if not sha:
        raise UsageError("--fixed %s needs --commit <sha>: the commit that holds the fix." % batch["id"])
    pr = store.pr(batch["pr"])
    path = repo_path(store, cfg, pr) if pr else None
    if path is not None and gitops.is_repo(path) and gitops.git(path, "cat-file", "-e", "%s^{commit}" % sha)[0] != 0:
        raise UsageError("There is no commit %s in %s." % (sha, path))
    marked = []
    for tid in batch["threads"]:
        it = store.items.get(tid)
        if it and it.get("state") != "closed":
            it.update(state="fixed", commit=sha)
            marked.append(tid)
    batch.update(state="fixed", commit=sha)
    save_plan(store, batches)
    store.save_triage()
    write_report(store)
    events.log(store.root, "fix", "%s fixed in %s: %s (%s)." % (batch["id"], sha, ", ".join(batch["groups"]),
                                                                plural(len(marked), "comment")), repo=batch["repo"])
    lines = ["Fixed:    %s · %s · %s: %s" % (batch["id"], sha, plural(len(marked), "comment"), ", ".join(marked) or "none"),
             "Next:     %s" % next_step(store)]
    emit(args, {"batch": batch["id"], "commit": sha, "fixed": marked}, lines)
    return 0


# --------------------------------------------------------------------------- replies


def cmd_replies(args, store, cfg):
    rows = report.reply_rows(store)
    out = store.dir / storelib.REPLIES
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.render_replies(store, rows), encoding="utf-8")
    ready = [r for r in rows if r["ready"]]
    lines = []
    for r in sorted(rows, key=lambda r: not r["ready"]):
        lines += ["Reply:    %s · to %s at %s · %s" % (r["id"], r["author"], r["where"],
                                                       "ready" if r["ready"] else "waits: %s" % r["why_not"])]
        lines += ["          | %s" % l for l in r["text"].split("\n")]
        if r["url"]:
            lines.append("          %s" % r["url"])
    if not rows:
        lines.append("Replies:  no reply is waiting.")
    lines += ["Saved:    %s" % out,
              "Next:     %s" % ("show the drafts to the person. Post only after they say yes: --post --yes"
                                if ready else next_step(store))]
    emit(args, {"replies": rows, "ready": [r["id"] for r in ready], "file": str(out)}, lines)
    return 0


def cmd_post(args, store, cfg):
    only = targets_of(store, args.post) if args.post else None
    rows = report.reply_rows(store, only)
    if only:
        have = {r["id"]: r for r in rows}
        bad = ["%s: %s" % (tid, "waits: %s" % have[tid]["why_not"] if tid in have else "has no reply to post, or is answered already")
               for tid in only if tid not in have or not have[tid]["ready"]]
        if bad:
            raise UsageError("Nothing was posted. These are not ready:\n  %s" % "\n  ".join(bad))
    ready = [r for r in rows if r["ready"]]
    if not ready:
        raise UsageError("No reply is ready to post. A reply is ready when the person chose 'reply', or chose 'fix' "
                         "and the fix is in.")
    if not args.yes:
        print("Refused:  posting needs the person's yes. Nothing was posted.", file=sys.stderr)
        print("Would post %s: %s" % (plural(len(ready), "reply"), ", ".join(r["id"] for r in ready)), file=sys.stderr)
        print("Next:     show the drafts (--replies). After a yes: --post %s--yes"
              % (args.post + " " if args.post else ""), file=sys.stderr)
        return 2
    threads = store.by_id()
    other = [r["id"] for r in ready if (store.pr(r["pr"]) or {}).get("host") != "github"]
    ready = [r for r in ready if r["id"] not in other]
    servers = sorted({hosts.server_of(store.pr(r["pr"])) for r in ready})
    for server in servers:
        why = hosts.ready(server)
        if why:
            raise hosts.GhError("%s, so nothing was posted. Paste the drafts by hand (--replies)." % why)
    me = hosts.whoami(servers[0]) if servers else None
    posted, failed = [], None
    for r in ready:
        t, pr = threads[r["id"]], store.pr(r["pr"])
        try:
            link = hosts.post_reply(pr, t, r["text"])
        except hosts.GhError as e:
            failed = "%s: %s" % (r["id"], e)
            break
        item = store.items[r["id"]]
        item["state"] = "replied"
        if t["kind"] == "inline":  # our reply is part of the thread now: it must not look new
            t["replies"].append({"author": me or pr.get("author") or "you", "body": r["text"], "created": now()})
            t["hash"] = item["hash"] = storelib.thread_hash(t["body"], t["replies"])
        posted.append({"id": r["id"], "url": link})
        events.log(store.root, "reply", "Replied to %s on %s (%s)." % (t["author"], t["pr"], report.where(t)),
                   repo=t.get("repo"))
    if posted:
        store.save_threads()
        store.save_triage()
        write_report(store)
    lines = ["Posted:   %s · %s" % (p["id"], p["url"] or "sent") for p in posted]
    if other:
        lines.append("Not sent: not on GitHub: %s. After the person's yes, post them with the team's tool, then fetch "
                     "and --ingest again." % ", ".join(other))
    if failed:
        lines += ["Failed:   %s" % failed, "Next:     the ones above are posted. Try the rest again: --post --yes"]
    elif not other:
        lines.append("Next:     %s" % next_step(store))
    emit(args, {"posted": posted, "failed": failed, "not_sent": other}, lines)
    return 1 if failed else 0


# --------------------------------------------------------------------------- wait, watch, status


def cmd_wait(args, ws):
    store, cfg = locate(args, ws, args.feature)
    with Lock(store):
        store.reload()
        if storelib.sync_prs(store, list(cfg_repos(cfg, ws))):
            store.save_prs()
    need_prs(store)
    every, limit = max(0.05, args.every), max(0.0, args.for_)
    deadline = time.monotonic() + limit
    failures = 0

    def stop(signum, frame):
        raise KeyboardInterrupt

    old = signal.signal(signal.SIGTERM, stop)
    try:
        while True:
            with Lock(store):
                store.reload()
                if storelib.sync_prs(store, list(cfg_repos(cfg, ws))):
                    store.save_prs()
            if not any(p.get("host") == "github" for p in store.prs["prs"]):
                raise UsageError("gh cannot read these PRs, so --wait cannot listen. Fetch with the team's tool and "
                                 "--ingest when you want to check.")
            result = None
            try:
                snaps, me = read_host(store, cfg)
                failures = 0
            except hosts.GhError:
                failures += 1
                if failures >= 3:
                    raise
                snaps, me = None, None
            with Lock(store):
                store.reload()
                if snaps is not None:
                    result = apply(store, cfg, snaps, me, write_threads=False)
                store.prs["watch"]["last"] = now()
                states = {p.get("state") for p in store.prs["prs"]}
                over = snaps is not None and states <= {"merged", "closed"}
                if over:
                    store.prs["watch"]["on"] = False
                store.save_prs()
            if result and result["new"]:
                lines = ["Feature:  %s" % store.name] + fetch_lines(store, result)
                lines.append("Next:     --pack %s, then the triager, then --triage. Then --wait again." % store.ref)
                emit(args, dict(result_data(store, result), state="new"), lines)
                return 0
            if over:
                lines = ["Feature:  %s" % store.name] + fetch_lines(store, result)
                lines += ["Done:     every PR is merged or closed. Nothing left to listen for."]
                emit(args, dict(result_data(store, result), state="finished"), lines)
                return 2
            if time.monotonic() + every > deadline:
                emit(args, {"store": store.name, "state": "quiet", "counts": triage.counts(store)},
                     ["Quiet:    nothing new on %s in %d seconds." % (store.name, round(limit)),
                      "Next:     --wait again to keep listening, or stop here."])
                return 3
            time.sleep(every)
    except KeyboardInterrupt:
        with Lock(store):
            store.reload()
            store.prs["watch"]["last"] = now()
            store.save_prs()
        print("Stopped:  no longer waiting on %s." % store.name)
        return 130
    finally:
        signal.signal(signal.SIGTERM, old)


def cmd_watch(args, store, cfg):
    on = args.watch == "on"
    watch = store.prs["watch"]
    if on and not watch.get("on"):
        watch["since"] = now()
    watch["on"] = on
    store.save_prs()
    lines = ["Watch:    %s for %s%s" % (args.watch, store.name, " since %s" % watch.get("since") if on else ""),
             "Next:     %s" % ("start --wait as a background command. When it ends with exit 0, explain the new "
                               "comments and start it again." if on else next_step(store))]
    emit(args, {"store": store.name, "watch": watch}, lines)
    return 0


def next_step(store):
    c = triage.counts(store)
    prs = store.prs["prs"]
    if not prs:
        return "add a PR: --pr <link>"
    if not any(p.get("fetched") for p in prs):
        return "--fetch %s" % store.ref
    if c["new"]:
        return "--pack %s, then the triager, then --triage" % store.ref
    if c["undecided"]:
        return "ask the person about the %d open call(s), then --decide <id or group> fix|reply|skip" % c["undecided"]
    batches = load_plan(store)
    committed = [b for b in batches if b.get("state") == "committed"]
    if committed:
        return "--push %s, then --fixed %s" % (committed[0]["repo"], committed[0]["id"])
    if triage.fixable(store):
        planned = [b for b in batches if b.get("state") == "planned"]
        if planned and set(triage.fixable(store)) <= {t for b in planned for t in b["threads"]}:
            return "fix %s: builder with %s, checks, review, then --commit %s" % (
                planned[0]["id"], planned[0].get("brief"), planned[0]["id"])
        return "--plan"
    ready = [t for t in store.threads["threads"] if report.ready_to_post(store, t)]
    if ready:
        return "--replies, then post after the person says yes (%d ready)" % len(ready)
    if prs and all(p.get("state") in ("merged", "closed") for p in prs):
        return "nothing. Every PR is merged or closed."
    return "nothing for now: the reviewers have the next move. --wait listens for new comments."


def cmd_status(args, store, cfg):
    if storelib.sync_prs(store, list(cfg_repos(cfg, store.ws))):
        store.save_prs()
    c = triage.counts(store)
    watch = store.prs["watch"]
    lines = ["Feature:  %s" % store.name,
             "PRs:      %d · %d open, %d merged, %d closed" % (c["prs"], c["open"], c["merged"], c["closed"]),
             "Comments: %d · %d open, %d settled" % (c["threads"], c["live"], c["threads"] - c["live"]),
             "New:      %d not explained yet" % c["new"],
             "Call:     %d need your call" % c["undecided"],
             "Work:     %d to fix · %d fixed · %d replied" % (c["to_fix"], c["fixed"], c["replied"]),
             "Watch:    %s%s" % ("on" if watch.get("on") else "off", " · last look %s" % watch["last"] if watch.get("last") else ""),
             "Report:   %s" % (store.report if store.report.is_file() else "not written yet"),
             "Next:     %s" % next_step(store)]
    emit(args, dict(c, store=store.name, ref=store.ref, watch=watch, next=next_step(store),
                    pr_list=store.prs["prs"]), lines)
    return 0


# --------------------------------------------------------------------------- main


ACTIONS = ["prs", "pr", "fetch", "ingest", "pack", "triage", "decide", "plan", "commit", "push", "fixed", "replies",
           "post", "wait", "watch", "status"]
OWN_LOCK = {"pr": cmd_pr, "fetch": cmd_fetch, "ingest": cmd_ingest, "wait": cmd_wait}
COMMANDS = {"prs": cmd_prs, "pack": cmd_pack, "triage": cmd_triage, "decide": cmd_decide, "plan": cmd_plan,
            "commit": cmd_commit, "push": cmd_push, "fixed": cmd_fixed, "replies": cmd_replies, "post": cmd_post,
            "watch": cmd_watch, "status": cmd_status}


def locate(args, ws, ref):
    return storelib.find_store(ws, ref), load_cfg(ws)


def build_parser():
    p = argparse.ArgumentParser(prog="chopchop_comments.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("--prs", nargs="?", const="", metavar="REF", help="find the feature and list its PRs")
    p.add_argument("--pr", metavar="URL", help="add a pull request")
    p.add_argument("--fetch", nargs="?", const="", metavar="REF", help="read PR state and review comments with gh")
    p.add_argument("--ingest", metavar="FILE", help="take comments another tool fetched (see SCHEMA.md)")
    p.add_argument("--pack", nargs="?", const="", metavar="REF", help="write pack.md for the triager")
    p.add_argument("--triage", metavar="FILE", help="check the triager's answer and merge it")
    p.add_argument("--decide", nargs=2, metavar=("TARGET", "CALL"), help="the person's call: fix, reply or skip")
    p.add_argument("--plan", action="store_true", help="cut the fix batches and write a brief for each")
    p.add_argument("--commit", metavar="BATCH", help="commit a batch (with --fixed: the commit sha)")
    p.add_argument("--push", metavar="REPO", help="push the PR's branch of this repo, never forced")
    p.add_argument("--fixed", metavar="BATCH", help="mark a batch fixed")
    p.add_argument("--replies", action="store_true", help="the reply drafts, ready to paste")
    p.add_argument("--post", nargs="?", const="", metavar="IDS", help="post replies with gh (needs --yes)")
    p.add_argument("--wait", action="store_true", help="block until a new comment arrives")
    p.add_argument("--watch", choices=["on", "off"], help="set the watch flag")
    p.add_argument("--status", action="store_true", help="counts and the next step")
    p.add_argument("--repo", metavar="NAME", help="with --pr: the chopchop name of its repo")
    p.add_argument("--path", metavar="DIR", help="with --pr: where its repo is checked out")
    p.add_argument("--all", action="store_true", help="with --pack: settled comments too")
    p.add_argument("--again", metavar="IDS", help="with --pack: explain these again (thread ids or groups)")
    p.add_argument("--force", action="store_true", help="with --decide: fix a negotiable or question comment")
    p.add_argument("--message", help="with --commit: the commit message")
    p.add_argument("--outside", metavar="FILES", help="with --commit: files outside the batch that it may commit")
    p.add_argument("--yes", action="store_true", help="with --post: the person said yes")
    p.add_argument("--every", type=float, default=60, metavar="SECONDS", help="with --wait: seconds between looks")
    p.add_argument("--for", dest="for_", type=float, default=1800, metavar="SECONDS", help="with --wait: give up after")
    p.add_argument("--feature", metavar="REF", help="feature, PR link or loose PR folder")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="path to the _chopchop folder")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    chosen = [a for a in ACTIONS if getattr(args, a) not in (None, False)]
    if "fixed" in chosen and "commit" in chosen:
        chosen.remove("commit")  # --fixed B1 --commit <sha>
    if "pr" in chosen and "prs" in chosen:
        chosen.remove("prs")  # --prs REF --pr <link>
    try:
        if len(chosen) != 1:
            raise UsageError("Use one of --%s." % ", --".join(ACTIONS))
        action = chosen[0]
        ws = find_workspace(args.workspace)
        if action in OWN_LOCK:
            return OWN_LOCK[action](args, ws)
        ref = getattr(args, action) if action in ("prs", "pack") else None
        store, cfg = locate(args, ws, ref or args.feature)
        with Lock(store):
            store.reload()
            return COMMANDS[action](args, store, cfg)
    except (UsageError, ConfigError, FeatureError, gitops.GitError, review.ReviewError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except hosts.GhError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
