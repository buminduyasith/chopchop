"""The spec script end to end, on the refunds sample project, then tasks cut from it."""

import contextlib
import copy
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(PLUGIN / "skills" / "tasks" / "scripts"))

import chopchop_spec  # noqa: E402  (puts the tasks scripts on the path)
import chopchop_tasks  # noqa: E402
from chopchoplib import diagrams, features, specdata  # noqa: E402
from chopchoplib import tasks as tasklib  # noqa: E402

SETUP = PLUGIN / "evals" / "sample-project" / "setup.py"
EXAMPLE = HERE.parent / "examples" / "refunds.spec.json"
FLOW = HERE.parent / "examples" / "refunds.flow.json"
PROSE = {1: "Customers ask for refunds from the order page.", 2: "The words this spec uses.",
         3: "Refunds move into the product.", 5: "Order cancel is the closest feature.",
         8: "Each message of the main flow, and its code.", 10: "One new table, refunds.",
         12: "Only the owner asks, only support cancels.", 13: "What every task agrees on.",
         19: "Ship payments-api first, then the rest."}


def run(main, *argv, code=0, ws=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        got = main(list(argv) + ["--workspace", str(ws)])
    text = out.getvalue() + err.getvalue()
    assert got == code, "exit %s, wanted %s:\n%s" % (got, code, text)
    return text


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        out = subprocess.run([sys.executable, str(SETUP), "--to", str(Path(self.tmp.name) / "s"), "--json"],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        info = json.loads(out.stdout)
        self.ws = info["workspace"]
        self.root = Path(info["root"])
        self.feature = features.resolve(self.ws, "")
        self.paths = chopchop_spec.Paths(self.feature)
        heads = {name: (c.get("second") or c["first"])[:7] for name, c in info["commits"].items()}
        text = EXAMPLE.read_text()
        for old, repo in (("9c209d4", "payments-api"), ("21fb0dc", "web-app"), ("1f429be", "notify-service")):
            text = text.replace("@" + old, "@" + heads[repo])
        self.spec = json.loads(text)

    def tearDown(self):
        self.tmp.cleanup()

    def spec_cmd(self, *argv, code=0):
        return run(chopchop_spec.main, *argv, code=code, ws=self.ws)

    def write(self, spec=None, prose=True):
        self.spec_cmd("--scaffold")
        (self.feature.path / "design").mkdir(exist_ok=True)
        self.paths.flow.write_text(FLOW.read_text())
        self.paths.json.write_text(json.dumps(spec or self.spec, indent=2))
        if prose:
            text = self.paths.md.read_text()
            for n, line in PROSE.items():
                m = re.search(r"(?m)^## %d\. [^\n]*\n\n<!--.*?-->\n" % n, text, re.S)
                text = text[:m.end()] + "\n**In short:** %s\n" % line + text[m.end():]
            self.paths.md.write_text(text)


class BuildTest(Base):
    def test_spec_then_tasks_then_done(self):
        self.write()
        out = self.spec_cmd("--build")
        self.assertIn("Result:   ready", out)
        self.assertIn("5 packages in 3 repos", out)
        body = self.paths.md.read_text()
        self.assertIn("status: \"ready\"", body)
        self.assertIn("| new | `src/refunds/RefundService.java` | the 30 day and 0.01 rules", body)  # section 6
        self.assertIn("        Order order = orders.findOwned(orderId, by);", body)  # section 7 shows the real code to copy
        self.assertIn("| `orders.findOwned(orderId, by)` |", body)
        self.assertIn("**R-1** A customer can ask for a refund only within 30 days", body)
        self.assertIn("- Example 2. Given an order paid 31 days ago", body)
        self.assertIn("| 11 | cancels while pending | Wrong caller |", body)
        self.assertIn("Accepted risk", body)
        self.assertIn("| `refuses_refund_after_30_days` | payments-api · P2 |", body)
        self.assertIn("### J1 · Customer gets a refund", body)
        self.assertIn("Manual: signed by Asha", body)
        self.assertIn("0 of 27 proofs passed", body)
        self.assertIn("```mermaid\nflowchart LR", body)

        out = run(chopchop_tasks.main, "--from-spec", code=0, ws=self.ws)
        self.assertIn("Cut:      5 tasks", out)
        found = {t.id: t for t in tasklib.load_tasks(self.paths.tasks)}
        self.assertEqual(sorted(found), ["T01", "T02", "T03", "T04", "T05"])
        self.assertEqual((found["T02"].get("package"), found["T02"].get("depends_on")), ("P2", ["T01"]))
        self.assertEqual(found["T04"].get("depends_on"), [])  # another repo codes against the contract with a mock
        t2 = found["T02"].body
        self.assertIn("## Code", t2)
        self.assertIn("    order.requireStatus(OrderStatus.PAID);", t2)  # the real code to copy, in the task
        self.assertIn("- [ ] Unit test `refuses_refund_after_30_days`", t2)
        self.assertIn("Code against this exact shape, with a mock", found["T04"].body)
        self.assertEqual(run(chopchop_tasks.main, "--from-spec", code=0, ws=self.ws).count("never rewrites"), 1)

        verify = self.paths.verify
        verify.mkdir(parents=True)
        (verify / "T01.json").write_text(json.dumps({"task": "T01", "ok": True, "when": "2026-11-09T10:00:00"}))
        run(chopchop_tasks.main, "--set", "T01", "done", "--feature", "1", ws=self.ws)
        out = self.spec_cmd("--status")
        self.assertIn("Proof:    2 of 27 proved", out)
        self.spec_cmd("--sign", "M2", "--by", "Asha")
        self.assertIn("signed by Asha", self.paths.md.read_text())
        self.assertIn("Not everything is proved yet", self.spec_cmd("--done", "--by", "Asha", code=2))
        self.assertIn("is not a manual check", self.spec_cmd("--sign", "R-1", "--by", "Asha", code=2))

    def test_build_blocks_on_code_that_does_not_fit(self):
        spec = copy.deepcopy(self.spec)
        p2 = spec["packages"][1]
        p2["reuse"][0]["name"] = "orders.findAny(orderId)"                      # not in the cited lines
        p2["sketch"][0]["code"] += "\nProblemDetail.forStatus(422);"            # the do-not list forbids it
        spec["packages"][2]["files"].append({"path": "src/refunds/RefundService.java", "change": "new", "what": "x"})
        spec["packages"][0]["files"][1]["path"] = "src/orders/Order.java"       # marked new, but it exists
        spec["packages"][4]["tests"][0]["failures"] = []                         # 9.twice loses its test
        self.write(spec)
        out = self.spec_cmd("--build", code=1)
        self.assertIn("P2 reuses orders.findAny(orderId), but findAny is not in the lines it cites", out)
        self.assertIn("P2 sketch for src/refunds/RefundService.java uses ProblemDetail", out)
        self.assertIn("P2 and P3 are both in wave 1 and both touch src/refunds/RefundService.java", out)
        self.assertIn("P1: src/orders/Order.java is marked new, but it already exists", out)
        self.assertIn("failure 9.twice (message 9, twice", out)
        self.assertIn("status: \"draft\"", self.paths.md.read_text())
        self.assertIn("The spec is not ready", run(chopchop_tasks.main, "--from-spec", code=2, ws=self.ws))

    def test_empty_prose_and_broken_json(self):
        self.write(prose=False)
        out = self.spec_cmd("--build", code=1)
        self.assertIn("section 1 (Summary) is empty", out)
        self.paths.json.write_text("{not json")
        self.assertIn("is not valid JSON", self.spec_cmd("--build", code=2))


class DataTest(unittest.TestCase):
    def spec(self):
        return json.loads(EXAMPLE.read_text())

    def test_example_is_clean(self):
        flow = json.loads(FLOW.read_text())
        errors, warnings = specdata.validate(self.spec(), ["PAY-121", "PAY-122"], None, None, flow)
        self.assertEqual(errors, [])

    def test_rules_need_examples_and_proof(self):
        s = self.spec()
        s["rules"].append({"id": "R-6", "text": "A new rule.", "stories": ["PAY-121"], "met": "x"})
        s["questions"].append({"text": "Which currency?", "owner": "@pay", "blocking": True})
        errors, _ = specdata.validate(s, ["PAY-121", "PAY-122", "PAY-130"])
        joined = "\n".join(errors)
        self.assertIn("R-6 needs at least one example", joined)
        self.assertIn("R-6 has no test, journey or manual check", joined)
        self.assertIn("story PAY-130 has no rule", joined)
        self.assertIn("open question blocks the build: Which currency?", joined)

    def test_a_journey_that_runs_becomes_a_prove_task(self):
        s = self.spec()
        s["journeys"].append({"id": "J2", "title": "Agent cancels a refund", "stories": ["PAY-122"], "rules": ["R-4"],
                              "repo": "payments-api", "file": "e2e/cancel_refund_test.java",
                              "run": {"command": "./gradlew e2eTest", "found_in": "build.gradle"},
                              "data": "A pending refund 88.", "steps": [{"do": "Cancel refund 88.", "see": "CANCELLED."}]})
        self.assertEqual(specdata.validate(s)[0], [])
        out = specdata.to_tasks(s)
        prove = out[-1]
        self.assertEqual((prove["meta"]["id"], prove["meta"]["wave"], prove["meta"]["kind"], prove["meta"]["e2e"]),
                         ("T06", 3, "prove", "./gradlew e2eTest"))
        self.assertEqual(prove["meta"]["depends_on"], ["T02"])
        self.assertIn("- [ ] E2E test `e2e/cancel_refund_test.java` passes with `./gradlew e2eTest`.", prove["body"])
        with tempfile.TemporaryDirectory() as d:
            for x in out:
                (Path(d) / x["file"]).write_text(chopchop_tasks.render_front_matter(x["meta"]) + x["body"])
            loaded = tasklib.load_tasks(Path(d))
            errors, _ = tasklib.check(loaded)
            self.assertEqual(errors, [])
            loaded[0].meta["wave"] = 3
            self.assertTrue(any("wave 3 is only for prove tasks" in e for e in tasklib.check(loaded)[0]))

    def test_file_map(self):
        s = self.spec()
        svg = diagrams.file_map_svg(s)
        self.assertTrue(svg.startswith("<svg") and 'class="cc-files"' in svg)
        self.assertIn("RefundService.java", svg)
        self.assertIn(">CHANGED<", svg)
        text = diagrams.file_map_mermaid(s)
        self.assertIn("subgraph r0[payments-api]", text)
        self.assertIn("class n1 new", text)


if __name__ == "__main__":
    unittest.main()
