"""Write the generated task files: plan.md and status.md. Markdown only.

Both start with a Summary. The live dashboard (the dashboard skill) shows them as they are, and
open_dashboard() starts it for the --open option of design, spec, tasks and diagram.
"""

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import plain
from .features import render_front_matter
from .tasks import STATUS_TITLES, STATUSES, as_list, find_section, waiting_on

DASHBOARD = Path(__file__).resolve().parents[3] / "dashboard" / "scripts" / "chopchop_dashboard.py"
NOTES_HINT = "_Your notes. chopchop keeps this section as it is._"


def now():
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _cell(text):
    return str(text if text not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def _md_list(items):
    return ", ".join(items) if items else "-"


# --------------------------------------------------------------------------- plan.md


def render_plan(feature, tasks, plan_meta, sources, notes, base=None):
    """base: the base branch to show before the feature branch exists (from chopchop.yaml)."""
    base = plan_meta.get("base_branch") or base
    fbranch = plan_meta.get("feature_branch")
    repos = sorted({t.get("repo") for t in tasks if t.get("repo")})
    done = sum(1 for t in tasks if t.get("status") == "done")
    lines = [render_front_matter(plan_meta).rstrip(), "",
             "# Plan · %s" % feature.name, "",
             "_Written by chopchop from the task files. Only the Notes section is yours to edit._", "",
             plain.summary_block([
                 ("What", "the build plan, in the order the tasks can be built."),
                 ("Tasks", "%d in %d wave(s), %d done" % (len(tasks), len({t.get("wave") for t in tasks}), done)
                  if tasks else "none yet"),
                 ("Repos", _md_list(repos)),
                 ("Base branch", "`%s`" % base if base else "not set"),
                 ("Feature branch", "`%s`" % fbranch if fbranch else "not created yet")])]

    lines += ["## Waves", ""]
    if tasks:
        lines += ["| Wave | Task | Title | Repo | Size | Depends on | Status |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for t in sorted(tasks, key=lambda t: (t.get("wave", 9), t.id)):
            lines.append("| %s | [%s](%s) | %s | %s | %s | %s | %s |" % (
                _cell(t.get("wave")), t.id, t.path.name, _cell(t.get("title")), _cell(t.get("repo")),
                _cell(t.get("size")), _md_list(as_list(t.get("depends_on"))), _cell(t.get("status"))))
    else:
        lines.append("_No tasks yet._")
    lines.append("")

    if tasks:
        lines += ["## Graph", "", "```mermaid", "graph LR"]
        for t in tasks:
            lines.append('  %s["%s %s"]' % (t.id, t.id, str(t.get("title", "")).replace('"', "'")))
        for t in tasks:
            for dep in as_list(t.get("depends_on")):
                lines.append("  %s --> %s" % (dep, t.id))
        lines += ["```", ""]

    lines += ["## Design", ""]
    if sources:
        for s in sources:
            lines.append("- [%s](../design/%s), copied %s from `%s`" % (
                s["file"], s["file"], s["copied"][:10], s["from"]))
    else:
        lines.append("_No design files copied._")
    lines += ["", "## Notes", "", (notes or "").strip() or NOTES_HINT, ""]
    return "\n".join(lines)


def read_notes(plan_text):
    found = find_section(plan_text or "", "Notes")
    if not found:
        return ""
    text = found[1].strip()
    return "" if text == NOTES_HINT else text


# --------------------------------------------------------------------------- status.md


def auto_cell(a):
    """What /chopchop:auto did to one task, in a few words."""
    if not a:
        return "-"
    state = a.get("state") or "-"
    if state == "committed":
        return "committed `%s`" % a.get("commit") if a.get("commit") else "committed"
    if state in ("stopped", "skipped"):
        return "%s: %s" % (state, a["why"]) if a.get("why") else state
    return "%s, round %d" % (state, a["round"]) if a.get("round") else state


def status_points(tasks, counts, auto=None):
    by_id = {t.id: t for t in tasks}
    ready = [t.id for t in tasks if t.get("status") == "todo" and not waiting_on(t, by_id)]
    points = [("Done", "%d of %d tasks" % (counts["done"], len(tasks))),
              ("Counts", " · ".join("%s **%d**" % (STATUS_TITLES[s], counts[s]) for s in STATUSES)),
              ("Ready to start", _md_list(ready) if ready else "nothing")]
    if auto:
        states = {}
        for a in auto.values():
            states[a.get("state")] = states.get(a.get("state"), 0) + 1
        stopped = sorted(tid for tid, a in auto.items() if a.get("state") == "stopped")
        text = ", ".join("%d %s" % (n, s) for s, n in sorted(states.items(), key=lambda kv: str(kv[0])))
        points.append(("Build run", text + (". A person decides on %s" % ", ".join(stopped) if stopped else "")))
    return points


def render_status(feature, tasks, auto=None):
    """auto: {task id: {"state", "commit", "why", "round"}} from the auto run, when there is one."""
    by_id = {t.id: t for t in tasks}
    counts = {s: sum(1 for t in tasks if t.get("status") == s) for s in STATUSES}
    lines = ["# Status · %s" % feature.name, "",
             "_Written by chopchop from the task files. Do not edit. Change a status with "
             "`/chopchop:tasks --set <task> <status>`._", "",
             plain.summary_block(status_points(tasks, counts, auto))]
    for s in STATUSES:
        group = [t for t in tasks if t.get("status") == s]
        lines += ["## %s" % STATUS_TITLES[s], ""]
        if not group:
            lines += ["_None._", ""]
            continue
        lines += ["| Task | Title | Repo | Wave | Owner | Waiting on | PR |%s" % (" Build |" if auto else ""),
                  "| --- | --- | --- | --- | --- | --- | --- |%s" % (" --- |" if auto else "")]
        for t in group:
            lines.append("| [%s](%s) | %s | %s | %s | %s | %s | %s |%s" % (
                t.id, t.path.name, _cell(t.get("title")), _cell(t.get("repo")), _cell(t.get("wave")),
                _cell(t.get("owner")), _md_list(waiting_on(t, by_id)), _cell(t.get("pr")),
                " %s |" % _cell(auto_cell(auto.get(t.id))) if auto else ""))
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- shared


def write_if_changed(path, text):
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def open_dashboard(ws, script=None):
    """Start the live dashboard and open it. Returns its "Dashboard: ..." line, or None when
    the dashboard skill is not next to this one or did not start."""
    script = Path(script or DASHBOARD)
    if not script.is_file():
        return None
    try:
        # Its output goes to a file, not a pipe: the server it leaves running must not hold us up.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out:
            done = subprocess.run([sys.executable, str(script), "--start", "--workspace", str(ws)],
                                  stdout=out, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=60)
            out.seek(0)
            text = out.read()
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return next((l.strip() for l in text.splitlines() if l.strip().startswith("Dashboard:")), None)
