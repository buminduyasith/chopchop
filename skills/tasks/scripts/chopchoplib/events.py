"""The activity log of a feature: one line per thing that happened.

  <feature>/work/events.jsonl      {"ts": "2026-11-14T10:22:05", "kind": "commit", "text": "T03 committed", ...}

Every script adds a line when it does something a person would want to see. The dashboard
shows the newest lines live. Logging never fails a command: a broken log is ignored.
"""

import json
from datetime import datetime
from pathlib import Path

FILE = "events.jsonl"
KEEP = 2000  # lines kept when the file is trimmed

KINDS = ["groom", "question", "answer", "brief", "design", "spec", "tasks", "approve", "run", "build",
         "review", "fix", "commit", "stop", "push", "pr", "comment", "triage", "reply", "merge", "done", "note"]


def _folder(feature):
    return Path(getattr(feature, "path", feature))


def log(feature, kind, text, **extra):
    """Add one line. feature is a Feature or the feature folder. Returns the entry, or None."""
    try:
        entry = {"ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "kind": str(kind), "text": str(text)}
        for key, value in extra.items():
            if value is not None:
                entry[key] = value
        work = _folder(feature) / "work"
        work.mkdir(parents=True, exist_ok=True)
        path = work / FILE
        with open(str(path), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if path.stat().st_size > 2 * 1024 * 1024:
            lines = path.read_text(encoding="utf-8").splitlines()[-KEEP:]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return entry
    except Exception:  # noqa: BLE001  the log must never break a command
        return None


def read(feature, limit=200):
    """The newest entries, oldest first."""
    path = _folder(feature) / "work" / FILE
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("text"):
            out.append(item)
    return out
