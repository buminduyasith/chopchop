"""Watch the workspace for changed files, and tell every open page.

The watcher looks at file times and sizes about once a second. It never reads a file. When
something under a feature changes, it publishes one "changed" message with the feature numbers.
The hub hands each message to every open page (one queue per page).
"""

import hashlib
import os
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path

FOLDER_RE = re.compile(r"^(\d{3,})-(.+)$")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".idea", ".vscode"}
OWN_PREFIX = ".dashboard"   # the dashboard's own files: .dashboard.json, .dashboard.log
MAX_FILES = 50000           # stop counting after this many files in one folder tree


def stamp(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts).strftime("%Y-%m-%dT%H:%M:%S")


def scan(folder, limit=MAX_FILES):
    """(signature, newest change time) of every file under a folder. Symlinked folders are not followed."""
    digest = hashlib.blake2b(digest_size=12)
    newest, seen = 0.0, 0
    stack = [str(folder)]
    while stack:
        here = stack.pop()
        try:
            with os.scandir(here) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if e.name.startswith(OWN_PREFIX):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name not in SKIP_DIRS:
                        stack.append(e.path)
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            seen += 1
            if seen > limit:
                break
            digest.update(("%s|%d|%d\n" % (e.path, st.st_mtime_ns, st.st_size)).encode("utf-8", "replace"))
            if st.st_mtime > newest:
                newest = st.st_mtime
    return digest.hexdigest(), newest


def updated(folder):
    """When a folder last changed, as text, or None for an empty folder."""
    newest = scan(folder)[1]
    return stamp(newest) if newest else None


def scopes(workspace):
    """What the page can ask for, and the folders behind each: features, loose PR stores, the system map."""
    ws = Path(workspace)
    out = {}
    names = []
    try:
        with os.scandir(str(ws)) as it:
            top = sorted(it, key=lambda e: e.name)
    except OSError:
        return out, ""
    for e in top:
        if e.name.startswith(OWN_PREFIX) or e.name in SKIP_DIRS:
            continue
        try:
            is_dir = e.is_dir(follow_symlinks=False)
        except OSError:
            continue
        m = FOLDER_RE.match(e.name)
        if is_dir and m:
            out.setdefault(("f", int(m.group(1))), []).append(e.path)
            names.append(e.name)
        elif is_dir and e.name == "prs":
            try:
                with os.scandir(e.path) as inner:
                    for p in sorted(inner, key=lambda x: x.name):
                        if p.is_dir(follow_symlinks=False):
                            out.setdefault(("pr", p.name), []).append(p.path)
                            names.append("prs/" + p.name)
            except OSError:
                pass
        elif is_dir and e.name == "system":
            out[("system", "")] = [e.path]
            names.append(e.name)
        elif not is_dir:
            try:
                st = e.stat(follow_symlinks=False)
                names.append("%s|%d|%d" % (e.name, st.st_mtime_ns, st.st_size))
            except OSError:
                pass
    return out, "\n".join(names)


class Hub:
    """Every open page has a queue here. publish() puts a message on each."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients = set()

    def join(self):
        q = queue.Queue(maxsize=256)
        with self.lock:
            self.clients.add(q)
        return q

    def leave(self, q):
        with self.lock:
            self.clients.discard(q)

    def count(self):
        with self.lock:
            return len(self.clients)

    def publish(self, message):
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(message)
            except queue.Full:  # a page that stopped reading: it reloads everything when it is back
                pass


class Watcher(threading.Thread):
    def __init__(self, workspace, hub, interval=1.0):
        threading.Thread.__init__(self, name="chopchop-watch", daemon=True)
        self.workspace = Path(workspace)
        self.hub = hub
        self.interval = interval
        self.stop = threading.Event()
        self.seen = None
        self.home = None

    def look(self):
        found, home = scopes(self.workspace)
        return {key: tuple(scan(p)[0] for p in paths) for key, paths in found.items()}, home

    def changes(self):
        """What changed since the last look: a message for the pages, or None."""
        now, home = self.look()
        before, home_before = self.seen, self.home
        self.seen, self.home = now, home
        if before is None:
            return None
        keys = [k for k in set(now) | set(before) if now.get(k) != before.get(k)]
        if not keys and home == home_before:
            return None
        return {
            "features": sorted(k[1] for k in keys if k[0] == "f"),
            "prs": sorted(k[1] for k in keys if k[0] == "pr"),
            "system": any(k[0] == "system" for k in keys),
            "home": home != home_before or any(set(now) ^ set(before)),
            "ts": stamp(),
        }

    def run(self):
        while not self.stop.is_set():
            began = time.time()
            try:
                message = self.changes()
                if message:
                    self.hub.publish(message)
            except Exception:  # noqa: BLE001  one bad look must not end the watching
                pass
            took = time.time() - began
            # A huge workspace takes longer to look at: wait longer, so the watcher stays cheap.
            self.stop.wait(max(self.interval, took * 10))
