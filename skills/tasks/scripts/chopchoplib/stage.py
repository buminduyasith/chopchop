"""Where a feature stands, read from its files. This module keeps no state of its own.

  groom -> brief -> design -> spec -> tasks -> build -> prs -> done

People decide at three gates: the brief (you), the design (the lead) and the spec (you).
Agents do the rest. /chopchop:run and the dashboard both ask this module the same question:
which step is the feature on, who is it waiting for, and what is the next move.
"""

import json
from pathlib import Path

from . import plain
from . import tasks as tasklib
from .features import read_front_matter

STAGES = ["groom", "brief", "design", "spec", "tasks", "build", "prs", "done"]
LABELS = {"groom": "Groom", "brief": "Brief", "design": "Design", "spec": "Spec", "tasks": "Tasks",
          "build": "Build", "prs": "Review", "done": "Done"}
GATES = {"brief": "you", "design": "lead", "spec": "you"}
WHO = {"you": "you", "lead": "the lead", "ba": "the BA", "reviewers": "the reviewers", "chopchop": "chopchop"}
VERDICTS = ["real", "false-positive", "negotiable", "question", "praise", "outdated"]
NEEDS_DECISION = ("real", "false-positive", "negotiable", "question")


def paths(feature):
    p = Path(feature.path)
    return {
        "requirement": p / "requirements" / "requirement.md",
        "grooming": p / "requirements" / "grooming.md",
        "brief": p / "requirements" / "brief.md",
        "design": p / "design" / "design.md",
        "options": p / "design" / "options.md",
        "spec": p / "spec" / "spec.md",
        "spec_json": p / "spec" / "spec.json",
        "tasks": p / "tasks",
        "auto": p / "work" / "auto.json",
        "comments": p / "work" / "comments",
        "check": p / "check.md",
    }


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def approved(meta):
    """True when a design.md, spec.md or brief.md front matter says a person approved it and it has not changed since."""
    if not meta:
        return False
    status = str(meta.get("status") or "")
    ok = status.startswith("approved") or bool(meta.get("approved_by"))
    return ok and not meta.get("changed_since_approval")


# --------------------------------------------------------------------------- the parts


def comments_view(folder):
    """Counts from work/comments: PRs, review comments, and how many still need a person."""
    folder = Path(folder)
    prs = (_json(folder / "prs.json") or {}).get("prs") or []
    threads = (_json(folder / "threads.json") or {}).get("threads") or []
    triage = _json(folder / "triage.json") or {}
    items = triage.get("items") or {}
    live = [t for t in threads if not t.get("resolved") and not t.get("outdated")]
    new = [t for t in live if t.get("id") not in items or items[t["id"]].get("hash") != t.get("hash")]
    by_verdict = {v: 0 for v in VERDICTS}
    undecided = to_fix = fixed = replied = 0
    for t in live:
        it = items.get(t.get("id"))
        if not it or it.get("hash") != t.get("hash"):
            continue
        if it.get("verdict") in by_verdict:
            by_verdict[it["verdict"]] += 1
        if it.get("state") == "fixed":
            fixed += 1
        elif it.get("state") == "replied":
            replied += 1
        elif it.get("decision") == "fix":
            to_fix += 1
        elif not it.get("decision") and it.get("verdict") in NEEDS_DECISION:
            undecided += 1
    return {
        "prs": prs,
        "open": sum(1 for p in prs if p.get("state") == "open"),
        "merged": sum(1 for p in prs if p.get("state") == "merged"),
        "closed": sum(1 for p in prs if p.get("state") == "closed"),
        "threads": len(threads), "live": len(live), "new": len(new), "undecided": undecided,
        "to_fix": to_fix, "fixed": fixed, "replied": replied, "by_verdict": by_verdict,
        "groups": len(triage.get("groups") or []),
        "watching": bool(((_json(folder / "prs.json") or {}).get("watch") or {}).get("on")),
    }


def auto_view(auto):
    """A short view of work/auto.json, or None when there is no run."""
    if not isinstance(auto, dict) or not isinstance(auto.get("tasks"), dict):
        return None
    states = {}
    for t in auto["tasks"].values():
        states[t.get("state")] = states.get(t.get("state"), 0) + 1
    repos = auto.get("repos") or {}
    return {
        "current": auto.get("current"),
        "states": states,
        "queue": auto.get("queue") or [],
        "finished": auto.get("finished"),
        "stopped": [tid for tid, t in auto["tasks"].items() if t.get("state") == "stopped"],
        "paused": [r["paused"].get("task") for r in repos.values() if isinstance(r.get("paused"), dict)],
        "prs": {name: r.get("pr") for name, r in repos.items() if r.get("pr")},
        "pushed": [name for name, r in repos.items() if r.get("pushed")],
        "repos": [name for name, r in repos.items() if any(t.get("repo") == name and t.get("state") == "committed"
                                                           for t in auto["tasks"].values())],
        "pr_mode": (auto.get("options") or {}).get("pr"),
        "task_state": {tid: t.get("state") for tid, t in auto["tasks"].items()},
    }


def title_of(feature, metas):
    for key in ("brief", "design", "spec"):
        if metas.get(key) and metas[key].get("title"):
            return str(metas[key]["title"])
    return str(feature.meta.get("title") or feature.slug.replace("-", " "))


def summary_of(f):
    """A few plain lines for the feature card: the newest document that has a Summary wins."""
    for key in ("brief", "design", "spec"):
        text = _text(f[key])
        points = plain.summary_points(text, 3) if text else []
        if points:
            return points
    return []


# --------------------------------------------------------------------------- the stage


def read(feature):
    """Everything /chopchop:run and the dashboard need to know about one feature."""
    f = paths(feature)
    exists = {k: (v.is_dir() if k in ("tasks", "comments") else v.is_file()) for k, v in f.items()}
    metas = {k: (read_front_matter(f[k]) if exists[k] else None) for k in ("grooming", "brief", "design", "spec")}
    found = tasklib.load_tasks(f["tasks"]) if exists["tasks"] else []
    counts = {s: sum(1 for t in found if t.get("status") == s) for s in tasklib.STATUSES}
    auto = auto_view(_json(f["auto"])) if exists["auto"] else None
    com = comments_view(f["comments"])
    groom, brief, design, spec = metas["grooming"], metas["brief"], metas["design"], metas["spec"]

    # A feature made before grooming existed has a design but no brief: do not send it back.
    legacy = not exists["grooming"] and not exists["brief"] and (exists["design"] or exists["spec_json"] or bool(found))
    committed = set()
    if auto:
        committed = {tid for tid, st in auto["task_state"].items() if st == "committed"}
    open_tasks = [t for t in found if t.get("status") in ("todo", "in-progress") and t.id not in committed]

    stage, who, text, nxt = None, None, "", None
    num = str(feature.number)

    def at(s, w, sentence, skill=None, args=None, say=None):
        return s, w, sentence, ({"skill": skill, "args": args or num, "say": say} if skill or say else None)

    if not legacy and not exists["brief"]:
        g = groom or {}
        open_dev = int(g.get("open_dev") or 0)
        open_ba = int(g.get("open_ba") or 0)
        if not exists["requirement"] and not exists["grooming"]:
            stage, who, text, nxt = at("groom", "chopchop", "Nothing is written yet. Grooming starts it.", "groom")
        elif not exists["grooming"]:
            stage, who, text, nxt = at("groom", "chopchop", "The stories are in. Next: check them against the code.", "groom")
        elif open_dev:
            stage, who, text, nxt = at("groom", "you", "%d question(s) wait for your answer." % open_dev, "groom")
        elif open_ba:
            stage, who, text, nxt = at("groom", "ba", "%d question(s) wait for the BA. Paste the answers when you have them."
                                       % open_ba, "groom")
        else:
            stage, who, text, nxt = at("groom", "chopchop", "All questions are answered. Next: write the brief.", "groom")
    elif not legacy and not approved(brief):
        stage, who, text, nxt = at("brief", "you", "Read the brief. Say approve when it is right.", None, None,
                                   "approve the brief")
    elif not exists["design"]:
        stage, who, text, nxt = at("design", "chopchop", "Next: write the design.", "design")
    elif str((design or {}).get("status") or "") == "changes-needed":
        stage, who, text, nxt = at("design", "chopchop", "The lead asked for changes. Next: change the design.", "design")
    elif not approved(design):
        again = " It changed after the last approval." if (design or {}).get("changed_since_approval") else ""
        stage, who, text, nxt = at("design", "lead", "The lead reads the design and approves it.%s" % again, None, None,
                                   "approve the design")
    elif not exists["spec_json"] or str((spec or {}).get("status") or "draft") == "draft":
        stage, who, text, nxt = at("spec", "chopchop", "Next: write the spec." if not exists["spec_json"]
                                   else "The spec has open checks. Next: finish it.", "spec")
    elif not found and not approved(spec):
        stage, who, text, nxt = at("spec", "you", "Read the spec. Say approve when it is right.", None, None,
                                   "approve the spec")
    elif not found:
        stage, who, text, nxt = at("tasks", "chopchop", "Next: cut the spec into tasks.", "tasks")
    elif found and counts["done"] == len(found):
        stage, who, text, nxt = at("done", None, "Every task is done.")
    elif open_tasks:
        stopped = (auto or {}).get("stopped") or []
        if stopped:
            stage, who, text, nxt = at("build", "you", "%s stopped. A person decides, then the build goes on."
                                       % ", ".join(stopped), "auto", "--status")
        elif auto and auto.get("current"):
            stage, who, text, nxt = at("build", "chopchop", "Building %s." % auto["current"], "auto", "--resume")
        else:
            left = len(open_tasks)
            stage, who, text, nxt = at("build", "chopchop", "%d task(s) left to build." % left, "auto",
                                       "--resume" if auto and not auto.get("finished") else num)
    else:
        no_pr = bool(committed) and not com["prs"] and not (auto or {}).get("prs") and \
            not any(t.get("pr") for t in found)
        pushed_all = bool(auto) and bool(auto["repos"]) and all(r in auto["pushed"] for r in auto["repos"])
        if no_pr and pushed_all:
            stage, who, text, nxt = at("prs", "you", "Everything is built and pushed. Open the PR for %s, then give "
                                       "chopchop the link." % ", ".join(auto["repos"]), "auto", "--status")
        elif no_pr:
            stage, who, text, nxt = at("prs", "chopchop", "Everything is built. Next: push and open the PRs.",
                                       "auto", "--resume")
        elif com["new"]:
            stage, who, text, nxt = at("prs", "chopchop", "%d new review comment(s) to explain." % com["new"], "comments")
        elif com["undecided"]:
            stage, who, text, nxt = at("prs", "you", "%d review comment(s) need your call: fix, reply or skip."
                                       % com["undecided"], "comments")
        elif com["to_fix"]:
            stage, who, text, nxt = at("prs", "chopchop", "%d review comment(s) to fix." % com["to_fix"], "comments", num + " --fix")
        else:
            stage, who, text, nxt = at("prs", "reviewers", "The PRs wait for review and merge.", "comments")

    i = STAGES.index(stage)
    steps = []
    for n, s in enumerate(STAGES):
        if legacy and s in ("groom", "brief"):
            state = "skipped"
        elif n < i or stage == "done":
            state = "done"
        elif n == i:
            state = "waiting" if who and who != "chopchop" else "now"
        else:
            state = "todo"
        steps.append({"id": s, "label": LABELS[s], "state": state})

    return {
        "number": feature.number, "folder": feature.name, "path": str(feature.path), "epic": feature.epic,
        "title": title_of(feature, metas), "mode": (groom or {}).get("mode") or ("locked" if feature.epic and not
                                                    str(feature.epic).upper().startswith("IDEA") else "open"),
        "stage": stage, "label": LABELS[stage], "steps": steps,
        "waiting_on": who, "waiting_who": WHO.get(who) if who else None, "waiting": text, "next": nxt,
        "summary": summary_of(f),
        "docs": {k: str(v) for k, v in f.items() if exists.get(k) and k not in ("tasks", "comments", "auto")},
        "status": {"brief": (brief or {}).get("status"), "design": (design or {}).get("status"),
                   "spec": (spec or {}).get("status"), "brief_ok": approved(brief), "design_ok": approved(design),
                   "spec_ok": approved(spec)},
        "tasks": dict(counts, total=len(found), committed=len(committed)),
        "auto": auto, "comments": {k: v for k, v in com.items() if k != "prs"}, "prs": com["prs"],
    }


def line(st):
    """One plain line: where the feature is and who it waits for."""
    who = "" if not st.get("waiting_on") else " · waiting on %s" % st["waiting_who"]
    return "%03d %s · %s%s · %s" % (st["number"], st["title"], st["label"], who, st["waiting"])
