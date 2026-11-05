"""design.md: 12 fixed sections for leads, generated blocks, lint and slides.

chopchop writes the prose. The script owns four blocks and fills them on every build:

  <!-- chopchop:architecture --> ... <!-- /chopchop:architecture -->  section 2, from architecture.json
  <!-- chopchop:flow --> ... <!-- /chopchop:flow -->                  section 5, from flow.json
  <!-- chopchop:decisions --> ... <!-- /chopchop:decisions -->  section 8, from options.json
  <!-- chopchop:approval --> ... <!-- /chopchop:approval -->    section 12, approvers and status

Speaker notes for the slides go in a section as <!-- talk: ... -->.
"""

import re

HEADINGS = [
    "Summary and the ask", "High-level design", "Why", "Scope", "Main flow and errors", "Data changes",
    "Contract changes", "Key decisions", "Impact and rollout", "Risks", "How we prove it",
    "Questions, assumptions, approval",
]
APPENDIX = "Likely questions"
BLOCKS = {"architecture": 2, "flow": 5, "decisions": 8, "approval": 12}
BUDGETS = {"small": 500, "medium": 1300, "large": 1800}
STATUSES = ["draft", "approved", "approved-with-conditions", "changes-needed"]
STATUS_TEXT = {"draft": "Draft. Not approved yet.", "approved": "Approved.",
               "approved-with-conditions": "Approved with conditions.", "changes-needed": "Changes needed."}
MAX_DIAGRAMS = 4
LONG_SENTENCE = 25
BANNED = {
    "utilize": "use", "utilise": "use", "leverage": "use", "facilitate": "help", "robust": "say what it survives",
    "seamless": "say what works", "seamlessly": "say what works", "e.g.": "for example", "i.e.": "that is",
    "etc.": "list them, or say the list is partial", "in order to": "to", "going forward": "from now on",
}
PLACEHOLDER = re.compile(r"\bTBD\b|\bTODO\b|\blorem\b|\{\{|<fill|\bXXX\b", re.I)
DASHES = re.compile("[–—]")


def block_re(name):
    return re.compile(r"(<!-- chopchop:%s -->)(.*?)(<!-- /chopchop:%s -->)" % (name, name), re.S)


def fill(text, name, content):
    """Replace a generated block's content. Returns (text, found)."""
    pat = block_re(name)
    if not pat.search(text):
        return text, False
    return pat.sub(lambda m: m.group(1) + "\n" + content.strip("\n") + "\n" + m.group(3), text, count=1), True


def without_blocks(text):
    for name in BLOCKS:
        text = block_re(name).sub("", text)
    return text


def sections(body):
    """[(number or None, title, text)] for every ## heading, in order."""
    heads = list(re.finditer(r"(?m)^## (?:(\d+)\. )?(.+?)\s*$", body))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        out.append((int(m.group(1)) if m.group(1) else None, m.group(2).strip(), body[m.end():end].strip("\n")))
    return out


def section_text(body, n):
    return next((t for num, _, t in sections(body) if num == n), "")


def appendix(body):
    return next((t for num, title, t in sections(body) if num is None and title == APPENDIX), "")


def _prose(text):
    """Text a person reads: no comments, code, tables, headings or generated blocks."""
    text = re.sub(r"(?s)<!--.*?-->", "", without_blocks(text))
    text = re.sub(r"(?ms)^```.*?^```", "", text)
    lines = [l for l in text.split("\n") if not l.lstrip().startswith(("|", "#"))]
    return "\n".join(lines)


def words(text):
    return len(re.findall(r"[A-Za-z0-9][\w'.-]*", _prose(text)))


def long_sentences(text, limit=LONG_SENTENCE):
    out = []
    flat = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*([-*+]|\d+[.)])\s+", "\n", _prose(text)))
    for s in re.split(r"(?<=[.!?])\s+|\n", flat):
        s = re.sub(r"`[^`]*`", "x", s).strip()
        n = len(s.split())
        if n > limit:
            out.append("%d words: %s..." % (n, " ".join(s.split()[:8])))
    return out


def ask_line(body):
    m = re.search(r"\*\*The ask:\*\*[ \t]*(\S.*)", body)
    return m.group(1).strip() if m else ""


def size_line(body):
    m = re.search(r"\*\*Size:\*\*[ \t]*(\S.*)", body)
    return m.group(1).strip() if m else ""


def talk(text):
    m = re.search(r"(?s)<!--\s*talk:\s*(.*?)-->", text)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# --------------------------------------------------------------------------- lint


def lint(body, size, story_ids=()):
    """Returns (errors, warnings) for design.md (without its front matter)."""
    errors, warnings = [], []
    found = [(n, t) for n, t, _ in sections(body) if n is not None]
    want = list(enumerate(HEADINGS, 1))
    if found != want:
        missing = [("%d. %s" % w) for w in want if w not in found]
        extra = [("%d. %s" % f) for f in found if f not in want]
        if missing or extra:
            errors.append("headings must be the 12 fixed ones, in order. Missing: %s. Not expected: %s."
                          % (", ".join(missing) or "none", ", ".join(extra) or "none"))
        else:
            errors.append("the 12 headings are out of order")
    for n, title, text in sections(body):
        if n is None:
            continue
        clean = _prose(text).strip() or re.sub(r"(?s)<!--.*?-->", "", without_blocks(text)).strip()
        if n not in BLOCKS.values() and not clean:
            errors.append('section %d (%s) is empty. Write "None." if there is nothing to say.' % (n, title))
    for name in BLOCKS:
        if not block_re(name).search(body):
            errors.append("the generated block chopchop:%s is missing from section %d. Put back:\n"
                          "<!-- chopchop:%s -->\n<!-- /chopchop:%s -->" % (name, BLOCKS[name], name, name))
    if not ask_line(section_text(body, 1)):
        errors.append('section 1 needs a line "**The ask:** ...": the one decision the lead makes')
    def blank(m):
        return "\n" * m.group(0).count("\n")
    plain = body
    for name in BLOCKS:
        plain = block_re(name).sub(blank, plain)
    plain = re.sub(r"(?ms)^```.*?^```", blank, plain)
    plain = re.sub(r"(?s)<!--.*?-->", blank, plain)
    for i, line in enumerate(plain.split("\n"), 1):
        if PLACEHOLDER.search(line):
            errors.append("line %d still has placeholder text: %s" % (i, line.strip()[:60]))
    for i, line in enumerate(body.split("\n"), 1):
        if DASHES.search(line):
            errors.append("line %d has a long dash. Use a comma, a full stop or a colon." % i)
    prose_low = _prose(body).lower()
    for word, use in BANNED.items():
        if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(word), prose_low):
            warnings.append('"%s": use "%s"' % (word, use))
    for s in long_sentences(body.split("\n## " + APPENDIX)[0]):
        warnings.append("long sentence, %s" % s)
    main = body.split("\n## " + APPENDIX)[0]
    budget = BUDGETS.get(size or "medium", BUDGETS["medium"])
    n_words = words(main)
    if n_words > budget:
        warnings.append("%d words. The budget for a %s feature is %d. Cut, or move detail to the spec."
                        % (n_words, size or "medium", budget))
    own = len(re.findall(r"(?m)^```mermaid", without_blocks(body)))
    if own:
        warnings.append("%d Mermaid diagram(s) written by hand. Draw diagrams with the diagram skill, so the page and design.md agree." % own)
    if own + 2 > MAX_DIAGRAMS:
        warnings.append("%d diagrams. At most %d in design.md." % (own + 2, MAX_DIAGRAMS))
    for m in re.finditer(r"(?ms)^```mermaid\n(flowchart|graph).*?^```", without_blocks(body)):
        for lab in re.findall(r"\[([^\]]*)\]", m.group(0)):
            if re.search(r"[()/\"]", lab.strip("()")):
                warnings.append("Mermaid label '%s' has ( ) / or quotes. Use plain words." % lab)
    why = section_text(body, 3)
    if why and "None." not in why and "@" not in why:
        warnings.append("section 3 (Why) has no citation. Facts about today's code need one.")
    scope = section_text(body, 4)
    for sid in story_ids:
        if not re.search(r"(?<![\w-])%s(?!\d)" % re.escape(sid), scope):
            errors.append("story %s is not in section 4 (Scope). Put it in scope or out of scope." % sid)
    no_talk = [str(n) for n, _, text in sections(body) if n and n not in (2, 8) and not talk(text)]
    if no_talk:
        warnings.append("no speaker notes (a talk comment) in section %s. The slides then use only the section's own points."
                        % ", ".join(no_talk))
    if not appendix(body).strip():
        warnings.append('no "## Likely questions" yet. The mock lead review fills it.')
    return errors, warnings


# --------------------------------------------------------------------------- slides


def _plain(s):
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: m.group(1) or m.group(2), s)
    s = re.sub(r"(?<!\w)[*_]([^*_]+)[*_](?!\w)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def bullets(text, limit=5, width=140):
    """The first few points of a section, as plain lines."""
    text = re.sub(r"(?s)<!--.*?-->", "", without_blocks(text))
    text = re.sub(r"(?ms)^```.*?^```", "", text)
    out = []
    rows = [l for l in text.split("\n") if l.strip().startswith("|") and not re.match(r"^\s*\|?\s*:?-{3,}", l)]
    items = [m.group(1) for m in re.finditer(r"(?m)^\s{0,1}(?:[-*+]|\d+[.)])\s+(.+)$", text)]
    if items:
        out = items
    elif len(rows) > 1:
        for r in rows[1:]:
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            out.append(": ".join(c for c in cells[:2] if c))
    else:
        para = " ".join(l.strip() for l in text.split("\n") if l.strip() and not l.startswith("#"))
        out = [s for s in re.split(r"(?<=[.!?])\s+", para) if s]
    clean = []
    for b in out[:limit]:
        b = _plain(b)
        clean.append(b if len(b) <= width else b[:width - 1].rsplit(" ", 1)[0] + "…")
    return [b for b in clean if b]


def first_diagram(text):
    m = re.search(r"(?ms)^```mermaid\n(.*?)^```", without_blocks(text))
    return m.group(1).strip() if m else ""


def questions(body):
    """[(question, answer)] from the Likely questions appendix (### headings)."""
    text = appendix(body)
    out = []
    parts = re.split(r"(?m)^### +", text)
    for p in parts[1:]:
        q, _, a = p.partition("\n")
        out.append((q.strip(), _plain(re.sub(r"(?s)<!--.*?-->", "", a)).strip()))
    return out
