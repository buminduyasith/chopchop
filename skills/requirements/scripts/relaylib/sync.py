"""Write normalized issues into _relay/features/<feature>/requirements/.

Ownership rules (so a sync never destroys human or agent work):
- The script owns the front matter keys in SCRIPT_KEYS and the <!-- relay:NAME -->
  blocks. It rewrites those on every sync.
- Everything else in a story file (acceptance criteria, questions, notes) belongs
  to the agent and people. The script never touches it, except with --fresh.
- Text between <!-- keep --> and <!-- /keep --> survives even --fresh.

A story "needs analysis" when its source_hash differs from its analysed_hash.
The agent sets analysed_hash (via `relay_req.py mark-analysed`) after it has
written the acceptance criteria. So a change is never lost, even if a later
sync runs before anyone analysed it.
"""

import difflib
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import mdconv
from .schema import CONTENT_FIELDS, META_FIELDS

SCRIPT_KEYS = ("id", "title", "type", "status", "priority", "assignee", "story_points",
               "labels", "parent", "url", "source_updated", "synced", "sync_state",
               "source_hash", "analysis")
KEEP_RE = re.compile(r"<!-- keep -->.*?<!-- /keep -->", re.S)


# --------------------------------------------------------------------------- small utils


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def slugify(text, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0] or s[:limit]
    return s or "feature"


def digest(obj):
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text.rstrip() + "\n", encoding="utf-8")


def content_part(issue):
    part = {k: issue.get(k) for k in CONTENT_FIELDS}
    part["attachments"] = sorted(a.get("name", "") for a in issue.get("attachments") or [])
    return part


def meta_part(issue):
    return {k: issue.get(k) for k in META_FIELDS}


def comments_part(issue):
    return [(c.get("author"), c.get("created"), c.get("body")) for c in issue.get("comments") or []]


def source_hash(issue):
    return digest({"content": content_part(issue), "comments": comments_part(issue)})


# --------------------------------------------------------------------------- front matter + blocks


def split_front_matter(text):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[4:end].split("\n"):
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        raw = raw.strip()
        try:
            meta[key.strip()] = json.loads(raw) if raw else None
        except ValueError:
            meta[key.strip()] = raw
    return meta, text[end + 5:]


def join_front_matter(meta, body):
    lines = ["---"]
    for key, value in meta.items():
        lines.append("%s: %s" % (key, json.dumps(value, ensure_ascii=False)))
    lines.append("---")
    return "\n".join(lines) + "\n" + body.lstrip("\n")


def set_block(text, name, content):
    start, end = "<!-- relay:%s -->" % name, "<!-- /relay:%s -->" % name
    new = "%s\n%s\n%s" % (start, content.strip("\n"), end) if content.strip() else "%s\n%s" % (start, end)
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if pattern.search(text):
        return pattern.sub(lambda _m: new, text, count=1)
    return text.rstrip() + "\n\n" + new + "\n"


def get_block(text, name):
    m = re.search(r"<!-- relay:%s -->\n?(.*?)<!-- /relay:%s -->" % (re.escape(name), re.escape(name)), text, re.S)
    return m.group(1).strip() if m else ""


# --------------------------------------------------------------------------- feature folders


def resolve_feature(workspace, feature=None, epic=None, epic_title=None, must_exist=False):
    """Pick the feature folder.

    feature: exact folder name, or a unique prefix of one (PAY-120 finds PAY-120-refund-flow).
    epic:    when no feature is given, reuse a folder starting with "<EPIC>-", or create one.
    """
    root = Path(workspace) / "features"
    existing = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if feature:
        if feature in existing:
            return root / feature
        matches = [n for n in existing if n.startswith(feature + "-") or n.lower() == feature.lower()]
        if len(matches) == 1:
            return root / matches[0]
        if len(matches) > 1:
            raise ValueError("'%s' matches several features: %s. Use the full name." % (feature, ", ".join(matches)))
        if must_exist:
            raise ValueError("No feature called '%s'. Existing: %s" % (feature, ", ".join(existing) or "none"))
        return root / (feature if re.match(r"^[A-Za-z0-9._-]+$", feature) else slugify(feature))
    if epic:
        matches = [n for n in existing if n == epic or n.startswith(epic + "-")]
        if matches:
            return root / matches[0]
        if must_exist:
            raise ValueError("No feature folder for epic %s yet." % epic)
        return root / ("%s-%s" % (epic, slugify(epic_title)) if epic_title else epic)
    raise ValueError("Give an epic ID or a feature name.")


def load_manifest(feature_dir):
    return read_json(Path(feature_dir) / "requirements" / ".source" / "manifest.json", default=None)


# --------------------------------------------------------------------------- rendering


def _join(values):
    return ", ".join(str(v) for v in values if v not in (None, "")) if values else ""


def _size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def _provider_label(issue):
    return (issue.get("provider") or "tracker").capitalize()


def render_source(issue, synced_at):
    """The machine-owned Source block for one story."""
    pid = issue["id"]
    link = "[%s](%s)" % (pid, issue["url"]) if issue.get("url") else pid
    updated = (issue.get("updated") or "")[:16].replace("T", " ")
    out = ["## Source",
           "_From %s %s%s · synced %s. Replaced on every sync, do not edit here._" % (
               _provider_label(issue), link, (" · updated " + updated) if updated else "",
               synced_at[:16].replace("T", " "))]
    facts = []
    for label, value in (("Type", issue.get("type")), ("Status", issue.get("status")),
                         ("Priority", issue.get("priority")), ("Points", issue.get("story_points")),
                         ("Assignee", issue.get("assignee")), ("Reporter", issue.get("reporter")),
                         ("Parent", issue.get("parent")), ("Labels", _join(issue.get("labels"))),
                         ("Components", _join(issue.get("components"))),
                         ("Fix versions", _join(issue.get("fix_versions")))):
        if value not in (None, ""):
            facts.append("**%s:** %s" % (label, value))
    if facts:
        out.append(" · ".join(facts))

    out.append("### Description")
    out.append(mdconv.demote_headings(issue.get("description"), 3) or "_Empty in the tracker._")
    if issue.get("acceptance_criteria"):
        out.append("### Acceptance criteria (as written in the tracker)")
        out.append(mdconv.demote_headings(issue["acceptance_criteria"], 3))
    for name, value in (issue.get("extra") or {}).items():
        if value not in (None, "", [], {}):
            out.append("### %s" % name)
            out.append(mdconv.demote_headings(str(value), 3))
    if issue.get("subtasks"):
        out.append("### Sub-tasks")
        out.extend("- %s %s%s" % (s.get("id"), s.get("title", ""), (" (%s)" % s["status"]) if s.get("status") else "")
                   for s in issue["subtasks"])
    if issue.get("links"):
        out.append("### Links")
        out.extend("- %s %s %s%s" % (l.get("relation", "relates to"), l.get("id"), l.get("title", ""),
                                     (" (%s)" % l["status"]) if l.get("status") else "")
                   for l in issue["links"])
    if issue.get("attachments"):
        out.append("### Attachments")
        for a in issue["attachments"]:
            name = a.get("name") or "file"
            item = "[%s](%s)" % (name, a["url"]) if a.get("url") else name
            extra = _join([a.get("mime"), _size(a.get("size"))])
            out.append("- %s%s" % (item, (" (%s)" % extra) if extra else ""))
    comments = issue.get("comments") or []
    if comments:
        out.append("### Comments (%d)" % len(comments))
        for c in comments:
            out.append("**%s** · %s" % (c.get("author") or "unknown", (c.get("created") or "")[:10]))
            body = mdconv.demote_headings(c.get("body") or "", 4)
            out.append("\n".join(("> " + l) if l else ">" for l in body.split("\n")))
    return "\n\n".join(out)


def story_template(issue):
    return "\n".join([
        "# %s · %s" % (issue["id"], issue.get("title") or "(no title)"),
        "",
        "<!-- relay:banner -->",
        "<!-- /relay:banner -->",
        "",
        "## Acceptance criteria",
        "",
        "_Not analysed yet._",
        "",
        "## Open questions",
        "",
        "_None yet._",
        "",
        "## Notes",
        "",
        "<!-- keep -->",
        "<!-- /keep -->",
        "",
        "<!-- relay:source -->",
        "<!-- /relay:source -->",
        "",
    ])


def analysis_state(meta):
    if meta.get("sync_state") == "removed":
        return "removed"
    if not meta.get("analysed_hash"):
        return "pending"
    return "done" if meta.get("analysed_hash") == meta.get("source_hash") else "stale"


def banner_for(meta, changed_fields, synced_at):
    state = meta.get("analysis")
    if meta.get("sync_state") == "removed":
        return "> **Removed.** This story is no longer part of the source (checked %s). Kept for history." % synced_at[:10]
    if state == "stale":
        fields = ", ".join(changed_fields) if changed_fields else "content"
        return ("> **Changed in the tracker** (%s). The acceptance criteria below may be out of date. "
                "See `requirements/sync-report.md`." % fields)
    if state == "pending":
        return "> **New.** Not analysed yet."
    return ""


def write_story(path, issue, synced_at, sync_state, changed_fields, fresh=False):
    path = Path(path)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    old_meta, body = split_front_matter(existing) if existing else ({}, "")
    keep_blocks = KEEP_RE.findall(body)

    if not existing or fresh:
        body = story_template(issue)
        if keep_blocks:
            body = body.replace("<!-- keep -->\n<!-- /keep -->", "\n\n".join(keep_blocks), 1)
        if fresh:
            old_meta.pop("analysed_hash", None)
    else:
        # keep the title line in step with the tracker
        body = re.sub(r"^# .*$", "# %s · %s" % (issue["id"], issue.get("title") or "(no title)"), body, count=1, flags=re.M)

    meta = {}
    meta["id"] = issue["id"]
    meta["title"] = issue.get("title")
    meta["type"] = issue.get("type")
    meta["status"] = issue.get("status")
    meta["priority"] = issue.get("priority")
    meta["assignee"] = issue.get("assignee")
    meta["story_points"] = issue.get("story_points")
    meta["labels"] = issue.get("labels") or []
    meta["parent"] = issue.get("parent")
    meta["url"] = issue.get("url")
    meta["source_updated"] = issue.get("updated")
    meta["synced"] = synced_at
    meta["sync_state"] = sync_state
    meta["source_hash"] = source_hash(issue)
    for key, value in old_meta.items():  # keep analysed_hash and anything people added
        if key not in SCRIPT_KEYS:
            meta[key] = value
    meta["analysis"] = analysis_state(meta)

    body = set_block(body, "source", render_source(issue, synced_at))
    body = set_block(body, "banner", banner_for(meta, changed_fields, synced_at))
    write_text(path, join_front_matter(meta, body))
    return meta


def mark_removed(path, synced_at):
    path = Path(path)
    if not path.is_file():
        return None
    meta, body = split_front_matter(path.read_text(encoding="utf-8"))
    if meta.get("sync_state") == "removed":
        return meta
    meta["sync_state"] = "removed"
    meta["synced"] = synced_at
    meta["analysis"] = analysis_state(meta)
    body = set_block(body, "banner", banner_for(meta, [], synced_at))
    write_text(path, join_front_matter(meta, body))
    return meta


def mark_analysed(feature_dir, story_ids=None):
    """Set analysed_hash = source_hash. Returns the ids that changed."""
    stories = Path(feature_dir) / "requirements" / "stories"
    done = []
    for path in sorted(stories.glob("*.md")):
        meta, body = split_front_matter(path.read_text(encoding="utf-8"))
        if story_ids and meta.get("id") not in story_ids:
            continue
        if meta.get("sync_state") == "removed":
            continue
        if meta.get("analysed_hash") == meta.get("source_hash") and meta.get("analysis") == "done":
            continue
        meta["analysed_hash"] = meta.get("source_hash")
        meta["analysed"] = now_iso()
        meta["analysis"] = analysis_state(meta)
        body = set_block(body, "banner", "")
        write_text(path, join_front_matter(meta, body))
        done.append(meta.get("id"))
    if story_ids:
        unknown = sorted(set(story_ids) - {m for m in _story_ids(stories)})
        if unknown:
            raise ValueError("Unknown story ids: %s" % ", ".join(unknown))
    write_overview_index(feature_dir)
    return done


def _story_ids(stories_dir):
    for path in stories_dir.glob("*.md"):
        meta, _ = split_front_matter(path.read_text(encoding="utf-8"))
        if meta.get("id"):
            yield meta["id"]


def read_story_metas(feature_dir):
    stories = Path(feature_dir) / "requirements" / "stories"
    metas = []
    for path in sorted(stories.glob("*.md")):
        meta, _ = split_front_matter(path.read_text(encoding="utf-8"))
        if meta.get("id"):
            meta["_file"] = path.name
            metas.append(meta)
    return metas


def write_overview_index(feature_dir):
    path = Path(feature_dir) / "requirements" / "overview.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    rows = ["| Story | Title | Type | Status | Points | Analysis |",
            "| --- | --- | --- | --- | --- | --- |"]
    for m in read_story_metas(feature_dir):
        title = (m.get("title") or "").replace("|", "\\|")
        if m.get("sync_state") == "removed":
            title = "~~%s~~" % title
        rows.append("| [%s](stories/%s) | %s | %s | %s | %s | %s |" % (
            m["id"], m["_file"], title, m.get("type") or "", m.get("status") or "",
            "" if m.get("story_points") is None else m.get("story_points"), m.get("analysis") or ""))
    write_text(path, set_block(text, "index", "\n".join(rows)))


def overview_template(feature_name):
    return "\n".join([
        "# %s · requirements" % feature_name,
        "",
        "<!-- relay:epic -->",
        "<!-- /relay:epic -->",
        "",
        "## Summary",
        "",
        "_Not written yet._",
        "",
        "## Stories",
        "",
        "<!-- relay:index -->",
        "<!-- /relay:index -->",
        "",
    ])


def render_epic(epic, source):
    if not epic:
        ids = ", ".join(source.get("ids") or [])
        return "_Built from a list of stories: %s._" % (ids or "none")
    link = "[%s](%s)" % (epic["id"], epic["url"]) if epic.get("url") else epic["id"]
    head = "**Epic:** %s · %s%s" % (link, epic.get("title") or "", (" · " + epic["status"]) if epic.get("status") else "")
    parts = [head]
    if epic.get("description"):
        parts.append(mdconv.demote_headings(epic["description"], 2))
    if source.get("ids"):
        parts.append("_Also includes stories added by id: %s._" % ", ".join(source["ids"]))
    return "\n\n".join(parts)


QUESTIONS_TEMPLATE = """# Open questions

Questions for the BA and the team. Keep ids stable (Q1, Q2...). Mark answered ones
with the answer and the date instead of deleting them.

| ID | Story / AC | Question | Asked | Answer |
| --- | --- | --- | --- | --- |
"""


FEATURE_TEMPLATE = """feature: {name}
epic: {epic}
stage: requirements   # requirements | design | tasks | checked | building | feature-review | done
created: {created}
gates:
  requirements: null
  design: null
  tasks: null
  ship: null
"""


# --------------------------------------------------------------------------- ingest


def _diff(old, new, label):
    old_lines = (old or "").split("\n")
    new_lines = (new or "").split("\n")
    lines = list(difflib.unified_diff(old_lines, new_lines, "before/" + label, "after/" + label, lineterm="", n=2))
    if len(lines) > 120:
        lines = lines[:120] + ["... (%d more lines)" % (len(lines) - 120)]
    return "\n".join(lines)


def compare(old, new):
    """Return (state, changed_content_fields, changed_meta_fields, new_comment_count)."""
    if old is None:
        return "new", [], [], len(new.get("comments") or [])
    content = [k for k in CONTENT_FIELDS if content_part(old).get(k) != content_part(new).get(k)]
    meta = [k for k in META_FIELDS if old.get(k) != new.get(k)]
    old_c = comments_part(old)
    new_c = comments_part(new)
    added = len([c for c in new_c if c not in old_c])
    if old_c != new_c:
        content.append("comments")
    if content:
        return "changed", content, meta, added
    return ("meta" if meta else "unchanged"), [], meta, 0


def ingest(workspace, feature_dir, epic, issues, source, provider_name, fresh=False,
           dry_run=False, full_set=True, missing=None, warnings=None):
    """Sync issues into the feature folder. Returns a report dict."""
    feature_dir = Path(feature_dir)
    req = feature_dir / "requirements"
    src = req / ".source"
    stories_dir = req / "stories"
    synced_at = now_iso()
    created_feature = not feature_dir.exists()

    manifest = read_json(src / "manifest.json", default=None) or {
        "provider": provider_name, "source": {"epic": None, "ids": []}, "stories": {}}
    merged_source = {
        "epic": source.get("epic") or manifest["source"].get("epic"),
        "ids": sorted(set(manifest["source"].get("ids") or []) | set(source.get("ids") or [])),
    }

    report = {"feature": feature_dir.name, "feature_dir": str(feature_dir), "synced": synced_at,
              "provider": provider_name, "source": merged_source, "created_feature": created_feature,
              "dry_run": dry_run, "fresh": fresh, "new": [], "changed": [], "meta": [], "unchanged": [],
              "removed": [], "missing": sorted(missing or []), "needs_analysis": [],
              "warnings": list(warnings or []), "details": {}}

    seen = set()
    for issue in issues:
        sid = issue["id"]
        if sid in seen:
            continue
        seen.add(sid)
        old = read_json(src / ("%s.json" % sid), default=None)
        state, changed, meta_changed, new_comments = compare(old, issue)
        report[state].append(sid)
        detail = {"title": issue.get("title"), "changed": changed, "meta_changed": meta_changed}
        if state == "changed":
            diffs = {}
            for field in ("title", "description", "acceptance_criteria"):
                if field in changed:
                    diffs[field] = _diff(old.get(field), issue.get(field), "%s.%s" % (sid, field))
            if "extra" in changed:
                diffs["extra"] = _diff(json.dumps(old.get("extra"), indent=1, ensure_ascii=False),
                                       json.dumps(issue.get("extra"), indent=1, ensure_ascii=False), sid + ".extra")
            detail["diffs"] = diffs
            detail["new_comments"] = new_comments
        if meta_changed and old is not None:
            detail["meta_values"] = {k: [old.get(k), issue.get(k)] for k in meta_changed
                                     if k not in ("subtasks", "links")}
        report["details"][sid] = detail

        entry = manifest["stories"].get(sid, {})
        entry.update({"state": "active", "source_hash": source_hash(issue), "last_seen": synced_at,
                      "via": "id" if sid in (source.get("ids") or []) else entry.get("via", "epic")})
        entry.setdefault("first_seen", synced_at)
        manifest["stories"][sid] = entry

        if not dry_run:
            write_json(src / ("%s.json" % sid), issue)
            meta = write_story(stories_dir / ("%s.md" % sid), issue, synced_at,
                               "new" if state == "new" else ("changed" if state == "changed" else "unchanged"),
                               changed, fresh=fresh)
            if meta["analysis"] != "done":
                report["needs_analysis"].append(sid)
        else:
            if state in ("new", "changed"):
                report["needs_analysis"].append(sid)

    # stories that disappeared from the source
    if full_set:
        for sid, entry in sorted(manifest["stories"].items()):
            if entry.get("state") == "active" and sid not in seen and sid not in (merged_source["ids"] or []):
                report["removed"].append(sid)
                entry["state"] = "removed"
                entry["removed"] = synced_at
                if not dry_run:
                    mark_removed(stories_dir / ("%s.md" % sid), synced_at)
    for sid in report["missing"]:
        entry = manifest["stories"].get(sid)
        if entry and entry.get("state") == "active":
            report["removed"].append(sid)
            entry["state"] = "removed"
            entry["removed"] = synced_at
            if not dry_run:
                mark_removed(stories_dir / ("%s.md" % sid), synced_at)

    # already-synced stories whose analysis is still open (from an earlier sync)
    if not dry_run:
        for m in read_story_metas(feature_dir):
            if m["id"] not in report["needs_analysis"] and m.get("analysis") in ("pending", "stale"):
                report["needs_analysis"].append(m["id"])

    if dry_run:
        return report

    manifest.update({"provider": provider_name, "source": merged_source, "last_sync": synced_at})
    if epic:
        manifest["epic"] = {"id": epic["id"], "title": epic.get("title"), "hash": source_hash(epic)}
        write_json(src / ("%s.json" % epic["id"]), epic)
    write_json(src / "manifest.json", manifest)

    overview = req / "overview.md"
    if not overview.is_file() or fresh:
        old_text = overview.read_text(encoding="utf-8") if overview.is_file() else ""
        text = overview_template(feature_dir.name)
        keeps = KEEP_RE.findall(old_text)
        if keeps:
            text = text.rstrip() + "\n\n" + "\n\n".join(keeps) + "\n"
        write_text(overview, text)
    write_text(overview, set_block(overview.read_text(encoding="utf-8"), "epic", render_epic(epic, merged_source)))
    write_overview_index(feature_dir)

    if not (req / "questions.md").is_file():
        write_text(req / "questions.md", QUESTIONS_TEMPLATE)
    if not (feature_dir / "feature.yaml").is_file():
        write_text(feature_dir / "feature.yaml", FEATURE_TEMPLATE.format(
            name=feature_dir.name, epic=merged_source["epic"] or "null", created=today()))

    write_json(src / "last-sync.json", report)
    write_text(req / "sync-report.md", render_report(report))
    return report


def render_report(r):
    out = ["# Sync report · %s" % r["feature"], "",
           "Synced %s from %s. Source: %s." % (
               r["synced"].replace("T", " ").replace("Z", " UTC"), r["provider"],
               _describe_source(r["source"])), ""]
    counts = ["%d new" % len(r["new"]), "%d changed" % len(r["changed"]),
              "%d status-only updates" % len(r["meta"]), "%d unchanged" % len(r["unchanged"]),
              "%d removed" % len(r["removed"])]
    out.append("**" + " · ".join(counts) + "**")
    out.append("")
    if r["needs_analysis"]:
        out.append("**Needs analysis:** " + ", ".join(r["needs_analysis"]))
        out.append("")
    if r["missing"]:
        out.append("**Not found in the tracker:** %s (deleted, moved, or no access)" % ", ".join(r["missing"]))
        out.append("")
    for w in r.get("warnings") or []:
        out.append("> Warning: %s" % w)
    if r.get("warnings"):
        out.append("")

    def title(sid):
        return (r["details"].get(sid) or {}).get("title") or ""

    if r["new"]:
        out.append("## New")
        out.extend("- %s %s" % (s, title(s)) for s in r["new"])
        out.append("")
    if r["changed"]:
        out.append("## Changed")
        for s in r["changed"]:
            d = r["details"][s]
            out.append("### %s %s" % (s, title(s)))
            out.append("Changed: %s%s" % (", ".join(d["changed"]),
                                          (" · %d new comment(s)" % d["new_comments"]) if d.get("new_comments") else ""))
            for field, diff in (d.get("diffs") or {}).items():
                if diff:
                    out.append("")
                    out.append("```diff\n%s\n```" % diff)
            out.append("")
    if r["meta"]:
        out.append("## Status-only updates")
        for s in r["meta"]:
            vals = (r["details"][s].get("meta_values") or {})
            bits = ["%s: %s → %s" % (k, v[0], v[1]) for k, v in vals.items()]
            others = [k for k in r["details"][s]["meta_changed"] if k not in vals]
            bits.extend("%s changed" % k for k in others)
            out.append("- %s %s (%s)" % (s, title(s), "; ".join(bits)))
        out.append("")
    if r["removed"]:
        out.append("## Removed")
        out.extend("- %s" % s for s in r["removed"])
        out.append("")
    out.append("## Impact")
    out.append("")
    out.append("_Filled in by the agent: design sections and tasks that point at changed or removed ACs._")
    return "\n".join(out)


def _describe_source(src):
    bits = []
    if src.get("epic"):
        bits.append("epic %s" % src["epic"])
    if src.get("ids"):
        bits.append("stories %s" % ", ".join(src["ids"]))
    return " + ".join(bits) or "nothing"
