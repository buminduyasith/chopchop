# chopchop

A Claude Code plugin that takes a feature from a Jira key or an idea to merged PRs.
Goal: people decide and approve, agents read the code, build, review, test and fix.

## Version

Format `MAJOR.MINOR.PATCH` (now in `.claude-plugin/plugin.json`).

- PATCH (last digit): fixes, docs, small tweaks. 0.10.2 -> 0.10.3
- MINOR (middle digit): new feature or a breaking change. Reset PATCH. 0.10.2 -> 0.11.0
- MAJOR (first digit): only the user changes it. If you think a change needs it, ask.

## Release

After anything is merged to main, ask the user if they want a GitHub release. Only on a yes:

1. Bump the version in `.claude-plugin/plugin.json`, the `ref` in `.claude-plugin/marketplace.json`
   and `docs/HANDOFF.md`. Commit `chore(release): bump version to X.Y.Z`.
2. Tag `vX.Y.Z`, push main and the tag.
3. `gh release create vX.Y.Z --title vX.Y.Z --notes-file <notes>` with the format below.

## Release notes format

```markdown
One or two lines: what this release is about.

## <Headline for a big change>   (optional, one per big change)

Short why and how to use it.

## Breaking changes
- **What changed.** What the user must do now.

## New
- **Short name.** What it does, in simple words.

## Fixes
- **What was wrong.** What happens now.

## Update

Run `/chopchop:update`, then `/reload-plugins`.

**Full changelog:** https://github.com/buminduyasith/chopchop/compare/vA.B.C...vX.Y.Z
```

Skip empty sections. Write for users, not commit by commit.
