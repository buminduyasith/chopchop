"""A small Markdown to HTML converter for the feature page. Standard library only.

It covers what chopchop writes: headings, paragraphs, lists, tables, code blocks, Mermaid
blocks, quotes, rules, bold, italics, code and links. HTML comments are dropped. A citation in
inline code becomes a button the page can open.
"""

import html
import re

from .cite import CITE_RE, find, short


def _inline(text, cites=True):
    out, pos = [], 0
    for m in re.finditer(r"`([^`]+)`", text):
        out.append(_emphasis(html.escape(text[pos:m.start()], quote=False)))
        code = m.group(1)
        if cites and CITE_RE.fullmatch(code.strip()):
            c = find(code.strip())[0]
            out.append('<button type="button" class="cite" data-cite="%s" title="%s">%s</button>'
                       % (html.escape(c["raw"]), html.escape(c["raw"]), html.escape(short(c))))
        else:
            out.append("<code>%s</code>" % html.escape(code, quote=False))
        pos = m.end()
    out.append(_emphasis(html.escape(text[pos:], quote=False)))
    return "".join(out)


def _emphasis(s):
    def link(m):
        url = m.group(2).replace('"', "%22")
        if re.match(r"^\s*(javascript|data|vbscript):", url, re.I):
            return m.group(1)
        return '<a href="%s">%s</a>' % (url, m.group(1))

    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w_])_([^_\s][^_]*?)_(?![\w_])", r"<em>\1</em>", s)
    return s


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    parts = re.split(r"(?<!\\)\|", line)
    return [p.strip().replace("\\|", "|") for p in parts]


def strip_comments(text):
    return re.sub(r"(?s)<!--.*?-->", "", text)


def convert(text, cites=True, heading_offset=0):
    text = strip_comments(text)
    lines = text.split("\n")
    out, i = [], 0
    para = []

    def flush():
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(l.strip() for l in para), cites))
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            lang = stripped[3:].strip().lower()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            src = html.escape("\n".join(body), quote=False)
            if lang == "mermaid":
                out.append('<div class="diagram"><pre class="mermaid">%s</pre></div>' % src)
            else:
                out.append("<pre><code>%s</code></pre>" % src)
            continue
        if not stripped:
            flush()
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", stripped)
        if m:
            flush()
            level = min(6, len(m.group(1)) + heading_offset)
            title = m.group(2)
            anchor = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            out.append('<h%d id="%s">%s</h%d>' % (level, anchor, _inline(title, cites), level))
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            flush()
            head = _cells(stripped)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            t = ['<div class="tbl"><table><thead><tr>%s</tr></thead><tbody>'
                 % "".join("<th>%s</th>" % _inline(h, cites) for h in head)]
            for r in rows:
                t.append("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(c, cites) for c in r))
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % convert("\n".join(quote), cites))
            continue
        lm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if lm:
            flush()
            ordered = lm.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                m2 = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", lines[i])
                if m2 and len(m2.group(1)) < 2:
                    items.append([m2.group(3)])
                    i += 1
                elif lines[i].strip() and lines[i][:2] == "  " and items:
                    items[-1].append(lines[i].strip())
                    i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            body = []
            for it in items:
                first = it[0]
                box = re.match(r"^\[( |x|X)\]\s+(.*)$", first)
                if box:
                    first = ('<span class="box%s"></span>' % (" on" if box.group(1) != " " else "")) + _inline(box.group(2), cites)
                else:
                    first = _inline(first, cites)
                rest = [x for x in it[1:]]
                sub = ""
                if rest and re.match(r"^([-*+]|\d+[.)])\s+", rest[0]):
                    sub = convert("\n".join(rest), cites)
                elif rest:
                    first += " " + _inline(" ".join(rest), cites)
                body.append("<li>%s%s</li>" % (first, sub))
            out.append("<%s>%s</%s>" % (tag, "".join(body), tag))
            continue
        para.append(line)
        i += 1
    flush()
    return "\n".join(out)
