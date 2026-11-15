"""What each dashboard API route returns. Everything here only reads files.

  home(ws)                /api/features     every feature as stage.read() gives it, plus key and updated
  feature(ws, n)          /api/feature/<n>  that, plus docs, tasks, events, comments, gates, links, run
  doc(ws, n, path)        /api/doc/<n>      one .md or .json file of the feature, as safe HTML
  pr_list(ws)             /api/prs          review stores of PRs that have no feature
  pr(ws, slug)            /api/pr/<slug>    one of them
  system(ws)              /api/system       the system map

In /api/feature/<n> the keys docs, tasks and comments are lists and maps for the page. The counts
that stage.read() keeps under the same names move to "counts".

A missing, half-written or broken file is "no data yet". It never fails a request.
"""

import html
import json
import os
import posixpath
import re
import secrets
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

from chopchoplib import changes, diagrams, events, features, plain, stage
from chopchoplib import tasks as tasklib
from chopchoplib.config import load_config
from chopchoplib.features import parse_front_matter

from . import md
from .watch import stamp, updated

DOC_TYPES = (".md", ".json")
MAX_DOC = 4 * 1024 * 1024     # bytes: a bigger file is not shown
JSON_SHOW = 400 * 1024        # characters of a .json file shown on the page
EVENTS = 200
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._#@+-]{0,120}$")
MERMAID_FENCE = re.compile(r"(?ms)^```mermaid[^\n]*\n.*?^```[ \t]*$")

KNOWN_DOCS = [
    ("requirement", "requirements/requirement.md", "Requirement, as given"),
    ("grooming", "requirements/grooming.md", "Grooming notes"),
    ("brief", "requirements/brief.md", "Brief"),
    ("design", "design/design.md", "Design"),
    ("options", "design/options.md", "Design options"),
    ("spec", "spec/spec.md", "Spec"),
    ("plan", "tasks/plan.md", "Task plan"),
    ("status", "tasks/status.md", "Task status"),
    ("changelog", "tasks/changelog.md", "Changes found while building"),
    ("check", "check.md", "Check report"),
    ("comments", "comments.md", "Review comments report"),
]
EXTRA_DOC_DIRS = ["", "requirements", "design", "spec"]
GATES = [("brief", "you"), ("design", "lead"), ("spec", "you")]
COLUMNS = ["todo", "building", "committed", "review", "done"]


class ApiError(Exception):
    status = 400


class NotFound(ApiError):
    status = 404


class Refused(ApiError):
    status = 403


class TooBig(ApiError):
    status = 413


# --------------------------------------------------------------------------- small helpers


def read_json(path):
    """The JSON in a file, or None when it is missing, half-written or not JSON."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def front_matter(path):
    try:
        meta = parse_front_matter(read_text(path))[0]
    except Exception:  # noqa: BLE001
        meta = {}
    return meta if isinstance(meta, dict) else {}


def dicts(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def text_or_none(value):
    return None if value is None else str(value)


def str_list(value):
    try:
        return tasklib.as_list(value)
    except Exception:  # noqa: BLE001
        return []


def safe_url(value):
    """A link the page may show: http or https only."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if re.match(r"^https?://[^\s<>\"']+$", value, re.I) else None


def mtime(path):
    try:
        return stamp(Path(path).stat().st_mtime)
    except OSError:
        return None


# --------------------------------------------------------------------------- the workspace


def workspace_info(ws):
    ws = Path(ws)
    info = {"path": str(ws), "project": ws.parent.name, "exists": ws.is_dir(),
            "config": (ws / "chopchop.yaml").is_file(), "team": None, "config_problem": None}
    if info["config"]:
        try:
            cfg = load_config(ws)
            info["team"] = text_or_none(cfg.get("team"))
        except Exception as e:  # noqa: BLE001  a broken config still shows the features
            info["config_problem"] = str(e)
    return info


def all_features(ws):
    """(features, broken). A folder that cannot be read is listed as broken, so the page still loads."""
    good, broken = [], []
    root = Path(ws)
    try:
        folders = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return good, broken
    for p in folders:
        m = features.FOLDER_RE.match(p.name)
        if not m:
            continue
        try:
            if p.is_dir():
                good.append(features.Feature(p))
        except Exception as e:  # noqa: BLE001
            broken.append((int(m.group(1)), p.name, "%s: %s" % (type(e).__name__, e)))
    good.sort(key=lambda f: (f.number, f.name))
    return good, broken


def find_feature(ws, number):
    try:
        number = int(str(number), 10)
    except ValueError:
        raise NotFound("No feature %s." % number)
    for f in all_features(ws)[0]:
        if f.number == number:
            return f
    raise NotFound("No feature %03d in %s." % (number, ws))


def broken_row(number, folder, why):
    return {"number": number, "folder": folder, "path": None, "epic": None, "key": None, "title": folder,
            "mode": None, "stage": None, "label": "Cannot be read", "steps": [], "waiting_on": None,
            "waiting_who": None, "waiting": "chopchop could not read this feature's files.", "next": None,
            "summary": [], "docs": {}, "status": {}, "tasks": dict({c: 0 for c in tasklib.STATUSES}, total=0, committed=0),
            "auto": None, "comments": {}, "prs": [], "updated": None, "error": why}


def feature_row(f):
    """stage.read() for one feature, plus key and updated."""
    try:
        row = stage.read(f)
        row["key"] = text_or_none(f.epic)
    except Exception as e:  # noqa: BLE001  one broken feature must not hide the others
        row = broken_row(f.number, f.name, "%s: %s" % (type(e).__name__, e))
    row["updated"] = updated(f.path)
    return row


def home(ws):
    ws = Path(ws)
    good, broken = all_features(ws)
    rows = [feature_row(f) for f in good] + [broken_row(*b) for b in broken]
    rows.sort(key=lambda r: (r["number"], r["folder"]))
    return {"workspace": workspace_info(ws), "features": rows, "prs": pr_list(ws)["prs"],
            "system": system_path(ws) is not None, "generated": stamp()}


# --------------------------------------------------------------------------- one feature


def doc_list(f):
    """Every document of a feature that a person may want to read."""
    root = Path(f.path)
    out, seen = [], set()

    def add(key, rel, label):
        path = root.joinpath(*rel.split("/"))
        if not path.is_file() or rel in seen:
            return
        seen.add(rel)
        text = read_text(path)
        meta = front_matter(path)
        out.append({
            "key": key, "path": rel, "label": label, "updated": mtime(path),
            "title": text_or_none(meta.get("title")), "status": text_or_none(meta.get("status")),
            "approved_by": text_or_none(meta.get("approved_by")), "approved_on": text_or_none(meta.get("approved_on")),
            "changed": bool(meta.get("changed_since_approval")), "ok": stage.approved(meta),
            "gate": key in dict(GATES), "summary": plain.summary_points(text, 3),
        })

    for key, rel, label in KNOWN_DOCS:
        add(key, rel, label)
    for folder in EXTRA_DOC_DIRS:
        here = root / folder if folder else root
        try:
            extra = sorted(p for p in here.glob("*.md") if p.is_file())
        except OSError:
            extra = []
        for p in extra:
            rel = (folder + "/" if folder else "") + p.name
            add(rel, rel, p.stem.replace("-", " ").replace("_", " ").capitalize())
    return out


def gates(f):
    """The three places where a person says yes: who, and whether they did."""
    paths = stage.paths(f)
    out = []
    for key, who in GATES:
        path = paths[key]
        exists = path.is_file()
        meta = front_matter(path) if exists else {}
        status = str(meta.get("status") or "")
        was_approved = status.startswith("approved") or bool(meta.get("approved_by"))
        if not exists:
            state = "missing"
        elif stage.approved(meta):
            state = "approved"
        elif status == "changes-needed":
            state = "changes-needed"
        elif was_approved and meta.get("changed_since_approval"):
            state = "changed"
        else:
            state = "open"
        out.append({
            "id": key, "label": stage.LABELS[key], "who": stage.WHO[who], "exists": exists, "state": state,
            "status": status or None, "approved_by": text_or_none(meta.get("approved_by")),
            "approved_on": text_or_none(meta.get("approved_on")),
            "conditions": [str(c) for c in meta.get("conditions") or []] if isinstance(meta.get("conditions"), list) else [],
            "version": meta.get("version"), "updated": mtime(path) if exists else None,
        })
    return out


def column(status, auto_state):
    """Where a task sits on the board."""
    if status == "done":
        return "done"
    if status == "in-review":
        return "review"
    if status == "in-progress":
        return "committed" if auto_state == "committed" else "building"
    return "todo"


def first_words(text, limit=220):
    """The first sentence or two of a piece of Markdown, as plain text."""
    lines = []
    for line in plain.prose(text or "").split("\n"):
        line = line.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith(">"):
            continue
        lines.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", line))
    flat = " ".join(lines)
    flat = re.sub(r"\*\*([^*]+)\*\*", r"\1", flat)
    flat = re.sub(r"`([^`]*)`", r"\1", flat)
    flat = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", flat)
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return cut[:stop + 1] if stop > limit // 3 else cut.rsplit(" ", 1)[0] + " ..."


def load_tasks(folder):
    """Like tasklib.load_tasks, but one unreadable file does not lose the others."""
    found = []
    try:
        files = sorted(p for p in Path(folder).glob("T*.md") if p.is_file())
    except OSError:
        return found
    for p in files:
        try:
            found.append(tasklib.Task(p))
        except Exception:  # noqa: BLE001
            continue

    def number(t):
        m = re.search(r"\d+", t.id or "")
        return (int(m.group(0)) if m else 0, t.id)
    return sorted(found, key=number)


def task_list(f, auto):
    """Every task with its Summary lines, its place on the board and its auto run state."""
    auto_tasks = auto.get("tasks") if isinstance(auto, dict) and isinstance(auto.get("tasks"), dict) else {}
    current = auto.get("current") if isinstance(auto, dict) else None
    found = load_tasks(Path(f.path) / tasklib.TASKS_DIR)
    status_of = {t.id: t.meta.get("status") for t in found}
    built = {tid for tid, a in auto_tasks.items() if isinstance(a, dict) and a.get("state") == "committed"}
    out = []
    for t in found:
        run = auto_tasks.get(t.id) if isinstance(auto_tasks.get(t.id), dict) else None
        state = run.get("state") if run else None
        points = plain.summary_points(t.text, 3)
        if not points:
            goal = tasklib.find_section(t.body, "Goal")
            first = first_words(goal[1]) if goal else ""
            points = [first] if first else []
        status = str(t.meta.get("status") or "todo")
        deps = str_list(t.meta.get("depends_on"))
        info = None
        if run:
            info = {"state": text_or_none(state), "round": run.get("round") or 0, "why": text_or_none(run.get("why")),
                    "commit": text_or_none(run.get("commit")), "subject": text_or_none(run.get("subject")),
                    "asked": run.get("asked_total") or len(run.get("asked") or []),
                    "parked": len(run.get("parked") or []), "left": len(run.get("left") or []),
                    "fixed": run.get("fixed") or 0, "tests": len(run.get("tests") or []),
                    "started": text_or_none(run.get("started")), "ended": text_or_none(run.get("ended"))}
        out.append({
            "id": t.id, "title": str(t.meta.get("title") or t.slug.replace("-", " ")), "repo": text_or_none(t.meta.get("repo")),
            "wave": t.meta.get("wave"), "size": text_or_none(t.meta.get("size")), "status": status,
            "kind": text_or_none(t.meta.get("kind")), "owner": text_or_none(t.meta.get("owner")),
            "depends_on": deps, "waits_for": [d for d in deps if d in status_of and status_of[d] != "done" and d not in built],
            "touches": str_list(t.meta.get("touches")), "stories": str_list(t.meta.get("stories")),
            "package": text_or_none(t.meta.get("package")),
            "pr": safe_url(t.meta.get("pr")), "path": "%s/%s" % (tasklib.TASKS_DIR, t.path.name),
            "summary": points, "column": column(status, state), "auto": info, "current": t.id == current,
            "updated": mtime(t.path),
        })
    return out


def run_view(auto):
    """The auto run in a few plain facts, or None."""
    if not isinstance(auto, dict) or not isinstance(auto.get("tasks"), dict):
        return None
    repos = {}
    for name, r in (auto.get("repos") or {}).items() if isinstance(auto.get("repos"), dict) else []:
        if not isinstance(r, dict):
            continue
        paused = r.get("paused") if isinstance(r.get("paused"), dict) else None
        repos[str(name)] = {"build_branch": text_or_none(r.get("build_branch")), "pushed": text_or_none(r.get("pushed")),
                            "pr": safe_url(r.get("pr")),
                            "paused": {"task": text_or_none(paused.get("task")), "why": text_or_none(paused.get("why"))}
                            if paused else None}
    return {"started": text_or_none(auto.get("started")), "finished": text_or_none(auto.get("finished")),
            "by": text_or_none(auto.get("by")), "current": text_or_none(auto.get("current")),
            "feature_branch": text_or_none(auto.get("feature_branch")), "base_branch": text_or_none(auto.get("base_branch")),
            "queue": str_list(auto.get("queue")), "repos": repos}


def web_base(remote):
    """The web page of a git remote on a known host, or None. git@github.com:o/r.git -> ("github", "https://github.com/o/r")."""
    remote = (remote or "").strip()
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", remote) or \
        re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote)
    if not m:
        return None, None
    host, path = m.group(1).lower(), m.group(2)
    if host == "ssh.dev.azure.com":                     # git@ssh.dev.azure.com:v3/org/project/repo
        parts = path.split("/")
        if len(parts) == 4 and parts[0] == "v3":
            return "azure", "https://dev.azure.com/%s/%s/_git/%s" % tuple(parts[1:])
        return None, None
    if host.endswith("dev.azure.com") or host.endswith("visualstudio.com"):
        return "azure", "https://%s/%s" % (host, path)
    for name in ("github", "gitlab", "bitbucket"):
        if name in host:
            return name, "https://%s/%s" % (host, path)
    return None, None


def new_pr_url(kind, base, head, into):
    """The host's "create a pull request" page for head into `into`."""
    q = lambda v: quote(v, safe="")
    if kind == "github":
        return "%s/compare/%s...%s?expand=1" % (base, quote(into, safe="/"), quote(head, safe="/"))
    if kind == "gitlab":
        return "%s/-/merge_requests/new?merge_request%%5Bsource_branch%%5D=%s&merge_request%%5Btarget_branch%%5D=%s" % (base, q(head), q(into))
    if kind == "bitbucket":
        return "%s/pull-requests/new?source=%s&dest=%s" % (base, q(head), q(into))
    if kind == "azure":
        return "%s/pullrequestcreate?sourceRef=%s&targetRef=%s" % (base, q(head), q(into))
    return None


def remote_of(path):
    try:
        out = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def add_repo_places(run, auto, f, ws):
    """Where each repo lives and where its PR text is, as paths from the project folder, for the steps on the page."""
    if not run or not isinstance(auto, dict):
        return
    project = Path(ws).resolve().parent
    for name, r in (auto.get("repos") or {}).items():
        view = run["repos"].get(str(name))
        if view is None or not isinstance(r, dict):
            continue
        try:
            view["path"] = posixpath.normpath(os.path.relpath(str(Path(str(r.get("path") or "")).resolve()), str(project)))
        except (OSError, ValueError):
            view["path"] = None
        kind, web = web_base(remote_of(r.get("path"))) if r.get("path") else (None, None)
        view["host"], view["web"] = kind, web
        view["new_pr_url"] = new_pr_url(kind, web, view.get("build_branch") or "", run.get("feature_branch") or "") \
            if web and view.get("build_branch") and run.get("feature_branch") else None
        pr_file = (Path(f.path) / "work" / "auto" / ("pr-%s.md" % name)).resolve()
        view["pr_file"] = posixpath.normpath(os.path.relpath(str(pr_file), str(project))) if pr_file.is_file() else None
        try:
            view["pr_title"] = pr_file.read_text(encoding="utf-8").split("\n", 1)[0].strip().lstrip("# ").strip()[:200] or None
        except OSError:
            view["pr_title"] = None


def pr_links(prs, run, tasks):
    """Every PR link we know for a feature, each one once."""
    out, by_url = [], {}

    def add(url, **info):
        url = safe_url(url)
        if not url:
            return
        row = by_url.get(url)
        if row is None:
            row = by_url[url] = {"url": url, "id": None, "repo": None, "title": None, "state": None,
                                 "review": None, "draft": False, "tasks": []}
            out.append(row)
        for key, value in info.items():
            if key == "task":
                if value and value not in row["tasks"]:
                    row["tasks"].append(value)
            elif value not in (None, "") and row.get(key) in (None, "", False):
                row[key] = value

    for p in prs:
        add(p.get("url"), id=text_or_none(p.get("id")), repo=text_or_none(p.get("repo")), title=text_or_none(p.get("title")),
            state=text_or_none(p.get("state")), review=text_or_none(p.get("review")), draft=bool(p.get("draft")))
    for name, r in ((run or {}).get("repos") or {}).items():
        add(r.get("pr"), repo=name)
    for t in tasks:
        add(t.get("pr"), repo=t.get("repo"), task=t.get("id"))
    return out


def feature(ws, number):
    f = find_feature(ws, number)
    row = feature_row(f)
    auto = read_json(stage.paths(f)["auto"])
    out = dict(row)
    out["counts"] = {"tasks": row.get("tasks"), "comments": row.get("comments")}
    out["docs"] = doc_list(f)
    out["tasks"] = task_list(f, auto)
    out["events"] = list(reversed(events.read(f, EVENTS)))
    out["comments"] = comments(stage.paths(f)["comments"])
    out["gates"] = gates(f)
    out["run"] = run_view(auto)
    add_repo_places(out["run"], auto, f, ws)
    out["links"] = pr_links(out["comments"]["prs"], out["run"], out["tasks"])
    out["changes"] = spec_changes(f, out["tasks"])
    return out


def spec_changes(f, tasks):
    """The files the spec adds, changes and deletes, per repo, for the Changes view. None without a spec."""
    spec = read_json(stage.paths(f)["spec_json"])
    if not isinstance(spec, dict):
        return None
    try:
        out = changes.collect(spec, tasks)
    except Exception:  # noqa: BLE001  a half-written spec must not break the page
        return None
    status = {t["id"]: t.get("column") or t.get("status") for t in tasks}
    for r in out["repos"]:
        for row in r["files"]:
            row["task_status"] = {tid: status.get(tid) for tid in row["tasks"]}
    return out


# --------------------------------------------------------------------------- review comments


def empty_counts():
    return {"open": 0, "merged": 0, "closed": 0, "threads": 0, "live": 0, "new": 0, "undecided": 0, "to_fix": 0,
            "fixed": 0, "replied": 0, "by_verdict": {v: 0 for v in stage.VERDICTS}, "groups": 0, "watching": False}


def thread_flags(thread, item):
    """live: still open. new: not explained yet. needs_call: a person must say fix, reply or skip."""
    live = not thread.get("resolved") and not thread.get("outdated")
    fresh = not item or item.get("hash") != thread.get("hash")
    needs = (live and not fresh and item.get("state") not in ("fixed", "replied") and not item.get("decision")
             and item.get("verdict") in stage.NEEDS_DECISION)
    return {"live": bool(live), "new": bool(live and fresh), "needs_call": bool(needs)}


def comments(folder):
    """prs.json, threads.json and triage.json of one review store, in shapes the page can trust."""
    folder = Path(folder)
    prs_doc = read_json(folder / "prs.json")
    threads_doc = read_json(folder / "threads.json")
    triage_doc = read_json(folder / "triage.json")
    prs_doc = prs_doc if isinstance(prs_doc, dict) else {}
    threads_doc = threads_doc if isinstance(threads_doc, dict) else {}
    triage_doc = triage_doc if isinstance(triage_doc, dict) else {}

    prs = []
    for p in dicts(prs_doc.get("prs")):
        p = dict(p)
        p["id"] = str(p.get("id") or p.get("url") or "")
        p["url"] = safe_url(p.get("url"))
        prs.append(p)
    raw_items = triage_doc.get("items") if isinstance(triage_doc.get("items"), dict) else {}
    items = {str(k): v for k, v in raw_items.items() if isinstance(v, dict)}
    threads = []
    for t in dicts(threads_doc.get("threads")):
        if not t.get("id"):
            continue
        t = dict(t)
        t["id"] = str(t["id"])
        t["url"] = safe_url(t.get("url"))
        t["body"] = "" if t.get("body") is None else str(t.get("body"))
        t["replies"] = dicts(t.get("replies"))
        t["flags"] = thread_flags(t, items.get(t["id"]))
        threads.append(t)
    groups = []
    for g in dicts(triage_doc.get("groups")):
        g = dict(g)
        g["id"] = str(g.get("id") or "")
        g["threads"] = [str(x) for x in g.get("threads")] if isinstance(g.get("threads"), list) else []
        g["files"] = [str(x) for x in g.get("files")] if isinstance(g.get("files"), list) else []
        groups.append(g)
    try:
        counts = {k: v for k, v in stage.comments_view(folder).items() if k != "prs"}
    except Exception:  # noqa: BLE001  a file in an odd shape: count what we can ourselves
        counts = empty_counts()
        counts.update(threads=len(threads), live=sum(1 for t in threads if t["flags"]["live"]),
                      new=sum(1 for t in threads if t["flags"]["new"]),
                      undecided=sum(1 for t in threads if t["flags"]["needs_call"]), groups=len(groups),
                      open=sum(1 for p in prs if p.get("state") == "open"),
                      merged=sum(1 for p in prs if p.get("state") == "merged"),
                      closed=sum(1 for p in prs if p.get("state") == "closed"))
    watch = prs_doc.get("watch") if isinstance(prs_doc.get("watch"), dict) else None
    return {"exists": folder.is_dir(), "prs": prs, "threads": threads,
            "triage": {"updated": text_or_none(triage_doc.get("updated")), "items": items, "groups": groups},
            "watch": watch, "fetched": text_or_none(threads_doc.get("fetched")), "counts": counts}


def review_wait(counts, prs):
    """(who, sentence) for a review store on its own, in the words stage.read() uses."""
    if counts.get("new"):
        return "chopchop", "%d new review comment(s) to explain." % counts["new"]
    if counts.get("undecided"):
        return "you", "%d review comment(s) need your call: fix, reply or skip." % counts["undecided"]
    if counts.get("to_fix"):
        return "chopchop", "%d review comment(s) to fix." % counts["to_fix"]
    if prs and not counts.get("open"):
        return None, "Every PR is merged or closed."
    if prs:
        return "reviewers", "The PRs wait for review and merge."
    return None, "No PR data yet."


# --------------------------------------------------------------------------- PRs without a feature


def pr_stores(ws):
    """[(slug, folder)] of _chopchop/prs/<slug>/ folders that hold a review store."""
    root = Path(ws) / "prs"
    out = []
    try:
        folders = sorted(root.iterdir(), key=lambda p: p.name)
        base = root.resolve()
    except OSError:
        return out
    for p in folders:
        try:
            if not SLUG_RE.match(p.name) or not (p / "work" / "comments").is_dir():
                continue
            p.resolve().relative_to(base)
        except (OSError, ValueError):
            continue
        out.append((p.name, p))
    return out


def pr_row(slug, folder, full=False):
    data = comments(folder / "work" / "comments")
    who, text = review_wait(data["counts"], data["prs"])
    title = next((str(p["title"]) for p in data["prs"] if p.get("title")), slug)
    row = {"slug": slug, "title": title, "prs": data["prs"], "counts": data["counts"], "waiting_on": who,
           "waiting_who": stage.WHO.get(who) if who else None, "waiting": text, "updated": updated(folder)}
    if full:
        row["comments"] = data
        row["events"] = list(reversed(events.read(folder, EVENTS)))
        row["links"] = pr_links(data["prs"], None, [])
    return row


def pr_list(ws):
    return {"prs": [pr_row(slug, folder) for slug, folder in pr_stores(ws)]}


def pr(ws, slug):
    for name, folder in pr_stores(ws):
        if name == slug:
            return pr_row(name, folder, full=True)
    raise NotFound("No PR store named %s." % slug)


# --------------------------------------------------------------------------- documents


def safe_path(root, rel):
    """The file a request may read: a .md or .json file that really lives inside root."""
    rel = (rel or "").strip()
    if not rel:
        raise Refused("Say which file: ?path=design/design.md")
    pure = PurePosixPath(rel)
    if ("\x00" in rel or "\\" in rel or pure.is_absolute() or re.match(r"^[A-Za-z]:", rel)
            or any(part in ("..", ".") or part.startswith(".") for part in pure.parts)):
        raise Refused("That path is not allowed. Give a path inside the feature folder.")
    if pure.suffix.lower() not in DOC_TYPES:
        raise Refused("Only .md and .json files can be shown.")
    try:
        base = Path(root).resolve()
        target = base.joinpath(*pure.parts).resolve()
        target.relative_to(base)
    except (OSError, ValueError, RuntimeError):
        raise Refused("That file is outside the feature folder.")
    if not target.is_file():
        raise NotFound("No such file: %s" % rel)
    return target


def draw_design(body, folder):
    """Swap the generated Mermaid of design.md for chopchop's own drawings, when the JSON is there.

    Returns (body, {token: svg}, [names drawn]). The Mermaid stays when a drawing is not possible."""
    arch = read_json(Path(folder) / "architecture.json")
    flow = read_json(Path(folder) / "flow.json")
    arch = arch if isinstance(arch, dict) else None
    flow = flow if isinstance(flow, dict) else None
    swaps, drawn = {}, []
    for name, data in (("architecture", arch), ("flow", flow)):
        if not data:
            continue
        try:
            svg = diagrams.architecture_svg(data) if name == "architecture" else diagrams.flow_svg(data, arch)
        except Exception:  # noqa: BLE001  a JSON file the drawer cannot use: keep the Mermaid
            continue
        if not isinstance(svg, str) or "<svg" not in svg or re.search(r"<\s*script", svg, re.I):
            continue
        m = re.search(r"(<!-- chopchop:%s -->)(.*?)(<!-- /chopchop:%s -->)" % (name, name), body, re.S)
        fence = MERMAID_FENCE.search(m.group(2)) if m else None
        if not fence:
            continue
        token = "CHOPCHOPDRAWING%s" % secrets.token_hex(8)
        inner = m.group(2)[:fence.start()] + "\n\n" + token + "\n\n" + m.group(2)[fence.end():]
        body = body[:m.start(2)] + inner + body[m.end(2):]
        swaps[token] = svg
        drawn.append(name)
    return body, swaps, drawn


def doc_link(f, rel):
    """Turns a relative link inside a document into a page link, when it points at another document."""
    base = PurePosixPath(rel).parent

    def link(url):
        target = unquote(url.split("#", 1)[0].split("?", 1)[0])
        if not target or target.startswith("/"):
            return None
        norm = posixpath.normpath(str(base / target))
        try:
            safe_path(f.path, norm)
        except ApiError:
            return None
        return "#/f/%d/doc/%s" % (f.number, quote(norm, safe="/"))
    return link


def render_file(path, rel, feature_=None):
    """{title, html, summary, updated, raw} and a few extras for one .md or .json file."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        raise NotFound("No such file: %s" % rel)
    if size > MAX_DOC:
        raise TooBig("%s is too big to show (%d KB)." % (rel, size // 1024))
    raw = read_text(path)
    base = {"path": rel, "name": path.name, "updated": mtime(path), "raw": raw, "summary": [], "toc": [],
            "meta": {}, "drawn": [], "words": 0, "minutes": 0}
    if path.suffix.lower() == ".json":
        try:
            pretty = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
        except ValueError:
            pretty = raw
        note = "" if len(pretty) <= JSON_SHOW else "<p><em>Only the first part of this file is shown.</em></p>"
        base.update(kind="json", title=path.name,
                    html='<pre class="code"><code class="lang-json">%s</code></pre>%s'
                         % (html.escape(pretty[:JSON_SHOW], quote=False), note))
        return base
    try:
        meta, body = parse_front_matter(raw)
    except Exception:  # noqa: BLE001
        meta, body = {}, raw
    swaps, drawn = {}, []
    # The page draws the design's Mermaid itself, in the theme's colours (draw_design stays for other callers).
    embed = None
    if feature_ is not None and rel == "spec/spec.md":
        m = re.search(r"<!-- chopchop:files -->(.*?)<!-- /chopchop:files -->", body, re.S)
        if m:
            embed = "CHOPCHOPCHANGES%s" % secrets.token_hex(8)
            body = body[:m.start(1)] + "\n\n%sA\n\n%s\n\n%sZ\n\n" % (embed, m.group(1), embed) + body[m.end(1):]
    try:
        out = md.render(body, link=doc_link(feature_, rel) if feature_ is not None else None)
    except Exception:  # noqa: BLE001  never fail a page over one odd file: show it as text
        out = {"html": '<pre class="code"><code>%s</code></pre>' % html.escape(body, quote=False), "toc": [], "title": None}
    page = out["html"]
    if embed:   # the page swaps this box for the file explorer; the text tree inside stays for when it cannot
        page = page.replace("<p>%sA</p>" % embed, '<div class="ch-embed">').replace("<p>%sZ</p>" % embed, "</div>")
    for token, svg in swaps.items():
        box = '<div class="diagram drawn">%s</div>' % svg
        page = page.replace("<p>%s</p>" % token, box) if "<p>%s</p>" % token in page else page.replace(token, box)
    words = plain.words(body)
    base.update(kind="md", title=str(meta.get("title") or out["title"] or path.stem), html=page,
                summary=plain.summary_points(raw, 5), toc=out["toc"], drawn=drawn, words=words,
                minutes=max(1, int(round(words / 200.0))) if words else 0,
                meta={k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, list)) or v is None})
    return base


def doc(ws, number, rel):
    f = find_feature(ws, number)
    path = safe_path(f.path, rel)
    return render_file(path, str(PurePosixPath((rel or "").strip())), f)


def system_path(ws):
    path = Path(ws) / "system" / "system-map.md"
    try:
        if not path.is_file():
            return None
        path.resolve().relative_to(Path(ws).resolve())
    except (OSError, ValueError):
        return None
    return path


def system(ws):
    path = system_path(ws)
    if path is None:
        raise NotFound("No system map yet. /chopchop:learn writes it.")
    out = render_file(path, "system/system-map.md")
    out["title"] = "System map"
    return out
