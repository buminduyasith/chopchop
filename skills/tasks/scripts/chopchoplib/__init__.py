"""Shared helpers for the chopchop tasks skill (standard library only).

config.py and features.py are copies of the ones in stories, so each skill
folder works on its own. tests/test_tasks.py fails if the copies drift apart.

plain.py holds the two rules for every Markdown file (a Summary first, simple English),
events.py the activity log, and stage.py where a feature stands. Every skill uses them.
"""

__version__ = "0.1.0"
