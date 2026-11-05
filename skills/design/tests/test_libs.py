"""The shared helpers design uses: citations, secrets, helpers, the diagrams, options, Markdown, lint."""

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tasks" / "scripts"))

from chopchoplib import cite, designdoc, diagrams, helpers, mdhtml, options  # noqa: E402


class CiteTest(unittest.TestCase):
    def test_find_and_write(self):
        text = "Payouts retry `payments-api/src/payouts/PayoutJob.java:35-40@a1f9c2e` and see a/b.java:3@zzz."
        found = cite.find(text)
        self.assertEqual(len(found), 1)
        c = found[0]
        self.assertEqual((c["repo"], c["path"], c["start"], c["end"], c["commit"]),
                         ("payments-api", "src/payouts/PayoutJob.java", 35, 40, "a1f9c2e"))
        self.assertEqual(cite.short(c), "PayoutJob.java:35-40")
        self.assertEqual(cite.write("r", "a.py", 3, 3, "abcdef1234"), "r/a.py:3@abcdef1")

    def test_secrets_are_masked(self):
        # Fake values, built from parts so no key-shaped text sits in the repo.
        fakes = ["key = " + "AKIA" + "A" * 16, "tok " + "gh" + "p_" + "a" * 36,
                 "-----BEGIN RSA " + "PRIVATE KEY-----", 'api_key: "' + "sk-" + "live-" + "1" * 16 + '"']
        for line in ['password = "hunter2hunter2"'] + fakes:
            masked, hit = cite.mask(line)
            self.assertTrue(hit, line)
            self.assertIn("*****", masked)
        self.assertEqual(cite.mask("retry.run(p, MAX_TRIES)"), ("retry.run(p, MAX_TRIES)", False))
        self.assertEqual(cite.mask('password = "hunter2hunter2"')[0], 'password = "*****"')

    def test_unknown_repo(self):
        r = cite.check(cite.find("x/y.py:1@abcdef1")[0], {})
        self.assertEqual(r["status"], "unknown")


class HelpersTest(unittest.TestCase):
    def test_settings_and_calls(self):
        s = helpers.settings({})
        self.assertEqual((s["set"], s["max"], s["model"]), (False, 3, "inherit"))
        s = helpers.settings({"agents": {"max": 0, "model": "haiku", "effort": "max",
                                         "roles": {"reviewer": {"model": "opus"}, "boss": {}}}})
        self.assertEqual(helpers.for_role(s, "explorer"), {"model": "haiku", "effort": "max"})
        self.assertEqual(helpers.for_role(s, "reviewer"), {"model": "opus", "effort": "max"})
        self.assertIn("agents.roles.boss is not a role", s["problems"][0])
        self.assertIn("No helpers", helpers.plan("large", ["a", "b"], s)["line"])
        bad = helpers.settings({"agents": {"max": 99, "model": "claude-opus-5-5"}})
        self.assertEqual(len(bad["problems"]), 2)

    def test_write_block_replaces_only_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "chopchop.yaml"
            cfg.write_text("team: t\n\n# Helpers (subagents). old comment\nagents:\n  max: 1\n\n# Kept from the old chopchop.yaml.\nextra: 1\n")
            helpers.write_block(cfg, 4, "opus", "high")
            text = cfg.read_text()
            self.assertEqual(text.count("agents:"), 1)
            self.assertIn("max: 4", text)
            self.assertIn("# Kept from the old chopchop.yaml.\nextra: 1", text)
            self.assertNotIn("old comment", text)
            self.assertTrue(text.startswith("team: t\n"))
            with self.assertRaises(ValueError):
                helpers.write_block(cfg, 4, "gpt", "high")


class DiagramsTest(unittest.TestCase):
    def arch(self):
        return {"title": "T", "nodes": [
            {"id": "u", "name": "User", "kind": "person", "row": 0, "col": 0},
            {"id": "a", "name": "API (v2) /x", "kind": "api", "repo": "r1", "status": "new", "row": 0, "col": 1},
            {"id": "d", "name": "table", "kind": "table", "repo": "r1", "status": "new", "row": 1, "col": 1},
            {"id": "e", "name": "Provider", "kind": "external", "status": "external", "row": 0, "col": 2}],
            "links": [{"from": "u", "to": "a", "label": "POST refunds"}, {"from": "a", "to": "d", "label": "saves", "kind": "data"},
                      {"from": "a", "to": "e", "label": "sends", "kind": "external"}]}

    def flow(self):
        return {"title": "F", "participants": ["u", "a", "e"], "messages": [
            {"n": 1, "from": "u", "to": "a", "kind": "person", "say": "POST /refunds [x]", "line": "One.",
             "stories": ["S-1"], "failure": {"twice": "ok", "caller": "ok"}},
            {"n": 2, "from": "a", "to": "e", "kind": "external", "say": "send", "line": "Two.",
             "stories": ["S-1"], "failure": {"fails": "retry"}},
            {"n": 3, "from": "a", "to": "u", "kind": "reply", "say": "422 too late", "line": "Three.", "if": "too late"}]}

    def test_architecture_draws_and_mermaid_is_safe(self):
        a = self.arch()
        self.assertEqual(diagrams.validate_architecture(a, {"r1"}), ([], []))
        self.assertEqual(diagrams.layout_problems(a), ([], []))
        svg = diagrams.architecture_svg(a)
        self.assertTrue(svg.startswith("<svg") and "r1" in svg and "OUTSIDE" in svg)
        text = diagrams.architecture_mermaid(a)
        self.assertIn("subgraph g_r1[r1]", text)
        self.assertIn("API v2 x", text)
        self.assertNotIn("(v2)", text)

    def test_architecture_is_not_a_sequence(self):
        a = self.arch()
        a["links"][0]["label"] = "1. asks"
        a["nodes"][3]["row"], a["nodes"][3]["col"] = 1, 1
        errors, _ = diagrams.validate_architecture(a)
        joined = "\n".join(errors)
        self.assertIn("is a step number", joined)
        self.assertIn("same cell", joined)

    def test_part_inside_another_repo(self):
        a = self.arch()
        a["nodes"][2].update(row=0, col=3)
        a["nodes"].append({"id": "o", "name": "Other", "kind": "service", "repo": "r2", "status": "new", "row": 0, "col": 2})
        a["nodes"][3].update(row=1, col=3)
        a["links"].append({"from": "a", "to": "o", "label": "asks"})
        errors, _ = diagrams.validate_architecture(a)
        self.assertTrue(any("inside the r1 group" in e for e in errors), errors)

    def test_flow(self):
        f, a = self.flow(), self.arch()
        self.assertEqual([r["question"] for r in diagrams.missing(f)], ["slow", "twice", "caller"])
        svg = diagrams.flow_svg(f, a)
        self.assertIn("too late", svg)
        self.assertIn("opt too late", diagrams.flow_mermaid(f, a))
        f["messages"][1]["n"] = 5
        f["participants"].append("zz")
        errors, _ = diagrams.validate_flow(f, a, ["S-1", "S-2"], {"S-1", "S-2"})
        joined = "\n".join(errors)
        self.assertIn("numbered 1, 2, 3", joined)
        self.assertIn("zz is not a part", joined)
        self.assertIn("story S-2 has no message", joined)


class OptionsTest(unittest.TestCase):
    def test_pick_errors(self):
        data = {"choices": [{"kind": "decision", "question": "Q?", "options": [{"key": "A"}, {"key": "B"}], "recommended": "A"}]}
        with self.assertRaises(ValueError):
            options.pick(data, "2=A")
        with self.assertRaises(ValueError):
            options.pick(data, "1=C")
        with self.assertRaises(ValueError):
            options.pick(data, "one")
        self.assertEqual(options.pick(data, "1=b", "lead")["picked"], "B")

    def test_breaking_pick_goes_to_the_lead(self):
        data = {"choices": [{"kind": "decision", "question": "Q?", "recommended": "A", "picked": "B", "picked_by": "you",
                             "options": [{"key": "A", "title": "Event", "fit": "follows"},
                                         {"key": "B", "title": "Direct call", "fit": "breaks", "fit_note": "Nothing calls it directly."}]}]}
        lead = options.lead_items(data)
        self.assertIn("It breaks a pattern: Nothing calls it directly. The lead must agree.", lead[0]["text"])


class MarkdownTest(unittest.TestCase):
    def test_convert(self):
        html = mdhtml.convert("# Title\n\n<!-- talk: hidden -->\nSee `a/b.py:3@abcdef1` and **bold**.\n\n"
                              "| A | B |\n| --- | --- |\n| 1 | x \\| y |\n\n- one\n- [x] two\n\n```mermaid\nflowchart LR\n  a-->b\n```\n"
                              "[ok](https://x.y) [bad](javascript:alert(1))")
        self.assertNotIn("hidden", html)
        self.assertIn('class="cite" data-cite="a/b.py:3@abcdef1"', html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<td>x | y</td>", html)
        self.assertIn('<span class="box on"></span>two', html)
        self.assertIn('<pre class="mermaid">flowchart LR\n  a--&gt;b</pre>', html)
        self.assertIn('<a href="https://x.y">ok</a>', html)
        self.assertNotIn("javascript:", html)

    def test_escapes_html(self):
        self.assertIn("&lt;script&gt;", mdhtml.convert("<script>x</script> text"))


class LintTest(unittest.TestCase):
    def test_words_and_style(self):
        body = "\n".join("## %d. %s\n\nNone." % (i, h) for i, h in enumerate(designdoc.HEADINGS, 1))
        body = body.replace("## 1. Summary and the ask\n\nNone.", "## 1. Summary and the ask\n\n**The ask:** approve it.\n\n"
                            "We utilize a robust queue, e.g. the outbox, in order to send events to every one of the many "
                            "services that listen for payment events across all of the teams in the company today.")
        for name, n in designdoc.BLOCKS.items():
            body = body.replace("## %d. %s\n\nNone." % (n, designdoc.HEADINGS[n - 1]),
                                "## %d. %s\n\n<!-- chopchop:%s -->\n<!-- /chopchop:%s -->" % (n, designdoc.HEADINGS[n - 1], name, name))
        errors, warnings = designdoc.lint(body, "small", [])
        self.assertEqual(errors, [])
        joined = "\n".join(warnings)
        for word in ("utilize", "robust", "e.g.", "in order to"):
            self.assertIn('"%s"' % word, joined)
        self.assertIn("long sentence", joined)

    def test_bullets_and_talk(self):
        text = "Intro line.\n\n- First point with `code`.\n- Second **point**.\n<!-- talk: Say this. -->"
        self.assertEqual(designdoc.bullets(text), ["First point with code.", "Second point."])
        self.assertEqual(designdoc.talk(text), "Say this.")


if __name__ == "__main__":
    unittest.main()
