"""Review a code change: build the pack a reviewer reads, and sort what it finds.

The sort is the guard. The spec is the agreement, so a finding may make the code better but
may not change the plan. Anything that would is parked, whatever the reviewer called it.
Standard library only.
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from . import tasks as tasklib

GROUPS = ["fix", "park", "stop"]
SEVERITIES = ["high", "medium", "low"]
FIX_KINDS = ["bug", "test", "lint", "style", "naming", "placement", "language", "security", "done-when", "scope"]
DIRECTION_KINDS = ["approach", "contract", "rule", "library", "other-task"]
KINDS = FIX_KINDS + DIRECTION_KINDS
GUIDES = ["CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md", ".editorconfig"]
PACK = "pack.md"
PACK_JSON = "pack.json"
DIFF = "diff.patch"
FINDINGS = "findings.json"
SORTED = "sorted.json"


class ReviewError(Exception):
    pass


def now():
    return datetime.now().isoformat(timespec="seconds")


def _git(repo, *args):
    """Like gitops.git, but keeps the output as it is (porcelain lines start with a space)."""
    try:
        out = subprocess.run(["git"] + list(args), cwd=str(repo), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise ReviewError("git %s failed: %s" % (" ".join(args), e))
    return out.returncode, out.stdout or "", (out.stderr or "").strip()


def toplevel(path):
    code, out, err = _git(path, "rev-parse", "--show-toplevel")
    if code:
        raise ReviewError("%s is not inside a git repo." % path)
    return Path(out.strip())


def git_dir(repo):
    code, out, _ = _git(repo, "rev-parse", "--absolute-git-dir")
    return Path(out.strip()) if code == 0 else Path(repo) / ".git"


# --------------------------------------------------------------------------- what changed


def pending(repo):
    """Uncommitted changes, new files included: [{"path", "change", "untracked"}]. Ignored files are left out."""
    code, out, err = _git(repo, "status", "--porcelain", "--untracked-files=all", "-z")
    if code:
        raise ReviewError("git status failed in %s: %s" % (repo, err))
    parts, items, i = out.split("\0"), [], 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:
            i += 1  # the old name follows a rename
        change = "new" if xy == "??" or "A" in xy else "delete" if "D" in xy else "change"
        items.append({"path": path, "change": change, "untracked": xy == "??"})
    return items


def pending_diff(repo, items):
    out = []
    tracked = [x["path"] for x in items if not x["untracked"]]
    if tracked:
        code, text, err = _git(repo, "diff", "HEAD", "--no-color", "--", *tracked)
        if code:
            code, text, err = _git(repo, "diff", "--cached", "--no-color", "--", *tracked)  # a repo with no commit yet
        out.append(text)
    for x in items:
        if x["untracked"]:
            out.append(_git(repo, "diff", "--no-index", "--no-color", "--", "/dev/null", x["path"])[1])
    return "".join(out)


def branch_changes(repo, base):
    """Files and diff of this branch against base, from where they split."""
    code, out, err = _git(repo, "diff", "--name-status", "-z", "%s...HEAD" % base)
    if code:
        raise ReviewError("Cannot compare with %s in %s: %s" % (base, repo, err))
    parts, items, i = out.split("\0"), [], 0
    while i < len(parts):
        status = parts[i]
        i += 1
        if not status:
            continue
        if status[0] in "RC":
            path, i = parts[i + 1], i + 2
        else:
            path, i = parts[i], i + 1
        change = {"A": "new", "D": "delete"}.get(status[0], "change")
        items.append({"path": path, "change": change, "untracked": False})
    diff = _git(repo, "diff", "--no-color", "%s...HEAD" % base)[1]
    return items, diff


def default_base(repo):
    code, out, _ = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out.strip():
        return out.strip()
    for name in ("origin/main", "origin/master", "main", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", name)[0] == 0:
            return name
    raise ReviewError("Cannot tell the base branch. Pass it: --branch <base>.")


def added_lines(diff):
    return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]


# --------------------------------------------------------------------------- the task's limits


def _is_path(token):
    return "/" in token or "*" in token or bool(re.search(r"\.[A-Za-z]{1,5}$", token))


def task_rules(task):
    """What the guard needs from a task file: its files, what it must not change, and its goal."""
    def section(name):
        found = tasklib.find_section(task.body, name)
        return found[1].strip() if found else ""

    do_not = section("Do not change")
    tokens = sorted(set(re.findall(r"`([^`\n]+)`", do_not)))
    return {"id": task.id, "title": task.get("title"), "repo": task.get("repo"),
            "touches": tasklib.as_list(task.get("touches")), "goal": section("Goal"),
            "done_when": section("Done when"), "do_not": do_not,
            "banned_paths": [t for t in tokens if _is_path(t)],
            "banned_names": [t for t in tokens if not _is_path(t) and len(t) > 2]}


def outside(paths, rules, allowed=()):
    """Changed files the task does not list in touches."""
    return [p for p in paths if p not in allowed and not any(tasklib.paths_overlap(p, t) for t in rules["touches"])]


def banned_uses(diff, rules):
    """Names the task says not to use that the change adds."""
    added = "\n".join(added_lines(diff))
    return [n for n in rules["banned_names"] if re.search(r"(?<![\w.])%s(?!\w)" % re.escape(n), added)]


# --------------------------------------------------------------------------- the pack


def write_pack(folder, info, diff):
    """info: repo, repo_path, mode (pending or branch), base, files, round, task (rules) or None,
    task_file, style, guides, profile, parked, fixed_last. Writes pack.md, pack.json and diff.patch."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / DIFF).write_text(diff, encoding="utf-8")
    info = dict(info, diff=str(folder / DIFF), findings=str(folder / FINDINGS), made=now(),
                diff_lines=len(diff.splitlines()))
    (folder / PACK_JSON).write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (folder / PACK).write_text(render_pack(info), encoding="utf-8")
    return folder / PACK


def render_pack(info):
    t = info.get("task")
    what = "pending changes (not committed)" if info["mode"] == "pending" else "this branch against %s" % info["base"]
    head = "# Review pack · %s · round %d" % ("%s %s" % (t["id"], t["title"]) if t else info["repo"], info.get("round") or 1)
    lines = [head, "",
             "- Repo: %s at `%s`, %s." % (info["repo"], info["repo_path"], what),
             "- Diff: `%s` (%d lines). Read all of it." % (info["diff"], info["diff_lines"]),
             "- Write your findings to `%s`." % info["findings"], ""]
    if t:
        lines += ["## The task", "",
                  "- Task file: `%s`. Read Goal, Contract, Code, Done when and Do not change." % info.get("task_file"),
                  "- Files it may touch: %s" % (", ".join("`%s`" % p for p in t["touches"]) or "not listed"), ""]
        if t["do_not"]:
            lines += ["Do not change:", "", t["do_not"], ""]
    lines += ["## How this repo codes", ""]
    lines += ["- Style file (wins over everything else): `%s`" % s for s in info.get("style") or []]
    lines += ["- Guide: `%s`" % g for g in info.get("guides") or []]
    if info.get("profile"):
        lines.append("- Profile (commands and rules): `%s`" % info["profile"])
    if not (info.get("style") or info.get("guides") or info.get("profile")):
        lines.append("- No style file or guide. Judge against the code next to each change.")
    lines += ["", "## Files changed", ""]
    lines += ["- %-6s `%s`" % (f["change"], f["path"]) for f in info["files"]]
    if info.get("parked"):
        lines += ["", "## Already parked, do not raise again", ""]
        lines += ["- %s" % p for p in info["parked"]]
    if info.get("fixed_last"):
        lines += ["", "## Fixed in the last round, check each one is really fixed", ""]
        lines += ["- %s" % p for p in info["fixed_last"]]
    return "\n".join(lines) + "\n"


def next_round(folder_of):
    """folder_of(n) gives the pack folder of round n. Returns the first n with no pack yet."""
    n = 1
    while (Path(folder_of(n)) / PACK_JSON).exists():
        n += 1
    return n


# --------------------------------------------------------------------------- the sort


def load_findings(path):
    path = Path(path)
    if not path.is_file():
        raise ReviewError("No findings at %s. The reviewer writes them there." % path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ReviewError("%s is not valid JSON: %s" % (path, e))
    items = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ReviewError("%s must hold {\"findings\": [...]}." % path)
    return items


def sort(findings, rules=None, changed=()):
    """Put each finding in fix, park or stop. Returns {"fix", "park", "stop", "problems"}."""
    out = {"fix": [], "park": [], "stop": [], "problems": []}
    for n, f in enumerate(findings, 1):
        if not isinstance(f, dict) or not str(f.get("what") or "").strip():
            out["problems"].append("finding %d has no 'what', so it was left out" % n)
            continue
        item = {k: f.get(k) for k in ("file", "line", "kind", "severity", "what", "fix")}
        item["id"] = str(f.get("id") or "F%d" % n)
        item["file"] = re.sub(r"^\./", "", str(item.get("file") or "").strip())
        kind = str(item.get("kind") or "bug").strip().lower()
        sev = str(item.get("severity") or "medium").strip().lower()
        item["kind"], item["severity"] = kind, sev if sev in SEVERITIES else "medium"
        group = str(f.get("group") or "").strip().lower()
        reason = None
        if kind in DIRECTION_KINDS:
            if group == "stop" and item["severity"] == "high":
                reason = "a different direction, and serious: a person decides"
            else:
                group, reason = "park", "a different direction from the spec"
        elif group == "stop" and item["severity"] != "high":
            group, reason = "fix", "only a high severity finding stops a task"
        elif group not in GROUPS:
            group = "fix"
        if group == "fix" and rules:
            why = guard(item, rules, changed)
            if why:
                group, reason = "park", why
        if group == "park" and not reason:
            reason = "the reviewer parked it"
        item["group"], item["reason"] = group, reason
        out[group].append(item)
    return out


def guard(item, rules, changed=()):
    """Why a fix may not be applied by the builder, or None."""
    f = item.get("file") or ""
    if not f:
        return None
    if any(tasklib.paths_overlap(f, b) for b in rules["banned_paths"]):
        return "the task says do not change %s" % f
    if f not in changed and not any(tasklib.paths_overlap(f, t) for t in rules["touches"]):
        return "%s is outside the task's files" % f
    return None


def where(item):
    return "%s%s" % (item.get("file") or "(no file)", ":%s" % item["line"] if item.get("line") else "")


def one_line(item):
    text = "[%s, %s] %s. %s." % (item["kind"], item["severity"], where(item), item["what"].strip().rstrip("."))
    if item.get("fix"):
        text += " Fix: %s" % str(item["fix"]).strip()
    return text


def sort_lines(result):
    lines = []
    for g, title in (("fix", "Fix"), ("park", "Park"), ("stop", "Stop")):
        items = result[g]
        kinds = {}
        for i in items:
            kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
        lines.append("%-9s %d%s" % (title + ":", len(items),
                                    "  (%s)" % ", ".join("%s %d" % kv for kv in sorted(kinds.items())) if items else ""))
    for g in ("stop", "fix", "park"):
        for i in result[g]:
            lines.append("  %-4s %-4s %s%s" % (i["id"], g, one_line(i), "  <- %s" % i["reason"] if i.get("reason") else ""))
    lines += ["Problem:  %s" % p for p in result["problems"]]
    return lines
