"""Task files: load, check, and write the parts the script owns.

  _chopchop/001-PAY-120-refunds/tasks/
    plan.md                   waves, graph, branches (script writes, keeps ## Notes)
    status.md                 the board as Markdown (script writes)
    board.html                the board as a page (script writes)
    changelog.md              changes found while building (people and /chopchop:code write)
    T01-refund-contracts.md   one task (the planner writes it, the script owns ## Branch)

Each task starts with front matter. Values are JSON or bare words:

  ---
  id: "T02"
  title: "Refund API endpoint"
  repo: "payments-api"
  wave: 1
  size: "M"
  status: "todo"
  owner: null
  depends_on: ["T01"]
  touches: ["src/refunds/api/**"]
  stories: ["PAY-121"]
  pr: null
  ---
"""

import fnmatch
import re
from pathlib import Path

from .features import parse_front_matter, render_front_matter, slugify

TASKS_DIR = "tasks"
DESIGN_DIR = "design"
PLAN_FILE = "plan.md"
STATUS_FILE = "status.md"
BOARD_FILE = "board.html"
CHANGELOG_FILE = "changelog.md"

STATUSES = ["todo", "in-progress", "in-review", "done"]
STATUS_TITLES = {"todo": "Todo", "in-progress": "In progress", "in-review": "In review", "done": "Done"}
SIZES = ["S", "M"]
MAX_WAVE = 2
MAX_TOUCHES = 12
MAX_DEPENDS = 3

TASK_FILE_RE = re.compile(r"^(T\d{2,})-([a-z0-9][a-z0-9-]*)\.md$")
REQUIRED = ["id", "title", "repo", "wave", "size", "status", "depends_on", "touches"]
SECTIONS = ["Goal", "Done when", "Branch"]

DEFAULT_BRANCHES = {"feature": "feature/{key}-{slug}", "task": "feature/{key}/{task}-{slug}"}


class Task:
    def __init__(self, path):
        self.path = Path(path)
        self.text = self.path.read_text(encoding="utf-8")
        self.meta, self.body = parse_front_matter(self.text)
        m = TASK_FILE_RE.match(self.path.name)
        self.file_id = m.group(1) if m else None
        self.slug = m.group(2) if m else slugify(self.path.stem)

    @property
    def id(self):
        return str(self.meta.get("id") or self.file_id or self.path.stem)

    def get(self, key, default=None):
        value = self.meta.get(key)
        return default if value is None else value

    def save(self):
        text = render_front_matter(self.meta) + self.body
        if text != self.text:
            self.path.write_text(text, encoding="utf-8")
            self.text = text
            return True
        return False


def load_tasks(tasks_dir):
    folder = Path(tasks_dir)
    if not folder.is_dir():
        return []
    found = [Task(p) for p in folder.glob("T*.md") if p.is_file()]
    return sorted(found, key=lambda t: (_id_number(t.id), t.id))


def _id_number(task_id):
    m = re.search(r"\d+", task_id or "")
    return int(m.group(0)) if m else 0


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [p.strip() for p in str(value).split(",") if p.strip()]


# --------------------------------------------------------------------------- check


def check(tasks, repos=None):
    """Returns (errors, warnings). Each item is 'T02: message'."""
    errors, warnings = [], []
    by_id = {}
    for t in tasks:
        where = t.path.name
        if not t.file_id:
            errors.append("%s: file name must look like T01-short-name.md" % where)
        for key in REQUIRED:
            if t.meta.get(key) in (None, "") or (key != "depends_on" and t.meta.get(key) == []):
                errors.append("%s: '%s' is missing in the front matter" % (where, key))
        if t.file_id and t.meta.get("id") and str(t.meta["id"]) != t.file_id:
            errors.append("%s: id is %s but the file name says %s" % (where, t.meta["id"], t.file_id))
        if t.id in by_id:
            errors.append("%s: id %s is also used by %s" % (where, t.id, by_id[t.id].path.name))
        by_id[t.id] = t

        repo = t.meta.get("repo")
        if isinstance(repo, list) or (isinstance(repo, str) and ("," in repo or " " in repo.strip())):
            errors.append("%s: a task works in one repo only, but repo is %s. Split it." % (t.id, repo))
        elif repo and repos and repo not in repos:
            errors.append("%s: repo '%s' is not in chopchop.yaml repos (%s)" % (t.id, repo, ", ".join(repos)))

        status = t.meta.get("status")
        if status and status not in STATUSES:
            errors.append("%s: status '%s' must be one of %s" % (t.id, status, ", ".join(STATUSES)))
        size = t.meta.get("size")
        if size and size not in SIZES:
            errors.append("%s: size '%s' is too big or unknown. Use S or M, split anything bigger." % (t.id, size))
        wave = t.meta.get("wave")
        if wave is not None and (not isinstance(wave, int) or not 0 <= wave <= MAX_WAVE):
            errors.append("%s: wave must be 0, 1 or 2" % t.id)

        missing = [s for s in SECTIONS if not find_section(t.body, s)]
        if missing:
            errors.append("%s: missing section %s" % (t.id, ", ".join("## " + s for s in missing)))
        done = find_section(t.body, "Done when")
        if done and not re.search(r"(?im)^\s*- \[[ x]\].*\btests?\b", done[1]):
            errors.append("%s: '## Done when' needs at least one '- [ ]' line that names a unit test" % t.id)

        touches = as_list(t.meta.get("touches"))
        if len(touches) > MAX_TOUCHES:
            warnings.append("%s: touches %d paths. It may be too big to review in one sitting." % (t.id, len(touches)))
        if size == "S" and len(touches) == 1 and not _has_glob(touches[0]):
            warnings.append("%s: one small file only. Fold it into the task that uses it, "
                            "unless two or more tasks need it." % t.id)
        if len(as_list(t.meta.get("depends_on"))) > MAX_DEPENDS:
            warnings.append("%s: depends on more than %d tasks. Can it lean on the contracts instead?"
                            % (t.id, MAX_DEPENDS))

    for t in tasks:
        wave = t.meta.get("wave")
        for dep in as_list(t.meta.get("depends_on")):
            if dep == t.id:
                errors.append("%s: depends on itself" % t.id)
            elif dep not in by_id:
                errors.append("%s: depends on %s, which does not exist" % (t.id, dep))
            else:
                dwave = by_id[dep].meta.get("wave")
                if isinstance(wave, int) and isinstance(dwave, int) and dwave >= wave:
                    errors.append("%s (wave %d) depends on %s (wave %d). A task may only depend on "
                                  "an earlier wave." % (t.id, wave, dep, dwave))

    for i, a in enumerate(tasks):
        for b in tasks[i + 1:]:
            if a.meta.get("wave") != b.meta.get("wave") or a.meta.get("repo") != b.meta.get("repo"):
                continue
            for pa in as_list(a.meta.get("touches")):
                for pb in as_list(b.meta.get("touches")):
                    if paths_overlap(pa, pb):
                        errors.append("%s and %s are both in wave %s and both touch %s. Move one to "
                                      "another wave or split the file." % (a.id, b.id, a.meta.get("wave"),
                                                                           pa if pa == pb else pa + " / " + pb))
    return errors, warnings


def _has_glob(path):
    return any(ch in path for ch in "*?[")


def paths_overlap(a, b):
    a, b = re.sub(r"^\./", "", a.strip()), re.sub(r"^\./", "", b.strip())
    return a == b or fnmatch.fnmatchcase(a, b) or fnmatch.fnmatchcase(b, a)


def waiting_on(task, by_id):
    """Dependencies that are not done yet."""
    return [d for d in as_list(task.meta.get("depends_on"))
            if d in by_id and by_id[d].meta.get("status") != "done"]


# --------------------------------------------------------------------------- sections


def find_section(body, title):
    """Returns (start, text, end) of '## title' up to the next '## ' heading, or None."""
    m = re.search(r"(?m)^## %s[ \t]*\n" % re.escape(title), body)
    if not m:
        return None
    nxt = re.search(r"(?m)^## ", body[m.end():])
    end = m.end() + nxt.start() if nxt else len(body)
    return m.start(), body[m.end():end], end


def replace_section(body, title, content):
    found = find_section(body, title)
    block = "## %s\n\n%s\n\n" % (title, content.strip())
    if not found:
        return body.rstrip() + "\n\n" + block.rstrip() + "\n"
    start, _, end = found
    rest = body[end:]
    return body[:start] + (block if rest else block.rstrip() + "\n") + rest


# --------------------------------------------------------------------------- branches


def branch_key(feature):
    return feature.epic or "%03d" % feature.number


def branch_slug(feature):
    slug = feature.slug
    if feature.epic and slug.upper().startswith(feature.epic.upper()):
        slug = slug[len(feature.epic):].lstrip("-")
    return slug or slugify(feature.meta.get("title") or "") or "feature"


def feature_branch_name(feature, patterns=None):
    pattern = (patterns or {}).get("feature") or DEFAULT_BRANCHES["feature"]
    return pattern.format(key=branch_key(feature), slug=branch_slug(feature))


def task_branch_name(feature, task, patterns=None):
    pattern = (patterns or {}).get("task") or DEFAULT_BRANCHES["task"]
    return pattern.format(key=branch_key(feature), slug=task.slug, task=task.id)


def branch_section(task, feature_branch, task_branch, repo_path):
    if not feature_branch:
        return ("_The feature branch is not created yet. Run `/chopchop:tasks --branch` first. "
                "This part is filled in for you._")
    cd = "cd %s\n" % repo_path if repo_path and repo_path != "." else ""
    return ("Repo: `%s`. Cut your branch from the feature branch, never from the base branch.\n\n"
            "```bash\n%sgit fetch origin\ngit checkout -b %s origin/%s\n```\n\n"
            "Open the PR into `%s`. Only a person merges it.\n\n"
            "_Written by chopchop. Do not edit this part._" % (
                task.get("repo", "?"), cd, task_branch, feature_branch, feature_branch))


# --------------------------------------------------------------------------- changelog


CHANGE_RE = re.compile(r"(?m)^## (C-\d+)\s*[·|-]\s*(T\d+)?\s*(?:[·|-]\s*(\S+))?\s*$")


def read_changelog(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    heads = list(CHANGE_RE.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.search(r"(?m)^## ", text[m.end():end])
        body = text[m.end():m.end() + nxt.start() if nxt else end].strip()
        affects = re.search(r"(?im)^affects:\s*(.*)$", body)
        out.append({"id": m.group(1), "task": m.group(2), "date": m.group(3), "text": body,
                    "affects": re.findall(r"T\d+", affects.group(1)) if affects else []})
    return out


CHANGELOG_TEMPLATE = """# Changelog · {feature}

Changes found while building the tasks. Newest first. Read this before you start any task.

<!--
Add one entry per change, like this:

## C-001 · T02 · 2026-10-28
Change: amounts are cents (long), not decimals.
Why: the ledger needs exact values.
Affects: T03, T05
-->
"""
