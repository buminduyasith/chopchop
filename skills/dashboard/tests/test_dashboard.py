"""The dashboard: Markdown, path safety, the API, start and stop, and the live stream."""

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(PLUGIN / "skills" / "tasks" / "scripts"))

import chopchop_dashboard  # noqa: E402
from dashlib import data, md  # noqa: E402

SCRIPT = HERE.parent / "scripts" / "chopchop_dashboard.py"
SETUP = PLUGIN / "evals" / "sample-project" / "setup.py"
GROOM = PLUGIN / "skills" / "groom" / "scripts" / "chopchop_groom.py"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def sample(tmp):
    out = subprocess.run([sys.executable, str(SETUP), "--to", str(Path(tmp) / "s"), "--json"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return Path(json.loads(out.stdout)["workspace"])


class Markdown(unittest.TestCase):
    def test_blocks(self):
        text = ("# Title\n\n## Summary\n\n- one\n- two\n  - nested\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n"
                "```python\nx = 1\n```\n\n```mermaid\nflowchart LR\n  a --> b\n```\n")
        html = md.render(text)["html"]
        self.assertIn("<h1", html)
        self.assertIn("<table", html)
        self.assertIn("<li", html)
        self.assertIn('class="mermaid"', html)
        self.assertIn("x = 1", html)

    def test_html_is_escaped(self):
        html = md.convert("Hello <script>alert(1)</script> and [x](javascript:alert(1))\n")
        self.assertNotIn("<script>", html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn("&lt;script&gt;", html)


class PrLinks(unittest.TestCase):
    def test_create_page_per_host(self):
        cases = {
            "git@github.com:acme/shop-api.git": "https://github.com/acme/shop-api/compare/feature/X-y...feature/X/build?expand=1",
            "https://gitlab.com/g/sub/repo.git": "https://gitlab.com/g/sub/repo/-/merge_requests/new?merge_request%5Bsource_branch%5D=feature%2FX%2Fbuild&merge_request%5Btarget_branch%5D=feature%2FX-y",
            "git@bitbucket.org:t/r.git": "https://bitbucket.org/t/r/pull-requests/new?source=feature%2FX%2Fbuild&dest=feature%2FX-y",
            "git@ssh.dev.azure.com:v3/org/proj/repo": "https://dev.azure.com/org/proj/_git/repo/pullrequestcreate?sourceRef=feature%2FX%2Fbuild&targetRef=feature%2FX-y",
        }
        for remote, want in cases.items():
            kind, web = data.web_base(remote)
            self.assertEqual(data.new_pr_url(kind, web, "feature/X/build", "feature/X-y"), want, remote)

    def test_a_local_remote_has_no_web_page(self):
        self.assertEqual(data.web_base("/tmp/remotes/shop-api.git"), (None, None))


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "f"
        (self.root / "design").mkdir(parents=True)
        (self.root / "design" / "design.md").write_text("# D\n", encoding="utf-8")
        (self.root / "x.yaml").write_text("a: 1\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_md_and_json_inside_the_folder(self):
        self.assertEqual(data.safe_path(self.root, "design/design.md").name, "design.md")
        for bad in ("../../chopchop.yaml", "/etc/passwd", "x.yaml", "design/../../x.md", ".hidden.md", ""):
            with self.assertRaises(data.ApiError, msg=bad):
                data.safe_path(self.root, bad)

    def test_symlink_out_is_refused(self):
        outside = Path(self.tmp.name) / "secret.md"
        outside.write_text("secret", encoding="utf-8")
        (self.root / "link.md").symlink_to(outside)
        with self.assertRaises(data.ApiError):
            data.safe_path(self.root, "link.md")


class Server(unittest.TestCase):
    """One real server on a free port, for the API, stream and broken-data checks."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ws = sample(cls.tmp.name)
        cls.feature = sorted(p for p in cls.ws.iterdir() if p.is_dir() and p.name[:3].isdigit())[0]
        work = cls.feature / "work"
        (work / "comments").mkdir(parents=True, exist_ok=True)
        (work / "comments" / "triage.json").write_text('{"items": {', encoding="utf-8")  # half written
        (work / "events.jsonl").write_text(json.dumps({"ts": "2026-11-15T10:00:00", "kind": "note", "text": "hi"}) + "\n",
                                           encoding="utf-8")
        cls.server = chopchop_dashboard.open_server(cls.ws, free_port())
        cls.server.heartbeat = 1.0
        cls.server.watcher.interval = 0.3
        cls.server.watcher.start()
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()
        cls.url = cls.server.url
        cls.number = int(cls.feature.name[:3])

    @classmethod
    def tearDownClass(cls):
        cls.server.stopping.set()
        cls.server.shutdown()
        cls.server.close()
        cls.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.url + path, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def test_features(self):
        status, body = self.get("/api/features")
        self.assertEqual(status, 200)
        rows = body["features"] if isinstance(body, dict) else body
        self.assertTrue(rows)
        for key in ("number", "title", "stage", "steps", "waiting_on", "tasks"):
            self.assertIn(key, rows[0])

    def test_feature(self):
        status, body = self.get("/api/feature/%d" % self.number)
        self.assertEqual(status, 200, body)
        for key in ("docs", "tasks", "events", "comments"):
            self.assertIn(key, body)
        self.assertEqual(self.get("/api/feature/999")[0], 404)
        self.assertIn("changes", body)   # None until there is a spec

    def test_changes_from_the_spec(self):
        spec = self.feature / "spec"
        spec.mkdir(exist_ok=True)
        (spec / "spec.json").write_text(json.dumps({"packages": [
            {"id": "P1", "repo": "payments-api", "files": [{"path": "src/a.js", "change": "new", "what": "x"},
                                                          {"path": "src/b.js", "change": "delete", "what": "y"}]}]}),
                                        encoding="utf-8")
        try:
            status, body = self.get("/api/feature/%d" % self.number)
            ch = body["changes"]
            self.assertEqual((ch["total"], ch["counts"]["new"], ch["counts"]["delete"]), (2, 1, 1))
            self.assertEqual(ch["repos"][0]["files"][0]["path"], "src/a.js")
            (spec / "spec.json").write_text("{not json", encoding="utf-8")
            self.assertIsNone(self.get("/api/feature/%d" % self.number)[1]["changes"])
        finally:
            (spec / "spec.json").unlink()

    def test_doc_and_refusals(self):
        status, body = self.get("/api/doc/%d?path=requirements/requirement.md" % self.number)
        self.assertEqual(status, 200, body)
        self.assertIn("html", body)
        self.assertGreaterEqual(self.get("/api/doc/%d?path=../chopchop.yaml" % self.number)[0], 400)
        self.assertGreaterEqual(self.get("/api/doc/%d?path=%%2Fetc%%2Fpasswd" % self.number)[0], 400)

    def test_other_routes_and_read_only(self):
        self.assertEqual(self.get("/api/prs")[0], 200)
        self.assertIn(self.get("/api/system")[0], (200, 404))
        req = urllib.request.Request(self.url + "/api/features", method="POST", data=b"x")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(e.exception.code, 405)

    def test_page(self):
        with urllib.request.urlopen(self.url + "/", timeout=5) as r:
            page = r.read().decode("utf-8")
            policy = r.headers.get("Content-Security-Policy")
        self.assertIn("<html", page.lower())
        # Code colours and diagrams load only from their pinned links, each with an integrity hash.
        self.assertIn("https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.1/highlight.min.js", policy)
        self.assertIn("https://cdn.jsdelivr.net/npm/mermaid@", policy)
        self.assertIn("HLJS_SRI", page)
        self.assertIn("function fhash(", page)  # links name a feature by its folder
        self.assertIn("function changesTab(", page)

    def test_stream_sends_changed(self):
        got = []

        def listen():
            with urllib.request.urlopen(self.url + "/api/stream", timeout=10) as r:
                for raw in r:
                    line = raw.decode("utf-8").strip()
                    if line == "event: changed":
                        got.append(line)
                        return

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        time.sleep(0.8)
        (self.feature / "requirements" / "note.md").write_text("## Summary\n\n- touched %s\n" % time.time(), encoding="utf-8")
        t.join(8)
        self.assertEqual(got, ["event: changed"])


class StartStop(unittest.TestCase):
    def test_start_status_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = sample(tmp)
            base = [sys.executable, str(SCRIPT), "--workspace", str(ws), "--json"]
            port = str(free_port())
            out = subprocess.run(base + ["--start", "--no-open", "--port", port], capture_output=True, text=True, timeout=40)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            started = json.loads(out.stdout)
            try:
                self.assertTrue(started["running"])
                self.assertTrue(started["url"].startswith("http://127.0.0.1:"))
                again = json.loads(subprocess.run(base + ["--start", "--no-open"], capture_output=True, text=True,
                                                  timeout=40).stdout)
                self.assertTrue(again["already"])
                self.assertEqual(again["url"], started["url"])
                status = json.loads(subprocess.run(base + ["--status"], capture_output=True, text=True, timeout=20).stdout)
                self.assertEqual((status["running"], status["url"]), (True, started["url"]))
            finally:
                subprocess.run(base + ["--stop"], capture_output=True, text=True, timeout=30)
            status = json.loads(subprocess.run(base + ["--status"], capture_output=True, text=True, timeout=20).stdout)
            self.assertFalse(status["running"])


if __name__ == "__main__":
    unittest.main()
