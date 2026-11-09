"""The review script in a plain git repo, with no chopchop workspace, and the sort rules."""

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

import chopchop_review  # noqa: E402  (puts the tasks scripts on the path)
from chopchoplib import review  # noqa: E402


def git(path, *args):
    out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), out.stderr))
    return out.stdout


def run(*argv, code=0):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        got = chopchop_review.main(list(argv))
    text = out.getvalue() + err.getvalue()
    assert got == code, "exit %s, wanted %s:\n%s" % (got, code, text)
    return text


class PlainRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "shop"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "dev")
        git(self.repo, "config", "user.email", "dev@acme.test")
        (self.repo / ".gitignore").write_text("build/\n")
        (self.repo / "CLAUDE.md").write_text("Use tabs.\n")
        (self.repo / "app.py").write_text("def total(xs):\n    return sum(xs)\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "start")

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_changes_then_sort_then_round_two(self):
        self.assertIn("Nothing to review", run("--pack", "--repo", str(self.repo), code=1))
        (self.repo / "app.py").write_text("def total(xs):\n    return sum(xs) + 1\n")
        (self.repo / "new dir").mkdir()
        (self.repo / "new dir" / "tax.py").write_text("RATE = 0.2\n")
        (self.repo / "build").mkdir()
        (self.repo / "build" / "out.txt").write_text("ignored\n")
        out = run("--pack", "--repo", str(self.repo))
        self.assertIn("(2 files,", out)
        folder = self.repo / ".git" / "chopchop-review" / "r1"
        diff = (folder / "diff.patch").read_text()
        self.assertIn("+    return sum(xs) + 1", diff)
        self.assertIn("+RATE = 0.2", diff)            # a new file is in the review
        self.assertNotIn("ignored", diff)
        pack = (folder / "pack.md").read_text()
        self.assertIn("pending changes (not committed)", pack)
        self.assertIn("CLAUDE.md", pack)
        self.assertIn("- new    `new dir/tax.py`", pack)
        self.assertNotIn("chopchop-review", git(self.repo, "status", "--porcelain"))  # kept inside .git

        (folder / "findings.json").write_text(json.dumps({"findings": [
            {"file": "app.py", "line": 2, "kind": "bug", "severity": "high", "what": "Adds 1 to every total",
             "fix": "Return sum(xs)."},
            {"file": "app.py", "kind": "library", "severity": "low", "group": "fix", "what": "Use numpy"},
            {"file": "new dir/tax.py", "kind": "approach", "severity": "high", "group": "stop",
             "what": "Tax must come from the tax service"},
            {"kind": "bug"}]}))
        out = run("--sort", str(folder / "findings.json"), code=1)
        self.assertIn("Fix:      1  (bug 1)", out)
        self.assertIn("Park:     1  (library 1)", out)
        self.assertIn("Stop:     1  (approach 1)", out)
        self.assertIn("finding 4 has no 'what'", out)
        self.assertTrue((folder / "sorted.json").is_file())

        run("--pack", "--repo", str(self.repo))
        pack2 = (self.repo / ".git" / "chopchop-review" / "r2" / "pack.md").read_text()
        self.assertIn("round 2", pack2)
        self.assertIn("- [library, low] app.py. Use numpy.", pack2)
        self.assertIn("- [bug, high] app.py:2. Adds 1 to every total. Fix: Return sum(xs).", pack2)

    def test_branch_against_its_base(self):
        git(self.repo, "checkout", "-q", "-b", "feature/tax")
        (self.repo / "tax.py").write_text("RATE = 0.2\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "tax")
        out = run("--pack", "--branch", "main", "--repo", str(self.repo))
        self.assertIn("(1 files,", out)
        pack = (self.repo / ".git" / "chopchop-review" / "r1" / "pack.md").read_text()
        self.assertIn("this branch against main", pack)
        self.assertIn("- new    `tax.py`", pack)

    def test_needs_one_action(self):
        self.assertIn("Use --pack or --sort", run(code=2))


class SortRulesTest(unittest.TestCase):
    RULES = {"touches": ["src/refunds/**"], "banned_paths": ["src/legacy/**"], "banned_names": ["ProblemDetail"]}

    def test_the_guard(self):
        found = [
            {"file": "src/refunds/A.java", "kind": "bug", "what": "a"},                         # fix
            {"file": "src/orders/B.java", "kind": "naming", "what": "b"},                       # outside: park
            {"file": "src/legacy/C.java", "kind": "bug", "what": "c"},                          # do not change: park
            {"file": "src/orders/D.java", "kind": "scope", "what": "d"},                        # in the change: fix
            {"file": "src/refunds/A.java", "kind": "contract", "what": "e"},                    # direction: park
            {"file": "src/refunds/A.java", "kind": "security", "severity": "high", "group": "stop", "what": "f"},
            {"file": "src/refunds/A.java", "kind": "rule", "severity": "high", "group": "stop", "what": "g"},
        ]
        out = review.sort(found, self.RULES, changed=["src/orders/D.java"])
        self.assertEqual([i["what"] for i in out["fix"]], ["a", "d"])
        self.assertEqual([(i["what"], i["reason"]) for i in out["park"]], [
            ("b", "src/orders/B.java is outside the task's files"),
            ("c", "the task says do not change src/legacy/C.java"),
            ("e", "a different direction from the spec")])
        self.assertEqual([i["what"] for i in out["stop"]], ["f", "g"])

    def test_banned_names_and_outside_files(self):
        diff = "+++ b/x\n+return ProblemDetail.of(422);\n-ProblemDetailOld\n+ProblemDetails x;\n"
        self.assertEqual(review.banned_uses(diff, self.RULES), ["ProblemDetail"])
        self.assertEqual(review.banned_uses("+ProblemDetails x;\n", self.RULES), [])
        self.assertEqual(review.outside(["src/refunds/A.java", "src/x.java", "ok.md"], self.RULES, ["ok.md"]),
                         ["src/x.java"])


if __name__ == "__main__":
    unittest.main()
