"""End to end: a fake Jira server, the real CLI, a temp workspace."""

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

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import relay_req  # noqa: E402
from relaylib.sync import split_front_matter  # noqa: E402


def adf(*paras):
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paras]}


def issue(key, summary, desc, status="To Do", parent="PAY-120", itype="Story", ac=None, points=None, comments=None,
          comment_total=None):
    fields = {
        "summary": summary, "issuetype": {"name": itype}, "status": {"name": status},
        "priority": {"name": "High"}, "assignee": None, "reporter": {"displayName": "BA One"},
        "labels": ["payments"], "components": [{"name": "refunds"}], "fixVersions": [],
        "parent": {"key": parent} if parent else None, "created": "2026-09-10T09:00:00.000+0530",
        "updated": "2026-09-20T09:00:00.000+0530", "description": desc, "subtasks": [], "issuelinks": [],
        "attachment": [{"filename": "flow.png", "content": "http://x/flow.png", "mimeType": "image/png", "size": 2048}],
        "comment": {"comments": comments or [], "total": comment_total if comment_total is not None else len(comments or [])},
    }
    if ac is not None:
        fields["customfield_10035"] = ac
    if points is not None:
        fields["customfield_10016"] = points
    return {"key": key, "fields": fields}


class FakeJira:
    def __init__(self):
        self.issues = {}
        self.children = []
        self.all_comments = {}
        self.auth_seen = set()
        self.requests = []

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
                fake.requests.append(("GET", u.path))
                if u.path == "/rest/api/3/myself":
                    return self._send(200, {"displayName": "Test User"})
                if u.path == "/rest/api/3/field":
                    return self._send(200, [{"id": "summary", "name": "Summary"},
                                            {"id": "customfield_10035", "name": "Acceptance Criteria"},
                                            {"id": "customfield_10016", "name": "Story point estimate"}])
                parts = u.path.split("/")
                if u.path.startswith("/rest/api/3/issue/") and u.path.endswith("/comment"):
                    key = parts[5]
                    return self._send(200, {"comments": fake.all_comments.get(key, [])})
                if u.path.startswith("/rest/api/3/issue/"):
                    key = parts[5]
                    assert "fields" in parse_qs(u.query)
                    if key in fake.issues:
                        return self._send(200, fake.issues[key])
                    return self._send(404, {"errorMessages": ["Issue does not exist"]})
                return self._send(404, {})

            def do_POST(self):
                fake.auth_seen.add(self.headers.get("Authorization"))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(("POST", self.path))
                if self.path == "/rest/api/3/search/jql":
                    assert body["jql"].startswith("parent = PAY-120"), body["jql"]
                    size = body["maxResults"]
                    start = int(body.get("nextPageToken") or 0)
                    keys = fake.children[start:start + size]
                    nxt = start + size
                    page = {"issues": [fake.issues[k] for k in keys]}
                    if nxt < len(fake.children):
                        page["nextPageToken"] = str(nxt)
                        page["isLast"] = False
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


class JiraEndToEnd(unittest.TestCase):
    def setUp(self):
        self.fake = FakeJira()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.fake.handler())
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "_relay"
        self.ws.mkdir()
        (self.ws / "relay.yaml").write_text(
            "tracker:\n  provider: jira\n  url: http://127.0.0.1:%d\n  email: ${T_EMAIL}\n  token: ${T_TOKEN}\n"
            "  jira:\n    deployment: cloud\n    page_size: 2\n    max_comments: 10\n" % self.server.server_port)
        os.environ["T_EMAIL"] = "dev@acme.io"
        os.environ["T_TOKEN"] = "secret"

        f = self.fake
        f.issues["PAY-120"] = issue("PAY-120", "Refunds for customers", adf("Let customers get money back."),
                                    parent=None, itype="Epic")
        f.issues["PAY-121"] = issue("PAY-121", "Customer can request a refund", adf("As a customer I want a refund."),
                                    ac=adf("Button shows for 30 days.", "Minimum 0.01."), points=5.0,
                                    comments=[{"author": {"displayName": "BA One"}, "created": "2026-09-17T12:40:00.000+0530",
                                               "body": adf("30 days from payment date.")}], comment_total=2)
        f.all_comments["PAY-121"] = [
            {"author": {"displayName": "BA One"}, "created": "2026-09-17T12:40:00.000+0530", "body": adf("30 days from payment date.")},
            {"author": {"displayName": "Dev Two"}, "created": "2026-09-18T10:00:00.000+0530", "body": adf("What about partial?")}]
        f.issues["PAY-122"] = issue("PAY-122", "Admin sees refund list", adf("Admins see all refunds."))
        f.issues["PAY-123"] = issue("PAY-123", "Refund export", adf("CSV export."))
        f.issues["PAY-200"] = issue("PAY-200", "Shared: audit log", adf("Log every refund."), parent="OPS-1")
        f.children = ["PAY-121", "PAY-122", "PAY-123"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def story(self, feature, sid):
        return (self.ws / "features" / feature / "requirements" / "stories" / ("%s.md" % sid)).read_text()

    def test_full_cycle(self):
        # doctor
        code, out, _ = run("--workspace", str(self.ws), "doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("Test User", out)
        self.assertIn("Basic " + base64.b64encode(b"dev@acme.io:secret").decode(), self.fake.auth_seen)

        # 1. first pull: epic + one extra story
        code, out, err = run("--workspace", str(self.ws), "pull", "--epic", "PAY-120", "--stories", "PAY-200", "--json")
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        feature = "PAY-120-refunds-for-customers"
        self.assertEqual(r["feature"], feature)
        self.assertEqual(sorted(r["new"]), ["PAY-121", "PAY-122", "PAY-123", "PAY-200"])
        self.assertEqual(sorted(r["needs_analysis"]), ["PAY-121", "PAY-122", "PAY-123", "PAY-200"])
        s121 = self.story(feature, "PAY-121")
        meta, body = split_front_matter(s121)
        self.assertEqual(meta["story_points"], 5)
        self.assertEqual(meta["analysis"], "pending")
        self.assertIn("### Acceptance criteria (as written in the tracker)", body)
        self.assertIn("Minimum 0.01.", body)
        self.assertIn("### Comments (2)", body)          # fetched the full comment list
        self.assertIn("What about partial?", body)
        fdir = self.ws / "features" / feature
        self.assertTrue((fdir / "feature.yaml").is_file())
        self.assertTrue((fdir / "requirements" / "questions.md").is_file())
        overview = (fdir / "requirements" / "overview.md").read_text()
        self.assertIn("**Epic:** [PAY-120]", overview)
        self.assertIn("| [PAY-121](stories/PAY-121.md) |", overview)

        # 2. the agent analyses PAY-121, a person adds a note
        edited = s121.replace("_Not analysed yet._", "- **PAY-121.AC1** Button shows for 30 days.\n- **PAY-121.AC2** Minimum 0.01.")
        edited = edited.replace("<!-- keep -->\n<!-- /keep -->", "<!-- keep -->\nOld orders have no date.\n<!-- /keep -->")
        (fdir / "requirements" / "stories" / "PAY-121.md").write_text(edited)
        code, out, _ = run("--workspace", str(self.ws), "mark-analysed", "--feature", "PAY-120", "--all")
        self.assertEqual(code, 0)
        self.assertIn("Still to analyse: none", out)

        # 3. the BA changes things in Jira
        f = self.fake
        f.issues["PAY-121"]["fields"]["customfield_10035"] = adf("Button shows for 30 days.", "Minimum 1.00.")
        f.issues["PAY-122"]["fields"]["status"] = {"name": "In Progress"}
        f.issues["PAY-124"] = issue("PAY-124", "Refund email", adf("Email when done."))
        f.children = ["PAY-121", "PAY-122", "PAY-124"]  # PAY-123 left the epic

        code, out, err = run("--workspace", str(self.ws), "pull", "--feature", "PAY-120", "--json")
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual(r["changed"], ["PAY-121"])
        self.assertEqual(r["meta"], ["PAY-122"])
        self.assertEqual(r["new"], ["PAY-124"])
        self.assertEqual(r["removed"], ["PAY-123"])
        self.assertEqual(r["unchanged"], ["PAY-200"])      # extra id is still synced on re-sync
        self.assertEqual(sorted(r["needs_analysis"]), ["PAY-121", "PAY-124"])   # status-only and unchanged stay analysed

        s121 = self.story(feature, "PAY-121")
        meta, body = split_front_matter(s121)
        self.assertEqual(meta["analysis"], "stale")
        self.assertIn("- **PAY-121.AC1** Button shows for 30 days.", body)   # agent work kept
        self.assertIn("Old orders have no date.", body)                        # keep block kept
        self.assertIn("Minimum 1.00.", body)                                  # source refreshed
        self.assertIn("**Changed in the tracker** (acceptance_criteria)", body)
        report = (fdir / "requirements" / "sync-report.md").read_text()
        self.assertIn("-Minimum 0.01.\n+Minimum 1.00.", report)
        self.assertIn("status: To Do → In Progress", report)
        meta123, body123 = split_front_matter(self.story(feature, "PAY-123"))
        self.assertEqual(meta123["analysis"], "removed")
        self.assertIn("**Removed.**", body123)

        # 4. re-analysis clears the flag
        code, out, _ = run("--workspace", str(self.ws), "mark-analysed", "--feature", "PAY-120", "--stories", "PAY-121")
        meta, body = split_front_matter(self.story(feature, "PAY-121"))
        self.assertEqual(meta["analysis"], "done")
        self.assertNotIn("Changed in the tracker", body)

        # 5. dry run writes nothing
        before = self.story(feature, "PAY-121")
        f.issues["PAY-121"]["fields"]["summary"] = "Customer can request a full or partial refund"
        code, out, _ = run("--workspace", str(self.ws), "pull", "--feature", "PAY-120", "--dry-run", "--json")
        self.assertEqual(json.loads(out)["changed"], ["PAY-121"])
        self.assertEqual(before, self.story(feature, "PAY-121"))

    def test_story_list_and_missing(self):
        code, out, err = run("--workspace", str(self.ws), "pull", "--stories", "PAY-200, NOPE-1", "--json")
        self.assertEqual(code, 2)
        self.assertIn("needs a feature name", err)
        code, out, err = run("--workspace", str(self.ws), "pull", "--stories",
                             "http://127.0.0.1/browse/PAY-200,NOPE-1", "--feature", "audit", "--json")
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual(r["new"], ["PAY-200"])
        self.assertEqual(r["missing"], ["NOPE-1"])
        self.assertEqual(r["source"]["ids"], ["NOPE-1", "PAY-200"])
        overview = (self.ws / "features" / "audit" / "requirements" / "overview.md").read_text()
        self.assertIn("Built from a list of stories", overview)

    def test_ingest_raw_for_mcp_mode(self):
        raw_epic = dict(self.fake.issues["PAY-120"])
        raw_121 = dict(self.fake.issues["PAY-121"], names={"customfield_10035": "Acceptance Criteria",
                                                            "customfield_10016": "Story point estimate"})
        path = Path(self.tmp.name) / "mcp.json"
        path.write_text(json.dumps({"epic": raw_epic, "issues": [raw_121]}))
        requests_before = len(self.fake.requests)
        code, out, err = run("--workspace", str(self.ws), "ingest", "--input", str(path), "--format", "raw", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.fake.requests), requests_before)   # no REST calls in MCP mode
        r = json.loads(out)
        self.assertEqual(r["new"], ["PAY-121"])
        body = self.story("PAY-120-refunds-for-customers", "PAY-121")
        self.assertIn("Minimum 0.01.", body)                         # custom field found by name
        self.assertIn("**Points:** 5", body)

    def test_auth_error_is_friendly(self):
        os.environ["T_TOKEN"] = ""
        code, out, err = run("--workspace", str(self.ws), "pull", "--epic", "PAY-120")
        self.assertEqual(code, 2)
        self.assertIn("RELAY_TRACKER_TOKEN", err)


class FileProviderTest(unittest.TestCase):
    def test_file_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "_relay"
            (ws / "stories").mkdir(parents=True)
            (ws / "relay.yaml").write_text("tracker:\n  provider: file\n  path: stories\n")
            (ws / "stories" / "E-1.json").write_text(json.dumps({"id": "E-1", "title": "Epic", "children": ["S-1"]}))
            (ws / "stories" / "S-1.json").write_text(json.dumps({"id": "S-1", "title": "One", "description": "Text"}))
            (ws / "stories" / "S-2.json").write_text(json.dumps({"id": "S-2", "title": "Two", "parent": "E-1"}))
            code, out, err = run("--workspace", str(ws), "pull", "--epic", "E-1", "--json")
            self.assertEqual(code, 0, err)
            self.assertEqual(sorted(json.loads(out)["new"]), ["S-1", "S-2"])
            code, out, _ = run("--workspace", str(ws), "features")
            self.assertIn("E-1-epic", out)


if __name__ == "__main__":
    unittest.main()
