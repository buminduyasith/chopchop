"""The design script end to end, on the refunds sample project (4 git repos with traps)."""

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

import chopchop_design  # noqa: E402  (puts the tasks scripts on the path)
from chopchoplib import board, events, features, plain  # noqa: E402

SETUP = PLUGIN / "evals" / "sample-project" / "setup.py"


def sample(tmp):
    out = subprocess.run([sys.executable, str(SETUP), "--to", str(Path(tmp) / "s"), "--json"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def run(main, *argv, code=0, ws=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        got = main(list(argv) + (["--workspace", ws] if ws else []))
    text = out.getvalue() + err.getvalue()
    assert got == code, "exit %s, wanted %s\n%s" % (got, code, text)
    return text


def options_json(first):
    c = "payments-api/%s@" + first[:7]
    return {
        "understood": {"text": "Customers ask for a refund of a card payment within 30 days. "
                               "Refunds start as pending. A support agent can cancel one while it is pending.",
                       "confidence": "high"},
        "follow": [{"text": "Refund status changes copy order cancel.", "cite": c % "src/orders/cancel/OrderCancelService.java:12-17"},
                   {"text": "The refund job copies the payout job and its retry rule.", "cite": c % "src/payouts/PayoutJob.java:6-11"}],
        "leave": [{"text": "CardClient has no retry wrapper. We add refund() the same way.", "why": "Not this feature.",
                   "cite": c % "src/provider/CardClient.java:4"}],
        "choices": [
            {"kind": "decision", "question": "Where does refund status live?", "why": "It decides the migration.",
             "options": [{"key": "A", "title": "A new refunds table", "fit": "follows", "fit_note": "Follows order_cancellations",
                          "rows": {"Touches": "1 migration, 3 new files", "Undo": "Drop the table"}},
                         {"key": "B", "title": "A status column on payments", "fit": "bends",
                          "fit_note": "payments has no status columns today", "rows": {"Touches": "1 migration, 4 changed files"}}],
             "recommended": "A", "reason": "It copies order cancel and leaves the busy payments table alone.",
             "picked": "A", "picked_by": "you"},
            {"kind": "conflict", "question": "Which error shape do refunds use?", "why": "Two shapes exist.",
             "options": [{"key": "A", "title": "ApiError", "fit": "follows", "fit_note": "Follows order cancel"},
                         {"key": "B", "title": "ProblemDetail", "fit": "breaks", "fit_note": "Only payouts use it."}],
             "recommended": "A", "reason": "The order page already reads ApiError.", "picked": None},
        ],
        "for_lead": [{"text": "Should the ledger hear refund.done in this release?", "owner": "@ledger-team"}],
        "parked": [{"text": "Partial refunds.", "why": "Out of scope from round 1."}],
    }


def architecture():
    return {"version": 2, "title": "Refunds for card payments",
            "nodes": [{"id": "agent", "name": "Support agent", "kind": "person", "row": 0, "col": 0},
                      {"id": "customer", "name": "Customer", "kind": "person", "row": 1, "col": 0},
                      {"id": "page", "name": "Order page", "kind": "ui", "repo": "web-app", "status": "changed", "row": 1, "col": 1},
                      {"id": "api", "name": "Refund API", "kind": "api", "repo": "payments-api", "status": "new", "row": 1, "col": 2},
                      {"id": "db", "name": "refunds table", "kind": "table", "repo": "payments-api", "status": "new", "row": 2, "col": 2}],
            "links": [{"from": "customer", "to": "page", "label": "asks for refund"},
                      {"from": "page", "to": "api", "label": "POST refunds"},
                      {"from": "api", "to": "db", "label": "saves pending", "kind": "data"},
                      {"from": "agent", "to": "api", "label": "cancels refund"}]}


def flow(answer_all=True):
    messages = [
        {"n": 1, "from": "customer", "to": "page", "kind": "person", "say": "clicks Refund",
         "line": "The customer clicks Refund on the order page.", "stories": ["PAY-121"],
         "failure": {"twice": "The button turns off after one click.", "caller": "Only the order's owner sees it."}},
        {"n": 2, "from": "page", "to": "api", "kind": "call", "say": "POST /refunds",
         "line": "web-app calls the new refund API.", "stories": ["PAY-121"],
         "failure": {"fails": "Refund not sent. Try again.", "slow": "5 s timeout.", "twice": "Idempotency key.",
                     "caller": "403 unless the owner."}},
        {"n": 3, "from": "api", "to": "db", "kind": "db", "say": "saves as pending",
         "line": "The API checks the 30 day window and saves the refund as pending.", "stories": ["PAY-121.AC1"],
         "failure": {"fails": "Rolls back. 500.", "twice": "One open refund per payment."}},
        {"n": 4, "from": "agent", "to": "api", "kind": "call", "say": "cancels while pending",
         "line": "A support agent cancels a refund while it is pending.", "stories": ["PAY-122"],
         "failure": {"fails": "409 if already sent.", "slow": "5 s timeout.", "twice": "Second cancel does nothing.",
                     "caller": {"risk": "Any support agent can cancel.", "accepted_by": "Asha"}}},
    ]
    if not answer_all:
        messages[2]["failure"].pop("twice")
    return {"version": 2, "title": "Request a refund", "participants": ["customer", "agent", "page", "api", "db"],
            "messages": messages}


DESIGN_BODY = """# Design · Refunds for card payments

## 1. Summary and the ask

Customers can ask for a refund of a card payment from the order page. A support agent can cancel it while it is pending.

**The ask:** approve refunds that start as pending and use a new refunds table.
**Size:** 2 repos, about 6 tasks in 3 waves.

<!-- talk: an old speaker note. Slides are gone, and a comment like this one is simply ignored. -->

## 2. High-level design

<!-- chopchop:architecture -->
<!-- /chopchop:architecture -->

## 3. Why

- Today refunds are done by hand. `payments-api/src/legacy/LegacyRefundNote.java:3@{first}`
- Order cancel already has a pending state. `payments-api/src/orders/cancel/OrderCancelService.java:12-17@{first}`
- Payouts run from a job with retries. `payments-api/src/payouts/PayoutJob.java:6-11@{first}`

## 4. Scope

In scope: PAY-121, PAY-122.

Out of scope: partial refunds.

## 5. Main flow and errors

The customer asks, the API saves the refund as pending, and an agent can cancel it.

<!-- chopchop:flow -->
<!-- /chopchop:flow -->

## 6. Data changes

| Table | Change |
| --- | --- |
| refunds | New table |

## 7. Contract changes

| API | Change |
| --- | --- |
| POST /refunds | New |

## 8. Key decisions

<!-- chopchop:decisions -->
<!-- /chopchop:decisions -->

## 9. Impact and rollout

- web-app and payments-api change. A flag hides the button until both are out.

## 10. Risks

- The card timeout grew to 15 s. `payments-api/src/provider/CardClient.java:4@{first}`

## 11. How we prove it

| Level | Count |
| --- | --- |
| Unit | 8 |

## 12. Questions, assumptions, approval

None.

<!-- chopchop:approval -->
<!-- /chopchop:approval -->

## Likely questions

### Why not a status column on payments?
payments is the busiest table and has no status columns today.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        info = sample(self.tmp.name)
        self.root = Path(info["root"])
        self.ws = info["workspace"]
        self.first = info["commits"]["payments-api"]["first"]
        self.feature = features.resolve(self.ws, "")
        self.paths = chopchop_design.Paths(self.feature)

    def tearDown(self):
        self.tmp.cleanup()

    def design(self, *argv, code=0):
        return run(chopchop_design.main, *argv, code=code, ws=self.ws)

    def write_inputs(self, opts=None, fl=None, body=None):
        self.design("--scaffold", "--size", "medium")
        self.paths.work.mkdir(parents=True, exist_ok=True)
        self.paths.options.write_text(json.dumps(opts or options_json(self.first)))
        self.paths.arch.write_text(json.dumps(architecture()))
        self.paths.flow.write_text(json.dumps(fl or flow()))
        meta, _ = chopchop_design.read_design(self.paths)
        chopchop_design.write_design(self.paths, meta, (body or DESIGN_BODY).replace("{first}", self.first[:7]))


class PrepareTest(Base):
    def test_prepare_on_a_new_feature(self):
        d = json.loads(self.design("--prepare", "--json"))
        self.assertEqual(d["requirements"]["stories"], ["PAY-121", "PAY-122"])
        self.assertTrue(d["helpers"]["ask"])  # an old chopchop.yaml has no agents block: ask once
        self.assertEqual(d["helpers"]["max"], 3)
        self.assertFalse(d["system_map"]["exists"])
        self.assertFalse(d["design"]["exists"])
        text = self.design("--prepare")
        self.assertIn("not set yet: ask the 3 helper questions once", text)
        self.assertIn("no system map yet", text)

    def test_helpers_are_saved_once_and_keep_the_rest(self):
        cfg = Path(self.ws) / "chopchop.yaml"
        before = cfg.read_text()
        self.design("--helpers", "--max", "2", "--model", "sonnet", "--effort", "high")
        after = cfg.read_text()
        self.assertTrue(after.startswith(before.rstrip("\n")))
        self.assertIn("agents:\n  max: 2", after)
        self.assertEqual((Path(self.ws) / "chopchop.yaml.bak").read_text(), before)
        d = json.loads(self.design("--prepare", "--json"))
        self.assertFalse(d["helpers"]["ask"])
        self.assertEqual(d["helpers"]["calls"]["explorer"], {"model": "sonnet", "effort": "high"})
        self.design("--helpers", "--max", "4")
        self.assertEqual(cfg.read_text().count("agents:"), 1)
        self.assertIn("max: 4", cfg.read_text())
        self.assertIn("model must be one of", self.design("--helpers", "--model", "gpt-9", code=2))

    def test_plan_line(self):
        self.design("--helpers", "--max", "2")
        line = self.design("--plan", "medium", "--repos", "payments-api,web-app,notify-service")
        self.assertIn("Using 6 helpers: 3 explorers (payments-api, web-app, notify-service), 1 architect, 2 reviewers.", line)
        self.assertIn("At most 2 at once, so the explorers run in 2 turns.", line)
        self.assertIn("Using 1 helper: 1 reviewer.", self.design("--plan", "small", "--repos", "web-app"))
        self.assertIn("They run on the same model as this chat, the default effort.", line)
        self.assertNotIn("not saved yet", line)
        self.design("--helpers", "--model", "sonnet", "--effort", "high")
        self.assertIn("They run on sonnet, effort high.", self.design("--plan", "small", "--repos", "web-app"))

    def test_plan_warns_when_settings_were_never_saved(self):
        line = self.design("--plan", "medium", "--repos", "web-app")
        self.assertIn("Helper settings are not saved yet: ask the 3 helper questions before starting any helper.", line)

    def test_plan_refuses_a_repo_that_is_not_in_the_config(self):
        out = self.design("--plan", "medium", "--repos", "web-app", "nosuch", code=2)
        self.assertIn("Error: Not in chopchop.yaml: nosuch. Repos: ledger-service, notify-service, payments-api, web-app.", out)
        self.assertIn("Not in chopchop.yaml: nosuch, other.", self.design("--plan", "small", "--repos", "nosuch,other", code=2))

    def test_prepare_names_the_brief_and_the_grooming(self):
        text = self.design("--prepare")
        self.assertNotIn("Brief:", text)
        self.assertNotIn("Grooming:", text)
        req = self.feature.path / "requirements"
        (req / "brief.md").write_text(features.render_front_matter(
            {"title": "Refunds", "status": "approved", "approved_by": "Dana", "approved_on": "2026-11-14",
             "changed_since_approval": False}) + "# Brief\n\n## Summary\n\n- Refunds for card payments.\n")
        (req / "grooming.md").write_text("# Grooming\n\n## Summary\n\n- 3 questions, all answered.\n")
        text = self.design("--prepare")
        self.assertIn("Brief:    %s (approved by Dana). Read it first: it wins on what to build." % (req / "brief.md"), text)
        self.assertIn("Grooming: %s. Its answers are decisions already made: do not ask them again." % (req / "grooming.md"), text)
        d = json.loads(self.design("--prepare", "--json"))
        self.assertEqual((d["brief"]["exists"], d["brief"]["approved_by"], d["grooming"]["exists"]), (True, "Dana", True))
        self.assertEqual(d["files"]["brief"], str(req / "brief.md"))


class BuildTest(Base):
    def test_build_blocks_then_passes(self):
        self.write_inputs()
        out = self.design("--build", code=1)
        self.assertIn("Blocks:   choice 1 not picked yet", out)
        self.assertIn("citation payments-api/src/legacy/LegacyRefundNote.java:3@", out)
        self.assertIn("is gone", out)
        self.assertIn("CardClient.java:4@", out)  # changed: a warning, not a block
        # the moved citation was fixed to the new lines at HEAD
        body = self.paths.design.read_text()
        self.assertIn("PayoutJob.java:11-16@", body)
        self.assertNotIn("PayoutJob.java:6-11@", body)
        self.assertIn("PayoutJob.java:11-16@", self.paths.options.read_text())
        # generated blocks
        self.assertIn("flowchart LR", body)
        self.assertIn("sequenceDiagram", body)
        self.assertIn("subgraph g_payments_api[payments-api]", body)
        self.assertIn("1. The customer clicks Refund on the order page. _(PAY-121)_", body)
        self.assertIn("| 4 | cancels while pending _(call between parts)_ |", body)
        self.assertIn("Accepted risk: Any support agent can cancel. (by Asha)", body)
        self.assertIn("**Who must approve:**", body)
        self.assertIn("- @pay-team (payments-api changes)", body)
        self.assertIn("- @web-team (web-app changes)", body)
        opts_md = self.paths.options_md.read_text()
        for h in ("## 1. What I understood", "## 2. Patterns we follow", "## 3. We leave alone", "## 4. Conflicts",
                  "## 5. Decisions", "## 6. For the lead", "## 7. Parked"):
            self.assertIn(h, opts_md)
        self.assertIn("### Choice 1: Which error shape do refunds use?", opts_md)  # conflicts come first
        self.assertIn("### Choice 2: Where does refund status live?", opts_md)
        # fix: drop the gone citation, pick the conflict
        body = body.replace("- Today refunds are done by hand. `payments-api/src/legacy/LegacyRefundNote.java:3@%s`\n" % self.first[:7], "")
        self.paths.design.write_text(body)
        out = self.design("--pick", "1=A")
        self.assertIn("Result:   ready for review", out)
        # the review message is in the build report now: there is no page to put it on
        self.assertIn("Message:  send this to the lead with the design", out)
        self.assertIn("  Design for review: Refunds for card payments (PAY-120)", out)
        self.assertIn("  The ask: approve refunds that start as pending and use a new refunds table.", out)
        self.assertIn("  Key choices: ApiError; A new refunds table.", out)
        self.assertIn("  For @ledger-team: Should the ledger hear refund.done", out)
        self.assertIn("  Who must approve: @pay-team; @web-team; @ledger-team", out)
        self.assertIn("  Read: design/design.md in 001-PAY-120-refunds-for-card-payments", out)
        report = json.loads(self.paths.build.read_text())
        self.assertTrue(report["ready"])
        self.assertIn("The ask: approve refunds", report["message"])
        self.assertNotIn("page", report)
        self.assertEqual(list(self.feature.path.rglob("*.html")), [])  # Markdown only
        # every Markdown file it writes starts with a Summary
        self.assertEqual(plain.summary_points(self.paths.options_md.read_text()), [
            "What: 2 choices before the design: 1 conflict in the code, 1 decision.", "Picked: 2 of 2",
            "For the lead: 1 point", "Parked: 1 idea, kept for later"])
        self.assertTrue(plain.has_summary(self.paths.design.read_text()))  # section 1 is the Summary
        self.assertNotIn("speaker notes", out)
        log = [(e["kind"], e["text"]) for e in events.read(self.feature)]
        self.assertEqual(log[0][0], "design")
        self.assertIn("block the approval request", log[0][1])
        self.assertEqual(log[1:], [("design", "Choice 1 is now A, picked by you."),
                                   ("design", "Design built: ready for review.")])

    def test_missing_failure_answer_blocks(self):
        self.write_inputs(fl=flow(answer_all=False))
        self.paths.design.write_text(self.paths.design.read_text().replace("LegacyRefundNote", "OrderCancelService"))
        out = self.design("--build", code=1)
        self.assertIn("message 3 (saves as pending) has no answer for: Runs twice", out)
        self.assertIn("⚠ **No answer yet.**", self.paths.design.read_text())
        failures = self.design("--failures")
        self.assertIn("MISSING", failures)

    def test_broken_inputs_exit_2(self):
        self.write_inputs()
        bad = options_json(self.first)
        bad["choices"][0]["options"] = bad["choices"][0]["options"][:1]
        self.paths.options.write_text(json.dumps(bad))
        self.assertIn("needs 2 or 3 options", self.design("--build", code=2))
        self.paths.options.write_text("{not json")
        self.assertIn("is not valid JSON", self.design("--build", code=2))
        fl = flow()
        fl["messages"][0]["to"] = "nowhere"
        self.paths.options.write_text(json.dumps(options_json(self.first)))
        self.paths.flow.write_text(json.dumps(fl))
        self.assertIn("message 1: to 'nowhere' is not a participant", self.design("--build", code=2))

    def test_lint_catches_missing_story_dash_and_headings(self):
        body = DESIGN_BODY.replace("In scope: PAY-121, PAY-122.", "In scope: PAY-121.").replace(
            "Out of scope: partial refunds.", "Out of scope: partial refunds — later.").replace("## 7. Contract changes", "## 7. Contracts")
        self.write_inputs(body=body.replace("LegacyRefundNote.java:3", "OrderCancelService.java:12-17"))
        out = self.design("--build", code=1)
        self.assertIn("story PAY-122 is not in section 4 (Scope)", out)
        self.assertIn("has a long dash", out)
        self.assertIn("Missing: 7. Contract changes", out)
        self.assertNotIn("Message:", out)  # nothing to send while something blocks it

    def test_no_summary_section_blocks(self):
        self.write_inputs(body=DESIGN_BODY.replace("## 1. Summary and the ask", "## 1. The ask")
                          .replace("LegacyRefundNote.java:3", "OrderCancelService.java:12-17"))
        out = self.design("--build", code=1)
        self.assertIn("Missing: 1. Summary and the ask", out)
        self.assertFalse(plain.has_summary(self.paths.design.read_text()))

    def test_open_starts_the_dashboard_or_names_the_file(self):
        self.assertIn("No design.md yet", self.design("--open", code=2))
        self.write_inputs()
        fake = self.root / "fake_dashboard.py"
        fake.write_text("print('Dashboard: http://127.0.0.1:4599/')\n")
        real = board.DASHBOARD
        try:
            board.DASHBOARD = fake
            self.assertEqual(self.design("--open").strip(), "Dashboard: http://127.0.0.1:4599/")
            board.DASHBOARD = self.root / "no-dashboard.py"
            self.assertEqual(self.design("--open").strip(),
                             "Read:     %s (no dashboard skill next to this one)" % self.paths.design)
        finally:
            board.DASHBOARD = real


class PickAndApproveTest(Base):
    def ready(self):
        opts = options_json(self.first)
        opts["choices"][1]["picked"], opts["choices"][1]["picked_by"] = "A", "chopchop"
        body = DESIGN_BODY.replace("- Today refunds are done by hand. `payments-api/src/legacy/LegacyRefundNote.java:3@{first}`\n", "")
        self.write_inputs(opts=opts, body=body)
        self.design("--build")

    def test_approve_pick_and_reapprove(self):
        self.ready()
        body = self.paths.design.read_text()
        self.assertIn("Choice 1: Which error shape do refunds use? chopchop picked A, ApiError.", body)  # an assumption
        self.assertIn("Assumed by chopchop: please confirm.", body)
        self.assertIn("needs at least one --note", self.design("--approve", "Asha", "--result", "conditions", code=2))
        out = self.design("--approve", "Asha", "--result", "conditions", "--note", "Ledger hears refund.done in release 2.")
        self.assertIn("approved-with-conditions by Asha", out)
        meta, _ = chopchop_design.read_design(self.paths)
        self.assertEqual((meta["status"], meta["version"]), ("approved-with-conditions", 1))
        self.assertTrue((self.paths.approved / "design-v1.md").is_file())
        self.assertIn("- Condition: Ledger hears refund.done in release 2.", self.paths.design.read_text())
        # the lead changes a pick: the design is marked changed since approval
        out = self.design("--pick", "2=B", "--by", "lead")
        self.assertIn("Picked:   choice 2 = B (lead)", out)
        meta, body = chopchop_design.read_design(self.paths)
        self.assertTrue(meta["changed_since_approval"])
        self.assertIn("Changed since the last approval", body)
        self.assertIn("| 2 | Where does refund status live? | B. A status column on payments | Picked by the lead.", body)
        out = self.design("--approve", "Asha", "--result", "approved")
        self.assertIn("File:     %s" % self.paths.design, out)
        self.assertIn("Next:     /chopchop:spec", out)
        meta, _ = chopchop_design.read_design(self.paths)
        self.assertEqual((meta["status"], meta["version"], meta["changed_since_approval"]), ("approved", 2, False))
        self.assertTrue((self.paths.approved / "design-v2.md").is_file())
        log = [(e["kind"], e["text"], e.get("by")) for e in events.read(self.feature)]
        self.assertEqual(log, [
            ("design", "Design built: ready for review.", None),
            ("approve", "Design approved with conditions by Asha (version 1).", "Asha"),
            ("design", "Choice 2 is now B, picked by lead.", "lead"),
            ("design", "Design built: ready for review.", None),
            ("approve", "Design approved by Asha (version 2).", "Asha")])

    def test_changes_needed_and_not_ready(self):
        self.write_inputs()
        self.assertIn("not ready for approval", self.design("--approve", "Asha", "--result", "approved", code=2))
        self.design("--approve", "Asha", "--result", "changes", "--note", "Use cents, not decimals.")
        meta, body = chopchop_design.read_design(self.paths)
        self.assertEqual(meta["status"], "changes-needed")
        self.assertIn("- Use cents, not decimals.", body)
        self.assertIn("Design:   changes-needed", self.design("--status"))
        last = events.read(self.feature)[-1]
        self.assertEqual((last["kind"], last["text"], last["by"]),
                         ("design", "Asha asked for changes to the design: Use cents, not decimals.", "Asha"))


if __name__ == "__main__":
    unittest.main()
