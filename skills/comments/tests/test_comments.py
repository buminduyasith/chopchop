"""The comments helper end to end: a fake gh on PATH, two local repos with bare remotes, no network."""

import contextlib
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import chopchop_comments as cc  # noqa: E402  (puts the tasks scripts on the path)
from commentslib import report, schema, similar, store as storelib, triage  # noqa: E402
from chopchoplib import events, features, plain, stage  # noqa: E402

APP_URL = "https://github.com/acme/app/pull/12"
WEB_URL = "https://github.com/acme/web/pull/7"
HEAD, BASE = "feature/IDEA-1/build", "feature/IDEA-1-refunds"
LONG_DASH = "\u2014"

FAKE_GH = r'''#!%s
import json, os, re, sys
home = os.environ["FAKE_GH"]
argv = sys.argv[1:]
with open(os.path.join(home, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps(argv) + "\n")
fields = {}
for i, a in enumerate(argv):
    if a in ("-f", "-F") and i + 1 < len(argv):
        k, _, v = argv[i + 1].partition("=")
        fields[k] = v
if argv[:2] == ["auth", "status"]:
    sys.exit(0 if os.path.exists(os.path.join(home, "logged_in")) else 1)
if os.path.exists(os.path.join(home, "fail")):
    sys.stderr.write("HTTP 502: Bad Gateway (https://api.github.com/graphql)\n")
    sys.exit(1)
if argv[:2] == ["api", "graphql"]:
    op = re.search(r"query (\w+)", fields["query"]).group(1)
    data = json.load(open(os.path.join(home, "responses.json")))
    key = "%%s/%%s#%%s %%s %%s" %% (fields.get("owner"), fields.get("name"), fields.get("number"), op, fields.get("after", ""))
    if op == "ThreadComments":
        key = "%%s %%s %%s" %% (fields.get("id"), op, fields.get("after", ""))
    if key not in data:
        sys.stderr.write("gh: Could not resolve to a PullRequest with the number of %%s.\n" %% fields.get("number"))
        sys.exit(1)
    print(json.dumps(data[key]))
    sys.exit(0)
if argv[:1] == ["api"] and "user" in argv:
    print("bumindu")
    sys.exit(0)
if argv[:1] == ["api"]:
    print("https://github.com/posted/%%s" %% argv[1])
    sys.exit(0)
sys.exit(1)
'''


def git(path, *args):
    out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), out.stderr))
    return out.stdout.strip()


def who(login, bot=False):
    return {"login": login, "__typename": "Bot" if bot else "User"}


def comment(n, login, body, at="2026-11-14T09:00:00Z", bot=False, hunk=None, slug="acme/app", number=12):
    return {"databaseId": n, "author": who(login, bot), "body": body, "createdAt": at, "updatedAt": at,
            "url": "https://github.com/%s/pull/%d#discussion_r%d" % (slug, number, n),
            "diffHunk": hunk or "@@ -1,6 +1,9 @@ def refund(amount):\n     total = amount\n+    if amount >= 0:"}


def node(comments, path, line, resolved=False, outdated=False, more=None):
    return {"id": "NODE%d" % comments[0]["databaseId"], "isResolved": resolved, "isOutdated": outdated, "path": path,
            "line": None if outdated else line, "originalLine": line,
            "comments": {"pageInfo": {"hasNextPage": bool(more), "endCursor": more}, "nodes": comments}}


def review_node(n, login, body, state="COMMENTED", bot=False):
    return {"databaseId": n, "author": who(login, bot), "body": body, "state": state, "isMinimized": False,
            "submittedAt": "2026-11-14T09:10:00Z", "createdAt": "2026-11-14T09:10:00Z", "updatedAt": "2026-11-14T09:10:00Z",
            "url": "https://github.com/acme/app/pull/12#pullrequestreview-%d" % n}


def general(n, login, body, bot=False, minimized=False):
    return {"databaseId": n, "author": who(login, bot), "body": body, "isMinimized": minimized,
            "createdAt": "2026-11-14T09:20:00Z", "updatedAt": "2026-11-14T09:20:00Z",
            "url": "https://github.com/acme/app/pull/12#issuecomment-%d" % n}


class FakeGh:
    """Lays out the GraphQL pages the fake gh answers with, and reads back what it was asked."""

    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir()
        (self.home / "logged_in").write_text("")
        self.data = {}

    def pr(self, slug, number, threads=(), reviews=(), comments=(), page=100, state="OPEN", me="bumindu",
           author="bumindu", decision=None, draft=False, title="Refund requests"):
        key = "%s#%d" % (slug, number)
        nodes = list(threads)
        pages = [nodes[i:i + page] for i in range(0, len(nodes), page)] or [[]]
        for i, chunk in enumerate(pages):
            nxt = "cur%d" % (i + 1) if i + 1 < len(pages) else None
            self.data["%s Threads %s" % (key, "" if i == 0 else "cur%d" % i)] = {"data": {
                "viewer": {"login": me},
                "repository": {"pullRequest": {
                    "title": title, "url": "https://github.com/%s/pull/%d" % (slug, number), "state": state,
                    "isDraft": draft, "reviewDecision": decision, "headRefName": HEAD, "baseRefName": BASE,
                    "author": who(author),
                    "reviewThreads": {"pageInfo": {"hasNextPage": bool(nxt), "endCursor": nxt}, "nodes": chunk}}}}}
        for name, items in (("Reviews", "reviews"), ("Comments", "comments")):
            self.data["%s %s " % (key, name)] = {"data": {"repository": {"pullRequest": {
                items: {"pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": list(reviews if name == "Reviews" else comments)}}}}}
        self.save()

    def save(self):
        (self.home / "responses.json").write_text(json.dumps(self.data))

    def calls(self):
        f = self.home / "calls.jsonl"
        return [json.loads(l) for l in f.read_text().splitlines()] if f.is_file() else []

    def posts(self):
        return [c for c in self.calls() if c[:1] == ["api"] and "POST" in c]


def task_text(tid, slug, repo, touches, status="in-review", pr=None):
    meta = {"id": tid, "title": slug.replace("-", " ").title(), "repo": repo, "wave": 1, "size": "S", "status": status,
            "owner": None, "depends_on": [], "touches": list(touches), "stories": [], "pr": pr}
    return features.render_front_matter(meta) + (
        "# %s\n\n## Goal\n\nIt works.\n\n## Done when\n\n- [ ] Unit test `does_the_thing`: it works.\n\n"
        "## Branch\n\n_Written by chopchop._\n" % tid)


REFUND_PY = "\n".join(["def refund(amount):", "    total = amount", "    # check the amount", "    limit = 100",
                       "    if amount >= 0:", "        total = min(amount, limit)", "    else:", "        total = 0",
                       "    fee = total / 10", "    return total - fee", "", "def cancel(order):", "    return order"]) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.ws = self.root / "_chopchop"
        self.ws.mkdir()
        self.repos = {"app": self.make_repo("app", {"src/refund.py": REFUND_PY}),
                      "web": self.make_repo("web", {"src/ui/form.js": "const amount = input.value\nsend(amount)\n"})}
        (self.ws / "chopchop.yaml").write_text("team: t\nbase_branch: dev\nrepos:\n" + "".join(
            "  %s:\n    path: %s\n" % (n, p) for n, p in self.repos.items()))
        self.fpath = self.make_feature("001-IDEA-1-refunds", "IDEA-1", APP_URL)
        (self.ws / "repos").mkdir()
        (self.ws / "repos" / "app.md").write_text(features.render_front_matter(
            {"repo": "app", "confirmed": True, "lint": "ruff check .", "test": "python3 -m unittest"}) + "# app\n")
        self.dir = self.fpath / "work" / "comments"

        self.gh = FakeGh(self.root / "gh")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        exe = bin_dir / "gh"
        exe.write_text(FAKE_GH % sys.executable)
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        self.env = {k: os.environ.get(k) for k in ("PATH", "FAKE_GH", "CHOPCHOP_HOME")}
        os.environ["PATH"] = "%s%s%s" % (bin_dir, os.pathsep, os.environ.get("PATH", ""))
        os.environ["FAKE_GH"] = str(self.gh.home)
        os.environ.pop("CHOPCHOP_HOME", None)
        self.cwd = os.getcwd()
        os.chdir(str(self.root))
        self.app()
        self.web()

    def tearDown(self):
        os.chdir(self.cwd)
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def make_repo(self, name, files):
        remote, repo = self.root / ("%s.git" % name), self.root / name
        git(self.root, "init", "--bare", "-q", str(remote))
        repo.mkdir()
        git(repo, "init", "-q", "-b", "dev")
        git(repo, "config", "user.name", "dev-a")
        git(repo, "config", "user.email", "a@acme.test")
        (repo / "README.md").write_text(name + "\n")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "start")
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "-q", "origin", "dev")
        git(repo, "checkout", "-q", "-b", BASE)
        git(repo, "push", "-q", "-u", "origin", BASE)
        git(repo, "checkout", "-q", "-b", HEAD)
        for rel, text in files.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "build")
        git(repo, "push", "-q", "-u", "origin", HEAD)
        return repo

    def make_feature(self, folder, key, app_pr, build=HEAD):
        f = self.ws / folder
        (f / "tasks").mkdir(parents=True)
        (f / "tasks" / "plan.md").write_text(features.render_front_matter(
            {"feature": folder, "epic": key, "feature_branch": BASE, "base_branch": "dev"}) + "# Plan\n")
        (f / "tasks" / "T01-refund-api.md").write_text(task_text("T01", "refund-api", "app", ["src/**"]))
        (f / "tasks" / "T02-refund-form.md").write_text(task_text("T02", "refund-form", "web", ["src/ui/**"], pr=WEB_URL))
        (f / "tasks" / "T03-refund-job.md").write_text(task_text("T03", "refund-job", "app", ["jobs/**"], status="todo"))
        (f / "work").mkdir()
        (f / "work" / "auto.json").write_text(json.dumps({
            "feature": folder, "feature_branch": BASE, "queue": ["T01", "T02", "T03"],
            "repos": {"app": {"path": str(self.repos["app"]), "build_branch": build, "pr": app_pr},
                      "web": {"path": str(self.repos["web"]), "build_branch": build, "pr": None}},
            "tasks": {"T01": {"repo": "app", "state": "committed"}, "T02": {"repo": "web", "state": "committed"},
                      "T03": {"repo": "app", "state": "stopped"}}}))
        (f / "spec").mkdir()
        (f / "spec" / "spec.json").write_text(json.dumps({"rules": [
            {"id": "R-1", "text": "A customer sees the order page.", "met": "The page loads."},
            {"id": "R-2", "text": "A refund amount must be more than zero.", "met": "A refund of 0 is refused."}]}))
        return f

    # ----- what the hosts say

    def app_threads(self, extra_reply=None):
        first = [comment(2001, "asha", "This lets a refund of 0 through. The amount check must refuse zero.")]
        if extra_reply:
            first.append(comment(2091, extra_reply[0], extra_reply[1], at="2026-11-14T11:00:00Z"))
        return [node(first, "src/refund.py", 5),
                node([comment(2002, "lee", "A negative amount is not handled here. The amount check looks wrong.")],
                     "src/refund.py", 9),
                node([comment(2003, "asha", "Typo in the name.")], "src/util.py", 3, resolved=True)]

    def app(self, threads=None, **meta):
        self.gh.pr("acme/app", 12, threads if threads is not None else self.app_threads(),
                   meta.pop("reviews", [review_node(900, "asha", "Please tighten the amount checks before merge.",
                                                    "CHANGES_REQUESTED")]),
                   meta.pop("comments", [general(700, "asha", "Can you add a changelog line for refunds?")]), **meta)

    def web(self, **meta):
        self.gh.pr("acme/web", 7, [node([comment(3110, "asha", "The form also lets a refund amount of 0 through. "
                                                                "Same zero check.", slug="acme/web", number=7)],
                                        "src/ui/form.js", 2)], **meta)

    # ----- running

    def run_cc(self, *argv, code=0, ws=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = cc.main(list(argv) + ["--workspace", str(ws or self.ws)])
        text = out.getvalue() + err.getvalue()
        self.assertTrue(code is None or got == code, "exit %s, wanted %s:\n%s" % (got, code, text))
        return text

    def load(self, name):
        return json.loads((self.dir / name).read_text())

    def threads(self):
        return {t["id"]: t for t in self.load("threads.json")["threads"]}

    def items(self):
        return self.load("triage.json")["items"]

    def item(self, verdict="real", group="G1", priority="high", **extra):
        base = {"plain": "A refund of 0 passes the check.", "verdict": verdict, "priority": priority, "group": group,
                "why": "Line 5 compares with >= 0, and rule R-2 says more than zero.",
                "evidence": ["app/src/refund.py:5"], "fix": "Compare with > 0 and add a test.",
                "impact": "Only this check.", "reply": "Good catch. Fixed in the next commit, with a test."}
        base.update(extra)
        return base

    def group(self, gid, threads, verdict="real", priority="high", **extra):
        base = {"id": gid, "title": "Zero and negative amounts pass", "plain": "The amount check is too loose.",
                "threads": threads, "verdict": verdict, "priority": priority,
                "fix": "Tighten the check in the service and mirror it in the form.", "impact": "Service and form."}
        base.update(extra)
        return base

    def default_triage(self):
        """Every open comment explained: G1 across two repos, G2 on the same file as G1, G3 and G4 on their own."""
        return {"items": {
            "app#12:r2001": self.item(),
            "web#7:r3110": self.item(evidence=["web/src/ui/form.js:2"], plain="The form lets 0 through too."),
            "app#12:r2002": self.item("false-positive", "G2", "medium", plain="They say negative amounts pass.",
                                      why="Line 7 sets the total to 0 for a negative amount.",
                                      evidence=["app/src/refund.py:7"], fix=None, impact=None,
                                      reply="Thanks for checking. Line 7 already sets a negative amount to 0."),
            "app#12:v900": self.item("question", "G3", "low", plain="They ask for tighter checks.", evidence=[],
                                     fix=None, impact=None, reply="Done in G1. Is anything else open?"),
            "app#12:c700": self.item("negotiable", "G4", "low", plain="They ask for a changelog line.", evidence=[],
                                     fix="Add a line to CHANGELOG.md.", impact="Docs only.",
                                     reply="Fair point. The changelog is written at release time, so I will add a task for it.")},
            "groups": [self.group("G1", ["app#12:r2001", "web#7:r3110"]),
                       self.group("G2", ["app#12:r2002"], "false-positive", "medium", title="Negative amounts",
                                  fix=None, impact=None),
                       self.group("G3", ["app#12:v900"], "question", "low", title="Tighter checks", fix=None, impact=None),
                       self.group("G4", ["app#12:c700"], "negotiable", "low", title="Changelog line",
                                  fix="Add a changelog line.", impact="Docs only.", files=["app/CHANGELOG.md"])]}

    def triage_with(self, data, code=0):
        self.dir.mkdir(parents=True, exist_ok=True)
        f = self.dir / "triage-in.json"
        f.write_text(json.dumps(data))
        return self.run_cc("--triage", str(f), code=code)

    def fetched_and_triaged(self):
        self.run_cc("--fetch")
        return self.triage_with(self.default_triage())


class FindTest(Base):
    def test_only_feature_with_prs(self):
        out = self.run_cc("--prs")
        self.assertIn("Feature:  001-IDEA-1-refunds", out)
        self.assertIn("PR:       app#12 · open (not read yet) · %s · new here" % APP_URL, out)
        self.assertIn("PR:       web#7", out)  # from T02's pr: line
        self.assertIn("Next:     --fetch 1", out)
        prs = self.load("prs.json")
        self.assertEqual([(p["id"], p["repo"], p["host"], p["slug"], p["number"]) for p in prs["prs"]],
                         [("app#12", "app", "github", "acme/app", 12), ("web#7", "web", "github", "acme/web", 7)])
        self.assertEqual(prs["watch"], {"on": False, "since": None, "last": None})

    def test_branch_wins_then_it_lists(self):
        other = "https://github.com/acme/app/pull/40"
        self.make_feature("002-IDEA-2-payouts", "IDEA-2", other, build="feature/IDEA-2/build")
        (self.ws / "002-IDEA-2-payouts" / "tasks" / "T02-refund-form.md").write_text(
            task_text("T02", "refund-form", "web", ["src/ui/**"]))
        (self.ws / "002-IDEA-2-payouts" / "tasks" / "plan.md").write_text(features.render_front_matter(
            {"feature": "002-IDEA-2-payouts", "epic": "IDEA-2", "feature_branch": "feature/IDEA-2-payouts"}) + "# Plan\n")
        out = self.run_cc("--prs", code=2)
        self.assertIn("More than one feature or PR is here. Say which one", out)
        self.assertIn("001 001-IDEA-1-refunds", out)
        self.assertIn("002 002-IDEA-2-payouts", out)
        os.chdir(str(self.repos["app"]))  # on feature/IDEA-1/build: the build branch of feature 1
        self.assertIn("Feature:  001-IDEA-1-refunds", self.run_cc("--prs"))
        self.assertIn("Feature:  002-IDEA-2-payouts", self.run_cc("--prs", "2"))  # an explicit ref wins
        self.assertIn("Feature:  002-IDEA-2-payouts", self.run_cc("--prs", other))  # so does a PR link

    def test_a_loose_pr_gets_its_own_store(self):
        ws = self.root / "elsewhere" / "_chopchop"  # no workspace, no chopchop.yaml
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cc.main(["--pr", "https://github.com/Other/Thing/pull/5/files", "--workspace", str(ws)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("Added:    Thing#5 · https://github.com/Other/Thing/pull/5", out.getvalue())
        self.assertIn("Next:     --fetch Other-Thing-5", out.getvalue())
        prs = json.loads((ws / "prs" / "Other-Thing-5" / "work" / "comments" / "prs.json").read_text())
        self.assertEqual(prs["prs"][0]["slug"], "Other/Thing")

    def test_a_known_link_goes_to_its_feature(self):
        out = self.run_cc("--pr", APP_URL + "/files")
        self.assertIn("Known:    app#12", out)
        self.assertFalse((self.ws / "prs").exists())
        self.assertIn("does not look like a pull request link", self.run_cc("--pr", "https://github.com/acme/app/issues/3", code=2))

    def test_link_shapes(self):
        for url, host, slug, n in (
                ("https://gitlab.com/g/sub/r/-/merge_requests/5", "gitlab", "g/sub/r", 5),
                ("https://bitbucket.org/w/r/pull-requests/9", "bitbucket", "w/r", 9),
                ("https://dev.azure.com/org/proj/_git/repo/pullrequest/77", "azure", "org/proj/repo", 77)):
            p = storelib.parse_pr_url(url)
            self.assertEqual((p["host"], p["slug"], p["number"]), (host, slug, n))


class FetchTest(Base):
    def test_fetch_normalises_everything(self):
        threads = self.app_threads() + [
            node([comment(2004, "copilot-pull-request-reviewer", "This loop may be slow.", bot=True)], "src/refund.py", 9,
                 outdated=True),
            node([comment(2005, "bumindu", "Note to self: rename later.")], "src/refund.py", 2)]
        self.app(threads, page=2, decision="CHANGES_REQUESTED", reviews=[
            review_node(900, "asha", "Please tighten the amount checks before merge.", "CHANGES_REQUESTED"),
            review_node(901, "lee", "", "APPROVED"), review_node(902, "kim", "still writing", "PENDING")],
            comments=[general(700, "asha", "Can you add a changelog line for refunds?"),
                      general(701, "codecov", "Coverage 91%", bot=True), general(702, "bumindu", "Pushed a fix."),
                      general(703, "spammer", "hidden", minimized=True),
                      general(704, "acme-ci", "<!-- sticky report -->\n## Memory usage", bot=True)])
        out = self.run_cc("--fetch")
        self.assertIn("PR:       app#12 · open · changes requested · 6 comments (1 settled)", out)
        self.assertIn("Left out: 2 by the author only, 2 bot status report(s)", out)
        self.assertIn("New:      app#12:r2001 · asha · src/refund.py:5 · This lets a refund of 0 through. "
                      "The amount check must refuse zero.", out)
        self.assertIn("New:      app#12:r2004 · copilot-pull-request-reviewer (bot) · src/refund.py:9", out)
        self.assertNotIn("r2003 ·", out)  # resolved: not new
        self.assertIn("Next:     --pack 1, then the triager, then --triage", out)

        pr = self.load("prs.json")["prs"][0]
        self.assertEqual({k: pr[k] for k in ("id", "title", "state", "draft", "head", "base", "author", "review", "threads")},
                         {"id": "app#12", "title": "Refund requests", "state": "open", "draft": False, "head": HEAD,
                          "base": BASE, "author": "bumindu", "review": "changes-requested", "threads": 6})
        self.assertRegex(pr["fetched"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual(list(pr)[:len(storelib.PR_KEYS)], storelib.PR_KEYS)

        t = self.threads()
        self.assertEqual(sorted(t), ["app#12:c700", "app#12:r2001", "app#12:r2002", "app#12:r2003", "app#12:r2004",
                                     "app#12:v900", "web#7:r3110"])
        one = t["app#12:r2001"]
        self.assertEqual(list(one), ["id", "pr", "repo", "kind", "file", "line", "hunk", "author", "bot", "created",
                                     "updated", "resolved", "outdated", "url", "body", "replies", "hash"])
        self.assertEqual((one["pr"], one["repo"], one["kind"], one["file"], one["line"], one["author"], one["bot"]),
                         ("app#12", "app", "inline", "src/refund.py", 5, "asha", False))
        self.assertTrue(one["hunk"].startswith("@@ -1,6 +1,9 @@ def refund(amount):"))
        self.assertRegex(one["created"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual(one["hash"], storelib.thread_hash(one["body"], []))
        self.assertTrue(t["app#12:r2003"]["resolved"])
        self.assertEqual((t["app#12:r2004"]["outdated"], t["app#12:r2004"]["line"], t["app#12:r2004"]["bot"]), (True, 9, True))
        self.assertEqual((t["app#12:v900"]["kind"], t["app#12:v900"]["file"]), ("review", None))
        self.assertEqual(t["app#12:c700"]["kind"], "general")

        asked = [c for c in self.gh.calls() if "number=12" in c and any("query Threads" in a for a in c)]
        self.assertEqual([[a for a in c if a.startswith("after=")] for c in asked], [[], ["after=cur1"], ["after=cur2"]])
        self.assertEqual(stage.comments_view(self.dir)["threads"], 7)
        self.assertIn("comment", [e["kind"] for e in events.read(self.fpath)])

    def test_config_can_keep_or_ignore_an_author(self):
        with open(str(self.ws / "chopchop.yaml"), "a") as fh:
            fh.write("comments:\n  ignore: [chatty]\n  keep: [codecov]\n")
        self.app(comments=[general(701, "codecov", "Coverage 91%", bot=True), general(705, "chatty", "Any news?")])
        self.run_cc("--fetch")
        self.assertIn("app#12:c701", self.threads())
        self.assertNotIn("app#12:c705", self.threads())

    def test_long_thread_is_read_to_the_end(self):
        long = node([comment(2001, "asha", "First.")], "src/refund.py", 5, more="more1")
        self.gh.data["NODE2001 ThreadComments more1"] = {"data": {"node": {"comments": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [comment(2050, "lee", "And one more thing.")]}}}}
        self.app([long])
        self.run_cc("--fetch")
        self.assertEqual([r["author"] for r in self.threads()["app#12:r2001"]["replies"]], ["lee"])

    def test_new_and_known_by_hash(self):
        self.fetched_and_triaged()
        out = self.run_cc("--fetch")
        self.assertIn("New:      nothing new to explain.", out)
        self.app(self.app_threads(extra_reply=("asha", "Still wrong for 0.5, I think.")))
        out = self.run_cc("--fetch")
        self.assertEqual(re.findall(r"New:      (\S+)", out), ["app#12:r2001"])
        self.assertNotEqual(self.items()["app#12:r2001"]["hash"], self.threads()["app#12:r2001"]["hash"])
        self.assertEqual(stage.comments_view(self.dir)["new"], 1)
        # when the last word is yours, there is nothing new to explain
        self.app(self.app_threads(extra_reply=("bumindu", "It is fixed now.")))
        out = self.run_cc("--fetch")
        self.assertIn("Answered: app#12:r2001. The last word there is yours.", out)
        self.assertIn("New:      nothing new to explain.", out)
        self.assertEqual(self.items()["app#12:r2001"]["state"], "replied")
        self.assertEqual(stage.comments_view(self.dir)["new"], 0)

    def test_a_follow_up_on_changed_code_is_not_lost(self):
        """After a fix is pushed the host calls the thread outdated. A reviewer can still answer there."""
        self.fetched_and_triaged()
        threads = self.app_threads(extra_reply=("asha", "Still lets 0.001 through."))
        threads[0].update(isOutdated=True, line=None)
        self.app(threads)
        out = self.run_cc("--fetch")
        self.assertEqual(re.findall(r"New:      (\S+)", out), ["app#12:r2001"])
        self.assertTrue(self.threads()["app#12:r2001"]["outdated"])
        self.assertIn("New:      1 not explained yet", self.run_cc("--status"))
        self.run_cc("--pack")
        self.assertIn("- Note: the diff under it changed since (outdated); explained before, but the comment changed.",
                      (self.dir / "pack.md").read_text())

    def test_gh_error_touches_nothing(self):
        self.run_cc("--fetch")
        before = {f.name: f.read_bytes() for f in self.dir.iterdir() if f.suffix == ".json"}
        (self.gh.home / "fail").write_text("")
        out = self.run_cc("--fetch", code=1)
        self.assertEqual(out.strip(), "Error: gh failed: HTTP 502: Bad Gateway (https://api.github.com/graphql)")
        self.assertEqual({f.name: f.read_bytes() for f in self.dir.iterdir() if f.suffix == ".json"}, before)
        (self.gh.home / "fail").unlink()
        (self.gh.home / "logged_in").unlink()
        out = self.run_cc("--fetch", code=1)
        self.assertIn("gh is not logged in to github.com", out)
        self.assertIn("--ingest <file>", out)
        self.assertEqual({f.name: f.read_bytes() for f in self.dir.iterdir() if f.suffix == ".json"}, before)

    def test_secrets_never_show(self):
        self.assertEqual(cc.hosts.scrub("bad token ghp_abcdefghij1234567890 here"), "bad token [hidden] here")


class IngestTest(Base):
    URL = "https://gitlab.com/g/sub/shop/-/merge_requests/5"

    def good(self):
        return {"me": "bumindu", "prs": [{"url": self.URL, "title": "Refunds", "state": "open", "head": "feat/x",
                                          "base": "main", "author": "bumindu", "review": "commented"}],
                "threads": [
                    {"id": "shop#5:n1", "pr": "shop#5", "kind": "inline", "file": "src/a.py", "line": 3,
                     "author": "asha", "body": "This check is wrong.", "created": "2026-11-14T09:00:00Z",
                     "replies": [{"author": "lee", "body": "Agree.", "created": "2026-11-14T09:05:00Z"}]},
                    {"id": "shop#5:n2", "pr": "shop#5", "kind": "general", "author": "bumindu", "body": "Pushed.",
                     "created": "2026-11-14T09:00:00Z"}]}

    def write(self, data):
        f = self.root / "in.json"
        f.write_text(json.dumps(data))
        return str(f)

    def test_bad_file_says_everything_plainly(self):
        bad = self.good()
        bad["prs"][0]["state"] = "opened"
        bad["threads"][0].update(path="src/a.py", line="3")
        del bad["threads"][0]["file"]
        bad["threads"][1]["id"] = "n2"
        bad["threads"].append({"id": "shop#5:n3", "pr": "shop#9", "kind": "note", "author": "", "body": ""})
        out = self.run_cc("--ingest", self.write(bad), code=2)
        for line in ("pr 1 (shop#5): 'state' must be one of open, merged, closed (got 'opened').",
                     "thread 1 (shop#5:n1): unknown field 'path'. Use 'file'.",
                     "thread 1 (shop#5:n1): an inline comment needs 'file' (the path in the repo).",
                     "thread 1 (shop#5:n1): 'line' must be a whole number from 1, or null.",
                     "thread 2 (n2): 'id' must start with the PR id, like shop#5:r2001.",
                     "thread 3 (shop#5:n3): 'pr' must be the id of a pull request in this file (shop#5), got 'shop#9'.",
                     "thread 3 (shop#5:n3): 'kind' must be one of inline, review, general (got 'note').",
                     "thread 3 (shop#5:n3): 'author' is needed", "thread 3 (shop#5:n3): 'body' is needed",
                     "SCHEMA.md"):
            self.assertIn(line, out)
        self.assertFalse((self.ws / "prs").exists())
        self.assertIn("is not valid JSON", self.bad_json())

    def bad_json(self):
        f = self.root / "broken.json"
        f.write_text("{not json")
        return self.run_cc("--ingest", str(f), code=2)

    def test_good_file_lands_in_a_loose_store(self):
        out = self.run_cc("--ingest", self.write(self.good()))
        self.assertIn("Feature:  prs/g-sub-shop-5", out)
        self.assertIn("PR:       shop#5 · open · commented · 1 comment", out)
        self.assertIn("Left out: 1 by the author only", out)
        self.assertIn("New:      shop#5:n1 · asha · src/a.py:3 · This check is wrong.", out)
        folder = self.ws / "prs" / "g-sub-shop-5" / "work" / "comments"
        t = json.loads((folder / "threads.json").read_text())["threads"]
        self.assertEqual([x["id"] for x in t], ["shop#5:n1"])
        self.assertEqual(t[0]["hash"], storelib.thread_hash("This check is wrong.", [{"body": "Agree."}]))
        self.assertEqual(json.loads((folder / "prs.json").read_text())["prs"][0]["host"], "gitlab")
        self.assertIn("gh cannot read these PRs", self.run_cc("--fetch", "g-sub-shop-5", code=1))
        # the same file again: nothing changes, nothing is new twice
        pack = self.run_cc("--pack", "g-sub-shop-5")
        self.assertIn("1 could not be read from a local checkout", pack)
        self.assertIn("there is no local checkout of shop", (folder / "pack.md").read_text())

    def test_ingest_into_a_feature(self):
        data = self.good()
        out = self.run_cc("--ingest", self.write(data), "--feature", "1")
        self.assertIn("Feature:  001-IDEA-1-refunds", out)
        self.assertEqual([p["id"] for p in self.load("prs.json")["prs"]], ["app#12", "web#7", "shop#5"])
        self.assertIn("shop#5:n1", self.threads())


class PackTest(Base):
    def test_pack_has_what_the_triager_needs(self):
        self.run_cc("--fetch")
        out = self.run_cc("--pack")
        self.assertIn("(5 comments on 2 PRs)", out)
        self.assertIn("Next:     start one chopchop:triager agent with the pack, then --triage %s"
                      % (self.dir / "triage-in.json"), out)
        pack = (self.dir / "pack.md").read_text()
        self.assertTrue(plain.has_summary(pack))
        self.assertIn("Write this JSON to `%s`" % (self.dir / "triage-in.json"), pack)
        self.assertEqual(plain.lint(pack)[0], [])
        self.assertIn("New groups start at G1.", pack)
        one = pack.split("### app#12:r2001")[1].split("### ")[0]
        self.assertIn("- PR: app#12 · by asha · at `src/refund.py:5`", one)
        self.assertIn("Tasks that cover this file: T01 Refund Api", one)
        self.assertIn('Spec rules that may apply: R-2 "A refund amount must be more than zero."', one)
        self.assertNotIn("R-1", one)
        self.assertRegex(one, r"- web#7:r3110 \(same words: [^)]*zero[^)]*\) · also in this pack")
        self.assertRegex(one, r"- app#12:r2002 \(same words: [^;]*; same file; same function refund\)")
        self.assertIn("This lets a refund of 0 through.", one)
        self.assertIn("```diff\n@@ -1,6 +1,9 @@ def refund(amount):", one)
        self.assertIn("The code now (`src/refund.py` lines 1 to 14, from the checkout, on branch %s):" % HEAD, one)
        self.assertIn(">    5      if amount >= 0:", one)
        self.assertIn("     6          total = min(amount, limit)", one)
        self.assertNotIn("r2003", pack)  # resolved

    def test_code_from_git_show_and_when_it_cannot_be_read(self):
        git(self.repos["app"], "checkout", "-q", "dev")
        (self.repos["web"] / "src" / "ui" / "form.js").unlink()
        git(self.repos["web"], "commit", "-q", "-am", "gone")
        git(self.repos["web"], "push", "-q", "origin", HEAD)
        self.run_cc("--fetch")
        out = self.run_cc("--pack")
        self.assertIn("Code:     1 could not be read", out)
        pack = (self.dir / "pack.md").read_text()
        self.assertIn("from git show origin/%s):" % HEAD, pack)
        self.assertIn(">    5      if amount >= 0:", pack)
        self.assertIn("The code could not be read: `src/ui/form.js` is not in branch `%s`" % HEAD, pack)
        self.assertIn("on branch `dev` (read the PR's code with `git show origin/%s:<path>`)" % HEAD, pack)

    def test_existing_groups_and_nothing_new(self):
        self.fetched_and_triaged()
        out = self.run_cc("--pack", code=1)
        self.assertIn("nothing new to explain", out)
        self.app(self.app_threads() + [node([comment(2010, "kim", "Zero amount: the check must refuse a refund of 0.")],
                                            "src/refund.py", 5)])
        self.run_cc("--fetch")
        self.run_cc("--pack")
        pack = (self.dir / "pack.md").read_text()
        self.assertIn("- G1 · real · high · Zero and negative amounts pass · threads: app#12:r2001, web#7:r3110", pack)
        self.assertIn("New groups start at G5.", pack)
        self.assertRegex(pack, r"- app#12:r2001 \([^)]*\) · already in G1 \(real\)")
        self.assertEqual(pack.count("\n### "), 1)
        self.assertFalse((self.dir / "triage-in.json").exists())  # the old answer is gone
        # --again brings a known comment back, --all the settled ones too
        self.run_cc("--pack", "--again", "G2")
        self.assertIn("### app#12:r2002", (self.dir / "pack.md").read_text())
        self.run_cc("--pack", "--all")
        self.assertIn("### app#12:r2003", (self.dir / "pack.md").read_text())

    def test_similarity(self):
        a = {"id": "a", "repo": "app", "file": "src/x.py", "hunk": "@@ -1 +1 @@ def refund(amount):",
             "body": "The amountCheck lets zero through", "replies": []}
        b = {"id": "b", "repo": "web", "file": "src/y.js", "hunk": "@@ -1 +1 @@ function send() {",
             "body": "Same zero problem in the amount check here", "replies": []}
        c = {"id": "c", "repo": "app", "file": "src/x.py", "hunk": None, "body": "Rename this variable", "replies": []}
        d = {"id": "d", "repo": "web", "file": "docs/a.md", "hunk": None, "body": "Add a screenshot please", "replies": []}
        self.assertTrue({"amount", "check", "zero"} <= similar.tokens(a["body"]))
        self.assertEqual(similar.function_of(a["hunk"]), "refund")
        self.assertEqual(similar.function_of(b["hunk"]), "send")
        got = similar.similar_threads([a], [a, b, c, d])["a"]
        self.assertEqual([h["id"] for h in got], ["b", "c"])
        self.assertIn("same file", got[1]["why"])
        self.assertEqual(similar.similar_threads([d], [a, b, c, d])["d"], [])


class TriageTest(Base):
    def test_bad_triage_is_refused_with_every_reason(self):
        self.run_cc("--fetch")
        bad = self.default_triage()
        bad["items"]["app#12:r2001"].update(verdict="bug", priority="urgent", evidence=[])
        bad["items"]["app#12:r2002"]["evidence"] = []
        bad["items"]["app#12:r9999"] = self.item()
        bad["items"]["app#12:v900"]["group"] = "G9"
        bad["items"]["app#12:c700"]["reply"] = ""
        bad["groups"][1]["threads"].append("web#7:r3110")
        bad["groups"][2]["id"] = "g3"
        out = self.triage_with(bad, code=2)
        for line in ("item app#12:r2001: 'verdict' must be one of real, false-positive, negotiable, question, praise, "
                     "outdated (got 'bug').",
                     "item app#12:r2001: 'priority' must be one of high, medium, low (got 'urgent').",
                     "item app#12:r2002: a false-positive verdict needs 'evidence'",
                     "item app#12:r9999: there is no thread with this id.",
                     "item app#12:v900: group G9 is not in 'groups' and is not an existing group.",
                     "item app#12:c700: 'reply' is needed",
                     "thread web#7:r3110 is in two groups (G1 and G2).",
                     "'id' must look like G1, G2, G3 (got 'g3')."):
            self.assertIn(line, out)
        self.assertFalse((self.dir / "triage.json").exists())
        bad = self.default_triage()
        bad["groups"][0]["threads"] = ["app#12:r2001"]
        self.assertIn("item web#7:r3110: it says group G1, but G1 does not list it in 'threads'.",
                      self.triage_with(bad, code=2))

    def test_merge_writes_the_spec_shapes_and_the_report(self):
        self.run_cc("--fetch")
        data = self.default_triage()
        data["items"]["app#12:r2002"]["reply"] = "Thanks %s line 7 already handles it." % LONG_DASH
        out = self.triage_with(data)
        self.assertIn("Triage:   5 comments explained, now 4 groups · 2 real, 1 question, 1 negotiable, 1 false positive", out)
        self.assertIn("Call:     5 need your call (fix, reply or skip)", out)
        self.assertIn("Top:      G1 · high · a real problem · Zero and negative amounts pass (2 comments) · same file as G2", out)
        self.assertIn("Warning:  app#12:r2002 reply: has a long dash.", out)
        self.assertIn("Next:     tell the person, ask which to fix", out)

        tri = self.load("triage.json")
        self.assertEqual(list(tri), ["updated", "items", "groups"])
        item = tri["items"]["app#12:r2001"]
        self.assertEqual(list(item), ["plain", "verdict", "priority", "group", "why", "evidence", "fix", "impact", "reply",
                                      "decision", "state", "hash", "commit"])
        self.assertEqual((item["decision"], item["state"], item["commit"]), (None, "triaged", None))
        self.assertEqual(item["hash"], self.threads()["app#12:r2001"]["hash"])
        groups = {g["id"]: g for g in tri["groups"]}
        self.assertEqual(list(groups["G1"]), ["id", "title", "plain", "threads", "verdict", "priority", "fix", "impact",
                                              "files", "order", "with"])
        self.assertEqual(groups["G1"]["files"], ["app/src/refund.py", "web/src/ui/form.js"])
        self.assertEqual((groups["G1"]["with"], groups["G2"]["with"], groups["G3"]["with"]), (["G2"], ["G1"], []))
        self.assertEqual(groups["G4"]["files"], ["app/CHANGELOG.md"])
        # high before medium before low, and a question before a negotiable one
        self.assertEqual([(g["id"], g["order"]) for g in tri["groups"]], [("G1", 1), ("G2", 2), ("G3", 3), ("G4", 4)])

        view = stage.comments_view(self.dir)
        mine = cc.triage.counts(storelib.Store(self.ws, self.fpath, features.resolve(self.ws, "1")))
        for key in ("open", "merged", "closed", "threads", "live", "new", "undecided", "to_fix", "fixed", "replied",
                    "by_verdict", "groups", "watching"):
            self.assertEqual(view[key], mine[key], key)
        self.assertEqual((view["new"], view["undecided"], view["groups"]), (0, 5, 4))

        text = (self.fpath / "comments.md").read_text()
        self.assertTrue(plain.has_summary(text))
        self.assertLess(text.index("## Summary"), text.index("## Pull requests"))
        self.assertLess(text.index("## Pull requests"), text.index("### G1 · Zero and negative amounts pass"))
        self.assertLess(text.index("### G1"), text.index("### G2"))
        self.assertLess(text.index("### G4"), text.index("## Not explained yet"))
        self.assertIn("- **Needs your call:** 5 comment(s). Say fix, reply or skip for each.", text)
        self.assertIn("| app#12 Refund requests | open | changes requested | 5 | %s |" % APP_URL, text)
        for line in ("- **Verdict:** a real problem", "- **Priority:** high", "- **Our fix:** Compare with > 0 and add a test.",
                     "- **What the fix touches:** Only this check.", "- **Evidence:** `app/src/refund.py:5`",
                     "- **Shares a file with:** G2.", "- **Your call:** not decided yet", "- **Why we think so:** Line 5",
                     "- **Verdict:** the reviewer is mistaken, medium priority",
                     "- **Verdict:** fair, but not for this PR, low priority",
                     "  > Good catch. Fixed in the next commit, with a test.",
                     "#### app#12:r2001 · asha · `src/refund.py:5` · [open]("):
            self.assertIn(line, text)
        self.assertIn("Every open comment is explained.", text)
        self.assertIn("1 more comment(s) are settled", text)
        self.assertEqual([e["kind"] for e in events.read(self.fpath)][-1], "triage")

    def test_decision_survives_and_a_changed_comment_starts_again(self):
        self.fetched_and_triaged()
        self.run_cc("--decide", "G1", "fix")
        self.triage_with(self.default_triage())  # the same answer again
        self.assertEqual(self.items()["app#12:r2001"]["decision"], "fix")
        self.app(self.app_threads(extra_reply=("asha", "Also 0.001 passes.")))
        self.run_cc("--fetch")
        text = (self.fpath / "comments.md").read_text()
        self.assertIn("- app#12:r2001 · asha · src/refund.py:5", text.split("## Not explained yet")[1])
        self.assertIn("the comment changed after this was written", text)
        again = {"items": {"app#12:r2001": self.item(plain="0.001 passes too.")}, "groups": []}  # joins the existing G1
        out = self.triage_with(again)
        self.assertIn("Again:    app#12:r2001 changed since the last look.", out)
        item = self.items()["app#12:r2001"]
        self.assertEqual((item["decision"], item["state"], item["was"]), (None, "triaged", "fix"))
        self.assertEqual(item["hash"], self.threads()["app#12:r2001"]["hash"])
        self.assertEqual(self.items()["web#7:r3110"]["decision"], "fix")  # it did not change
        g1 = self.load("triage.json")["groups"][0]
        self.assertEqual((g1["id"], g1["threads"]), ("G1", ["app#12:r2001", "web#7:r3110"]))
        self.assertIn("it was 'fix' before the comment changed", (self.fpath / "comments.md").read_text())

    def test_moving_a_comment_empties_and_drops_a_group(self):
        self.fetched_and_triaged()
        move = {"items": {"app#12:r2002": self.item(group="G1", evidence=["app/src/refund.py:7"])},
                "groups": [self.group("G1", ["app#12:r2001", "web#7:r3110", "app#12:r2002"])]}
        self.triage_with(move)
        groups = self.load("triage.json")["groups"]
        self.assertEqual([g["id"] for g in groups], ["G1", "G3", "G4"])
        self.assertEqual(groups[0]["threads"], ["app#12:r2001", "app#12:r2002", "web#7:r3110"])


class DecideTest(Base):
    def test_rules(self):
        self.fetched_and_triaged()
        out = self.run_cc("--decide", "app#12:r2002", "fix", code=2)
        self.assertIn("the verdict is 'false-positive', so there is nothing to fix", out)
        self.assertIn("--pack --again app#12:r2002", out)
        out = self.run_cc("--decide", "G4", "fix", code=2)
        self.assertIn("it is fair, but not for this PR, not a real problem. Fix it only when the person insists: add --force", out)
        self.assertIn("Decided:  fix · 1 comment: app#12:c700", self.run_cc("--decide", "G4", "fix", "--force"))
        out = self.run_cc("--decide", "all-real", "fix")
        self.assertIn("Decided:  fix · 2 comments: app#12:r2001, web#7:r3110", out)
        self.assertIn("Still:    2 need your call", out)
        self.assertIn("Next:     ask the person about the 2 open call(s)", out)
        self.run_cc("--decide", "app#12:r2002,G3", "reply")
        items = self.items()
        self.assertEqual({k: v["decision"] for k, v in items.items()},
                         {"app#12:r2001": "fix", "web#7:r3110": "fix", "app#12:r2002": "reply", "app#12:v900": "reply",
                          "app#12:c700": "fix"})
        self.assertIn("Next:     --plan", self.run_cc("--status"))
        self.assertIn("'G9' is not a thread id or a group", self.run_cc("--decide", "G9", "skip", code=2))
        self.assertIn("The call must be fix, reply or skip", self.run_cc("--decide", "G1", "later", code=2))
        out = self.run_cc("--decide", "all", "skip")
        self.assertIn("5 comments", out)
        self.assertEqual(stage.comments_view(self.dir)["undecided"], 0)
        self.assertIn("comment", [e["kind"] for e in events.read(self.fpath) if e.get("by") == "you"])

    def test_all_fix_leaves_what_is_not_real(self):
        self.fetched_and_triaged()
        out = self.run_cc("--decide", "all", "fix")
        self.assertIn("Decided:  fix · 2 comments", out)
        self.assertEqual(out.count("Left:     "), 3)
        self.assertEqual(self.items()["app#12:r2002"]["decision"], None)


class FixTest(Base):
    def planned(self):
        self.fetched_and_triaged()
        self.run_cc("--decide", "all-real", "fix")
        return self.run_cc("--plan")

    def plan(self):
        return json.loads((self.dir / "fix" / "plan.json").read_text())["batches"]

    def test_groups_that_share_a_file_are_one_batch(self):
        self.run_cc("--fetch")
        data = self.default_triage()
        data["items"]["app#12:r2002"].update(verdict="real", fix="Refuse a negative amount.", impact="The same check.")
        data["groups"][1].update(verdict="real", fix="Refuse a negative amount.", impact="The same check.")
        self.triage_with(data)
        self.assertEqual(self.run_cc("--plan", code=1).splitlines()[0],
                         "Plan:     nothing to fix. No open comment has the call 'fix'.")
        self.run_cc("--decide", "all-real", "fix")
        out = self.run_cc("--plan")
        self.assertIn("Plan:     2 batches, most urgent first.", out)
        self.assertIn("B1:       app · %s · G1, G2 · 2 comments · 1 file" % HEAD, out)
        self.assertIn("B2:       web · %s · G1 · 1 comment · 1 file" % HEAD, out)
        self.assertIn("chopchop_review.py --pack --repo %s" % self.repos["app"], out)
        b1, b2 = self.plan()
        self.assertEqual((b1["threads"], b1["files"], b1["groups"]), (["app#12:r2001", "app#12:r2002"], ["src/refund.py"], ["G1", "G2"]))
        self.assertEqual((b2["repo"], b2["threads"], b2["files"]), ("web", ["web#7:r3110"], ["src/ui/form.js"]))
        self.assertEqual({v["state"] for k, v in self.items().items() if v["decision"] == "fix"}, {"fixing"})
        self.assertEqual([b["id"] for b in json.loads(self.run_cc("--plan", "--json"))["batches"]], ["B1", "B2"])  # stable ids

        brief = (self.dir / "fix" / "B1" / "brief.md").read_text()
        self.assertTrue(plain.has_summary(brief))
        for line in ("There is no task file for this job. This brief is the task.",
                     "- Repo: app at `%s`, on branch `%s`. It is checked out. Stay on it." % (self.repos["app"], HEAD),
                     "- Files you may touch: `src/refund.py`, and the tests of those files.",
                     "- Check: run `ruff check .`, then `python3 -m unittest` in the repo. All must pass.",
                     "- Profile (commands and rules): `%s`" % (self.ws / "repos" / "app.md"),
                     "- Task file to read for the contract and the names: `%s`" % (self.fpath / "tasks" / "T01-refund-api.md"),
                     "### G1 · Zero and negative amounts pass", "### G2 · Negative amounts",
                     "app#12:r2001, by asha at `src/refund.py:5`:",
                     "This lets a refund of 0 through. The amount check must refuse zero.",
                     "A negative amount is not handled here.",
                     "Other comments of this group are not yours to fix here: web#7:r3110.",
                     "- B2 changes web for G1. Do not touch that repo.",
                     "- Never commit, push, stash, reset, switch branches or stage files.",
                     "Write `%s`:" % (self.dir / "fix" / "B1" / "report.json"), '"batch": "B1"'):
            self.assertIn(line, brief)
        self.assertNotIn("web#7:r3110, by", brief)

    def test_commit_and_push_guards(self):
        out = self.planned()
        self.assertIn("B1:       app · %s · G1 · 1 comment · 1 file" % HEAD, out)
        app = self.repos["app"]
        self.assertIn("Nothing to commit for B1", self.run_cc("--commit", "B1", "--message", "fix: x", code=2))
        (app / "src" / "refund.py").write_text(REFUND_PY.replace("amount >= 0", "amount > 0"))
        (app / "tests").mkdir()
        (app / "tests" / "test_refund.py").write_text("def test_refuses_zero_refund():\n    assert True\n")
        (app / "docs").mkdir()
        (app / "docs" / "notes.md").write_text("unrelated\n")
        out = self.run_cc("--commit", "B1", "--message", "fix: refuse zero refunds", code=1)
        self.assertIn("Outside:  B1 changed files that are not in or next to the batch's files: docs/notes.md", out)
        self.assertIn("--outside docs/notes.md", out)
        (app / "docs" / "notes.md").unlink()
        self.assertIn('needs --message', self.run_cc("--commit", "B1", code=2))

        git(app, "stash", "-q", "-u")
        git(app, "checkout", "-q", "dev")
        out = self.run_cc("--commit", "B1", "--message", "fix: refuse zero refunds", code=2)
        self.assertIn("app is on branch dev, not on the PR's branch %s." % HEAD, out)
        git(app, "checkout", "-q", HEAD)
        git(app, "stash", "pop", "-q")

        before = git(app, "rev-parse", "HEAD")
        out = self.run_cc("--commit", "B1", "--message", "fix: refuse zero refunds")
        self.assertRegex(out, r"Commit:   B1 [0-9a-f]{7,} on %s · 2 files · fix: refuse zero refunds" % re.escape(HEAD))
        self.assertIn("Next:     --push app, then --fixed B1", out)
        self.assertEqual(git(app, "log", "-1", "--format=%s"), "fix: refuse zero refunds")
        self.assertEqual(git(app, "rev-parse", "HEAD~1"), before)
        self.assertEqual(git(app, "status", "--porcelain"), "")
        self.assertEqual(self.plan()[0]["state"], "committed")
        self.assertIn("B1 is already committed", self.run_cc("--commit", "B1", "--message", "again", code=2))

        # push: never to the base branch or a protected one, also not through a wrong upstream
        prs = self.load("prs.json")
        prs["prs"][0]["base"] = HEAD
        (self.dir / "prs.json").write_text(json.dumps(prs))
        self.assertIn("is the PR's base branch. chopchop never commits or pushes there.", self.run_cc("--push", "app", code=2))
        prs["prs"][0]["base"] = BASE
        (self.dir / "prs.json").write_text(json.dumps(prs))
        git(app, "config", "branch.%s.merge" % HEAD, "refs/heads/dev")
        self.assertIn("Not pushed. 'dev' is a protected branch.", self.run_cc("--push", "app", code=2))
        git(app, "config", "branch.%s.merge" % HEAD, "refs/heads/%s" % HEAD)
        self.assertIn("No open PR for repo 'api' here. Repos: app, web.", self.run_cc("--push", "api", code=2))

        # someone else pushed first: the push is refused, never forced
        other = self.root / "other"
        git(self.root, "clone", "-q", "-b", HEAD, str(self.root / "app.git"), str(other))
        git(other, "config", "user.name", "dev-b")
        git(other, "config", "user.email", "b@acme.test")
        (other / "late.txt").write_text("x\n")
        git(other, "add", ".")
        git(other, "commit", "-q", "-m", "late")
        git(other, "push", "-q", "origin", HEAD)
        theirs = git(self.root / "app.git", "rev-parse", HEAD)
        out = self.run_cc("--push", "app", code=1)
        self.assertIn("Push:     refused for app (%s)" % HEAD, out)
        self.assertIn("chopchop never force-pushes", out)
        self.assertEqual(git(self.root / "app.git", "rev-parse", HEAD), theirs)
        git(app, "pull", "-q", "--rebase", "origin", HEAD)  # what a person does
        sha = git(app, "rev-parse", "--short", "HEAD")

        out = self.run_cc("--push", "app")
        self.assertIn("Push:     app · %s -> origin/%s" % (HEAD, HEAD), out)
        self.assertIn("Next:     --fixed B1", out)
        self.assertEqual(git(self.root / "app.git", "rev-parse", HEAD), git(app, "rev-parse", "HEAD"))
        self.assertEqual(git(self.root / "app.git", "rev-parse", BASE), git(app, "rev-parse", BASE))

        self.assertIn("There is no commit deadbeef", self.run_cc("--fixed", "B1", "--commit", "deadbeef", code=2))
        out = self.run_cc("--fixed", "B1", "--commit", sha)
        self.assertIn("Fixed:    B1 · %s · 1 comment: app#12:r2001" % sha, out)
        item = self.items()["app#12:r2001"]
        self.assertEqual((item["state"], item["commit"]), ("fixed", sha))
        self.assertEqual(self.items()["web#7:r3110"]["state"], "fixing")
        self.assertEqual(stage.comments_view(self.dir)["fixed"], 1)
        out = self.run_cc("--replies")
        self.assertIn("Reply:    app#12:r2001 · to asha at src/refund.py:5 · ready", out)
        self.assertIn("          | Fixed in %s." % sha, out)
        self.assertIn("Reply:    web#7:r3110 · to asha at src/ui/form.js:2 · waits: after the fix is in", out)
        kinds = [e["kind"] for e in events.read(self.fpath)]
        for kind in ("fix", "commit", "push"):
            self.assertIn(kind, kinds)

    def test_a_blocked_builder_stops_the_commit(self):
        self.planned()
        (self.repos["app"] / "src" / "refund.py").write_text("changed\n")
        (self.dir / "fix" / "B1" / "report.json").write_text(json.dumps({"batch": "B1", "blocked": "the check is in another repo"}))
        out = self.run_cc("--commit", "B1", "--message", "fix: x", code=1)
        self.assertIn("Blocked:  the builder could not make the fix as written: the check is in another repo", out)
        self.assertEqual(git(self.repos["app"], "log", "-1", "--format=%s"), "build")

    def test_near(self):
        files = ["src/services/refundService.js"]
        for path, ok in (("src/services/refundService.js", True), ("src/services/helper.js", True),
                         ("test/refundService.test.js", True), ("tests/test_refund_service.py", True),
                         ("src/views/other.js", False), ("test/orders.test.js", False)):
            self.assertEqual(cc.near(path, files), ok, path)


class RepliesTest(Base):
    def test_drafts_and_no_post_without_a_yes(self):
        self.fetched_and_triaged()
        self.run_cc("--decide", "G2,G4", "reply")
        out = self.run_cc("--replies")
        self.assertIn("Reply:    app#12:r2002 · to lee at src/refund.py:9 · ready", out)
        self.assertIn("          | Thanks for checking. Line 7 already sets a negative amount to 0.", out)
        self.assertIn("Reply:    app#12:v900 · to asha at review summary · waits: not decided yet", out)
        self.assertIn("Post only after they say yes: --post --yes", out)
        text = (self.dir / "replies.md").read_text()
        self.assertTrue(plain.has_summary(text))
        self.assertIn("## Ready to post", text)
        self.assertIn("Thanks for checking. Line 7 already sets a negative amount to 0.", text)

        out = self.run_cc("--post", code=2)
        self.assertIn("Refused:  posting needs the person's yes. Nothing was posted.", out)
        self.assertIn("Would post 2 replies: app#12:r2002, app#12:c700", out)
        self.assertEqual(self.gh.posts(), [])
        self.assertIn("app#12:v900: waits: not decided yet", self.run_cc("--post", "G3", "--yes", code=2))
        self.assertEqual(self.gh.posts(), [])

        out = self.run_cc("--post", "--yes")
        self.assertIn("Posted:   app#12:r2002 · https://github.com/posted/repos/acme/app/pulls/12/comments/2002/replies", out)
        self.assertIn("Posted:   app#12:c700 · https://github.com/posted/repos/acme/app/issues/12/comments", out)
        posts = self.gh.posts()
        self.assertEqual([p[1] for p in posts], ["repos/acme/app/pulls/12/comments/2002/replies",
                                                 "repos/acme/app/issues/12/comments"])
        self.assertIn("body=Thanks for checking. Line 7 already sets a negative amount to 0.", posts[0])
        # a reply to a PR comment is a new PR comment, so it quotes what it answers
        self.assertIn("body=> Can you add a changelog line for refunds?\n\nFair point. The changelog is written at "
                      "release time, so I will add a task for it.", posts[1])
        items = self.items()
        self.assertEqual((items["app#12:r2002"]["state"], items["app#12:c700"]["state"]), ("replied", "replied"))
        self.assertEqual(stage.comments_view(self.dir)["replied"], 2)
        self.assertEqual(stage.comments_view(self.dir)["new"], 0)  # our own reply is not a new comment
        self.assertIn("No reply is ready to post", self.run_cc("--post", "--yes", code=2))
        self.assertEqual(len(self.gh.posts()), 2)  # never twice
        self.assertIn("reply", [e["kind"] for e in events.read(self.fpath)])

        # the host now shows our reply in the thread: still nothing new
        threads = self.app_threads()
        threads[1]["comments"]["nodes"].append(comment(2099, "bumindu", "Thanks for checking. Line 7 already sets a "
                                                                        "negative amount to 0.", at="2026-11-14T12:00:00Z"))
        self.app(threads)
        self.assertIn("nothing new to explain", self.run_cc("--fetch"))
        self.assertEqual(self.items()["app#12:r2002"]["state"], "replied")

    def test_post_fails_cleanly(self):
        self.fetched_and_triaged()
        self.run_cc("--decide", "G2", "reply")
        (self.gh.home / "fail").write_text("")
        out = self.run_cc("--post", "--yes", code=1)
        self.assertIn("Failed:   app#12:r2002: gh failed: HTTP 502", out)
        self.assertEqual(self.items()["app#12:r2002"]["state"], "triaged")


class WaitTest(Base):
    def test_new_comment_ends_the_wait_with_0(self):
        out = self.run_cc("--wait", "--every", "0.05", "--for", "5")
        self.assertIn("New:      app#12:r2001 · asha · src/refund.py:5", out)
        self.assertIn("Then --wait again.", out)

    def test_quiet_ends_with_3_and_keeps_the_time(self):
        self.fetched_and_triaged()
        self.run_cc("--watch", "on")
        self.assertTrue(stage.comments_view(self.dir)["watching"])

        def threads():
            return len([c for c in self.gh.calls() if any("query Threads" in a for a in c)])

        before = threads()
        out = self.run_cc("--wait", "--every", "0.05", "--for", "0.3", code=3)
        self.assertIn("Quiet:    nothing new on 001-IDEA-1-refunds", out)
        watch = self.load("prs.json")["watch"]
        self.assertTrue(watch["on"] and watch["since"] and watch["last"])
        # At least one full look at every PR. How many looks fit in 0.3 s depends on the machine.
        self.assertGreaterEqual(threads() - before, len(self.load("prs.json")["prs"]))

    def test_a_comment_that_arrives_while_waiting(self):
        self.fetched_and_triaged()

        def late():
            self.app(self.app_threads() + [node([comment(2020, "kim", "One more thing here.")], "src/refund.py", 2)])

        timer = threading.Timer(0.3, late)
        timer.start()
        try:
            out = self.run_cc("--wait", "--every", "0.1", "--for", "10")
        finally:
            timer.cancel()
        self.assertEqual(re.findall(r"New:      (\S+)", out), ["app#12:r2020"])

    def test_all_merged_or_closed_ends_with_2(self):
        self.fetched_and_triaged()
        self.run_cc("--watch", "on")
        self.app(state="MERGED")
        self.web(state="CLOSED")
        out = self.run_cc("--wait", "--every", "0.05", "--for", "5", code=2)
        self.assertIn("Merged:   app#12 is merged. Done now: T01.", out)
        self.assertIn("Done:     every PR is merged or closed.", out)
        self.assertFalse(self.load("prs.json")["watch"]["on"])
        self.assertIn("Next:     nothing. Every PR is merged or closed.", self.run_cc("--status"))

    def test_gh_down_ends_with_1(self):
        self.fetched_and_triaged()
        (self.gh.home / "fail").write_text("")
        self.assertIn("Error: gh failed: HTTP 502", self.run_cc("--wait", "--every", "0.05", "--for", "5", code=1))

    def test_sigterm_stops_it_cleanly(self):
        self.fetched_and_triaged()
        proc = subprocess.Popen([sys.executable, str(HERE.parent / "scripts" / "chopchop_comments.py"), "--wait",
                                 "--every", "0.2", "--for", "120", "--workspace", str(self.ws)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(self.root))
        time.sleep(2.5)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 130, out + err)
        self.assertIn("Stopped:  no longer waiting on 001-IDEA-1-refunds.", out)
        self.assertNotIn("Traceback", err)
        self.assertTrue(self.load("prs.json")["watch"]["last"])


class LooseTest(Base):
    def test_a_pr_with_no_feature_goes_all_the_way(self):
        ws = self.root / "solo" / "_chopchop"
        app = self.repos["app"]
        out = self.run_cc("--pr", APP_URL, "--path", str(app), ws=ws)
        self.assertIn("Added:    app#12", out)
        folder = ws / "prs" / "acme-app-12"
        self.assertIn("Feature:  prs/acme-app-12", self.run_cc("--fetch", ws=ws))  # the only store: no ref needed
        self.run_cc("--pack", APP_URL, ws=ws)
        pack = (folder / "work" / "comments" / "pack.md").read_text()
        self.assertIn(">    5      if amount >= 0:", pack)
        self.assertIn("Tasks that cover this file: none found", pack)
        answer = folder / "work" / "comments" / "triage-in.json"
        answer.write_text(json.dumps({"items": {"app#12:r2001": self.item()}, "groups": [self.group("G1", ["app#12:r2001"])]}))
        out = self.run_cc("--triage", str(answer), ws=ws)
        self.assertIn("Missing:  3 comments still not explained: app#12:r2002, app#12:v900, app#12:c700", out)
        text = (folder / "comments.md").read_text()
        self.assertTrue(plain.has_summary(text))
        self.assertIn("- **Not explained yet:** 3 new comment(s).", text)
        self.run_cc("--decide", "all-real", "fix", ws=ws)
        out = self.run_cc("--plan", ws=ws)
        self.assertIn("B1:       app · %s · G1 · 1 comment · 1 file" % HEAD, out)
        brief = (folder / "work" / "comments" / "fix" / "B1" / "brief.md").read_text()
        self.assertIn("chopchop does not know this repo's test command", brief)
        self.assertIn("triage", [e["kind"] for e in events.read(folder)])
        self.app(state="MERGED")
        self.assertIn("Merged:   app#12 is merged.", self.run_cc("--fetch", ws=ws))

    def test_the_checkout_is_found_by_its_origin(self):
        repo = self.root / "clone"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "remote", "add", "origin", "git@github.com:Acme/App.git")
        self.assertTrue(cc.origin_is(repo, "acme/app"))
        self.assertFalse(cc.origin_is(repo, "acme/web"))
        git(repo, "remote", "set-url", "origin", "https://github.com/acme/app")
        self.assertTrue(cc.origin_is(repo, "acme/app"))


class MergeTest(Base):
    def status(self, tid):
        f = next((self.fpath / "tasks").glob("%s-*.md" % tid))
        return features.read_front_matter(f)["status"]

    def test_merged_pr_finishes_its_tasks(self):
        self.fetched_and_triaged()
        self.run_cc("--decide", "G1", "fix")
        self.app(state="MERGED")
        self.web(state="CLOSED")
        out = self.run_cc("--fetch")
        self.assertIn("PR:       app#12 · merged", out)
        self.assertIn("Merged:   app#12 is merged. Done now: T01.", out)
        self.assertEqual((self.status("T01"), self.status("T02"), self.status("T03")), ("done", "in-review", "todo"))
        merges = [e for e in events.read(self.fpath) if e["kind"] == "merge"]
        self.assertEqual((len(merges), merges[0]["text"], merges[0]["repo"]), (1, "app#12 is merged. Done: T01.", "app"))
        self.assertTrue(all(t["resolved"] for t in self.threads().values()))
        self.assertEqual({v["state"] for v in self.items().values()}, {"closed"})
        self.assertEqual(stage.comments_view(self.dir)["undecided"], 0)
        self.assertIn("Plan:     nothing to fix.", self.run_cc("--plan", code=1))
        # a second look does not fetch the merged PR again, and logs no second merge
        calls = len([c for c in self.gh.calls() if "number=12" in c])
        self.run_cc("--fetch")
        self.assertEqual(len([c for c in self.gh.calls() if "number=12" in c]), calls)
        self.assertEqual(len([e for e in events.read(self.fpath) if e["kind"] == "merge"]), 1)
        # the web PR is reopened and merged: its task carries the PR link
        self.web(state="MERGED")
        self.assertIn("Merged:   web#7 is merged. Done now: T02.", self.run_cc("--fetch"))
        self.assertEqual(self.status("T02"), "done")


class StatusTest(Base):
    def test_status_walks_the_steps(self):
        self.assertIn("Next:     --fetch 1", self.run_cc("--status"))
        self.run_cc("--fetch")
        out = self.run_cc("--status")
        self.assertIn("PRs:      2 · 2 open, 0 merged, 0 closed", out)
        self.assertIn("Comments: 6 · 5 open, 1 settled", out)
        self.assertIn("New:      5 not explained yet", out)
        self.assertIn("Next:     --pack 1, then the triager, then --triage", out)
        self.triage_with(self.default_triage())
        data = json.loads(self.run_cc("--status", "--json"))
        self.assertEqual((data["new"], data["undecided"], data["groups"]), (0, 5, 4))
        self.run_cc("--decide", "all", "skip")
        self.assertIn("the reviewers have the next move", self.run_cc("--status"))
        self.assertIn("Use one of --prs", self.run_cc(code=2))

    def test_schema_keeps_spec_values(self):
        self.assertEqual(schema.VERDICTS, stage.VERDICTS)
        self.assertEqual(tuple(triage.NEEDS_DECISION), tuple(stage.NEEDS_DECISION))
        self.assertEqual(report.fence("a ``` b"), "```text\na ''' b\n```")
        self.assertEqual(report.fence("a ``` b", exact=True), "````text\na ``` b\n````")
        self.assertEqual(report.first_words("```suggestion\nx = 1\n```\nUse this."), "x = 1 Use this.")


if __name__ == "__main__":
    unittest.main()
