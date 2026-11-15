"""Helpers for the chopchop comments skill (standard library only).

  store.py     where the files live, and how to find the right feature or loose PR
  hosts.py     read and answer GitHub PRs through the gh command
  schema.py    check a file that comes in: an ingest file or the triager's answer
  similar.py   cheap text likeness between comments, and between a comment and a spec rule
  triage.py    merge a triage, order the groups, cut the fix batches
  report.py    the files people and agents read: comments.md, pack.md, briefs, replies
"""

__version__ = "0.1.0"
