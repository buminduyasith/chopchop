import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import chopchop_diagram  # noqa: E402

ARCH = {"title": "Refunds", "nodes": [
    {"id": "customer", "name": "Customer", "kind": "person", "row": 0, "col": 0},
    {"id": "api", "name": "Refund API", "kind": "api", "repo": "payments-api", "status": "new", "row": 0, "col": 1},
    {"id": "db", "name": "refunds table", "kind": "table", "repo": "payments-api", "status": "new", "row": 1, "col": 1}],
    "links": [{"from": "customer", "to": "api", "label": "POST refunds"},
              {"from": "api", "to": "db", "label": "saves pending", "kind": "data"}]}
FLOW = {"title": "Ask", "participants": ["customer", "api", "db"], "messages": [
    {"n": 1, "from": "customer", "to": "api", "kind": "person", "say": "asks for refund", "line": "The customer asks.",
     "failure": {"twice": "One refund per order.", "caller": "Owner only."}},
    {"n": 2, "from": "api", "to": "db", "kind": "db", "say": "saves pending", "line": "It is saved.",
     "failure": {"fails": "500, nothing saved."}},
    {"n": 3, "from": "api", "to": "customer", "kind": "reply", "say": "201 pending", "line": "Pending."}]}


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = chopchop_diagram.main(list(argv))
    return code, out.getvalue() + err.getvalue()


class DiagramTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, arch=ARCH, flow=FLOW):
        (self.dir / "architecture.json").write_text(json.dumps(arch))
        (self.dir / "flow.json").write_text(json.dumps(flow))
        return ["--arch", str(self.dir / "architecture.json"), "--flow", str(self.dir / "flow.json")]

    def test_draw_writes_both_pictures(self):
        code, out = run("--draw", *self.write())
        self.assertEqual(code, 0, out)
        self.assertIn("message 2 (saves pending): Runs twice", out)  # a missing answer does not stop the drawing
        page = (self.dir / "diagrams.html").read_text()
        self.assertIn('class="cc-arch"', page)
        self.assertIn('class="cc-flow"', page)

    def test_steps_on_the_structure_are_refused(self):
        arch = json.loads(json.dumps(ARCH))
        arch["links"][0]["label"] = "1. asks"
        code, out = run("--check", *self.write(arch=arch))
        self.assertEqual(code, 1)
        self.assertIn("is a step number", out)

    def test_mermaid_and_missing_files(self):
        code, out = run("--mermaid", *self.write())
        self.assertEqual(code, 0)
        self.assertIn("flowchart LR", out)
        self.assertIn("sequenceDiagram", out)
        code, out = run("--check", "--arch", str(self.dir / "nope.json"))
        self.assertEqual(code, 2)
        self.assertIn("no architecture.json yet", out)


if __name__ == "__main__":
    unittest.main()
