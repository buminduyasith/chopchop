"""Where the review comments of a feature (or of one loose PR) live, and how to find the right one.

  <feature>/work/comments/              prs.json  threads.json  triage.json  pack.md  replies.md  fix/
  <feature>/comments.md                 the report people read
  _chopchop/prs/<owner>-<repo>-<n>/     the same, for a PR that belongs to no feature
"""

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from chopchoplib import features
from chopchoplib import tasks as tasklib

PRS, THREADS, TRIAGE = "prs.json", "threads.json", "triage.json"
PACK, TRIAGE_IN, REPLIES, REPORT = "pack.md", "triage-in.json", "replies.md", "comments.md"
FIX_DIR, PLAN = "fix", "plan.json"
LOOSE_DIR = "prs"
PR_STATES = ["open", "merged", "closed"]
REVIEWS = ["approved", "changes-requested", "commented", "none"]
KINDS = ["inline", "review", "general"]
PR_KEYS = ["id", "repo", "host", "slug", "number", "url", "title", "state", "draft", "head", "base", "author",
           "review", "fetched", "threads"]


class UsageError(Exception):
    """The call cannot be done as asked: exit 2."""


def now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def local_time(text):
    """A host time (2026-11-14T09:00:00Z) as local time with no zone, like every other time chopchop writes."""
    if not text:
        return None
    s = str(text).strip()
    try:
        d = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s)
    except ValueError:
        return s
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def norm_text(text):
    return str(text or "").replace("\r\n", "\n").strip()


def thread_hash(body, replies):
    """sha1 of the comment and its replies, in order. A new reply or an edit changes it."""
    parts = [norm_text(body)] + [norm_text((r or {}).get("body")) for r in replies or []]
    return hashlib.sha1("\n\x1e".join(parts).encode("utf-8")).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def git_raw(path, *args):
    """(code, stdout as it is, stderr). gitops.git strips the output, which shifts line numbers."""
    try:
        out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True, timeout=120,
                             errors="replace")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return out.returncode, out.stdout or "", (out.stderr or "").strip()


def current_branch(path):
    code, out, _ = git_raw(path, "branch", "--show-current")
    return out.strip() if code == 0 and out.strip() else None


# --------------------------------------------------------------------------- PR links


def parse_pr_url(url):
    """{"host", "server", "slug", "name", "number", "url"} from a pull request link. Raises UsageError."""
    raw = str(url or "").strip()
    u = urlparse(raw)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise UsageError("'%s' is not a pull request link. It must start with https://." % raw)
    server, path = u.netloc.lower(), u.path
    found = None
    for host, pattern in (
            ("azure", r"^/(?:(?P<org>[^/]+)/)?(?P<project>[^/]+)/_git/(?P<repo>[^/]+)/pullrequest/(?P<n>\d+)"),
            ("gitlab", r"^/(?P<slug>.+?)/-/merge_requests/(?P<n>\d+)"),
            ("bitbucket", r"^/projects/(?P<org>[^/]+)/repos/(?P<repo>[^/]+)/pull-requests/(?P<n>\d+)"),
            ("bitbucket", r"^/(?P<org>[^/]+)/(?P<repo>[^/]+)/pull-requests/(?P<n>\d+)"),
            ("github", r"^/(?P<org>[^/]+)/(?P<repo>[^/]+)/pull/(?P<n>\d+)")):
        m = re.match(pattern, path)
        if m:
            found = (host, m)
            break
    if not found:
        raise UsageError("'%s' does not look like a pull request link (for example "
                         "https://github.com/owner/repo/pull/12)." % raw)
    host, m = found
    g = m.groupdict()
    if g.get("slug"):
        slug = g["slug"]
    elif host == "azure":
        slug = "/".join(p for p in (g.get("org"), g["project"], g["repo"]) if p)
    else:
        slug = "%s/%s" % (g["org"], g["repo"])
    clean = "%s://%s%s" % (u.scheme, u.netloc, m.group(0))
    return {"host": host, "server": server, "slug": slug, "name": slug.rsplit("/", 1)[-1], "number": int(g["n"]),
            "url": clean}


def url_key(url):
    """One value for every spelling of the same PR link, or None when it is not a PR link."""
    try:
        p = parse_pr_url(url)
    except UsageError:
        return None
    return "%s/%s#%d" % (p["server"], p["slug"].lower(), p["number"])


def loose_slug(parsed):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", "%s-%d" % (parsed["slug"], parsed["number"])).strip("-")


def new_pr(parsed, repo):
    """A prs.json entry for a PR nobody has read yet."""
    return {"id": "%s#%d" % (repo, parsed["number"]), "repo": repo, "host": parsed["host"], "slug": parsed["slug"],
            "number": parsed["number"], "url": parsed["url"], "title": None, "state": "open", "draft": False,
            "head": None, "base": None, "author": None, "review": "none", "fetched": None, "threads": 0}


# --------------------------------------------------------------------------- the store


class Store:
    """The comment files of one feature, or of one loose PR."""

    def __init__(self, ws, root, feature=None):
        self.ws, self.root, self.feature = Path(ws), Path(root), feature
        self.dir = self.root / "work" / "comments"
        self.report = self.root / REPORT
        self.reload()

    def reload(self):
        prs = read_json(self.dir / PRS)
        self.prs = prs if isinstance(prs, dict) else {}
        if not isinstance(self.prs.get("prs"), list):
            self.prs["prs"] = []
        if not isinstance(self.prs.get("watch"), dict):
            self.prs["watch"] = {"on": False, "since": None, "last": None}
        threads = read_json(self.dir / THREADS)
        self.threads = threads if isinstance(threads, dict) and isinstance(threads.get("threads"), list) else \
            {"fetched": None, "threads": []}
        triage = read_json(self.dir / TRIAGE)
        self.triage = triage if isinstance(triage, dict) else {}
        if not isinstance(self.triage.get("items"), dict):
            self.triage["items"] = {}
        if not isinstance(self.triage.get("groups"), list):
            self.triage["groups"] = []
        self.triage.setdefault("updated", None)

    @property
    def name(self):
        return self.feature.name if self.feature else "%s/%s" % (LOOSE_DIR, self.root.name)

    @property
    def ref(self):
        """What to pass as REF to reach this store again."""
        return str(self.feature.number) if self.feature else self.root.name

    @property
    def title(self):
        if self.feature:
            for doc in ("requirements/brief.md", "design/design.md", "spec/spec.md"):
                title = features.read_front_matter(self.root / doc).get("title")
                if title:
                    return str(title)
            return str(self.feature.meta.get("title") or self.feature.slug.replace("-", " "))
        first = self.prs["prs"][0] if self.prs["prs"] else {}
        return str(first.get("title") or first.get("id") or self.root.name)

    @property
    def items(self):
        return self.triage["items"]

    def pr(self, pr_id):
        return next((p for p in self.prs["prs"] if p.get("id") == pr_id), None)

    def by_id(self):
        return {t["id"]: t for t in self.threads["threads"]}

    def auto(self):
        data = read_json(self.root / "work" / "auto.json")
        return data if isinstance(data, dict) else {}

    def save_prs(self):
        write_json(self.dir / PRS, self.prs)

    def save_threads(self):
        write_json(self.dir / THREADS, self.threads)

    def save_triage(self):
        self.triage["updated"] = now()
        write_json(self.dir / TRIAGE, {"updated": self.triage["updated"], "items": self.triage["items"],
                                       "groups": self.triage["groups"]})

    # ----- what is new

    def is_new(self, thread):
        """Not settled, and never explained or changed since it was explained."""
        if thread.get("resolved"):
            return False
        item = self.items.get(thread["id"])
        return item is None or item.get("hash") != thread.get("hash")

    def new_threads(self):
        return [t for t in self.threads["threads"] if self.is_new(t)]

    def current(self, thread):
        """The triage item of a thread, when it still matches what the thread says now."""
        item = self.items.get(thread["id"])
        return item if item and item.get("hash") == thread.get("hash") else None


# --------------------------------------------------------------------------- a feature's PRs and branches


def feature_prs(feature):
    """PRs chopchop already knows for a feature: from work/auto.json and from the task files."""
    out, seen = [], set()

    def add(url, repo, source):
        key = url_key(url)
        if key and key not in seen:
            seen.add(key)
            out.append({"url": str(url).strip(), "repo": repo, "source": source})

    auto = read_json(feature.path / "work" / "auto.json")
    if isinstance(auto, dict) and isinstance(auto.get("repos"), dict):
        for name, r in auto["repos"].items():
            if isinstance(r, dict) and r.get("pr"):
                add(r["pr"], name, "auto")
    for t in tasklib.load_tasks(feature.path / tasklib.TASKS_DIR):
        if t.get("pr"):
            add(t.get("pr"), str(t.get("repo") or ""), t.id)
    return out


def stored_prs(root):
    data = read_json(Path(root) / "work" / "comments" / PRS)
    return [p for p in (data or {}).get("prs") or [] if isinstance(p, dict)] if isinstance(data, dict) else []


def feature_branches(feature):
    """The feature branch and the build branches of a feature, plus the head branches of its PRs."""
    names = set()
    auto = read_json(feature.path / "work" / "auto.json")
    if isinstance(auto, dict):
        names.add(auto.get("feature_branch"))
        for r in (auto.get("repos") or {}).values():
            if isinstance(r, dict):
                names.add(r.get("build_branch"))
    names.add(features.read_front_matter(feature.path / tasklib.TASKS_DIR / tasklib.PLAN_FILE).get("feature_branch"))
    names |= {p.get("head") for p in stored_prs(feature.path)}
    return {n for n in names if n}


def loose_stores(ws):
    folder = Path(ws) / LOOSE_DIR
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if (p / "work" / "comments" / PRS).is_file())


def knows_url(root, feature, key):
    urls = [p.get("url") for p in stored_prs(root)]
    if feature is not None:
        urls += [p["url"] for p in feature_prs(feature)]
    return any(url_key(u) == key for u in urls)


def find_store(ws, ref=None, cwd=None, create=False):
    """The store for a ref, or the one the user most likely means.

    An explicit ref wins: a feature (number, key, name), a PR link, or a loose PR folder name.
    With no ref: the feature whose branch is checked out here, else the only one that has PRs.
    """
    ws = Path(ws)
    all_features = features.all_features(ws)
    ref = (ref or "").strip()
    if "://" in ref:
        parsed = parse_pr_url(ref)
        key = url_key(ref)
        for f in all_features:
            if knows_url(f.path, f, key):
                return Store(ws, f.path, f)
        root = ws / LOOSE_DIR / loose_slug(parsed)
        if not create and not (root / "work" / "comments" / PRS).is_file():
            raise UsageError("No comments are stored for %s yet. Add it first: --pr %s" % (parsed["url"], parsed["url"]))
        return Store(ws, root)
    if ref:
        if (ws / LOOSE_DIR / ref / "work" / "comments" / PRS).is_file():
            return Store(ws, ws / LOOSE_DIR / ref)
        if not all_features:
            raise UsageError("No feature or stored PR matches '%s' in %s." % (ref, ws))
        f = features.resolve(ws, ref)
        return Store(ws, f.path, f)

    branch = current_branch(cwd or Path.cwd())
    if branch:
        hits = [Store(ws, f.path, f) for f in all_features if branch in feature_branches(f)]
        hits += [Store(ws, p) for p in loose_stores(ws) if branch in {x.get("head") for x in stored_prs(p)}]
        if len(hits) == 1:
            return hits[0]
    with_prs = [Store(ws, f.path, f) for f in all_features if feature_prs(f) or stored_prs(f.path)]
    with_prs += [Store(ws, p) for p in loose_stores(ws)]
    if len(with_prs) == 1:
        return with_prs[0]
    if not with_prs:
        raise UsageError("No feature has a PR yet. Open the PRs with /chopchop:auto, or add one: --pr <link>.")
    rows = ["  %-28s %d PR(s)" % (s.ref if not s.feature else "%03d %s" % (s.feature.number, s.feature.name),
                                  len(s.prs["prs"]) or len(feature_prs(s.feature) if s.feature else []))
            for s in with_prs]
    raise UsageError("More than one feature or PR is here. Say which one (a number, a name or a PR link):\n%s"
                     % "\n".join(rows))


def sync_prs(store, repo_names=()):
    """Add the PRs a feature already knows (auto.json, task files) to prs.json. Returns the ids added."""
    if store.feature is None:
        return []
    have = {url_key(p.get("url")) for p in store.prs["prs"]}
    added = []
    for found in feature_prs(store.feature):
        key = url_key(found["url"])
        if key in have:
            continue
        parsed = parse_pr_url(found["url"])
        entry = new_pr(parsed, found["repo"] or pick_repo_name(parsed, repo_names))
        if store.pr(entry["id"]):
            continue
        store.prs["prs"].append(entry)
        have.add(key)
        added.append(entry["id"])
    return added


def pick_repo_name(parsed, repo_names=()):
    """The chopchop name of a PR's repo: the name from chopchop.yaml when one matches, else the repo's own name."""
    low = parsed["name"].lower()
    return next((n for n in repo_names if n.lower() == low), parsed["name"])
