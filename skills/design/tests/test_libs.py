"""The shared helpers design uses: citations, secrets, helpers, the feature map, options, Markdown, lint."""

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tasks" / "scripts"))

from chopchoplib import cite, designdoc, featuremap, helpers, mdhtml, options  # noqa: E402


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


class FeatureMapTest(unittest.TestCase):
    def fm(self):
        return {"title": "T", "actors": [{"id": "u", "name": "User"}],
                "boxes": [{"id": "a", "name": "API (v2) /x", "repo": "r1", "status": "new", "kind": "api"},
                          {"id": "e", "name": "Provider", "status": "external", "kind": "external"}],
                "steps": [{"n": 1, "from": "u", "to": "a", "kind": "person", "say": "POST /refunds [x]", "line": "One.",
                           "stories": ["S-1"], "failure": {"twice": "ok", "caller": "ok"}},
                          {"n": 2, "from": "a", "to": "e", "kind": "external", "say": "send", "line": "Two.",
                           "stories": ["S-1"], "failure": {"fails": "retry"}}]}

    def test_mermaid_is_safe_and_marks_gaps(self):
        text = featuremap.mermaid(self.fm())
        self.assertIn("n_a[API v2 x NEW]", text)
        self.assertIn("|1 POST refunds x|", text)
        self.assertIn("|2 send ⚠|", text)
        self.assertIn("class n_e ext", text)
        self.assertEqual([r["question"] for r in featuremap.missing(self.fm())], ["slow", "twice", "caller"])

    def test_validate(self):
        fm = self.fm()
        fm["boxes"] += [{"id": "b%d" % i, "name": "x", "repo": "r1", "status": "same", "kind": "service"} for i in range(10)]
        fm["steps"][1]["n"] = 5
        errors, warnings = featuremap.validate(fm, {"r1"}, ["S-1", "S-2"], {"S-1", "S-2"})
        joined = "\n".join(errors)
        self.assertIn("At most 12", joined)
        self.assertIn("numbered 1, 2, 3", joined)
        self.assertIn("story S-2 has no step", joined)
        self.assertTrue(any("is on no step" in w for w in warnings))


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
