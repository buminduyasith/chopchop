"""The system map: every repo, API, event, table and outside system, and how they connect.

It lives in _chopchop/system/system-map.json. Helpers (explorers) read the code and send an
update per repo. The script checks it, merges it and writes system-map.md for people.

  {"version": 1, "updated": "...",
   "repos": {"payments-api": {"path": "../payments-api", "commit": "<sha the map saw>",
             "learned": "2026-11-05", "owners": ["@pay-team"], "kind": "service",
             "summary": "...", "layers": ["controller", "service", "repository", "job"],
             "patterns": [{"text": "...", "cite": "payments-api/src/x.java:42@a1f9c2e"}],
             "hotspots": [{"file": "src/x.java", "changes": 31}], "adrs": ["docs/adr/0003-x.md"]}},
   "nodes": [{"id": "payments-api:refund-api", "name": "Refund API", "kind": "api",
              "repo": "payments-api", "cite": "...", "source": "agent"}],
   "links": [{"from": "web-app:order-page", "to": "payments-api:payments-api", "kind": "call",
              "say": "POST payments", "found_in": "web-app", "cite": "...", "source": "agent"}]}

Entries with "source": "person" were fixed by a person and are never overwritten or removed.
The script fills commit, learned, owners, hotspots and adrs itself.
"""

import json
import re
import subprocess
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .cite import CITE_RE

SYSTEM_DIR = "system"
MAP_FILE = "system-map.json"
MD_FILE = "system-map.md"
NODE_KINDS = ["service", "api", "ui", "job", "table", "topic", "external", "library", "person"]
LINK_KINDS = ["call", "event", "db", "external", "person", "message"]
REPO_KINDS = ["service", "web", "mobile", "library", "job", "infra", "data", "other"]
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
OWNER_FILES = ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS", ".gitlab/CODEOWNERS", ".bitbucket/CODEOWNERS"]
ADR_DIRS = ["docs/adr", "doc/adr", "adr", "docs/decisions", "docs/architecture/decisions", "architecture/decisions"]
GUIDES = ["README.md", "CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md"]
NOISE = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|go\.sum|Cargo\.lock"
                   r"|composer\.lock|Gemfile\.lock|CHANGELOG\.md)$")
MAX_CHANGED = 200


def path_of(ws):
    return Path(ws) / SYSTEM_DIR / MAP_FILE


def load(ws):
    p = path_of(ws)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError("%s is not valid JSON: %s" % (p, e))


def empty():
    return {"version": 1, "updated": None, "repos": {}, "nodes": [], "links": []}


# --------------------------------------------------------------------------- git facts


def _git(path, *args):
    try:
        out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def is_repo(path):
    return Path(path).is_dir() and _git(path, "rev-parse", "--is-inside-work-tree") is not None


def head(path):
    out = _git(path, "rev-parse", "HEAD")
    return out.strip() if out else None


def tracked(path):
    out = _git(path, "ls-files")
    return [l for l in (out or "").split("\n") if l]


def owners(path):
    """Owners of the whole repo from CODEOWNERS: the last rule for * or /. Plus every owner named."""
    for name in OWNER_FILES:
        f = Path(path) / name
        if not f.is_file():
            continue
        main, everyone = [], []
        for line in f.read_text(encoding="utf-8", errors="replace").split("\n"):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            names = [p for p in parts[1:] if p.startswith("@") or "@" in p]
            everyone += [n for n in names if n not in everyone]
            if parts[0] in ("*", "/", "/*", "**"):
                main = names
        return {"file": name, "repo": main or everyone, "all": everyone}
    return {"file": None, "repo": [], "all": []}


def candidates(files):
    """Files worth reading first: API specs, schemas, migrations, ADRs and guides."""
    out = {"openapi": [], "proto": [], "graphql": [], "asyncapi": [], "migrations": [], "adrs": [], "guides": []}
    for f in files:
        low = f.lower()
        name = low.rsplit("/", 1)[-1]
        if re.search(r"(openapi|swagger)[^/]*\.(ya?ml|json)$", name):
            out["openapi"].append(f)
        elif name.endswith(".proto"):
            out["proto"].append(f)
        elif name.endswith((".graphql", ".gql", ".graphqls")):
            out["graphql"].append(f)
        elif "asyncapi" in name and name.endswith((".yaml", ".yml", ".json")):
            out["asyncapi"].append(f)
        elif re.search(r"(^|/)(migrations?|db/migrate|flyway|liquibase|changelog)(/|$)", low) and \
                name.endswith((".sql", ".xml", ".yaml", ".yml", ".rb", ".py", ".js", ".ts", ".go")):
            out["migrations"].append(f)
        elif any(low.startswith(d + "/") for d in ADR_DIRS) and name.endswith(".md"):
            out["adrs"].append(f)
        elif f in GUIDES:
            out["guides"].append(f)
    for k in out:
        out[k] = sorted(out[k])[:60]
    return out


def languages(files, top=5):
    exts = Counter(f.rsplit(".", 1)[-1].lower() for f in files if "." in f.rsplit("/", 1)[-1])
    return [e for e, _ in exts.most_common(top)]


def hotspots(path, commits=300, top=10):
    """Files that changed most often in the last N commits."""
    out = _git(path, "log", "-n", str(commits), "--name-only", "--format=")
    counts = Counter(l for l in (out or "").split("\n") if l and not NOISE.search(l))
    return [{"file": f, "changes": n} for f, n in counts.most_common(top) if n > 1]


def changed_since(path, commit):
    """Files changed from commit to HEAD, or None when the commit is not in this clone."""
    if not commit or _git(path, "cat-file", "-e", commit + "^{commit}") is None:
        return None
    out = _git(path, "diff", "--name-status", commit, "HEAD")
    rows = []
    for line in (out or "").split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        rows.append({"status": parts[0][:1], "file": parts[-1]})
    return rows


def behind(path, commit):
    out = _git(path, "rev-list", "--count", "%s..HEAD" % commit) if commit else None
    return int(out.strip()) if out and out.strip().isdigit() else None


def repo_facts(name, path, known=None):
    """What the script can see without reading code. known: this repo's entry in the map."""
    p = Path(path)
    fact = {"name": name, "path": str(p), "exists": p.is_dir(), "is_repo": False}
    if not p.is_dir() or not is_repo(p):
        fact["mode"] = "missing"
        return fact
    files = tracked(p)
    hd = head(p)
    seen = (known or {}).get("commit")
    fact.update(is_repo=True, head=hd, files=len(files), languages=languages(files),
                owners=owners(p), candidates=candidates(files), map_commit=seen)
    if not seen:
        fact["mode"] = "full"
    else:
        changed = changed_since(p, seen)
        if changed is None:
            fact.update(mode="full", note="the commit the map saw is not in this clone: read it again")
        elif not changed:
            fact["mode"] = "fresh"
        else:
            fact.update(mode="refresh", behind=behind(p, seen), changed=changed[:MAX_CHANGED],
                        changed_count=len(changed))
    return fact


# --------------------------------------------------------------------------- update


def validate(update, repo_names, current=None):
    """Errors and warnings for a helper's update. repo_names: repos in chopchop.yaml."""
    errors, warnings = [], []
    if not isinstance(update, dict):
        return ["the update must be a JSON object"], []
    repos = update.get("repos") or {}
    if not isinstance(repos, dict) or not repos:
        errors.append('"repos" must name at least one repo this update covers')
        repos = {}
    for name, info in repos.items():
        if name not in repo_names:
            errors.append("repo %s is not in chopchop.yaml" % name)
        if not isinstance(info, dict):
            errors.append("repos.%s must be an object" % name)
            continue
        if info.get("kind") and info["kind"] not in REPO_KINDS:
            errors.append("repos.%s.kind must be one of %s" % (name, ", ".join(REPO_KINDS)))
        for i, pat in enumerate(info.get("patterns") or [], 1):
            if not isinstance(pat, dict) or not pat.get("text"):
                errors.append("repos.%s.patterns[%d] needs text" % (name, i))
            elif not pat.get("cite"):
                warnings.append("repos.%s.patterns[%d] has no citation: %s" % (name, i, pat["text"][:60]))
            elif not CITE_RE.fullmatch(pat["cite"]):
                errors.append("repos.%s.patterns[%d].cite is not repo/path:line@commit" % (name, i))
    nodes = update.get("nodes") or []
    ids = {n["id"] for n in (current or {}).get("nodes", []) if isinstance(n, dict) and n.get("id")}
    seen = set()
    for i, n in enumerate(nodes, 1):
        if not isinstance(n, dict):
            errors.append("nodes[%d] must be an object" % i)
            continue
        nid = str(n.get("id") or "")
        if not ID_RE.match(nid):
            errors.append("nodes[%d].id '%s' may only use letters, numbers, dot, dash, colon and underscore" % (i, nid))
        if nid in seen:
            errors.append("node id %s is used twice" % nid)
        seen.add(nid)
        if not n.get("name"):
            errors.append("node %s needs a name" % nid)
        if n.get("kind") not in NODE_KINDS:
            errors.append("node %s: kind must be one of %s" % (nid, ", ".join(NODE_KINDS)))
        if n.get("repo") and n["repo"] not in repo_names:
            warnings.append("node %s: repo %s is not in chopchop.yaml" % (nid, n["repo"]))
        if n.get("cite") and not CITE_RE.fullmatch(n["cite"]):
            errors.append("node %s: cite is not repo/path:line@commit" % nid)
    known = ids | seen
    for i, l in enumerate(update.get("links") or [], 1):
        if not isinstance(l, dict):
            errors.append("links[%d] must be an object" % i)
            continue
        for end in ("from", "to"):
            if l.get(end) not in known:
                errors.append("links[%d].%s '%s' is not a node" % (i, end, l.get(end)))
        if l.get("kind") not in LINK_KINDS:
            errors.append("links[%d]: kind must be one of %s" % (i, ", ".join(LINK_KINDS)))
        if l.get("found_in") not in repos:
            errors.append("links[%d].found_in must name the repo this update covers where the code was found" % i)
        if l.get("cite") and not CITE_RE.fullmatch(l["cite"]):
            errors.append("links[%d]: cite is not repo/path:line@commit" % i)
    return errors, warnings


def _link_key(l):
    return (l.get("from"), l.get("to"), l.get("kind"), (l.get("say") or "").lower())


def merge(current, update, facts):
    """Replace what the update covers. Person entries always stay. facts: {repo: repo_facts()}."""
    m = json.loads(json.dumps(current or empty()))
    covered = set(update.get("repos") or {})
    person_nodes = {n["id"] for n in m["nodes"] if n.get("source") == "person"}
    person_links = {_link_key(l) for l in m["links"] if l.get("source") == "person"}
    new_ids = {n["id"] for n in update.get("nodes") or []}

    def drop_node(n):
        if n.get("source") == "person":
            return False
        return n.get("repo") in covered or (n.get("id") in new_ids)

    m["nodes"] = [n for n in m["nodes"] if not drop_node(n)]
    m["links"] = [l for l in m["links"] if l.get("source") == "person" or l.get("found_in") not in covered]
    for n in update.get("nodes") or []:
        if n["id"] in person_nodes:
            continue
        n = dict(n)
        n.setdefault("source", "agent")
        m["nodes"].append(n)
    have = {_link_key(l) for l in m["links"]}
    for l in update.get("links") or []:
        key = _link_key(l)
        if key in person_links or key in have:
            continue
        l = dict(l)
        l.setdefault("source", "agent")
        m["links"].append(l)
        have.add(key)
    ids = {n["id"] for n in m["nodes"]}
    m["links"] = [l for l in m["links"] if l.get("from") in ids and l.get("to") in ids]
    today = date.today().isoformat()
    for name, info in (update.get("repos") or {}).items():
        old = m["repos"].get(name, {})
        kept = [p for p in old.get("patterns") or [] if p.get("source") == "person"]
        entry = dict(old)
        entry.update({k: v for k, v in info.items() if k != "patterns"})
        entry["patterns"] = kept + [dict(p, source=p.get("source", "agent")) for p in info.get("patterns") or []]
        f = facts.get(name) or {}
        entry.update(path=f.get("path", old.get("path")), commit=f.get("head") or old.get("commit"),
                     learned=today, owners=(f.get("owners") or {}).get("repo", old.get("owners", [])))
        if f.get("is_repo"):
            entry["hotspots"] = hotspots(f["path"])
            entry["adrs"] = (f.get("candidates") or {}).get("adrs", [])
        m["repos"][name] = entry
    m["updated"] = datetime.now().astimezone().replace(microsecond=0).isoformat()
    m["nodes"].sort(key=lambda n: (n.get("repo") or "~", n["id"]))
    return m


def save(ws, m):
    p = path_of(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (p.parent / MD_FILE).write_text(render_md(m), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- reading it


def owners_of(m, repo):
    return list(((m or {}).get("repos") or {}).get(repo, {}).get("owners") or [])


def node(m, nid):
    return next((n for n in (m or {}).get("nodes", []) if n["id"] == nid), None)


def neighbours(m, repos):
    """Nodes in other repos that talk to the given repos: who might be affected."""
    ids = {n["id"] for n in m.get("nodes", []) if n.get("repo") in repos}
    out = []
    for l in m.get("links", []):
        for a, b in ((l["from"], l["to"]), (l["to"], l["from"])):
            if a in ids and b not in ids:
                other = node(m, b)
                if other and other not in out:
                    out.append(other)
    return out


def _mid(nid):
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", nid)


def _label(text):
    return re.sub(r"\s+", " ", re.sub(r"[\[\]{}()<>|\"#;/\\]", " ", str(text))).strip() or "x"


def render_md(m):
    repos = m.get("repos") or {}
    lines = ["# System map", "",
             "_Written by chopchop from system-map.json. Fix entries in the JSON and mark them "
             '`"source": "person"`, so chopchop never overwrites them._', "",
             "Updated: %s" % (m.get("updated") or "never"), "", "## Repos", "",
             "| Repo | Kind | Owners | Layers | Read at | Learned |", "| --- | --- | --- | --- | --- | --- |"]
    for name in sorted(repos):
        r = repos[name]
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            name, r.get("kind") or "-", ", ".join(r.get("owners") or []) or "-",
            ", ".join(r.get("layers") or []) or "-", (r.get("commit") or "-")[:7], r.get("learned") or "-"))
    lines.append("")
    nodes = m.get("nodes") or []
    if nodes:
        lines += ["## How it connects", "", "```mermaid", "flowchart LR"]
        groups = {}
        for n in nodes:
            groups.setdefault(n.get("repo"), []).append(n)
        for repo in sorted(groups, key=lambda r: r or "~"):
            items = groups[repo]
            if repo:
                lines.append("  subgraph g_%s[%s]" % (re.sub(r"[^A-Za-z0-9_]", "_", repo), _label(repo)))
            for n in items:
                shape = {"table": "[(%s)]", "topic": "{{%s}}", "person": "([%s])", "job": "[[%s]]"}.get(n["kind"], "[%s]")
                lines.append("%s%s%s" % ("    " if repo else "  ", _mid(n["id"]), shape % _label(n["name"])))
            if repo:
                lines.append("  end")
        for l in m.get("links") or []:
            say = _label(l.get("say") or "")
            arrow = "-.->" if l.get("kind") == "event" else "-->"
            lines.append("  %s %s%s %s" % (_mid(l["from"]), arrow, "|%s|" % say if say != "x" else "", _mid(l["to"])))
        lines += ["```", ""]
        lines += ["## Parts", "", "| Id | Name | Kind | Repo | Where |", "| --- | --- | --- | --- | --- |"]
        for n in nodes:
            lines.append("| %s | %s | %s | %s | %s |" % (n["id"], n["name"], n["kind"], n.get("repo") or "outside",
                                                         "`%s`" % n["cite"] if n.get("cite") else "-"))
        lines.append("")
    for name in sorted(repos):
        r = repos[name]
        pats = r.get("patterns") or []
        if not pats and not r.get("hotspots"):
            continue
        lines += ["## %s" % name, ""]
        if r.get("summary"):
            lines += [r["summary"], ""]
        if pats:
            lines += ["Patterns:", ""] + ["- %s%s" % (p["text"], " `%s`" % p["cite"] if p.get("cite") else "")
                                         for p in pats] + [""]
        if r.get("hotspots"):
            lines += ["Hotspots (changed most often):", ""] + \
                     ["- `%s` (%d changes)" % (h["file"], h["changes"]) for h in r["hotspots"]] + [""]
    return "\n".join(lines).rstrip() + "\n"
