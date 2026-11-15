#!/usr/bin/env python3
"""Update the chopchop plugin in place, without removing and installing it again.

Usage
  chopchop_update.py                    update every chopchop install to the latest release
  chopchop_update.py --version 0.10.1   install that release instead, and stay on it
  chopchop_update.py --check            show the installed version(s), the pin, the latest release
                                        and whether auto-update is on
  chopchop_update.py --auto on          let Claude Code update chopchop by itself (--auto off to stop)
  chopchop_update.py --json             machine-readable output

Only releases are installed, never unreleased work on main. The marketplace file on main points
the plugin at the newest release tag, so a normal update (and auto-update) gets the latest
release. --version pins the marketplace to that release's tag (its `ref`), so it stays there.
An update without --version removes the pin again, so chopchop follows the latest release.

It runs the Claude Code CLI: `claude plugin marketplace update <marketplace>` and then
`claude plugin update <plugin>@<marketplace> --scope <scope>` for each install. A project or
local install belongs to one folder and the CLI only updates the install of the folder it runs
in, so each of those updates runs from its own project folder. If the chopchop marketplace is
missing, it is added again first. New versions take effect after a restart (or /reload-plugins).

The pin is the marketplace's `ref`, kept in Claude Code's known_marketplaces.json and in the
marketplace's `extraKnownMarketplaces` entry, in the user's Claude settings or a project's
.claude/settings(.local).json. Each changed file keeps a copy as <file>.bak.

Auto-update is off by default for marketplaces that are not official. --auto writes
`autoUpdate` into this marketplace's entry under `extraKnownMarketplaces` in the user's
Claude settings (a copy is kept as settings.json.bak). Claude Code then checks for updates in
the background during a session and says when one is ready.

Standard library only. Python 3.8+.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = "chopchop"
REPO = "buminduyasith/chopchop"
TIMEOUT = 300
VERSION = re.compile(r"^v?(\d+\.\d+\.\d+)$")


class UpdateError(Exception):
    pass


def claude():
    path = shutil.which("claude")
    if not path:
        raise UpdateError("The `claude` command is not on PATH, so I cannot update the plugin from here. "
                          "In Claude Code, run: /plugin marketplace update chopchop, then /plugin update chopchop@chopchop")
    return path


def run(*args, timeout=TIMEOUT, cwd=None):
    try:
        out = subprocess.run([claude()] + list(args), capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise UpdateError("`claude %s` did not finish in %d seconds." % (" ".join(args), timeout))
    return out.returncode, out.stdout or "", out.stderr or ""


def last_json(text):
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def installs():
    code, out, err = run("plugin", "list", "--json")
    if code != 0:
        raise UpdateError("`claude plugin list` failed: %s" % (err.strip() or out.strip()))
    try:
        data = json.loads(out)
    except ValueError:
        raise UpdateError("Could not read the output of `claude plugin list --json`.")
    rows = data if isinstance(data, list) else data.get("plugins") or []
    return [p for p in rows if str(p.get("id", "")).split("@")[0] == PLUGIN]


def market_of(p):
    pid = str(p.get("id", ""))
    return pid.split("@", 1)[1] if "@" in pid else ""


def project_folder(p):
    """The folder a project or local install belongs to, or None for the other scopes."""
    if p.get("scope") in ("project", "local") and p.get("projectPath"):
        return p["projectPath"]
    return None


def where(r):
    """'scope user' or 'scope project: /path/to/folder' for the printed lines."""
    return "scope %s: %s" % (r["scope"], r["path"]) if r.get("path") else "scope %s" % r["scope"]


# --------------------------------------------------------------------------- releases


def normalize(version):
    """'0.10.1' or 'v0.10.1' -> '0.10.1'. None or 'latest' -> None (follow the latest release)."""
    if version in (None, "", "latest"):
        return None
    m = VERSION.match(str(version).strip())
    if not m:
        raise UpdateError("'%s' is not a version. Use a release number like 0.10.1, or leave it out "
                          "for the latest release." % version)
    return m.group(1)


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def releases(repo=REPO):
    """Release versions from the repo's vX.Y.Z tags, newest first. Raises UpdateError when git fails."""
    git = shutil.which("git")
    if not git:
        raise UpdateError("git is not on PATH, so I cannot list the chopchop releases.")
    try:
        out = subprocess.run([git, "ls-remote", "--tags", "--refs", "https://github.com/%s.git" % repo],
                             capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise UpdateError("Listing the releases of %s took too long. Check the network." % repo)
    if out.returncode != 0:
        raise UpdateError("Could not list the releases of %s: %s" % (repo, (out.stderr or out.stdout).strip()))
    found = set()
    for line in out.stdout.splitlines():
        m = re.search(r"refs/tags/v(\d+\.\d+\.\d+)$", line.strip())
        if m:
            found.add(m.group(1))
    return sorted(found, key=vkey, reverse=True)


# --------------------------------------------------------------------------- settings files


def config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def known_path():
    return config_dir() / "plugins" / "known_marketplaces.json"


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    path = Path(path)
    if path.exists():
        shutil.copyfile(str(path), str(path) + ".bak")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def known_source(market):
    """The marketplace's source in known_marketplaces.json, or None when it is not added here."""
    entry = (read_json(known_path()) or {}).get(market)
    return entry.get("source") if isinstance(entry, dict) and isinstance(entry.get("source"), dict) else None


def repo_of(market):
    src = known_source(market) or {}
    if src.get("source") == "github" and src.get("repo"):
        return src["repo"]
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?/?$", str(src.get("url") or ""))
    return m.group(1) if m else REPO


def settings_files(found):
    """The Claude settings files that can declare the marketplace: the user's, and each project's."""
    files = [config_dir() / "settings.json"]
    for p in found:
        folder = project_folder(p)
        if folder:
            files += [Path(folder) / ".claude" / "settings.json", Path(folder) / ".claude" / "settings.local.json"]
    out = []
    for f in files:
        if f not in out:
            out.append(f)
    return out


def set_ref(market, ref, found):
    """Pin the marketplace to `ref` (a release tag), or remove the pin when ref is None.

    Changes known_marketplaces.json and every extraKnownMarketplaces entry for it. The CLI refuses
    a marketplace whose settings entry and known source disagree, so both change together.
    Returns the files changed."""
    changed = []

    def apply(source):
        if not isinstance(source, dict) or source.get("source") not in ("github", "git", "url"):
            return False
        if ref and source.get("ref") != ref:
            source["ref"] = ref
            return True
        if not ref and "ref" in source:
            source.pop("ref")
            return True
        return False

    known = read_json(known_path())
    if isinstance(known, dict) and apply((known.get(market) or {}).get("source")):
        write_json(known_path(), known)
        changed.append(str(known_path()))
    for f in settings_files(found):
        data = read_json(f) if f.is_file() else None
        entry = ((data or {}).get("extraKnownMarketplaces") or {}).get(market) if isinstance(data, dict) else None
        if isinstance(entry, dict) and apply(entry.get("source")):
            write_json(f, data)
            changed.append(str(f))
    return changed


# --------------------------------------------------------------------------- update


def prepare_market(market, version, found):
    """Point the marketplace at the right release and refresh it. Returns (ok, message, changed files)."""
    ref = "v%s" % version if version else None
    src = known_source(market)
    if src is None:
        target = repo_of(market) + ("#%s" % ref if ref else "")
        code, out, err = run("plugin", "marketplace", "add", target, "--json")
        info = last_json(out) or {}
        ok = code == 0 and info.get("outcome", "ok") == "ok"
        return ok, ("" if ok else "could not add marketplace %s: %s"
                    % (market, info.get("message") or err.strip() or out.strip())), []
    if ref and src.get("source") not in ("github", "git", "url"):
        return False, ("marketplace %s comes from a local folder, so I cannot pick a release for it. "
                       "Check out tag %s in that folder, then run /plugin marketplace update %s" % (market, ref, market)), []
    changed = set_ref(market, ref, found)
    code, out, err = run("plugin", "marketplace", "update", market, "--json")
    info = last_json(out) or {}
    ok = code == 0 and info.get("outcome", "ok") == "ok"
    return ok, ("" if ok else "could not refresh marketplace %s: %s"
                % (market, info.get("message") or err.strip() or out.strip())), changed


def update(version=None):
    found = installs()
    if not found:
        raise UpdateError("chopchop is not installed. Install it with:\n"
                          "  /plugin marketplace add %s\n"
                          "  /plugin install chopchop@chopchop" % REPO)
    if version:
        known = releases(repo_of(next((market_of(p) for p in found if market_of(p) not in ("", "inline")), PLUGIN)))
        if version not in known:
            raise UpdateError("There is no release %s. Releases: %s" % (version, ", ".join(known[:10]) or "none"))
    results, markets, changed = [], {}, []
    for p in found:
        pid, market = p["id"], market_of(p)
        row = {"id": pid, "scope": p.get("scope"), "old": p.get("version"), "new": p.get("version")}
        folder = project_folder(p)
        if folder:
            row["path"] = folder
        if market in ("", "inline"):
            row.update(outcome="skipped", message="loaded with --plugin-dir: update that folder with git pull, "
                                                  "then /reload-plugins")
            results.append(row)
            continue
        if market not in markets:
            ok, msg, files = prepare_market(market, version, found)
            markets[market] = (ok, msg)
            changed += files
        ok, msg = markets[market]
        if not ok:
            row.update(outcome="failed", message=msg)
            results.append(row)
            continue
        if folder and not os.path.isdir(folder):
            row.update(outcome="failed", message="project folder %s no longer exists" % folder)
            results.append(row)
            continue
        args = ["plugin", "update", pid, "--json"]
        if p.get("scope"):
            args += ["--scope", p["scope"]]
        code, out, err = run(*args, cwd=folder)
        info = last_json(out)
        if code != 0 or not info or info.get("outcome") not in (None, "ok"):
            msg = (info or {}).get("message") or err.strip() or out.strip() or "unknown error"
            row.update(outcome="failed", message=msg)
        else:
            row["new"] = info.get("newVersion") or row["old"]
            up_to_date = info.get("updateOutcome") == "up_to_date" or row["new"] == row["old"]
            row.update(outcome="up_to_date" if up_to_date else "updated", message=info.get("message", ""))
        results.append(row)
    return {"version": version or "latest", "changed": changed, "results": results}


# --------------------------------------------------------------------------- auto-update


def marketplace_name():
    found = [market_of(p) for p in installs()]
    found = [m for m in found if m not in ("", "inline")]
    return found[0] if found else PLUGIN


def auto_state(market):
    settings = read_json(config_dir() / "settings.json") or {}
    entry = (settings.get("extraKnownMarketplaces") or {}).get(market) or {}
    if "autoUpdate" in entry:
        return bool(entry["autoUpdate"])
    known = (read_json(known_path()) or {}).get(market) or {}
    return bool(known.get("autoUpdate", False))


def set_auto(on):
    market = marketplace_name()
    path = config_dir() / "settings.json"
    if path.exists():
        settings = read_json(path)
        if settings is None:
            raise UpdateError("%s is not valid JSON, so I did not change it." % path)
    else:
        settings = {}
    markets = settings.setdefault("extraKnownMarketplaces", {})
    entry = markets.get(market)
    if entry is None:
        source = known_source(market)
        if not source:
            raise UpdateError("Marketplace %s is not set up here. Add it first: /plugin marketplace add %s"
                              % (market, REPO))
        entry = markets[market] = {"source": source}
    entry["autoUpdate"] = bool(on)
    write_json(path, settings)
    return {"marketplace": market, "auto_update": bool(on), "settings": str(path)}


def check():
    found = installs()
    rows = [{"id": r.get("id"), "scope": r.get("scope"), "version": r.get("version"),
             "path": project_folder(r)} for r in found]
    market = marketplace_name()
    src = known_source(market) or {}
    try:
        latest = releases(repo_of(market))[:1]
    except UpdateError:
        latest = []
    return {"installs": rows, "auto_update": auto_state(market) if rows else False,
            "pinned": src.get("ref"), "marketplace_added": bool(src),
            "latest_release": latest[0] if latest else None}


def main(argv=None):
    p = argparse.ArgumentParser(prog="chopchop_update.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
    p.add_argument("--version", metavar="X.Y.Z", help="install this release and stay on it (default: the latest release)")
    p.add_argument("--check", action="store_true", help="only show what is installed")
    p.add_argument("--auto", choices=["on", "off"], help="turn Claude Code's auto-update for chopchop on or off")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)
    try:
        if args.auto:
            result = set_auto(args.auto == "on")
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print("Auto:      %s for marketplace %s (in %s)" % (
                    "on" if result["auto_update"] else "off", result["marketplace"], result["settings"]))
                if result["auto_update"]:
                    print("Note:      Claude Code checks in the background during a session and says "
                          "\"Plugin updated\". Run /reload-plugins then.")
            return 0
        if args.check:
            info = check()
            if args.json:
                print(json.dumps(info, indent=2))
            else:
                for r in info["installs"] or [{"id": "chopchop", "scope": "-", "version": "not installed"}]:
                    print("Installed: %s %s (%s)" % (r["id"], r["version"], where(r)))
                print("Latest:    %s" % ("release %s" % info["latest_release"] if info["latest_release"]
                                         else "unknown (could not list the releases)"))
                if info["installs"]:
                    print("Version:   %s" % ("pinned to %s (run without --version to follow the latest release)"
                                             % info["pinned"] if info["pinned"] else "follows the latest release"
                                             if info["marketplace_added"] else
                                             "the chopchop marketplace is missing here: an update adds it again"))
                    print("Auto:      %s" % ("on" if info["auto_update"] else "off (turn it on with --auto on)"))
            return 0
        out = update(normalize(args.version))
    except UpdateError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    results = out["results"]
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for r in results:
            if r["outcome"] == "updated":
                print("Updated:   %s %s -> %s (%s)" % (r["id"], r["old"], r["new"], where(r)))
            elif r["outcome"] == "up_to_date":
                print("Latest:    %s %s (%s), nothing to update" % (r["id"], r["new"], where(r)))
            else:
                print("%-10s %s (%s): %s" % (r["outcome"].capitalize() + ":", r["id"], where(r), r["message"]))
        print("Version:   %s" % ("pinned to release %s. Run without --version to follow the latest release again."
                                 % out["version"] if out["version"] != "latest" else "follows the latest release"))
        for f in out["changed"]:
            print("Changed:   %s (copy kept as %s.bak)" % (f, Path(f).name))
        if any(r["outcome"] == "updated" for r in results):
            print("Next:      restart Claude Code (or run /reload-plugins) to use the new version.")
    return 1 if any(r["outcome"] == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
