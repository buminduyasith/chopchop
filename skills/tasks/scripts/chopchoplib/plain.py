"""Simple English and the Summary rule, shared by every file chopchop writes.

Two rules for every Markdown file:

1. It starts with a short Summary, so a busy reader can stop there.
2. It uses simple English: short sentences, everyday words, no long dashes.

design.md and spec.md have their own, stricter checks. They call into here for the shared parts.
"""

import re

LONG_SENTENCE = 25
SUMMARY_MAX_WORDS = 120
SUMMARY_WITHIN_LINES = 60

BANNED = {
    "utilize": "use", "utilise": "use", "leverage": "use", "facilitate": "help", "robust": "say what it survives",
    "seamless": "say what works", "seamlessly": "say what works", "e.g.": "for example", "i.e.": "that is",
    "etc.": "list them, or say the list is partial", "in order to": "to", "going forward": "from now on",
    "prior to": "before", "subsequently": "then", "commence": "start", "terminate": "end", "aforementioned": "this",
    "holistic": "whole", "synergy": "say what works together", "paradigm": "way", "endeavor": "try",
    "endeavour": "try", "ascertain": "find out", "with regard to": "about", "in the event that": "if",
    "at this point in time": "now", "due to the fact that": "because",
}
# TBD, TODO and XXX only in capitals: "todo" is also a task status and an everyday word.
PLACEHOLDER = re.compile(r"\bTBD\b|\bTODO\b|\b[Ll]orem ipsum\b|\{\{|<fill|\bXXX\b")
DASHES = re.compile("[\u2013\u2014]")
# A fence with no language, or text/txt/plain, around words that are not code: a grey box nobody wants to read.
PLAIN_FENCES = ("", "text", "txt", "plain", "plaintext")


def text_boxes(body):
    """Line numbers of code blocks that hold plain text instead of code."""
    out, inside, ticks = [], False, ""
    for n, line in enumerate(body.split("\n"), 1):
        m = re.match(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)", line)
        if not m:
            continue
        if not inside:
            inside, ticks = True, m.group(1)
            if m.group(2).lower() in PLAIN_FENCES:
                out.append(n)
        elif m.group(1).startswith(ticks[0]) and len(m.group(1)) >= len(ticks) and not m.group(2):
            inside = False
    return out
SUMMARY_HEAD = re.compile(r"(?m)^(#{1,3})[ \t]+(?:\d+\.[ \t]+)?Summary\b[^\n]*$", re.I)
ANY_HEAD = re.compile(r"(?m)^#{1,6}[ \t]+\S")


def strip_front_matter(text):
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[end + 5:]
    return text


def prose(text):
    """Text a person reads: no comments, code blocks, tables or headings."""
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    text = re.sub(r"(?ms)^```.*?^```", "", text)
    lines = [l for l in text.split("\n") if not l.lstrip().startswith(("|", "#"))]
    return "\n".join(lines)


def words(text):
    return len(re.findall(r"[A-Za-z0-9][\w'.-]*", prose(text)))


def long_sentences(text, limit=LONG_SENTENCE):
    out = []
    flat = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*([-*+]|\d+[.)])\s+", "\n", prose(text)))
    for s in re.split(r"(?<=[.!?])\s+|\n", flat):
        s = re.sub(r"`[^`]*`", "x", s)
        s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s).strip()
        n = len(s.split())
        if n > limit:
            out.append("%d words: %s..." % (n, " ".join(s.split()[:8])))
    return out


# --------------------------------------------------------------------------- summary


def summary(text):
    """The text under the Summary heading, or None when the file has no Summary near its top."""
    body = strip_front_matter(text)
    m = SUMMARY_HEAD.search(body)
    if not m or body.count("\n", 0, m.start()) > SUMMARY_WITHIN_LINES:
        return None
    rest = body[m.end():]
    nxt = ANY_HEAD.search(rest)
    block = rest[:nxt.start()] if nxt else rest
    block = re.sub(r"(?s)<!--.*?-->", "", block)
    return block.strip()


def has_summary(text):
    s = summary(text)
    return bool(s and s.strip())


def summary_points(text, limit=4):
    """A few plain lines from the Summary, for a card or a list."""
    s = summary(text)
    if not s:
        return []
    out = []
    for line in s.split("\n"):
        line = line.strip()
        if not line or line.startswith(("|", "```", "<!--")):
            continue
        line = re.sub(r"^([-*+]|\d+[.)])\s+", "", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        if line:
            out.append(line)
        if len(out) >= limit:
            break
    return out


def summary_block(points):
    """Render a Summary section. points: a list of lines, or (label, text) pairs."""
    lines = ["## Summary", ""]
    for p in points:
        if isinstance(p, (tuple, list)) and len(p) == 2:
            if p[1] not in (None, ""):
                lines.append("- **%s:** %s" % (p[0], p[1]))
        elif p:
            lines.append("- %s" % p)
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- lint


def lint(text, need_summary=True, limit=LONG_SENTENCE, name="the file"):
    """Returns (errors, warnings) for one Markdown file. Errors block, warnings do not."""
    errors, warnings = [], []
    body = strip_front_matter(text)
    if need_summary:
        s = summary(text)
        if s is None:
            errors.append('%s has no "## Summary" near the top. Add one: what, why, where it stands.' % name)
        elif not s.strip():
            errors.append("%s has an empty Summary. Write 2 to 5 short lines." % name)
        elif words(s) > SUMMARY_MAX_WORDS:
            warnings.append("the Summary is %d words. Keep it under %d." % (words(s), SUMMARY_MAX_WORDS))

    def blank(m):
        return "\n" * m.group(0).count("\n")
    plain = re.sub(r"(?ms)^```.*?^```", blank, body)
    plain = re.sub(r"(?s)<!--.*?-->", blank, plain)
    for i, line in enumerate(plain.split("\n"), 1):
        if PLACEHOLDER.search(line):
            errors.append("line %d still has placeholder text: %s" % (i, line.strip()[:60]))
        if DASHES.search(line):
            errors.append("line %d has a long dash. Use a comma, a full stop or a colon." % i)
    for line in text_boxes(body):
        warnings.append("line %d is a plain text box. Use a list, a table or a quote. Only code goes in a code block, "
                        "with its language (```js, ```bash)." % line)
    low = prose(body).lower()
    for word, use in BANNED.items():
        if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(word), low):
            warnings.append('"%s": use "%s"' % (word, use))
    for s in long_sentences(body, limit):
        warnings.append("long sentence, %s" % s)
    return errors, warnings


def lint_text(text, limit=LONG_SENTENCE):
    """Warnings for a short piece of text (a question, a reply, one field). No Summary needed."""
    return lint(text, need_summary=False, limit=limit)
