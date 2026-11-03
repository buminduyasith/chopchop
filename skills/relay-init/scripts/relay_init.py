#!/usr/bin/env python3
"""Relay init: set up _relay/relay.yaml for a team.

Usage
  relay_init.py --detect                         what is here: repos, branches, style files, existing config
  relay_init.py --write answers.json             write relay.yaml from the user's answers
  relay_init.py --style-skeleton NAME --repo-path PATH   start _relay/styles/NAME.md from what the code uses

answers.json:
  {"workspace": "/work/_relay", "team": "payments", "base_branch": "dev",
   "repos": [{"name": "payments-api", "path": "/work/payments-api", "style": ["docs/code-style.md"]}],
   "tracker": {"provider": "jira", "mode": "rest"}}       # or null for none, or "keep"

Options: --json, --force (overwrite an existing style skeleton).
Needs relay-tasks next to it (shared config code). Standard library only. Python 3.8+.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_SCRIPTS = HERE.parents[1] / "relay-tasks" / "scripts"
if not (TASKS_SCRIPTS / "relaylib" / "config.py").is_file():
    sys.exit("Error: relay-init needs the relay-tasks skill next to it (%s not found)." % TASKS_SCRIPTS)
sys.path.insert(0, str(TASKS_SCRIPTS))

from relaylib.config import CONFIG_FILE, WORKSPACE_DIR, git_toplevel, parse_yaml  # noqa: E402

BASE_CANDIDATES = ["dev", "develop", "development", "main", "master"]
STYLE_NAMES = re.compile(r"(style|convention|coding|guideline|standards?)[\w.-]*\.md$", re.I)
GUIDES = ["CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md"]
FORMATTERS = {".editorconfig": "EditorConfig", ".prettierrc": "Prettier", ".prettierrc.json": "Prettier",
              "prettier.config.js": "Prettier", ".eslintrc": "ESLint", ".eslintrc.json": "ESLint",
              ".eslintrc.js": "ESLint", "eslint.config.js": "ESLint", "eslint.config.mjs": "ESLint",
              "biome.json": "Biome", "ruff.toml": "Ruff", ".flake8": "Flake8", "pyproject.toml": "pyproject",
              "checkstyle.xml": "Checkstyle", ".golangci.yml": "golangci-lint", "rustfmt.toml": "rustfmt",
              ".rubocop.yml": "RuboCop", ".stylelintrc": "Stylelint", ".clang-format": "clang-format",
              "detekt.yml": "detekt", ".scalafmt.conf": "scalafmt", ".swiftlint.yml": "SwiftLint"}
SKIP_DIRS = {".git", "node_modules", "build", "dist", "target", "out", ".venv", "venv", "__pycache__", ".gradle",
             ".idea", "vendor", "bin", "obj", ".next", "coverage", "_relay"}
LANGS = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
         ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rs": "Rust", ".cs": "C#", ".rb": "Ruby", ".php": "PHP",
         ".swift": "Swift", ".scala": "Scala", ".c": "C", ".cpp": "C++", ".vue": "Vue", ".dart": "Dart"}


class UsageError(Exception):
    pass


def git(path, *args):
    try:
        out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def is_repo(path):
    return Path(path).is_dir() and git(path, "rev-parse", "--is-inside-work-tree") == "true"


# --------------------------------------------------------------------------- detect


def repo_facts(path):
    path = Path(path)
    remote = set()
    for line in git(path, "branch", "-r", "--format=%(refname:short)").splitlines():
        if line.startswith("origin/") and line != "origin/HEAD":
            remote.add(line[len("origin/"):])
    local = set(git(path, "branch", "--format=%(refname:short)").splitlines())
    head = git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").replace("origin/", "")
    styles = []
    for folder in (path, path / "docs", path / "doc", path / ".github"):
        if folder.is_dir():
            for f in sorted(folder.iterdir()):
                if f.is_file() and STYLE_NAMES.search(f.name):
                    styles.append(f.relative_to(path).as_posix())
    return {
        "name": path.name, "path": str(path), "origin": git(path, "remote", "get-url", "origin"),
        "current_branch": git(path, "branch", "--show-current"), "origin_head": head or None,
        "base_candidates": [b for b in BASE_CANDIDATES if b in remote or b in local],
        "style_files": styles, "guides": [g for g in GUIDES if (path / g).is_file()],
    }


def detect(cwd):
    cwd = Path(cwd).resolve()
    top = git_toplevel(cwd)
    existing = None
    for folder in [cwd] + list(cwd.parents):
        if (folder / WORKSPACE_DIR / CONFIG_FILE).is_file():
            existing = folder / WORKSPACE_DIR
            break
    repos = []
    if top and is_repo(top):
        repos.append(repo_facts(top))
        parent = Path(top).parent
        for sib in sorted(parent.iterdir()):
            if len(repos) >= 12:
                break
            if sib.is_dir() and sib != Path(top) and not sib.name.startswith(".") and (sib / ".git").exists():
                repos.append(repo_facts(sib))
    votes = Counter(b for r in repos for b in r["base_candidates"])
    base = next((b for b in BASE_CANDIDATES if votes.get(b)), None)
    locations = []
    if top:
        locations.append({"path": str(Path(top) / WORKSPACE_DIR), "why": "inside this repo (git-ignored)"})
        if len(repos) > 1:
            locations.append({"path": str(Path(top).parent / WORKSPACE_DIR),
                              "why": "next to all the repos, so every repo finds it"})
    else:
        locations.append({"path": str(cwd / WORKSPACE_DIR), "why": "in this folder"})
    config = None
    if existing:
        config = parse_yaml((existing / CONFIG_FILE).read_text(encoding="utf-8")) or {}
    return {"cwd": str(cwd), "git_top": str(top) if top else None, "existing_workspace": str(existing) if existing else None,
            "existing_config": config, "workspace_options": locations, "suggested_base": base,
            "suggested_team": Path(top or cwd).name, "repos": repos}


# --------------------------------------------------------------------------- style skeleton


def style_facts(path, limit=4000):
    path = Path(path)
    langs, tools, seen = Counter(), [], 0
    for name, tool in FORMATTERS.items():
        if (path / name).exists() and tool not in tools:
            tools.append(tool)
    stack = [path]
    while stack and seen < limit:
        folder = stack.pop()
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.name.startswith("."):
                    stack.append(p)
            elif p.suffix in LANGS:
                langs[LANGS[p.suffix]] += 1
                seen += 1
    top = [d.name for d in sorted(path.iterdir()) if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".")]
    return {"languages": [l for l, _ in langs.most_common(4)], "tools": tools, "top_folders": top[:15]}


def style_skeleton(name, facts):
    return "\n".join([
        "# Code style · %s" % name, "",
        "_Relay follows this file for every task in %s. Started by relay-init from the code; "
        "keep it short, real and checked by the team._" % name, "",
        "- **Languages:** %s" % (", ".join(facts["languages"]) or "?"),
        "- **Formatters and linters:** %s (their config wins on formatting)" % (", ".join(facts["tools"]) or "none found"),
        "- **Top folders:** %s" % (", ".join("`%s/`" % f for f in facts["top_folders"]) or "-"), "",
        "## Structure", "", "_Where things go: layers, folders, one example feature to copy._", "",
        "## Naming", "", "_Files, classes, functions, variables, tests._", "",
        "## Errors and logging", "", "_How errors are raised, returned and logged._", "",
        "## Tests", "", "_Framework, where tests live, how they are named, what to mock._", "",
        "## Do", "", "_Patterns the team wants._", "",
        "## Avoid", "", "_Things reviewers always push back on._", ""])


# --------------------------------------------------------------------------- write


def rel_to(base, path):
    path, base = Path(path).resolve(), Path(base).resolve()
    try:
        return path.relative_to(base).as_posix() or "."
    except ValueError:
        pass
    try:
        relpath = os.path.relpath(str(path), str(base))
        return relpath if not relpath.startswith(".." + os.sep + "..") else str(path)
    except ValueError:
        return str(path)


def scalar(value):
    if value is None:
        return "null"
    if value is True or value is False:
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if s == "" or re.search(r"^[\s\-?:,\[\]{}#&*!|>'\"%@`]|: | #|\s$|[{}]", s) or s.lower() in (
            "true", "false", "yes", "no", "on", "off", "null", "~") or re.match(r"^-?\d+(\.\d+)?$", s):
        return json.dumps(s)
    return s


def dump(value, indent=0):
    pad = "  " * indent
    lines = []
    for k, v in value.items():
        if isinstance(v, dict) and v:
            lines.append("%s%s:" % (pad, k))
            lines += dump(v, indent + 1)
        elif isinstance(v, list) and v and all(not isinstance(x, (dict, list)) for x in v):
            lines.append("%s%s: [%s]" % (pad, k, ", ".join(scalar(x) for x in v)))
        elif isinstance(v, list) and v:
            lines.append("%s%s:" % (pad, k))
            for item in v:
                sub = dump(item, indent + 2) if isinstance(item, dict) else ["%s    %s" % (pad, scalar(item))]
                sub[0] = "%s  - %s" % (pad, sub[0].strip())
                lines += sub
        else:
            lines.append("%s%s: %s" % (pad, k, scalar(v) if not isinstance(v, (dict, list)) else ("{}" if isinstance(v, dict) else "[]")))
    return lines


TRACKER_REST = """tracker:
  provider: jira            # jira | file | <your own, see relay-requirements/providers/README.md>
  mode: rest                # rest = scripts call the API with a token from env vars
  url: ${RELAY_TRACKER_URL}           # https://yourcompany.atlassian.net
  email: ${RELAY_TRACKER_EMAIL:-}     # Jira Cloud only
  token: ${RELAY_TRACKER_TOKEN}       # Cloud: API token · Server/DC: personal access token
  jira:
    include_comments: false"""

TRACKER_MCP = """tracker:
  provider: jira
  mode: mcp                 # the agent reads Jira through the Atlassian MCP server. No token needed here."""


def render(answers, ws, existing):
    base = Path(ws).parent
    lines = ["# Relay team config. Written by relay-init. No secrets here: ${VAR} values come from",
             "# environment variables. Run /relay:relay-init again to change it.", "",
             "team: %s" % scalar(answers.get("team") or base.name), "",
             "# The branch you work from. Feature branches are cut from it. Only a person merges back.",
             "base_branch: %s" % scalar(answers["base_branch"]), "",
             "# Code repos. path is relative to the folder that holds _relay/ (or absolute).",
             "# style: the repo's own code style file(s), relative to the repo or to _relay/.",
             "#        Relay always codes by them. Without one, it follows the existing code.",
             "repos:"]
    for r in answers["repos"]:
        path = rel_to(base, r["path"])
        styles = [s for s in (r.get("style") or []) if s]
        if styles:
            lines += ["  %s:" % r["name"], "    path: %s" % scalar(path),
                      "    style: %s" % (scalar(styles[0]) if len(styles) == 1 else "[%s]" % ", ".join(scalar(s) for s in styles))]
        else:
            lines.append("  %s: %s" % (r["name"], scalar(path)))
    branches = (existing or {}).get("branches") or {}
    lines += ["", "branches:",
              "  # {key} is the epic key (PAY-120), or the feature number (007) when there is no epic.",
              "  feature: %s" % scalar(branches.get("feature") or "feature/{key}-{slug}"),
              "  task: %s" % scalar(branches.get("task") or "feature/{key}/{task}-{slug}"), ""]
    tracker = answers.get("tracker", "keep")
    if tracker == "keep":
        old = (existing or {}).get("tracker")
        if old:
            lines += ["# Jira (or another tracker) for relay-requirements."] + dump({"tracker": old}) + [""]
    elif tracker:
        mode = tracker.get("mode") or "rest"
        old = (existing or {}).get("tracker") or {}
        if old.get("provider") == tracker.get("provider", "jira") and old.get("mode", "rest") == mode:
            lines += ["# Jira (or another tracker) for relay-requirements."] + dump({"tracker": old}) + [""]
        else:
            lines += ["# Jira for relay-requirements.", TRACKER_MCP if mode == "mcp" else TRACKER_REST, ""]
    known = {"team", "base_branch", "repos", "branches", "tracker"}
    extra = {k: v for k, v in (existing or {}).items() if k not in known and not k.startswith("_")}
    if extra:
        lines += ["# Kept from the old relay.yaml."] + dump(extra) + [""]
    return "\n".join(lines).rstrip() + "\n"


def validate(answers):
    if not isinstance(answers, dict):
        raise UsageError("answers must be a JSON object")
    if not answers.get("workspace"):
        raise UsageError("answers.workspace is missing (the _relay folder path)")
    if not answers.get("base_branch"):
        raise UsageError("answers.base_branch is missing")
    repos = answers.get("repos")
    if not isinstance(repos, list) or not repos:
        raise UsageError("answers.repos needs at least one repo")
    names = set()
    for r in repos:
        if not re.match(r"^[A-Za-z0-9_.-]+$", str(r.get("name") or "")):
            raise UsageError("repo name '%s' may only use letters, numbers, dot, dash and underscore" % r.get("name"))
        if r["name"] in names:
            raise UsageError("repo name '%s' is used twice" % r["name"])
        names.add(r["name"])
        if not is_repo(r.get("path") or ""):
            raise UsageError("%s (%s) is not a git repo" % (r["name"], r.get("path")))
        if isinstance(r.get("style"), str):
            r["style"] = [r["style"]]
    tracker = answers.get("tracker", "keep")
    if tracker not in (None, "keep") and (not isinstance(tracker, dict) or tracker.get("mode", "rest") not in ("rest", "mcp")):
        raise UsageError('answers.tracker must be null, "keep", or {"provider": "jira", "mode": "rest" | "mcp"}')
    return answers


def find_style(ws, repo_path, style):
    p = Path(style).expanduser()
    if p.is_absolute():
        return p if p.is_file() else None
    for base in (Path(repo_path), Path(ws)):
        if (base / p).is_file():
            return base / p
    return None


def ignore_workspace(ws):
    top = git_toplevel(Path(ws).parent)
    if not top or Path(ws).parent.resolve() != Path(top).resolve():
        return None
    gi = Path(top) / ".gitignore"
    current = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if re.search(r"(?m)^/?_relay/?\s*$", current):
        return None
    with gi.open("a", encoding="utf-8") as fh:
        fh.write(("" if current.endswith("\n") or not current else "\n") + "\n# Relay workspace (kept out of the code)\n_relay/\n")
    return str(gi)


def write(answers):
    answers = validate(answers)
    ws = Path(answers["workspace"]).expanduser().resolve()
    if ws.name != WORKSPACE_DIR:
        raise UsageError("The workspace folder must be called %s (got %s)" % (WORKSPACE_DIR, ws))
    missing = [(r["name"], s) for r in answers["repos"] for s in r.get("style") or [] if not find_style(ws, r["path"], s)]
    if missing:
        raise UsageError("Style file(s) not found: %s. Paths are relative to the repo or to %s."
                         % (", ".join("%s: %s" % m for m in missing), ws))
    cfg = ws / CONFIG_FILE
    existing = parse_yaml(cfg.read_text(encoding="utf-8")) if cfg.is_file() else None
    ws.mkdir(parents=True, exist_ok=True)
    backup = None
    if cfg.is_file():
        backup = cfg.with_name(CONFIG_FILE + ".bak")
        shutil.copyfile(str(cfg), str(backup))
    text = render(answers, ws, existing)
    parse_yaml(text)  # must read back
    cfg.write_text(text, encoding="utf-8")
    return {"config": str(cfg), "backup": str(backup) if backup else None, "gitignore": ignore_workspace(ws),
            "text": text}


# --------------------------------------------------------------------------- main


def main(argv=None):
    p = argparse.ArgumentParser(prog="relay_init.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("--detect", action="store_true", help="show repos, branches, style files and any existing config")
    p.add_argument("--write", metavar="ANSWERS_JSON", help="write relay.yaml from an answers file")
    p.add_argument("--style-skeleton", metavar="NAME", help="start _relay/styles/NAME.md from the code")
    p.add_argument("--repo-path", help="with --style-skeleton: the repo folder")
    p.add_argument("--workspace", help="with --style-skeleton: the _relay folder")
    p.add_argument("--force", action="store_true", help="with --style-skeleton: overwrite")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)
    try:
        if args.detect:
            data = detect(Path.cwd())
            if args.json:
                print(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                print("Config:    %s" % (data["existing_workspace"] + "/relay.yaml" if data["existing_workspace"] else "none yet"))
                print("Base:      %s" % (data["suggested_base"] or "?"))
                for loc in data["workspace_options"]:
                    print("Folder:    %s (%s)" % (loc["path"], loc["why"]))
                for r in data["repos"]:
                    print("Repo:      %-20s %s · branches %s · style %s · guides %s" % (
                        r["name"], r["path"], ", ".join(r["base_candidates"]) or "-",
                        ", ".join(r["style_files"]) or "-", ", ".join(r["guides"]) or "-"))
            return 0
        if args.write:
            result = write(json.loads(Path(args.write).read_text(encoding="utf-8")))
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print("Wrote:     %s" % result["config"])
                if result["backup"]:
                    print("Backup:    %s" % result["backup"])
                if result["gitignore"]:
                    print("Updated:   %s (added _relay/)" % result["gitignore"])
                print()
                print(result["text"], end="")
            return 0
        if args.style_skeleton:
            if not args.repo_path or not args.workspace:
                raise UsageError("--style-skeleton needs --repo-path and --workspace")
            target = Path(args.workspace) / "styles" / ("%s.md" % args.style_skeleton)
            if target.exists() and not args.force:
                raise UsageError("%s exists. Use --force to start it again." % target)
            facts = style_facts(args.repo_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(style_skeleton(args.style_skeleton, facts), encoding="utf-8")
            data = {"path": str(target), "style": "styles/%s.md" % args.style_skeleton, **facts}
            print(json.dumps(data, indent=2) if args.json else "Started:   %s (in relay.yaml: style: %s)\nFound:     %s · %s"
                  % (target, data["style"], ", ".join(facts["languages"]) or "?", ", ".join(facts["tools"]) or "no formatter config"))
            return 0
        raise UsageError("Nothing to do. See --help.")
    except (UsageError, ValueError, OSError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
