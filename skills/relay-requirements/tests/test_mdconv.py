import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from relaylib.mdconv import adf_to_md, demote_headings, wiki_to_md  # noqa: E402


def text(t, *marks, href=None):
    node = {"type": "text", "text": t}
    if marks or href:
        node["marks"] = [{"type": m} for m in marks]
        if href:
            node["marks"].append({"type": "link", "attrs": {"href": href}})
    return node


def para(*nodes):
    return {"type": "paragraph", "content": list(nodes)}


class AdfTest(unittest.TestCase):
    def test_paragraph_marks_and_link(self):
        doc = {"type": "doc", "content": [para(text("Refund "), text("must", "strong"), text(" be "),
                                               text("fast ", "em"), text("docs", href="https://x.io"))]}
        self.assertEqual(adf_to_md(doc), "Refund **must** be *fast* [docs](https://x.io)")

    def test_heading_lists_nested(self):
        doc = {"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [text("Acceptance Criteria")]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [para(text("First")), {"type": "orderedList", "content": [
                    {"type": "listItem", "content": [para(text("Sub one"))]},
                    {"type": "listItem", "content": [para(text("Sub two"))]}]}]},
                {"type": "listItem", "content": [para(text("Second"))]}]}]}
        self.assertEqual(adf_to_md(doc), "## Acceptance Criteria\n\n- First\n  1. Sub one\n  2. Sub two\n- Second")

    def test_table_code_panel_tasks_mention(self):
        doc = {"type": "doc", "content": [
            {"type": "table", "content": [
                {"type": "tableRow", "content": [
                    {"type": "tableHeader", "content": [para(text("Case"))]},
                    {"type": "tableHeader", "content": [para(text("Result"))]}]},
                {"type": "tableRow", "content": [
                    {"type": "tableCell", "content": [para(text("a|b"))]},
                    {"type": "tableCell", "content": [para(text("ok"))]}]}]},
            {"type": "codeBlock", "attrs": {"language": "json"}, "content": [text('{"a": 1}')]},
            {"type": "panel", "attrs": {"panelType": "warning"}, "content": [para(text("Careful"))]},
            {"type": "taskList", "content": [
                {"type": "taskItem", "attrs": {"state": "DONE"}, "content": [text("Done thing")]},
                {"type": "taskItem", "attrs": {"state": "TODO"}, "content": [text("Open thing")]}]},
            para({"type": "mention", "attrs": {"text": "@Ann"}}, text(" please check")),
            {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"alt": "flow.png", "type": "file"}}]},
        ]}
        md = adf_to_md(doc)
        self.assertIn("| Case | Result |\n| --- | --- |\n| a\\|b | ok |", md)
        self.assertIn('```json\n{"a": 1}\n```', md)
        self.assertIn("> **Warning:** Careful", md)
        self.assertIn("- [x] Done thing\n- [ ] Open thing", md)
        self.assertIn("@Ann please check", md)
        self.assertIn("[attachment: flow.png]", md)

    def test_empty(self):
        self.assertEqual(adf_to_md(None), "")
        self.assertEqual(adf_to_md({"type": "doc", "content": []}), "")


class WikiTest(unittest.TestCase):
    def test_wiki_basics(self):
        src = "h2. Rules\n* *Bold* item\n** nested _it_\n# one\n{code:java}\nint x = 1;\n{code}\n[Spec|https://s.io] and {{mono}}\n||A||B||\n|1|2|"
        md = wiki_to_md(src)
        self.assertIn("## Rules", md)
        self.assertIn("- **Bold** item", md)
        self.assertIn("   - nested *it*", md)
        self.assertIn("1. one", md)
        self.assertIn("```java\nint x = 1;\n```", md)
        self.assertIn("[Spec](https://s.io) and `mono`", md)
        self.assertIn("| A | B |\n| --- | --- |\n| 1 | 2 |", md)

    def test_hyphens_are_not_strike(self):
        self.assertEqual(wiki_to_md("a well-known pre-paid card"), "a well-known pre-paid card")


class DemoteTest(unittest.TestCase):
    def test_demote_skips_code(self):
        self.assertEqual(demote_headings("# A\n```\n# not\n```\n###### B", 3), "#### A\n```\n# not\n```\n###### B")


if __name__ == "__main__":
    unittest.main()
