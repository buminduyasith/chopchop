"""Markdown to HTML for the dashboard. Standard library only.

The files are data, never markup to trust. So every piece of text is escaped, raw HTML never
passes through, and a link is kept only when it is http, https, mailto or a link the caller
resolves. HTML comments are dropped.

It covers what chopchop writes and what people add by hand: headings, paragraphs, nested lists,
task lists, tables, fenced code, Mermaid blocks, quotes, rules, bold, italics, strike, inline
code and links.

  render(text)   -> {"html": ..., "toc": [{"level", "id", "text"}], "title": ...}
  convert(text)  -> the HTML only
"""

import html
import re

MAX_DEPTH = 12  # quotes in quotes, lists in lists: deeper than this is shown as plain text
ID_PREFIX = "h-"

FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*(.*?)[ \t]*$")
FENCE_ANY = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*(.*?)[ \t]*$")
HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])(?:( +)(.*))?$")
QUOTE = re.compile(r"^ {0,3}>")
TABLE_SEP = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
TASK = re.compile(r"^\[([ xX])\](?:[ \t]+(.*))?$")
SUMMARY = re.compile(r"^(?:\d+\.\s+)?Summary\b", re.I)

_NEXT = re.compile(r"`+|<!--")
_TOKEN = re.compile("\x00(\\d+)\x00")
_CODE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>~])")
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^\s<>]+)>")
_URL_PART = r"(<[^<>\n]*>|[^\s()<>]*(?:\([^\s()<>]*\)[^\s()<>]*)*)"
_TITLE_PART = r"(?:\s+(?:\"[^\"]*\"|'[^']*'))?"
_LABEL_PART = r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]"
_IMAGE = re.compile(r"!" + _LABEL_PART + r"\(\s*" + _URL_PART + _TITLE_PART + r"\s*\)")
_LINK = re.compile(_LABEL_PART + r"\(\s*" + _URL_PART + _TITLE_PART + r"\s*\)")
_BARE = re.compile(r"(?<![\w@/.\-\"'=])https?://[^\s<>\x00]+")
_STRONG_A = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_STRONG_U = re.compile(r"(?<![A-Za-z0-9_])__(?=\S)(.+?)(?<=\S)__(?![A-Za-z0-9_])", re.S)
_EM_A = re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![*\w])", re.S)
_EM_U = re.compile(r"(?<![A-Za-z0-9_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![A-Za-z0-9_])", re.S)
_DEL = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)
_BREAK = re.compile(r"(?: {2,}|\\)\n")
_ENTITY = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
_CONTROL = re.compile(r"[\x00-\x20\x7f]")


def esc(s):
    return html.escape(s, quote=True)


class _Ctx:
    def __init__(self, link):
        self.link = link      # called with a relative link, returns the href to use or None
        self.toc = []
        self.ids = {}

    def heading_id(self, text):
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
        n = self.ids.get(slug, 0) + 1
        self.ids[slug] = n
        return ID_PREFIX + (slug if n == 1 else "%s-%d" % (slug, n))


# --------------------------------------------------------------------------- comments


def strip_comments(text):
    """Drop <!-- ... --> everywhere except inside fenced code and inline code.

    A comment that never closes is kept as text, so a stray "<!--" cannot hide the rest of a file."""
    out = []
    i, n = 0, len(text)
    fence = None
    while i < n:
        eol = text.find("\n", i)
        if eol < 0:
            eol = n
        line = text[i:eol]
        if fence:
            if re.match(r"^[ \t]*%s{%d,}[ \t]*$" % (re.escape(fence[0]), len(fence)), line):
                fence = None
            out.append(line)
            i = eol + 1
            continue
        m = FENCE_ANY.match(line)
        if m and not ("`" in m.group(2) and m.group(1)[0] == "`"):
            fence = m.group(1)
            out.append(line)
            i = eol + 1
            continue
        buf = []
        j = i
        while j < eol:
            m = _NEXT.search(text, j, eol)
            if not m:
                buf.append(text[j:eol])
                break
            buf.append(text[j:m.start()])
            if m.group(0) == "<!--":
                end = text.find("-->", m.end())
                if end < 0:
                    buf.append(text[m.start():eol])
                    break
                j = end + 3
                if j > eol:  # the comment ran over several lines: carry on from where it ends
                    eol = text.find("\n", j)
                    if eol < 0:
                        eol = n
                continue
            run = m.group(0)
            close = re.compile(r"(?<!`)%s(?!`)" % re.escape(run)).search(text, m.end(), eol)
            if close:
                buf.append(text[m.start():close.end()])
                j = close.end()
            else:
                buf.append(run)
                j = m.end()
        out.append("".join(buf))
        i = eol + 1
    return "\n".join(out)


# --------------------------------------------------------------------------- inline


def _href(url, ctx):
    """(kind, href) for a link target. kind is ext, mail, anchor, page or None (no link)."""
    url = _CONTROL.sub("", html.unescape(url or ""))
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1]
    if not url:
        return None, None
    m = _SCHEME.match(url)
    if m:
        scheme = m.group(1).lower()
        if scheme in ("http", "https"):
            return "ext", url
        if scheme == "mailto":
            return "mail", url
        return None, None
    if url.startswith("//"):
        return "ext", "https:" + url
    if url.startswith("#"):
        slug = re.sub(r"[^a-z0-9]+", "-", url[1:].lower()).strip("-")
        return ("anchor", slug) if slug else (None, None)
    if ctx.link:
        try:
            target = ctx.link(url)
        except Exception:  # noqa: BLE001  a broken resolver must not break the page
            target = None
        if target:
            return "page", target
    return None, None


def _anchor(url, inner, ctx):
    kind, href = _href(url, ctx)
    if kind == "ext":
        return '<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (esc(href), inner)
    if kind == "mail":
        return '<a href="%s">%s</a>' % (esc(href), inner)
    if kind == "anchor":
        return '<a href="#" data-anchor="%s%s">%s</a>' % (ID_PREFIX, esc(href), inner)
    if kind == "page":
        return '<a href="%s" data-page="1">%s</a>' % (esc(href), inner)
    return inner


def _trim_url(url):
    """A bare link ends before the sentence's own punctuation."""
    tail = ""
    while url and url[-1] in ".,;:!?'\"*_~":
        tail = url[-1] + tail
        url = url[:-1]
    while url.endswith(")") and url.count(")") > url.count("("):
        tail = ")" + tail
        url = url[:-1]
    return url, tail


def _inline(text, ctx, stash=None, links=True):
    top = stash is None
    if top:
        stash = []

    def keep(s):
        stash.append(s)
        return "\x00%d\x00" % (len(stash) - 1)

    def code(m):
        body = m.group(2).replace("\n", " ")
        if len(body) > 2 and body[0] == " " and body[-1] == " " and body.strip():
            body = body[1:-1]
        return keep("<code>%s</code>" % esc(body))

    def bare(m):
        url, tail = _trim_url(m.group(0))
        return keep(_anchor(url, esc(url), ctx)) + tail

    def image(m):
        label = m.group(1).strip() or "image"
        kind, href = _href(m.group(2), ctx)
        inner = '<span class="img-ref">%s</span>' % esc("Image: %s" % label)
        if kind == "ext":
            return keep('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (esc(href), inner))
        return keep(inner)

    def link(m):
        inner = _inline(m.group(1), ctx, stash, links=False)
        return keep(_anchor(m.group(2), inner, ctx))

    text = _CODE.sub(code, text)
    text = _ESCAPE.sub(lambda m: keep(esc(m.group(1))), text)
    if links:
        text = _AUTOLINK.sub(lambda m: keep(_anchor(m.group(1), esc(m.group(1)), ctx)), text)
        text = _IMAGE.sub(image, text)
        text = _LINK.sub(link, text)
        text = _BARE.sub(bare, text)
    text = esc(_ENTITY.sub(lambda m: html.unescape(m.group(0)).replace("\x00", ""), text))
    text = _STRONG_A.sub(r"<strong>\1</strong>", text)
    text = _STRONG_U.sub(r"<strong>\1</strong>", text)
    text = _EM_A.sub(r"<em>\1</em>", text)
    text = _EM_U.sub(r"<em>\1</em>", text)
    text = _DEL.sub(r"<del>\1</del>", text)
    text = _BREAK.sub("<br>\n", text)
    if top:
        for _ in range(MAX_DEPTH * 4):
            if "\x00" not in text:
                break
            text = _TOKEN.sub(lambda m: stash[int(m.group(1))] if int(m.group(1)) < len(stash) else "", text)
        text = text.replace("\x00", "")
    return text


def plain_text(inline_html):
    return html.unescape(re.sub(r"<[^>]+>", "", inline_html)).strip()


# --------------------------------------------------------------------------- tables


def _cells(line):
    """Split a table row on | . A | inside inline code or after a backslash is text."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    cells, cur, i, n = [], [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if ch == "`":
            j = i
            while j < n and s[j] == "`":
                j += 1
            run = s[i:j]
            close = re.compile(r"(?<!`)%s(?!`)" % re.escape(run)).search(s, j)
            if close:
                cur.append(s[i:close.end()])
                i = close.end()
            else:
                cur.append(run)
                i = j
            continue
        if ch == "|":
            cells.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    last = "".join(cur).strip()
    if last or not cells:
        cells.append(last)
    return cells


def _align(cell):
    cell = cell.strip()
    if cell.startswith(":") and cell.endswith(":"):
        return "c"
    if cell.endswith(":"):
        return "r"
    return ""


def _table_head(lines, i):
    """(head cells, alignments) when a table starts at line i, else None."""
    if i + 1 >= len(lines) or "|" not in lines[i] or not TABLE_SEP.match(lines[i + 1]):
        return None
    head, sep = _cells(lines[i]), _cells(lines[i + 1])
    if len(head) != len(sep) or not all(re.match(r"^:?-+:?$", c) for c in sep):
        return None
    return head, [_align(c) for c in sep]


def _table(lines, i, ctx):
    """Returns (html, next index) when a table starts at line i, else None."""
    found = _table_head(lines, i)
    if not found:
        return None
    head, aligns = found

    def cell(tag, text, k):
        cls = ' class="al-%s"' % aligns[k] if k < len(aligns) and aligns[k] else ""
        return "<%s%s>%s</%s>" % (tag, cls, _inline(text, ctx), tag)

    out = ['<div class="tbl"><table><thead><tr>%s</tr></thead><tbody>'
           % "".join(cell("th", c, k) for k, c in enumerate(head))]
    i += 2
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        row = _cells(lines[i])
        row = (row + [""] * len(head))[:len(head)]
        out.append("<tr>%s</tr>" % "".join(cell("td", c, k) for k, c in enumerate(row)))
        i += 1
    out.append("</tbody></table></div>")
    return "".join(out), i


# --------------------------------------------------------------------------- blocks


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _starts_block(lines, i):
    line = lines[i]
    return bool(FENCE.match(line) or HEADING.match(line) or RULE.match(line) or QUOTE.match(line)
                or ITEM.match(line) or _table_head(lines, i))


def _same_list(m, ordered, mark):
    kind = m.group(2)
    return (kind[0].isdigit() == ordered) and (kind[-1] == mark)


def _list(lines, i, ctx, depth):
    """Returns (html, next index) for the list that starts at line i."""
    first = ITEM.match(lines[i])
    base = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    mark = first.group(2)[-1]
    start = int(first.group(2)[:-1]) if ordered else 1
    items, loose, n = [], False, len(lines)
    while i < n:
        m = ITEM.match(lines[i])
        if not m or len(m.group(1)) < base or not _same_list(m, ordered, mark):
            break
        own = len(m.group(1))
        gap = len(m.group(3) or "")
        content = own + len(m.group(2)) + (gap if 1 <= gap <= 4 else 1)
        body = [m.group(4) or ""]
        i += 1
        blanks, spread = 0, False
        while i < n:
            line = lines[i]
            if not line.strip():
                blanks += 1
                i += 1
                continue
            ind = _indent(line)
            child = ITEM.match(line) and ind > own
            if ind >= content or child:
                if blanks:
                    spread = True
                    body.extend([""] * blanks)
                    blanks = 0
                body.append(line[min(ind, content):])
                i += 1
                continue
            if not blanks and not _starts_block(lines, i):
                body.append(line.strip())  # a lazy line: it carries on the paragraph above
                i += 1
                continue
            break
        if blanks and i < n:
            nxt = ITEM.match(lines[i])
            if nxt and len(nxt.group(1)) >= base and _same_list(nxt, ordered, mark):
                loose = True
        items.append((body, spread))

    out = []
    for body, spread in items:
        box = TASK.match(body[0])
        if box:
            body = [box.group(2) or ""] + body[1:]
        blocks = _blocks(body, ctx, depth + 1)
        tight = not loose and not (spread and sum(1 for b in blocks if b[0] == "p") > 1)
        inner = _emit(blocks, tight)
        if box:
            check = '<input type="checkbox" disabled%s> ' % (" checked" if box.group(1) != " " else "")
            inner = inner[:3] + check + inner[3:] if inner.startswith("<p>") else check + inner
            out.append('<li class="task">%s</li>' % inner)
        else:
            out.append("<li>%s</li>" % inner)
    tag = "ol" if ordered else "ul"
    attr = ' start="%d"' % start if ordered and start != 1 else ""
    return "<%s%s>%s</%s>" % (tag, attr, "".join(out), tag), i


def _quote(lines, i, ctx, depth):
    body, n = [], len(lines)
    while i < n:
        line = lines[i]
        if QUOTE.match(line):
            body.append(re.sub(r"^ {0,3}> ?", "", line))
        elif line.strip() and body and body[-1].strip() and not _starts_block(lines, i):
            body.append(line)  # a lazy line inside the quote
        else:
            break
        i += 1
    return "<blockquote>%s</blockquote>" % _emit(_blocks(body, ctx, depth + 1)), i


def _blocks(lines, ctx, depth=0):
    """A list of (kind, html, extra). A paragraph keeps its inner HTML, so a tight list can drop the <p>."""
    out, para = [], []

    def flush():
        if para:
            text = "\n".join(l.lstrip() for l in para).rstrip()
            out.append(("p", _inline(text, ctx), None))
            del para[:]

    if depth > MAX_DEPTH:
        text = "\n".join(l.strip() for l in lines if l.strip())
        return [("p", esc(text), None)] if text else []

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        m = FENCE.match(line)
        if m and not ("`" in m.group(3) and m.group(2)[0] == "`"):
            flush()
            pad, fence, info = len(m.group(1)), m.group(2), m.group(3)
            close = re.compile(r"^ {0,3}%s{%d,}[ \t]*$" % (re.escape(fence[0]), len(fence)))
            body = []
            i += 1
            while i < n and not close.match(lines[i]):
                cut = 0
                while cut < pad and cut < len(lines[i]) and lines[i][cut] == " ":
                    cut += 1
                body.append(lines[i][cut:])
                i += 1
            i += 1
            lang = re.sub(r"[^a-z0-9_+#.\-]", "", (info.split() or [""])[0].lower())
            src = html.escape("\n".join(body), quote=False)
            if lang == "mermaid":
                out.append(("mermaid", '<div class="diagram"><pre class="mermaid">%s</pre></div>' % src, None))
            else:
                cls = ' class="lang-%s"' % lang if lang else ""
                out.append(("code", '<pre class="code"><code%s>%s</code></pre>' % (cls, src), None))
            continue
        m = HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            inner = _inline((m.group(2) or "").strip(), ctx)
            text = plain_text(inner)
            hid = ctx.heading_id(text)
            if depth == 0:
                ctx.toc.append({"level": level, "id": hid, "text": text})
            out.append(("h", '<h%d id="%s">%s</h%d>' % (level, hid, inner, level), {"level": level, "text": text}))
            i += 1
            continue
        if RULE.match(line):
            flush()
            out.append(("hr", "<hr>", None))
            i += 1
            continue
        if QUOTE.match(line):
            flush()
            block, i = _quote(lines, i, ctx, depth)
            out.append(("quote", block, None))
            continue
        table = _table(lines, i, ctx)
        if table:
            flush()
            out.append(("table", table[0], None))
            i = table[1]
            continue
        m = ITEM.match(line)
        if m and (not para or m.group(4)):
            flush()
            block, i = _list(lines, i, ctx, depth)
            out.append(("list", block, None))
            continue
        para.append(line)
        i += 1
    flush()
    return out


def _emit(blocks, tight=False):
    out = []
    for kind, body, _ in blocks:
        if kind == "p":
            out.append(body if tight else "<p>%s</p>" % body)
        else:
            out.append(body)
    return "\n".join(out)


def _mark_summary(blocks):
    """Wrap the Summary section, so the page can make it stand out."""
    for k, (kind, _, extra) in enumerate(blocks):
        if kind == "h" and extra["level"] <= 3 and SUMMARY.match(extra["text"]):
            end = k + 1
            while end < len(blocks) and blocks[end][0] != "h":
                end += 1
            if end == k + 1:
                return blocks
            inner = _emit(blocks[k:end])
            return blocks[:k] + [("summary", '<section class="summary">%s</section>' % inner, None)] + blocks[end:]
    return blocks


# --------------------------------------------------------------------------- entry points


def _lines(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = strip_comments(text)
    return [re.sub(r"^[ \t]+", lambda m: m.group(0).expandtabs(4), line) for line in text.split("\n")]


def render(text, link=None, summary=True):
    """Markdown to {"html", "toc", "title"}. link(url) may turn a relative link into an href."""
    ctx = _Ctx(link)
    blocks = _blocks(_lines(text), ctx)
    title = next((e["text"] for kind, _, e in blocks if kind == "h" and e["level"] == 1), None)
    if summary:
        blocks = _mark_summary(blocks)
    return {"html": _emit(blocks), "toc": [t for t in ctx.toc if t["level"] <= 3], "title": title}


def convert(text, link=None):
    return render(text, link=link, summary=False)["html"]
