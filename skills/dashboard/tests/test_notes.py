"""The reviewer's notes: the checks, the file, the copy block, and the /api/notes route on a real server."""

import http.client
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(PLUGIN / "skills" / "tasks" / "scripts"))

import chopchop_dashboard  # noqa: E402
from dashlib import data, notes  # noqa: E402

SETUP = PLUGIN / "evals" / "sample-project" / "setup.py"
FOLDER = "002-IDEA-2-dashboard-comments"
DOC = "requirements/requirement.md"


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


def small_workspace(tmp):
    """One feature with two documents: enough for notes.get and notes.save."""
    ws = Path(tmp) / "_chopchop"
    feature = ws / FOLDER
    (feature / "requirements").mkdir(parents=True)
    (feature / "design").mkdir()
    (feature / "requirements" / "requirement.md").write_text("# Requirement\n", encoding="utf-8")
    (feature / "design" / "design.md").write_text("# Design\n", encoding="utf-8")
    return ws, feature


def text_note(k=1, **more):
    note = {"id": "n-lq3k9x-%d" % k, "text": "Should this be per feature?", "created": "2026-11-17T10:02:11Z",
            "heading": "4. Scope > In scope", "quote": "one list per document",
            "before": "are saved in `work/.dashboard-notes.json`, ", "after": ".", "match": 0}
    note.update(more)
    return note


def box_note(k=2, **more):
    note = {"id": "n-lq3kb2-%d" % k, "text": "Split this box in two?", "created": "2026-11-17T10:04:40Z",
            "heading": "2. High-level design", "diagram": "High-level design", "box": "notesroute",
            "label": "Notes route"}
    note.update(more)
    return note


class Store(unittest.TestCase):
    """notes.py on a small workspace, without a server."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws, self.feature = small_workspace(self.tmp.name)
        self.file = self.feature / "work" / ".dashboard-notes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def stored(self):
        return json.loads(self.file.read_text(encoding="utf-8"))

    def test_two_notes_on_one_quote_are_both_kept(self):
        got = notes.clean({"notes": [text_note(1, match=0), text_note(2, match=1)]})
        self.assertEqual([(n["quote"], n["match"]) for n in got], [("one list per document", 0), ("one list per document", 1)])
        self.assertNotIn("line", got[0])

    def test_clean_refuses_bad_notes(self):
        bad = [
            [text_note(text="   ")],
            [text_note(text="x" * 2001)],
            [text_note(quote="q" * 1001)],
            [text_note(line=12)],
            [box_note(box="a b")],
            [box_note(box="notesroute\n")],
            [text_note(id="n-abc-1\n")],
            [text_note(k) for k in range(201)],
        ]
        for case in bad:
            with self.assertRaises(data.ApiError, msg=str(case)[:80]) as e:
                notes.clean({"notes": case})
            self.assertIn(e.exception.status, (400, 413))
        with self.assertRaises(data.ApiError) as e:
            notes.clean({"notes": [text_note(1), text_note(2), text_note(3, text="")]})
        self.assertEqual(str(e.exception), "Note 3: the text is empty.")
        with self.assertRaises(data.TooBig) as e:
            notes.clean({"notes": [text_note(k) for k in range(201)]})
        self.assertEqual(str(e.exception), "Too many notes: 200 per document at most.")

    def test_empty_list_removes_the_document(self):
        notes.save(self.ws, 2, DOC, {"notes": [text_note()]})
        notes.save(self.ws, 2, "design/design.md", {"notes": [box_note()]})
        out = notes.save(self.ws, 2, DOC, {"notes": []})
        self.assertEqual((out["notes"], out["block"]), ([], ""))
        docs = self.stored()["docs"]
        self.assertNotIn(DOC, docs)
        self.assertEqual(len(docs["design/design.md"]), 1)

    def test_broken_file_moves_to_bad(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text("{not json", encoding="utf-8")
        notes.save(self.ws, 2, DOC, {"notes": [text_note()]})
        bad = self.file.with_name(".dashboard-notes.json.bad")
        self.assertEqual(bad.read_text(encoding="utf-8"), "{not json")
        self.assertEqual(self.stored(), {"version": 1, "docs": {DOC: [text_note()]}})

    def test_failed_replace_keeps_the_old_file(self):
        notes.save(self.ws, 2, DOC, {"notes": [text_note()]})
        before = self.file.read_bytes()
        with mock.patch("pathlib.Path.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                notes.save(self.ws, 2, DOC, {"notes": [box_note()]})
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(self.stored()["docs"][DOC], [text_note()])

    def test_two_saves_at_once_leave_valid_json(self):
        problems = []

        def one(k):
            doc = DOC if k % 2 else "design/design.md"
            try:
                notes.save(self.ws, 2, doc, {"notes": [text_note(k)]})
            except Exception as e:  # noqa: BLE001
                problems.append(e)

        threads = [threading.Thread(target=one, args=(k,)) for k in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(problems, [])
        docs = self.stored()["docs"]
        self.assertEqual(sorted(docs), ["design/design.md", DOC])

    def test_block_text(self):
        feature = data.find_feature(self.ws, 2)
        want = ("Notes on _chopchop/002-IDEA-2-dashboard-comments/design/design.md\n"
                "Each note says where it is, the text I picked, and my note.\n"
                "\n"
                "1. At: 4. Scope > In scope\n"
                "   Text: \"one list per document\"\n"
                "   Note: Should this be per feature?\n"
                "\n"
                "2. At: diagram \"High-level design\", box \"Notes route\" (notesroute)\n"
                "   Note: Split this box in two?")
        listed = [text_note(), box_note()]
        self.assertEqual(notes.block(feature, "design/design.md", listed), want)
        self.assertEqual(notes.block(feature, "design/design.md", listed), want)
        self.assertEqual(notes.block(feature, "design/design.md", []), "")

    def test_get_on_a_broken_file_writes_nothing(self):
        self.file.parent.mkdir(parents=True)
        self.file.write_text("{not json", encoding="utf-8")
        out = notes.get(self.ws, 2, DOC)
        self.assertEqual(out["notes"], [])
        self.assertIn("broken", out["warning"])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "{not json")
        self.assertFalse(self.file.with_name(".dashboard-notes.json.bad").exists())

    def test_block_with_awkward_text(self):
        listed = [
            text_note(1, heading="", text="First line\nsecond line"),
            text_note(2, text="2. starts like a list item", quote='say "hi" \U0001F600\nagain', match=3),
        ]
        out = notes.save(self.ws, 2, DOC, {"notes": listed})
        want = ("Notes on _chopchop/002-IDEA-2-dashboard-comments/requirements/requirement.md\n"
                "Each note says where it is, the text I picked, and my note.\n"
                "\n"
                "1. At: the top of the document\n"
                "   Text: \"one list per document\"\n"
                "   Note: First line\n"
                "   second line\n"
                "\n"
                "2. At: 4. Scope > In scope\n"
                "   Text: \"say \"hi\" \U0001F600 again\"\n"
                "   Note: 2. starts like a list item")
        self.assertEqual(out["block"], want)
        self.assertEqual(self.stored()["docs"][DOC][1]["quote"], 'say "hi" \U0001F600\nagain')
        self.assertEqual(notes.get(self.ws, 2, DOC)["block"], want)


class Route(unittest.TestCase):
    """One real server on a free port, for GET and POST /api/notes."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ws = sample(cls.tmp.name)
        cls.feature = sorted(p for p in cls.ws.iterdir() if p.is_dir() and p.name[:3].isdigit())[0]
        (cls.feature / "design").mkdir(exist_ok=True)
        (cls.feature / "design" / "design.md").write_text("# Design\n", encoding="utf-8")
        (cls.feature / "design" / "architecture.json").write_text("{}\n", encoding="utf-8")
        cls.file = cls.feature / "work" / ".dashboard-notes.json"
        cls.server = chopchop_dashboard.open_server(cls.ws, free_port())
        cls.server.heartbeat = 1.0
        cls.server.watcher.interval = 0.3
        cls.server.watcher.start()
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()
        cls.url = cls.server.url
        cls.port = cls.server.server_port
        cls.number = int(cls.feature.name[:3])
        cls.route = "/api/notes/%d?path=" % cls.number

    @classmethod
    def tearDownClass(cls):
        cls.server.stopping.set()
        cls.server.shutdown()
        cls.server.close()
        cls.tmp.cleanup()

    def send(self, method, path, body=b"", headers=None, length=True):
        """(status, JSON answer). Headers go out exactly as given; Content-Length is added unless length is False."""
        headers = dict(headers or {})
        if length and not any(k.lower() == "content-length" for k in headers):
            headers["Content-Length"] = str(len(body))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host="Host" in headers, skip_accept_encoding=True)
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.endheaders(body or None)
            answer = conn.getresponse()
            return answer.status, json.loads(answer.read().decode("utf-8") or "{}")
        finally:
            conn.close()

    def get(self, path, headers=None):
        return self.send("GET", path, headers=headers, length=False)

    def post(self, path, body, headers=None):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        headers = dict({"Content-Type": "application/json", "Origin": self.url}, **(headers or {}))
        return self.send("POST", path, body, headers)

    def snapshot(self):
        return self.file.read_bytes() if self.file.exists() else None

    def test_save_and_load_one_list_per_document(self):
        listed = [text_note(1), text_note(2, match=1)]
        status, body = self.post(self.route + DOC, {"notes": listed})
        self.assertEqual(status, 200, body)
        status, body = self.get(self.route + DOC)
        self.assertEqual(status, 200, body)
        self.assertEqual((body["path"], body["notes"]), (DOC, listed))
        self.assertTrue(body["block"].startswith("Notes on _chopchop/%s/%s\n" % (self.feature.name, DOC)))
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8"))["docs"][DOC], listed)

    def test_same_list_twice_writes_the_same_file(self):
        listed = {"notes": [box_note(5)]}
        first = self.post(self.route + "design/design.md", listed)
        before = self.file.read_bytes()
        second = self.post(self.route + "design/design.md", listed)
        self.assertEqual((first[0], second[0]), (200, 200))
        self.assertEqual(first, second)
        self.assertEqual(self.file.read_bytes(), before)

    def test_get_twice_is_the_same(self):
        before = self.snapshot()
        one = self.get(self.route + DOC)
        two = self.get(self.route + DOC)
        self.assertEqual(one[0], 200)
        self.assertEqual(one, two)
        self.assertEqual(self.snapshot(), before)

    def test_refusals_write_nothing(self):
        before = self.snapshot()
        good = json.dumps({"notes": [text_note()]}).encode("utf-8")
        cases = [
            (415, DOC, good, {"Content-Type": "text/plain"}),
            (403, DOC, good, {"Origin": "https://evil.test"}),
            (403, DOC, good, {"Origin": "http://127.0.0.1:%d" % (self.port + 1)}),
            (413, DOC, b"{}", {"Content-Length": "300000"}),
            (404, "design/nope.md", good, {}),
            (403, "../chopchop.yaml", good, {}),
        ]
        for want, doc, body, headers in cases:
            status, answer = self.post(self.route + doc, body, headers)
            self.assertEqual(status, want, (doc, headers, answer))
            self.assertTrue(answer.get("error"))
            self.assertEqual(self.snapshot(), before, (doc, headers))
        self.assertEqual(self.post(self.route + DOC, good, {"Content-Type": "text/plain"})[1],
                         {"error": "Send the notes as application/json."})
        self.assertEqual(self.post(self.route + DOC, good, {"Origin": "https://evil.test"})[1],
                         {"error": "Only the dashboard page can save notes."})

    def test_bad_host_is_refused(self):
        before = self.snapshot()
        self.assertEqual(self.post(self.route + DOC, {"notes": [text_note()]}, {"Host": "evil.test"})[0], 403)
        self.assertEqual(self.get(self.route + DOC, {"Host": "evil.test"})[0], 403)
        self.assertEqual(self.snapshot(), before)

    def test_other_posts_still_405(self):
        self.assertEqual(self.post("/api/features", {"notes": []})[0], 405)
        self.assertEqual(self.post("/api/doc/%d?path=%s" % (self.number, DOC), {"notes": []})[0], 405)

    def test_save_sends_no_live_update(self):
        got, lines = [], []
        done = threading.Event()

        def listen():
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.request("GET", "/api/stream")
                answer = conn.getresponse()
                while not done.is_set():
                    raw = answer.fp.readline()
                    if not raw:
                        return
                    line = raw.decode("utf-8").strip()
                    lines.append(line)
                    if line == "event: changed":
                        got.append(line)
            except OSError:
                pass
            finally:
                conn.close()

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        time.sleep(0.8)
        self.assertEqual(self.post(self.route + DOC, {"notes": [text_note(9, text="live? %s" % time.time())]})[0], 200)
        time.sleep(2.0)
        done.set()
        self.assertIn("event: hello", lines)
        self.assertEqual(got, [])

    def test_one_list_for_one_document_whatever_the_path(self):
        listed = [text_note(7, text="same list")]
        self.assertEqual(self.post(self.route + "requirements//requirement.md", {"notes": listed})[0], 200)
        status, body = self.get(self.route + DOC)
        self.assertEqual((status, body["path"], body["notes"]), (200, DOC, listed))

    def test_bad_content_length_is_400(self):
        before = self.snapshot()
        good = json.dumps({"notes": [text_note()]}).encode("utf-8")
        for size in ("abc", "-1"):
            status, answer = self.post(self.route + DOC, good, {"Content-Length": size})
            self.assertEqual(status, 400, (size, answer))
        status, answer = self.send("POST", self.route + DOC, good,
                                   {"Content-Type": "application/json", "Origin": self.url}, length=False)
        self.assertEqual(status, 400, answer)
        self.assertEqual(answer, {"error": "Say the body size in Content-Length."})
        self.assertEqual(self.snapshot(), before)

    def test_json_documents_take_no_notes(self):
        before = self.snapshot()
        status, answer = self.post(self.route + "design/architecture.json", {"notes": [text_note()]})
        self.assertEqual(status, 403, answer)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
