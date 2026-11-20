"""The page side of notes on diagrams: Add note in each card, the box from the drawing, and marks after each paint."""

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


class DiagramNotesPage(unittest.TestCase):
    def test_page_has_diagram_notes(self):
        text = page()
        self.assertIn("function markDiagram(", text)
        self.assertIn("function boxOf(", text)
        paint = body(text, "paint")
        self.assertIn("markDiagram(", paint)
        done = paint.find('dataset.state = "done"')
        self.assertGreaterEqual(done, 0)
        self.assertLess(done, paint.find("markDiagram("))   # marked once drawn
        self.assertIn("flowchart-n_", body(text, "boxOf"))
        self.assertIn("Add note", body(text, "diagramCard"))
        self.assertIn('securityLevel: "strict"', text)


if __name__ == "__main__":
    unittest.main()
