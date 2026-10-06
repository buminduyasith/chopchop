"""Find the _relay workspace and load relay.yaml.

Uses PyYAML when it is installed. Otherwise falls back to a small parser that
handles the subset relay.yaml uses: nested maps, lists, quoted strings,
numbers, booleans, null and comments.
"""

import os
import re
import subprocess
from pathlib import Path

WORKSPACE_DIR = "_relay"
CONFIG_FILE = "relay.yaml"


class ConfigError(Exception):
    pass


# --------------------------------------------------------------------------- workspace


def find_workspace(explicit=None):
    """Return the _relay folder path. It may not exist yet."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("RELAY_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = Path.cwd().resolve()
    for folder in [here] + list(here.parents):
        if (folder / WORKSPACE_DIR / CONFIG_FILE).is_file():
            return folder / WORKSPACE_DIR
    top = git_toplevel(here)
    return (top or here) / WORKSPACE_DIR


def git_toplevel(path):
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(path),
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def load_config(workspace):
    path = Path(workspace) / CONFIG_FILE
    if not path.is_file():
        raise ConfigError(
            "No %s found in %s. Run: relay_req.py init" % (CONFIG_FILE, workspace))
    data = parse_yaml(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError("%s must be a map at the top level." % path)
    missing = []
    data = expand_env(data, missing)
    data["_missing_env"] = sorted(set(missing))
    data["_path"] = str(path)
    return data


def tracker_config(cfg):
    tracker = cfg.get("tracker")
    if not isinstance(tracker, dict) or not tracker.get("provider"):
        raise ConfigError("relay.yaml has no tracker.provider. Example:\n  tracker:\n    provider: jira")
    return tracker


# --------------------------------------------------------------------------- env vars

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value, missing):
    if isinstance(value, dict):
        return {k: expand_env(v, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v, missing) for v in value]
    if isinstance(value, str):
        def sub(m):
            name, default = m.group(1), m.group(2)
            if name in os.environ and os.environ[name] != "":
                return os.environ[name]
            if default is not None:
                return default
            missing.append(name)
            return ""
        return _ENV.sub(sub, value)
    return value


# --------------------------------------------------------------------------- yaml


def parse_yaml(text):
    try:
        import yaml  # type: ignore
    except ImportError:
        return mini_yaml(text)
    return yaml.safe_load(text)


def mini_yaml(text):
    lines = []
    for raw in text.splitlines():
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip() or stripped.strip() == "---":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.strip()))
    if not lines:
        return {}
    value, _ = _parse_block(lines, 0, lines[0][0])
    return value


def _parse_block(lines, i, indent):
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_map(lines, i, indent):
    out = {}
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise ConfigError("Bad indentation near: %s" % content)
        key, rest = _split_key(content)
        i += 1
        if rest == "":
            if i < len(lines) and (lines[i][0] > ind or (lines[i][0] == ind and lines[i][1].startswith("- "))):
                out[key], i = _parse_block(lines, i, lines[i][0])
            else:
                out[key] = None
        else:
            out[key] = _scalar(rest)
    return out, i


def _parse_list(lines, i, indent):
    out = []
    while i < len(lines):
        ind, content = lines[i]
        if ind < indent or not (content.startswith("- ") or content == "-"):
            break
        item = content[2:].strip() if content != "-" else ""
        i += 1
        if item == "":
            if i < len(lines) and lines[i][0] > ind:
                value, i = _parse_block(lines, i, lines[i][0])
                out.append(value)
            else:
                out.append(None)
        elif _looks_like_pair(item):
            # "- key: value" starts a map inside the list
            child_indent = ind + 2
            sub = [(child_indent, item)]
            while i < len(lines) and lines[i][0] >= child_indent:
                sub.append(lines[i])
                i += 1
            value, _ = _parse_map(sub, 0, child_indent)
            out.append(value)
        else:
            out.append(_scalar(item))
    return out, i


def _looks_like_pair(item):
    if item[:1] in "\"'[{":
        return False
    return bool(re.match(r"^[^:]+:(\s|$)", item))


def _split_key(content):
    m = re.match(r"""^("[^"]*"|'[^']*'|[^:]+?)\s*:(?:\s+(.*))?$""", content)
    if not m:
        raise ConfigError("Expected 'key: value' but got: %s" % content)
    key = m.group(1)
    if key[:1] in "\"'":
        key = key[1:-1]
    return key, (m.group(2) or "").strip()


def _strip_comment(line):
    quote = None
    for idx, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (idx == 0 or line[idx - 1] in " \t"):
            return line[:idx]
    return line


def _scalar(text):
    text = text.strip()
    if text[:1] == '"' and text[-1:] == '"' and len(text) >= 2:
        return bytes(text[1:-1], "utf-8").decode("unicode_escape")
    if text[:1] == "'" and text[-1:] == "'" and len(text) >= 2:
        return text[1:-1].replace("''", "'")
    if text[:1] == "[" and text[-1:] == "]":
        inner = text[1:-1].strip()
        return [_scalar(p) for p in _split_flow(inner)] if inner else []
    if text[:1] == "{" and text[-1:] == "}":
        inner = text[1:-1].strip()
        out = {}
        for part in _split_flow(inner) if inner else []:
            k, v = _split_key(part)
            out[k] = _scalar(v) if v else None
        return out
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", ""):
        return None
    if re.match(r"^-?\d+$", text):
        return int(text)
    if re.match(r"^-?\d+\.\d+$", text):
        return float(text)
    return text


def _split_flow(text):
    parts, depth, quote, cur = [], 0, None, ""
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts
