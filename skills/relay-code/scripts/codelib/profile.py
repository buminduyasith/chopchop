"""Repo profiles: how to build, lint and test one code repo, and the rules to follow.

  _relay/repos/payments-api.md

  ---
  repo: "payments-api"
  confirmed: true
  build: "./gradlew assemble"
  lint: "./gradlew spotlessCheck"
  test: "./gradlew test"
  pr: "Atlassian MCP server (createPullRequest)"
  ---
  # How to work in payments-api
  ...

The first time a repo is used, detect() looks at the repo (guides, CI, build files, tests)
and writes a draft. The agent fills in the rules, a person confirms it, and from then on
every task in that repo uses it. People can edit the file any time.
"""

import json
import re
from datetime import date
from pathlib import Path

PROFILES_DIR = "repos"
COMMANDS = ["build", "lint", "test"]
GUIDES = ["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md", ".cursorrules", "CONTRIBUTING.md",
          "README.md", "docs"]
SKIP_DIRS = {".git", "node_modules", "build", "dist", "target", "out", ".venv", "venv", "__pycache__", ".gradle",
             ".idea", "vendor", "bin", "obj", ".next", "coverage"}
TEST_NAME = re.compile(r"(^test_.*\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$|Tests?\.(java|kt|cs)$|_spec\.rb$|Test\.php$)")


def path_for(ws, repo):
    return Path(ws) / PROFILES_DIR / ("%s.md" % repo)


def load(ws, repo):
    """(meta, body) or (None, None) when there is no profile yet."""
    from relaylib.features import parse_front_matter  # relay-tasks' copy
    p = path_for(ws, repo)
    if not p.is_file():
        return None, None
    return parse_front_matter(p.read_text(encoding="utf-8"))


def guides(root):
    root = Path(root)
    return [g for g in GUIDES if (root / g).exists()]


# --------------------------------------------------------------------------- detect


def detect(root):
    """Best guess at the repo's commands. Returns {"commands": {...}, "sources": {...}, ...}."""
    root = Path(root)
    cmds, src = {}, {}

    def put(kind, cmd, where):
        if cmd and kind not in cmds:
            cmds[kind] = cmd
            src[kind] = where

    targets = _make_targets(root / "Makefile")
    for kind in COMMANDS:
        if kind in targets:
            put(kind, "make %s" % kind, "Makefile")

    pkg = root / "package.json"
    if pkg.is_file():
        try:
            scripts = (json.loads(pkg.read_text(encoding="utf-8")) or {}).get("scripts") or {}
        except ValueError:
            scripts = {}
        run = ("pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists()
               else "bun" if (root / "bun.lockb").exists() or (root / "bun.lock").exists() else "npm")
        if "test" in scripts:
            put("test", "%s test" % run, "package.json scripts.test")
        for name in ("lint", "typecheck", "check"):
            if name in scripts:
                put("lint", "%s run %s" % (run, name), "package.json scripts.%s" % name)
        if "build" in scripts:
            put("build", "%s run build" % run, "package.json scripts.build")

    gradle = next((root / n for n in ("build.gradle.kts", "build.gradle") if (root / n).is_file()), None)
    if gradle:
        tool = "./gradlew" if (root / "gradlew").exists() else "gradle"
        text = gradle.read_text(encoding="utf-8", errors="replace")
        put("test", "%s test" % tool, gradle.name)
        if "spotless" in text:
            put("lint", "%s spotlessCheck" % tool, "%s (spotless plugin)" % gradle.name)
        elif "ktlint" in text:
            put("lint", "%s ktlintCheck" % tool, "%s (ktlint plugin)" % gradle.name)
        put("build", "%s assemble" % tool, gradle.name)

    if (root / "pom.xml").is_file():
        tool = "./mvnw" if (root / "mvnw").exists() else "mvn"
        put("test", "%s -q test" % tool, "pom.xml")
        put("build", "%s -q -DskipTests package" % tool, "pom.xml")

    py = root / "pyproject.toml"
    pytext = py.read_text(encoding="utf-8", errors="replace") if py.is_file() else ""
    if pytext or (root / "setup.py").exists() or (root / "setup.cfg").exists() or (root / "pytest.ini").exists():
        uses_pytest = "pytest" in pytext or (root / "pytest.ini").exists() or (root / "conftest.py").exists()
        put("test", "pytest" if uses_pytest else "python -m unittest discover",
            "pyproject.toml" if pytext else "Python project files")
        if "ruff" in pytext or (root / "ruff.toml").exists():
            put("lint", "ruff check .", "ruff config")
        elif (root / ".flake8").exists() or "flake8" in pytext:
            put("lint", "flake8", "flake8 config")

    if (root / "go.mod").is_file():
        put("test", "go test ./...", "go.mod")
        put("lint", "go vet ./...", "go.mod")
        put("build", "go build ./...", "go.mod")

    if (root / "Cargo.toml").is_file():
        put("test", "cargo test", "Cargo.toml")
        put("lint", "cargo clippy -- -D warnings", "Cargo.toml")
        put("build", "cargo build", "Cargo.toml")

    if any(root.glob("*.sln")) or any(root.glob("*.csproj")):
        put("test", "dotnet test", ".sln / .csproj")
        put("build", "dotnet build", ".sln / .csproj")

    return {"commands": cmds, "sources": src, "ci": ci_commands(root), "guides": guides(root),
            "tests": example_tests(root)}


def _make_targets(path):
    if not path.is_file():
        return set()
    return set(re.findall(r"(?m)^([A-Za-z][\w-]*)\s*:(?!=)", path.read_text(encoding="utf-8", errors="replace")))


def ci_commands(root, limit=15):
    """Commands the CI runs: the most honest answer to 'how do we test here'."""
    root = Path(root)
    out = []
    files = [root / "bitbucket-pipelines.yml", root / ".gitlab-ci.yml"] + sorted((root / ".github" / "workflows").glob("*.y*ml"))
    for f in files:
        if not f.is_file():
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        rel = f.relative_to(root).as_posix()
        i = 0
        while i < len(lines) and len(out) < limit:
            line = lines[i]
            m = re.match(r"^(\s*)-?\s*run:\s*(.*)$", line)
            if m and m.group(2).strip() not in ("|", ">", "|-", ">-"):
                out.append((rel, m.group(2).strip()))
            elif m:
                indent = len(m.group(1))
                i += 1
                while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                    if lines[i].strip():
                        out.append((rel, lines[i].strip()))
                    i += 1
                continue
            s = re.match(r"^(\s*)script:\s*$", line)
            if s:
                indent = len(s.group(1))
                i += 1
                while i < len(lines):
                    ind = len(lines[i]) - len(lines[i].lstrip())
                    if lines[i].strip() and not (ind > indent or (ind == indent and lines[i].lstrip().startswith("- "))):
                        break
                    item = re.match(r"^\s*-\s+(.*)$", lines[i])
                    if item:
                        out.append((rel, item.group(1).strip().strip("'\"")))
                    i += 1
                continue
            i += 1
    return [{"file": f, "command": c} for f, c in out[:limit]]


def example_tests(root, limit=5):
    root = Path(root)
    found = []
    stack = [root]
    while stack and len(found) < limit:
        folder = stack.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.name.startswith("."):
                    stack.append(p)
            elif TEST_NAME.search(p.name):
                found.append(p.relative_to(root).as_posix())
                if len(found) >= limit:
                    break
    return sorted(found)


# --------------------------------------------------------------------------- write


def render_draft(repo, found):
    from relaylib.features import render_front_matter
    meta = {"repo": repo, "confirmed": False}
    for kind in COMMANDS:
        meta[kind] = found["commands"].get(kind)
    meta["pr"] = None
    meta["detected"] = date.today().isoformat()
    lines = [render_front_matter(meta).rstrip(), "",
             "# How to work in %s" % repo, "",
             "_Draft written by Relay from what it found in the repo. Check the commands, fill in the "
             "rules, then confirm it with `/relay-code --profile %s --confirm`. Edit it any time._" % repo, "",
             "## Commands", "",
             "Relay runs these, in this order, before it opens a PR. They live in the front matter above.", "",
             "| Step | Command | Found in |", "| --- | --- | --- |"]
    for kind in COMMANDS:
        lines.append("| %s | %s | %s |" % (kind, "`%s`" % meta[kind] if meta[kind] else "_not found_",
                                          found["sources"].get(kind, "-")))
    lines += ["", "## What CI runs", ""]
    lines += ["- `%s` (%s)" % (c["command"], c["file"]) for c in found["ci"]] or ["_No CI file found._"]
    lines += ["", "## Read first", ""]
    lines += ["- `%s`" % g for g in found["guides"]] or ["_No guide files found (CLAUDE.md, AGENTS.md, CONTRIBUTING.md, README.md)._"]
    lines += ["", "## Tests", "",
              "Example test files to copy the style from:", ""]
    lines += ["- `%s`" % t for t in found["tests"]] or ["_No test files found._"]
    lines += ["", "## Pull requests", "",
              "_How this team opens PRs, in one line, also saved as `pr:` above. For example a connected "
              "tool (an Atlassian, Bitbucket or GitHub MCP server), a CLI that is already logged in, or "
              "\"by hand\". Relay never stores logins or tokens._"]
    lines += ["", "## Rules", "",
              "_Fill in from the guides and the code: layers and folders, naming, how errors and logging are "
              "done, which existing feature to copy, what to avoid._", ""]
    return "\n".join(lines)


def confirm(ws, repo):
    from relaylib.features import parse_front_matter, render_front_matter
    p = path_for(ws, repo)
    meta, body = parse_front_matter(p.read_text(encoding="utf-8"))
    meta["confirmed"] = True
    body = re.sub(r"(?m)^_Draft written by Relay[^\n]*\n\n?", "", body)
    p.write_text(render_front_matter(meta) + body, encoding="utf-8")
    return meta
