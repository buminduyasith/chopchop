"""The two design diagrams: the high-level design and the main flow.

One JSON source each, two outputs: a static SVG for feature.html (drawn here, no browser and no
library), and Mermaid for design.md, so GitHub and editors still show it.

design/architecture.json  the high-level design: parts, the repo each lives in, what talks to what.

  {"version": 2, "title": "Refunds for card payments",
   "nodes": [{"id": "customer", "name": "Customer", "kind": "person", "row": 1, "col": 0},
             {"id": "api", "name": "Refund API", "kind": "api", "repo": "payments-api",
              "status": "new", "note": "POST /refunds", "row": 1, "col": 2}],
   "links": [{"from": "page", "to": "api", "label": "POST refunds", "kind": "call"}]}

design/flow.json  the main flow in time order, with a failure answer for every message.

  {"version": 2, "title": "Request a refund",
   "participants": ["customer", "page", "api", "db"],
   "messages": [{"n": 1, "from": "customer", "to": "page", "kind": "person", "say": "clicks Refund",
                 "line": "The customer clicks Refund.", "stories": ["PAY-121"],
                 "failure": {"twice": "...", "caller": "..."}},
                {"n": 4, "from": "api", "to": "page", "kind": "reply", "say": "422 window closed",
                 "line": "...", "if": "older than 30 days"}],
   "out_of_scope": []}

Placement follows archify's rule: the author places parts on a grid (row, col) by their
connections. The router draws right-angled lines through the gaps and never moves a part.
A line that cannot avoid a part, two parts in one cell, or a part inside another repo's group
is an error with a fix.
"""

import html
import re

# --------------------------------------------------------------------------- vocabulary

NODE_KINDS = ["person", "ui", "api", "service", "job", "table", "topic", "library", "external"]
STATUSES = ["new", "changed", "same", "external"]
LINK_KINDS = ["call", "event", "data", "external"]
MSG_KINDS = {
    "person": ["twice", "caller"],
    "call": ["fails", "slow", "twice", "caller"],
    "db": ["fails", "twice"],
    "event": ["fails", "twice"],
    "external": ["fails", "slow", "twice", "caller"],
    "message": ["fails"],
    "reply": [],
}
KIND_NAMES = {"person": "person to screen", "call": "call between parts", "db": "database write", "event": "event",
              "external": "outside system", "message": "message to a person", "reply": "reply"}
QUESTIONS = {
    "fails": "Fails: what does the user see, and what state is left behind?",
    "slow": "Slow: what is the timeout, and what happens after it?",
    "twice": "Runs twice: a double click, a retry, an event sent again. Is the result still right?",
    "caller": "Wrong caller: who may do this, and where is it checked?",
}
ANSWER_KEYS = ["fails", "slow", "twice", "caller"]
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
STEP_RE = re.compile(r"^\s*(step\s*)?\d+\s*[.):-]", re.I)
MAX_NODES = 14
MAX_COLS = 5
MAX_PARTICIPANTS = 8
MAX_WIDTH = 1240

COLOR = {
    "new": ("#e9f7ef", "#1d6a51"), "changed": ("#fff4e2", "#b26100"), "same": ("#ffffff", "#94a3b8"),
    "external": ("#f8fafc", "#64748b"), "person": ("#eef4ff", "#3b6fe0"),
}
CHIP = {"new": ("NEW", "#1d6a51"), "changed": ("CHANGED", "#9a4b00"), "external": ("OUTSIDE", "#475569")}
INK, MUTED, LINE, BLUE, NAVY, RED, AMBER = "#0b1220", "#556072", "#475569", "#1d4ed8", "#1e3a8a", "#b42318", "#b26100"
FONT = "Inter, Segoe UI, system-ui, -apple-system, sans-serif"
ICONS = {
    "ui": "M3 5h18v14H3zM3 9h18", "api": "M8 7l-5 5 5 5M16 7l5 5-5 5",
    "service": "M4 7l8-4 8 4v10l-8 4-8-4zM4 7l8 4 8-4M12 11v10",
    "job": "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18zM12 7v5l3 3",
    "table": "M4 6c0-2 16-2 16 0v12c0 2-16 2-16 0zM4 6c0 2 16 2 16 0M4 12c0 2 16 2 16 0",
    "topic": "M3 8h18M3 16h18M7 4l-4 4 4 4M17 12l4 4-4 4", "library": "M5 4h10l4 4v12H5zM15 4v4h4",
    "external": "M7 18a5 5 0 0 1-.6-10A6 6 0 0 1 18 8.5a4.5 4.5 0 0 1-1 9.5z",
    "person": "M12 4a4 4 0 1 0 0 8a4 4 0 1 0 0-8zM4 21c1-4 4.5-6 8-6s7 2 8 6",
}


def esc(s):
    return html.escape(str(s), quote=True)


def text_w(s, size):
    """Rough width of Inter text: wide letters count more."""
    w = 0.0
    for ch in str(s):
        if ch in "mwMW@":
            w += 0.86
        elif ch.isupper() or ch.isdigit():
            w += 0.64
        elif ch in "il.,:;'|!()[] ":
            w += 0.3
        else:
            w += 0.54
    return w * size


def wrap(s, size, width, lines=2):
    out = [""]
    for word in str(s).split():
        cand = (out[-1] + " " + word).strip()
        if text_w(cand, size) > width and out[-1]:
            out.append(word)
        else:
            out[-1] = cand
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1].rstrip(".") + "…"
    return out


def answer_state(value):
    if value is None or value == "" or value == {}:
        return "missing"
    if isinstance(value, str):
        return "answered" if value.strip() else "missing"
    if isinstance(value, dict):
        if value.get("risk") and value.get("accepted_by"):
            return "risk"
        if value.get("text"):
            return "suggested" if value.get("suggested") else "answered"
    return "missing"


def answer_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("risk"):
            return "Accepted risk: %s (by %s)" % (value["risk"], value.get("accepted_by") or "nobody")
        return value.get("text") or ""
    return ""


# --------------------------------------------------------------------------- architecture: checks and grid


def auto_place(nodes):
    """Fill in row and col for parts that have none: people, screens, services, data, outside."""
    tier = {"person": 0, "ui": 1, "api": 2, "service": 2, "job": 2, "library": 2, "table": 3, "topic": 3, "external": 4}
    used = {(n["row"], n["col"]) for n in nodes if isinstance(n.get("row"), int) and isinstance(n.get("col"), int)}
    cols = sorted({tier.get(n.get("kind"), 2) for n in nodes})
    remap = {c: i for i, c in enumerate(cols)}
    for n in nodes:
        if isinstance(n.get("row"), int) and isinstance(n.get("col"), int):
            continue
        col = remap[tier.get(n.get("kind"), 2)]
        row = 0
        while (row, col) in used:
            row += 1
        n["row"], n["col"] = row, col
        used.add((row, col))


def validate_architecture(a, repo_names=None):
    errors, warnings = [], []
    if not isinstance(a, dict):
        return ["architecture.json must be a JSON object"], []
    if not a.get("title"):
        errors.append("title is missing")
    nodes, links = a.get("nodes") or [], a.get("links") or []
    ids, cells = set(), {}
    if not nodes:
        errors.append("the high-level design has no parts")
    if len(nodes) > MAX_NODES:
        errors.append("%d parts. At most %d: group small parts into one." % (len(nodes), MAX_NODES))
    for i, n in enumerate(nodes, 1):
        if not isinstance(n, dict):
            errors.append("node %d must be an object" % i)
            continue
        nid = str(n.get("id") or "")
        if not ID_RE.match(nid):
            errors.append("node %d: id '%s' must start with a letter and use letters, numbers, - or _" % (i, nid))
        if nid in ids:
            errors.append("id %s is used twice" % nid)
        ids.add(nid)
        if not n.get("name"):
            errors.append("node %s needs a name" % nid)
        kind = n.get("kind")
        if kind not in NODE_KINDS:
            errors.append("node %s: kind must be one of %s" % (nid, ", ".join(NODE_KINDS)))
        if kind not in ("person",):
            st = n.get("status")
            if st not in STATUSES:
                errors.append("node %s: status must be one of %s" % (nid, ", ".join(STATUSES)))
            if st == "external" or kind == "external":
                if n.get("repo"):
                    warnings.append("node %s is outside the system, so it has no repo" % nid)
            elif not n.get("repo"):
                errors.append("node %s needs the repo it lives in" % nid)
            elif repo_names is not None and n["repo"] not in repo_names and st != "same":
                warnings.append("node %s: repo %s is not in chopchop.yaml" % (nid, n["repo"]))
        for key in ("row", "col"):
            if key in n and (not isinstance(n[key], int) or isinstance(n[key], bool) or n[key] < 0):
                errors.append("node %s: %s must be a whole number from 0" % (nid, key))
        if isinstance(n.get("col"), int) and n["col"] >= MAX_COLS:
            errors.append("node %s: col %d is too far right. Use at most %d columns, and more rows." % (nid, n["col"], MAX_COLS))
        if isinstance(n.get("row"), int) and isinstance(n.get("col"), int):
            key = (n["row"], n["col"])
            if key in cells:
                errors.append("%s and %s are in the same cell (row %d, col %d)" % (cells[key], nid, key[0], key[1]))
            cells[key] = nid
        if n.get("note") and len(str(n["note"])) > 40:
            warnings.append("node %s: note is long. Keep it under 40 characters." % nid)
    seen = set()
    for i, l in enumerate(links, 1):
        if not isinstance(l, dict):
            errors.append("link %d must be an object" % i)
            continue
        for end in ("from", "to"):
            if l.get(end) not in ids:
                errors.append("link %d: %s '%s' is not a part" % (i, end, l.get(end)))
        if l.get("from") == l.get("to"):
            errors.append("link %d goes from %s to itself" % (i, l.get("from")))
        if l.get("kind", "call") not in LINK_KINDS:
            errors.append("link %d: kind must be one of %s" % (i, ", ".join(LINK_KINDS)))
        if not l.get("label"):
            errors.append("link %d (%s to %s) needs a label: what it carries, in 1 to 4 words" % (i, l.get("from"), l.get("to")))
        elif STEP_RE.match(str(l["label"])):
            errors.append("link %d label '%s' is a step number. The high-level design shows parts, not steps: "
                          "say what the link carries, and put the order in flow.json." % (i, l["label"]))
        elif len(str(l["label"]).split()) > 5:
            warnings.append("link %d label has more than 5 words. Keep it short." % i)
        key = (l.get("from"), l.get("to"))
        if key in seen:
            warnings.append("link %d repeats %s to %s. Merge them into one label." % (i, key[0], key[1]))
        seen.add(key)
    used = {l.get("from") for l in links} | {l.get("to") for l in links}
    for n in nodes:
        if isinstance(n, dict) and n.get("id") not in used:
            warnings.append("part %s has no link. Connect it or take it off." % n.get("id"))
    if any(isinstance(n, dict) and ("n" in n or "step" in n) for n in links):
        errors.append("links have step numbers. The order of things goes in flow.json, not in the high-level design.")
    placed = [n for n in nodes if isinstance(n, dict) and isinstance(n.get("row"), int)]
    if len(placed) >= 5 and len({n["row"] for n in placed}) == 1:
        warnings.append("every part is in one row, so it reads like a sequence. Put each store under the part that owns it, "
                        "outside systems on the right and people on the left.")
    if not errors:
        errors += layout_problems(a)[0]
    return errors, warnings


# --------------------------------------------------------------------------- architecture: geometry

CELL_W, CELL_H, GAP_X, GAP_Y, ORIGIN_X, ORIGIN_Y, FRAME_PAD, FRAME_TOP = 208, 74, 104, 76, 28, 34, 16, 30


def _geometry(a):
    nodes = [dict(n) for n in a.get("nodes") or []]
    auto_place(nodes)
    by_id = {}
    for n in nodes:
        n["x"] = ORIGIN_X + n["col"] * (CELL_W + GAP_X)
        n["y"] = ORIGIN_Y + FRAME_TOP + n["row"] * (CELL_H + GAP_Y)
        n["w"], n["h"] = CELL_W, CELL_H
        by_id[n["id"]] = n
    groups = {}
    for n in nodes:
        if n.get("repo") and n.get("status") != "external" and n.get("kind") not in ("person", "external"):
            groups.setdefault(n["repo"], []).append(n)
    frames = []
    for repo, members in groups.items():
        x0 = min(m["x"] for m in members) - FRAME_PAD
        y0 = min(m["y"] for m in members) - FRAME_PAD - FRAME_TOP + 6
        x1 = max(m["x"] + m["w"] for m in members) + FRAME_PAD
        y1 = max(m["y"] + m["h"] for m in members) + FRAME_PAD
        frames.append({"repo": repo, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "members": {m["id"] for m in members}})
    return nodes, by_id, frames


def _inside(px, py, r, pad=0):
    return r["x"] - pad < px < r["x"] + r["w"] + pad and r["y"] - pad < py < r["y"] + r["h"] + pad


def _seg_hits(p, q, r, pad=6):
    """Does the axis-aligned segment p-q pass through rectangle r (grown by pad)?"""
    x0, x1 = sorted((p[0], q[0]))
    y0, y1 = sorted((p[1], q[1]))
    return not (x1 <= r["x"] - pad or x0 >= r["x"] + r["w"] + pad or y1 <= r["y"] - pad or y0 >= r["y"] + r["h"] + pad)


SIDES = {"r": (1, 0), "l": (-1, 0), "b": (0, 1), "t": (0, -1)}


def _port(n, side, offset=0.0):
    if side == "r":
        return (n["x"] + n["w"], n["y"] + n["h"] / 2 + offset)
    if side == "l":
        return (n["x"], n["y"] + n["h"] / 2 + offset)
    if side == "b":
        return (n["x"] + n["w"] / 2 + offset, n["y"] + n["h"])
    return (n["x"] + n["w"] / 2 + offset, n["y"])


def _candidates(a, sa, b, sb, oa=0.0, ob=0.0):
    """Right-angled paths from a's side sa to b's side sb, through the gaps."""
    p, q = _port(a, sa, oa), _port(b, sb, ob)
    stub = 14
    p1 = (p[0] + SIDES[sa][0] * stub, p[1] + SIDES[sa][1] * stub)
    q1 = (q[0] + SIDES[sb][0] * stub, q[1] + SIDES[sb][1] * stub)
    out = []
    if abs(p1[1] - q1[1]) < 0.5 or abs(p1[0] - q1[0]) < 0.5:
        out.append([p, p1, q1, q])
    out.append([p, p1, (q1[0], p1[1]), q1, q])
    out.append([p, p1, (p1[0], q1[1]), q1, q])
    # through a column gap, or a row gap
    for gx in _gaps(a, b, "x"):
        out.append([p, p1, (gx, p1[1]), (gx, q1[1]), q1, q])
    for gy in _gaps(a, b, "y"):
        out.append([p, p1, (p1[0], gy), (q1[0], gy), q1, q])
    return out


def _gaps(a, b, axis):
    if axis == "x":
        lo, hi = sorted((a["col"], b["col"]))
        cols = range(lo, hi) if hi > lo else [lo - 1, lo]
        return [ORIGIN_X / 2 if c < 0 else ORIGIN_X + c * (CELL_W + GAP_X) + CELL_W + GAP_X / 2 for c in cols]
    lo, hi = sorted((a["row"], b["row"]))
    rows = range(lo, hi) if hi > lo else [lo - 1, lo]
    return [ORIGIN_Y / 2 if r < 0 else ORIGIN_Y + FRAME_TOP + r * (CELL_H + GAP_Y) + CELL_H + GAP_Y / 2 for r in rows]


def _clean(points):
    out = []
    for pt in points:
        if out and abs(out[-1][0] - pt[0]) < 0.5 and abs(out[-1][1] - pt[1]) < 0.5:
            continue
        out.append(pt)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 0.5 and abs(b[0] - c[0]) < 0.5) or (abs(a[1] - b[1]) < 0.5 and abs(b[1] - c[1]) < 0.5):
            out.pop(i)
        else:
            i += 1
    return out


def _score(points, obstacles, a, b):
    hits = 0
    for i in range(len(points) - 1):
        for r in obstacles:
            if _seg_hits(points[i], points[i + 1], r):
                hits += 1
    length = sum(abs(points[i][0] - points[i + 1][0]) + abs(points[i][1] - points[i + 1][1]) for i in range(len(points) - 1))
    bends = max(0, len(points) - 2)
    return hits, bends * 60 + length


def route_all(a):
    """Lay out and route the high-level design. Returns (nodes, frames, routes, problems)."""
    nodes, by_id, frames = _geometry(a)
    problems = []
    plans = []
    for i, l in enumerate(a.get("links") or []):
        na, nb = by_id.get(l.get("from")), by_id.get(l.get("to"))
        if not na or not nb:
            continue
        best = None
        obstacles = [n for n in nodes if n["id"] not in (na["id"], nb["id"])]
        for sa in SIDES:
            for sb in SIDES:
                for pts in _candidates(na, sa, nb, sb):
                    pts = _clean(pts)
                    hits, cost = _score(pts, obstacles, na, nb)
                    # no middle segment may run back through its own two parts
                    mids = [(pts[j], pts[j + 1]) for j in range(1, len(pts) - 2)]
                    if any(_seg_hits(u, v, na, pad=-1) or _seg_hits(u, v, nb, pad=-1) for u, v in mids):
                        hits += 5
                    key = (hits, cost)
                    if best is None or key < best[0]:
                        best = (key, sa, sb)
        plans.append({"i": i, "link": l, "a": na, "b": nb, "sa": best[1], "sb": best[2], "hits": best[0][0]})
    # spread several lines on one side of a part
    slots = {}
    for p in plans:
        slots.setdefault((p["a"]["id"], p["sa"]), []).append((p, "a"))
        slots.setdefault((p["b"]["id"], p["sb"]), []).append((p, "b"))
    for (nid, side), items in slots.items():
        node = by_id[nid]
        horiz = side in ("t", "b")
        items.sort(key=lambda it: (it[0]["b"] if it[1] == "a" else it[0]["a"])["x" if horiz else "y"])
        k = len(items)
        span = (node["w"] if horiz else node["h"]) - 24
        step = min(16 if not horiz else 28, span / max(1, k - 1)) if k > 1 else 0
        for j, (p, end) in enumerate(items):
            p["o" + end] = (j - (k - 1) / 2) * step
    routes = []
    for p in plans:
        na, nb = p["a"], p["b"]
        obstacles = [n for n in nodes if n["id"] not in (na["id"], nb["id"])]
        best = None
        for pts in _candidates(na, p["sa"], nb, p["sb"], p.get("oa", 0), p.get("ob", 0)):
            pts = _clean(pts)
            key = _score(pts, obstacles, na, nb)
            if best is None or key < best[0]:
                best = (key, pts)
        if best[0][0]:
            blocked = [n["name"] for n in obstacles if any(_seg_hits(best[1][j], best[1][j + 1], n) for j in range(len(best[1]) - 1))]
            problems.append("the line %s to %s (%s) crosses %s. Move %s or %s so a straight or one-bend path is free."
                            % (na["name"], nb["name"], p["link"].get("label"), ", ".join(blocked), na["name"], nb["name"]))
        routes.append({"link": p["link"], "points": best[1]})
    return nodes, frames, routes, problems


def layout_problems(a):
    """Errors in placement, found by laying it out."""
    errors, warnings = [], []
    nodes, frames, routes, problems = route_all(a)
    errors += problems
    for f in frames:
        for n in nodes:
            if n["id"] in f["members"]:
                continue
            cx, cy = n["x"] + n["w"] / 2, n["y"] + n["h"] / 2
            if _inside(cx, cy, f):
                errors.append("%s sits inside the %s group but is not in that repo. Move it outside the group's rows and columns."
                              % (n["name"], f["repo"]))
    for i, f in enumerate(frames):
        for g in frames[i + 1:]:
            if not (f["x"] + f["w"] <= g["x"] or g["x"] + g["w"] <= f["x"] or f["y"] + f["h"] <= g["y"] or g["y"] + g["h"] <= f["y"]):
                errors.append("the %s and %s groups overlap. Keep each repo's parts in their own block of rows and columns."
                              % (f["repo"], g["repo"]))
    width = max([n["x"] + n["w"] for n in nodes] + [0]) + ORIGIN_X
    if width > MAX_WIDTH:
        warnings.append("the high-level design is %dpx wide. Above %dpx its text gets small: use more rows and fewer columns."
                        % (width, MAX_WIDTH))
    return errors, warnings


# --------------------------------------------------------------------------- architecture: SVG


def _rounded(points, r=10):
    d = "M%.1f %.1f" % points[0]
    for i in range(1, len(points) - 1):
        (x0, y0), (x1, y1), (x2, y2) = points[i - 1], points[i], points[i + 1]
        l1 = max(1.0, abs(x1 - x0) + abs(y1 - y0))
        l2 = max(1.0, abs(x2 - x1) + abs(y2 - y1))
        rr = min(r, l1 / 2, l2 / 2)
        ax, ay = x1 - (x1 - x0) / l1 * rr, y1 - (y1 - y0) / l1 * rr
        bx, by = x1 + (x2 - x1) / l2 * rr, y1 + (y2 - y1) / l2 * rr
        d += " L%.1f %.1f Q%.1f %.1f %.1f %.1f" % (ax, ay, x1, y1, bx, by)
    d += " L%.1f %.1f" % points[-1]
    return d


def _icon(kind, x, y, stroke):
    return ('<path d="%s" transform="translate(%.1f %.1f)" fill="none" stroke="%s" stroke-width="1.8" '
            'stroke-linecap="round" stroke-linejoin="round"/>' % (ICONS.get(kind, ICONS["service"]), x, y, stroke))


def _node_svg(n):
    kind, st = n.get("kind"), n.get("status")
    key = "person" if kind == "person" else (st if st in COLOR else "same")
    fill, stroke = COLOR[key]
    x, y, w, h = n["x"], n["y"], n["w"], n["h"]
    out = ['<g class="node">']
    dash = ' stroke-dasharray="6 4"' if key == "external" else ""
    out.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="%d" fill="%s" stroke="%s" stroke-width="1.6"%s/>'
               % (x, y, w, h, h // 2 if kind == "person" else 12, fill, stroke, dash))
    if key in ("new", "changed"):
        out.append('<rect x="%.1f" y="%.1f" width="5" height="%d" rx="2.5" fill="%s"/>' % (x + 1, y + 10, h - 20, stroke))
    out.append(_icon(kind, x + 16, y + h / 2 - 12, stroke))
    tx = x + 50
    name_lines = wrap(n["name"], 15, w - 62, 2)
    sub = n.get("note") or ""
    chip = CHIP.get(key)
    meta = bool(sub or chip)
    total = len(name_lines) * 19 + (20 if meta else 0)
    ty = y + h / 2 - total / 2 + 14
    for i, line in enumerate(name_lines):
        out.append('<text x="%.1f" y="%.1f" font-size="15" font-weight="600" fill="%s">%s</text>' % (tx, ty + i * 19, INK, esc(line)))
    mx, my = tx, ty + len(name_lines) * 19 - 9
    if chip:
        label, color = chip
        cw = text_w(label, 9.5) + 12
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="16" rx="8" fill="%s"/>' % (mx, my, cw, color))
        out.append('<text x="%.1f" y="%.1f" font-size="9.5" font-weight="700" letter-spacing="0.06em" fill="#fff" text-anchor="middle">%s</text>'
                   % (mx + cw / 2, my + 11.5, label))
        mx += cw + 7
    if sub:
        sub_line = wrap(sub, 12, x + w - 12 - mx, 1)[0]
        out.append('<text x="%.1f" y="%.1f" font-size="12" fill="%s">%s</text>' % (mx, my + 12, MUTED, esc(sub_line)))
    out.append("</g>")
    return "\n".join(out)


def _label_box(points, text, size=12.5):
    """The middle of the longest segment, with a white pill."""
    best, bi = -1, 0
    for i in range(len(points) - 1):
        ln = abs(points[i][0] - points[i + 1][0]) + abs(points[i][1] - points[i + 1][1])
        if ln > best:
            best, bi = ln, i
    (x0, y0), (x1, y1) = points[bi], points[bi + 1]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w = text_w(text, size) + 16
    return {"x": cx - w / 2, "y": cy - 11, "w": w, "h": 22, "cx": cx, "cy": cy}


def architecture_svg(a):
    nodes, frames, routes, _ = route_all(a)
    W = max([n["x"] + n["w"] for n in nodes] + [400]) + ORIGIN_X
    H = max([n["y"] + n["h"] for n in nodes] + [200]) + 34
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" font-family="%s" class="cc-arch" '
           'style="width:100%%;height:auto;max-width:%dpx;min-width:%dpx">'
           % (W, H, W, H, esc(FONT), W, int(W * 0.8)),
           "<title>%s</title>" % esc(a.get("title") or "High-level design"),
           '<defs><marker id="cc-ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0 0L10 5L0 10z" fill="%s"/></marker></defs>' % LINE]
    for f in frames:
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="16" fill="#f5f8fe" stroke="#c5d1e4" stroke-width="1.2"/>'
                   % (f["x"], f["y"], f["w"], f["h"]))
        out.append('<text x="%.1f" y="%.1f" font-size="13" font-weight="700" fill="%s" letter-spacing="0.02em">%s</text>'
                   % (f["x"] + 14, f["y"] + 21, NAVY, esc(f["repo"])))
    placed = []
    lines, labels = [], []
    for r in routes:
        l = r["link"]
        dash = ' stroke-dasharray="7 5"' if l.get("kind") == "event" else ""
        lines.append('<path d="%s" fill="none" stroke="%s" stroke-width="1.8"%s marker-end="url(#cc-ah)"/>'
                     % (_rounded(r["points"]), LINE, dash))
        if l.get("label"):
            box = _label_box(r["points"], l["label"])
            for other in placed:
                if not (box["x"] + box["w"] < other["x"] or other["x"] + other["w"] < box["x"] or
                        box["y"] + box["h"] < other["y"] or other["y"] + other["h"] < box["y"]):
                    box["y"] = other["y"] + other["h"] + 3
                    box["cy"] = box["y"] + 11
            placed.append(box)
            labels.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%d" rx="11" fill="#ffffff" stroke="#dde4ef"/>'
                          '<text x="%.1f" y="%.1f" font-size="12.5" font-weight="500" fill="%s" text-anchor="middle">%s</text>'
                          % (box["x"], box["y"], box["w"], box["h"], box["cx"], box["cy"] + 4.5, INK, esc(l["label"])))
    out += lines
    out += [_node_svg(n) for n in nodes]
    out += labels
    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------- architecture: Mermaid


def _mid(i):
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", str(i))


def mlabel(text):
    text = re.sub(r"[\[\]{}()<>|\"#;`\\]", " ", str(text or "")).replace("/", " ")
    return re.sub(r"\s+", " ", text).strip() or "x"


def architecture_mermaid(a):
    lines = ["flowchart LR"]
    groups = {}
    for n in a.get("nodes") or []:
        key = None if n.get("kind") in ("person", "external") or n.get("status") == "external" else n.get("repo")
        groups.setdefault(key, []).append(n)
    shapes = {"table": "[(%s)]", "topic": "{{%s}}", "job": "[[%s]]", "person": "([%s])"}
    tags = {"new": " NEW", "changed": " CHANGED"}
    for repo in sorted(groups, key=lambda r: r or "~"):
        ind = "    " if repo else "  "
        if repo:
            lines.append("  subgraph g_%s[%s]" % (re.sub(r"[^A-Za-z0-9_]", "_", repo), mlabel(repo)))
        for n in groups[repo]:
            lines.append("%s%s%s" % (ind, _mid(n["id"]), shapes.get(n.get("kind"), "[%s]") % (mlabel(n["name"]) + tags.get(n.get("status"), ""))))
        if repo:
            lines.append("  end")
    for l in a.get("links") or []:
        arrow = "-.->" if l.get("kind") == "event" else "-->"
        lines.append("  %s %s|%s| %s" % (_mid(l["from"]), arrow, mlabel(l.get("label")), _mid(l["to"])))
    cls = {"new": [], "changed": [], "same": [], "ext": []}
    for n in a.get("nodes") or []:
        c = "ext" if n.get("status") == "external" or n.get("kind") == "external" else n.get("status")
        if c in cls:
            cls[c].append(_mid(n["id"]))
    for c, members in cls.items():
        if members:
            lines.append("  class %s %s" % (",".join(members), c))
    lines += ["  classDef new fill:#e9f7ef,stroke:#1d6a51,color:#10231a",
              "  classDef changed fill:#fff4e2,stroke:#b26100,color:#2b1c00",
              "  classDef same fill:#ffffff,stroke:#94a3b8,color:#0b1220",
              "  classDef ext fill:#f8fafc,stroke:#64748b,stroke-dasharray:4 3,color:#1f2937"]
    return "\n".join(lines)


def repos_touched(a):
    return sorted({n["repo"] for n in (a or {}).get("nodes") or [] if n.get("status") in ("new", "changed") and n.get("repo")})


# --------------------------------------------------------------------------- flow: checks


def participants(f, a=None):
    by_id = {n["id"]: n for n in (a or {}).get("nodes") or []}
    out = []
    for pid in f.get("participants") or []:
        n = by_id.get(pid) or {"id": pid, "name": pid, "kind": "service", "status": "same"}
        out.append(n)
    return out


def validate_flow(f, a=None, story_ids=None, known_ids=None):
    errors, warnings = [], []
    if not isinstance(f, dict):
        return ["flow.json must be a JSON object"], []
    if not f.get("title"):
        errors.append("title is missing")
    parts = f.get("participants") or []
    arch_ids = {n.get("id") for n in (a or {}).get("nodes") or []}
    if not parts:
        errors.append("participants is empty: list the parts of the high-level design this flow passes, left to right")
    if len(parts) > MAX_PARTICIPANTS:
        errors.append("%d participants. At most %d: leave out parts the flow only passes through." % (len(parts), MAX_PARTICIPANTS))
    for pid in parts:
        if a is not None and pid not in arch_ids:
            errors.append("participant %s is not a part in architecture.json. Use the same ids." % pid)
    if len(set(parts)) != len(parts):
        errors.append("a participant is listed twice")
    msgs = f.get("messages") or []
    if not msgs:
        errors.append("the flow has no messages")
    for i, m in enumerate(msgs, 1):
        if not isinstance(m, dict):
            errors.append("message %d must be an object" % i)
            continue
        if m.get("n") != i:
            errors.append("messages must be numbered 1, 2, 3 in order: message %d has n=%r" % (i, m.get("n")))
        for end in ("from", "to"):
            if m.get(end) not in parts:
                errors.append("message %d: %s '%s' is not a participant" % (i, end, m.get(end)))
        if m.get("kind") not in MSG_KINDS:
            errors.append("message %d: kind must be one of %s" % (i, ", ".join(MSG_KINDS)))
        if not m.get("say"):
            errors.append("message %d needs say: 2 to 6 words on the arrow" % i)
        elif len(str(m["say"]).split()) > 6:
            warnings.append("message %d: say has more than 6 words" % i)
        if not m.get("line"):
            errors.append("message %d needs line: one plain sentence" % i)
        for sid in m.get("stories") or []:
            if known_ids is not None and sid not in known_ids:
                errors.append("message %d: %s is not a story or AC id in requirement.md" % (i, sid))
        failure = m.get("failure") or {}
        if not isinstance(failure, dict):
            errors.append("message %d: failure must be an object" % i)
        else:
            for key in failure:
                if key not in ANSWER_KEYS:
                    errors.append("message %d: failure.%s is not a question. Use %s" % (i, key, ", ".join(ANSWER_KEYS)))
    if story_ids:
        on = {sid.split(".AC")[0] for m in msgs if isinstance(m, dict) for sid in m.get("stories") or []}
        out = set(f.get("out_of_scope") or [])
        for sid in story_ids:
            if sid not in on and sid not in out:
                errors.append("story %s has no message in flow.json. Add one, or list it in out_of_scope." % sid)
    return errors, warnings


def failures(f):
    rows = []
    for m in f.get("messages") or []:
        if not isinstance(m, dict) or m.get("kind") not in MSG_KINDS:
            continue
        given = m.get("failure") or {}
        for key in ANSWER_KEYS:
            if key not in MSG_KINDS[m["kind"]]:
                continue
            value = given.get(key) if isinstance(given, dict) else None
            rows.append({"n": m.get("n"), "say": m.get("say"), "kind": m["kind"], "question": key,
                         "ask": QUESTIONS[key], "state": answer_state(value), "answer": answer_text(value)})
    return rows


def missing(f):
    return [r for r in failures(f) if r["state"] == "missing"]


def caption(f):
    out = []
    for m in f.get("messages") or []:
        ids = ", ".join(m.get("stories") or [])
        cond = " (if %s)" % m["if"] if m.get("if") else ""
        out.append("%s. %s%s%s" % (m.get("n"), m.get("line") or m.get("say"), cond, " _(%s)_" % ids if ids else ""))
    return out


def failure_table(f):
    rows = ["| # | Message | Fails | Slow | Runs twice | Wrong caller |", "| --- | --- | --- | --- | --- | --- |"]
    for m in f.get("messages") or []:
        if m.get("kind") not in MSG_KINDS or not MSG_KINDS[m["kind"]]:
            continue
        given = m.get("failure") or {}
        cells = []
        for key in ANSWER_KEYS:
            if key not in MSG_KINDS[m["kind"]]:
                cells.append("Not needed")
                continue
            value = given.get(key)
            state = answer_state(value)
            text = answer_text(value).replace("|", "\\|").replace("\n", " ")
            cells.append({"missing": "⚠ **No answer yet.**", "suggested": "_Suggested, confirm:_ " + text}.get(state, text))
        rows.append("| %s | %s _(%s)_ | %s |" % (m.get("n"), mlabel(m.get("say")), KIND_NAMES[m["kind"]], " | ".join(cells)))
    return "\n".join(rows)


# --------------------------------------------------------------------------- flow: SVG


def flow_svg(f, a=None):
    parts = participants(f, a)
    msgs = f.get("messages") or []
    gaps = {r["n"] for r in missing(f)}
    col_w = []
    for p in parts:
        col_w.append(max(170, text_w(p["name"], 14.5) + 70))
    # widen a gap when a label between two neighbours needs it
    idx = {p["id"]: i for i, p in enumerate(parts)}
    for m in msgs:
        i, j = idx.get(m.get("from")), idx.get(m.get("to"))
        if i is None or j is None or i == j:
            continue
        lo, hi = sorted((i, j))
        need = text_w(m.get("say") or "", 13) + 64 + (text_w("if " + m["if"], 11) + 24 if m.get("if") else 0)
        have = sum((col_w[k] + col_w[k + 1]) / 2 for k in range(lo, hi))
        if need > have:
            extra = (need - have) / (hi - lo)
            for k in range(lo, hi):
                col_w[k] += extra / 2
                col_w[k + 1] += extra / 2
    xs, x = [], 24
    for w in col_w:
        xs.append(x + w / 2)
        x += w
    W = int(x + 24)
    top, head_h, step = 20, 56, 52
    y = top + head_h + 34
    rows = []
    for m in msgs:
        rows.append(y)
        y += step + (16 if m.get("if") else 0)
    H = int(y + 10)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" font-family="%s" class="cc-flow" '
           'style="width:100%%;height:auto;max-width:%dpx;min-width:%dpx">'
           % (W, H, W, H, esc(FONT), W, int(W * 0.75)),
           "<title>%s</title>" % esc(f.get("title") or "Main flow"),
           '<defs><marker id="cc-fa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0 0L10 5L0 10z" fill="%s"/></marker>'
           '<marker id="cc-fr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           '<path d="M0 0L10 5L0 10z" fill="%s"/></marker></defs>' % (LINE, AMBER)]
    for p, cx, w in zip(parts, xs, col_w):
        key = "person" if p.get("kind") == "person" else (p.get("status") if p.get("status") in COLOR else "same")
        fill, stroke = COLOR[key]
        bw = min(w - 18, max(140, text_w(p["name"], 14.5) + 58))
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#c5d1e4" stroke-width="1.5" stroke-dasharray="4 5"/>'
                   % (cx, top + head_h, cx, H - 8))
        dash = ' stroke-dasharray="6 4"' if key == "external" else ""
        out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" rx="%d" fill="%s" stroke="%s" stroke-width="1.6"%s/>'
                   % (cx - bw / 2, top, bw, head_h, head_h // 2 if key == "person" else 12, fill, stroke, dash))
        out.append(_icon(p.get("kind"), cx - bw / 2 + 12, top + head_h / 2 - 12, stroke))
        name = wrap(p["name"], 14.5, bw - 52, 1)[0]
        sub = p.get("repo") or ("outside" if key == "external" else "")
        out.append('<text x="%.1f" y="%d" font-size="14.5" font-weight="600" fill="%s">%s</text>'
                   % (cx - bw / 2 + 44, top + (24 if sub else head_h / 2 + 5), INK, esc(name)))
        if sub:
            out.append('<text x="%.1f" y="%d" font-size="11.5" fill="%s">%s</text>' % (cx - bw / 2 + 44, top + 41, MUTED, esc(sub)))
    for m, y in zip(msgs, rows):
        i, j = idx.get(m.get("from")), idx.get(m.get("to"))
        if i is None or j is None:
            continue
        x1, x2 = xs[i], xs[j]
        cond = bool(m.get("if"))
        color = AMBER if cond else LINE
        marker = "cc-fr" if cond else "cc-fa"
        dash = ' stroke-dasharray="6 5"' if m.get("kind") in ("reply", "event") else ""
        if i == j:
            out.append('<path d="M%.1f %d h46 v22 h-42" fill="none" stroke="%s" stroke-width="1.8"%s marker-end="url(#%s)"/>'
                       % (x1, y, color, dash, marker))
            lx = x1 + 56
            anchor = "start"
        else:
            d = 1 if x2 > x1 else -1
            out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1.8"%s marker-end="url(#%s)"/>'
                       % (x1 + d * 4, y, x2 - d * 6, y, color, dash, marker))
            lx = (x1 + x2) / 2
            anchor = "middle"
        text = m.get("say") or ""
        tw = text_w(text, 13)
        badge = 24
        block = tw + badge + 6
        bx = lx - block / 2 if anchor == "middle" else lx
        badge_fill = RED if m.get("n") in gaps else BLUE
        ly = y - 10
        out.append('<circle cx="%.1f" cy="%d" r="10.5" fill="%s"/>' % (bx + 10.5, ly - 4, badge_fill))
        out.append('<text x="%.1f" y="%d" font-size="11.5" font-weight="700" fill="#fff" text-anchor="middle">%s</text>'
                   % (bx + 10.5, ly, m.get("n")))
        out.append('<text x="%.1f" y="%d" font-size="13" font-weight="500" fill="%s">%s</text>' % (bx + badge + 4, ly, INK, esc(text)))
        if cond:
            ctext = "if " + m["if"]
            cw = text_w(ctext, 11) + 16
            cx0 = (lx - cw / 2) if anchor == "middle" else lx
            out.append('<rect x="%.1f" y="%d" width="%.1f" height="18" rx="9" fill="#fff3e0" stroke="#f1c98b"/>'
                       '<text x="%.1f" y="%d" font-size="11" font-weight="600" fill="#9a4b00" text-anchor="middle">%s</text>'
                       % (cx0, y + 8, cw, cx0 + cw / 2, y + 21, esc(ctext)))
    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------- flow: Mermaid


def flow_mermaid(f, a=None):
    parts = participants(f, a)
    aliases = {}
    lines = ["sequenceDiagram"]
    for k, p in enumerate(parts):
        alias = "P%d" % (k + 1)
        aliases[p["id"]] = alias
        lines.append("  %s %s as %s" % ("actor" if p.get("kind") == "person" else "participant", alias, mlabel(p["name"])))
    open_if = None
    for m in f.get("messages") or []:
        cond = m.get("if")
        if open_if and cond != open_if:
            lines.append("  end")
            open_if = None
        if cond and cond != open_if:
            lines.append("  opt %s" % mlabel(cond))
            open_if = cond
        arrow = {"reply": "-->>", "event": "--)"}.get(m.get("kind"), "->>")
        lines.append("  %s%s %s%s: %s. %s" % ("  " if open_if else "", aliases.get(m.get("from"), "X"), arrow,
                                              aliases.get(m.get("to"), "X"), m.get("n"), mlabel(m.get("say"))))
    if open_if:
        lines.append("  end")
    return "\n".join(lines)


# --------------------------------------------------------------------------- the file map (spec)

FILE_COLOR = {"new": ("#e9f7ef", "#1d6a51", "NEW"), "change": ("#fff4e2", "#b26100", "CHANGED"),
              "delete": ("#fdecea", "#b42318", "DELETED")}
FM_COL_W, FM_GAP, FM_PAD, FM_ROW, FM_HEAD, FM_FOLDER, FM_COLS = 380, 28, 20, 34, 44, 26, 3


def _file_groups(spec):
    """{repo: {folder: [(file name, change, package id)]}} in package order."""
    out = {}
    pk = sorted([p for p in spec.get("packages") or [] if isinstance(p, dict)],
                key=lambda p: (p.get("wave") if isinstance(p.get("wave"), int) else 9, str(p.get("id"))))
    for p in pk:
        for f in p.get("files") or []:
            if not isinstance(f, dict) or not f.get("path"):
                continue
            folder, _, name = str(f["path"]).rpartition("/")
            out.setdefault(p.get("repo") or "?", {}).setdefault(folder or ".", []).append((name, f.get("change"), p.get("id")))
    return out


def file_map_svg(spec):
    groups = _file_groups(spec)
    if not groups:
        return ""
    cols = []
    for repo, folders in groups.items():
        h = FM_HEAD + sum(FM_FOLDER + len(files) * FM_ROW + 10 for files in folders.values()) + 8
        cols.append((repo, folders, h))
    per_row = min(FM_COLS, len(cols))
    W = FM_PAD * 2 + per_row * FM_COL_W + (per_row - 1) * FM_GAP
    rows = [cols[i:i + per_row] for i in range(0, len(cols), per_row)]
    H = FM_PAD * 2 + sum(max(c[2] for c in r) for r in rows) + FM_GAP * (len(rows) - 1)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" font-family="%s" '
           'class="cc-files" style="width:100%%;height:auto;max-width:%dpx;min-width:%dpx">'
           % (W, H, W, H, esc(FONT), W, int(W * 0.7)),
           '<title>%s</title>' % esc("Files this feature creates or changes, by repo")]
    y0 = FM_PAD
    for r in rows:
        for i, (repo, folders, h) in enumerate(r):
            x = FM_PAD + i * (FM_COL_W + FM_GAP)
            n = sum(len(v) for v in folders.values())
            out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="14" fill="#f7faff" stroke="#c5d1e4"/>' % (x, y0, FM_COL_W, h))
            out.append('<text x="%d" y="%d" font-size="15" font-weight="700" fill="%s">%s</text>' % (x + 16, y0 + 28, NAVY, esc(repo)))
            out.append('<text x="%d" y="%d" font-size="12.5" fill="%s" text-anchor="end">%d file%s</text>'
                       % (x + FM_COL_W - 16, y0 + 28, MUTED, n, "" if n == 1 else "s"))
            y = y0 + FM_HEAD
            for folder, files in folders.items():
                label = folder + "/" if folder != "." else "(repo root)"
                out.append('<text x="%d" y="%d" font-size="12.5" font-family="JetBrains Mono, ui-monospace, monospace" fill="%s">%s</text>'
                           % (x + 16, y + 16, MUTED, esc(wrap(label, 12.5 * 1.1, FM_COL_W - 40, 1)[0])))
                y += FM_FOLDER
                for name, change, pid in files:
                    fill, stroke, chip = FILE_COLOR.get(change, ("#ffffff", "#94a3b8", ""))
                    out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="%s" stroke="%s"/>'
                               % (x + 12, y, FM_COL_W - 24, FM_ROW - 6, fill, stroke))
                    out.append('<rect x="%d" y="%d" width="4" height="%d" rx="2" fill="%s"/>' % (x + 12, y, FM_ROW - 6, stroke))
                    out.append('<text x="%d" y="%d" font-size="13.5" font-weight="600" fill="%s">%s</text>'
                               % (x + 24, y + 19, INK, esc(wrap(name, 13.5, FM_COL_W - 150, 1)[0])))
                    if chip:
                        out.append('<text x="%d" y="%d" font-size="10.5" font-weight="700" fill="%s" text-anchor="end" letter-spacing=".04em">%s</text>'
                                   % (x + FM_COL_W - 62, y + 18, stroke, chip))
                    if pid:
                        out.append('<rect x="%d" y="%d" width="34" height="18" rx="9" fill="#eaf1ff" stroke="#bcd0fb"/>'
                                   % (x + FM_COL_W - 54, y + 5))
                        out.append('<text x="%d" y="%d" font-size="11" font-weight="700" fill="%s" text-anchor="middle">%s</text>'
                                   % (x + FM_COL_W - 37, y + 18, NAVY, esc(pid)))
                    y += FM_ROW
                y += 10
        y0 += max(c[2] for c in r) + FM_GAP
    out.append("</svg>")
    return "".join(out)


def file_map_mermaid(spec):
    lines = ["flowchart LR"]
    k = 0
    for ri, (repo, folders) in enumerate(_file_groups(spec).items()):
        lines.append("  subgraph r%d[%s]" % (ri, mlabel(repo)))
        for fi, (folder, files) in enumerate(folders.items()):
            lines.append("    subgraph r%df%d[%s]" % (ri, fi, mlabel(folder.replace("/", " › ")) if folder != "." else "root"))
            for name, change, pid in files:
                k += 1
                tag = {"new": "NEW", "change": "CHANGED", "delete": "DELETED"}.get(change, "")
                lines.append("      n%d[%s]" % (k, mlabel("%s %s %s" % (name, tag, pid or ""))))
                if change in ("new", "change", "delete"):
                    lines.append("      class n%d %s" % (k, change))
            lines.append("    end")
        lines.append("  end")
    lines += ["  classDef new fill:#e9f7ef,stroke:#1d6a51", "  classDef change fill:#fff4e2,stroke:#b26100",
              "  classDef delete fill:#fdecea,stroke:#b42318"]
    return "\n".join(lines)
