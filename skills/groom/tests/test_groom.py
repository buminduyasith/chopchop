"""The groom script end to end on the refunds sample: research, questions, answers, the brief, and ideas."""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(PLUGIN / "skills" / "tasks" / "scripts"))

import chopchop_groom  # noqa: E402
from chopchoplib import events, features, plain, stage  # noqa: E402
from chopchoplib.requirements import requirement_items  # noqa: E402

SETUP = PLUGIN / "evals" / "sample-project" / "setup.py"


def run(*argv, code=0, ws=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        got = chopchop_groom.main(list(argv) + ["--workspace", str(ws)])
    text = out.getvalue() + err.getvalue()
    assert got == code, "exit %s, wanted %s:\n%s" % (got, code, text)
    return text


def findings(stories, **extra):
    data = {"stories": [{"id": s, "fits": "yes", "plain": "The code can take this as written.", "size": "S",
                         "touches": ["refund service"], "evidence": ["payments-api/src/x.js:1@abc1234"]} for s in stories],
            "questions": [
                {"text": "Can a customer ask for part of the money back?", "why": "The order has one amount field.",
                 "story": stories[0], "options": ["Yes", "No, full only"], "guess": "No, full only", "ask": "dev",
                 "blocking": True},
                {"text": "How many days after delivery can a refund be asked for?", "why": "The story gives no limit.",
                 "ask": "ba", "blocking": False}],
            "risks": ["No tests for money rounding."], "summary": ["Refunds fit the cancel pattern."]}
    data.update(extra)
    return data


BRIEF = """# Brief · Refunds

## Summary

- Customers can ask for a refund from the order page.
- Support can approve or refuse it.

## What we build

A refund request on a delivered order.

## Who it is for and why

Customers who got the wrong item.

## In scope

%s

## Out of scope

None.

## Rules

- A refund needs a reason (%s).

## Decisions from grooming

<!-- chopchop:answers -->
<!-- /chopchop:answers -->

## Assumptions

<!-- chopchop:assumptions -->
<!-- /chopchop:assumptions -->

## Open questions

<!-- chopchop:open -->
<!-- /chopchop:open -->
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        out = subprocess.run([sys.executable, str(SETUP), "--to", str(Path(self.tmp.name) / "s"), "--json"],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        info = json.loads(out.stdout)
        self.ws = Path(info["workspace"])
        self.feature = features.resolve(self.ws, "")
        self.paths = chopchop_groom.Paths(self.feature)
        self.stories = [r["id"] for r in requirement_items(self.feature.file) if r["kind"] == "story"]
        assert self.stories, "the sample has stories"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        p = Path(self.tmp.name) / name
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)

    def research(self, **extra):
        return run("--findings", self.write("f.json", findings(self.stories, **extra)), ws=self.ws)

    def write_brief(self, stories=None):
        stories = self.stories if stories is None else stories
        scope = "\n".join("- %s is built as written." % s for s in stories) or "None."
        meta, _ = features.parse_front_matter(self.paths.brief.read_text(encoding="utf-8"))
        self.paths.brief.write_text(features.render_front_matter(meta) + BRIEF % (scope, self.stories[0]), encoding="utf-8")


class Research(Base):
    def test_prepare_says_locked_and_lists_the_stories(self):
        d = json.loads(run("--prepare", "--json", ws=self.ws))
        self.assertEqual(d["mode"], "locked")
        self.assertEqual(d["requirement"]["stories"], self.stories)
        self.assertEqual(d["status"], "researching")
        self.assertIn("groomer", d["next"])

    def test_findings_write_grooming_with_a_summary_and_question_ids(self):
        text = self.research()
        self.assertIn("1 open for the developer", text)
        md = self.paths.grooming.read_text(encoding="utf-8")
        self.assertTrue(plain.has_summary(md))
        meta = features.read_front_matter(self.paths.grooming)
        self.assertEqual((meta["open_dev"], meta["open_ba"], meta["status"]), (1, 1, "questions"))
        self.assertIn("### Q1 Can a customer ask for part of the money back?", md)
        self.assertIn("### Q2 How many days after delivery can a refund be asked for?", md)
        self.assertNotIn("```", md)   # no text boxes: the BA questions are a list
        self.assertNotRegex(md, "[\u2013\u2014]")
        self.assertTrue(any(e["kind"] == "groom" for e in events.read(self.feature)))

    def test_bad_findings_are_refused_with_plain_reasons(self):
        bad = findings(self.stories)
        bad["stories"][0]["id"] = "NOPE-1"
        bad["questions"][0]["text"] = "Partial refunds"
        text = run("--findings", self.write("bad.json", bad), ws=self.ws, code=2)
        self.assertIn("NOPE-1", text)
        self.assertIn("question mark", text)
        self.assertFalse(self.paths.grooming.is_file())

    def test_a_second_research_keeps_answers_and_does_not_repeat_questions(self):
        self.research()
        run("--answer", "Q1", "--text", "Full refunds only.", ws=self.ws)
        self.research()
        state = json.loads(self.paths.state.read_text(encoding="utf-8"))
        self.assertEqual(len(state["questions"]), 2)
        self.assertEqual(state["questions"][0]["answer"], "Full refunds only.")


class Interview(Base):
    def test_answers_file_saves_a_round_and_hands_one_to_the_ba(self):
        self.research(questions=findings(self.stories)["questions"] + [
            {"text": "Should support see the reason?", "why": "The support page has no reason field.", "ask": "dev"}])
        q = json.loads(run("--questions", "dev", "--json", ws=self.ws))
        self.assertEqual([x["id"] for x in q["this_round"]], ["Q1", "Q3"])  # the blocking one first
        run("--answers", self.write("a.json", [{"id": "Q1", "text": "Full only.", "by": "dev"}, {"id": "Q3", "ask": "ba"}]),
            ws=self.ws)
        run("--round", ws=self.ws)
        meta = features.read_front_matter(self.paths.grooming)
        self.assertEqual((meta["open_dev"], meta["open_ba"], meta["status"], meta["rounds"]), (0, 2, "waiting-ba", 1))
        paste = run("--questions", "ba", ws=self.ws)
        self.assertIn("Ref: Q2", paste)
        self.assertIn("Ref: Q3", paste)
        st = stage.read(self.feature)
        self.assertEqual((st["stage"], st["waiting_on"]), ("groom", "ba"))

    def test_assume_marks_it_as_our_assumption(self):
        self.research()
        run("--answer", "Q1", "--assume", "--text", "Full refunds only.", ws=self.ws)
        state = json.loads(self.paths.state.read_text(encoding="utf-8"))
        self.assertEqual((state["questions"][0]["state"], state["questions"][0]["by"]), ("assumed", "chopchop"))

    def test_stage_waits_for_you_while_a_dev_question_is_open(self):
        st = stage.read(self.feature)
        self.assertEqual((st["stage"], st["waiting_on"]), ("groom", "chopchop"))
        self.research()
        st = stage.read(self.feature)
        self.assertEqual((st["stage"], st["waiting_on"]), ("groom", "you"))


class Brief(Base):
    def test_brief_flow_from_template_to_approved(self):
        self.research()
        text = run("--brief", ws=self.ws, code=1)
        self.assertIn("started from the template", text)
        self.write_brief(self.stories[1:])
        text = run("--brief", ws=self.ws, code=1)
        self.assertIn("story %s is not under In scope" % self.stories[0], text)
        self.assertIn("Q1 must be answered", text)
        self.write_brief()
        run("--answer", "Q1", "--text", "Full refunds only.", ws=self.ws)
        text = run("--brief", ws=self.ws)
        self.assertIn("ready for approval", text)
        body = self.paths.brief.read_text(encoding="utf-8")
        self.assertIn("| Q1 Can a customer ask for part of the money back? | Full refunds only. | developer |", body)
        self.assertIn("Q2 How many days", body)  # still open, listed
        st = stage.read(self.feature)
        self.assertEqual((st["stage"], st["waiting_on"]), ("brief", "you"))
        run("--approve", "Asha", ws=self.ws)
        st = stage.read(self.feature)
        self.assertEqual((st["stage"], st["status"]["brief_ok"]), ("design", True))

    def test_guides_go_once_sections_are_filled(self):
        self.research()
        run("--answer", "Q1", "--text", "Full only.", ws=self.ws)
        run("--brief", ws=self.ws, code=1)
        text = self.paths.brief.read_text(encoding="utf-8")
        self.assertIn("Delete these comments", text)
        meta, _ = features.parse_front_matter(text)
        filled = text.replace("## Summary\n", "## Summary\n\n- Customers can ask for a refund.\n", 1)
        self.paths.brief.write_text(filled, encoding="utf-8")
        run("--brief", ws=self.ws, code=1)  # still errors: other sections are empty
        text = self.paths.brief.read_text(encoding="utf-8")
        self.assertNotIn("Delete these comments", text)
        self.assertNotIn("3 to 5 short lines", text)  # the Summary's own hint went
        self.assertIn("One or two short paragraphs", text)  # an empty section keeps its hint
        self.assertIn("<!-- chopchop:answers -->", text)

    def test_an_answer_after_approval_marks_the_brief_changed(self):
        self.research()
        run("--answer", "Q1", "--text", "Full only.", ws=self.ws)
        run("--brief", ws=self.ws, code=1)
        self.write_brief()
        run("--brief", ws=self.ws)
        run("--approve", "Asha", ws=self.ws)
        run("--answer", "Q2", "--text", "14 days.", "--by", "ba", ws=self.ws)
        meta = features.read_front_matter(self.paths.brief)
        self.assertTrue(meta["changed_since_approval"])
        st = stage.read(self.feature)
        self.assertEqual((st["stage"], st["waiting_on"]), ("brief", "you"))

    def test_approve_refuses_a_brief_that_is_not_ready(self):
        self.research()
        run("--brief", ws=self.ws, code=1)
        text = run("--approve", "Asha", ws=self.ws, code=2)
        self.assertIn("not ready for approval", text)

    def test_long_dash_and_missing_summary_are_errors(self):
        self.research()
        run("--answer", "Q1", "--text", "Full only.", ws=self.ws)
        run("--brief", ws=self.ws, code=1)
        self.write_brief()
        p = self.paths.brief
        p.write_text(p.read_text(encoding="utf-8").replace("## Summary", "## Overview").replace(
            "A refund request", "A refund request \u2014 new"), encoding="utf-8")
        text = run("--brief", ws=self.ws, code=1)
        self.assertIn('no "## Summary"', text)
        self.assertIn("long dash", text)


class Idea(Base):
    def test_idea_makes_an_open_feature_and_rules_become_stories(self):
        text = run("--idea", "Let support staff add a note to any order. Customers never see it.", "--name", "order-notes",
                   ws=self.ws)
        self.assertIn("new, from an idea", text)
        feature = features.resolve(self.ws, "order-notes")
        self.assertTrue(str(feature.epic).startswith("IDEA-"))
        paths = chopchop_groom.Paths(feature)
        self.assertIn("Customers never see it.", paths.requirement.read_text(encoding="utf-8"))
        d = json.loads(run("--prepare", str(feature.number), "--json", ws=self.ws))
        self.assertEqual((d["mode"], d["requirement"]["stories"]), ("open", []))
        rules = [{"title": "Support can add a note to an order", "acceptance_criteria": ["A note is at most 500 characters."]},
                 {"id": "R2", "title": "Customers never see notes"}]
        run("--rules", self.write("r.json", rules), str(feature.number), ws=self.ws)
        ids = [r["id"] for r in requirement_items(paths.requirement)]
        self.assertIn("R1", ids)
        self.assertIn("R1.AC1", ids)
        self.assertIn("R2", ids)
        self.assertIn("Customers never see it.", paths.requirement.read_text(encoding="utf-8"))

    def test_rules_are_refused_for_tracker_stories(self):
        text = run("--rules", self.write("r.json", [{"title": "x y"}]), ws=self.ws, code=2)
        self.assertIn("only for ideas", text)

    def test_a_one_word_idea_is_refused(self):
        self.assertIn("few words", run("--idea", "refunds", ws=self.ws, code=2))


if __name__ == "__main__":
    unittest.main()
