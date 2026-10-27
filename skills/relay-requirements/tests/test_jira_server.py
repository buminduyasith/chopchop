"""Jira Server / Data Center: REST v2, wiki markup, startAt paging, Epic Link, bearer token."""

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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import relay_req  # noqa: E402

FIELDS = [{"id": "customfield_10100", "name": "Epic Link"},
          {"id": "customfield_10200", "name": "Acceptance Criteria"}]


def v2_issue(key, summary, desc, epic="OPS-1"):
    return {"key": key, "fields": {"summary": summary, "issuetype": {"name": "Story"}, "status": {"name": "Open"},
                                   "description": desc, "customfield_10100": epic,
                                   "customfield_10200": "* Rule *one*\n* Rule two",
                                   "comment": {"comments": [], "total": 0}}}


ISSUES = {"OPS-1": {"key": "OPS-1", "fields": {"summary": "Ops epic", "issuetype": {"name": "Epic"},
                                               "description": "h1. Goal\nKeep things _running_."}}}
CHILDREN = ["OPS-%d" % i for i in range(2, 7)]
for k in CHILDREN:
    ISSUES[k] = v2_issue(k, "Story " + k, "h2. Details\n{code}x = 1{code}")


class H(BaseHTTPRequestHandler):
    auth = set()
    jql = []

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        H.auth.add(self.headers.get("Authorization"))
        path = self.path.split("?")[0]
        if path == "/rest/api/2/field":
            return self._send(200, FIELDS)
        if path.startswith("/rest/api/2/issue/"):
            key = path.split("/")[5]
            return self._send(200, ISSUES[key]) if key in ISSUES else self._send(404, {})
        return self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/rest/api/2/search":
            H.jql.append(body["jql"])
            start, size = body["startAt"], body["maxResults"]
            keys = CHILDREN[start:start + size]
            return self._send(200, {"issues": [ISSUES[k] for k in keys], "total": len(CHILDREN), "startAt": start})
        return self._send(404, {})


class JiraServerTest(unittest.TestCase):
    def test_server_mode(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                ws = Path(tmp) / "_relay"
                ws.mkdir()
                (ws / "relay.yaml").write_text(
                    "tracker:\n  provider: jira\n  url: http://127.0.0.1:%d/\n  token: pat-123\n"
                    "  jira:\n    page_size: 2\n" % server.server_port)
                os.environ.pop("RELAY_TRACKER_EMAIL", None)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = relay_req.main(["--workspace", str(ws), "OPS-1", "--json"])
                self.assertEqual(code, 0)
                r = json.loads(out.getvalue())
                self.assertEqual(r["stories"], len(CHILDREN))                 # 3 pages of 2
                self.assertEqual(r["feature"], "001-OPS-1-ops-epic")
                self.assertTrue(H.jql[0].startswith('"Epic Link" = OPS-1'))
                self.assertIn("Bearer pat-123", H.auth)
                text = (ws / "001-OPS-1-ops-epic" / "requirements" / "requirement.md").read_text()
                for key in CHILDREN:
                    self.assertIn("## %s Story %s" % (key, key), text)
                self.assertIn("### Goal", text)                              # wiki h1 under the epic heading
                self.assertIn("Keep things *running*.", text)
                self.assertIn("##### Details", text)                         # wiki h2, under ### Description
                self.assertIn("```\nx = 1\n```", text)
                self.assertIn("- Rule **one**", text)                        # wiki AC field converted
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
