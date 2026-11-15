"""The changes a spec makes, file by file: what is new, what changes, what goes away.

One merged list per repo, from the packages in spec.json. A file two packages touch shows once.
The spec writes it as a folder tree (spec.md section 6), and the dashboard draws the same data as
an editor's file explorer.

  {"repos": [{"repo": "shop-api", "counts": {"new": 1, "change": 3, "delete": 0},
              "files": [{"path": "src/models/order.js", "change": "change", "what": ["..."],
                         "packages": ["P1"], "tasks": ["T01"], "test": false}]}],
   "counts": {"new": 1, "change": 3, "delete": 0}, "total": 4}
"""

import re

CHANGES = ["new", "change", "delete"]
MARK = {"new": "A", "change": "M", "delete": "D"}
WORD = {"new": "new", "change": "changed", "delete": "deleted"}
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec|specs)/|(\.|_)(test|spec)\.[a-z0-9]+$|(^|/)test_[^/]+$", re.I)


def _list(value):
    return value if isinstance(value, list) else []


def merge(old, new):
    """Two packages touch one file. A new file stays new, a delete wins over a change."""
    if "new" in (old, new):
        return "new"
    if "delete" in (old, new):
        return "delete"
    return "change"


def collect(spec, tasks=None):
    """The merged changes of a spec. tasks: optional [{"id", "repo", "package", "touches"}] to link files to tasks."""
    by_repo = {}
    for p in _list((spec or {}).get("packages")):
        if not isinstance(p, dict):
            continue
        repo = str(p.get("repo") or "?")
        files = by_repo.setdefault(repo, {})
        for f in _list(p.get("files")):
            if not isinstance(f, dict) or not f.get("path"):
                continue
            path = str(f["path"]).strip().lstrip("./")
            change = f.get("change") if f.get("change") in CHANGES else "change"
            row = files.get(path)
            if row is None:
                row = files[path] = {"path": path, "change": change, "what": [], "packages": [], "tasks": [],
                                     "test": bool(TEST_RE.search(path))}
            else:
                row["change"] = merge(row["change"], change)
            what = str(f.get("what") or "").strip()
            if what and what not in row["what"]:
                row["what"].append(what)
            if p.get("id") and p["id"] not in row["packages"]:
                row["packages"].append(str(p["id"]))
    for t in tasks or []:
        repo = t.get("repo")
        for row in (by_repo.get(repo) or {}).values():
            if (t.get("package") and t["package"] in row["packages"]) or row["path"] in _list(t.get("touches")):
                if t["id"] not in row["tasks"]:
                    row["tasks"].append(t["id"])
    repos, total = [], {c: 0 for c in CHANGES}
    for repo in sorted(by_repo):
        files = sorted(by_repo[repo].values(), key=lambda r: r["path"].lower())
        counts = {c: sum(1 for r in files if r["change"] == c) for c in CHANGES}
        for c in CHANGES:
            total[c] += counts[c]
        repos.append({"repo": repo, "counts": counts, "files": files})
    return {"repos": repos, "counts": total, "total": sum(total.values())}


def sentence(text):
    """A capital letter and a full stop, but never touch a code name such as findAll or REFUND_STATUS."""
    text = text.strip().rstrip(".")
    first = text.split(" ", 1)[0]
    if first.isalpha() and first.islower():
        text = text[:1].upper() + text[1:]
    return text + "."


def count_line(counts):
    parts = ["%d %s" % (counts[c], WORD[c]) for c in CHANGES if counts.get(c)]
    return ", ".join(parts) or "no files"


# --------------------------------------------------------------------------- the tree as text


def _tree(files):
    root = {}
    for f in files:
        node = root
        parts = f["path"].split("/")
        for part in parts[:-1]:
            node = node.setdefault(part + "/", {})
        node[parts[-1]] = f
    return root


def _compact(name, node):
    """Fold a chain of folders that each hold one folder, the way an editor shows src/main/java."""
    while isinstance(node, dict) and len(node) == 1:
        (child, sub), = node.items()
        if not child.endswith("/"):
            break
        name, node = name + child, sub
    return name, node


def tree_lines(files):
    """Text lines of a folder tree with a mark at the end of each file: A new, M changed, D deleted. For chat replies."""
    rows = []

    def walk(node, prefix):
        items = sorted(node.items(), key=lambda kv: (not kv[0].endswith("/"), kv[0].lower()))
        for i, (name, sub) in enumerate(items):
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            if name.endswith("/"):
                name, sub = _compact(name, sub)
                rows.append((prefix + branch + name, ""))
                walk(sub, prefix + ("    " if last else "│   "))
            else:
                rows.append((prefix + branch + name, "%s  %s" % (MARK[sub["change"]], " ".join(sub["packages"]))))

    walk(_tree(files), "")
    width = max([len(left) for left, _ in rows] + [20]) + 3
    return [(left.ljust(width) + right).rstrip() for left, right in rows]


def list_lines(files):
    """The folder tree as a nested Markdown list: it reads as a tree anywhere, with no text box."""
    out = []

    def walk(node, depth):
        items = sorted(node.items(), key=lambda kv: (not kv[0].endswith("/"), kv[0].lower()))
        for name, sub in items:
            pad = "  " * depth
            if name.endswith("/"):
                name, sub = _compact(name, sub)
                out.append("%s- `%s`" % (pad, name))
                walk(sub, depth + 1)
                continue
            word = WORD[sub["change"]]
            label = "~~`%s`~~" % name if sub["change"] == "delete" else "`%s`" % name
            what = " ".join(sentence(w) for w in sub["what"])
            line = "%s- %s **%s**%s" % (pad, label, word, ": " + what if what else "")
            if sub["packages"]:
                line += " _(%s)_" % ", ".join(sub["packages"])
            out.append(line)

    walk(_tree(files), 0)
    return out


def render(changes):
    """The Markdown for spec.md section 6: one folder tree per repo, as nested lists, with the reason for each file."""
    if not changes["total"]:
        return "None."
    n = len(changes["repos"])
    out = ["**In short:** %d files in %d repo%s: %s." % (
        changes["total"], n, "" if n == 1 else "s", count_line(changes["counts"])), ""]
    for r in changes["repos"]:
        out += ["### %s" % r["repo"], "", "%s." % count_line(r["counts"]).capitalize(), ""]
        out += list_lines(r["files"])
        out.append("")
    return "\n".join(out).rstrip()
