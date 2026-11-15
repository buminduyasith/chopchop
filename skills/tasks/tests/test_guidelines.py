"""The team's code guidelines file: placeholders are not rules."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from chopchoplib import guidelines  # noqa: E402


class GuidelinesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "_chopchop"

    def tearDown(self):
        self.tmp.cleanup()

    def test_template_has_no_rules(self):
        self.assertFalse(guidelines.has_rules(guidelines.TEMPLATE))
        self.assertFalse(guidelines.has_rules("# Rules\n\n## Tests\n\n- \n* [ ]\n<!-- - use tabs -->\n"))
        self.assertTrue(guidelines.has_rules(guidelines.TEMPLATE.replace("## Tests\n", "## Tests\n\n- Use AAA.\n")))
        self.assertTrue(guidelines.has_rules("Write small functions.\n"))

    def test_missing_placeholder_and_filled(self):
        i = guidelines.info(self.ws)
        self.assertEqual((i["exists"], i["filled"]), (False, False))
        self.assertIn("none.", guidelines.describe(i))
        self.assertTrue(guidelines.ensure(self.ws))
        i = guidelines.info(self.ws)
        self.assertEqual((i["exists"], i["filled"]), (True, False))
        self.assertIn("only placeholders", guidelines.describe(i))
        self.assertIsNone(guidelines.active(self.ws))
        f = self.ws / "guidelines.md"
        f.write_text("# Rules\n\n- No raw SQL.\n")
        self.assertFalse(guidelines.ensure(self.ws))  # never overwrites
        self.assertEqual(f.read_text(), "# Rules\n\n- No raw SQL.\n")
        self.assertEqual(guidelines.active(self.ws), str(f))
        self.assertIn("follow them", guidelines.describe(guidelines.info(self.ws)))

    def test_path_from_config(self):
        shared = Path(self.tmp.name) / "shared" / "rules.md"
        self.assertEqual(guidelines.path(self.ws, {"guidelines": str(shared)}), shared)
        self.assertEqual(guidelines.path(self.ws, {"guidelines": "team/rules.md"}), self.ws / "team" / "rules.md")
        self.assertEqual(guidelines.path(self.ws, {}), self.ws / "guidelines.md")


if __name__ == "__main__":
    unittest.main()
