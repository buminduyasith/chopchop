"""Convert tracker rich text to Markdown.

- adf_to_md:  Atlassian Document Format (Jira Cloud REST v3, JSON)
- wiki_to_md: Jira wiki markup (Jira Server / Data Center REST v2, text)
- demote_headings: push Markdown headings down so they nest under ours
"""

import re
from datetime import datetime, timezone

# --------------------------------------------------------------------------- ADF


def adf_to_md(doc):
    if not doc:
        return ""
    if isinstance(doc, str):
        return doc.strip()
    if not isinstance(doc, dict):
        return str(doc)
    if doc.get("type") == "doc" or "content" in doc:
        body = _blocks(doc.get("content") or [])
    else:
        body = _block(doc) or ""
    return _tidy(body)


def _blocks(nodes, sep="\n\n"):
    parts = []
    for node in nodes:
        text = _block(node)
        if text:
            parts.append(text)
    return sep.join(parts)


def _block(node):
    t = node.get("type")
    content = node.get("content") or []
    attrs = node.get("attrs") or {}

    if t == "paragraph":
        return _inline(content).strip()
    if t == "heading":
        level = min(max(int(attrs.get("level") or 1), 1), 6)
        return "#" * level + " " + _inline(content).strip()
    if t == "bulletList":
        return _list(content, ordered=False)
    if t == "orderedList":
        return _list(content, ordered=True, start=int(attrs.get("order") or 1))
    if t == "taskList":
        return _task_list(content)
    if t == "decisionList":
        return "\n".join("- Decision: " + _inline(i.get("content") or []).strip() for i in content)
    if t == "codeBlock":
        code = "".join(c.get("text", "") for c in content)
        return "```" + (attrs.get("language") or "") + "\n" + code.rstrip("\n") + "\n```"
    if t == "blockquote":
        return _quote(_blocks(content))
    if t == "panel":
        kind = (attrs.get("panelType") or "note").capitalize()
        return _quote("**%s:** " % kind + _blocks(content))
    if t == "rule":
        return "---"
    if t == "table":
        return _table(content)
    if t in ("mediaSingle", "mediaGroup"):
        return " ".join(filter(None, (_media(m) for m in content)))
    if t == "media":
        return _media(node)
    if t in ("expand", "nestedExpand"):
        title = attrs.get("title") or "Details"
        return "**%s**\n\n%s" % (title, _blocks(content))
    if t in ("blockCard", "embedCard"):
        return "<%s>" % attrs.get("url") if attrs.get("url") else ""
    if t in ("layoutSection", "layoutColumn", "bodiedExtension", "extensionFrame"):
        return _blocks(content)
    if t in ("extension", "inlineExtension"):
        return ""
    # Unknown node: keep whatever text it has.
    if content:
        if all(c.get("type") in _INLINE_TYPES for c in content):
            return _inline(content).strip()
        return _blocks(content)
    return node.get("text", "")


def _list(items, ordered, start=1):
    lines = []
    for i, item in enumerate(items):
        marker = ("%d. " % (start + i)) if ordered else "- "
        body = _blocks(item.get("content") or [], sep="\n")
        lines.append(_hang(marker, body))
    return "\n".join(lines)


def _task_list(items):
    lines = []
    for item in items:
        if item.get("type") == "taskList":
            lines.append(_indent(_task_list(item.get("content") or []), "  "))
            continue
        done = (item.get("attrs") or {}).get("state") == "DONE"
        lines.append(_hang("- [x] " if done else "- [ ] ", _inline(item.get("content") or []).strip()))
    return "\n".join(lines)


def _hang(marker, body):
    rows = body.split("\n") if body else [""]
    pad = " " * len(marker)
    out = [marker + rows[0]]
    out.extend((pad + r) if r.strip() else "" for r in rows[1:])
    return "\n".join(out)


def _indent(text, pad):
    return "\n".join((pad + r) if r.strip() else r for r in text.split("\n"))


def _quote(text):
    return "\n".join(("> " + r) if r else ">" for r in text.split("\n"))


def _table(rows):
    parsed = []
    for row in rows:
        cells, header = [], False
        for cell in row.get("content") or []:
            if cell.get("type") == "tableHeader":
                header = True
            text = _blocks(cell.get("content") or [], sep=" ")
            text = text.replace("\n", " <br> ").replace("|", "\\|").strip()
            cells.append(text)
        parsed.append((cells, header))
    if not parsed:
        return ""
    width = max(len(c) for c, _ in parsed) or 1

    def fmt(cells):
        cells = cells + [""] * (width - len(cells))
        return "| " + " | ".join(cells) + " |"

    out = []
    first, is_header = parsed[0]
    body = parsed[1:] if is_header else parsed
    out.append(fmt(first if is_header else [""] * width))
    out.append("|" + "|".join([" --- "] * width) + "|")
    out.extend(fmt(c) for c, _ in body)
    return "\n".join(out)


def _media(node):
    attrs = node.get("attrs") or {}
    name = attrs.get("alt") or attrs.get("filename") or attrs.get("id") or "file"
    if attrs.get("type") == "external" and attrs.get("url"):
        return "![%s](%s)" % (name, attrs["url"])
    return "[attachment: %s]" % name


_INLINE_TYPES = {"text", "hardBreak", "mention", "emoji", "inlineCard", "status", "date",
                 "placeholder", "mediaInline", "inlineExtension"}


def _inline(nodes):
    out = []
    for node in nodes:
        t = node.get("type")
        attrs = node.get("attrs") or {}
        if t == "text":
            out.append(_marks(node.get("text", ""), node.get("marks") or []))
        elif t == "hardBreak":
            out.append("  \n")
        elif t == "mention":
            out.append("@" + str(attrs.get("text") or attrs.get("id") or "").lstrip("@"))
        elif t == "emoji":
            out.append(attrs.get("text") or attrs.get("shortName") or "")
        elif t == "inlineCard":
            out.append("<%s>" % attrs["url"] if attrs.get("url") else "")
        elif t == "status":
            out.append("[%s]" % (attrs.get("text") or ""))
        elif t == "date":
            out.append(_date(attrs.get("timestamp")))
        elif t == "mediaInline":
            out.append(_media(node))
        elif t in ("placeholder", "inlineExtension"):
            continue
        elif node.get("content"):
            out.append(_inline(node["content"]))
        elif node.get("text"):
            out.append(node["text"])
    return "".join(out)


def _marks(text, marks):
    if not text:
        return ""
    kinds = {m.get("type"): (m.get("attrs") or {}) for m in marks}
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    core = text.strip()
    if not core:
        return text
    if "code" in kinds:
        tick = "``" if "`" in core else "`"
        core = tick + core + tick
    if "strike" in kinds:
        core = "~~" + core + "~~"
    if "em" in kinds:
        core = "*" + core + "*"
    if "strong" in kinds:
        core = "**" + core + "**"
    if "link" in kinds and kinds["link"].get("href"):
        core = "[%s](%s)" % (core, kinds["link"]["href"])
    return lead + core + trail


def _date(ts):
    try:
        return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return str(ts or "")


# --------------------------------------------------------------------------- wiki markup

_WIKI_HEADING = re.compile(r"^h([1-6])\.\s+(.*)$")
_WIKI_LIST = re.compile(r"^([*#-]+)\s+(.*)$")
_WIKI_CODE = re.compile(r"^\{(code|noformat)(?::([^}|]*))?[^}]*\}(.*)$")


def wiki_to_md(text):
    if not text:
        return ""
    if not isinstance(text, str):
        return adf_to_md(text)
    out = []
    in_code = False
    in_quote = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if in_code:
            if re.search(r"\{(code|noformat)\}\s*$", line):
                before = re.sub(r"\{(code|noformat)\}\s*$", "", line)
                if before:
                    out.append(before)
                out.append("```")
                in_code = False
            else:
                out.append(raw)
            continue
        m = _WIKI_CODE.match(line.strip())
        if m:
            lang = (m.group(2) or "").strip() if m.group(1) == "code" else ""
            out.append("```" + ("" if "=" in lang else lang))
            rest = m.group(3)
            if re.search(r"\{(code|noformat)\}\s*$", rest):
                out.append(re.sub(r"\{(code|noformat)\}\s*$", "", rest))
                out.append("```")
            else:
                if rest:
                    out.append(rest)
                in_code = True
            continue
        if line.strip() == "{quote}":
            in_quote = not in_quote
            continue
        prefix = "> " if in_quote else ""
        h = _WIKI_HEADING.match(line)
        if h:
            out.append(prefix + "#" * int(h.group(1)) + " " + _wiki_inline(h.group(2)))
            continue
        if line.startswith("bq. "):
            out.append("> " + _wiki_inline(line[4:]))
            continue
        if line.strip() == "----":
            out.append(prefix + "---")
            continue
        if line.startswith("||"):
            cells = [c.strip() for c in line.strip().strip("|").split("||")]
            out.append(prefix + "| " + " | ".join(_wiki_inline(c) for c in cells) + " |")
            out.append(prefix + "|" + "|".join([" --- "] * len(cells)) + "|")
            continue
        if line.startswith("|") and line.rstrip().endswith("|"):
            cells = [c.strip() for c in line.strip()[1:-1].split("|")]
            out.append(prefix + "| " + " | ".join(_wiki_inline(c) for c in cells) + " |")
            continue
        li = _WIKI_LIST.match(line)
        if li and not (li.group(1) == "-" and li.group(2).startswith("-")):
            depth = len(li.group(1))
            marker = "1. " if li.group(1)[-1] == "#" else "- "
            out.append(prefix + "   " * (depth - 1) + marker + _wiki_inline(li.group(2)))
            continue
        out.append(prefix + _wiki_inline(line))
    if in_code:
        out.append("```")
    return _tidy("\n".join(out))


def _wiki_inline(s):
    code_spans = []

    def keep_code(m):
        code_spans.append(m.group(1))
        return "\x00%d\x00" % (len(code_spans) - 1)

    s = re.sub(r"\{\{(.+?)\}\}", keep_code, s)
    s = re.sub(r"\[~([^\]]+)\]", r"@\1", s)
    s = re.sub(r"\[([^|\]]+)\|([^\]]+)\]", r"[\1](\2)", s)
    s = re.sub(r"\[((?:https?|mailto):[^\]\s]+)\]", r"<\1>", s)
    s = re.sub(r"!([^!\s|][^!|]*?)(?:\|[^!]*)?!", r"[attachment: \1]", s)
    s = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]*?\S)\*(?![\w*])", r"**\1**", s)
    s = re.sub(r"(?<![\w_])_(?=\S)([^_\n]*?\S)_(?![\w_])", r"*\1*", s)
    s = re.sub(r"(?<![\w-])-(?=[^\s-])([^-\n]*?[^\s-])-(?![\w-])", r"~~\1~~", s)
    s = re.sub(r"\{color[^}]*\}", "", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: "`%s`" % code_spans[int(m.group(1))], s)


# --------------------------------------------------------------------------- helpers


def demote_headings(md, by):
    """Add `by` levels to every heading outside code fences (max level 6)."""
    if not md or by <= 0:
        return md or ""
    out, fence = [], False
    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence:
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                line = "#" * min(len(m.group(1)) + by, 6) + " " + m.group(2)
        out.append(line)
    return "\n".join(out)


def _tidy(text):
    text = re.sub(r"(?m)^[ \t]+$", "", text)  # blank-looking lines (keeps "  \n" hard breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
