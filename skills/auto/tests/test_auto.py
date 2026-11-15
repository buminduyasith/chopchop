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
from chopchoplib import events, features, plain  # noqa: E402


def git(path, *args):
    out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), out.stderr))
    return out.stdout.strip()


def task_text(tid, slug, repo, wave=1, deps=(), touches=(), do_not=""):
    meta = {"id": tid, "title": slug.replace("-", " ").title(), "repo": repo, "wave": wave, "size": "S",
            "status": "todo", "owner": None, "depends_on": list(deps), "touches": list(touches),
            "stories": ["PAY-121"], "pr": None}
    if "LegacyMoney" in do_not:
        meta["forbid"] = ["LegacyMoney"]
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

    def whole_task(self, tid, repo, files):
        """Pick, build, review with no findings, commit. Returns what --commit printed."""
        self.assertIn("Task:     %s" % tid, self.auto("--next"))
        self.build(tid, repo, files)
        self.auto("--review", tid)
        self.review(tid, [])
        return self.auto("--commit", tid)

    def kinds(self):
        return [e["kind"] for e in events.read(self.feature)]


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
        self.assertIn("- Do not use these names: `LegacyMoney`. New code must not use them", brief)  # from the task's forbid
        self.assertIn("A name is still fine as an object key and in a comment.", brief)
        self.assertEqual(plain.summary_points(brief)[:3], ["What: build task T01, Money, and nothing else.",
                                                           "Where: app, on branch feature/001/build",
                                                           "Do not use: LegacyMoney"])
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
        self.assertTrue(plain.has_summary(pack))
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
        self.assertEqual(plain.summary_points(fix)[0], "What: 2 things to fix in T01, inside the task's files.")
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
        self.build("T02", "app", {"src/api/Refund.java": "// LegacyMoney is the old type\nclass Refund {\n"
                                                         "  Map a = Map.of(LegacyMoney: 1);\n  LegacyMoney m;\n}\n",
                                  "src/job/Extra.java": "class Extra {}\n"})
        self.auto("--review", "T02")
        self.review("T02", [])
        self.assertIn("Outside:  T02 changed files its task does not list: src/job/Extra.java",
                      self.auto("--commit", "T02", code=1))
        (app / "src" / "job" / "Extra.java").unlink()
        out = self.auto("--commit", "T02", code=1)
        self.assertIn("Not allowed: the change uses LegacyMoney, which the task says not to use, at src/api/Refund.java:4. "
                      "Object keys and comments are allowed.", out)
        fix = (self.work / "auto" / "T02" / "fix-not-allowed.md").read_text()
        self.assertIn("1. [scope, medium] src/api/Refund.java:4. This line uses `LegacyMoney`, which the task says not "
                      "to use: `LegacyMoney m;`.", fix)  # only the real use: not the comment on line 1, not the key on line 3
        self.assertNotIn("Refund.java:1", fix)
        self.assertNotIn("Refund.java:3", fix)
        self.assertIn("A forbidden name is still allowed as an object key (`{ LegacyMoney: 1 }`) and in a comment", fix)
        self.build("T02", "app", {"src/api/Refund.java": "class Refund { Money m; }\n"})
        self.auto("--review", "T02")
        self.review("T02", [])
        self.auto("--commit", "T02")
        self.assertEqual(git(app, "log", "-1", "--format=%s"), "T02 Refund Api")

        # T03: the builder finds the plan cannot work, so web waits; T04 is left out by a person
        self.assertIn("Task:     T03", self.auto("--next"))
        self.assertEqual(git(web, "branch", "--show-current"), "feature/001/build")
        self.assertNotIn("Do not use", (self.work / "auto" / "T03" / "brief.md").read_text())  # T03 forbids nothing
        self.build("T03", "web", {"src/ui/Button.tsx": "x\n"}, blocked="the UI kit has no Button")
        out = self.auto("--review", "T03", code=1)
        self.assertIn("Stopped:  T03: the builder could not build it as written: the UI kit has no Button", out)
        self.assertIn("Waits:    web.", out)
        self.assertIn("Retry:    when a person has decided to go on: --retry T03", out)
        self.auto("--stop", "T04", "--why", "not in this release")
        self.assertIn("Next:     nothing left to build.", self.auto("--next"))

        out = self.auto("--finish")
        self.assertIn("app            pushed, back on dev · feature/001/build (2 commits)", out)
        self.assertEqual(git(app, "branch", "--show-current"), "dev")
        self.assertIn("web            not pushed: waits for T03", out)
        self.assertIn("open a draft PR from each pushed build branch into feature/001-refunds", out)
        self.assertEqual(git(self.root / "app.git", "log", "-1", "--format=%s", "feature/001/build"), "T02 Refund Api")
        body = (self.work / "auto" / "pr-app.md").read_text()
        self.assertTrue(body.startswith("# 001: refunds (app)"))
        self.assertEqual(plain.summary_points(body)[:3], ["What: 2 tasks of refunds, in app.", "Tasks: T01, T02",
                                                          "Review: 3 fixed, 2 parked for the lead, 0 left for a person"])
        self.assertIn("## Review ideas not done (the spec decides)", body)
        self.assertIn("T01 · [approach, medium] src/contract/Money.java. Use BigDecimal instead of cents.", body)
        self.assertIn("T01 · [naming, low] src/other/Util.java. Rename Util.", body)
        self.assertIn("- `test ! -f FAIL` passed", body)
        self.assertIn("- T04 skipped: not in this release", body)

        out = self.auto("--pr", "app", "https://git.example/app/pull/7")
        self.assertIn("T01, T02 now in review", out)
        meta = features.read_front_matter(next((self.feature.path / "tasks").glob("T02-*.md")))
        self.assertEqual((meta["status"], meta["pr"]), ("in-review", "https://git.example/app/pull/7"))
        status = (self.feature.path / "tasks" / "status.md").read_text()  # status.md shows the run, in Markdown
        self.assertIn("| committed `%s` |" % self.state()["tasks"]["T02"]["commit"], status)
        self.assertIn("| stopped: the builder could not build it as written: the UI kit has no Button |", status)
        self.assertFalse((self.feature.path / "tasks" / "board.html").exists())
        self.assertIn("Next:     a person decides on T03. Then --retry T03 to go on, or plan a new run.", self.auto("--status"))
        # the activity log has one line for each thing a person would ask about
        log = events.read(self.feature)
        for kind in ("run", "build", "review", "fix", "commit", "stop", "push", "pr"):
            self.assertIn(kind, [e["kind"] for e in log], kind)
        commit = next(e for e in log if e["kind"] == "commit")
        self.assertEqual((commit["task"], commit["repo"]), ("T01", "app"))
        self.assertIn("T01 committed %s on feature/001/build" % self.state()["tasks"]["T01"]["commit"], commit["text"])
        self.assertIn("T01 review round 1 sorted: 2 fix, 2 park, 0 stop.", [e["text"] for e in log])
        self.assertIn("T03 stopped: the builder could not build it as written: the UI kit has no Button",
                      [e["text"] for e in log])

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


class RetryTest(Base):
    def test_a_stopped_task_starts_again_and_its_repo_goes_on(self):
        self.auto("--start", "--repo", "app")  # T01, T02, T04
        self.auto("--next")
        self.build("T01", "app", {"src/contract/Money.java": "class Money {}\n"}, blocked="the task forbids a name it needs")
        self.auto("--review", "T01", code=1)
        # before the fix there was no way back: the stopped task refused every step
        out = self.auto("--commit", "T01", code=2)
        self.assertIn("T01 is stopped: the builder could not build it as written: the task forbids a name it needs. "
                      "When a person has decided to go on, start it again with --retry T01.", out)
        self.assertIn("--retry T01", self.auto("--review", "T01", code=2))
        self.assertIn("Next:     nothing left to build.", self.auto("--next"))
        st = self.state()
        self.assertEqual([st["tasks"][x]["state"] for x in ("T01", "T02", "T04")], ["stopped", "skipped", "skipped"])
        self.assertEqual(st["tasks"]["T02"]["because"], "T01")
        self.assertIn("not pushed: waits for T01", self.auto("--finish"))
        self.assertIn("T02 is skipped, not stopped", self.auto("--retry", "T02", code=2))

        out = self.auto("--retry", "T01", "--why", "The name is fine as an object key.")
        self.assertIn("Retry:    T01 goes on. Its work is still in app, on feature/001/build.", out)
        self.assertIn("Back:     T02, T04 queued again, they only waited for T01", out)
        self.assertIn("then --review T01", out)
        st = self.state()
        t = st["tasks"]["T01"]
        self.assertEqual((t["state"], st["current"], st["repos"]["app"]["paused"], st["finished"]), ("fixing", "T01", None, None))
        self.assertNotIn("why", t)
        self.assertNotIn("ended", t)
        self.assertEqual([st["tasks"][x]["state"] for x in ("T02", "T04")], ["queued", "queued"])
        note = Path(t["fix"]).read_text()
        self.assertEqual(Path(t["fix"]).name, "retry-1.md")
        self.assertIn("- **It stopped because:** the builder could not build it as written: the task forbids a name it needs", note)
        self.assertIn("- **The person says:** The name is fine as an object key.", note)
        report = json.loads((self.work / "auto" / "T01" / "report.json").read_text())
        self.assertEqual((report["blocked"], report["ok"]), (None, True))  # no hand edit of the report needed
        self.assertTrue((self.work / "auto" / "T01" / "report-stop-1.json").is_file())
        self.assertIn("retry-1.md to the builder, then --review T01", self.auto("--status"))
        # the check must run again after the retry, then the task goes through review and commit as usual
        self.assertIn("No check of T01 since it was built", self.auto("--review", "T01", code=2))
        self.build("T01", "app", {"src/contract/Money.java": "final class Money {}\n"})
        self.auto("--review", "T01")
        pack = (self.work / "auto" / "T01" / "review-1" / "pack.md").read_text()
        self.assertIn("## Decided by a person, do not raise again", pack)
        self.assertIn("A person decided: The name is fine as an object key.", pack)
        self.review("T01", [])
        self.assertIn("Next:     --next", self.auto("--commit", "T01"))
        self.assertIn("Task:     T02", self.auto("--next"))
        log = events.read(self.feature)
        self.assertIn("T01 retried: a person decided to go on. It had stopped because: the builder could not build it as "
                      "written: the task forbids a name it needs", [e["text"] for e in log if e["kind"] == "run"])

    def test_nothing_built_goes_back_to_the_queue(self):
        self.auto("--start", "--max", "1")
        self.auto("--next")
        self.build("T01", "app", {})  # the builder wrote a report and changed nothing
        self.assertIn("the builder changed nothing", self.auto("--review", "T01", code=1))
        out = self.auto("--retry", "T01")
        self.assertIn("Retry:    T01 is back in the queue. Nothing was built, so it starts again.", out)
        self.assertIn("Next:     --next", out)
        st = self.state()
        self.assertEqual((st["tasks"]["T01"]["state"], st["current"], st["repos"]["app"]["paused"]), ("queued", None, None))
        self.assertFalse((self.work / "auto" / "T01" / "report.json").exists())  # the old report is not read as the new one
        self.assertIn("Task:     T01", self.auto("--next"))

    def test_retry_waits_for_the_task_that_is_running(self):
        self.auto("--start")
        self.auto("--next")
        self.build("T01", "app", {"src/contract/Money.java": "x\n"}, blocked="no")
        self.auto("--review", "T01", code=1)
        self.assertIn("Task:     T03", self.auto("--next"))  # the other repo goes on
        self.assertIn("T03 is still building. Finish it or --stop it first, then --retry T01.", self.auto("--retry", "T01", code=2))
        self.assertEqual(self.state()["tasks"]["T01"]["state"], "stopped")

    def test_a_commit_clears_a_pause_that_points_at_its_task(self):
        self.auto("--start", "--max", "1")
        self.auto("--next")
        self.build("T01", "app", {"src/contract/Money.java": "class Money {}\n"})
        self.auto("--review", "T01")
        self.review("T01", [])
        st = self.state()  # what the trial left behind after a hand edit: the task goes on, the repo still waits
        st["repos"]["app"]["paused"] = {"task": "T01", "why": "an old stop"}
        (self.work / "auto.json").write_text(json.dumps(st))
        self.auto("--commit", "T01")
        self.assertIsNone(self.state()["repos"]["app"]["paused"])
        self.assertIn("app            pushed", self.auto("--finish"))  # it said "not pushed: waits for T01" before


class WaveTest(Base):
    def test_pause_after_the_last_task_of_a_wave(self):
        out = self.auto("--plan", "--wave")
        self.assertIn("Pause:    after each wave, the run waits for a go", out)
        self.auto("--start", "--wave")
        self.assertTrue(self.state()["options"]["wave"])
        self.assertEqual(self.state()["tasks"]["T04"]["wave"], 2)
        self.assertIn("pause after each wave", self.auto("--status"))
        out = self.whole_task("T01", "app", {"src/contract/Money.java": "class Money {}\n"})
        self.assertIn("Pause:    wave 0 is done (T01 committed). Show the user what it built and wait for a go. "
                      "To go on: --next", out)
        out = self.whole_task("T02", "app", {"src/api/Refund.java": "class Refund {}\n"})
        self.assertNotIn("Pause:", out)  # T03 is in wave 1 too, and still waits
        out = self.whole_task("T03", "web", {"src/ui/Button.tsx": "x\n"})
        self.assertIn("Pause:    wave 1 is done (T02, T03 committed).", out)
        out = self.whole_task("T04", "app", {"src/job/Job.java": "class Job {}\n"})
        self.assertNotIn("Pause:", out)  # the last task of the run: nothing waits, so it goes on to --finish
        self.assertIn("Next:     --finish", out)

    def test_the_config_turns_it_on_and_step_still_works(self):
        cfg = self.ws / "chopchop.yaml"
        cfg.write_text(cfg.read_text() + "auto:\n  pause: wave\n")
        self.assertIn("Pause:    after each wave", self.auto("--plan"))
        self.assertIn("Pause:    after each task", self.auto("--plan", "--step"))
        self.auto("--start", "--max", "2")
        self.assertEqual((self.state()["options"]["wave"], self.state()["options"]["step"]), (True, False))
        self.assertIn("Pause:    wave 0 is done (T01 committed)", self.whole_task("T01", "app", {"src/contract/M.java": "x\n"}))
        self.auto("--start", "--new", "--step", "--only", "T03")
        self.assertEqual((self.state()["options"]["wave"], self.state()["options"]["step"]), (False, True))
        self.assertIn("Pause:    --step is on. Show the user what T03 did", self.whole_task("T03", "web", {"src/ui/B.tsx": "x\n"}))


class PackTest(Base):
    def test_risks_and_assumptions_have_their_own_headings(self):
        (self.feature.path / "design" / "design.md").write_text(
            "# Design\n\n## 9. Impact and rollout\n\nNone.\n\n## 10. Risks\n\n| Risk | What we do |\n| --- | --- |\n"
            "| Two refunds race | One open refund per payment |\n\n## 11. How we prove it\n\nNone.\n")
        (self.feature.path / "design" / "flow.json").write_text(json.dumps({"participants": ["a", "b"], "messages": [
            {"n": 1, "from": "a", "to": "b", "kind": "call", "say": "cancels", "line": "x",
             "failure": {"fails": "409.", "slow": "5 s.", "twice": "Nothing.",
                         "caller": {"risk": "Any support agent can cancel.", "accepted_by": "Asha"}}}]}))
        (self.feature.path / "spec").mkdir()
        (self.feature.path / "spec" / "spec.json").write_text(json.dumps({"assumptions": ["Refunds are in EUR only."]}))
        self.auto("--start", "--max", "1")
        self.auto("--next")
        self.build("T01", "app", {"src/contract/Money.java": "class Money {}\n"})
        self.auto("--review", "T01")
        pack = (self.work / "auto" / "T01" / "review-1" / "pack.md").read_text()
        self.assertIn("## Risks the design already lists, do not raise", pack)
        self.assertIn("- Design risk: Two refunds race: One open refund per payment", pack)  # the design's own table
        self.assertIn("- Flow message 1, caller: Accepted risk: Any support agent can cancel. (by Asha)", pack)
        self.assertIn("## Spec assumptions, do not raise as new", pack)
        self.assertIn("Guesses the spec made, for a person to confirm. Nobody has accepted them yet.", pack)
        self.assertIn("- Refunds are in EUR only.", pack)
        self.assertNotIn("accepted by the lead", pack)  # a guess is not an approval
        self.assertLess(pack.index("- Design risk:"), pack.index("## Spec assumptions"))


class SubjectTest(unittest.TestCase):
    def test_keeps_the_repo_commit_style(self):
        f = chopchop_auto.task_subject
        self.assertEqual(f("T01", "feat(orders): add refund status"), "feat(orders): add refund status (T01)")
        self.assertEqual(f("T01", "T01 feat(orders): add refund status"), "feat(orders): add refund status (T01)")
        self.assertEqual(f("T01", "add refund status"), "T01 add refund status")
        self.assertEqual(f("T01", "T01 add refund status"), "T01 add refund status")


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
