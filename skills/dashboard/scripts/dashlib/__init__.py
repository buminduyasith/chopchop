"""The parts of the chopchop dashboard (standard library only).

  md.py      Markdown to safe HTML
  data.py    what each API route returns, read from the workspace files
  watch.py   file watching and the live stream

The dashboard reads the same shared library as every other chopchop script. It lives in the
tasks skill, so that folder goes on the path here.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE.parents[2] / "tasks"

if not (TASKS / "scripts" / "chopchoplib" / "stage.py").is_file():
    raise ImportError("dashboard needs the tasks skill next to it (%s not found)." % TASKS)
if str(TASKS / "scripts") not in sys.path:
    sys.path.insert(0, str(TASKS / "scripts"))

__version__ = "2.0.0"
