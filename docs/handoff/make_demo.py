"""Fill the demo workspace with hand-made review data, events, a second feature and a PR without a feature."""
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ws = Path(sys.argv[1])
feat = ws / "001-IDEA-1-refund-requests"
now = datetime.now().replace(microsecond=0)


def at(minutes):
    return (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")


def sha(body, replies=()):
    return hashlib.sha1((body + "".join(r["body"] for r in replies)).encode()).hexdigest()


def thread(tid, pr, repo, kind, file, line, author, body, replies=(), minutes=120, bot=False, resolved=False, outdated=False):
    num = tid.split(":")[1]
    owner_repo = "acme/%s" % repo
    n = pr.split("#")[1]
    return {"id": tid, "pr": pr, "repo": repo, "kind": kind, "file": file, "line": line,
            "hunk": "@@ -%d,6 +%d,9 @@" % (max(1, (line or 3) - 2), max(1, (line or 3) - 2)) if file else None,
            "author": author, "bot": bot, "created": at(minutes), "updated": at(max(1, minutes - 20)),
            "resolved": resolved, "outdated": outdated,
            "url": "https://github.com/%s/pull/%s#discussion_%s" % (owner_repo, n, num),
            "body": body, "replies": list(replies), "hash": sha(body, replies)}


prs = {"prs": [
    {"id": "shop-api#12", "repo": "shop-api", "host": "github", "slug": "acme/shop-api", "number": 12,
     "url": "https://github.com/acme/shop-api/pull/12", "title": "Refund requests: service rules and routes", "state": "open",
     "draft": False, "head": "feature/IDEA-1/build", "base": "feature/IDEA-1-refund-requests", "author": "bumindu",
     "review": "changes-requested", "fetched": at(6), "threads": 5},
    {"id": "shop-web#7", "repo": "shop-web", "host": "github", "slug": "acme/shop-web", "number": 7,
     "url": "https://github.com/acme/shop-web/pull/7", "title": "Refund form and status on the order page", "state": "open",
     "draft": True, "head": "feature/IDEA-1/build", "base": "feature/IDEA-1-refund-requests", "author": "bumindu",
     "review": "commented", "fetched": at(6), "threads": 3}],
    "watch": {"on": True, "since": at(180), "last": at(6)}}

T = [
    thread("shop-api#12:r2001", "shop-api#12", "shop-api", "inline", "src/services/orderService.js", 88, "asha",
           "A reason made of spaces only passes this check. `'   '.length` is 3, so it gets saved as a refund reason.",
           [{"author": "bumindu", "body": "Looking into it.", "created": at(150)}], 170),
    thread("shop-api#12:r2002", "shop-api#12", "shop-api", "inline", "src/routes/orderRoutes.js", 41, "asha",
           "Should we trim the note here as well? Same problem as the reason I think.", (), 165),
    thread("shop-api#12:r2003", "shop-api#12", "shop-api", "inline", "src/services/orderService.js", 121, "marco",
           "This will let a customer approve their own refund. I do not see a role check anywhere in decideRefund.", (), 140),
    thread("shop-api#12:r2004", "shop-api#12", "shop-api", "review", None, None, "marco",
           "Nice and small. Tests read well. One thing: can we add a version check on save so two support agents cannot decide at the same time?", (), 135),
    thread("shop-api#12:r2005", "shop-api#12", "shop-api", "inline", "test/services/orderService.refundRequest.test.js", 14, "review-bot",
           "Consider using `buildOrder` from test/helpers/fixtures.js instead of an inline object.", (), 200, bot=True, outdated=True),
    thread("shop-web#7:r3110", "shop-web#7", "shop-web", "inline", "src/views/orderDetailView.js", 63, "asha",
           "The form lets me submit an empty reason. The button should stay disabled until there is real text.", (), 90),
    thread("shop-web#7:r3111", "shop-web#7", "shop-web", "inline", "src/api/ordersApi.js", 27, "priya",
           "Why POST and not PUT for approve and reject? Just asking, the design may say so.", (), 80),
    thread("shop-web#7:r3112", "shop-web#7", "shop-web", "general", None, None, "priya",
           "I get a blank status for orders that were refunded before this change. Is that expected?\n\nSteps: open order o-9 as support.", (), 12),
]
threads = {"fetched": at(6), "threads": T}
by = {t["id"]: t for t in T}


def item(tid, plain, verdict, priority, group, why, evidence, fix, impact, reply, decision=None, state="triaged", commit=None):
    return {"plain": plain, "verdict": verdict, "priority": priority, "group": group, "why": why, "evidence": evidence,
            "fix": fix, "impact": impact, "reply": reply, "decision": decision, "state": state,
            "hash": by[tid]["hash"], "commit": commit}


items = {
    "shop-api#12:r2001": item("shop-api#12:r2001", "A reason of only spaces is saved as a real reason.", "real", "high", "G1",
        "Line 88 checks the length before it trims. Rule R-1 says 1 to 200 characters after trimming.",
        ["shop-api/src/services/orderService.js:88", "spec/spec.md#r-1"],
        "Trim first, then check the length. Add the test rejects_reason_of_only_spaces.",
        "Only this check. The route and the DTO do not change.",
        "Good catch. The check now trims first, and there is a test for a reason of only spaces."),
    "shop-api#12:r2002": item("shop-api#12:r2002", "The note has the same gap: it is checked before it is trimmed.", "real", "medium", "G1",
        "The note goes through the same helper as the reason, so the same fix covers it.",
        ["shop-api/src/services/orderService.js:131"],
        "Use the same trimmed check for the note. Add the test stores_a_null_note_when_only_spaces.",
        "Approve and reject both use it.",
        "Yes, same gap. Fixed with the reason check, in one commit.", decision="fix", state="fixing"),
    "shop-web#7:r3110": item("shop-web#7:r3110", "The form sends an empty reason, because the button is never disabled.", "real", "high", "G1",
        "The view enables the button on any input event. It should look at the trimmed value.",
        ["shop-web/src/views/orderDetailView.js:63"],
        "Disable the button while the trimmed reason is empty. Mirror the 200 character limit.",
        "Only the refund form. The cancel form is not touched.",
        "Fixed: the button stays disabled until the reason has real text."),
    "shop-api#12:r2003": item("shop-api#12:r2003", "The reviewer thinks a customer can approve a refund. That is not so.", "false-positive", "medium", "G2",
        "decideRefund is only called by approveRefund and rejectRefund. Both refuse a customer with 403 before the order is loaded.",
        ["shop-api/src/services/orderService.js:104-110", "shop-api/test/services/orderService.refundDecision.test.js:58"],
        "No code change. Maybe add a one-line comment on decideRefund that the callers check the role.",
        "None.",
        "The role check is in approveRefund and rejectRefund (lines 104 to 110), before the order is loaded. There is a test for it: rejects with FORBIDDEN when the caller is a customer."),
    "shop-api#12:r2004": item("shop-api#12:r2004", "The reviewer likes the PR, and asks for a version check on save.", "negotiable", "low", "G3",
        "The design parks the version check for all order actions (section 4, out of scope). It is fair, but it is a bigger change.",
        ["design/design.md#4-scope"],
        "Not in this PR. Open a follow-up story for a version check on every order action.",
        "It would touch cancel as well, so it needs its own design.",
        "Thanks. The version check is parked in the design, because it covers cancel as well. I opened a follow-up for it.",
        decision="reply", state="replied"),
    "shop-api#12:r2005": item("shop-api#12:r2005", "A bot asks to use the shared test helper. That code is already changed.", "outdated", "low", None,
        "The auto run fixed this in round 2. The comment sits on old code.",
        ["shop-api/test/models/order.test.js:90"], "Nothing to do.", "None.",
        "Done in a1cf8fc.", decision="skip", state="closed"),
    "shop-web#7:r3111": item("shop-web#7:r3111", "A question: why POST and not PUT for approve and reject.", "question", "low", None,
        "The design picks POST, to match the cancel endpoint that already exists.",
        ["design/design.md#7-contract-changes", "shop-api/src/routes/orderRoutes.js:16"],
        "No code change.", "None.",
        "POST matches the cancel endpoint (POST /api/orders/:id/cancel), and the design keeps the two the same on purpose."),
}
groups = [
    {"id": "G1", "title": "Text of only spaces passes the checks", "plain": "Three comments say the same thing: the reason and the note are checked before they are trimmed, in the API and in the form.",
     "threads": ["shop-api#12:r2001", "shop-api#12:r2002", "shop-web#7:r3110"], "verdict": "real", "priority": "high",
     "fix": "Trim first, then check the length, in the service. Mirror it in the form.", "impact": "The service check and the refund form. No contract change.",
     "files": ["shop-api/src/services/orderService.js", "shop-web/src/views/orderDetailView.js"], "order": 1, "with": []},
    {"id": "G2", "title": "The role check is there, in the callers", "plain": "One reviewer missed that approve and reject refuse customers before decideRefund runs.",
     "threads": ["shop-api#12:r2003"], "verdict": "false-positive", "priority": "medium",
     "fix": "No code change. A short comment may help the next reader.", "impact": "None.",
     "files": ["shop-api/src/services/orderService.js"], "order": 2, "with": []},
    {"id": "G3", "title": "A version check on save", "plain": "Fair, but the design parks it, because it covers every order action.",
     "threads": ["shop-api#12:r2004"], "verdict": "negotiable", "priority": "low",
     "fix": "A follow-up story.", "impact": "Cancel as well.", "files": [], "order": 3, "with": []},
]
store = feat / "work" / "comments"
store.mkdir(parents=True, exist_ok=True)
(store / "prs.json").write_text(json.dumps(prs, indent=1))
(store / "threads.json").write_text(json.dumps(threads, indent=1))
(store / "triage.json").write_text(json.dumps({"updated": at(5), "items": items, "groups": groups}, indent=1))

events = [
    (60 * 26, "design", "The design is approved by Trial Lead", {"by": "Trial Lead"}),
    (60 * 25, "spec", "The spec is ready: 9 rules, 4 packages"), (60 * 25 - 10, "tasks", "4 tasks cut in 2 waves"),
    (60 * 24, "run", "The automatic build started", {"by": "bumindu"}),
    (60 * 24 - 2, "build", "Building T01", {"task": "T01", "repo": "shop-api"}),
    (60 * 24 - 4, "review", "Review round 1: 1 fix asked", {"task": "T01"}),
    (60 * 24 - 5, "fix", "The builder fixed 1 item", {"task": "T01"}),
    (60 * 24 - 6, "commit", "T01 committed as a1cf8fc", {"task": "T01", "repo": "shop-api"}),
    (60 * 24 - 9, "commit", "T02 committed as e4d721b", {"task": "T02", "repo": "shop-api"}),
    (60 * 24 - 11, "commit", "T03 committed", {"task": "T03", "repo": "shop-web"}),
    (60 * 24 - 13, "commit", "T04 committed", {"task": "T04", "repo": "shop-web"}),
    (60 * 24 - 14, "push", "Pushed feature/IDEA-1/build", {"repo": "shop-api"}),
    (60 * 24 - 14, "push", "Pushed feature/IDEA-1/build", {"repo": "shop-web"}),
    (180, "pr", "PR opened: shop-api#12", {"repo": "shop-api"}), (179, "pr", "PR opened: shop-web#7 (draft)", {"repo": "shop-web"}),
    (60, "comment", "7 review comments read from 2 PRs"), (55, "triage", "7 comments explained in 3 groups"),
    (30, "reply", "Reply drafted and posted for the version check", {"by": "bumindu"}),
    (12, "comment", "1 new review comment on shop-web#7"),
]
lines = []
for ev in events:
    e = {"ts": at(ev[0]), "kind": ev[1], "text": ev[2]}
    if len(ev) > 3:
        e.update(ev[3])
    lines.append(json.dumps(e))
(feat / "work" / "events.jsonl").write_text("\n".join(lines) + "\n")

# record the PR links where the auto run keeps them
auto = json.loads((feat / "work" / "auto.json").read_text())
auto["repos"]["shop-api"]["pr"] = "https://github.com/acme/shop-api/pull/12"
auto["repos"]["shop-web"]["pr"] = "https://github.com/acme/shop-web/pull/7"
(feat / "work" / "auto.json").write_text(json.dumps(auto, indent=2))

# a second feature that waits on a person
f2 = ws / "002-PAY-140-partial-refunds"
(f2 / "requirements").mkdir(parents=True, exist_ok=True)
(f2 / "work").mkdir(exist_ok=True)
(f2 / "requirements" / "requirement.md").write_text(
    '---\nfeature: "002"\nepic: "PAY-140"\ntitle: "Partial refunds"\nstories: 2\n---\n\n# Partial refunds\n\n'
    '## PAY-141 Refund part of an order\n\nAs support, I want to refund part of an order, so a customer keeps the items they like.\n\n'
    '- AC1: support picks the lines to refund.\n- AC2: the refund total is never more than what was paid.\n')
(f2 / "requirements" / "grooming.md").write_text(
    '---\nmode: "locked"\nstatus: "answered"\nquestions: 3\nopen_dev: 0\nopen_ba: 0\nupdated: "%s"\n---\n# Grooming · Partial refunds\n\n'
    '## Summary\n\n- **What we found:** the order model has one amount field, so line refunds need a new shape.\n'
    '- **Questions:** 3 asked, 3 answered.\n\n## Questions\n\n| # | Question | Answer | By |\n| --- | --- | --- | --- |\n'
    '| Q1 | Can one line be refunded twice? | No. | dev |\n| Q2 | Who may refund? | Support only. | ba |\n| Q3 | Do we move money? | No, finance does. | ba |\n' % at(40))
(f2 / "requirements" / "brief.md").write_text(
    '---\ntitle: "Partial refunds"\nstatus: "draft"\napproved_by: null\napproved_on: null\nchanged_since_approval: false\n---\n# Brief · Partial refunds\n\n'
    '## Summary\n\n- **What:** support can refund some lines of a delivered order, not only the whole order.\n'
    '- **Why:** today a customer must send everything back to get any money.\n'
    '- **How big:** 2 repos, about 5 tasks.\n\n## In scope\n\n- [x] PAY-141 AC1: support picks the lines.\n- [x] PAY-141 AC2: never more than what was paid.\n\n'
    '## Out of scope\n\n- [ ] Moving the money. Finance does that.\n\n## How it fits\n\n```mermaid\nflowchart LR\n  support([Support]) --> page[Order page]\n  page --> api[shop-api]\n  api --> store[(orders)]\n```\n')
(f2 / "work" / "events.jsonl").write_text("\n".join(json.dumps(e) for e in [
    {"ts": at(90), "kind": "groom", "text": "2 stories read from PAY-140"},
    {"ts": at(70), "kind": "question", "text": "Q2 asked: who may refund?"},
    {"ts": at(45), "kind": "answer", "text": "Q2 answered by the BA", "by": "ba"},
    {"ts": at(40), "kind": "brief", "text": "The brief is written. It waits for your yes."}]) + "\n")

# a PR that has no feature
loose = ws / "prs" / "acme-shop-api-31" / "work" / "comments"
loose.mkdir(parents=True, exist_ok=True)
lt = [thread("shop-api#31:r5001", "shop-api#31", "shop-api", "inline", "src/app.js", 22, "marco",
             "This timeout is in seconds here, but the config says milliseconds.", (), 300),
      thread("shop-api#31:r5002", "shop-api#31", "shop-api", "general", None, None, "asha", "Looks good to me otherwise.", (), 280)]
(loose / "prs.json").write_text(json.dumps({"prs": [
    {"id": "shop-api#31", "repo": "shop-api", "host": "github", "slug": "acme/shop-api", "number": 31,
     "url": "https://github.com/acme/shop-api/pull/31", "title": "Add a request timeout", "state": "open", "draft": False,
     "head": "chore/timeout", "base": "develop", "author": "bumindu", "review": "commented", "fetched": at(200), "threads": 2}],
    "watch": {"on": False}}, indent=1))
(loose / "threads.json").write_text(json.dumps({"fetched": at(200), "threads": lt}, indent=1))
(loose / "triage.json").write_text(json.dumps({"updated": at(190), "items": {
    "shop-api#31:r5001": {"plain": "The timeout uses the wrong unit, so it is 1000 times too long.", "verdict": "real", "priority": "high",
                          "group": None, "why": "config.timeoutMs is 5000 and line 22 multiplies it by 1000.",
                          "evidence": ["shop-api/src/app.js:22", "shop-api/src/config.js:9"], "fix": "Drop the multiply.",
                          "impact": "Only the server timeout.", "reply": "Right, fixed: the value is already in milliseconds.",
                          "decision": None, "state": "triaged", "hash": lt[0]["hash"], "commit": None},
    "shop-api#31:r5002": {"plain": "The reviewer is happy with the rest.", "verdict": "praise", "priority": "low", "group": None,
                          "why": "No change is asked.", "evidence": [], "fix": "", "impact": "", "reply": "Thanks.",
                          "decision": None, "state": "triaged", "hash": lt[1]["hash"], "commit": None}}, "groups": []}, indent=1))
print("demo data written in", ws)
