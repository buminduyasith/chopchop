"""The contract every tracker provider implements.

A provider turns a tracker (Jira, Azure Boards, Linear, a folder of files...)
into normalized issue dicts. See providers/SCHEMA.md for the exact shape.
Nothing outside the provider knows which tracker it is talking to.
"""


class ProviderError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Provider:
    name = "base"

    def __init__(self, tracker_cfg):
        self.cfg = tracker_cfg or {}
        self.warnings = []

    # --- required -----------------------------------------------------------
    def ping(self):
        """Check the connection. Return a short string, e.g. the user's name."""
        raise NotImplementedError

    def get_issue(self, key):
        """Return one normalized issue. Raise ProviderError(status=404) if missing."""
        raise NotImplementedError

    def get_epic_children(self, epic_key):
        """Return normalized issues that belong to the epic (no sub-tasks)."""
        raise NotImplementedError

    # --- optional -----------------------------------------------------------
    def normalize_raw(self, raw_issue):
        """Turn one raw tracker payload (for example from an MCP tool) into a
        normalized issue. Providers that cannot do this keep the default."""
        raise ProviderError(
            "Provider '%s' cannot read raw payloads. Use --format normalized." % self.name
        )

    def get_issues(self, keys):
        """Fetch many issues. Returns (found, missing_keys)."""
        found, missing = [], []
        for key in keys:
            try:
                found.append(self.get_issue(key))
            except ProviderError as e:
                if e.status == 404:
                    missing.append(key)
                else:
                    raise
        return found, missing

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)
