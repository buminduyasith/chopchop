"""The page side of the reviewer's notes: the functions are there, and note text never goes in as HTML."""

import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "assets" / "dashboard.html"


def page():
    return PAGE.read_text(encoding="utf-8")


def body(text, name):
    """The source of one top-level function: from its line to the next top-level function."""
    m = re.search(r"^(?:async )?function %s\(" % re.escape(name), text, re.M)
    assert m, "function %s( is not in the page" % name
    end = re.compile(r"^(?:async )?function \w+\(", re.M).search(text, m.end())
    return text[m.start():end.start() if end else len(text)]


class NotesPage(unittest.TestCase):
    def test_page_has_the_notes_functions(self):
        text = page()
        for name in ("function copyText(", "function markNotes(", "function noteBar(", "function anchorOf(", "/api/notes/"):
            self.assertIn(name, text)

    def test_page_puts_no_note_text_in_html(self):
        # The three are the server's escaped Markdown, highlight.js output and Mermaid's strict SVG.
        self.assertEqual(page().count("innerHTML"), 3)

    def test_copy_button_still_copies_elements(self):
        text = page()
        self.assertIn("function copyButton(", text)
        self.assertIn("copyText(", body(text, "copyButton"))

    def test_page_keeps_the_popover_out_of_the_view(self):
        text = page()
        self.assertIn("function notePopover(", text)
        self.assertIn("function changeNotes(", text)
        change = body(text, "changeNotes")
        first = re.search(r"\bapi\(", change)
        post = change.find("apiPost(")
        self.assertIsNotNone(first)
        self.assertGreater(post, 0)
        self.assertLess(first.start(), post)   # load the list from the server, then save
        self.assertIn("document.body.append(", body(text, "notePopover"))


if __name__ == "__main__":
    unittest.main()
