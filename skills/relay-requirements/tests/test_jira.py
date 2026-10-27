"""End to end: a fake Jira Cloud server, the real CLI, a temp workspace."""

import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import relay_req  # noqa: E402
from relaylib.features import parse_front_matter  # noqa: E402


def adf(*paras):
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paras]}


def issue(key, summary, desc, status="To Do", parent="PAY-120", itype="Story", ac=None, points=None):
    fields = {
        "summary": summary, "issuetype": {"name": itype}, "status": {"name": status},
        "priority": {"name": "High"}, "assignee": None, "reporter": {"displayName": "BA One"},
        "labels": ["payments"], "components": [{"name": "refunds"}], "fixVersions": [],
        "parent": {"key": parent} if parent else None, "created": "2026-09-10T09:00:00.000+0530",
        "updated": "2026-09-20T09:00:00.000+0530", "description": desc, "subtasks": [], "issuelinks": [],
        "attachment": [{"filename": "flow.png", "content": "http://x/flow.png", "mimeType": "image/png", "size": 2048}],
        "comment": {"comments": [{"author": {"displayName": "BA One"}, "created": "2026-09-17T12:40:00.000+0530",
                                  "body": adf("A comment.")}], "total": 1},
    }
    if ac is not None:
        fields["customfield_10035"] = ac
    if points is not None:
        fields["customfield_10016"] = points
    return {"key": key, "fields": fields}


class FakeJira:
    def __init__(self):
        self.issues = {}
        self.children = {}  # epic -> [keys]
        self.auth_seen = set()
        self.field_requests = []

    def handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                fake.auth_seen.add(self.headers.get("Authorization"))
                u = urlparse(self.path)
                if u.path == "/rest/api/3/myself":
                    return self._send(200, {"displayName": "Test User"})
                if u.path == "/rest/api/3/field":
                    return self._send(200, [{"id": "summary", "name": "Summary"},
                                            {"id": "customfield_10035", "name": "Acceptance Criteria"},
                                            {"id": "customfield_10016", "name": "Story point estimate"}])
                if u.path.startswith("/rest/api/3/issue/"):
                    key = u.path.split("/")[5]
                    fake.field_requests.append(parse_qs(u.query).get("fields", [""])[0])
                    if key in fake.issues:
                        return self._send(200, fake.issues[key])
                    return self._send(404, {"errorMessages": ["Issue does not exist"]})
                return self._send(404, {})

            def do_POST(self):
                fake.auth_seen.add(self.headers.get("Authorization"))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/rest/api/3/search/jql":
                    epic = body["jql"].split()[2]
                    keys_all = fake.children.get(epic, [])
                    size = body["maxResults"]
                    start = int(body.get("nextPageToken") or 0)
                    page = {"issues": [fake.issues[k] for k in keys_all[start:start + size]]}
                    if start + size < len(keys_all):
                        page.update(nextPageToken=str(start + size), isLast=False)
                    else:
                        page["isLast"] = True
                    return self._send(200, page)
                return self._send(404, {})

        return H


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = relay_req.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class JiraSyncTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeJira()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.fake.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "_relay"
        self.ws.mkdir()
        self.write_config()
        os.environ["T_EMAIL"] = "dev@acme.io"
        os.environ["T_TOKEN"] = "secret"

        f = self.fake
        f.issues["PAY-120"] = issue("PAY-120", "Refunds for customers", adf("Let customers get money back."),
                                    parent=None, itype="Epic")
        f.issues["PAY-121"] = issue("PAY-121", "Customer can request a refund", adf("As a customer I want a refund."),
                                    ac=adf("Button shows for 30 days.", "Minimum 0.01."), points=5.0)
        f.issues["PAY-122"] = issue("PAY-122", "Agent approves refunds", adf("Agents approve big refunds."))
        f.issues["PAY-123"] = issue("PAY-123", "Refund email | receipt", adf("Send an email."))
        f.children["PAY-120"] = ["PAY-121", "PAY-122", "PAY-123"]

        f.issues["LOY-1"] = issue("LOY-1", "Loyalty points", adf("Points for every order."), parent=None, itype="Epic")
        f.issues["LOY-2"] = issue("LOY-2", "Earn points", adf("1 point per dollar."), parent="LOY-1")
        f.children["LOY-1"] = ["LOY-2"]

    def write_config(self, extra=""):
        (self.ws / "relay.yaml").write_text(
            "tracker:\n  provider: jira\n  url: http://127.0.0.1:%d\n  email: ${T_EMAIL}\n  token: ${T_TOKEN}\n%s"
            "  jira:\n    deployment: cloud\n    page_size: 2\n" % (self.server.server_port, extra))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def cli(self, *argv, expect=0):
        code, out, err = run("--workspace", str(self.ws), *argv)
        self.assertEqual(code, expect, "exit %s\nstdout:\n%s\nstderr:\n%s" % (code, out, err))
        return out, err

    def req(self, folder="001-PAY-120-refunds-for-customers"):
        return (self.ws / folder / "requirements" / "requirement.md").read_text(encoding="utf-8")

    # ------------------------------------------------------------------ create

    def test_first_sync_creates_numbered_folder_with_one_file(self):
        out, _ = self.cli("PAY-120")
        self.assertIn("001-PAY-120-refunds-for-customers  (new feature)", out)
        folder = self.ws / "001-PAY-120-refunds-for-customers"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["requirements"])
        self.assertEqual(sorted(p.name for p in (folder / "requirements").iterdir()), ["requirement.md"])

        text = self.req()
        meta, body = parse_front_matter(text)
        self.assertEqual(meta["feature"], "001")
        self.assertEqual(meta["epic"], "PAY-120")
        self.assertEqual(meta["stories"], 3)
        self.assertEqual(meta["created"], meta["synced"])
        self.assertIn("# Refunds for customers", body)
        self.assertIn("Let customers get money back.", body)
        # every story, as is, in Jira rank order
        self.assertLess(body.index("## PAY-121 Customer can request a refund"), body.index("## PAY-122 "))
        self.assertLess(body.index("## PAY-122 "), body.index("## PAY-123 "))
        self.assertIn("As a customer I want a refund.", body)
        self.assertIn("### Acceptance criteria\n\nButton shows for 30 days.\n\nMinimum 0.01.", body)
        self.assertIn("**Points:** 5", body)
        self.assertIn("- [flow.png](http://x/flow.png) (2 KB)", body)
        self.assertIn("| PAY-123 | Refund email \\| receipt | Story | To Do | - | - |", body)
        # comments are off by default: not requested, not written
        self.assertNotIn("A comment.", body)
        self.assertTrue(all("comment" not in f.split(",") for f in self.fake.field_requests))
        self.assertIn("## Sync history\n\n- **%s** first sync: 3 stories" % meta["synced"][:10], body)
        self.assertIn("Basic " + base64.b64encode(b"dev@acme.io:secret").decode(), self.fake.auth_seen)

    def test_same_epic_again_resyncs_instead_of_new_folder(self):
        self.cli("PAY-120")
        out, _ = self.cli("PAY-120")
        self.assertIn("001-PAY-120-refunds-for-customers  (no changes)", out)
        self.assertEqual(sorted(p.name for p in self.ws.iterdir() if p.is_dir()), ["001-PAY-120-refunds-for-customers"])

    def test_numbers_go_up_and_custom_name(self):
        self.cli("PAY-120")
        out, _ = self.cli("https://acme.atlassian.net/browse/loy-1", "--name", "Points & Rewards")
        self.assertIn("002-LOY-1-points-rewards", out)
        self.assertTrue((self.ws / "002-LOY-1-points-rewards" / "requirements" / "requirement.md").is_file())
        out, _ = self.cli("LOY-1", "--name", "other")
        self.assertIn("--name ignored", out)

    def test_number_skips_numbers_used_by_features_without_requirements(self):
        (self.ws / "007-old-feature" / "design").mkdir(parents=True)
        out, _ = self.cli("PAY-120")
        self.assertIn("008-PAY-120-refunds-for-customers", out)

    # ------------------------------------------------------------------ resync

    def test_resync_no_changes_leaves_file_untouched(self):
        self.cli("PAY-120")
        before = self.req()
        out, _ = self.cli("-rs", "1")
        self.assertIn("(no changes)", out)
        self.assertIn("nothing changed in the tracker", out)
        self.assertEqual(self.req(), before)

    def test_resync_reports_every_kind_of_change(self):
        self.cli("PAY-120")
        created = parse_front_matter(self.req())[0]["created"]
        f = self.fake
        f.issues["PAY-121"]["fields"]["status"] = {"name": "In Progress"}           # status only
        f.issues["PAY-122"]["fields"]["description"] = adf("Agents approve refunds over 500.")
        f.issues["PAY-122"]["fields"]["customfield_10035"] = adf("Over 500 needs approval.")
        f.issues["PAY-130"] = issue("PAY-130", "Partial refunds", adf("Refund part of an order."))
        f.children["PAY-120"] = ["PAY-121", "PAY-122", "PAY-130"]                    # PAY-123 removed

        out, _ = self.cli("-rs", "PAY-120")
        self.assertIn("(updated)", out)
        self.assertIn("3 total · 1 added · 1 changed · 1 status/details · 1 removed · 0 unchanged", out)
        self.assertIn("Added:    PAY-130 Partial refunds", out)
        self.assertIn("Changed:  PAY-122 Agent approves refunds (description, acceptance criteria)", out)
        self.assertIn("Status:   PAY-121 Customer can request a refund (To Do to In Progress)", out)
        self.assertIn("Removed:  PAY-123 Refund email | receipt (no longer in the epic)", out)

        meta, body = parse_front_matter(self.req())
        self.assertEqual(meta["created"], created)
        self.assertEqual(meta["stories"], 3)
        self.assertIn("Agents approve refunds over 500.", body)
        self.assertNotIn("## PAY-123", body)
        history = body[body.index("## Sync history"):]
        self.assertIn("  - Added: PAY-130 Partial refunds", history)
        self.assertIn("  - Removed from epic: PAY-123 Refund email | receipt", history)
        self.assertLess(history.index("resync"), history.index("first sync"))      # newest first

        # and a second resync right after is a no-op again
        out, _ = self.cli("-rs", "1")
        self.assertIn("(no changes)", out)

    def test_report_has_before_and_after_text(self):
        self.cli("PAY-120")
        f = self.fake
        f.issues["PAY-121"]["fields"]["customfield_10035"] = adf("Button shows for 14 days.", "Minimum 0.01.")
        f.issues["PAY-121"]["fields"]["status"] = {"name": "Ready"}
        f.issues["PAY-130"] = issue("PAY-130", "Partial refunds", adf("Refund part of an order."))
        f.children["PAY-120"] = ["PAY-121", "PAY-122", "PAY-130"]
        out, _ = self.cli("-rs", "1", "--json")
        d = json.loads(out)["changes"]
        changed = d["changed"][0]
        self.assertEqual((changed["from"], changed["to"]), ("To Do", "Ready"))
        self.assertIn("-Button shows for 30 days.", changed["diff"])
        self.assertIn("+Button shows for 14 days.", changed["diff"])
        self.assertNotIn("relay:story", changed["diff"])
        self.assertIn("Refund part of an order.", d["added"][0]["text"])
        self.assertIn("Send an email.", d["removed"][0]["text"])
        self.assertIn("(acceptance criteria; status To Do to Ready)", self.req())

        f.issues["PAY-122"]["fields"]["summary"] = "Agent approves all refunds"
        out, _ = self.cli("-rs", "1", "--diff")
        self.assertIn("Changed:  PAY-122 Agent approves all refunds (title)\n"
                      "          @@ -1,2 +1,2 @@\n"
                      "          -## PAY-122 Agent approves refunds\n"
                      "          +## PAY-122 Agent approves all refunds", out)

    def test_dry_run_writes_nothing(self):
        out, _ = self.cli("PAY-120", "--dry-run")
        self.assertIn("Dry run", out)
        self.assertFalse((self.ws / "001-PAY-120-refunds-for-customers").exists())
        self.cli("PAY-120")
        before = self.req()
        self.fake.issues["PAY-121"]["fields"]["summary"] = "Renamed"
        out, _ = self.cli("-rs", "--dry-run")
        self.assertIn("Changed:  PAY-121 Renamed (title)", out)
        self.assertEqual(self.req(), before)

    def test_hand_edits_are_overwritten_with_a_note(self):
        self.cli("PAY-120")
        path = self.ws / "001-PAY-120-refunds-for-customers" / "requirements" / "requirement.md"
        path.write_text(self.req().replace("Send an email.", "Send an email. MY NOTE"), encoding="utf-8")
        out, _ = self.cli("-rs")
        self.assertIn("(file rewritten (no tracker changes))", out)
        self.assertNotIn("MY NOTE", self.req())

    def test_comments_when_enabled(self):
        self.write_config()
        cfg = (self.ws / "relay.yaml").read_text().replace("page_size: 2\n", "page_size: 2\n    include_comments: true\n")
        (self.ws / "relay.yaml").write_text(cfg)
        self.cli("PAY-120")
        self.assertIn("### Comments\n\n**BA One**, 2026-09-17\n\nA comment.", self.req())

    # ------------------------------------------------------------------ picking a feature

    def test_resync_refs(self):
        self.cli("PAY-120")
        for ref in (["-rs"], ["-rs", "1"], ["-rs", "001"], ["-rs", "pay-120"], ["-rs", "refund"],
                    ["-rs", "001-PAY-120-refunds-for-customers"], ["PAY-120", "-rs"]):
            out, _ = self.cli(*ref)
            self.assertIn("001-PAY-120-refunds-for-customers  (no changes)", out, ref)

        self.cli("LOY-1")
        _, err = self.cli("-rs", expect=2)
        self.assertIn("Which feature?", err)
        self.assertIn("001  PAY-120", err)
        self.assertIn("002  LOY-1", err)
        _, err = self.cli("-rs", "9", expect=2)
        self.assertIn("No feature matches '9'", err)
        _, err = self.cli("-rs", "o", expect=2)
        self.assertIn("matches more than one feature", err)

        out, _ = self.cli("-rs", "all")
        self.assertIn("001-PAY-120-refunds-for-customers  (no changes)", out)
        self.assertIn("002-LOY-1-loyalty-points  (no changes)", out)

    def test_list_and_resolve(self):
        out, _ = self.cli("--list")
        self.assertIn("No features yet", out)
        self.cli("PAY-120")
        self.cli("LOY-1")
        out, _ = self.cli("--list")
        self.assertIn("001  PAY-120    001-PAY-120-refunds-for-customers ", out)
        self.assertIn("002  LOY-1      002-LOY-1-loyalty-points", out)
        out, _ = self.cli("--resolve", "2")
        self.assertEqual(json.loads(out)["epic"], "LOY-1")
        out, _ = self.cli("--list", "--json")
        self.assertEqual([f["number"] for f in json.loads(out)], ["001", "002"])

    # ------------------------------------------------------------------ errors and mcp

    def test_errors(self):
        _, err = self.cli("not-a-key!", expect=2)
        self.assertIn("does not look like an epic key", err)
        _, err = self.cli("PAY-999", expect=2)
        self.assertIn("Not found", err)
        _, err = self.cli("--list", "-rs", expect=2)
        self.assertIn("one of", err)
        _, err = self.cli(expect=2)
        self.assertIn("Give an epic key", err)

    def test_mcp_mode_uses_ingest(self):
        self.write_config("  mode: mcp\n")
        _, err = self.cli("PAY-120", expect=2)
        self.assertIn("--ingest", err)
        f = self.fake
        names = {"customfield_10035": "Acceptance Criteria", "customfield_10016": "Story point estimate"}
        payload = {"epic": dict(f.issues["PAY-120"], names=names),
                   "issues": [dict(f.issues[k], names=names) for k in f.children["PAY-120"]]}
        path = Path(self.tmp.name) / "issues.json"
        path.write_text(json.dumps(payload))
        out, _ = self.cli("--ingest", str(path))
        self.assertIn("001-PAY-120-refunds-for-customers  (new feature)", out)
        self.assertIn("Button shows for 30 days.", self.req())
        out, _ = self.cli("--ingest", str(path))
        self.assertIn("(no changes)", out)
        # --rest still works in mcp mode, and sees the same content
        out, _ = self.cli("-rs", "1", "--rest")
        self.assertIn("(no changes)", out)


if __name__ == "__main__":
    unittest.main()
