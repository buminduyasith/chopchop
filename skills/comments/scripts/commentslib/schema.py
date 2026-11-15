"""Check a file that comes in: an ingest file from another host, or the triager's answer.

Both checks collect every problem and say each one in a plain line, so one run shows all of them.
"""

import re

from chopchoplib import plain

from .store import KINDS, PR_STATES, REVIEWS, UsageError, local_time, parse_pr_url, pick_repo_name, new_pr

VERDICTS = ["real", "false-positive", "negotiable", "question", "praise", "outdated"]
PRIORITIES = ["high", "medium", "low"]
DECISIONS = ["fix", "reply", "skip"]
STATES = ["triaged", "fixing", "fixed", "replied", "closed"]
GROUP_ID = re.compile(r"^G[1-9]\d*$")
CITE = re.compile(r"^[^\s:]+(/[^\s:]+)*:\d+(-\d+)?$")

PR_IN = {"id", "repo", "host", "slug", "number", "url", "title", "state", "draft", "head", "base", "author", "review",
         "fetched", "threads"}
THREAD_IN = {"id", "pr", "repo", "kind", "file", "line", "hunk", "author", "bot", "created", "updated", "resolved",
             "outdated", "url", "body", "replies", "hash"}
REPLY_IN = {"author", "body", "created"}
ALIASES = {"path": "file", "filename": "file", "text": "body", "comment": "body", "user": "author", "login": "author",
           "comments": "replies", "isResolved": "resolved", "isOutdated": "outdated", "diffHunk": "hunk",
           "createdAt": "created", "updatedAt": "updated", "pull": "pr", "link": "url", "type": "kind"}


def _unknown(keys, allowed, where, errors):
    for k in sorted(set(keys) - allowed):
        hint = ALIASES.get(k)
        errors.append("%s: unknown field '%s'%s." % (where, k, ". Use '%s'" % hint if hint in allowed else ""))


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _flag(obj, key, where, errors):
    value = obj.get(key, False)
    if value is None:
        return False
    if not isinstance(value, bool):
        errors.append("%s: '%s' must be true or false." % (where, key))
        return False
    return value


# --------------------------------------------------------------------------- ingest


def check_ingest(data, repo_names=()):
    """Returns (prs, threads, me, errors). prs are prs.json entries, threads are threads.json entries without hash."""
    errors = []
    if not isinstance(data, dict):
        return [], [], None, ['The file must be a JSON object: {"prs": [...], "threads": [...]}.']
    _unknown(data.keys(), {"prs", "threads", "me", "fetched"}, "top level", errors)
    raw_prs, raw_threads = data.get("prs"), data.get("threads")
    if not isinstance(raw_prs, list) or not raw_prs:
        errors.append("'prs' must be a list with at least one pull request.")
        raw_prs = []
    if not isinstance(raw_threads, list):
        errors.append("'threads' must be a list (it may be empty).")
        raw_threads = []
    me = data.get("me")
    if me is not None and not _text(me):
        errors.append("'me' must be your login on the host, or left out.")

    prs, by_id = [], {}
    for n, p in enumerate(raw_prs, 1):
        where = "pr %d" % n
        if not isinstance(p, dict):
            errors.append("%s: must be an object." % where)
            continue
        _unknown(p.keys(), PR_IN, where, errors)
        try:
            parsed = parse_pr_url(p.get("url"))
        except UsageError as e:
            errors.append("%s: 'url' is needed. %s" % (where, e))
            continue
        entry = new_pr(parsed, _text(p.get("repo")) or pick_repo_name(parsed, repo_names))
        where = "pr %d (%s)" % (n, entry["id"])
        if p.get("id") not in (None, entry["id"]):
            errors.append("%s: 'id' is %s but repo and number give %s. Leave 'id' out." % (where, p.get("id"), entry["id"]))
        if p.get("number") not in (None, entry["number"]):
            errors.append("%s: 'number' is %s but the link says %d." % (where, p.get("number"), entry["number"]))
        if p.get("state") not in PR_STATES:
            errors.append("%s: 'state' must be one of %s (got %r)." % (where, ", ".join(PR_STATES), p.get("state")))
        if p.get("review", "none") not in REVIEWS:
            errors.append("%s: 'review' must be one of %s (got %r)." % (where, ", ".join(REVIEWS), p.get("review")))
        for key in ("title", "head", "base", "author"):
            if p.get(key) is not None and not isinstance(p.get(key), str):
                errors.append("%s: '%s' must be text." % (where, key))
        if _text(p.get("host")):
            entry["host"] = _text(p["host"]).lower()
        entry.update(title=p.get("title"), state=p.get("state"), draft=_flag(p, "draft", where, errors),
                     head=p.get("head"), base=p.get("base"), author=p.get("author"), review=p.get("review", "none"))
        if entry["id"] in by_id:
            errors.append("%s: the same pull request is listed twice." % where)
        by_id[entry["id"]] = entry
        prs.append(entry)

    threads, seen = [], set()
    for n, t in enumerate(raw_threads, 1):
        where = "thread %d" % n
        if not isinstance(t, dict):
            errors.append("%s: must be an object." % where)
            continue
        tid = _text(t.get("id"))
        where = "thread %d (%s)" % (n, tid) if tid else where
        _unknown(t.keys(), THREAD_IN, where, errors)
        pr = by_id.get(t.get("pr"))
        if pr is None:
            errors.append("%s: 'pr' must be the id of a pull request in this file (%s), got %r."
                          % (where, ", ".join(by_id) or "none", t.get("pr")))
        elif not tid.startswith(pr["id"] + ":") or len(tid) <= len(pr["id"]) + 1:
            errors.append("%s: 'id' must start with the PR id, like %s:r2001." % (where, pr["id"]))
        if not tid:
            errors.append("%s: 'id' is needed." % where)
        elif tid in seen:
            errors.append("%s: this id is used twice." % where)
        seen.add(tid)
        kind = t.get("kind")
        if kind not in KINDS:
            errors.append("%s: 'kind' must be one of %s (got %r)." % (where, ", ".join(KINDS), kind))
        if not _text(t.get("author")):
            errors.append("%s: 'author' is needed (the login of who wrote it)." % where)
        if not _text(t.get("body")):
            errors.append("%s: 'body' is needed (the comment text, as written)." % where)
        file, line = t.get("file"), t.get("line")
        if kind == "inline" and not _text(file):
            errors.append("%s: an inline comment needs 'file' (the path in the repo)." % where)
        if file is not None and not isinstance(file, str):
            errors.append("%s: 'file' must be text or null." % where)
        if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
            errors.append("%s: 'line' must be a whole number from 1, or null." % where)
        for key in ("hunk", "url", "created", "updated"):
            if t.get(key) is not None and not isinstance(t.get(key), str):
                errors.append("%s: '%s' must be text or null." % (where, key))
        if not _text(t.get("created")):
            errors.append("%s: 'created' is needed (when it was written, like 2026-11-14T09:00:00Z)." % where)
        replies = t.get("replies", [])
        if replies is None:
            replies = []
        if not isinstance(replies, list):
            errors.append("%s: 'replies' must be a list." % where)
            replies = []
        clean = []
        for k, r in enumerate(replies, 1):
            rw = "%s reply %d" % (where, k)
            if not isinstance(r, dict):
                errors.append("%s: must be an object with author, body and created." % rw)
                continue
            _unknown(r.keys(), REPLY_IN, rw, errors)
            if not _text(r.get("author")) or not _text(r.get("body")):
                errors.append("%s: 'author' and 'body' are needed." % rw)
            clean.append({"author": _text(r.get("author")), "body": r.get("body") if isinstance(r.get("body"), str) else "",
                          "created": local_time(r.get("created"))})
        created = local_time(t.get("created"))
        threads.append({
            "id": tid, "pr": t.get("pr"), "repo": pr["repo"] if pr else None, "kind": kind,
            "file": _text(file) or None, "line": line if isinstance(line, int) and not isinstance(line, bool) else None,
            "hunk": t.get("hunk") or None, "author": _text(t.get("author")), "bot": _flag(t, "bot", where, errors),
            "created": created, "updated": local_time(t.get("updated")) or created,
            "resolved": _flag(t, "resolved", where, errors), "outdated": _flag(t, "outdated", where, errors),
            "url": t.get("url") or None, "body": t.get("body") if isinstance(t.get("body"), str) else "", "replies": clean})
    return prs, threads, _text(me) or None, errors


# --------------------------------------------------------------------------- triage


def _lint(label, text, warnings):
    if not text:
        return
    errors, warns = plain.lint_text(text)
    for w in errors + warns:
        w = re.sub(r"^line \d+ ", "", w)
        warnings.append("%s: %s" % (label, w))


def check_triage(data, threads, stored):
    """Check the triager's answer against the threads and what is stored.

    Returns (items, groups, errors, warnings). items: {thread id: fields}. groups: the groups the file writes.
    """
    errors, warnings = [], []
    if not isinstance(data, dict):
        return {}, [], ['The file must be a JSON object: {"items": {...}, "groups": [...]}.'], []
    _unknown(data.keys(), {"items", "groups", "updated"}, "top level", errors)
    raw_items, raw_groups = data.get("items"), data.get("groups", [])
    if not isinstance(raw_items, dict):
        errors.append("'items' must be an object: one entry per thread id.")
        raw_items = {}
    if not isinstance(raw_groups, list):
        errors.append("'groups' must be a list.")
        raw_groups = []
    old_items = stored.get("items") or {}
    old_groups = {g.get("id"): g for g in stored.get("groups") or []}

    groups, group_ids = [], {}
    for n, g in enumerate(raw_groups, 1):
        if not isinstance(g, dict):
            errors.append("group %d: must be an object." % n)
            continue
        gid = g.get("id")
        where = "group %s" % gid if isinstance(gid, str) and gid else "group %d" % n
        _unknown(g.keys(), {"id", "title", "plain", "threads", "verdict", "priority", "fix", "impact", "files", "order",
                            "with"}, where, errors)
        if not isinstance(gid, str) or not GROUP_ID.match(gid):
            errors.append("%s: 'id' must look like G1, G2, G3 (got %r)." % (where, gid))
            continue
        if gid in group_ids:
            errors.append("%s: this id is used twice." % where)
            continue
        for key in ("title", "plain"):
            if not _text(g.get(key)):
                errors.append("%s: '%s' is needed." % (where, key))
        if g.get("verdict") not in VERDICTS:
            errors.append("%s: 'verdict' must be one of %s (got %r)." % (where, ", ".join(VERDICTS), g.get("verdict")))
        if g.get("priority") not in PRIORITIES:
            errors.append("%s: 'priority' must be one of %s (got %r)." % (where, ", ".join(PRIORITIES), g.get("priority")))
        if g.get("verdict") == "real":
            for key in ("fix", "impact"):
                if not _text(g.get(key)):
                    errors.append("%s: a real problem needs '%s'." % (where, key))
        ids = g.get("threads")
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            errors.append("%s: 'threads' must be a list of thread ids." % where)
            ids = []
        files = g.get("files") or []
        if not isinstance(files, list) or not all(isinstance(x, str) and "/" in x for x in files):
            errors.append("%s: 'files' must be a list like [\"repo/path/to/file\"], or left out." % where)
            files = []
        clean = {"id": gid, "title": _text(g.get("title")), "plain": _text(g.get("plain")), "threads": list(ids),
                 "verdict": g.get("verdict"), "priority": g.get("priority"), "fix": _text(g.get("fix")) or None,
                 "impact": _text(g.get("impact")) or None, "files": [re.sub(r"^\./", "", f.strip()) for f in files]}
        for key in ("title", "plain", "fix", "impact"):
            _lint("%s %s" % (gid, key), clean[key], warnings)
        group_ids[gid] = clean
        groups.append(clean)

    items = {}
    for tid, it in raw_items.items():
        where = "item %s" % tid
        if tid not in threads:
            errors.append("%s: there is no thread with this id. Copy the ids from the pack." % where)
            continue
        if not isinstance(it, dict):
            errors.append("%s: must be an object." % where)
            continue
        _unknown(it.keys(), {"plain", "verdict", "priority", "group", "why", "evidence", "fix", "impact", "reply",
                             "decision", "state", "hash", "commit", "was"}, where, errors)
        verdict, priority, gid = it.get("verdict"), it.get("priority"), it.get("group")
        if verdict not in VERDICTS:
            errors.append("%s: 'verdict' must be one of %s (got %r)." % (where, ", ".join(VERDICTS), verdict))
        if priority not in PRIORITIES:
            errors.append("%s: 'priority' must be one of %s (got %r)." % (where, ", ".join(PRIORITIES), priority))
        for key in ("plain", "why"):
            if not _text(it.get(key)):
                errors.append("%s: '%s' is needed." % (where, key))
        evidence = it.get("evidence", [])
        if evidence is None:
            evidence = []
        if not isinstance(evidence, list) or not all(isinstance(x, str) and x.strip() for x in evidence):
            errors.append("%s: 'evidence' must be a list like [\"repo/path/file.js:42\"]." % where)
            evidence = []
        if verdict in ("real", "false-positive") and not evidence:
            errors.append("%s: a %s verdict needs 'evidence': the code you read, as repo/path:line." % (where, verdict))
        for cite in evidence:
            if not CITE.match(cite.strip()):
                warnings.append("%s evidence: '%s' should look like repo/path/file:line" % (tid, cite.strip()))
        if verdict == "real":
            for key in ("fix", "impact"):
                if not _text(it.get(key)):
                    errors.append("%s: a real problem needs '%s'." % (where, key))
        if verdict not in ("praise", "outdated") and not _text(it.get("reply")):
            errors.append("%s: 'reply' is needed: the answer we would post." % where)
        if not isinstance(gid, str) or not GROUP_ID.match(gid):
            errors.append("%s: 'group' must be a group id like G1 (got %r). Every thread is in one group." % (where, gid))
        elif gid in group_ids:
            if tid not in group_ids[gid]["threads"]:
                errors.append("%s: it says group %s, but %s does not list it in 'threads'." % (where, gid, gid))
        elif gid not in old_groups:
            errors.append("%s: group %s is not in 'groups' and is not an existing group." % (where, gid))
        clean = {"plain": _text(it.get("plain")), "verdict": verdict, "priority": priority, "group": gid,
                 "why": _text(it.get("why")), "evidence": [c.strip() for c in evidence],
                 "fix": _text(it.get("fix")) or None, "impact": _text(it.get("impact")) or None,
                 "reply": _text(it.get("reply")) or None}
        for key in ("plain", "why", "fix", "impact", "reply"):
            _lint("%s %s" % (tid, key), clean[key], warnings)
        items[tid] = clean

    listed = {}
    for g in groups:
        for tid in g["threads"]:
            if tid in listed:
                errors.append("thread %s is in two groups (%s and %s). A thread is in exactly one." % (tid, listed[tid], g["id"]))
                continue
            listed[tid] = g["id"]
            if tid in items:
                if items[tid]["group"] != g["id"] and isinstance(items[tid]["group"], str):
                    errors.append("thread %s is listed in %s, but its item says %s." % (tid, g["id"], items[tid]["group"]))
            elif tid in old_items:
                if old_items[tid].get("group") != g["id"]:
                    errors.append("thread %s is already in %s. To move it to %s, write its item again."
                                  % (tid, old_items[tid].get("group"), g["id"]))
            elif tid in threads:
                errors.append("thread %s is listed in %s but has no item. Every thread needs an item." % (tid, g["id"]))
            else:
                errors.append("group %s lists %s, which is not a thread id." % (g["id"], tid))
        if g["id"] not in old_groups and not g["threads"]:
            errors.append("group %s has no threads." % g["id"])
    if not items and not errors:
        errors.append("The file has no items. Write one item per thread in the pack.")
    seen, short = set(), []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            short.append(w)
    return items, groups, errors, short
