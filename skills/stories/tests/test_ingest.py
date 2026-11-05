"""End to end: stories JSON in, the real CLI, a temp workspace."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import chopchop_stories  # noqa: E402
from chopchoplib.features import parse_front_matter  # noqa: E402


def story(sid, title, desc, status="To Do", ac=None, points=None, **kw):
    out = {"id": sid, "title": title, "description": desc, "status": status, "type": "Story",
           "priority": "High", "reporter": "BA One", "labels": ["payments"], "parent": "PAY-120",
           "url": "https://tracker.example.com/browse/%s" % sid,
           "attachments": [{"name": "flow.png", "url": "http://x/flow.png", "mime": "image/png", "size": 2048}]}
    if ac is not None:
        out["acceptance_criteria"] = ac
    if points is not None:
        out["story_points"] = points
    out.update(kw)
    return out


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = chopchop_stories.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "_chopchop"
        self.ws.mkdir()
        (self.ws / "chopchop.yaml").write_text("team: t\nbase_branch: dev\n")
        self.epic = {"id": "PAY-120", "title": "Refunds for customers", "type": "Epic",
                     "description": "Let customers get money back.", "provider": "tracker-mcp"}
        self.stories = [
            story("PAY-121", "Customer can request a refund", "As a customer I want a refund.",
                  ac="Button shows for 30 days.\n\nMinimum 0.01.", points=5),
            story("PAY-122", "Agent approves refunds", "Agents approve big refunds."),
            story("PAY-123", "Refund email | receipt", "Send an email.",
                  comments=[{"author": "BA One", "created": "2026-09-17T12:40:00", "body": "A comment."}]),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *argv, expect=0):
        code, out, err = run("--workspace", str(self.ws), *argv)
        self.assertEqual(code, expect, "exit %s\nstdout:\n%s\nstderr:\n%s" % (code, out, err))
        return out, err

    def ingest(self, *extra, epic=None, stories=None, key="stories", expect=0):
        path = Path(self.tmp.name) / "stories.json"
        path.write_text(json.dumps({"epic": epic or self.epic, key: self.stories if stories is None else stories}))
        return self.cli("--ingest", str(path), *extra, expect=expect)

    def req(self, folder="001-PAY-120-refunds-for-customers"):
        return (self.ws / folder / "requirements" / "requirement.md").read_text(encoding="utf-8")

    # ------------------------------------------------------------------ create

    def test_first_ingest_creates_numbered_folder_with_one_file(self):
        out, _ = self.ingest()
        self.assertIn("001-PAY-120-refunds-for-customers  (new feature)", out)
        folder = self.ws / "001-PAY-120-refunds-for-customers"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["requirements"])
        meta, body = parse_front_matter(self.req())
        self.assertEqual((meta["feature"], meta["epic"], meta["stories"]), ("001", "PAY-120", 3))
        self.assertEqual(meta["created"], meta["synced"])
        self.assertIn("# Refunds for customers", body)
        self.assertLess(body.index("## PAY-121 Customer can request a refund"), body.index("## PAY-122 "))
        self.assertLess(body.index("## PAY-122 "), body.index("## PAY-123 "))
        self.assertIn("### Acceptance criteria\n\nButton shows for 30 days.\n\nMinimum 0.01.", body)
        self.assertIn("**Points:** 5", body)
        self.assertIn("[Open](https://tracker.example.com/browse/PAY-121)", body)
        self.assertIn("- [flow.png](http://x/flow.png) (2 KB)", body)
        self.assertIn("| PAY-123 | Refund email \\| receipt | Story | To Do | - | - |", body)
        self.assertIn("### Comments\n\n**BA One**, 2026-09-17\n\nA comment.", body)
        self.assertIn("## Sync history\n\n- **%s** first sync: 3 stories" % meta["synced"][:10], body)

    def test_issues_key_also_works_and_same_epic_updates(self):
        self.ingest(key="issues")
        out, _ = self.ingest()
        self.assertIn("001-PAY-120-refunds-for-customers  (no changes)", out)
        self.assertEqual(sorted(p.name for p in self.ws.iterdir() if p.is_dir()), ["001-PAY-120-refunds-for-customers"])

    def test_numbers_go_up_custom_name_and_odd_ids(self):
        self.ingest()
        out, _ = self.ingest("--name", "Points & Rewards", epic={"id": "LOY-1", "title": "Loyalty"}, stories=[])
        self.assertIn("002-LOY-1-points-rewards", out)
        out, _ = self.ingest("--name", "other", epic={"id": "LOY-1", "title": "Loyalty"}, stories=[])
        self.assertIn("--name ignored", out)
        out, _ = self.ingest(epic={"id": "#42", "title": "Dark mode"}, stories=[{"id": "#43", "title": "Toggle"}])
        self.assertIn("003-42-dark-mode", out)

    def test_number_skips_numbers_used_by_features_without_requirements(self):
        (self.ws / "007-old-feature" / "design").mkdir(parents=True)
        out, _ = self.ingest()
        self.assertIn("008-PAY-120-refunds-for-customers", out)

    # ------------------------------------------------------------------ resync

    def test_resync_reports_every_kind_of_change(self):
        self.ingest()
        before = self.req()
        out, _ = self.ingest()
        self.assertIn("nothing changed in the tracker", out)
        self.assertEqual(self.req(), before)
        created = parse_front_matter(before)[0]["created"]

        s = [dict(x) for x in self.stories]
        s[0]["status"] = "In Progress"
        s[1]["description"] = "Agents approve refunds over 500."
        s[1]["acceptance_criteria"] = "Over 500 needs approval."
        s[2] = story("PAY-130", "Partial refunds", "Refund part of an order.")
        out, _ = self.ingest(stories=s)
        self.assertIn("(updated)", out)
        self.assertIn("3 total · 1 added · 1 changed · 1 status/details · 1 removed · 0 unchanged", out)
        self.assertIn("Added:    PAY-130 Partial refunds", out)
        self.assertIn("Changed:  PAY-122 Agent approves refunds (description, acceptance criteria)", out)
        self.assertIn("Status:   PAY-121 Customer can request a refund (To Do to In Progress)", out)
        self.assertIn("Removed:  PAY-123 Refund email | receipt (no longer in the epic)", out)
        meta, body = parse_front_matter(self.req())
        self.assertEqual(meta["created"], created)
        history = body[body.index("## Sync history"):]
        self.assertLess(history.index("resync"), history.index("first sync"))

    def test_report_has_before_and_after_text(self):
        self.ingest()
        s = [dict(x) for x in self.stories]
        s[0]["acceptance_criteria"] = "Button shows for 14 days.\n\nMinimum 0.01."
        s[0]["status"] = "Ready"
        path = Path(self.tmp.name) / "s.json"
        path.write_text(json.dumps({"epic": self.epic, "stories": s}))
        out, _ = self.cli("--ingest", str(path), "--json")
        changed = json.loads(out)["changes"]["changed"][0]
        self.assertEqual((changed["from"], changed["to"]), ("To Do", "Ready"))
        self.assertIn("-Button shows for 30 days.", changed["diff"])
        self.assertIn("+Button shows for 14 days.", changed["diff"])
        s[1]["title"] = "Agent approves all refunds"
        out, _ = self.ingest("--diff", stories=s)
        self.assertIn("Changed:  PAY-122 Agent approves all refunds (title)\n"
                      "          @@ -1,2 +1,2 @@\n"
                      "          -## PAY-122 Agent approves refunds\n"
                      "          +## PAY-122 Agent approves all refunds", out)

    def test_dry_run_and_hand_edits(self):
        out, _ = self.ingest("--dry-run")
        self.assertIn("Dry run", out)
        self.assertFalse((self.ws / "001-PAY-120-refunds-for-customers").exists())
        self.ingest()
        path = self.ws / "001-PAY-120-refunds-for-customers" / "requirements" / "requirement.md"
        path.write_text(self.req().replace("Send an email.", "Send an email. MY NOTE"), encoding="utf-8")
        out, _ = self.ingest()
        self.assertIn("(file rewritten (no tracker changes))", out)
        self.assertNotIn("MY NOTE", self.req())

    # ------------------------------------------------------------------ resync targets, list, errors

    def test_resync_says_what_to_fetch(self):
        self.ingest()
        for ref in ([], ["1"], ["001"], ["pay-120"], ["refund"]):
            out, _ = self.cli("-rs", *ref)
            self.assertIn("Fetch:    PAY-120 Refunds for customers  (feature 001-PAY-120-refunds-for-customers", out, ref)
        data = json.loads(self.cli("-rs", "1", "--json")[0])
        self.assertEqual(data["stories"], ["PAY-121", "PAY-122", "PAY-123"])
        self.assertEqual(data["from"], "tracker-mcp")
        self.ingest(epic={"id": "LOY-1", "title": "Loyalty"}, stories=[])
        _, err = self.cli("-rs", expect=2)
        self.assertIn("Which feature?", err)
        self.assertEqual(len(json.loads(self.cli("-rs", "all", "--json")[0])), 2)

    def test_list_resolve_and_errors(self):
        self.assertIn("No features yet", self.cli("--list")[0])
        self.ingest()
        self.assertIn("001  PAY-120    001-PAY-120-refunds-for-customers ", self.cli("--list")[0])
        self.assertEqual(json.loads(self.cli("--resolve", "1")[0])["epic"], "PAY-120")
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text(json.dumps({"stories": []}))
        self.assertIn("shaped like", self.cli("--ingest", str(bad), expect=2)[1])
        bad.write_text(json.dumps({"epic": {"title": "no id"}, "stories": []}))
        self.assertIn("missing 'id'", self.cli("--ingest", str(bad), expect=2)[1])
        self.assertIn("Give --ingest", self.cli(expect=2)[1])
        self.assertIn("one of", self.cli("--list", "-rs", expect=2)[1])


if __name__ == "__main__":
    unittest.main()
