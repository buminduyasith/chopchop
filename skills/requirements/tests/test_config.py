import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from relaylib.config import expand_env, mini_yaml  # noqa: E402

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "relay.yaml"


class MiniYamlTest(unittest.TestCase):
    def test_template_parses_same_as_pyyaml(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        mine = mini_yaml(text)
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        self.assertEqual(mine, yaml.safe_load(text))

    def test_subset(self):
        text = """
a: 1
b: "two # not a comment"   # a comment
c:
  d: [x, "y z", 3]
  e: true
  f: null
  g:
    - one
    - two
  h:
    - name: n1
      id: 5
    - name: n2
url: https://x.atlassian.net/path
empty:
"""
        self.assertEqual(mini_yaml(text), {
            "a": 1, "b": "two # not a comment",
            "c": {"d": ["x", "y z", 3], "e": True, "f": None, "g": ["one", "two"],
                  "h": [{"name": "n1", "id": 5}, {"name": "n2"}]},
            "url": "https://x.atlassian.net/path", "empty": None})

    def test_env_expansion(self):
        os.environ["RELAY_TEST_X"] = "hello"
        os.environ.pop("RELAY_TEST_MISSING", None)
        missing = []
        out = expand_env({"a": "${RELAY_TEST_X}/p", "b": ["${RELAY_TEST_MISSING}"], "c": "${RELAY_TEST_MISSING:-dflt}"}, missing)
        self.assertEqual(out, {"a": "hello/p", "b": [""], "c": "dflt"})
        self.assertEqual(missing, ["RELAY_TEST_MISSING"])


if __name__ == "__main__":
    unittest.main()
