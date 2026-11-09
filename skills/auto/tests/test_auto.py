"""The auto loop end to end on two local repos, with a fake builder and a fake reviewer."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(SKILLS / "review" / "scripts"))

import chopchop_auto  # noqa: E402  (puts the code and tasks scripts on the path)
import chopchop_code  # noqa: E402
import chopchop_review  # noqa: E402
import chopchop_tasks  # noqa: E402
from codelib import profile  # noqa: E402
from chopchoplib import features  # noqa: E402


def git(path, *args):
    out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), out.stderr))
    return out.stdout.strip()


def task_text(tid, slug, repo, wave=1, deps=(), touches=(), do_not=""):
    meta = {"id": tid, "title": slug.replace("-", " ").title(), "repo": repo, "wave": wave, "size": "S",
            "status": "todo", "owner": None, "depends_on": list(deps), "touches": list(touches),
            "stories": ["PAY-121"], "pr": None}
    return features.render_front_matter(meta) + (
        "# %s\n\n## Goal\n\nIt works.\n\n## Done when\n\n- [ ] Unit test `does_the_thing`: it works.\n\n"
        "## Do not change\n\n%s- Contracts from earlier tasks.\n\n## Branch\n\n_Written by chopchop._\n" % (tid, do_not))


def run(main, ws, *argv, code=0):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        got = main(list(argv) + ["--workspace", str(ws)])
    text = out.getvalue() + err.getvalue()
    assert code is None or got == code, "exit %s, wanted %s:\n%s" % (got, code, text)
    return text


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "_chopchop"
        self.ws.mkdir()
        self.repos = {name: self.make_repo(name) for name in ("app", "web")}
        (self.ws / "chopchop.yaml").write_text("team: t\nbase_branch: dev\nrepos:\n" + "".join(
            "  %s:\n    path: %s\n" % (n, p) for n, p in self.repos.items()))
        design = self.root / "design.md"
        design.write_text("# Design\n")
        run(chopchop_tasks.main, self.ws, "--new", str(design), "--name", "refunds")
        self.feature = features.resolve(self.ws, "1")
        tdir = self.feature.path / "tasks"
        (tdir / "T01-money.md").write_text(task_text("T01", "money", "app", 0, touches=["src/contract/**"],
                                                     do_not="- Do not use `LegacyMoney`.\n"))
        (tdir / "T02-refund-api.md").write_text(task_text("T02", "refund-api", "app", 1, ["T01"], ["src/api/**"],
                                                          do_not="- Do not use `LegacyMoney`.\n"))
        (tdir / "T03-refund-button.md").write_text(task_text("T03", "refund-button", "web", 1, touches=["src/ui/**"]))
        (tdir / "T04-refund-job.md").write_text(task_text("T04", "refund-job", "app", 2, ["T02"], ["src/job/**"]))
        run(chopchop_tasks.main, self.ws, "--branch", "1", "--create")
        for name in self.repos:
            p = profile.path_for(self.ws, name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(features.render_front_matter({"repo": name, "confirmed": True, "test": "test ! -f FAIL"}) + "# x\n")
        self.work = self.feature.path / "work"

    def tearDown(self):
        self.tmp.cleanup()

    def make_repo(self, name):
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
        return repo

    def auto(self, *argv, code=0):
        return run(chopchop_auto.main, self.ws, *argv, code=code)

    def state(self):
        return json.loads((self.work / "auto.json").read_text())

    def build(self, tid, repo, files, blocked=None, commit=None):
        """What the builder agent does: write the code, run the check, write the report."""
        for rel, text in files.items():
            f = self.repos[repo] / rel
            if text is None:
                f.unlink()
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        report = {"task": tid, "ok": not blocked, "blocked": blocked, "files": list(files), "tests": ["does_the_thing"],
                  "notes": "%s added %s." % (tid, ", ".join(files)), "commit": commit}
        (self.work / "auto" / tid / "report.json").write_text(json.dumps(report))
        if not blocked:
            return run(chopchop_code.main, self.ws, tid, "--verify", code=None if "FAIL" in files else 0)

    def review(self, tid, findings, code=0):
        """What the reviewer agent does: write findings next to the pack. Then sort them."""
        pack = Path(self.state()["tasks"][tid]["pack"])
        (pack.parent / "findings.json").write_text(json.dumps({"findings": findings}))
        return self.auto("--sort", tid, code=code)


class LoopTest(Base):
    def test_whole_run(self):
        app, web = self.repos["app"], self.repos["web"]
        (app / "notes.txt").write_text("mine")
        self.assertIn("app has uncommitted or new files: notes.txt", self.auto("--plan", code=1))
        (app / "notes.txt").unlink()
        out = self.auto("--plan")
        self.assertIn("Order:    T01 (app) -> T02 (app) -> T03 (web) -> T04 (app)", out)
        self.assertIn("new feature/001/build from feature/001-refunds · pushed at the end", out)
        self.assertIn("one draft PR per repo, into feature/001-refunds. Never into dev.", out)

        out = self.auto("--start")
        self.assertIn("created feature/001/build in app", out)
        self.assertEqual(git(app, "branch", "--show-current"), "feature/001/build")
        self.assertIn("A run is going", self.auto("--start", code=2))

        # T01: built, one fix round, parked ideas, committed
        out = self.auto("--next")
        self.assertIn("Task:     T01 Money (app)", out)
        brief = (self.work / "auto" / "T01" / "brief.md").read_text()
        self.assertIn("Files you may touch: `src/contract/**`", brief)
        self.assertIn("--verify --feature 1", brief)
        self.assertEqual(features.read_front_matter(next((self.feature.path / "tasks").glob("T01-*.md")))["status"],
                         "in-progress")
        self.assertIn("start chopchop:builder with", self.auto("--status"))
        self.assertIn("wrote no report", self.auto("--review", "T01", code=2))
        money = "class Money { long cents; }\n"
        (self.work / "auto" / "T01" / "report.json").write_text(json.dumps({"task": "T01", "ok": True}))
        (app / "src" / "contract").mkdir(parents=True)
        (app / "src" / "contract" / "Money.java").write_text(money)
        self.assertIn("No check of T01", self.auto("--review", "T01", code=2))
        self.build("T01", "app", {"src/contract/Money.java": money}, commit="T01 add money contract")
        out = self.auto("--review", "T01")
        self.assertIn("Review:   T01 round 1 · 1 files", out)
        pack = (self.work / "auto" / "T01" / "review-1" / "pack.md").read_text()
        self.assertIn("Files it may touch: `src/contract/**`", pack)
        self.assertIn("+class Money { long cents; }", (self.work / "auto" / "T01" / "review-1" / "diff.patch").read_text())
        out = self.review("T01", [
            {"file": "src/contract/Money.java", "line": 1, "kind": "bug", "severity": "high", "group": "fix",
             "what": "Cents can be negative", "fix": "Refuse a negative amount."},
            {"file": "src/contract/Money.java", "kind": "approach", "severity": "medium", "group": "fix",
             "what": "Use BigDecimal instead of cents"},
            {"file": "src/other/Util.java", "kind": "naming", "severity": "low", "group": "fix", "what": "Rename Util"},
            {"file": "src/contract/Money.java", "kind": "lint", "severity": "low", "group": "stop", "what": "Missing final"},
        ])
        self.assertIn("Sorted:   2 fix, 2 park, 0 stop", out)
        fix = (self.work / "auto" / "T01" / "fix-1.md").read_text()
        self.assertIn("1. [bug, high] src/contract/Money.java:1. Cents can be negative. Fix: Refuse a negative amount.", fix)
        self.assertIn("## Parked, do not do", fix)
        self.assertIn("Use BigDecimal instead of cents", fix)
        self.assertIn("is fixing, not ready", self.auto("--commit", "T01", code=2))

        self.build("T01", "app", {"src/contract/Money.java": "final class Money { long cents; }\n"}, commit="T01 add money contract")
        self.auto("--review", "T01")
        pack = (self.work / "auto" / "T01" / "review-2" / "pack.md").read_text()
        self.assertIn("## Already parked, do not raise again", pack)
        self.assertIn("## Fixed in the last round", pack)
        self.assertIn("Next:     --commit T01", self.review("T01", []))
        out = self.auto("--commit", "T01")
        self.assertIn("Review:   2 fixed, 2 parked, 0 left", out)
        self.assertEqual(git(app, "log", "-1", "--format=%s"), "T01 add money contract")
        self.assertEqual(git(app, "status", "--porcelain"), "")

        # T02: a file outside the task, then a name the task says not to use
        self.assertIn("Task:     T02", self.auto("--next"))
        self.assertIn("T01 (app, ", (self.work / "auto" / "T02" / "brief.md").read_text())  # notes from earlier tasks
        self.build("T02", "app", {"src/api/Refund.java": "class Refund { LegacyMoney m; }\n",
                                  "src/job/Extra.java": "class Extra {}\n"})
        self.auto("--review", "T02")
        self.review("T02", [])
        self.assertIn("Outside:  T02 changed files its task does not list: src/job/Extra.java",
                      self.auto("--commit", "T02", code=1))
        (app / "src" / "job" / "Extra.java").unlink()
        out = self.auto("--commit", "T02", code=1)
        self.assertIn("Not allowed: the change uses LegacyMoney", out)
        self.build("T02", "app", {"src/api/Refund.java": "class Refund { Money m; }\n"})
        self.auto("--review", "T02")
        self.review("T02", [])
        self.auto("--commit", "T02")
        self.assertEqual(git(app, "log", "-1", "--format=%s"), "T02 Refund Api")

        # T03: the builder finds the plan cannot work, so web waits; T04 is left out by a person
        self.assertIn("Task:     T03", self.auto("--next"))
        self.assertEqual(git(web, "branch", "--show-current"), "feature/001/build")
        self.build("T03", "web", {"src/ui/Button.tsx": "x\n"}, blocked="the UI kit has no Button")
        out = self.auto("--review", "T03", code=1)
        self.assertIn("Stopped:  T03: the builder could not build it as written: the UI kit has no Button", out)
        self.assertIn("Waits:    web.", out)
        self.auto("--stop", "T04", "--why", "not in this release")
        self.assertIn("Next:     nothing left to build.", self.auto("--next"))

        out = self.auto("--finish")
        self.assertIn("app            pushed · feature/001/build (2 commits)", out)
        self.assertIn("web            not pushed: waits for T03", out)
        self.assertIn("open a draft PR from each pushed build branch into feature/001-refunds", out)
        self.assertEqual(git(self.root / "app.git", "log", "-1", "--format=%s", "feature/001/build"), "T02 Refund Api")
        body = (self.work / "auto" / "pr-app.md").read_text()
        self.assertTrue(body.startswith("# 001: refunds (app)"))
        self.assertIn("## Review ideas not done (the spec decides)", body)
        self.assertIn("T01 · [approach, medium] src/contract/Money.java. Use BigDecimal instead of cents.", body)
        self.assertIn("T01 · [naming, low] src/other/Util.java. Rename Util.", body)
        self.assertIn("- `test ! -f FAIL` passed", body)
        self.assertIn("- T04 skipped: not in this release", body)

        out = self.auto("--pr", "app", "https://git.example/app/pull/7")
        self.assertIn("T01, T02 now in review", out)
        meta = features.read_front_matter(next((self.feature.path / "tasks").glob("T02-*.md")))
        self.assertEqual((meta["status"], meta["pr"]), ("in-review", "https://git.example/app/pull/7"))
        board = (self.feature.path / "tasks" / "board.html").read_text()
        self.assertIn('"auto": {"state": "committed"', board)
        self.assertIn("Next:     a person decides on T03.", self.auto("--status"))

    def test_failing_checks_stop_the_task_and_max_limits_the_run(self):
        out = self.auto("--start", "--max", "1")
        self.assertIn("Run:      1 tasks: T01", out)
        self.auto("--next")
        self.build("T01", "app", {"src/contract/Money.java": "x\n", "FAIL": "x\n"})
        out = self.auto("--review", "T01", code=1)
        self.assertIn("the checks still fail after the builder's tries", out)
        self.assertEqual((self.repos["app"] / "FAIL").read_text(), "x\n")  # left for a person, never discarded
        self.assertIn("Next:     nothing left to build.", self.auto("--next"))
        self.assertIn("not pushed: waits for T01", self.auto("--finish"))
        self.assertIn("Next:     a person decides on T01.", self.auto("--status"))


class TaskReviewTest(Base):
    def test_review_skill_on_a_task(self):
        self.auto("--start")
        self.auto("--next")
        self.build("T01", "app", {"src/contract/Money.java": "x\n", "src/elsewhere/A.java": "y\n"})
        out = run(chopchop_review.main, self.ws, "--pack", "T01")
        self.assertIn("work/reviews/T01-r1/pack.md", out)
        folder = self.work / "reviews" / "T01-r1"
        (folder / "findings.json").write_text(json.dumps({"findings": [
            {"file": "src/elsewhere/A.java", "kind": "scope", "severity": "medium", "what": "Not part of T01",
             "fix": "Undo it."},
            {"file": "src/contract/Other.java", "kind": "bug", "severity": "low", "what": "x"}]}))
        out = run(chopchop_review.main, self.ws, "--sort", str(folder / "findings.json"))
        self.assertIn("Fix:      2  (bug 1, scope 1)", out)  # A.java is in the change, so undoing it is in scope
        self.assertIn("Park:     0", out)


if __name__ == "__main__":
    unittest.main()
