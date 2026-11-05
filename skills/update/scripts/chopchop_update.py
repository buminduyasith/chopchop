#!/usr/bin/env python3
"""Update the chopchop plugin in place, without removing and installing it again.

Usage
  chopchop_update.py              refresh the marketplace, then update every chopchop install
  chopchop_update.py --check      only show the installed version(s) and whether auto-update is on
  chopchop_update.py --auto on    let Claude Code update chopchop by itself (--auto off to stop)
  chopchop_update.py --json       machine-readable output

It runs the Claude Code CLI: `claude plugin marketplace update <marketplace>` and then
`claude plugin update <plugin>@<marketplace> --scope <scope>` for each scope it is
installed in. New versions take effect after a restart (or /reload-plugins).

Auto-update is off by default for marketplaces that are not official. --auto writes
`autoUpdate` into this marketplace's entry under `extraKnownMarketplaces` in the user's
Claude settings (a copy is kept as settings.json.bak). Claude Code then checks for updates in
the background during a session and says when one is ready.

Standard library only. Python 3.8+.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN = "chopchop"
TIMEOUT = 300


class UpdateError(Exception):
    pass


def claude():
    path = shutil.which("claude")
    if not path:
        raise UpdateError("The `claude` command is not on PATH, so I cannot update the plugin from here. "
                          "In Claude Code, run: /plugin marketplace update chopchop, then /plugin update chopchop@chopchop")
    return path


def run(*args, timeout=TIMEOUT):
    try:
        out = subprocess.run([claude()] + list(args), capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL)
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


def update():
    found = installs()
    if not found:
        raise UpdateError("chopchop is not installed. Install it with:\n"
                          "  /plugin marketplace add buminduyasith/chopchop\n"
                          "  /plugin install chopchop@chopchop")
    results, refreshed = [], {}
    for p in found:
        pid = p["id"]
        market = pid.split("@", 1)[1] if "@" in pid else ""
        row = {"id": pid, "scope": p.get("scope"), "old": p.get("version"), "new": p.get("version")}
        if market in ("", "inline"):
            row.update(outcome="skipped", message="loaded with --plugin-dir: update that folder with git pull, "
                                                  "then /reload-plugins")
            results.append(row)
            continue
        if market not in refreshed:
            code, out, err = run("plugin", "marketplace", "update", market, "--json")
            info = last_json(out) or {}
            refreshed[market] = code == 0 and info.get("outcome", "ok") == "ok"
            if not refreshed[market]:
                row.update(outcome="failed", message="could not refresh marketplace %s: %s"
                           % (market, info.get("message") or err.strip() or out.strip()))
                results.append(row)
                continue
        elif not refreshed[market]:
            row.update(outcome="failed", message="marketplace %s could not be refreshed" % market)
            results.append(row)
            continue
        args = ["plugin", "update", pid, "--json"]
        if p.get("scope"):
            args += ["--scope", p["scope"]]
        code, out, err = run(*args)
        info = last_json(out)
        if code != 0 or not info or info.get("outcome") not in (None, "ok"):
            msg = (info or {}).get("message") or err.strip() or out.strip() or "unknown error"
            row.update(outcome="failed", message=msg)
        else:
            row["new"] = info.get("newVersion") or row["old"]
            up_to_date = info.get("updateOutcome") == "up_to_date" or row["new"] == row["old"]
            row.update(outcome="up_to_date" if up_to_date else "updated", message=info.get("message", ""))
        results.append(row)
    return results


# --------------------------------------------------------------------------- auto-update


def config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def marketplace_name():
    found = [p["id"].split("@", 1)[1] for p in installs() if "@" in p.get("id", "")]
    found = [m for m in found if m != "inline"]
    return found[0] if found else PLUGIN


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def auto_state(market):
    settings = read_json(config_dir() / "settings.json") or {}
    entry = (settings.get("extraKnownMarketplaces") or {}).get(market) or {}
    if "autoUpdate" in entry:
        return bool(entry["autoUpdate"])
    known = (read_json(config_dir() / "plugins" / "known_marketplaces.json") or {}).get(market) or {}
    return bool(known.get("autoUpdate", False))


def set_auto(on):
    market = marketplace_name()
    path = config_dir() / "settings.json"
    if path.exists():
        settings = read_json(path)
        if settings is None:
            raise UpdateError("%s is not valid JSON, so I did not change it." % path)
        shutil.copyfile(str(path), str(path) + ".bak")
    else:
        settings = {}
    markets = settings.setdefault("extraKnownMarketplaces", {})
    entry = markets.get(market)
    if entry is None:
        known = (read_json(config_dir() / "plugins" / "known_marketplaces.json") or {}).get(market) or {}
        if not known.get("source"):
            raise UpdateError("Marketplace %s is not set up here. Add it first: /plugin marketplace add "
                              "buminduyasith/chopchop" % market)
        entry = markets[market] = {"source": known["source"]}
    entry["autoUpdate"] = bool(on)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return {"marketplace": market, "auto_update": bool(on), "settings": str(path)}


def main(argv=None):
    p = argparse.ArgumentParser(prog="chopchop_update.py", description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n".join(__doc__.split("\n")[2:]))
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
            rows = [{"id": r.get("id"), "scope": r.get("scope"), "version": r.get("version")} for r in installs()]
            auto = auto_state(marketplace_name()) if rows else False
            if args.json:
                print(json.dumps({"installs": rows, "auto_update": auto}, indent=2))
            else:
                for r in rows or [{"id": "chopchop", "scope": "-", "version": "not installed"}]:
                    print("Installed: %s %s (scope %s)" % (r["id"], r["version"], r["scope"]))
                if rows:
                    print("Auto:      %s" % ("on" if auto else "off (turn it on with --auto on)"))
            return 0
        results = update()
    except UpdateError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            if r["outcome"] == "updated":
                print("Updated:   %s %s -> %s (scope %s)" % (r["id"], r["old"], r["new"], r["scope"]))
            elif r["outcome"] == "up_to_date":
                print("Latest:    %s %s (scope %s), nothing to update" % (r["id"], r["old"], r["scope"]))
            else:
                print("%-10s %s (scope %s): %s" % (r["outcome"].capitalize() + ":", r["id"], r["scope"], r["message"]))
        if any(r["outcome"] == "updated" for r in results):
            print("Next:      restart Claude Code (or run /reload-plugins) to use the new version.")
    return 1 if any(r["outcome"] == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
