import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "scripts"))

import chopchop_init  # noqa: E402  (puts tasks' scripts on the path too)
from chopchoplib.config import load_config, parse_yaml  # noqa: E402

sys.path.insert(0, str(SKILLS / "code" / "scripts"))


def git(path, *args):
    out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), out.stderr))
    return out.stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.api = self.make_repo("payments-api", branches=("dev", "main"))
        self.web = self.make_repo("payments-web", branches=("main",))
        (self.api / "docs").mkdir()
        (self.api / "docs" / "code-style.md").write_text("# Style\n")
        (self.api / "CLAUDE.md").write_text("rules\n")
        (self.root / "notes").mkdir()  # not a repo
        self.cwd = os.getcwd()
        os.chdir(str(self.api))

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def make_repo(self, name, branches=("main",)):
        remote = self.root / "remotes" / (name + ".git")
        remote.parent.mkdir(exist_ok=True)
        git(self.root, "init", "--bare", "-q", str(remote))
        repo = self.root / name
        repo.mkdir()
        git(repo, "init", "-q", "-b", branches[0])
        git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "start")
        git(repo, "remote", "add", "origin", str(remote))
        for b in branches:
            if b != branches[0]:
                git(repo, "branch", b)
            git(repo, "push", "-q", "origin", b)
        git(repo, "fetch", "-q", "origin")
        return repo

    def cli(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = chopchop_init.main(list(argv))
        self.assertEqual(got, code, "exit %s\nstdout:\n%s\nstderr:\n%s" % (got, out.getvalue(), err.getvalue()))
        return out.getvalue() + err.getvalue()

    def answers(self, **kw):
        data = {"workspace": str(self.root / "_chopchop"), "team": "payments", "base_branch": "dev",
                "repos": [{"name": "payments-api", "path": str(self.api), "style": ["docs/code-style.md"]},
                          {"name": "payments-web", "path": str(self.web), "style": []}]}
        data.update(kw)
        path = self.root / "answers.json"
        path.write_text(json.dumps(data))
        return str(path)


class DetectTest(Base):
    def test_detect_finds_repos_branches_and_styles(self):
        data = json.loads(self.cli("--detect", "--json"))
        self.assertEqual([r["name"] for r in data["repos"]], ["payments-api", "payments-web"])
        api = data["repos"][0]
        self.assertEqual(api["base_candidates"], ["dev", "main"])
        self.assertEqual(api["style_files"], ["docs/code-style.md"])
        self.assertEqual(api["guides"], ["CLAUDE.md"])
        self.assertEqual(data["suggested_base"], "dev")
        self.assertEqual(data["suggested_team"], "payments-api")
        self.assertEqual([o["path"] for o in data["workspace_options"]],
                         [str(self.api / "_chopchop"), str(self.root / "_chopchop")])
        self.assertIsNone(data["existing_config"])

    def test_detect_sees_existing_config(self):
        self.cli("--write", self.answers())
        data = json.loads(self.cli("--detect", "--json"))
        self.assertEqual(data["existing_workspace"], str(self.root / "_chopchop"))
        self.assertEqual(data["existing_config"]["base_branch"], "dev")


class WriteTest(Base):
    def test_write_shared_workspace(self):
        out = self.cli("--write", self.answers())
        self.assertIn("Wrote:", out)
        ws = self.root / "_chopchop"
        cfg = load_config(ws)
        self.assertEqual(cfg["base_branch"], "dev")
        self.assertEqual(cfg["team"], "payments")
        self.assertEqual(cfg["repos"]["payments-api"], {"path": "payments-api", "style": "docs/code-style.md"})
        self.assertEqual(cfg["repos"]["payments-web"], "payments-web")
        self.assertNotIn("tracker", cfg)
        self.assertEqual(cfg["branches"]["feature"], "feature/{key}-{slug}")
        self.assertFalse((self.api / ".gitignore").exists())  # _chopchop is not inside a repo

        import chopchop_tasks
        import chopchop_code
        self.assertEqual(chopchop_tasks.repos_of(cfg, ws)[0], {"payments-api": "payments-api", "payments-web": "payments-web"})
        styles = chopchop_code.style_files(self.api, cfg["repos"]["payments-api"], ws)
        self.assertTrue(styles[0]["exists"])

    def test_write_inside_repo_ignores_it(self):
        self.cli("--write", self.answers(workspace=str(self.api / "_chopchop")))
        self.assertIn("_chopchop/", (self.api / ".gitignore").read_text())
        cfg = load_config(self.api / "_chopchop")
        self.assertEqual(cfg["repos"]["payments-api"]["path"], ".")
        self.assertEqual(cfg["repos"]["payments-web"], "../payments-web")
        self.assertNotIn("tracker", cfg)

    def test_rerun_keeps_extras_and_backs_up(self):
        ws = self.root / "_chopchop"
        ws.mkdir()
        (ws / "chopchop.yaml").write_text(
            "team: old\nbase_branch: main\nrepos:\n  payments-api: payments-api\n"
            "branches:\n  feature: \"feat/{key}\"\n  task: \"feat/{key}/{task}\"\n"
            "freshen:\n  run_tests: true\n  token: ${SOME_TOKEN}\n")
        self.cli("--write", self.answers())
        self.assertIn("team: old", (ws / "chopchop.yaml.bak").read_text())
        cfg = parse_yaml((ws / "chopchop.yaml").read_text())
        self.assertEqual(cfg["base_branch"], "dev")
        self.assertEqual(cfg["branches"], {"feature": "feat/{key}", "task": "feat/{key}/{task}", "build": "feature/{key}/build"})
        self.assertEqual(cfg["freshen"], {"run_tests": True, "token": "${SOME_TOKEN}"})

    def test_helper_settings_written_and_kept(self):
        self.cli("--write", self.answers(agents={"max": 2, "model": "sonnet", "effort": "high"}))
        cfg = load_config(self.root / "_chopchop")
        self.assertEqual(cfg["agents"], {"max": 2, "model": "sonnet", "effort": "high"})
        self.cli("--write", self.answers())  # a rerun without the question keeps them
        cfg = load_config(self.root / "_chopchop")
        self.assertEqual(cfg["agents"]["max"], 2)
        self.assertEqual((self.root / "_chopchop" / "chopchop.yaml").read_text().count("agents:"), 1)
        self.assertIn("model must be one of", self.cli("--write", self.answers(agents={"model": "gpt-9"}), code=2))

    def test_bad_answers(self):
        bad_style = self.answers(repos=[{"name": "payments-web", "path": str(self.web), "style": ["nope.md"]}])
        self.assertIn("Style file(s) not found: payments-web: nope.md", self.cli("--write", bad_style, code=2))
        self.assertIn("not a git repo", self.cli("--write", self.answers(
            repos=[{"name": "notes", "path": str(self.root / "notes")}]), code=2))
        self.assertIn("used twice", self.cli("--write", self.answers(
            repos=[{"name": "a", "path": str(self.api)}, {"name": "a", "path": str(self.web)}]), code=2))
        self.assertIn("may only use", self.cli("--write", self.answers(
            repos=[{"name": "a b", "path": str(self.api)}]), code=2))
        self.assertIn("base_branch", self.cli("--write", self.answers(base_branch=""), code=2))
        self.assertIn("must be called _chopchop", self.cli("--write", self.answers(workspace=str(self.root / "x")), code=2))
        self.assertFalse((self.root / "_chopchop" / "chopchop.yaml").exists())


class StyleTest(Base):
    def test_skeleton_then_use_it(self):
        (self.web / "src").mkdir()
        (self.web / "src" / "App.tsx").write_text("")
        (self.web / "src" / "util.ts").write_text("")
        (self.web / ".prettierrc").write_text("{}")
        ws = self.root / "_chopchop"
        out = self.cli("--style-skeleton", "payments-web", "--repo-path", str(self.web), "--workspace", str(ws))
        self.assertIn("style: styles/payments-web.md", out)
        text = (ws / "styles" / "payments-web.md").read_text()
        self.assertIn("**Languages:** TypeScript", text)
        self.assertIn("Prettier", text)
        self.assertIn("## Naming", text)
        self.assertIn("exists", self.cli("--style-skeleton", "payments-web", "--repo-path", str(self.web),
                                         "--workspace", str(ws), code=2))
        self.cli("--write", self.answers(repos=[{"name": "payments-web", "path": str(self.web),
                                                 "style": "styles/payments-web.md"}]))
        cfg = load_config(ws)
        self.assertEqual(cfg["repos"]["payments-web"]["style"], "styles/payments-web.md")
        import chopchop_code
        self.assertTrue(chopchop_code.style_files(self.web, cfg["repos"]["payments-web"], ws)[0]["exists"])


class PluginTest(unittest.TestCase):
    def test_manifest_and_skills(self):
        root = SKILLS.parent
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(manifest["name"], "chopchop")
        self.assertEqual(market["plugins"][0]["name"], manifest["name"])
        self.assertEqual(market["plugins"][0]["source"], "./")
        names = sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))
        self.assertEqual(names, ["auto", "check", "code", "design", "diagram", "init", "learn", "review", "spec", "stories", "tasks", "update"])
        for name in names:
            text = (SKILLS / name / "SKILL.md").read_text()
            self.assertTrue(text.startswith("---\nname: %s\n" % name), name)
            self.assertNotIn("python3 scripts/", text, name)  # paths go through ${CLAUDE_SKILL_DIR}
            self.assertNotIn("\u2014", text, name)  # no em-dashes
        agents = sorted(p.stem for p in (root / "agents").glob("*.md"))
        self.assertEqual(agents, ["architect", "builder", "code-reviewer", "explorer", "reviewer"])
        for name in agents:
            text = (root / "agents" / (name + ".md")).read_text()
            self.assertTrue(text.startswith("---\nname: %s\ndescription: " % name), name)
            self.assertNotIn("Agent", text.split("---")[1], name)  # helpers never start helpers
            self.assertNotIn("\u2014", text, name)


if __name__ == "__main__":
    unittest.main()
