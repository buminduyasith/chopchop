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

import relay_tasks  # noqa: E402
from relaylib import features, tasks  # noqa: E402
from relaylib.config import load_config  # noqa: E402


def task_text(tid, slug, repo="api", wave=1, deps=(), touches=("src/x/**",), size="M", status="todo",
              done="- [ ] Unit test `does_the_thing`: it works."):
    meta = {"id": tid, "title": slug.replace("-", " ").title(), "repo": repo, "wave": wave, "size": size,
            "status": status, "owner": None, "depends_on": list(deps), "touches": list(touches),
            "stories": [], "pr": None}
    body = ("# %s\n\n## Goal\n\nIt works.\n\n## Context\n\n> From the design.\n\n## Done when\n\n%s\n\n"
            "## Branch\n\n_Written by Relay._\n" % (tid, done))
    return features.render_front_matter(meta) + body


def git(path, *args):
    subprocess.run(["git"] + list(args), cwd=str(path), check=True, capture_output=True, text=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "_relay"
        self.design = self.root / "docs" / "design.md"
        self.design.parent.mkdir()
        self.design.write_text("# Refunds design\n\nA refund can be full or partial.\n")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = relay_tasks.main(list(argv) + ["--workspace", str(self.ws)])
        self.assertEqual(got, code, "exit %s\nstdout:\n%s\nstderr:\n%s" % (got, out.getvalue(), err.getvalue()))
        return out.getvalue() + err.getvalue()

    def init(self, base="dev", repos=("api=.",)):
        self.cli("--init", "--base", base)
        for r in repos:
            self.cli("--repo", r)

    def new_feature(self, name="refunds"):
        self.cli("--new", str(self.design), "--name", name)
        return self.ws / ("001-%s" % name) / "tasks"

    def write(self, tdir, *items):
        for tid, slug, kw in items:
            (tdir / ("%s-%s.md" % (tid, slug))).write_text(task_text(tid, slug, **kw))


class ConfigTest(Base):
    def test_init_saves_base_and_repos(self):
        self.init(repos=("api=../payments-api", "web=../payments-web"))
        self.cli("--repo", "api=../api-v2")
        cfg = load_config(self.ws)
        self.assertEqual(cfg["base_branch"], "dev")
        self.assertEqual(cfg["repos"], {self.root.name: ".", "api": "../api-v2", "web": "../payments-web"})
        self.cli("--base", "develop")
        self.assertEqual(load_config(self.ws)["base_branch"], "develop")

    def test_init_with_repos_drops_the_guess(self):
        self.cli("--init", "--base", "dev", "--repo", "api=../api")
        self.assertEqual(load_config(self.ws)["repos"], {"api": "../api"})

    def test_long_form_repo(self):
        self.cli("--init", "--base", "dev")
        cfg = self.ws / "relay.yaml"
        cfg.write_text(cfg.read_text().replace("repos:\n", "repos:\n  web:\n    path: ../web\n"))
        self.assertEqual(relay_tasks.repos_of(load_config(self.ws), self.ws)[0]["web"], "../web")
        self.assertIn("by hand", self.cli("--repo", "web=../x", code=2))

    def test_bad_repo_arg(self):
        self.cli("--init")
        self.assertIn("name=path", self.cli("--repo", "nopath", code=2))


class NewTest(Base):
    def test_new_feature_copies_design(self):
        spec = self.root / "spec"
        (spec / "api").mkdir(parents=True)
        (spec / "api" / "refunds.yaml").write_text("openapi: 3.0.0\n")
        (spec / ".hidden").write_text("skip me")
        out = self.cli("--new", str(self.design), str(spec), "--name", "Refunds for customers")
        self.assertIn("001-refunds-for-customers (new)", out)
        self.assertIn("Base:     NOT SET", out)
        f = self.ws / "001-refunds-for-customers"
        self.assertEqual((f / "design" / "design.md").read_text(), self.design.read_text())
        self.assertTrue((f / "design" / "api" / "refunds.yaml").is_file())
        self.assertFalse((f / "design" / ".hidden").exists())
        sources = features.read_front_matter(f / "design" / "SOURCES.md")["files"]
        self.assertEqual([s["file"] for s in sources], ["api/refunds.yaml", "design.md"])
        for name in ("plan.md", "status.md", "board.html", "changelog.md"):
            self.assertTrue((f / "tasks" / name).is_file(), name)
        self.assertEqual(features.read_front_matter(f / "tasks" / "plan.md")["title"], "Refunds for customers")

    def test_rerun_reports_unchanged_and_changed(self):
        self.new_feature()
        self.assertIn("design.md (unchanged)", self.cli("--new", str(self.design), "--feature", "1"))
        self.design.write_text("# Refunds design\n\nNow 14 days.\n")
        self.assertIn("design.md (changed)", self.cli("--new", str(self.design), "--feature", "1"))
        self.assertIn("14 days", (self.ws / "001-refunds" / "design" / "design.md").read_text())

    def test_new_needs_feature_or_name(self):
        self.assertIn("--name", self.cli("--new", str(self.design), code=2))

    def test_name_clash_between_inputs(self):
        other = self.root / "other"
        other.mkdir()
        (other / "design.md").write_text("x")
        self.assertIn("both be copied", self.cli("--new", str(self.design), str(other / "design.md"),
                                                 "--name", "x", code=2))

    def test_epic_without_requirement_is_remembered(self):
        self.cli("--new", str(self.design), "--name", "refunds", "--epic", "pay-120")
        f = features.find_by_epic(self.ws, "PAY-120")
        self.assertEqual(f.name, "001-PAY-120-refunds")
        self.assertEqual(tasks.feature_branch_name(f), "feature/PAY-120-refunds")
        self.assertIn("already has a folder", self.cli("--new", str(self.design), "--name", "again",
                                                       "--epic", "PAY-120", code=2))

    def test_numbers_follow_existing_features(self):
        (self.ws / "004-PAY-1-old" / "requirements").mkdir(parents=True)
        self.assertIn("005-next", self.cli("--new", str(self.design), "--name", "next"))


class CheckTest(Base):
    def setUp(self):
        super().setUp()
        self.init(repos=("api=.", "web=../web"))
        self.tdir = self.new_feature()

    def good(self):
        self.write(self.tdir,
                   ("T01", "contracts", {"wave": 0, "touches": ["src/contract/**"], "size": "S"}),
                   ("T02", "refund-api", {"deps": ["T01"], "touches": ["src/refunds/api/**"]}),
                   ("T03", "refund-ui", {"repo": "web", "deps": ["T01"], "touches": ["src/refunds/api/**"]}))

    def test_good_plan_passes_and_fills_branch(self):
        self.good()
        out = self.cli("--check", "1")
        self.assertIn("Result:   OK", out)
        body = (self.tdir / "T02-refund-api.md").read_text()
        self.assertIn("Run `/relay-tasks --branch` first", body)
        plan = (self.tdir / "plan.md").read_text()
        self.assertIn("T01 --> T02", plan)
        self.assertIn("| 1 | [T02](T02-refund-api.md) |", plan)

    def test_errors(self):
        self.good()
        self.write(self.tdir,
                   ("T04", "two-repos", {"repo": "api,web", "deps": ["T01"], "touches": ["a/**"]}),
                   ("T05", "same-wave-dep", {"deps": ["T02"], "touches": ["b/**"]}),
                   ("T06", "unknown-dep", {"deps": ["T99"], "touches": ["c/**"]}),
                   ("T07", "clash", {"deps": ["T01"], "touches": ["src/refunds/api/Controller.java"]}),
                   ("T08", "too-big", {"size": "L", "deps": ["T01"], "touches": ["d/**"]}),
                   ("T09", "no-test", {"deps": ["T01"], "touches": ["e/**"], "done": "- [ ] It builds."}),
                   ("T10", "bad-repo", {"repo": "mobile", "touches": ["f/**"]}))
        out = self.cli("--check", "1", code=1)
        for needle in ("T04: a task works in one repo only",
                       "T05 (wave 1) depends on T02 (wave 1)",
                       "T06: depends on T99, which does not exist",
                       "T02 and T07 are both in wave 1 and both touch",
                       "T08: size 'L' is too big",
                       "T09: '## Done when' needs at least one",
                       "T10: repo 'mobile' is not in relay.yaml repos"):
            self.assertIn(needle, out)
        self.assertNotIn("T03 and", out)  # same paths, but another repo

    def test_missing_section_and_bad_name(self):
        (self.tdir / "T01-x.md").write_text(features.render_front_matter(
            {"id": "T01", "title": "x", "repo": "api", "wave": 0, "size": "M", "status": "todo",
             "depends_on": [], "touches": ["x/**"]}) + "# T01\n")
        (self.tdir / "Tfoo.md").write_text("no front matter")
        out = self.cli("--check", "1", code=1)
        self.assertIn("T01: missing section ## Goal, ## Done when", out)
        self.assertIn("## Branch", (self.tdir / "T01-x.md").read_text())  # the script adds it
        self.assertIn("Tfoo.md: file name must look like", out)

    def test_tiny_task_warns(self):
        self.write(self.tdir, ("T01", "enum", {"wave": 0, "size": "S", "touches": ["src/Status.java"]}))
        self.assertIn("Fold it into the task that uses it", self.cli("--check", "1"))

    def test_no_tasks_is_an_error(self):
        self.assertIn("No task files yet", self.cli("--check", "1", code=1))


class BranchTest(Base):
    def setUp(self):
        super().setUp()
        self.remote = self.root / "remote.git"
        self.repo = self.root / "app"
        git(self.root, "init", "--bare", "-q", str(self.remote))
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "dev")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "start")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-q", "origin", "dev")
        self.init(repos=("app=%s" % self.repo,))
        self.tdir = self.new_feature()
        self.write(self.tdir, ("T01", "contracts", {"repo": "app", "wave": 0, "touches": ["src/**"]}))

    def remote_branches(self):
        out = subprocess.run(["git", "ls-remote", "--heads", str(self.remote)], capture_output=True, text=True)
        return sorted(line.split("refs/heads/")[1] for line in out.stdout.splitlines())

    def test_suggest_then_create(self):
        out = self.cli("--branch", "1")
        self.assertIn("Branch:   feature/001-refunds (from dev)", out)
        self.assertIn("planned", out)
        self.assertEqual(self.remote_branches(), ["dev"])

        out = self.cli("--branch", "1", "--create")
        self.assertIn("created", out)
        self.assertEqual(self.remote_branches(), ["dev", "feature/001-refunds"])
        current = subprocess.run(["git", "branch", "--show-current"], cwd=str(self.repo),
                                 capture_output=True, text=True).stdout.strip()
        self.assertEqual(current, "dev")  # never checks out

        body = (self.tdir / "T01-contracts.md").read_text()
        self.assertIn("git checkout -b feature/001/T01-contracts origin/feature/001-refunds", body)
        self.assertIn("Open the PR into `feature/001-refunds`", body)
        self.assertIn("cd %s" % self.repo, body)
        plan = features.read_front_matter(self.tdir / "plan.md")
        self.assertEqual(plan["feature_branch"], "feature/001-refunds")
        self.assertEqual(plan["branch_repos"], ["app"])

        self.assertIn("exists", self.cli("--branch", "1", "--create"))
        self.assertIn("does not rename", self.cli("--branch", "1", "--branch-name", "feature/other", code=2))

    def test_refuses_protected_names(self):
        self.assertIn("protected", self.cli("--branch", "1", "--create", "--branch-name", "dev", code=2))
        self.assertIn("prefix", self.cli("--branch", "1", "--create", "--branch-name", "refunds", code=2))
        self.assertEqual(self.remote_branches(), ["dev"])

    def test_needs_base_branch(self):
        cfg = self.ws / "relay.yaml"
        cfg.write_text(cfg.read_text().replace("base_branch: dev", "base_branch:"))
        self.assertIn("Base branch is not set", self.cli("--branch", "1", code=2))


class StatusTest(Base):
    def setUp(self):
        super().setUp()
        self.init()
        self.tdir = self.new_feature()
        self.write(self.tdir,
                   ("T01", "contracts", {"wave": 0, "touches": ["src/contract/**"]}),
                   ("T02", "refund-api", {"deps": ["T01"], "touches": ["src/api/**"]}))
        (self.tdir / "changelog.md").write_text(
            (self.tdir / "changelog.md").read_text() +
            "\n## C-001 · T01 · 2026-10-28\nChange: amounts are cents.\nWhy: exact values.\nAffects: T02\n")

    def board_data(self):
        html = (self.tdir / "board.html").read_text()
        start = html.index('<script id="relay-data" type="application/json">') + len(
            '<script id="relay-data" type="application/json">')
        return json.loads(html[start:html.index("</script>", start)])

    def test_status_writes_board_and_markdown(self):
        out = self.cli("--status", "1")
        self.assertIn("Todo:        T01, T02 (waiting on T01)", out)
        data = self.board_data()
        self.assertEqual([t["id"] for t in data["tasks"]], ["T01", "T02"])
        self.assertEqual(data["tasks"][1]["waiting_on"], ["T01"])
        self.assertEqual(data["tasks"][1]["changes"], ["C-001"])
        self.assertEqual(data["changelog"][0]["affects"], ["T02"])
        self.assertIn("Todo **2**", (self.tdir / "status.md").read_text())

    def test_set_moves_a_task(self):
        out = self.cli("--set", "t01", "done", "--feature", "1", "--owner", "dev-a", "--pr", "https://x/pr/1")
        self.assertIn("T01 Contracts: todo -> done", out)
        meta = features.read_front_matter(self.tdir / "T01-contracts.md")
        self.assertEqual((meta["status"], meta["owner"], meta["pr"]), ("done", "dev-a", "https://x/pr/1"))
        self.assertEqual(self.board_data()["tasks"][1]["waiting_on"], [])
        self.assertIn("## Done\n\n| Task |", (self.tdir / "status.md").read_text())

    def test_set_rejects_unknown_status_and_task(self):
        self.assertIn("Status must be one of", self.cli("--set", "T01", "blocked", code=2))
        self.assertIn("No task T09", self.cli("--set", "T09", "done", code=2))

    def test_board_data_cannot_close_the_script_tag(self):
        p = self.tdir / "T01-contracts.md"
        p.write_text(p.read_text().replace("It works.", "Watch out for </script><b>x</b>."))
        self.cli("--status", "1")
        html = (self.tdir / "board.html").read_text()
        self.assertEqual(html.count("</script>"), 2)
        self.assertIn("</script><b>x</b>", self.board_data()["tasks"][0]["body"])

    def test_list(self):
        self.assertIn("001  -          001-refunds", self.cli("--list"))


class SectionTest(unittest.TestCase):
    def test_replace_section_keeps_the_rest(self):
        body = "# T\n\n## Goal\n\nA\n\n## Branch\n\nold\n\n## Do not change\n\nB\n"
        out = tasks.replace_section(body, "Branch", "new")
        self.assertEqual(out, "# T\n\n## Goal\n\nA\n\n## Branch\n\nnew\n\n## Do not change\n\nB\n")
        self.assertEqual(tasks.replace_section("# T\n", "Branch", "new"), "# T\n\n## Branch\n\nnew\n")

    def test_paths_overlap(self):
        self.assertTrue(tasks.paths_overlap("src/refunds/**", "src/refunds/api/X.java"))
        self.assertTrue(tasks.paths_overlap("./a/b.py", "a/b.py"))
        self.assertFalse(tasks.paths_overlap("src/**/refunds/api/**", "src/**/refunds/RefundService.*"))


class SharedCopyTest(unittest.TestCase):
    def test_shared_modules_match_relay_requirements(self):
        other = HERE.parents[1] / "relay-requirements" / "scripts" / "relaylib"
        if not other.is_dir():
            self.skipTest("relay-requirements is not next to this skill")
        for name in ("config.py", "features.py"):
            mine = (HERE.parent / "scripts" / "relaylib" / name).read_text()
            self.assertEqual(mine, (other / name).read_text(), "%s differs from relay-requirements" % name)


if __name__ == "__main__":
    unittest.main()
