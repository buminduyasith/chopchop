"""Log a change found while building a task, and pass it on to the tasks it affects.

  todo         the task file gets a line under '## Heads-up', so whoever starts it sees it
  in-progress  not touched; the owner is named in the report so someone tells them
  in-review    same as in-progress
  done         not touched; the report suggests a follow-up task
"""

import re
from datetime import date
from pathlib import Path

from relaylib import tasks as tasklib  # tasks' copy

HEADS_UP = "Heads-up"


def next_change_id(entries):
    numbers = [int(e["id"].split("-")[1]) for e in entries if re.match(r"^C-\d+$", e["id"])]
    return "C-%03d" % (max(numbers or [0]) + 1)


def affected(task, all_tasks):
    """Tasks that build on this one, or share files with it in the same repo."""
    out = []
    mine = tasklib.as_list(task.get("touches"))
    for t in all_tasks:
        if t.id == task.id:
            continue
        if task.id in tasklib.as_list(t.get("depends_on")):
            out.append(t)
        elif t.get("repo") == task.get("repo") and any(
                tasklib.paths_overlap(a, b) for a in mine for b in tasklib.as_list(t.get("touches"))):
            out.append(t)
    return out


def render_entry(change_id, task_id, change, why, affects, day=None):
    lines = ["## %s · %s · %s" % (change_id, task_id, day or date.today().isoformat()),
             "Change: %s" % one_line(change)]
    if why:
        lines.append("Why: %s" % one_line(why))
    lines.append("Affects: %s" % (", ".join(affects) if affects else "none"))
    return "\n".join(lines) + "\n"


def one_line(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def add_entry(changelog_path, entry):
    """Newest first: after the header and its format comment, before older entries."""
    path = Path(changelog_path)
    text = path.read_text(encoding="utf-8") if path.exists() else "# Changelog\n"
    end = text.find("-->")
    if end >= 0:
        pos = end + 3
    else:
        first = re.search(r"(?m)^## C-\d+", text)
        pos = first.start() if first else len(text)
    head, tail = text[:pos].rstrip("\n"), text[pos:].lstrip("\n")
    path.write_text(head + "\n\n" + entry + ("\n" + tail if tail.strip() else ""), encoding="utf-8")


def add_heads_up(task, line):
    """Add one line under '## Heads-up', just before '## Branch'."""
    found = tasklib.find_section(task.body, HEADS_UP)
    if found:
        start, text, end = found
        if line in text:
            return False
        items = text.strip()
        content = (items + "\n" if items else "") + line
        task.body = tasklib.replace_section(task.body, HEADS_UP, content)
    else:
        block = "## %s\n\n%s\n\n" % (HEADS_UP, line)
        branch = tasklib.find_section(task.body, "Branch")
        if branch:
            task.body = task.body[:branch[0]] + block + task.body[branch[0]:]
        else:
            task.body = task.body.rstrip() + "\n\n" + block.rstrip() + "\n"
    return task.save()


def log_change(tasks_dir, task, all_tasks, change, why=None, affects=None, day=None):
    """Write the entry and pass it on. Returns a report dict."""
    if not (change or "").strip():
        raise ValueError("Say what changed with --change.")
    by_id = {t.id: t for t in all_tasks}
    if affects is None:
        hit = affected(task, all_tasks)
    else:
        unknown = [a for a in affects if a not in by_id]
        if unknown:
            raise ValueError("Unknown task(s) in --affects: %s" % ", ".join(unknown))
        hit = [by_id[a] for a in affects if a != task.id]
    log = Path(tasks_dir) / tasklib.CHANGELOG_FILE
    change_id = next_change_id(tasklib.read_changelog(log))
    day = day or date.today().isoformat()
    add_entry(log, render_entry(change_id, task.id, change, why, [t.id for t in hit], day))

    report = {"id": change_id, "task": task.id, "updated": [], "tell": [], "follow_up": []}
    note = "- %s from %s (%s): %s See changelog.md." % (change_id, task.id, day, one_line(change).rstrip(".") + ".")
    for t in hit:
        status = t.get("status")
        if status == "todo":
            add_heads_up(t, note)
            report["updated"].append(t.id)
        elif status == "done":
            report["follow_up"].append(t.id)
        else:
            report["tell"].append({"task": t.id, "status": status, "owner": t.get("owner")})
    return report
