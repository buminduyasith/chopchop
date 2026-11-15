"""Cheap text likeness: which comments may be about the same thing, and which spec rules a comment touches.

No model, no index: shared words (without filler words), plus the same file or the same function.
It only suggests. The triager reads the code and decides what really belongs together.
"""

import re

THRESHOLD = 0.3
SAME_FILE, SAME_FUNC = 0.3, 0.2
MAX_SIMILAR = 5
MAX_RULES = 3

STOP = set("""
a an the and or but if then else for to of in on at by with from as is are was were be been being this that these
those it its i you we they he she me my our your their not no yes do does did done doing can could should would will
shall may might must have has had having there here what when where why how which who whom so than too very just also
about into over under again more most some any each all both only same such own out off up down
please think maybe seems seem looks look like need needs want wants make makes made use uses used using get gets got
instead rather still even really actually probably well good nice great thanks thank let lets sure
line lines code file files change changes changed comment comments review reviews pr nit nits here
true false null none return returns new old one two
""".split())
FUNC = re.compile(r"\b(?:def|function|func|fn|fun|class|interface|struct|sub)\s+([A-Za-z_]\w*)")
CALL = re.compile(r"([A-Za-z_]\w*)\s*\(")
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "def", "class", "new", "await", "async",
            "public", "private", "protected", "static", "void"}


def _stem(word):
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def tokens(text):
    """Lower-case words of a text, without filler words. camelCase and snake_case names also give their parts."""
    text = str(text or "")
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    out = set()
    for source in (text, spaced):
        for word in re.findall(r"[a-z_][a-z0-9_]{2,}", source.lower()):
            for part in [word] + [p for p in word.split("_") if len(p) > 2]:
                part = _stem(part.strip("_"))
                if len(part) > 2 and part not in STOP:
                    out.add(part)
    return out


def function_of(hunk):
    """The function a diff hunk sits in, from its @@ line, or None."""
    m = re.match(r"^@@[^@]*@@(.*)$", str(hunk or "").split("\n", 1)[0])
    if not m or not m.group(1).strip():
        return None
    head = m.group(1)
    named = FUNC.search(head)
    if named:
        return named.group(1)
    calls = [c for c in CALL.findall(head) if c not in KEYWORDS]
    return calls[0] if calls else None


def features_of(thread):
    text = "\n".join([thread.get("body") or ""] + [r.get("body") or "" for r in thread.get("replies") or []])
    return {"tokens": tokens(text),
            "file": "%s/%s" % (thread.get("repo"), thread["file"]) if thread.get("file") else None,
            "func": function_of(thread.get("hunk"))}


def score(a, b):
    """(0..1, reasons) for two feature sets from features_of()."""
    shared = a["tokens"] & b["tokens"]
    small = min(len(a["tokens"]), len(b["tokens"]))
    value, why = 0.0, []
    if small and len(shared) >= 2:
        value = len(shared) / float(small)
        why.append("same words: %s" % ", ".join(sorted(shared)[:5]))
    if a["file"] and a["file"] == b["file"]:
        value += SAME_FILE
        why.append("same file")
    if a["func"] and a["func"] == b["func"]:
        value += SAME_FUNC
        why.append("same function %s" % a["func"])
    return min(value, 1.0), why


def similar_threads(targets, everything, limit=MAX_SIMILAR, threshold=THRESHOLD):
    """{target id: [{"id", "score", "why"}]}: for each target thread, the most alike among all threads."""
    feats = {t["id"]: features_of(t) for t in everything}
    out = {}
    for t in targets:
        mine = feats.get(t["id"]) or features_of(t)
        hits = []
        for other in everything:
            if other["id"] == t["id"]:
                continue
            value, why = score(mine, feats[other["id"]])
            if value >= threshold:
                hits.append({"id": other["id"], "score": round(value, 2), "why": why})
        hits.sort(key=lambda h: (-h["score"], h["id"]))
        out[t["id"]] = hits[:limit]
    return out


def matching_rules(rules, thread, limit=MAX_RULES):
    """Spec rules whose text shares at least two words with the comment: [{"id", "text", "words"}]."""
    mine = features_of(thread)["tokens"]
    hits = []
    for r in rules or []:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        shared = mine & tokens("%s %s" % (r.get("text") or "", r.get("met") or ""))
        if len(shared) >= 2:
            hits.append({"id": str(r["id"]), "text": str(r.get("text") or ""), "words": sorted(shared)})
    hits.sort(key=lambda h: (-len(h["words"]), h["id"]))
    return hits[:limit]
