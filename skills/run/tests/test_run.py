"""The run script: what the user's words mean, where a feature stands, and approvals through the gates."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(PLUGIN / "skills" / "tasks" / "scripts"))

import chopchop_run  # noqa: E402
from chopchoplib import features, stage  # noqa: E402

SETUP = PLUGIN / "evals" / "sample-project" / "setup.py"
GROOM = PLUGIN / "skills" / "groom" / "scripts" / "chopchop_groom.py"


def run(*argv, code=0, ws=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        got = chopchop_run.main(list(argv) + ["--workspace", str(ws)])
    text = out.getvalue() + err.getvalue()
    assert got == code, "exit %s, wanted %s:\n%s" % (got, code, text)
    return text


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        out = subprocess.run([sys.executable, str(SETUP), "--to", str(Path(self.tmp.name) / "s"), "--json"],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        self.ws = Path(json.loads(out.stdout)["workspace"])
        self.feature = features.resolve(self.ws, "")

    def tearDown(self):
        self.tmp.cleanup()

    def where(self, text):
        return json.loads(run("--where", text, "--json", "--no-dashboard", ws=self.ws))


class Where(Base):
    def test_nothing_typed_and_one_feature_means_that_feature(self):
        d = self.where("")
        self.assertEqual((d["kind"], d["number"], d["stage"]), ("feature", self.feature.number, "groom"))

    def test_the_epic_key_a_link_and_the_number_find_the_feature(self):
        key = self.feature.epic
        for text in (key, key.lower(), "https://tracker.example.com/browse/%s" % key, str(self.feature.number)):
            self.assertEqual(self.where(text)["number"], self.feature.number, text)

    def test_a_new_key_or_link_is_a_new_epic(self):
        d = self.where("LOY-7")
        self.assertEqual((d["kind"], d["key"]), ("epic", "LOY-7"))
        d = self.where("https://dev.azure.com/org/proj/_workitems/edit/1234")
        self.assertEqual((d["kind"], d["key"]), ("epic", None))

    def test_a_sentence_is_an_idea_and_flags_are_kept_apart(self):
        d = self.where("let support staff add a note to any order --auto")
        self.assertEqual((d["kind"], d["text"], d["flags"]), ("idea", "let support staff add a note to any order", ["--auto"]))

    def test_a_few_words_that_name_one_feature_mean_that_feature(self):
        self.assertEqual(self.where("refunds")["number"], self.feature.number)

    def test_one_unknown_word_is_refused_with_a_hint(self):
        text = run("--where", "zebra", "--no-dashboard", ws=self.ws, code=2)
        self.assertIn("few words", text)

    def test_a_missing_number_is_an_error(self):
        self.assertIn("No feature number 9", run("--where", "9", "--no-dashboard", ws=self.ws, code=2))

    def test_lines_name_the_next_skill(self):
        text = run("--where", "", "--no-dashboard", ws=self.ws)
        self.assertIn("Kind:     feature", text)
        self.assertIn("Step:     groom (1 of 8)", text)
        self.assertIn("Next:     the groom skill with `%d`" % self.feature.number, text)

    def test_no_config_means_setup_first(self):
        with tempfile.TemporaryDirectory() as d:
            text = run("--where", "an idea to build something new", ws=Path(d) / "_chopchop")
            self.assertIn("Kind:     setup", text)

    def test_two_features_and_nothing_typed_gives_the_list(self):
        out = subprocess.run([sys.executable, str(GROOM), "--idea", "let support add a note to an order",
                              "--workspace", str(self.ws)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        d = self.where("")
        self.assertEqual((d["kind"], len(d["features"])), ("list", 2))
        self.assertIn("Features: 2", run("--list", ws=self.ws))


class Gates(Base):
    def groom(self, *argv, code=0):
        out = subprocess.run([sys.executable, str(GROOM)] + list(argv) + ["--workspace", str(self.ws)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, code, out.stdout + out.stderr)
        return out.stdout

    def brief_ready(self):
        f = Path(self.tmp.name) / "f.json"
        f.write_text(json.dumps({"stories": [], "questions": [], "summary": ["All fits."]}), encoding="utf-8")
        self.groom("--findings", str(f))
        self.groom("--brief", code=1)
        from chopchoplib.requirements import requirement_items
        stories = [r["id"] for r in requirement_items(self.feature.file) if r["kind"] == "story"]
        p = self.feature.path / "requirements" / "brief.md"
        text = p.read_text(encoding="utf-8")
        for head, body in (("Summary", "- Customers can ask for a refund."), ("What we build", "A refund request."),
                           ("In scope", "\n".join("- %s as written." % s for s in stories)),
                           ("Out of scope", "None."), ("Rules", "- A refund needs a reason.")):
            text = text.replace("## %s\n" % head, "## %s\n\n%s\n" % (head, body), 1)
        p.write_text(text, encoding="utf-8")
        self.groom("--brief")

    def test_the_brief_gate_names_the_approve_call_and_approve_moves_on(self):
        self.brief_ready()
        text = run("--where", "", "--no-dashboard", ws=self.ws)
        self.assertIn("Waiting:  on you.", text)
        self.assertIn("--approve %d brief --by" % self.feature.number, text)
        text = run("--approve", str(self.feature.number), "brief", "--by", "Asha", ws=self.ws)
        self.assertIn("approved by Asha", text)
        self.assertIn("Design", text)
        self.assertEqual(stage.read(self.feature)["stage"], "design")

    def test_approve_needs_a_name_and_a_known_document(self):
        self.assertIn("Who approves", run("--approve", "1", "brief", ws=self.ws, code=2))
        self.assertIn("brief, design, spec", run("--approve", "1", "tasks", "--by", "A", ws=self.ws, code=2))

    def test_approving_a_brief_that_is_not_ready_fails(self):
        text = run("--approve", str(self.feature.number), "brief", "--by", "Asha", ws=self.ws, code=2)
        self.assertIn("No brief.md yet", text)


if __name__ == "__main__":
    unittest.main()
