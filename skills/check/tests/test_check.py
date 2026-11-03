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

import relay_check  # noqa: E402
from relaylib.features import parse_front_matter  # noqa: E402

DESIGN = """# Refund design

## 4. Rules

### 4.1 Window

Reject refund requests older than 14 days.

### 4.2 Amounts

Amounts are decimals.

## 5. Wallet

Refunds can go to a wallet.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "_chopchop"
        self.ws.mkdir()
        (self.ws / "chopchop.yaml").write_text("team: t\nbase_branch: dev\n")
        stories = {"epic": {"id": "PAY-120", "title": "Refunds", "description": "Money back."},
                   "stories": [{"id": "PAY-121", "title": "Request a refund", "description": "As a customer...",
                                "acceptance_criteria": "- Refunds are allowed within 30 days.\n- Minimum 0.01."},
                               {"id": "PAY-122", "title": "Admin cancels", "description": "An admin can cancel.",
                                "acceptance_criteria": "Cancel works while pending.\n\nA cancelled refund sends an email."}]}
        path = self.root / "stories.json"
        path.write_text(json.dumps(stories))
        out = subprocess.run([sys.executable, str(SKILLS / "stories" / "scripts" / "relay_req.py"), "--ingest", str(path),
                              "--workspace", str(self.ws)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.feature = self.ws / "001-PAY-120-refunds"
        (self.feature / "design").mkdir()
        (self.feature / "design" / "refund-design.md").write_text(DESIGN)
        (self.feature / "design" / "SOURCES.md").write_text("ignored")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = relay_check.main(list(argv) + ["--workspace", str(self.ws)])
        self.assertEqual(got, code, "exit %s\nstdout:\n%s\nstderr:\n%s" % (got, out.getvalue(), err.getvalue()))
        return out.getvalue() + err.getvalue()

    def findings(self, findings, coverage=None, extra=None):
        data = {"findings": findings, "coverage": coverage or []}
        if extra:
            data["requirements"] = extra
        path = self.root / "findings.json"
        path.write_text(json.dumps(data))
        return str(path)


CONFLICT = {"kind": "conflict", "severity": "high", "req": "PAY-121.AC1",
            "req_quote": "Refunds are allowed within 30 days.", "design": "refund-design.md §4.1 (line 7)",
            "design_quote": "Reject refund requests older than 14 days.",
            "problem": "The story allows 30 days, the design blocks after 14.", "fix": "Use 30 days.", "ask": "BA"}
MISSING = {"kind": "missing", "severity": "high", "req": "PAY-122", "req_quote": "An admin can cancel.",
           "problem": "Nothing in the design lets an admin cancel a refund.", "ask": "design owner"}
EXTRA = {"kind": "extra", "severity": "low", "design": "refund-design.md §5 (line 15)",
         "design_quote": "Refunds can go to a wallet.", "problem": "No story asks for wallet refunds."}


class PrepareTest(Base):
    def test_prepare_lists_ids_and_headings(self):
        data = json.loads(self.cli("--prepare", "--json"))
        ids = [r["id"] for r in data["requirements"]]
        self.assertEqual(ids, ["PAY-120", "PAY-121", "PAY-121.AC1", "PAY-121.AC2", "PAY-122", "PAY-122.AC1", "PAY-122.AC2"])
        ac = next(r for r in data["requirements"] if r["id"] == "PAY-121.AC1")
        self.assertEqual(ac["text"], "Refunds are allowed within 30 days.")
        self.assertTrue(ac["source"].startswith("requirement.md:"))
        self.assertEqual(next(r for r in data["requirements"] if r["id"] == "PAY-122.AC2")["text"],
                         "A cancelled refund sends an email.")
        design = data["design"]
        self.assertEqual([Path(d["file"]).name for d in design], ["refund-design.md"])  # SOURCES.md left out
        self.assertIn({"line": 5, "level": 3, "title": "4.1 Window"}, design[0]["headings"])
        self.assertTrue(data["report"].endswith("001-PAY-120-refunds/check.md"))
        self.assertIsNone(data["previous"])

    def test_needs_inputs(self):
        self.assertIn("No design", self.cli("--prepare", "--req", str(self.feature / "requirements"), code=2))
        self.assertIn("Use --prepare or --write", self.cli(code=2))


class WriteTest(Base):
    def test_report_and_recheck(self):
        cov = [{"req": "PAY-121.AC1", "status": "partly", "design": "refund-design.md §4.1"},
               {"req": "PAY-121.AC2", "status": "covered", "design": "refund-design.md §4.2"},
               {"req": "PAY-122", "status": "missing"}]
        out = self.cli("--write", self.findings([CONFLICT, MISSING, EXTRA], cov), "1")
        self.assertIn("Result:   not ready · 1 conflict(s), 1 missing, 1 extra, 0 question(s)", out)
        self.assertIn("Coverage: 1 covered, 1 partly, 1 missing", out)
        text = (self.feature / "check.md").read_text()
        meta, body = parse_front_matter(text)
        self.assertEqual((meta["result"], meta["conflicts"]), ("not ready", 1))
        self.assertIn("**Result: not ready.** Fix 1 conflict and 1 important gap before cutting tasks.", body)
        self.assertIn("### F1 · high · PAY-121.AC1 vs refund-design.md §4.1 (line 7)", body)
        self.assertIn("**Requirement** (PAY-121.AC1):\n\n> Refunds are allowed within 30 days.", body)
        self.assertIn("**Design** (refund-design.md §4.1 (line 7)):\n\n> Reject refund requests older than 14 days.", body)
        self.assertIn("- **Ask:** BA", body)
        self.assertLess(body.index("## Conflicts"), body.index("## Missing in the design"))
        self.assertLess(body.index("## Missing in the design"), body.index("## Extra in the design"))
        self.assertIn("| PAY-122 | **missing** | - |", body)
        self.assertNotIn("(new)", body)

        # the design was fixed for the window, a question came up
        question = {"kind": "question", "severity": "medium", "req": "PAY-121.AC2", "req_quote": "Minimum 0.01.",
                    "design": "refund-design.md §4.2 (line 9)", "design_quote": "Amounts are decimals.",
                    "problem": "Is 0.01 in the account currency?", "ask": "BA"}
        out = self.cli("--write", self.findings([MISSING, question]), "1")
        self.assertIn("Since:    2 fixed, 1 new since the last check", out)
        body = (self.feature / "check.md").read_text()
        self.assertIn("## Fixed since the last check\n\n- conflict PAY-121.AC1 vs refund-design.md", body)
        self.assertIn("(new)", body)
        self.assertIn("_Open since ", body)
        self.assertIn("Fix 1 important gap", body)

    def test_ready_when_only_small_points(self):
        low = dict(MISSING, severity="low")
        self.cli("--write", self.findings([low, EXTRA]), "1")
        body = (self.feature / "check.md").read_text()
        self.assertIn("**Result: ready.** No conflicts and nothing important missing. 2 smaller points below.", body)

    def test_bad_findings(self):
        bad = [dict(CONFLICT, req="PAY-999"), dict(CONFLICT, kind="nit"), dict(MISSING, problem=""),
               {"kind": "extra", "severity": "low", "problem": "x"}, dict(MISSING, req=None)]
        out = self.cli("--write", self.findings(bad, [{"req": "PAY-121", "status": "done"}]), "1", code=2)
        for needle in ("'PAY-999' is not a known id", "kind must be one of", "'problem' is empty",
                       "an extra finding needs 'design'", "a missing finding needs 'req'", "status must be one of"):
            self.assertIn(needle, out)
        self.assertFalse((self.feature / "check.md").exists())


class AnyFilesTest(Base):
    def test_any_files_without_a_feature(self):
        brief = self.root / "brief.md"
        brief.write_text("# Brief\n\nUsers can export a CSV.\n")
        design = self.root / "spec.yaml"
        design.write_text("paths:\n  /export:\n    get: {}\n")
        data = json.loads(self.cli("--prepare", "--req", str(brief), "--design", str(design), "--json"))
        self.assertIsNone(data["feature"])
        self.assertEqual(data["requirements"], [])
        self.assertEqual(Path(data["requirement_files"][0]["file"]).name, "brief.md")
        f = self.findings([{"kind": "question", "severity": "low", "req": "R1", "req_quote": "Users can export a CSV.",
                            "design": "spec.yaml (line 2)", "problem": "Which columns go in the CSV?", "ask": "BA"}],
                          [{"req": "R1", "status": "partly", "design": "spec.yaml /export"}],
                          extra=[{"id": "R1", "text": "Users can export a CSV.", "source": "brief.md:3"}])
        printed = self.cli("--write", f, "--req", str(brief), "--design", str(design))
        self.assertIn("# Check · design vs requirements", printed)
        out = self.root / "report.md"
        self.cli("--write", f, "--req", str(brief), "--design", str(design), "--out", str(out))
        self.assertIn("**Result: ready.**", out.read_text())
        self.assertIn("'R9' is not a known id", self.cli("--write", self.findings([dict(MISSING, req="R9")], extra=[{"id": "R1"}]),
                                                         "--req", str(brief), "--design", str(design), code=2))


class SplitTest(unittest.TestCase):
    def test_split_items(self):
        self.assertEqual(relay_check.split_items("- a\n  more\n- [ ] b\n1. c"), ["a more", "b", "c"])
        self.assertEqual(relay_check.split_items("First rule.\n\nSecond\nrule."), ["First rule.", "Second rule."])


if __name__ == "__main__":
    unittest.main()
