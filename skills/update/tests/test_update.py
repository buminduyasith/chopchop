"""The update script against a fake `claude` command and a temp Claude config folder."""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import chopchop_update  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_CLAUDE_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
state.setdefault("calls", []).append(args)
state.setdefault("cwds", []).append(os.path.realpath(os.getcwd()))
def save():
    json.dump(state, open(state_path, "w"))
if args[:3] == ["plugin", "list", "--json"]:
    print(json.dumps(state["installed"])); save(); sys.exit(0)
known_path = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "plugins", "known_marketplaces.json")
known = json.load(open(known_path)) if os.path.exists(known_path) else {}
if args[:3] == ["plugin", "marketplace", "add"]:
    repo, _, ref = args[3].partition("#")
    known["chopchop"] = {"source": dict({"source": "github", "repo": repo}, **({"ref": ref} if ref else {}))}
    json.dump(known, open(known_path, "w"))
    print(json.dumps({"command": "marketplace-add", "outcome": "ok", "marketplace": "chopchop"}))
    save(); sys.exit(0)
if args[:3] == ["plugin", "marketplace", "update"]:
    if args[3] not in known:
        print("Marketplace '%s' not found" % args[3], file=sys.stderr); save(); sys.exit(1)
    ok = state.get("market_ok", True)
    print(json.dumps({"command": "marketplace-update", "outcome": "ok" if ok else "error",
                      "message": "Successfully updated" if ok else "network down"}))
    save(); sys.exit(0 if ok else 1)
if args[:2] == ["plugin", "update"]:
    pid = args[2]
    scope = args[args.index("--scope") + 1] if "--scope" in args else "user"
    # Like the real CLI: a project or local install is the one for the folder it runs in.
    here = os.path.realpath(os.getcwd())
    row = next(p for p in state["installed"] if p["id"] == pid and p["scope"] == scope
               and (not p.get("projectPath") or os.path.realpath(p["projectPath"]) == here))
    # Like the real CLI: a marketplace pinned to a release tag installs that release.
    ref = known.get("chopchop", {}).get("source", {}).get("ref")
    old, new = row["version"], ref.lstrip("v") if ref else state["latest"]
    row["version"] = new
    print(json.dumps({"command": "update", "outcome": "ok", "oldVersion": old, "newVersion": new,
                      "updateOutcome": "up_to_date" if old == new else "updated", "message": "done"}))
    save(); sys.exit(0)
print("unknown command", args, file=sys.stderr); save(); sys.exit(2)
'''

FAKE_GIT = r'''#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_CLAUDE_STATE"]))
if sys.argv[1:2] == ["ls-remote"]:
    for i, v in enumerate(state.get("tags", ["0.4.0", "0.5.0"])):
        print("%040x\trefs/tags/v%s" % (i + 1, v))
    print("%040x\trefs/tags/not-a-release" % 99)
    sys.exit(0)
sys.exit(2)
'''

ROOT = HERE.parents[2]


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "claude"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        fake_git = bin_dir / "git"
        fake_git.write_text(FAKE_GIT)
        fake_git.chmod(fake_git.stat().st_mode | stat.S_IEXEC)
        self.state = root / "state.json"
        self.config = root / "config"
        (self.config / "plugins").mkdir(parents=True)
        (self.config / "plugins" / "known_marketplaces.json").write_text(json.dumps(
            {"chopchop": {"source": {"source": "github", "repo": "buminduyasith/chopchop"}}}))
        self.env = dict(os.environ)
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
        os.environ["FAKE_CLAUDE_STATE"] = str(self.state)
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.config)
        self.write_state([{"id": "chopchop@chopchop", "version": "0.4.0", "scope": "user"}], "0.5.0")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def write_state(self, installed, latest, **kw):
        self.state.write_text(json.dumps(dict({"installed": installed, "latest": latest}, **kw)))

    def calls(self):
        return json.loads(self.state.read_text())["calls"]

    def cli(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = chopchop_update.main(list(argv))
        self.assertEqual(got, code, "exit %s\nstdout:\n%s\nstderr:\n%s" % (got, out.getvalue(), err.getvalue()))
        return out.getvalue() + err.getvalue()

    def test_updates_in_place(self):
        out = self.cli()
        self.assertIn("Updated:   chopchop@chopchop 0.4.0 -> 0.5.0 (scope user)", out)
        self.assertIn("/reload-plugins", out)
        calls = self.calls()
        self.assertEqual(calls[1], ["plugin", "marketplace", "update", "chopchop", "--json"])
        self.assertEqual(calls[2], ["plugin", "update", "chopchop@chopchop", "--json", "--scope", "user"])
        self.assertFalse(any("uninstall" in c or "install" in c for c in calls))
        self.assertIn("Latest:    chopchop@chopchop 0.5.0", self.cli())

    def test_every_scope_one_marketplace_refresh(self):
        self.write_state([{"id": "chopchop@chopchop", "version": "0.4.0", "scope": "user"},
                          {"id": "chopchop@chopchop", "version": "0.3.0", "scope": "project"},
                          {"id": "other@x", "version": "1", "scope": "user"}], "0.5.0")
        out = self.cli()
        self.assertIn("0.4.0 -> 0.5.0 (scope user)", out)
        self.assertIn("0.3.0 -> 0.5.0 (scope project)", out)
        self.assertEqual(sum(1 for c in self.calls() if c[:3] == ["plugin", "marketplace", "update"]), 1)
        self.assertNotIn("other@x", out)

    def test_project_installs_in_two_folders(self):
        root = Path(self.tmp.name)
        a, b = root / "repos", root / "repos-copy"
        a.mkdir()
        b.mkdir()
        self.write_state([{"id": "chopchop@chopchop", "version": "0.7.0", "scope": "project", "projectPath": str(a)},
                          {"id": "chopchop@chopchop", "version": "0.7.0", "scope": "project", "projectPath": str(b)}],
                         "0.10.0")
        out = self.cli()
        self.assertIn("0.7.0 -> 0.10.0 (scope project: %s)" % a, out)
        self.assertIn("0.7.0 -> 0.10.0 (scope project: %s)" % b, out)
        self.assertNotIn("nothing to update", out)
        state = json.loads(self.state.read_text())
        self.assertEqual([r["version"] for r in state["installed"]], ["0.10.0", "0.10.0"])
        self.assertIn("Installed: chopchop@chopchop 0.10.0 (scope project: %s)" % b, self.cli("--check"))
        self.assertIn("Latest:    chopchop@chopchop 0.10.0 (scope project: %s), nothing to update" % b, self.cli())

    def test_project_folder_gone(self):
        gone = Path(self.tmp.name) / "deleted"
        self.write_state([{"id": "chopchop@chopchop", "version": "0.7.0", "scope": "project",
                           "projectPath": str(gone)}], "0.10.0")
        self.assertIn("project folder %s no longer exists" % gone, self.cli(code=1))
        self.assertFalse(any(c[:2] == ["plugin", "update"] for c in self.calls()))

    def known(self):
        return json.loads((self.config / "plugins" / "known_marketplaces.json").read_text())["chopchop"]["source"]

    def test_version_pins_and_latest_unpins(self):
        settings = self.config / "settings.json"
        settings.write_text(json.dumps({"theme": "dark", "extraKnownMarketplaces": {"chopchop": {
            "source": {"source": "github", "repo": "buminduyasith/chopchop"}}}}))
        self.write_state([{"id": "chopchop@chopchop", "version": "0.5.0", "scope": "user"}], "0.5.0")
        out = self.cli("--version", "v0.4.0")
        self.assertIn("Updated:   chopchop@chopchop 0.5.0 -> 0.4.0 (scope user)", out)
        self.assertIn("pinned to release 0.4.0", out)
        self.assertEqual(self.known()["ref"], "v0.4.0")
        data = json.loads(settings.read_text())
        self.assertEqual(data["extraKnownMarketplaces"]["chopchop"]["source"]["ref"], "v0.4.0")
        self.assertEqual(data["theme"], "dark")
        self.assertTrue((self.config / "settings.json.bak").exists())
        check = self.cli("--check")
        self.assertIn("pinned to v0.4.0", check)
        self.assertIn("Latest:    release 0.5.0", check)
        out = self.cli()
        self.assertIn("0.4.0 -> 0.5.0", out)
        self.assertIn("follows the latest release", out)
        self.assertNotIn("ref", self.known())
        self.assertNotIn("ref", json.loads(settings.read_text())["extraKnownMarketplaces"]["chopchop"]["source"])
        self.assertIn("follows the latest release", self.cli("--check"))

    def test_project_settings_pin(self):
        proj = Path(self.tmp.name) / "proj"
        (proj / ".claude").mkdir(parents=True)
        (proj / ".claude" / "settings.json").write_text(json.dumps({"extraKnownMarketplaces": {"chopchop": {
            "source": {"source": "github", "repo": "buminduyasith/chopchop"}}}}))
        self.write_state([{"id": "chopchop@chopchop", "version": "0.5.0", "scope": "project",
                           "projectPath": str(proj)}], "0.5.0")
        self.assertIn("0.5.0 -> 0.4.0 (scope project: %s)" % proj, self.cli("--version", "0.4.0"))
        data = json.loads((proj / ".claude" / "settings.json").read_text())
        self.assertEqual(data["extraKnownMarketplaces"]["chopchop"]["source"]["ref"], "v0.4.0")

    def test_unknown_or_bad_version(self):
        self.assertIn("There is no release 9.9.9. Releases: 0.5.0, 0.4.0", self.cli("--version", "9.9.9", code=2))
        self.assertIn("is not a version", self.cli("--version", "newest", code=2))
        self.assertFalse(any(c[:2] == ["plugin", "update"] for c in self.calls()))

    def test_missing_marketplace_is_added(self):
        (self.config / "plugins" / "known_marketplaces.json").write_text("{}")
        self.assertIn("0.4.0 -> 0.5.0", self.cli())
        self.assertIn(["plugin", "marketplace", "add", "buminduyasith/chopchop", "--json"], self.calls())
        (self.config / "plugins" / "known_marketplaces.json").write_text("{}")
        self.assertIn("0.5.0 -> 0.4.0", self.cli("--version", "0.4.0"))
        self.assertIn(["plugin", "marketplace", "add", "buminduyasith/chopchop#v0.4.0", "--json"], self.calls())

    def test_marketplace_points_at_this_release(self):
        """The release bump sets both: the plugin version and the tag the marketplace installs."""
        version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        source = next(x for x in market["plugins"] if x["name"] == "chopchop")["source"]
        self.assertEqual(source, {"source": "github", "repo": "buminduyasith/chopchop", "ref": "v%s" % version})

    def test_plugin_dir_and_failures(self):
        self.write_state([{"id": "chopchop@inline", "version": "0.4.0", "scope": "session"}], "0.5.0")
        self.assertIn("git pull", self.cli())
        self.write_state([{"id": "chopchop@chopchop", "version": "0.4.0", "scope": "user"}], "0.5.0", market_ok=False)
        self.assertIn("network down", self.cli(code=1))
        self.write_state([], "0.5.0")
        self.assertIn("not installed", self.cli(code=2))

    def test_no_claude_command(self):
        os.environ["PATH"] = str(Path(self.tmp.name) / "empty")
        self.assertIn("/plugin marketplace update chopchop", self.cli(code=2))

    def test_auto_update_on_and_off(self):
        self.assertIn("Auto:      off", self.cli("--check"))
        settings = self.config / "settings.json"
        settings.write_text(json.dumps({"theme": "dark", "enabledPlugins": {"chopchop@chopchop": True}}))
        self.assertIn("Auto:      on for marketplace chopchop", self.cli("--auto", "on"))
        data = json.loads(settings.read_text())
        self.assertEqual(data["extraKnownMarketplaces"]["chopchop"],
                         {"source": {"source": "github", "repo": "buminduyasith/chopchop"}, "autoUpdate": True})
        self.assertEqual(data["theme"], "dark")
        self.assertTrue((self.config / "settings.json.bak").exists())
        self.assertIn("Auto:      on", self.cli("--check"))
        self.cli("--auto", "off")
        self.assertFalse(json.loads(settings.read_text())["extraKnownMarketplaces"]["chopchop"]["autoUpdate"])
        settings.write_text("{broken")
        self.assertIn("not valid JSON", self.cli("--auto", "on", code=2))
        self.assertEqual(settings.read_text(), "{broken")


if __name__ == "__main__":
    unittest.main()
