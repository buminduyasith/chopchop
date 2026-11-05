"""The learn script on the refunds sample project: prepare, write, refresh and person entries."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "scripts"))

import chopchop_learn  # noqa: E402

SETUP = PLUGIN / "evals" / "sample-project" / "setup.py"


def run(main, *argv, code=0, ws=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        got = main(list(argv) + (["--workspace", ws] if ws else []))
    text = out.getvalue() + err.getvalue()
    assert got == code, "exit %s, wanted %s\n%s" % (got, code, text)
    return text


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        out = subprocess.run([sys.executable, str(SETUP), "--to", str(Path(self.tmp.name) / "s"), "--json"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        info = json.loads(out.stdout)
        self.root = Path(info["root"])
        self.ws = info["workspace"]
        self.first = info["commits"]["payments-api"]["first"]

    def tearDown(self):
        self.tmp.cleanup()


class LearnTest(Base):
    def learn(self, *argv, code=0):
        return run(chopchop_learn.main, *argv, code=code, ws=self.ws)

    def update(self, first):
        c = "payments-api/%s@" + first[:7]
        return {"repos": {"payments-api": {"kind": "service", "summary": "Payments, order cancel and payouts.",
                                           "layers": ["controller", "service", "repository", "job"],
                                           "patterns": [{"text": "Status changes go through one service.",
                                                         "cite": c % "src/orders/cancel/OrderCancelService.java:12-17"}]}},
                "nodes": [{"id": "payments-api:api", "name": "Payments API", "kind": "api", "repo": "payments-api"},
                          {"id": "payments-api:payout-job", "name": "Payout job", "kind": "job", "repo": "payments-api"},
                          {"id": "psp", "name": "Card provider", "kind": "external"}],
                "links": [{"from": "payments-api:payout-job", "to": "psp", "kind": "external", "say": "send payout",
                           "found_in": "payments-api"}]}

    def test_learn_write_status_and_person_entries(self):
        self.assertIn("full", self.learn("--prepare"))
        f = Path(self.tmp.name) / "u.json"
        f.write_text(json.dumps(self.update(self.first)))
        out = self.learn("--write", str(f))
        self.assertIn("1 repos, 3 parts, 1 links", out)
        m = json.loads((Path(self.ws) / "system" / "system-map.json").read_text())
        repo = m["repos"]["payments-api"]
        self.assertEqual(repo["owners"], ["@pay-team"])
        self.assertEqual(repo["adrs"], ["docs/adr/0001-events-through-outbox.md"])
        self.assertTrue(repo["commit"])
        md = (Path(self.ws) / "system" / "system-map.md").read_text()
        self.assertIn("```mermaid", md)
        self.assertIn("| payments-api | service | @pay-team |", md)
        status = json.loads(self.learn("--status", "--json"))
        self.assertEqual({r["repo"]: r["mode"] for r in status["repos"]}["payments-api"], "fresh")
        # a person fixes one node; the next helper update keeps it
        m["nodes"][0]["name"], m["nodes"][0]["source"] = "Payments API (fixed by hand)", "person"
        (Path(self.ws) / "system" / "system-map.json").write_text(json.dumps(m))
        self.learn("--write", str(f))
        m2 = json.loads((Path(self.ws) / "system" / "system-map.json").read_text())
        self.assertIn("Payments API (fixed by hand)", [n["name"] for n in m2["nodes"]])
        self.assertEqual(len(m2["nodes"]), 3)
        # bad update
        bad = self.update(self.first)
        bad["links"][0]["to"] = "nowhere"
        f.write_text(json.dumps(bad))
        self.assertIn("'nowhere' is not a node", self.learn("--write", str(f), code=2))

    def test_refresh_after_a_new_commit(self):
        f = Path(self.tmp.name) / "u.json"
        f.write_text(json.dumps(self.update(self.first)))
        self.learn("--write", str(f))
        repo = self.root / "web-app"
        (repo / "src" / "orders" / "OrderPage.tsx").write_text("// refund button soon\n")
        env = {"GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": "x@x", "GIT_COMMITTER_NAME": "x", "GIT_COMMITTER_EMAIL": "x@x"}
        subprocess.run(["git", "commit", "-qam", "change"], cwd=str(repo), env=dict(os.environ, **env), check=True)
        d = json.loads(self.learn("--prepare", "--json"))
        modes = {r["name"]: r["mode"] for r in d["repos"]}
        self.assertEqual(modes["payments-api"], "fresh")
        self.assertEqual(modes["web-app"], "full")  # never learned
        web = {"repos": {"web-app": {"kind": "web"}}, "nodes": [], "links": []}
        f.write_text(json.dumps(web))
        self.learn("--write", str(f))
        (repo / "src" / "orders" / "OrderPage.tsx").write_text("// refund button now\n")
        subprocess.run(["git", "commit", "-qam", "change 2"], cwd=str(repo), env=dict(os.environ, **env), check=True)
        d = json.loads(self.learn("--prepare", "--json"))
        web = next(r for r in d["repos"] if r["name"] == "web-app")
        self.assertEqual(web["mode"], "refresh")
        self.assertEqual(web["changed"], [{"status": "M", "file": "src/orders/OrderPage.tsx"}])
        self.assertEqual(d["to_read"], ["web-app", "notify-service", "ledger-service"])


if __name__ == "__main__":
    unittest.main()
