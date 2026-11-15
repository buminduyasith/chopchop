"""Read and answer GitHub pull requests through the gh command.

Reading uses the GraphQL API (review threads know if they are resolved or outdated). Posting a
reply uses two REST paths. chopchop never sees a token: gh keeps the login.
"""

import json
import re
import shutil
import subprocess

from .store import local_time, thread_hash

TIMEOUT = 90
HUNK_KEEP = 12  # lines of a diff hunk kept, counted from the commented line upwards
SECRET = re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,})")

# General PR comments from these bots are status reports, not review comments. They change on every
# push, so they are left out. So is any general bot comment that starts with a hidden <!-- marker -->:
# that is how a bot finds its own report to rewrite it. Comments a bot leaves on a line are always kept.
NOISE_BOTS = {"codecov", "codecov-commenter", "codecov-io", "vercel", "netlify", "dependabot", "renovate",
              "sonarcloud", "sonarqubecloud", "changeset-bot", "cla-assistant", "claassistant", "linux-foundation-easycla",
              "github-actions", "coveralls", "netlify-bot", "k8s-ci-robot", "googlebot", "google-cla", "allcontributors",
              "pkg-pr-new", "socket-security", "cloudflare-workers-and-pages", "codspeed-hq", "graphite-app", "stale"}

COMMENT = "databaseId author { login __typename } body createdAt updatedAt url"
PAGE = "pageInfo { hasNextPage endCursor }"
Q_THREADS = """query Threads($owner: String!, $name: String!, $number: Int!, $after: String) {
  viewer { login }
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    title url state isDraft reviewDecision headRefName baseRefName author { login __typename }
    reviewThreads(first: 100, after: $after) { %s nodes {
      id isResolved isOutdated path line originalLine
      comments(first: 100) { %s nodes { %s diffHunk } } } } } } }""" % (PAGE, PAGE, COMMENT)
Q_THREAD_COMMENTS = """query ThreadComments($id: ID!, $after: String) {
  node(id: $id) { ... on PullRequestReviewThread {
    comments(first: 100, after: $after) { %s nodes { %s diffHunk } } } } }""" % (PAGE, COMMENT)
Q_REVIEWS = """query Reviews($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    reviews(first: 100, after: $after) { %s nodes {
      databaseId author { login __typename } body state submittedAt createdAt updatedAt url isMinimized } } } } }""" % PAGE
Q_COMMENTS = """query Comments($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    comments(first: 100, after: $after) { %s nodes { %s isMinimized } } } } }""" % (PAGE, COMMENT)


class GhError(Exception):
    """gh could not do it: exit 1, and nothing stored is touched."""


def scrub(text):
    return SECRET.sub("[hidden]", str(text or ""))


def server_of(pr):
    m = re.match(r"^https?://([^/]+)/", str(pr.get("url") or ""))
    return m.group(1).lower() if m else "github.com"


def ready(server="github.com"):
    """None when gh can be used for this server, else one plain line that says why not."""
    if not shutil.which("gh"):
        return "The gh command is not installed"
    try:
        out = subprocess.run(["gh", "auth", "status", "--hostname", server], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "The gh command does not answer"
    return None if out.returncode == 0 else "gh is not logged in to %s" % server


def run(args):
    try:
        out = subprocess.run(["gh"] + list(args), capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise GhError("gh did not answer in %d seconds." % TIMEOUT)
    except OSError as e:
        raise GhError("gh could not start: %s" % e)
    if out.returncode != 0:
        lines = [l for l in scrub(out.stderr or out.stdout).strip().splitlines() if l.strip()]
        raise GhError("gh failed: %s" % (lines[-1] if lines else "exit %d" % out.returncode))
    return out.stdout


def graphql(server, query, variables, after=None):
    cmd = ["api", "graphql"] + ([] if server == "github.com" else ["--hostname", server]) + ["-f", "query=" + query]
    for key, value in variables.items():
        cmd += ["-F" if isinstance(value, int) else "-f", "%s=%s" % (key, value)]
    if after:
        cmd += ["-f", "after=" + after]
    try:
        data = json.loads(run(cmd))
    except ValueError:
        raise GhError("gh answered with something that is not JSON.")
    if isinstance(data, dict) and data.get("errors"):
        raise GhError("gh failed: %s" % scrub((data["errors"][0] or {}).get("message") or "GraphQL error"))
    return (data or {}).get("data") or {}


def _pull(data):
    return ((data.get("repository") or {}).get("pullRequest")) if isinstance(data, dict) else None


def _paged(server, query, variables, field):
    nodes, after = [], None
    while True:
        pull = _pull(graphql(server, query, variables, after))
        conn = (pull or {}).get(field) or {}
        nodes += [n for n in conn.get("nodes") or [] if n]
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage") or not info.get("endCursor"):
            return nodes
        after = info["endCursor"]


def fetch(pr):
    """Everything gh says about one PR, as it comes: {"me", "pull", "threads", "reviews", "comments"}."""
    server = server_of(pr)
    owner, _, name = str(pr["slug"]).partition("/")
    variables = {"owner": owner, "name": name, "number": int(pr["number"])}
    me, meta, threads, after = None, None, [], None
    while True:
        data = graphql(server, Q_THREADS, variables, after)
        pull = _pull(data)
        if not pull:
            raise GhError("gh cannot see %s. Check the link, and that your login may read it." % pr["url"])
        me = me or (data.get("viewer") or {}).get("login")
        meta = meta or {k: v for k, v in pull.items() if k != "reviewThreads"}
        conn = pull.get("reviewThreads") or {}
        threads += [n for n in conn.get("nodes") or [] if n]
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage") or not info.get("endCursor"):
            break
        after = info["endCursor"]
    for node in threads:  # a thread with more than 100 messages
        comments = node.get("comments") or {}
        info = comments.get("pageInfo") or {}
        while info.get("hasNextPage") and info.get("endCursor"):
            more = ((graphql(server, Q_THREAD_COMMENTS, {"id": node["id"]}, info["endCursor"]).get("node") or {})
                    .get("comments") or {})
            comments.setdefault("nodes", []).extend(n for n in more.get("nodes") or [] if n)
            info = more.get("pageInfo") or {}
    return {"me": me, "pull": meta, "threads": threads,
            "reviews": _paged(server, Q_REVIEWS, variables, "reviews"),
            "comments": _paged(server, Q_COMMENTS, variables, "comments")}


# --------------------------------------------------------------------------- normalise


def login(author):
    return str((author or {}).get("login") or "ghost")


def is_bot(author):
    author = author or {}
    return author.get("__typename") == "Bot" or str(author.get("login") or "").endswith("[bot]")


def trim_hunk(hunk, keep=HUNK_KEEP):
    """The @@ line and the last lines of a diff hunk: the commented line is always the last one."""
    lines = str(hunk or "").split("\n")
    if len(lines) <= keep + 1:
        return hunk or None
    return "\n".join([lines[0]] + lines[-keep:])


def review_state(pull, reviews):
    decision = str(pull.get("reviewDecision") or "")
    if decision == "APPROVED":
        return "approved"
    if decision == "CHANGES_REQUESTED":
        return "changes-requested"
    last = {}
    for r in reviews:  # the last firm review of each person counts
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            last[login(r.get("author"))] = r["state"]
    if "CHANGES_REQUESTED" in last.values():
        return "changes-requested"
    if "APPROVED" in last.values() and decision != "REVIEW_REQUIRED":
        return "approved"
    return "commented" if reviews else "none"


def normalise(pr, raw, ignore=(), keep=()):
    """(PR fields, threads, counts of what was left out) in the shape of prs.json and threads.json."""
    pull, pid = raw["pull"], pr["id"]
    author = login(pull.get("author"))
    state = str(pull.get("state") or "OPEN").lower()
    fields = {"title": pull.get("title"), "state": state if state in ("open", "merged", "closed") else "open",
              "draft": bool(pull.get("isDraft")), "head": pull.get("headRefName"), "base": pull.get("baseRefName"),
              "author": author, "review": review_state(pull, raw["reviews"])}
    threads = []

    def thread(tid, kind, first, replies=(), **extra):
        t = {"id": "%s:%s" % (pid, tid), "pr": pid, "repo": pr["repo"], "kind": kind, "file": None, "line": None,
             "hunk": None, "author": login(first.get("author")), "bot": is_bot(first.get("author")),
             "created": local_time(first.get("submittedAt") or first.get("createdAt")),
             "updated": local_time(first.get("updatedAt") or first.get("submittedAt") or first.get("createdAt")),
             "resolved": False, "outdated": False, "url": first.get("url"), "body": first.get("body") or "",
             "replies": [{"author": login(c.get("author")), "body": c.get("body") or "",
                          "created": local_time(c.get("createdAt"))} for c in replies]}
        t.update(extra)
        stamps = [t["updated"]] + [local_time(c.get("updatedAt") or c.get("createdAt")) for c in replies]
        t["updated"] = max(s for s in stamps if s) if any(stamps) else None
        threads.append(t)

    for node in raw["threads"]:
        comments = [c for c in (node.get("comments") or {}).get("nodes") or [] if c]
        if comments:
            thread("r%s" % comments[0].get("databaseId"), "inline", comments[0], comments[1:], file=node.get("path"),
                   line=node.get("line") or node.get("originalLine"), hunk=trim_hunk(comments[0].get("diffHunk")),
                   resolved=bool(node.get("isResolved")), outdated=bool(node.get("isOutdated")))
    for r in raw["reviews"]:
        if str(r.get("body") or "").strip() and r.get("state") != "PENDING" and not r.get("isMinimized"):
            thread("v%s" % r.get("databaseId"), "review", r, resolved=r.get("state") == "DISMISSED")
    for c in raw["comments"]:
        if str(c.get("body") or "").strip() and not c.get("isMinimized"):
            thread("c%s" % c.get("databaseId"), "general", c)
    kept, left = leave_out(threads, {raw.get("me"), author}, state, ignore, keep)
    return fields, kept, left


def leave_out(threads, ours, pr_state="open", ignore=(), keep=()):
    """Drop what is not a review comment, settle the threads of a finished PR, and add the hash.

    Left out: a thread where only the PR's author (or you) wrote, and a status report from a CI bot
    (a general comment from a bot in NOISE_BOTS, a general bot comment that starts with a hidden marker,
    or one from a login in comments.ignore of chopchop.yaml; comments.keep wins over all three).
    """
    ours = {str(o).lower() for o in ours if o}
    ignore, keep = {str(x).lower() for x in ignore or ()}, {str(x).lower() for x in keep or ()}
    kept, left = [], {"own": 0, "bots": 0}
    for t in threads:
        voices = {str(t["author"]).lower()} | {str(r.get("author")).lower() for r in t["replies"]}
        if voices <= ours:
            left["own"] += 1
            continue
        who = re.sub(r"\[bot\]$", "", str(t["author"]).lower())
        report = t["bot"] and (who in NOISE_BOTS or str(t["body"]).lstrip().startswith("<!--"))
        if t["kind"] == "general" and who not in keep and (who in ignore or report):
            left["bots"] += 1
            continue
        if pr_state in ("merged", "closed"):
            t["resolved"] = True
        t["hash"] = thread_hash(t["body"], t["replies"])
        kept.append(t)
    return kept, left


# --------------------------------------------------------------------------- answer


def whoami(server="github.com"):
    try:
        return run(["api"] + ([] if server == "github.com" else ["--hostname", server]) + ["user", "--jq", ".login"]).strip() or None
    except GhError:
        return None


def post_reply(pr, thread, body):
    """Post one reply. A review thread gets a reply in the thread, anything else a PR comment. Returns its link."""
    server = server_of(pr)
    if thread["kind"] == "inline":
        m = re.search(r":r(\d+)$", thread["id"])
        if not m:
            raise GhError("%s has no GitHub comment number, so gh cannot reply in its thread." % thread["id"])
        path = "repos/%s/pulls/%d/comments/%s/replies" % (pr["slug"], int(pr["number"]), m.group(1))
    else:
        path = "repos/%s/issues/%d/comments" % (pr["slug"], int(pr["number"]))
    cmd = ["api"] + ([] if server == "github.com" else ["--hostname", server])
    return run(cmd + [path, "--method", "POST", "-f", "body=" + body, "--jq", ".html_url"]).strip()
