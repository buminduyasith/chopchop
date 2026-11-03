"""Write the generated files: plan.md, status.md and board.html.

board.html is a fixed template (templates/board.html) with the data put in as JSON, so the
page looks the same every run and no one has to write HTML.
"""

import json
from datetime import datetime
from pathlib import Path

from .features import render_front_matter
from .tasks import STATUS_TITLES, STATUSES, as_list, find_section, waiting_on

DATA_MARK = "/*__RELAY_DATA__*/null"
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
    lines = [render_front_matter(plan_meta).rstrip(), "",
             "# Plan · %s" % feature.name, "",
             "_Written by chopchop from the task files. Only the Notes section is yours to edit._", "",
             "- **Base branch:** %s" % ("`%s`" % base if base else "not set"),
             "- **Feature branch:** %s" % ("`%s`" % fbranch if fbranch else "not created yet"),
             "- **Tasks:** %d in %d wave(s)" % (len(tasks), len({t.get("wave") for t in tasks})),
             "- **Repos:** %s" % _md_list(repos), ""]

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


def render_status(feature, tasks):
    by_id = {t.id: t for t in tasks}
    counts = {s: sum(1 for t in tasks if t.get("status") == s) for s in STATUSES}
    lines = ["# Status · %s" % feature.name, "",
             "_Written by chopchop from the task files. Do not edit. Change a status with "
             "`/chopchop:tasks --set <task> <status>`._", "",
             " · ".join("%s **%d**" % (STATUS_TITLES[s], counts[s]) for s in STATUSES) +
             " (%d of %d done)" % (counts["done"], len(tasks)), ""]
    for s in STATUSES:
        group = [t for t in tasks if t.get("status") == s]
        lines += ["## %s" % STATUS_TITLES[s], ""]
        if not group:
            lines += ["_None._", ""]
            continue
        lines += ["| Task | Title | Repo | Wave | Owner | Waiting on | PR |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for t in group:
            lines.append("| [%s](%s) | %s | %s | %s | %s | %s | %s |" % (
                t.id, t.path.name, _cell(t.get("title")), _cell(t.get("repo")), _cell(t.get("wave")),
                _cell(t.get("owner")), _md_list(waiting_on(t, by_id)), _cell(t.get("pr"))))
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- board.html


def board_data(feature, tasks, plan_meta, changelog, branches, base=None):
    by_id = {t.id: t for t in tasks}
    out = []
    for t in tasks:
        changes = [c["id"] for c in changelog if c["task"] == t.id or t.id in c["affects"]]
        out.append({
            "id": t.id, "title": t.get("title", ""), "status": t.get("status", "todo"),
            "repo": t.get("repo"), "wave": t.get("wave"), "size": t.get("size"), "owner": t.get("owner"),
            "depends_on": as_list(t.get("depends_on")), "waiting_on": waiting_on(t, by_id),
            "stories": as_list(t.get("stories")), "pr": t.get("pr"), "branch": branches.get(t.id),
            "file": t.path.name, "changes": changes, "body": t.body.strip(),
        })
    return {
        "feature": feature.name, "number": "%03d" % feature.number, "epic": feature.epic,
        "title": feature.meta.get("title") or plan_meta.get("title") or feature.slug.replace("-", " "),
        "generated": now(), "base_branch": plan_meta.get("base_branch") or base,
        "feature_branch": plan_meta.get("feature_branch"),
        "statuses": [{"id": s, "title": STATUS_TITLES[s]} for s in STATUSES],
        "tasks": out, "changelog": changelog,
    }


def render_board(template_text, data):
    if DATA_MARK not in template_text:
        raise ValueError("board template has no %s marker" % DATA_MARK)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return template_text.replace(DATA_MARK, payload, 1)


def write_if_changed(path, text):
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True
