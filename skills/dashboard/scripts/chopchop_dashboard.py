#!/usr/bin/env python3
"""Dashboard: one live page for every feature in the workspace. It only reads files, except the reviewer's notes.

Usage
  chopchop_dashboard.py --start [--port N] [--no-open] [--json]   start it in the background, print the link
  chopchop_dashboard.py --stop [--json]                           stop it
  chopchop_dashboard.py --status [--json]                         running or not, and the link
  chopchop_dashboard.py --serve [--port N]                        run it here in the foreground (--start runs this)

--start is safe to run again: when the dashboard of this workspace already runs, it prints the
same link. It opens the browser unless a page is already open, or --no-open is given. When the
port is taken, it uses the next free one.

Files, in _chopchop/:
  .dashboard.json   pid, port, url, started, token, workspace, log (gone when it stops)
  .dashboard.log    what the server printed

In each feature folder:
  work/.dashboard-notes.json   the reviewer's notes, one list per document (written only by POST /api/notes)

HTTP, on 127.0.0.1 only, GET only, except POST /api/notes:
  /                          the page
  /api/features              every feature as stage.read() gives it, plus key and updated
  /api/feature/<n>           that, plus docs, tasks, events, comments, gates, links, run
  /api/doc/<n>?path=...      one .md or .json file inside the feature folder: {title, html, summary, updated, raw}
  /api/prs  /api/pr/<slug>   review stores of PRs that have no feature (_chopchop/prs/<slug>/)
  /api/system                the system map, when there is one
  /api/notes/<n>?path=...    GET or POST the notes of one .md document: {path, notes, block}
                             A POST needs Content-Type application/json, a body of 256 KB at most,
                             and no Origin or this dashboard's own
  /api/stream                server-sent events: "changed" with the feature numbers, when a file changes
  /api/ping                  who is this (used by --start, --stop and --status)

Needs the tasks skill next to it. Standard library only. Python 3.8+.
"""

import argparse
import http.client
import json
import os
import queue
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

HERE = Path(__file__).resolve().parent
TASKS = HERE.parents[1] / "tasks"
if not (TASKS / "scripts" / "chopchoplib" / "stage.py").is_file():
    sys.exit("Error: dashboard needs the tasks skill next to it (%s not found)." % TASKS)
sys.path.insert(0, str(TASKS / "scripts"))
sys.path.insert(0, str(HERE))

from chopchoplib.config import ConfigError, find_workspace, load_config  # noqa: E402
from dashlib import data, notes  # noqa: E402
from dashlib.watch import Hub, Watcher, stamp  # noqa: E402

APP = "chopchop-dashboard"
HOST = "127.0.0.1"
DEFAULT_PORT = 4747
PORT_TRIES = 20          # ports tried after the wanted one, before taking any free port
START_WAIT = 12.0        # seconds --start waits for the server to answer
STOP_WAIT = 5.0
HEARTBEAT = 15.0         # seconds between keep-alive lines on the stream
STATE_FILE = ".dashboard.json"
LOG_FILE = ".dashboard.log"
LOG_KEEP = 512 * 1024
PAGE = HERE.parent / "assets" / "dashboard.html"
NONCE_MARK = "__CSP_NONCE__"
MAX_BODY = 256 * 1024   # bytes: a bigger notes POST is refused before it is read


class UsageError(Exception):
    pass


def emit(args, payload, lines):
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n".join(lines))


# --------------------------------------------------------------------------- the server


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"
    request_queue_size = 64

    def __init__(self, port, workspace, heartbeat=HEARTBEAT, interval=1.0):
        ThreadingHTTPServer.__init__(self, (HOST, port), Handler)
        self.workspace = Path(workspace)
        self.token = secrets.token_hex(16)
        self.started = stamp()
        self.heartbeat = heartbeat
        self.hub = Hub()
        self.watcher = Watcher(self.workspace, self.hub, interval)
        self.stopping = threading.Event()

    @property
    def url(self):
        return "http://%s:%d" % (HOST, self.server_port)

    def handle_error(self, request, client_address):
        err = sys.exc_info()[1]
        if isinstance(err, (BrokenPipeError, ConnectionResetError, socket.timeout)):
            return  # the browser went away: nothing to report
        sys.stderr.write("%s error while answering %s\n%s\n" % (stamp(), client_address, traceback.format_exc()))

    def close(self):
        self.stopping.set()
        self.watcher.stop.set()
        self.hub.publish(None)
        self.server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "chopchop-dashboard"
    sys_version = ""
    timeout = 30

    def log_message(self, fmt, *args):  # only problems go to the log
        pass

    def log_error(self, fmt, *args):
        text = fmt % args
        if text.startswith("Request timed out"):
            return  # a browser opened a spare connection and never used it
        sys.stderr.write("%s %s\n" % (stamp(), text))

    def do_GET(self):
        self.route(True)

    def do_HEAD(self):
        self.route(False)

    def read_only(self):
        self.send_json(405, {"error": "The dashboard only reads, except notes at /api/notes."}, {"Allow": "GET, HEAD"})

    def do_POST(self):
        self.route(True, post=True)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = read_only

    # ------------------------------------------------------------------ answers

    def common_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")

    def send_bytes(self, status, body, content_type, extra=None, with_body=True):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.common_headers()
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if with_body and self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status, payload, extra=None):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8", extra)

    def send_page(self):
        try:
            page = PAGE.read_text(encoding="utf-8")
        except OSError:
            return self.send_bytes(500, b"The dashboard page is missing: assets/dashboard.html", "text/plain; charset=utf-8")
        nonce = secrets.token_urlsafe(16)
        cdn = [m.group(1) for m in re.finditer(
            r'(?:MERMAID|HLJS)_URL\s*=\s*"(https://(?:cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com)/[^"\s;,]+)"', page)]
        policy = ("default-src 'none'; script-src 'nonce-%s'%s; style-src 'unsafe-inline' https://fonts.googleapis.com; "
                  "img-src 'self' data:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
                  % (nonce, "".join(" " + u for u in cdn)))
        self.send_bytes(200, page.replace(NONCE_MARK, nonce).encode("utf-8"), "text/html; charset=utf-8",
                        {"Content-Security-Policy": policy, "X-Frame-Options": "DENY"})

    # ------------------------------------------------------------------ routes

    def host_ok(self):
        """Refuse a request that reached us under another name (a web page that points its own name at 127.0.0.1)."""
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return True
        name = host[:host.find("]") + 1] if host.startswith("[") else host.rsplit(":", 1)[0]
        return name in ("127.0.0.1", "localhost", "[::1]")

    def origin_ok(self):
        """A browser always sends Origin on a POST. Allow none (a local script), or this dashboard only."""
        origin = (self.headers.get("Origin") or "").strip().lower()
        if not origin:
            return True
        try:
            url = urlsplit(origin)
            port = url.port
        except ValueError:
            return False
        return (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost") and url.path in ("", "/")
                and port == self.server.server_port)

    def read_body(self):
        """The JSON body of a notes POST. The type and size are checked before anything is read."""
        if not (self.headers.get("Content-Type") or "").strip().lower().startswith("application/json"):
            raise notes.BadType("Send the notes as application/json.")
        try:
            size = int(self.headers.get("Content-Length") or "")
        except ValueError:
            raise data.ApiError("Say the body size in Content-Length.")
        if size < 0:
            raise data.ApiError("Say the body size in Content-Length.")
        if size > MAX_BODY:
            raise data.TooBig("The notes are too big: 256 KB at most.")
        try:
            return json.loads(self.rfile.read(size).decode("utf-8") or "{}")
        except ValueError:
            raise data.ApiError("The notes are not JSON.")

    def route(self, with_body, post=False):
        srv = self.server
        try:
            if not self.host_ok():
                return self.send_json(403, {"error": "Open the dashboard at %s." % srv.url})
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = parse_qs(url.query)
            ws = srv.workspace
            m = re.match(r"^/api/notes/(\d{1,9})$", path)
            if post and not m:
                return self.read_only()
            if m:
                doc = (query.get("path") or [""])[0]
                if not post:
                    return self.send_json(200, notes.get(ws, m.group(1), doc))
                if not self.origin_ok():
                    return self.send_json(403, {"error": "Only the dashboard page can save notes."})
                return self.send_json(200, notes.save(ws, m.group(1), doc, self.read_body()))
            if path in ("/", "/index.html"):
                return self.send_page()
            if path == "/favicon.ico":
                return self.send_bytes(204, b"", "image/x-icon")
            if path == "/api/ping":
                return self.send_json(200, {"ok": True, "app": APP, "token": srv.token, "pid": os.getpid(),
                                            "workspace": str(ws), "started": srv.started, "url": srv.url,
                                            "clients": srv.hub.count()})
            if path == "/api/stream":
                return self.stream(with_body)
            if path == "/api/features":
                return self.send_json(200, data.home(ws))
            m = re.match(r"^/api/feature/(\d{1,9})$", path)
            if m:
                return self.send_json(200, data.feature(ws, m.group(1)))
            m = re.match(r"^/api/doc/(\d{1,9})$", path)
            if m:
                return self.send_json(200, data.doc(ws, m.group(1), (query.get("path") or [""])[0]))
            if path == "/api/prs":
                return self.send_json(200, data.pr_list(ws))
            m = re.match(r"^/api/pr/([^/]+)$", path)
            if m:
                return self.send_json(200, data.pr(ws, m.group(1)))
            if path == "/api/system":
                return self.send_json(200, data.system(ws))
            return self.send_json(404, {"error": "Nothing here: %s" % path})
        except data.ApiError as e:
            return self.send_json(e.status, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            return None
        except Exception as e:  # noqa: BLE001  a bug must not take the page down: say it and carry on
            sys.stderr.write("%s error on %s\n%s\n" % (stamp(), self.path, traceback.format_exc()))
            try:
                return self.send_json(500, {"error": "The dashboard could not read the files: %s: %s"
                                                     % (type(e).__name__, e)})
            except OSError:
                return None

    def stream(self, with_body):
        """Server-sent events: one "changed" message per change, and a keep-alive line now and then."""
        srv = self.server
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.common_headers()
        self.end_headers()
        if not with_body:
            return
        box = srv.hub.join()
        try:
            self.wfile.write(b"retry: 2000\n\nevent: hello\ndata: %s\n\n"
                             % json.dumps({"ts": stamp(), "started": srv.started}).encode("utf-8"))
            self.wfile.flush()
            while not srv.stopping.is_set():
                try:
                    message = box.get(timeout=srv.heartbeat)
                except queue.Empty:
                    self.wfile.write(b": still here\n\n")
                    self.wfile.flush()
                    continue
                if message is None:
                    break
                self.wfile.write(b"event: changed\ndata: %s\n\n" % json.dumps(message).encode("utf-8"))
                self.wfile.flush()
        except (OSError, ValueError):
            pass  # the page was closed
        finally:
            srv.hub.leave(box)


def in_use(port):
    """True when something already answers on this port."""
    try:
        with socket.create_connection((HOST, port), timeout=0.3):
            return True
    except OSError:
        return False


def open_server(workspace, port, **options):
    """A server on the wanted port, or on the next free one. Port 0 means any free port."""
    wanted = [port] + [port + k for k in range(1, PORT_TRIES + 1)] if port else []
    for candidate in wanted + [0]:
        if candidate > 65535 or (candidate and in_use(candidate)):
            continue
        try:
            return Server(candidate, workspace, **options)
        except OSError:
            continue
    raise UsageError("No free port found from %d on. Give one with --port." % port)


# --------------------------------------------------------------------------- the state file


def read_state(ws):
    try:
        info = json.loads((Path(ws) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("pid"), int) or not isinstance(info.get("port"), int):
        return None
    return info


def write_state(ws, info):
    path = Path(ws) / STATE_FILE
    tmp = path.with_name(STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def drop_state(ws, token=None):
    """Remove the state file. With a token, only when the file is still ours."""
    path = Path(ws) / STATE_FILE
    if token is not None:
        info = read_state(ws)
        if info and info.get("token") != token:
            return
    try:
        path.unlink()
    except OSError:
        pass


def ping(port, timeout=1.5):
    """What the server on this port says about itself, or None. It never goes through a proxy."""
    conn = http.client.HTTPConnection(HOST, port, timeout=timeout)
    try:
        conn.request("GET", "/api/ping")
        answer = conn.getresponse()
        if answer.status != 200:
            return None
        info = json.loads(answer.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()
    return info if isinstance(info, dict) and info.get("app") == APP else None


def live(ws):
    """The state of this workspace's running dashboard, checked with the server itself. None when it does not run."""
    info = read_state(ws)
    if not info:
        return None
    answer = ping(info["port"])
    if not answer or not info.get("token") or answer.get("token") != info["token"] or answer.get("pid") != info["pid"]:
        return None
    return dict(info, clients=int(answer.get("clients") or 0))


def need_folder(ws):
    if not Path(ws).is_dir():
        raise UsageError("No _chopchop folder at %s. Next: set the project up with /chopchop:init." % ws)


def wanted_port(args, ws):
    if args.port is not None:
        if not 0 <= args.port <= 65535:
            raise UsageError("--port must be between 0 and 65535.")
        return args.port
    try:
        section = load_config(ws).get("dashboard")
        port = int(section.get("port")) if isinstance(section, dict) and section.get("port") else DEFAULT_PORT
    except (ConfigError, TypeError, ValueError):
        port = DEFAULT_PORT
    except Exception:  # noqa: BLE001  a broken chopchop.yaml: the dashboard still starts
        port = DEFAULT_PORT
    return port if 0 < port <= 65535 else DEFAULT_PORT


def gone(pid):
    """True when no process has this pid any more."""
    if os.name == "nt":
        return True  # there, os.kill ends a process at once, and signal 0 is not a harmless question
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)   # only works for our own child: it also clears it away
        if done == pid:
            return True
    except (ChildProcessError, OSError, AttributeError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return False


# --------------------------------------------------------------------------- commands


def cmd_serve(args, ws):
    need_folder(ws)
    running = live(ws)
    if running:
        raise UsageError("The dashboard already runs at %s. Next: --stop, then start it again." % running["url"])
    wanted = wanted_port(args, ws)
    server = open_server(ws, wanted)
    info = {"pid": os.getpid(), "port": server.server_port, "url": server.url, "started": server.started,
            "token": server.token, "workspace": str(ws), "log": str(Path(ws) / LOG_FILE), "wanted_port": wanted}
    write_state(ws, info)

    def stop(*_):
        server.stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, stop)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, stop)
    server.watcher.start()
    print("Dashboard: %s" % server.url)
    print("Serving:   %s (pid %d). Ctrl+C stops it." % (ws, os.getpid()))
    sys.stdout.flush()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        drop_state(ws, server.token)
    return 0


def log_tail(path, lines=3):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return ""
    return " ".join(l.strip() for l in text[-lines:] if l.strip())


def launch(ws, port):
    """Start --serve as its own process, cut loose from this one. Returns the Popen."""
    log = Path(ws) / LOG_FILE
    try:
        mode = "wb" if log.stat().st_size > LOG_KEEP else "ab"
    except OSError:
        mode = "ab"
    cmd = [sys.executable, str(Path(__file__).resolve()), "--serve", "--workspace", str(ws), "--port", str(port)]
    options = {}
    if os.name == "nt":
        options["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0)
                                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        options["start_new_session"] = True
    with open(str(log), mode) as fh:
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh, stderr=fh, close_fds=True,
                                cwd=str(ws), **options)


def cmd_start(args, ws):
    need_folder(ws)
    info = live(ws)
    already = bool(info)
    wanted = wanted_port(args, ws)
    if not info:
        drop_state(ws)  # an old file from a server that is gone
        proc = launch(ws, wanted)
        deadline = time.time() + START_WAIT
        while time.time() < deadline and proc.poll() is None:
            info = live(ws)
            if info and info["pid"] == proc.pid:
                break
            info = None
            time.sleep(0.1)
        if not info:
            log = Path(ws) / LOG_FILE
            why = log_tail(log) or "It gave no reason."
            if proc.poll() is None:
                proc.terminate()
            raise UsageError("The dashboard did not start. %s Log: %s" % (why, log))
    opened = False
    if not args.no_open and not info.get("clients"):
        try:
            opened = bool(webbrowser.open(info["url"]))
        except Exception:  # noqa: BLE001  no browser on this machine: the link is still printed
            opened = False
    moved = not already and wanted and info["port"] != wanted
    payload = {"running": True, "already": already, "url": info["url"], "port": info["port"], "pid": info["pid"],
               "started": info.get("started"), "workspace": str(ws), "opened": opened, "pages_open": info.get("clients", 0),
               "log": str(Path(ws) / LOG_FILE)}
    lines = ["Dashboard: %s" % info["url"],
             "Status:    %s (pid %d)" % ("already running" if already else "started", info["pid"])]
    if moved:
        lines.append("Note:      port %d is taken, so it uses %d." % (wanted, info["port"]))
    if opened:
        lines.append("Browser:   opened")
    elif info.get("clients"):
        lines.append("Browser:   already open in %d tab(s)" % info["clients"])
    else:
        lines.append("Browser:   not opened. Open the link yourself.")
    lines.append("Next:      read it in the browser. It updates by itself. --stop stops it.")
    emit(args, payload, lines)
    return 0


def cmd_status(args, ws):
    info = live(ws) if Path(ws).is_dir() else None
    if not info:
        emit(args, {"running": False, "workspace": str(ws)},
             ["Dashboard: not running", "Next:      --start starts it."])
        return 0
    payload = {"running": True, "url": info["url"], "port": info["port"], "pid": info["pid"],
               "started": info.get("started"), "workspace": str(ws), "pages_open": info["clients"]}
    emit(args, payload, ["Dashboard: %s" % info["url"],
                         "Status:    running since %s (pid %d), %d page(s) open"
                         % (info.get("started"), info["pid"], info["clients"]),
                         "Next:      --stop stops it."])
    return 0


def cmd_stop(args, ws):
    state = read_state(ws) if Path(ws).is_dir() else None
    info = live(ws) if state else None
    if not info:
        if state:
            drop_state(ws)
        emit(args, {"running": False, "stopped": False, "workspace": str(ws)},
             ["Dashboard: not running" + (" (removed an old state file)" if state else ""),
              "Next:      --start starts it."])
        return 0
    pid = info["pid"]
    # live() just asked the server on that port for its token and pid: this pid really is our dashboard.
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as e:
        raise UsageError("Could not stop the dashboard (pid %d): %s" % (pid, e))
    deadline = time.time() + STOP_WAIT
    while time.time() < deadline and not gone(pid):
        time.sleep(0.1)
    if not gone(pid) and live(ws):   # still answers with our token after the wait: end it the hard way
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass
        time.sleep(0.3)
    drop_state(ws, info.get("token"))
    emit(args, {"running": False, "stopped": True, "pid": pid, "url": info["url"], "workspace": str(ws)},
         ["Dashboard: stopped (pid %d)" % pid, "Next:      --start starts it again."])
    return 0


# --------------------------------------------------------------------------- main


ACTIONS = ["start", "stop", "status", "serve"]


def build_parser():
    p = argparse.ArgumentParser(prog="chopchop_dashboard.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", action="store_true", help="start it in the background and print the link")
    p.add_argument("--stop", action="store_true", help="stop it")
    p.add_argument("--status", action="store_true", help="running or not, and the link")
    p.add_argument("--serve", action="store_true", help="run it here, in the foreground")
    p.add_argument("--port", type=int, metavar="N", help="with --start or --serve: the port to try first (default %d)" % DEFAULT_PORT)
    p.add_argument("--no-open", action="store_true", help="with --start: do not open the browser")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--workspace", help="path to the _chopchop folder")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    chosen = [a for a in ACTIONS if getattr(args, a)]
    try:
        if len(chosen) != 1:
            raise UsageError("Use one of --%s." % ", --".join(ACTIONS))
        ws = find_workspace(args.workspace)
        return globals()["cmd_" + chosen[0]](args, ws)
    except (UsageError, ConfigError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
