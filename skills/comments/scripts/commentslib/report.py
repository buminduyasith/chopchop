"""The files people and agents read: comments.md, pack.md, the fix briefs and the reply drafts.

Every file is Markdown, starts with a Summary and uses simple English. What a reviewer wrote is
shown as written, inside a code block, so their words are never changed.
"""

import json
import re

from chopchoplib import plain

from .store import now
from .triage import NEEDS_DECISION, counts

VERDICT_WORDS = {"real": "a real problem", "false-positive": "the reviewer is mistaken",
                 "negotiable": "fair, but not for this PR", "question": "a question", "praise": "praise",
                 "outdated": "out of date"}
DECISION_WORDS = {"fix": "fix it", "reply": "reply only", "skip": "skip it"}
STATE_WORDS = {"triaged": "explained, nothing done yet", "fixing": "being fixed", "fixed": "fixed",
               "replied": "answered", "closed": "settled"}
REVIEW_WORDS = {"approved": "approved", "changes-requested": "changes requested", "commented": "commented",
                "none": "no review yet"}
QUOTE = 200


def clean(text):
    """Host text for a heading, a list line or a table cell: one line, no long dashes, no table breaks."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return re.sub("[\u2013\u2014]", "-", text).replace("|", "/")


def fence(text, lang="text", exact=False):
    """A code block. Other people's words get their own ``` marks softened; exact=True keeps every character
    (for a reply someone will paste) and makes the fence longer instead."""
    text = str(text or "").replace("\r\n", "\n").rstrip()
    if not exact:
        return "```%s\n%s\n```" % (lang, text.replace("```", "'''"))
    ticks = "`" * max(3, max([len(m) for m in re.findall(r"`+", text)] or [0]) + 1)
    return "%s%s\n%s\n%s" % (ticks, lang, text, ticks)


def quote(text):
    """Other people's words for a person to read: a Markdown quote, not a grey text box."""
    text = re.sub("[\u2013\u2014]", "-", str(text or "").replace("\r\n", "\n").strip())
    text = text.replace("```", "'''")
    return "\n".join("> %s" % l if l.strip() else ">" for l in text.split("\n")) or "> (empty)"


def first_words(text, limit=80):
    """The start of a text on one line. Code fence marks go, so the line is safe inside Markdown."""
    flat = re.sub(r"\s+", " ", re.sub(r"`{3,}\w*", " ", str(text or ""))).strip()
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "..."


def where(thread):
    if thread.get("kind") == "inline" or thread.get("file"):
        return "%s%s" % (thread.get("file") or "?", ":%s" % thread["line"] if thread.get("line") else "")
    return "review summary" if thread.get("kind") == "review" else "PR comment"


def where_md(thread):
    """where(), with code marks around a file position."""
    return "`%s`" % where(thread) if thread.get("file") else where(thread)


def who(thread):
    return "%s%s" % (thread.get("author") or "someone", " (bot)" if thread.get("bot") else "")


def new_line(thread):
    """One line for a new comment: who, where, and how it starts."""
    return "%s · %s · %s · %s" % (thread["id"], who(thread), where(thread), first_words(thread.get("body")))


def call_words(item):
    if item.get("decision"):
        return DECISION_WORDS.get(item["decision"], item["decision"])
    if item.get("verdict") in NEEDS_DECISION:
        return "not decided yet" + (" (it was '%s' before the comment changed)" % item["was"] if item.get("was") else "")
    return "none needed"


def reply_text(item, thread=None):
    """The reply exactly as it would be posted: the draft, plus the commit when the fix is in.

    A reply to a review summary or a PR comment is a new PR comment, so it starts with a short quote
    of what it answers."""
    text = str(item.get("reply") or "").strip()
    if not text:
        return ""
    sha = str(item.get("commit") or "")
    if item.get("state") == "fixed" and sha and sha[:7] not in text:
        text += "\n\nFixed in %s." % sha[:10]
    if thread is not None and thread.get("kind") in ("review", "general"):
        text = "> %s\n\n%s" % (first_words(thread.get("body"), QUOTE), text)
    return text


def ready_to_post(store, thread):
    """True when a reply may go out: a person chose reply, or chose fix and the fix is in."""
    item = store.current(thread)
    if not item or not item.get("reply") or thread.get("resolved") or item.get("state") in ("replied", "closed"):
        return False
    return item.get("decision") == "reply" or (item.get("decision") == "fix" and item.get("state") == "fixed")


# --------------------------------------------------------------------------- comments.md


def render_report(store):
    c = counts(store)
    threads, items = store.by_id(), store.items
    verdicts = ", ".join("%d %s" % (n, v.replace("-", " ")) for v, n in c["by_verdict"].items() if n)
    done = [x for x in ("%d to fix" % c["to_fix"] if c["to_fix"] else "", "%d fixed" % c["fixed"] if c["fixed"] else "",
                        "%d answered" % c["replied"] if c["replied"] else "") if x]
    lines = ["# Review comments · %s" % clean(store.title), "",
             plain.summary_block([
                 ("What", "%d open review comment(s) on %d PR(s), in %d group(s)%s."
                  % (c["live"], c["prs"], c["groups"], ": %s" % verdicts if verdicts else "")),
                 ("Needs your call", "%d comment(s). Say fix, reply or skip for each." % c["undecided"]
                  if c["undecided"] else "nothing right now."),
                 ("Work", ", ".join(done) + "." if done else None),
                 ("Not explained yet", "%d new comment(s)." % c["new"] if c["new"] else None),
                 ("Updated", now())]),
             "## Pull requests", "", "| PR | State | Review | Comments | Link |", "| --- | --- | --- | --- | --- |"]
    for p in store.prs["prs"]:
        lines.append("| %s %s | %s%s | %s | %s | %s |" % (
            p.get("id"), clean(p.get("title") or ""), p.get("state") or "?", ", draft" if p.get("draft") else "",
            REVIEW_WORDS.get(p.get("review"), "?"), p.get("threads") or 0, p.get("url") or ""))
    if not store.prs["prs"]:
        lines.append("| none yet | | | | |")
    lines += ["", "## Groups", ""]
    if not store.triage["groups"]:
        lines += ["No comment is explained yet.", ""]
    for g in store.triage["groups"]:
        mine = [(tid, items[tid]) for tid in g["threads"] if tid in items]
        calls = {}
        for _, it in mine:
            calls[call_words(it)] = calls.get(call_words(it), 0) + 1
        lines += ["### %s · %s" % (g["id"], clean(g.get("title"))), "",
                  "- **Verdict:** %s" % VERDICT_WORDS.get(g.get("verdict"), g.get("verdict")),
                  "- **Priority:** %s" % g.get("priority"),
                  "- **In plain words:** %s" % (g.get("plain") or "-")]
        if g.get("fix"):
            lines.append("- **Our fix:** %s" % g["fix"])
        if g.get("impact"):
            lines.append("- **What the fix touches:** %s" % g["impact"])
        if g.get("files"):
            lines.append("- **Files:** %s" % ", ".join("`%s`" % f for f in g["files"]))
        if g.get("with"):
            lines.append("- **Shares a file with:** %s. What gets fixed there goes in one fix, so no fix undoes another."
                         % ", ".join(g["with"]))
        lines += ["- **Your call:** %s" % ", ".join("%s (%d)" % kv for kv in sorted(calls.items())), ""]
        for tid, it in mine:
            lines += comment_block(threads.get(tid), tid, it)
    fresh = store.new_threads()
    lines += ["## Not explained yet", ""]
    lines += ["- %s" % clean(new_line(t)) for t in fresh] or ["Every open comment is explained."]
    settled = sum(1 for t in store.threads["threads"] if t.get("resolved"))
    if settled:
        lines += ["", "%d more comment(s) are settled: resolved, or on a PR that is merged or closed." % settled]
    return "\n".join(lines) + "\n"


def comment_block(thread, tid, item):
    if thread is None:
        return ["#### %s" % tid, "", "This comment is gone from the PR.", ""]
    link = " · [open](%s)" % thread["url"] if thread.get("url") else ""
    lines = ["#### %s · %s · %s%s" % (tid, clean(who(thread)), where_md(thread), link), "", quote(thread.get("body"))]
    for r in thread.get("replies") or []:
        lines += ["", "Reply from %s:" % clean(r.get("author")), "", quote(r.get("body"))]
    lines += ["", "- **In plain words:** %s" % item.get("plain"),
              "- **Verdict:** %s, %s priority" % (VERDICT_WORDS.get(item.get("verdict"), item.get("verdict")),
                                                  item.get("priority")),
              "- **Why we think so:** %s" % item.get("why")]
    if item.get("evidence"):
        lines.append("- **Evidence:** %s" % ", ".join("`%s`" % e for e in item["evidence"]))
    if item.get("fix"):
        lines.append("- **Our fix:** %s" % item["fix"])
    if item.get("impact"):
        lines.append("- **What the fix touches:** %s" % item["impact"])
    lines.append("- **Your call:** %s" % call_words(item))
    state = STATE_WORDS.get(item.get("state"), item.get("state"))
    if item.get("hash") != thread.get("hash"):
        state = "the comment changed after this was written. It will be explained again."
    lines.append("- **State:** %s%s" % (state, " (commit `%s`)" % item["commit"] if item.get("commit") else ""))
    reply = reply_text(item, thread)
    if reply:
        lines += ["- **Reply draft:**", ""] + ["  > %s" % l if l.strip() else "  >" for l in reply.split("\n")]
    return lines + [""]


# --------------------------------------------------------------------------- pack.md


TRIAGE_EXAMPLE = {
    "items": {"<thread id>": {
        "plain": "What the reviewer says, in one or two short sentences.", "verdict": "real", "priority": "high",
        "group": "G1", "why": "Why you think so, with the code you read.", "evidence": ["repo/path/file.js:42"],
        "fix": "What we would change.", "impact": "What else the fix touches, and the risk.",
        "reply": "The reply we would post."}},
    "groups": [{"id": "G1", "title": "A short name for the root cause", "plain": "What these comments have in common.",
                "threads": ["<thread id>"], "verdict": "real", "priority": "high", "fix": "The one fix for all of them.",
                "impact": "What the fix touches.", "files": ["repo/path/of/a/file/the/fix/changes"]}]}


def render_pack(store, entries, out_file, repos):
    """entries: one dict per thread to explain, made by the script (thread, code, tasks, rules, similar)."""
    prs = sorted({e["thread"]["pr"] for e in entries})
    groups = store.triage["groups"]
    next_group = max([int(re.sub(r"\D", "", g["id"]) or 0) for g in groups] or [0]) + 1
    lines = ["# Triage pack · %s" % clean(store.title), "",
             plain.summary_block([
                 ("What", "%d review comment(s) on %d PR(s) to explain." % (len(entries), len(prs))),
                 ("Write", "your answer as JSON, to the file named under Your answer."),
                 ("How", "read the code for each comment and give a verdict with evidence. Then group the comments "
                         "that have the same root cause.")]),
             "## Your answer", "", "Write this JSON to `%s`:" % out_file, "",
             fence(json.dumps(TRIAGE_EXAMPLE, indent=2), "json"), "",
             "- One item for every thread id below. Every item names its group.",
             "- A group lists the thread ids you put in it. To add a comment to an existing group, use its id.",
             "- New groups start at G%d." % next_group,
             "- `files` is for files the fix changes that no comment in the group sits on. Leave it out when there are none.",
             "", "## Pull requests", ""]
    for pid in prs:
        p = store.pr(pid) or {}
        lines.append("- %s · %s · `%s` into `%s` · %s · %s" % (
            pid, p.get("state") or "?", p.get("head") or "?", p.get("base") or "?", p.get("url") or "",
            repos.get(pid) or "no local checkout"))
    lines += ["", "## Existing groups", ""]
    if not groups:
        lines.append("None yet.")
    for g in groups:
        lines.append("- %s · %s · %s · %s · threads: %s · files: %s" % (
            g["id"], g.get("verdict"), g.get("priority"), clean(g.get("title")), ", ".join(g["threads"]),
            ", ".join("`%s`" % f for f in g.get("files") or []) or "none"))
    lines += ["", "## Comments to explain", ""]
    for e in entries:
        t = e["thread"]
        lines += ["### %s" % t["id"], "",
                  "- PR: %s · by %s · at %s%s" % (t["pr"], clean(who(t)), where_md(t), " · %s" % t["url"] if t.get("url") else "")]
        flags = [f for f, on in (("the diff under it changed since (outdated)", t.get("outdated")),
                                 ("settled on the host", t.get("resolved")),
                                 ("explained before, but the comment changed", e.get("again"))) if on]
        if flags:
            lines.append("- Note: %s." % "; ".join(flags))
        lines.append("- Tasks that cover this file: %s" % (", ".join(
            "%s %s (`%s`)" % (x["id"], clean(x["title"]), x["file"]) for x in e["tasks"]) or "none found"))
        lines.append("- Spec rules that may apply: %s" % ("; ".join(
            "%s \"%s\"" % (r["id"], clean(r["text"])) for r in e["rules"]) or "none found"))
        if e["similar"]:
            lines.append("- Possibly similar:")
            lines += ["  - %s (%s)%s" % (s["id"], "; ".join(s["why"]), " · %s" % s["note"] if s.get("note") else "")
                      for s in e["similar"]]
        else:
            lines.append("- Possibly similar: none found by the word check. Still compare it with the others.")
        lines += ["", "The comment:", "", fence(t.get("body"))]
        for r in t.get("replies") or []:
            lines += ["", "Reply from %s:" % clean(r.get("author")), "", fence(r.get("body"))]
        if t.get("hunk"):
            lines += ["", "The diff it was written on:", "", fence(t["hunk"], "diff")]
        if e.get("code"):
            lines += ["", "The code now (%s):" % e["code_note"], "", fence(e["code"])]
        elif t.get("file"):
            lines += ["", e["code_note"]]
        lines.append("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- fix briefs


def render_brief(store, batch, info):
    """info: repo_path, report, check (list of commands), style, guidelines, guides, profile, tasks, others (batches)."""
    threads, items = store.by_id(), store.items
    groups = [g for g in store.triage["groups"] if g["id"] in batch["groups"]]
    example = {"batch": batch["id"], "ok": True, "blocked": None, "files": ["path/of/each/file/you/changed"],
               "tests": ["the_test_names_you_wrote_or_changed"], "notes": "1 to 3 lines: what you changed and where.",
               "commit": "<one subject line in this repo's commit style>"}
    lines = ["# Fix review comments · %s · %s" % (batch["id"], batch["repo"]), "",
             plain.summary_block([
                 ("What", "fix %d review comment(s) from %s in %s." % (len(batch["threads"]), ", ".join(batch["groups"]),
                                                                      batch["repo"])),
                 ("Where", "repo %s, on branch `%s`." % (batch["repo"], batch["branch"])),
                 ("Rule", "never commit. chopchop commits after the checks and a review.")]),
             "There is no task file for this job. This brief is the task.", "",
             "- Repo: %s at `%s`, on branch `%s`. It is checked out. Stay on it." % (batch["repo"], info["repo_path"],
                                                                                   batch["branch"]),
             "- Files you may touch: %s, and the tests of those files." % (
                 ", ".join("`%s`" % f for f in batch["files"]) or "not listed: keep the change small")]
    lines += ["- Style file (follow it first): `%s`" % s for s in info["style"]] or [
        "- Style: no style file. Follow the code next to yours."]
    if info.get("guidelines"):
        lines.append("- Team guidelines for every repo (follow them; the style file wins if they disagree): `%s`" % info["guidelines"])
    lines += ["- Guide: `%s`" % g for g in info["guides"]]
    if info.get("profile"):
        lines.append("- Profile (commands and rules): `%s`" % info["profile"])
    lines += ["- Task file to read for the contract and the names: `%s`" % t["file"] for t in info["tasks"]]
    if info["check"]:
        lines.append("- Check: run %s in the repo. All must pass." % ", then ".join("`%s`" % c for c in info["check"]))
    else:
        lines.append("- Check: chopchop does not know this repo's test command. Find it in the README or the CI file "
                     "and run it.")
    lines += ["", "## What to change", ""]
    for g in groups:
        lines += ["### %s · %s" % (g["id"], clean(g.get("title"))), "",
                  "- What the reviewers say: %s" % g.get("plain"),
                  "- The fix: %s" % (g.get("fix") or "see the comments below"),
                  "- What it touches: %s" % (g.get("impact") or "only these lines"), ""]
        for tid in g["threads"]:
            t, it = threads.get(tid), items.get(tid)
            if t is None or it is None or tid not in batch["threads"]:
                continue
            lines += ["%s, by %s at %s:" % (tid, clean(who(t)), where_md(t)), "", fence(t.get("body"))]
            for r in t.get("replies") or []:
                lines += ["", "Reply from %s:" % clean(r.get("author")), "", fence(r.get("body"))]
            lines += ["", "- In plain words: %s" % it.get("plain"), "- The fix for this one: %s" % (it.get("fix") or g.get("fix"))]
            if it.get("evidence"):
                lines.append("- Code to read first: %s" % ", ".join("`%s`" % e for e in it["evidence"]))
            lines.append("")
        elsewhere = [tid for tid in g["threads"] if tid not in batch["threads"]]
        if elsewhere:
            lines += ["Other comments of this group are not yours to fix here: %s." % ", ".join(elsewhere), ""]
    if info["others"]:
        lines += ["## Other parts of the same fix", ""]
        lines += ["- %s changes %s for %s. Do not touch that repo." % (o["id"], o["repo"], ", ".join(o["groups"]))
                  for o in info["others"]]
        lines.append("")
    lines += ["## Rules", "",
              "- Fix only what is listed here. No other clean-up.",
              "- Add or change a unit test for each fix when the repo has tests.",
              "- Never commit, push, stash, reset, switch branches or stage files. chopchop commits after a review.",
              "- If a fix cannot be made as written, do not invent another plan. Set `blocked` to one line that says why.",
              "", "## When you finish", "", "Write `%s`:" % info["report"], "", fence(json.dumps(example, indent=2), "json"), "",
              "`blocked` is null, or one line on why the fix cannot be made as written. Then stop."]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- replies


def reply_rows(store, only=None):
    """Every reply draft that is not posted yet: [{"id", "ready", "why_not", "text", ...}]."""
    rows = []
    for t in store.threads["threads"]:
        item = store.current(t)
        if not item or (only is not None and t["id"] not in only):
            continue
        text = reply_text(item, t)
        if not text or item.get("state") in ("replied", "closed") or t.get("resolved"):
            continue
        if item.get("decision") == "skip" and only is None:
            continue
        ready = ready_to_post(store, t)
        why_not = None
        if not ready:
            why_not = {"fix": "after the fix is in", "skip": "you chose skip"}.get(
                item.get("decision"), "not decided yet")
        rows.append({"id": t["id"], "pr": t["pr"], "author": who(t), "where": where(t), "where_md": where_md(t),
                     "url": t.get("url"),
                     "group": item.get("group"), "verdict": item.get("verdict"), "decision": item.get("decision"),
                     "ready": ready, "why_not": why_not, "text": text, "kind": t.get("kind")})
    return rows


def render_replies(store, rows):
    ready = [r for r in rows if r["ready"]]
    lines = ["# Reply drafts · %s" % clean(store.title), "",
             plain.summary_block([
                 ("What", "%d reply draft(s), %d ready to post." % (len(rows), len(ready))),
                 ("Rule", "these are drafts. Nothing is posted until you say yes."),
                 ("Updated", now())])]
    for title, part in (("Ready to post", ready), ("Not ready yet", [r for r in rows if not r["ready"]])):
        if not part:
            continue
        lines += ["## %s" % title, ""]
        for r in part:
            lines += ["### %s" % r["id"], "",
                      "- To: %s at %s%s" % (clean(r["author"]), r["where_md"], " · [open](%s)" % r["url"] if r["url"] else ""),
                      "- Group %s · %s%s" % (r["group"], VERDICT_WORDS.get(r["verdict"], r["verdict"]),
                                           " · waits: %s" % r["why_not"] if r["why_not"] else ""),
                      "", fence(r["text"], exact=True), ""]
    if not rows:
        lines += ["No reply is waiting.", ""]
    return "\n".join(lines) + "\n"
