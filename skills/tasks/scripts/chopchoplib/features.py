"""Feature folders: numbering and lookup.

Every feature has one folder right under _chopchop/, and each stage has its own subfolder:

  _chopchop/001-PAY-120-refunds-for-customers/requirements/requirement.md
  _chopchop/001-PAY-120-refunds-for-customers/design/...
  _chopchop/001-PAY-120-refunds-for-customers/tasks/...

The number is given once (highest feature number + 1) and never reused.
"""

import json
import re
from pathlib import Path

REQUIREMENTS_DIR = "requirements"
REQUIREMENT_FILE = "requirement.md"

FOLDER_RE = re.compile(r"^(\d{3,})-(.+)$")
ISSUE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")


class FeatureError(Exception):
    pass


class Feature:
    def __init__(self, path):
        self.path = Path(path)
        m = FOLDER_RE.match(self.path.name)
        self.number = int(m.group(1))
        self.slug = m.group(2)
        self.meta = read_front_matter(self.file)

    @property
    def name(self):
        return self.path.name

    @property
    def file(self):
        return self.path / REQUIREMENTS_DIR / REQUIREMENT_FILE

    @property
    def epic(self):
        # A feature started from a design (tasks --new --epic) keeps its epic in tasks/plan.md.
        return self.meta.get("epic") or read_front_matter(self.path / "tasks" / "plan.md").get("epic")

    def as_dict(self):
        return {"number": "%03d" % self.number, "folder": self.name, "path": str(self.path),
                "file": str(self.file), "epic": self.epic, "title": self.meta.get("title"),
                "stories": self.meta.get("stories"), "synced": self.meta.get("synced")}


# --------------------------------------------------------------------------- names


def slugify(text, limit=40):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0] or s[:limit]
    return s


def folder_name(number, epic_key, title):
    """001-PAY-120-refunds-for-customers: number to type, epic key to recognise, name to read."""
    slug = slugify(title)
    key = re.sub(r"[^A-Za-z0-9]+", "-", str(epic_key)).strip("-").upper()
    return "%03d%s%s" % (number, "-" + key if key else "", "-" + slug if slug else "")


def normalize_key(value):
    """Accept PAY-120, pay-120 or a pasted link that contains one. Returns PAY-120 or None."""
    value = (value or "").strip().rstrip("/")
    if "://" in value:
        value = value.split("://", 1)[1].partition("/")[2]  # look past the host name
        found = re.findall(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9_]*-\d+)(?![A-Za-z0-9])", value)
        value = found[-1] if found else ""
    return value.upper() if ISSUE_KEY_RE.match(value) else None


# --------------------------------------------------------------------------- registry


def all_features(workspace):
    root = Path(workspace)
    if not root.is_dir():
        return []
    found = [Feature(p) for p in root.iterdir() if p.is_dir() and FOLDER_RE.match(p.name)]
    return sorted(found, key=lambda f: (f.number, f.name))


def next_number(workspace):
    """Highest feature number used, plus one."""
    return max([f.number for f in all_features(workspace)] or [0]) + 1


def duplicate_numbers(features):
    seen = {}
    for f in features:
        seen.setdefault(f.number, []).append(f.name)
    return {n: names for n, names in seen.items() if len(names) > 1}


def find_by_epic(workspace, epic_key):
    hits = [f for f in all_features(workspace) if (f.epic or "").upper() == epic_key.upper()]
    if len(hits) > 1:
        raise FeatureError("Epic %s is in more than one folder: %s. Delete or merge the extra one."
                           % (epic_key, ", ".join(f.name for f in hits)))
    return hits[0] if hits else None


def resolve(workspace, ref):
    """Find one feature from a number (1, 01, 001), an epic key, a folder name or part of it."""
    features = all_features(workspace)
    ref = (ref or "").strip()
    if not features:
        raise FeatureError("No features yet in %s. Create one with an epic id, e.g. PAY-120."
                           % Path(workspace))
    if not ref:
        if len(features) == 1:
            return features[0]
        raise FeatureError("Which feature? Give a number, epic key or part of the name:\n" + table(features))

    if ref.isdigit():
        hits = [f for f in features if f.number == int(ref)]
    elif normalize_key(ref):
        key = normalize_key(ref)
        hits = [f for f in features if (f.epic or "").upper() == key]
    else:
        hits = [f for f in features if f.name == ref]
        if not hits:
            low = ref.lower()
            hits = [f for f in features if low in f.name.lower()]

    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise FeatureError("No feature matches '%s'. Features:\n%s" % (ref, table(features)))
    raise FeatureError("'%s' matches more than one feature. Be more specific:\n%s" % (ref, table(hits)))


def table(features):
    lines = []
    for f in features:
        count = f.meta.get("stories", "?")
        if f.meta:
            info = "%s %s, synced %s" % (count, "story" if count == 1 else "stories",
                                        (f.meta.get("synced") or "never")[:10])
        else:
            info = "no requirement.md"
        lines.append("  %03d  %-10s %-48s %s" % (f.number, f.epic or "-", f.name, info))
    return "\n".join(lines)


# --------------------------------------------------------------------------- front matter


def read_front_matter(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    return parse_front_matter(text)[0]


def parse_front_matter(text):
    """Returns (meta, body). Values written by render_front_matter are JSON strings or bare words."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        raw = m.group(2).strip()
        try:
            meta[m.group(1)] = json.loads(raw) if raw else None
        except ValueError:
            meta[m.group(1)] = raw
    return meta, text[end + 5:]


def render_front_matter(meta):
    lines = ["---"]
    for key, value in meta.items():
        lines.append("%s: %s" % (key, json.dumps(value, ensure_ascii=False)))
    lines.append("---")
    return "\n".join(lines) + "\n"
