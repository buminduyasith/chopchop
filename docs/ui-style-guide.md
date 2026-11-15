# chopchop UI style guide: "Calm & clear"

## Summary

- **What:** the rules every dashboard screen follows: the next action first, plain words, one idea per card,
  status as colour plus icon plus word, and light and dark themes that are equally good.
- **Where:** the tokens are at the top of `skills/dashboard/assets/dashboard.html` (inline, because the page's
  content policy allows inline styles only). Never hard-code a colour, font or size: use a token.
- **Themes:** `class="cc-dark"` (the default) or `class="cc-light"` on `<html>`.
- **Fonts:** Lexend for text, JetBrains Mono for code, ids, paths and branches, from Google Fonts.

## The rules in short

1. **The next action comes first.** When a person must act, a "Your turn" card at the top says what to do, in
   numbered steps, with any command in a code bar with a Copy button. Other tabs show a slim "Your turn" line.
2. **Plain language.** "Built and pushed. It's waiting for you to open the pull requests", not "Waiting on: you".
3. **One idea per card.** Each card has one title and an icon tile.
4. **No number that looks like nothing happened.** "6 of 6 tasks built", never "0/6 done".
5. **Status is colour, icon and word together.** Done is green with a check, your turn is amber with a hand.
6. **Readable.** Body text 17px, line height 1.6, at most 70 characters a line, contrast at least 4.5:1 in both
   themes (checked for every text and background pair the page uses).
7. **No plain text boxes.** A code block is only for real code or a command.

## Type, spacing and radius

| Token | Size | Use |
| --- | --- | --- |
| `--text-h1` | 40px | page title |
| `--text-h2` | 26px | the "Your turn" title |
| `--text-h3` | 20px | card titles |
| `--text-lg` | 19px | the status sentence |
| `--text-base` | 17px | body |
| `--text-md` | 15px | secondary text, nav, breadcrumb |
| `--text-sm` | 14px | meta, badges, small buttons |
| `--text-xs` | 13px | tags, sub-labels |

Radius: badge 4, chip 8, button 10, diagram card 12, step card 14, card 16, action card 20, pill 999.
Page width 1120px, side padding 24px, 28px between sections, cards 24px inside, card grids
`repeat(auto-fit, minmax(340px, 1fr))` with a 20px gap. Anything clickable is at least 44px tall.

## The feature page

1. Top bar: `// chopchop`, the project, Features, System, a Live pill and the theme toggle.
2. Title block: breadcrumb ("Features / Feature 001 · IDEA-1"), the title, one status sentence.
3. Progress card: "Step 7 of 8 · Review" and 8 bars: green done, amber now, grey next, with a word under each.
4. "Your turn" card, only when a person must act. Opening PRs is not a command block: while a feature is in
   review, a **Pull requests** section sits here instead, one row per repo with its state and a link: "Open pull
   request" when it exists, or "Create pull request" (the git host's create page, with the branches filled in) when
   the branch is only pushed. GitHub, GitLab, Bitbucket and Azure DevOps remotes are understood.
5. Tabs: Overview, Brief, Design, Spec, Files, Tasks, Review, Activity. A check marks an approved document.
6. Overview: cards for In short, Tasks, Approvals, Pull requests, Latest activity and Documents.

## Diagrams

Mermaid, drawn with the `base` theme from the tokens, redrawn when the theme changes. Each diagram sits in a
card with a title (the heading above it), one "how to read it" sentence, the drawing in a scroll box, and a
"Show Mermaid source" button. **See full view** (or a click on the drawing) opens the whole diagram
fitted to the window, with zoom in, zoom out, Fit, drag to move, Ctrl and the mouse wheel to zoom, and Esc to close. chopchop's own `classDef new / changed / same / ext` colours are swapped for the
theme's `--okSoft`, `--changedSoft`, `--card` and `--band`.

## Activity

A 72px tag, a sentence, a time. Push is blue, commit and approve green, review purple, fix, run and stop
orange, the rest neutral. Days read like "15 Nov".
