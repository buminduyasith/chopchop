#!/usr/bin/env python3
"""Draw docs/images/how-it-works-{light,dark}.svg: chopchop on one page, in the "Calm & clear" colours.

Run it again after changing the steps: python3 docs/images/make_how_it_works.py
"""

from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
W, H = 1200, 760
FONT = "Lexend, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace"

THEMES = {
    "light": dict(bg="#F6F6F3", surface="#FFFFFF", border="#E6E5E0", text="#1C1C1A", text2="#4A4945", muted="#5F5E5A",
                  accent="#2F5BD3", accentSoft="#EBF0FC", ok="#1F7A4D", okBar="#1F9D5C", okSoft="#E8F5EE",
                  warnText="#8A4B05", warnBar="#E0A030", warnSoft="#FFF8EC", warnBorder="#EED6A8", warnPill="#FBE7C4",
                  codeBg="#1C1C1A", codeText="#F6F6F3", stepBg="#1C1C1A", stepText="#FFFFFF", band="#F4F3EF",
                  bandBorder="#E2E0D9", line="#8A877F", track="#E6E5E0", purple="#6B3FC4", purpleSoft="#F1ECFB"),
    "dark": dict(bg="#121314", surface="#1B1C1E", border="#2C2D30", text="#ECECEA", text2="#C9C8C3", muted="#A3A29C",
                 accent="#8FA9FF", accentSoft="#1F2740", ok="#5BD49A", okBar="#34B27A", okSoft="#15291F",
                 warnText="#F5C46B", warnBar="#E0A030", warnSoft="#221B0E", warnBorder="#5A4415", warnPill="#3A2C10",
                 codeBg="#0B0B0C", codeText="#ECECEA", stepBg="#ECECEA", stepText="#121314", band="#17181A",
                 bandBorder="#2E2F33", line="#8C8B86", track="#2C2D30", purple="#C4A8FF", purpleSoft="#2A2140"),
}

# x, y, w, h of the cards in the two rows
CW, CH = 200, 156
ROW1 = 150
ROW2 = 364
XS = [40, 268, 496, 724, 952]

STEPS_1 = [
    ("", "Start", ["A Jira key or link,", "or an idea in a sentence"], None),
    ("1", "Groom", ["Agents check every story", "against the code, then", "ask you a few questions"], None),
    ("2", "Brief", ["What we build,", "in plain words"], ("you", "You approve")),
    ("3", "Design", ["For the lead:", "a ten minute read"], ("lead", "Lead approves")),
    ("4", "Spec", ["For the agents:", "every file and test"], ("you", "You approve")),
]


def t(x, y, s, size=14, color="text", weight=400, anchor="start", family=FONT, extra=""):
    return ('<text x="%g" y="%g" font-family="%s" font-size="%d" font-weight="%d" fill="{%s}" text-anchor="%s"%s>%s</text>'
            % (x, y, family, size, weight, color, anchor, extra, escape(s)))


def rect(x, y, w, h, r, fill, stroke=None, dash=False, sw=1):
    s = '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="{%s}"' % (x, y, w, h, r, fill)
    if stroke:
        s += ' stroke="{%s}" stroke-width="%g"' % (stroke, sw)
    if dash:
        s += ' stroke-dasharray="6 5"'
    return s + "/>"


def arrow(d, color="line", dash=False):
    return ('<path d="%s" fill="none" stroke="{%s}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"%s '
            'marker-end="url(#head-%s)"/>' % (d, color, ' stroke-dasharray="5 5"' if dash else "", color))


def num(cx, cy, n):
    return ('<circle cx="%g" cy="%g" r="13" fill="{stepBg}"/>' % (cx, cy) +
            t(cx, cy + 5, n, 13, "stepText", 600, "middle"))


def pill(x, y, label, kind):
    w = 18 + len(label) * 7.6 + 22
    fill, ink = ("warnPill", "warnText") if kind in ("you", "lead") else ("okSoft", "ok")
    hand = ('<path d="M%g %g v-5.5a1.2 1.2 0 0 1 2.4 0v4.5m0-4.5v-1a1.2 1.2 0 0 1 2.4 0v5.5m0-3.8a1.2 1.2 0 0 1 2.4 0v4.2a4.6 4.6 0 0 1-4.6 4.6h-.6'
            'a4.6 4.6 0 0 1-3.5-1.7l-1.6-2a1.2 1.2 0 0 1 1.8-1.5l.9 1"'
            ' fill="none" stroke="{%s}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>' % (x + 12, y + 16, ink))
    return rect(x, y, w, 26, 13, fill) + hand + t(x + 26, y + 18, label, 13, ink, 600)


def card(x, y, n, title, lines, gate, w=CW, h=CH):
    out = [rect(x, y, w, h, 16, "warnSoft" if gate else "surface", "warnBorder" if gate else "border")]
    tx = x + 20
    if n:
        out.append(num(x + 33, y + 33, n))
        tx = x + 56
    out.append(t(tx, y + 39, title, 18, "text", 600))
    for i, line in enumerate(lines):
        out.append(t(x + 20, y + 70 + i * 20, line, 14, "text2"))
    if gate:
        out.append(pill(x + 20, y + h - 42, gate[1], gate[0]))
    return "".join(out)


def build():
    parts = []
    # title and the one command
    parts.append(t(40, 62, "How chopchop works", 32, "text", 600))
    parts.append(t(40, 96, "One command takes a feature from a Jira key or an idea to merged pull requests.", 17, "text2"))
    parts.append(t(40, 120, "People decide at three gates. Agents do the rest.", 17, "text2"))
    cmd = "/chopchop:run PAY-120"
    cw = len(cmd) * 9.6 + 40
    parts.append(rect(W - 40 - cw, 44, cw, 44, 10, "codeBg"))
    parts.append(t(W - 40 - cw / 2, 72, cmd, 16, "codeText", 500, "middle", MONO))

    # row 1
    for i, (n, title, lines, gate) in enumerate(STEPS_1):
        parts.append(card(XS[i], ROW1, n, title, lines, gate))
        if i:
            parts.append(arrow("M%g %g H%g" % (XS[i - 1] + CW + 4, ROW1 + CH / 2, XS[i] - 6)))
    # down from Spec, back to the left, into Tasks
    y_mid = ROW1 + CH + 28
    parts.append(arrow("M%g %g V%g H%g V%g" % (XS[4] + CW / 2, ROW1 + CH + 4, y_mid, XS[0] + CW / 2, ROW2 - 6)))

    # row 2: tasks, the build loop, review, done
    h2 = 170
    parts.append(card(XS[0], ROW2, "5", "Tasks", ["Small tasks, one repo", "each, in waves"], None, h=h2))
    lx, lw = XS[1], XS[3] + CW - XS[1]
    parts.append(rect(lx, ROW2, lw, h2, 16, "band", "bandBorder", dash=True, sw=1.5))
    parts.append(num(lx + 33, ROW2 + 33, "6"))
    parts.append(t(lx + 56, ROW2 + 39, "Build loop", 18, "text", 600))
    parts.append(t(lx + 160, ROW2 + 39, "one task at a time, a fresh agent for each", 14, "muted"))
    names = ["Build", "Review", "Fix", "Test", "Commit"]
    pw, gap = 112, 20
    total = len(names) * pw + (len(names) - 1) * gap
    px0 = lx + (lw - total) / 2
    py = ROW2 + 66
    for i, name in enumerate(names):
        px = px0 + i * (pw + gap)
        parts.append(rect(px, py, pw, 40, 20, "surface", "border"))
        parts.append(t(px + pw / 2, py + 26, name, 15, "accent" if name in ("Build", "Review") else "text", 600, "middle"))
        if i:
            parts.append(arrow("M%g %g H%g" % (px - gap + 2, py + 20, px - 5), "line"))
    back_y = py + 64
    parts.append(arrow("M%g %g V%g H%g V%g" % (px0 + 4 * (pw + gap) + pw / 2, py + 42, back_y, px0 + pw / 2, py + 46), "accent", dash=True))
    parts.append(t(lx + lw / 2, back_y - 8, "next task", 13, "accent", 500, "middle"))
    parts.append(t(lx + lw / 2, ROW2 + h2 - 12, "Another agent reviews each change before its commit. One PR per repo.", 13, "muted", 400, "middle"))
    parts.append(arrow("M%g %g H%g" % (XS[0] + CW + 4, ROW2 + h2 / 2, lx - 6)))

    parts.append(card(XS[4], ROW2, "7", "Review", ["Every PR comment", "explained, grouped", "and answered"], None, h=h2 - 0))
    parts.append(pill(XS[4] + 20, ROW2 + h2 - 40, "A person merges", "you"))
    parts.append(arrow("M%g %g H%g" % (lx + lw + 4, ROW2 + h2 / 2, XS[4] - 6)))

    # the dashboard band
    by, bh = ROW2 + h2 + 36, 112
    parts.append(rect(40, by, W - 80, bh, 16, "surface", "border"))
    parts.append(rect(64, by + 24, 40, 40, 12, "accentSoft"))
    parts.append('<path d="M74 %g h20 v16 h-20z M74 %g h20 M80 %g v10" fill="none" stroke="{accent}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
                 % (by + 36, by + 41, by + 41))
    parts.append(t(120, by + 44, "Live dashboard", 18, "text", 600))
    parts.append(t(120, by + 70, "Every feature, document, task and PR comment, updated as it happens.", 14, "text2"))
    parts.append(t(120, by + 92, "Runs on your machine. /chopchop:dashboard", 14, "muted"))
    bx, bw = 760, 40
    for i in range(8):
        color = "okBar" if i < 6 else ("warnBar" if i == 6 else "track")
        parts.append(rect(bx + i * (bw + 6), by + 40, bw, 8, 4, color))
    parts.append(t(bx, by + 30, "Step 7 of 8 · Review", 14, "text", 600))
    parts.append(t(bx, by + 76, "Done", 13, "ok", 500))
    parts.append(t(bx + 6 * (bw + 6), by + 76, "Your turn", 13, "warnText", 600))

    # legend
    ly = H - 26
    parts.append(rect(40, ly - 13, 16, 16, 4, "warnSoft", "warnBorder"))
    parts.append(t(64, ly, "A person decides", 13, "muted"))
    parts.append(rect(210, ly - 13, 16, 16, 4, "surface", "border"))
    parts.append(t(234, ly, "Agents do the work", 13, "muted"))
    parts.append(t(W - 40, ly, "Markdown only · simple English · a Summary on every file", 13, "muted", 400, "end"))
    return "\n".join(parts)


def render(theme):
    c = THEMES[theme]
    body = build()
    for k, v in c.items():
        body = body.replace("{%s}" % k, v)
    marks = "".join('<marker id="head-%s" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                    '<path d="M1 1 9 5 1 9z" fill="%s"/></marker>' % (k, c[k]) for k in ("line", "accent"))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
            'aria-label="How chopchop works: groom, brief, design, spec, tasks, a build loop, review, with a live dashboard">'
            '<title>How chopchop works</title><defs>%s</defs><rect width="100%%" height="100%%" rx="20" fill="%s"/>\n%s\n</svg>\n'
            % (W, H, W, H, marks, c["bg"], body))


if __name__ == "__main__":
    for theme in THEMES:
        out = HERE / ("how-it-works-%s.svg" % theme)
        out.write_text(render(theme), encoding="utf-8")
        print("wrote", out)
