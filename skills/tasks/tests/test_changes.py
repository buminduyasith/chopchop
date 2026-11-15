"""The spec's file changes: merged per repo, drawn as a folder tree."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from chopchoplib import changes  # noqa: E402

SPEC = {"packages": [
    {"id": "P1", "repo": "api", "files": [
        {"path": "src/models/order.js", "change": "change", "what": "the refund block"},
        {"path": "src/refunds/refundService.js", "change": "new", "what": "the service"},
        {"path": "test/refunds/refundService.test.js", "change": "new", "what": "its tests"}]},
    {"id": "P2", "repo": "api", "files": [
        {"path": "src/models/order.js", "change": "change", "what": "the status list"},
        {"path": "src/refunds/refundService.js", "change": "change", "what": "one more method"},
        {"path": "src/utils/orderHelpers.js", "change": "delete", "what": "the old helper"}]},
    {"id": "P3", "repo": "web", "files": [
        {"path": "src/main/java/pay/web/RefundPage.java", "change": "new", "what": "the page"}]}]}


class Collect(unittest.TestCase):
    def test_files_are_merged_per_repo(self):
        c = changes.collect(SPEC, [{"id": "T01", "repo": "api", "package": "P1", "touches": []},
                                   {"id": "T02", "repo": "api", "package": "P2", "touches": []}])
        self.assertEqual([r["repo"] for r in c["repos"]], ["api", "web"])
        api = {f["path"]: f for f in c["repos"][0]["files"]}
        self.assertEqual(len(api), 4)                      # order.js shows once
        order = api["src/models/order.js"]
        self.assertEqual((order["change"], order["packages"], order["tasks"]), ("change", ["P1", "P2"], ["T01", "T02"]))
        self.assertEqual(order["what"], ["the refund block", "the status list"])
        self.assertEqual(api["src/refunds/refundService.js"]["change"], "new")   # new, then changed, is still new
        self.assertEqual(api["src/utils/orderHelpers.js"]["change"], "delete")
        self.assertTrue(api["test/refunds/refundService.test.js"]["test"])
        self.assertEqual(c["counts"], {"new": 3, "change": 1, "delete": 1})
        self.assertEqual(c["total"], 5)

    def test_tree_marks_and_compact_folders(self):
        c = changes.collect(SPEC)
        api = "\n".join(changes.tree_lines(c["repos"][0]["files"]))
        self.assertIn("orderHelpers.js", api)
        self.assertRegex(api, r"orderHelpers\.js\s+D  P2")
        self.assertEqual(changes.sentence("findAll filters"), "findAll filters.")   # a code name keeps its case
        self.assertEqual(changes.sentence("two new actions"), "Two new actions.")
        self.assertRegex(api, r"refundService\.js\s+A  P1 P2")
        web = "\n".join(changes.tree_lines(c["repos"][1]["files"]))
        self.assertIn("src/main/java/pay/web/", web)    # a chain of single folders is one line

    def test_render_has_a_tree_per_repo_and_no_code(self):
        md = changes.render(changes.collect(SPEC))
        self.assertTrue(md.startswith("**In short:** 5 files in 2 repos: 3 new, 1 changed, 1 deleted."))
        self.assertIn("### api", md)
        self.assertIn("### web", md)
        self.assertIn("- `src/`\n  - `models/`\n    - `order.js` **changed**: The refund block. The status list. _(P1, P2)_", md)
        self.assertIn("    - ~~`orderHelpers.js`~~ **deleted**: The old helper. _(P2)_", md)
        self.assertIn("- `src/main/java/pay/web/`", md)
        self.assertNotIn("```", md)
        self.assertEqual(changes.render(changes.collect({"packages": []})), "None.")


if __name__ == "__main__":
    unittest.main()
