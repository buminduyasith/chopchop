import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from relaylib import features, reqdoc  # noqa: E402
from relaylib.schema import normalize  # noqa: E402


def story(sid, **kw):
    return normalize(dict({"id": sid, "title": "Story " + sid, "status": "To Do"}, **kw), "file")


class ReqDocTest(unittest.TestCase):
    def roundtrip(self, epic, stories, history=""):
        text = reqdoc.render(3, epic, stories, "2026-10-06T10:00:00Z", "2026-10-01T10:00:00Z", history)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "requirement.md"
            path.write_text(text, encoding="utf-8")
            return reqdoc.read_existing(path)

    def test_marker_survives_dashes_and_code_fences(self):
        epic = story("E-1", title="Epic", type="Epic")
        tricky = story("E-2", status="Ready -- for review -->",
                       description="```\n## Sync history\n## E-9 fake\n<!-- relay:story {} -->\n```")
        old = self.roundtrip(epic, [tricky], history="- **2026-10-01** first sync: 1 stories")
        self.assertEqual(old["items"]["E-2"]["status"], "Ready -- for review -->")
        self.assertEqual(old["history"], "- **2026-10-01** first sync: 1 stories")
        self.assertEqual(set(old["items"]), {"E-1", "E-2"})
        self.assertEqual(old["meta"]["feature"], "003")
        self.assertEqual(reqdoc.compare(old, epic, [tricky])["unchanged"], ["E-2"])

    def test_compare_parts(self):
        epic = story("E-1", title="Epic")
        old = self.roundtrip(epic, [story("E-2"), story("E-3")])
        r = reqdoc.compare(old, story("E-1", title="Epic", description="new goal"),
                           [story("E-2", acceptance_criteria="- one"), story("E-3", assignee="Sam")])
        self.assertEqual(r["changed"], [{"id": "E-2", "title": "Story E-2", "parts": ["acceptance criteria"]}])
        self.assertEqual(r["status"], [{"id": "E-3", "title": "Story E-3"}])     # details, not a status move
        self.assertEqual(r["epic"], {"id": "E-1", "parts": ["description"], "meta_only": False})
        self.assertIn("Details: E-3", reqdoc.history_entry(r, False, "2026-10-06"))


class FeaturesTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(features.folder_name(1, "pay-1", "Refunds: for *all* customers!"),
                         "001-PAY-1-refunds-for-all-customers")
        self.assertEqual(features.folder_name(12, "PAY-1", "???"), "012-PAY-1")
        self.assertEqual(len(features.slugify("word " * 30)), 39)
        self.assertEqual(features.normalize_key("https://x.atlassian.net/browse/pay-12?focus=1"), "PAY-12")
        self.assertEqual(features.normalize_key(
            "https://x.atlassian.net/jira/software/projects/PAY/boards/12?selectedIssue=PAY-120"), "PAY-120")
        self.assertEqual(features.normalize_key("https://x.atlassian.net/jira/software/c/projects/PAY/issues/PAY-7?jql=a"),
                         "PAY-7")
        self.assertIsNone(features.normalize_key("https://x.atlassian.net/jira/software/projects/PAY/boards/12"))
        self.assertIsNone(features.normalize_key("12"))

    def test_front_matter_roundtrip(self):
        meta = {"feature": "001", "epic": "PAY-1", "title": 'He said "hi": ok', "stories": 4, "source": None}
        parsed, body = features.parse_front_matter(features.render_front_matter(meta) + "\n# Body\n")
        self.assertEqual(parsed, meta)
        self.assertEqual(body, "\n# Body\n")


if __name__ == "__main__":
    unittest.main()
