"""File provider: stories from JSON files on disk. For teams with no tracker,
for demos, and for tests. It is also the smallest example of a provider.

relay.yaml:
  tracker:
    provider: file
    path: stories          # folder, relative to _relay/ (or absolute)

The folder holds one JSON file per issue in the normalized shape
(providers/SCHEMA.md), named <ID>.json. An epic lists its children with
"children": ["PAY-121", ...], or children point to it with "parent".
"""

import json
from pathlib import Path

from relaylib.provider_base import Provider, ProviderError
from relaylib.schema import normalize


def create(tracker_cfg):
    return FileProvider(tracker_cfg)


class FileProvider(Provider):
    name = "file"

    def __init__(self, tracker_cfg):
        super().__init__(tracker_cfg)
        path = Path(str(self.cfg.get("path") or "stories")).expanduser()
        if not path.is_absolute():
            path = Path(str(self.cfg.get("_workspace") or ".")) / path
        self.root = path

    def _all(self):
        if not self.root.is_dir():
            raise ProviderError("Story folder not found: %s" % self.root)
        items = {}
        for p in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except ValueError as e:
                raise ProviderError("%s is not valid JSON: %s" % (p.name, e))
            items[str(data.get("id") or p.stem)] = data
        return items

    def ping(self):
        return "%d issue file(s) in %s" % (len(self._all()), self.root)

    def get_issue(self, key):
        data = self._all().get(key)
        if data is None:
            raise ProviderError("%s not found in %s" % (key, self.root), status=404)
        data = dict(data, id=key)
        data.pop("children", None)
        return normalize(data, "file")

    def get_epic_children(self, epic_key):
        items = self._all()
        epic = items.get(epic_key) or {}
        keys = list(epic.get("children") or [])
        keys += [k for k, v in items.items() if v.get("parent") == epic_key and k not in keys]
        return [self.get_issue(k) for k in keys]
