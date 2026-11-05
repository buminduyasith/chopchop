"""Citations: every claim about today's code points at the lines it came from.

A citation is written as repo/path:start-end@commit, for example
`payments-api/src/payouts/PayoutJob.java:35-40@a1f9c2e`. The commit is the one the lines
were read at. The check compares those lines with the repo's HEAD:

  fresh    the same lines are at the same place
  moved    the same lines are somewhere else in the file (the numbers can be fixed)
  changed  the file is there, but the cited lines are not
  gone     the file is gone, or the cited lines never existed
  unknown  the repo or the commit cannot be found here, so nothing can be compared

Code lines that go into a page pass a secret scan first, and secrets are masked.
"""

import re
import subprocess
from pathlib import Path

CITE_RE = re.compile(
    r"(?<![\w/.@-])(?P<repo>[A-Za-z0-9_.-]+)/(?P<path>[^\s:@`'\"<>()\[\]|]+)"
    r":(?P<start>\d+)(?:-(?P<end>\d+))?@(?P<commit>[0-9a-fA-F]{7,40})(?![\w])")
STATUSES = ["fresh", "moved", "changed", "gone", "unknown"]
BLOCKING = {"gone"}
MAX_LINES = 40

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
               r"(\s*[:=]\s*|\s*\"\s*:\s*)(['\"])[^'\"\s]{6,}\3"),
]


def find(text):
    """All citations in a text, in order, without duplicates."""
    seen, out = set(), []
    for m in CITE_RE.finditer(text or ""):
        if m.group(0) in seen:
            continue
        seen.add(m.group(0))
        start = int(m.group("start"))
        end = int(m.group("end") or start)
        out.append({"raw": m.group(0), "repo": m.group("repo"), "path": m.group("path"),
                    "start": start, "end": max(start, end), "commit": m.group("commit")})
    return out


def write(repo, path, start, end, commit):
    lines = "%d" % start if end == start else "%d-%d" % (start, end)
    return "%s/%s:%s@%s" % (repo, path, lines, commit[:7])


def short(c):
    """What a page shows: the file name and lines."""
    name = c["path"].rsplit("/", 1)[-1]
    return "%s:%s" % (name, c["start"] if c["end"] == c["start"] else "%d-%d" % (c["start"], c["end"]))


# --------------------------------------------------------------------------- git


def _git(path, *args):
    try:
        out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def head(repo_dir):
    out = _git(repo_dir, "rev-parse", "HEAD")
    return out.strip() if out else None


def file_at(repo_dir, commit, path):
    out = _git(repo_dir, "show", "%s:%s" % (commit, path))
    return None if out is None else out.split("\n")


# --------------------------------------------------------------------------- check


def _same(a, b):
    return [x.rstrip() for x in a] == [x.rstrip() for x in b]


def check(c, repo_dirs, heads=None):
    """Compare one citation with the repo's HEAD. repo_dirs: {repo name: Path}."""
    heads = heads if heads is not None else {}
    res = dict(c, status="unknown", new_start=c["start"], new_end=c["end"], head=None, old=None, now=None, note="")
    rdir = repo_dirs.get(c["repo"])
    if rdir is None or not Path(rdir).is_dir():
        res["note"] = "repo %s is not in chopchop.yaml" % c["repo"]
        return res
    if c["repo"] not in heads:
        heads[c["repo"]] = head(rdir)
    hd = heads[c["repo"]]
    if not hd:
        res["note"] = "%s is not a git repo" % c["repo"]
        return res
    res["head"] = hd
    old_file = file_at(rdir, c["commit"], c["path"])
    new_file = file_at(rdir, "HEAD", c["path"])
    if old_file is None:
        if new_file is None:
            res.update(status="gone", note="the file is not in the repo")
        else:
            res["note"] = "commit %s is not in this clone, so the lines cannot be compared" % c["commit"][:7]
            res["now"] = new_file[c["start"] - 1:c["end"]]
        return res
    old = old_file[c["start"] - 1:c["end"]]
    res["old"] = old
    if len(old) != c["end"] - c["start"] + 1 or not any(x.strip() for x in old):
        res.update(status="gone", note="lines %d-%d are not in %s at %s" % (c["start"], c["end"], c["path"], c["commit"][:7]))
        return res
    if new_file is None:
        res.update(status="gone", note="the file was removed or renamed after %s" % c["commit"][:7])
        return res
    now = new_file[c["start"] - 1:c["end"]]
    if _same(old, now):
        res.update(status="fresh", now=now)
        return res
    n = len(old)
    hits = [i for i in range(len(new_file) - n + 1) if _same(new_file[i:i + n], old)]
    if hits:
        best = min(hits, key=lambda i: abs(i + 1 - c["start"]))
        res.update(status="moved", new_start=best + 1, new_end=best + n, now=new_file[best:best + n],
                   note="now at lines %d-%d" % (best + 1, best + n))
        return res
    res.update(status="changed", now=now, note="the code at these lines changed after %s" % c["commit"][:7])
    return res


def check_all(cites, repo_dirs):
    heads = {}
    return [check(c, repo_dirs, heads) for c in cites]


def fixed_raw(r):
    """The citation as it should now be written, or None when it cannot be fixed by itself."""
    if r["status"] == "moved" or (r["status"] == "fresh" and r["head"] and not r["head"].startswith(r["commit"])):
        return write(r["repo"], r["path"], r["new_start"], r["new_end"], r["head"])
    return None


def fix_text(text, results):
    """Rewrite moved citations (and fresh ones read at an older commit) to HEAD. Returns (text, count)."""
    count = 0
    for r in results:
        new = fixed_raw(r)
        if new and new != r["raw"] and r["raw"] in text:
            text = text.replace(r["raw"], new)
            count += 1
    return text, count


def summary(results):
    counts = {s: 0 for s in STATUSES}
    for r in results:
        counts[r["status"]] += 1
    return counts


# --------------------------------------------------------------------------- snippets


def mask(line):
    """Returns (line, masked?). Anything that looks like a key, token or password is hidden."""
    hit = False
    for pat in SECRET_PATTERNS:
        if pat.search(line):
            hit = True
            line = pat.sub(lambda m: (m.group(1) + m.group(2) + m.group(3) + "*****" + m.group(3))
                           if m.re.groups >= 3 else "*****", line)
    return line, hit


def snippet(r):
    """Numbered lines for a page, masked. Uses HEAD's lines when it has them, else the cited ones."""
    lines = r.get("now") or r.get("old") or []
    first = r.get("new_start") or r["start"]
    out, masked = [], False
    for i, line in enumerate(lines[:MAX_LINES]):
        clean, hit = mask(line)
        masked = masked or hit
        out.append([first + i, clean])
    return {"lines": out, "masked": masked, "cut": len(lines) > MAX_LINES}
