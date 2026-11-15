"""Merge a triage into what is stored, order the groups, and cut the fix batches.

One rule runs through all of it: comments that touch the same files are fixed together, in one
batch, so the second fix never undoes the first.
"""

import re

from .store import now

PRI = {"high": 0, "medium": 1, "low": 2}
VER = {"real": 0, "question": 1, "negotiable": 2, "false-positive": 3, "outdated": 4, "praise": 5}
NEEDS_DECISION = ("real", "false-positive", "negotiable", "question")
ITEM_KEYS = ["plain", "verdict", "priority", "group", "why", "evidence", "fix", "impact", "reply", "decision", "state",
             "hash", "commit"]
GROUP_KEYS = ["id", "title", "plain", "threads", "verdict", "priority", "fix", "impact", "files", "order", "with"]


def group_number(gid):
    m = re.search(r"\d+", str(gid or ""))
    return int(m.group(0)) if m else 0


def merge(store, items, groups):
    """Put checked items and groups into the stored triage. Returns {"first": [...], "again": [...], "kept": [...]}.

    A person's decision and a fixed or replied state stay when the thread did not change. When it
    did change, the item starts again as triaged and the old decision is kept as 'was'.
    """
    threads = store.by_id()
    seen = {"first": [], "again": [], "kept": []}
    for tid, new in items.items():
        old = store.items.get(tid)
        item = dict(new, decision=None, state="triaged", hash=threads[tid]["hash"], commit=None)
        if old and old.get("hash") == item["hash"]:
            item.update(decision=old.get("decision"), state=old.get("state") or "triaged", commit=old.get("commit"))
            if old.get("was"):
                item["was"] = old["was"]
            seen["kept"].append(tid)
        elif old:
            was = old.get("decision") or old.get("was")
            if was:
                item["was"] = was
            seen["again"].append(tid)
        else:
            seen["first"].append(tid)
        store.items[tid] = {k: item.get(k) for k in ITEM_KEYS + (["was"] if item.get("was") else [])}
    by_id = {g.get("id"): g for g in store.triage["groups"]}
    for g in groups:
        by_id[g["id"]] = dict(g)
    store.triage["groups"] = list(by_id.values())
    regroup(store)
    return seen


def regroup(store):
    """Fill in what the script owns in each group: threads, files, priority, order and with."""
    threads, items = store.by_id(), store.items
    order_of = {t["id"]: n for n, t in enumerate(store.threads["threads"])}
    members = {}
    for tid, it in items.items():
        if it.get("group"):
            members.setdefault(it["group"], []).append(tid)
    groups = []
    for g in store.triage["groups"]:
        ids = members.get(g.get("id"))
        if not ids:
            continue  # every comment moved out: the group goes away
        repos = {p.get("repo") for p in store.prs["prs"] if p.get("repo")}
        own = sorted({threads[tid]["repo"] for tid in ids if tid in threads and threads[tid].get("repo")})
        files = set()
        for f in g.get("files") or []:
            f = str(f).strip()
            while f.startswith("./"):
                f = f[2:]
            if f.split("/", 1)[0] not in repos and len(own) == 1:
                f = "%s/%s" % (own[0], f)  # the triager left out the repo: it is the group's own repo
            files.add(f)
        for tid in ids:
            t = threads.get(tid)
            if t and t.get("file"):
                files.add("%s/%s" % (t["repo"], t["file"]))
        ranks = [PRI.get(g.get("priority"), 2)] + [PRI.get(items[tid].get("priority"), 2) for tid in ids]
        g = dict(g, threads=sorted(ids, key=lambda tid: (order_of.get(tid, 10 ** 6), tid)), files=sorted(files),
                 priority=[p for p, n in PRI.items() if n == min(ranks)][0])
        groups.append(g)
    groups.sort(key=lambda g: (PRI.get(g.get("priority"), 9), VER.get(g.get("verdict"), 9), group_number(g["id"])))
    for n, g in enumerate(groups, 1):
        g["order"] = n
    for g in groups:
        g["with"] = sorted((o["id"] for o in groups if o is not g and set(o["files"]) & set(g["files"])), key=group_number)
    store.triage["groups"] = [{k: g.get(k) for k in GROUP_KEYS} for g in groups]


def reconcile(store, ours=()):
    """Bring the items in line with the threads after a fetch. Returns {"closed": [...], "replied": [...]}.

    A settled thread (resolved on the host, or its PR is merged or closed) closes its item. When the
    thread changed but the last word is yours, there is nothing new to explain: it counts as replied.
    """
    ours = {str(o).lower() for o in ours if o}
    threads = store.by_id()
    changed = {"closed": [], "replied": []}
    for tid, it in store.items.items():
        t = threads.get(tid)
        if t is None or t.get("resolved"):
            if it.get("state") != "closed":
                it["state"] = "closed"
                changed["closed"].append(tid)
            continue
        if it.get("state") == "closed":
            it["state"] = "fixed" if it.get("commit") else "triaged"
        if it.get("hash") != t.get("hash") and t.get("replies") and \
                str(t["replies"][-1].get("author") or "").lower() in ours:
            it["hash"] = t["hash"]
            if it.get("state") == "triaged":
                it["state"] = "replied"
            changed["replied"].append(tid)
    return changed


# --------------------------------------------------------------------------- counts


def counts(store):
    """The same numbers stage.comments_view() gives, from what is in memory."""
    prs, threads = store.prs["prs"], store.threads["threads"]
    live = [t for t in threads if not t.get("resolved")]
    out = {"prs": len(prs), "open": sum(1 for p in prs if p.get("state") == "open"),
           "merged": sum(1 for p in prs if p.get("state") == "merged"),
           "closed": sum(1 for p in prs if p.get("state") == "closed"),
           "threads": len(threads), "live": len(live), "new": 0, "undecided": 0, "to_fix": 0, "fixed": 0,
           "replied": 0, "by_verdict": {v: 0 for v in VER}, "groups": len(store.triage["groups"]),
           "watching": bool(store.prs["watch"].get("on"))}
    for t in live:
        it = store.current(t)
        if not it:
            out["new"] += 1
            continue
        if it.get("verdict") in out["by_verdict"]:
            out["by_verdict"][it["verdict"]] += 1
        if it.get("state") == "fixed":
            out["fixed"] += 1
        elif it.get("state") == "replied":
            out["replied"] += 1
        elif it.get("decision") == "fix":
            out["to_fix"] += 1
        elif not it.get("decision") and it.get("verdict") in NEEDS_DECISION:
            out["undecided"] += 1
    return out


# --------------------------------------------------------------------------- fix batches


def fixable(store, taken=()):
    """Threads a person chose to fix that are still open: not settled, not fixed, on an open PR."""
    out = []
    for t in store.threads["threads"]:
        it, pr = store.current(t), store.pr(t["pr"])
        if it and it.get("decision") == "fix" and it.get("state") in ("triaged", "fixing") and not t.get("resolved") \
                and pr and pr.get("state") == "open" and t["id"] not in taken:
            out.append(t["id"])
    return out


def _part(by_pr, pid):
    return by_pr.setdefault(pid, {"threads": [], "files": set(), "groups": []})


def make_batches(store, old=()):
    """(batches, warnings). Groups that share a file land in one batch per PR, most urgent first.

    old: the batches of the last plan. A fixed or committed batch stays as it is. A planned batch
    keeps its id when it still holds the same comments.
    """
    threads = store.by_id()
    keep = [b for b in old if b.get("state") in ("fixed", "committed")]
    taken = {tid for b in keep if b.get("state") == "committed" for tid in b.get("threads") or []}
    ids = set(fixable(store, taken))
    groups = [g for g in store.triage["groups"] if any(t in ids for t in g["threads"])]
    parent = {g["id"]: g["id"] for g in groups}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(groups):
        for b in groups[i + 1:]:
            if set(a["files"]) & set(b["files"]):
                parent[find(a["id"])] = find(b["id"])
    comps = {}
    for g in groups:
        comps.setdefault(find(g["id"]), []).append(g)

    made, warnings = [], []
    for gs in sorted(comps.values(), key=lambda gs: min(g["order"] for g in gs)):
        by_pr = {}
        for g in sorted(gs, key=lambda g: g["order"]):
            for tid in g["threads"]:
                if tid in ids:
                    p = _part(by_pr, threads[tid]["pr"])
                    p["threads"].append(tid)
                    if g["id"] not in p["groups"]:
                        p["groups"].append(g["id"])
        for g in sorted(gs, key=lambda g: g["order"]):
            for f in g["files"]:
                repo, _, path = f.partition("/")
                targets = [pid for pid in by_pr if store.pr(pid)["repo"] == repo]
                if not targets:
                    other = next((p for p in store.prs["prs"] if p.get("repo") == repo and p.get("state") == "open"), None)
                    if other is None:
                        warnings.append("%s names %s, but %s has no open PR here. A person decides how to change it."
                                        % (g["id"], f, repo))
                        continue
                    targets = [other["id"]]
                for pid in targets:
                    p = _part(by_pr, pid)
                    p["files"].add(path)
                    if g["id"] not in p["groups"]:
                        p["groups"].append(g["id"])
        for pid in sorted(by_pr, key=lambda pid: [p.get("id") for p in store.prs["prs"]].index(pid)):
            pr, p = store.pr(pid), by_pr[pid]
            made.append({"id": None, "pr": pid, "repo": pr["repo"], "branch": pr.get("head"), "groups": p["groups"],
                         "threads": p["threads"], "files": sorted(p["files"]), "state": "planned", "commit": None,
                         "made": now()})
    last = max([group_number(b.get("id")) for b in old] or [0])
    planned = [b for b in old if b.get("state") == "planned"]
    for b in made:
        same = next((o for o in planned if o.get("pr") == b["pr"] and set(o.get("threads") or []) == set(b["threads"])), None)
        if same:
            b["id"], b["made"] = same["id"], same.get("made") or b["made"]
            planned.remove(same)
        else:
            last += 1
            b["id"] = "B%d" % last
    return keep + made, warnings
