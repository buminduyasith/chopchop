import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import relay_code  # noqa: E402  (puts tasks' scripts on the path too)
import relay_tasks  # noqa: E402
from codelib import changes, profile  # noqa: E402
from relaylib import features  # noqa: E402

def git(path, *args):
    out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), out.stderr))
    return out.stdout.strip()


def task_text(tid, slug, wave=1, deps=(), touches=("src/x/**",), status="todo"):
    meta = {"id": tid, "title": slug.replace("-", " ").title(), "repo": "app", "wave": wave, "size": "M",
            "status": status, "owner": None, "depends_on": list(deps), "touches": list(touches),
            "stories": ["PAY-121"], "pr": None}
    return features.render_front_matter(meta) + (
        "# %s\n\n## Goal\n\nIt works.\n\n## Context\n\n> From the design.\n\n## Done when\n\n"
        "- [ ] Unit test `does_the_thing`: it works.\n\n## Branch\n\n_Written by chopchop._\n" % tid)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "_chopchop"
        self.remote = self.root / "remote.git"
        self.repo = self.root / "app"
        git(self.root, "init", "--bare", "-q", str(self.remote))
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "dev")
        git(self.repo, "config", "user.name", "dev-a")
        git(self.repo, "config", "user.email", "a@acme.test")
        (self.repo / "README.md").write_text("app\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "start")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-q", "origin", "dev")

        self.ws.mkdir()
        (self.ws / "chopchop.yaml").write_text("team: t\nbase_branch: dev\nrepos:\n  app:\n    path: %s\n" % self.repo)
        design = self.root / "design.md"
        design.write_text("# Design\n")
        self.tasks_cli("--new", str(design), "--name", "refunds")
        self.tdir = self.ws / "001-refunds" / "tasks"
        (self.tdir / "T01-contracts.md").write_text(task_text("T01", "contracts", wave=0, touches=["src/contract/**"]))
        (self.tdir / "T02-refund-api.md").write_text(task_text("T02", "refund-api", deps=["T01"], touches=["src/api/**"]))
        (self.tdir / "T03-ledger.md").write_text(task_text("T03", "ledger", deps=["T01"], touches=["src/ledger/**"]))
        self.tasks_cli("--branch", "1", "--create")

    def tearDown(self):
        self.tmp.cleanup()

    def tasks_cli(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = relay_tasks.main(list(argv) + ["--workspace", str(self.ws)])
        self.assertEqual(code, 0, err.getvalue())

    def cli(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = relay_code.main(list(argv) + ["--workspace", str(self.ws)])
        self.assertEqual(got, code, "exit %s\nstdout:\n%s\nstderr:\n%s" % (got, out.getvalue(), err.getvalue()))
        return out.getvalue() + err.getvalue()

    def meta(self, tid):
        return features.read_front_matter(next(self.tdir.glob("%s-*.md" % tid)))

    def commit_file(self, name, text, msg="T01 work"):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        git(self.repo, "add", name)
        git(self.repo, "commit", "-q", "-m", msg)

    def write_profile(self, **cmds):
        p = profile.path_for(self.ws, "app")
        p.parent.mkdir(parents=True, exist_ok=True)
        meta = {"repo": "app", "confirmed": True}
        meta.update(cmds)
        p.write_text(features.render_front_matter(meta) + "# How to work in app\n")


# --------------------------------------------------------------------------- start


class StartTest(Base):
    def test_ready_lists_startable_and_waiting(self):
        out = self.cli("--ready")
        self.assertIn("Ready to start:\n  T01", out)
        self.assertIn("waiting on T01", out)
        self.assertIn("app", out)

    def test_preview_changes_nothing(self):
        out = self.cli("T02")
        self.assertIn("Blocked:  Waiting on T01", out)
        out = self.cli("T01", "-p")
        self.assertIn("Start:    will create feature/001/T01-contracts and set status in-progress", out)
        self.assertIn("Warning:  No profile for app yet", out)
        self.assertEqual(self.meta("T01")["status"], "todo")
        self.assertEqual(git(self.repo, "branch", "--show-current"), "dev")

    def test_start_claims_and_branches(self):
        out = self.cli("T01", "--start")
        self.assertIn("Branch:   created feature/001/T01-contracts", out)
        self.assertIn("Status:   todo -> in-progress, owner dev-a", out)
        self.assertEqual(git(self.repo, "branch", "--show-current"), "feature/001/T01-contracts")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), git(self.repo, "rev-parse", "origin/feature/001-refunds"))
        meta = self.meta("T01")
        self.assertEqual((meta["status"], meta["owner"]), ("in-progress", "dev-a"))
        self.assertIn("In progress **1**", (self.tdir / "status.md").read_text())
        self.assertIn("already on", self.cli("T01", "--start"))

    def test_start_blockers(self):
        self.assertIn("Waiting on T01", self.cli("T02", "--start", code=2))
        self.assertIn("created", self.cli("T02", "--start", "--force"))
        git(self.repo, "checkout", "-q", "dev")
        (self.repo / "README.md").write_text("changed\n")
        self.assertIn("uncommitted changes", self.cli("T03", "--start", "--force", code=2))

    def test_owned_by_someone_else(self):
        p = next(self.tdir.glob("T01-*.md"))
        p.write_text(p.read_text().replace("owner: null", 'owner: "dev-b"'))
        self.assertIn("owned by dev-b", self.cli("T01", "--start", code=2))
        self.assertIn("owner dev-a", self.cli("T01", "--start", "--take"))

    def test_resume_merges_new_feature_commits_and_stops_on_conflict(self):
        self.cli("T01", "--start")
        self.commit_file("src/contract/a.txt", "mine\n")
        other = self.root / "other"
        git(self.root, "clone", "-q", "-b", "feature/001-refunds", str(self.remote), str(other))
        git(other, "config", "user.name", "x")
        git(other, "config", "user.email", "x@x")
        (other / "NEW.md").write_text("from T02\n")
        git(other, "add", ".")
        git(other, "commit", "-q", "-m", "other task")
        git(other, "push", "-q", "origin", "feature/001-refunds")
        self.assertIn("Merged:   the latest feature/001-refunds", self.cli("T01", "--start"))
        self.assertTrue((self.repo / "NEW.md").exists())

        (other / "src" / "contract").mkdir(parents=True)
        (other / "src" / "contract" / "a.txt").write_text("theirs\n")
        git(other, "add", ".")
        git(other, "commit", "-q", "-m", "clash")
        git(other, "push", "-q", "origin", "feature/001-refunds")
        out = self.cli("T01", "--start", code=2)
        self.assertIn("conflicts in: src/contract/a.txt", out)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertFalse((self.repo / ".git" / "MERGE_HEAD").exists())


# --------------------------------------------------------------------------- verify, log, done


class WorkTest(Base):
    def test_verify(self):
        self.assertIn("No profile for app", self.cli("T01", "--verify", code=2))
        self.write_profile(lint="true", test="echo all good")
        out = self.cli("T01", "--verify")
        self.assertIn("lint   PASS", out)
        self.assertIn("Result:   all passed", out)
        self.write_profile(lint="true", test="echo boom >&2; exit 3")
        out = self.cli("T01", "--verify", code=1)
        self.assertIn("test   FAIL", out)
        self.assertIn("boom", out)

    def test_verify_skips_after_build_fails(self):
        self.write_profile(build="exit 1", test="true")
        self.assertIn("skipped (build failed)", self.cli("T01", "--verify", code=1))

    def test_log_passes_changes_on(self):
        self.cli("T02", "--start", "--force")
        out = self.cli("T01", "--log", "--change", "Amounts are cents.", "--why", "exact values")
        self.assertIn("Logged:   C-001", out)
        self.assertIn("Tell:     T02 is in-progress (owner dev-a)", out)
        self.assertIn("Updated:  T03", out)
        t3 = next(self.tdir.glob("T03-*.md")).read_text()
        self.assertIn("## Heads-up\n\n- C-001 from T01", t3)
        self.assertLess(t3.index("## Heads-up"), t3.index("## Branch"))
        self.cli("T01", "--log", "--change", "Status gets PARTIAL", "--affects", "T03")
        log = (self.tdir / "changelog.md").read_text()
        log = log[log.index("-->"):]  # skip the format example at the top
        self.assertLess(log.index("## C-002"), log.index("## C-001"))
        self.assertIn("Affects: T02, T03", log)
        t3 = next(self.tdir.glob("T03-*.md")).read_text()
        self.assertEqual(t3.count("## Heads-up"), 1)
        self.assertIn("C-002 from T01", t3)
        self.assertIn("Unknown task", self.cli("T01", "--log", "--change", "x", "--affects", "T99", code=2))

    def test_done_is_manual_and_unblocks(self):
        out = self.cli("--done", "T01")
        self.assertIn("T01 Contracts: todo -> done", out)
        self.assertIn("Ready:    T02, T03 can start now", out)
        self.assertEqual(self.meta("T01")["status"], "done")


# --------------------------------------------------------------------------- style


class StyleTest(Base):
    def set_style(self, value):
        (self.ws / "chopchop.yaml").write_text(
            "team: t\nbase_branch: dev\nrepos:\n  app:\n    path: %s\n    style: %s\n" % (self.repo, value))

    def test_no_style_follows_the_code(self):
        self.assertIn("Style:    not set in chopchop.yaml. Follow the code", self.cli("T01", "-p"))

    def test_style_file_is_shown_and_must_exist(self):
        self.set_style("docs/code-style.md")
        out = self.cli("T01", "-p")
        self.assertIn("Blocked:  Style file docs/code-style.md from chopchop.yaml (repos.app.style) is not in the repo", out)
        self.assertIn("Style file", self.cli("T01", "--start", code=2))
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "code-style.md").write_text("# Style\n")
        out = self.cli("T01", "-p")
        self.assertIn("Style:    docs/code-style.md (from chopchop.yaml, always follow it)", out)
        self.assertNotIn("Blocked:", out)

    def test_style_list_with_absolute_path(self):
        shared = self.root / "team-style.md"
        shared.write_text("# Team\n")
        (self.repo / "STYLE.md").write_text("# Repo\n")
        self.set_style("[STYLE.md, %s]" % shared)
        import json as _json
        ctx = _json.loads(self.cli("T01", "-p", "--json"))
        self.assertEqual([s["file"] for s in ctx["style"]], ["STYLE.md", str(shared)])
        self.assertTrue(all(s["exists"] for s in ctx["style"]))


# --------------------------------------------------------------------------- profile, setup, parsing


class ProfileTest(Base):
    def test_draft_and_confirm(self):
        (self.repo / "package.json").write_text(json.dumps({"scripts": {"test": "jest", "lint": "eslint .", "build": "tsc"}}))
        (self.repo / "yarn.lock").write_text("")
        (self.repo / "CLAUDE.md").write_text("rules\n")
        (self.repo / "bitbucket-pipelines.yml").write_text(
            "pipelines:\n  default:\n    - step:\n        script:\n          - yarn install\n          - yarn test\n"
            "    - step:\n        script:\n          - yarn lint\n")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "a.test.ts").write_text("")
        out = self.cli("--profile", "app")
        self.assertIn("Drafted:", out)
        self.assertIn("test:     yarn test", out)
        self.assertIn("lint:     yarn run lint", out)
        text = profile.path_for(self.ws, "app").read_text()
        self.assertIn("- `yarn install` (bitbucket-pipelines.yml)", text)
        self.assertIn("- `yarn lint` (bitbucket-pipelines.yml)", text)
        self.assertIn("- `CLAUDE.md`", text)
        self.assertIn("- `src/a.test.ts`", text)
        self.assertIn("pr: null", text)
        self.assertIn("## Pull requests", text)
        out = self.cli("T01", "-p")
        self.assertIn("DRAFT", out)
        self.assertIn("PRs:      not set in the profile", out)
        self.cli("--profile", "app", "--confirm")
        text = profile.path_for(self.ws, "app").read_text()
        self.assertIn("confirmed: true", text)
        self.assertNotIn("Draft written", text)
        self.assertIn("(confirmed)", self.cli("--profile", "app"))

    def test_detect_other_stacks(self):
        d = self.root / "gradle"
        d.mkdir()
        (d / "build.gradle.kts").write_text('plugins { id("com.diffplug.spotless") }\n')
        (d / "gradlew").write_text("")
        (d / ".github" / "workflows").mkdir(parents=True)
        (d / ".github" / "workflows" / "ci.yml").write_text(
            "jobs:\n  t:\n    steps:\n      - run: ./gradlew check\n      - run: |\n          echo a\n          echo b\n")
        found = profile.detect(d)
        self.assertEqual(found["commands"], {"test": "./gradlew test", "lint": "./gradlew spotlessCheck",
                                             "build": "./gradlew assemble"})
        self.assertEqual([c["command"] for c in found["ci"]], ["./gradlew check", "echo a", "echo b"])
        g = self.root / "go"
        g.mkdir()
        (g / "go.mod").write_text("module x\n")
        (g / "Makefile").write_text("test:\n\tgo test ./...\n")
        self.assertEqual(profile.detect(g)["commands"]["test"], "make test")


class UnitTest(unittest.TestCase):
    def test_next_change_id(self):
        self.assertEqual(changes.next_change_id([]), "C-001")
        self.assertEqual(changes.next_change_id([{"id": "C-009"}, {"id": "C-002"}]), "C-010")


if __name__ == "__main__":
    unittest.main()
