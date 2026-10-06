"""Load a tracker provider by name.

A provider is a folder with a provider.py that defines create(tracker_cfg).
Search order:
  1. tracker.provider_path in relay.yaml (a team's own providers, no fork needed)
  2. <workspace>/providers/<name>/provider.py
  3. the providers/ folder that ships with this skill
"""

import importlib.util
import sys
from pathlib import Path

from .provider_base import Provider, ProviderError

SKILL_DIR = Path(__file__).resolve().parents[2]
BUILTIN = SKILL_DIR / "providers"


def candidates(name, tracker_cfg, workspace=None):
    dirs = []
    if tracker_cfg.get("provider_path"):
        base = Path(str(tracker_cfg["provider_path"])).expanduser()
        if not base.is_absolute() and workspace:
            base = Path(workspace) / base
        dirs.append(base)
    if workspace:
        dirs.append(Path(workspace) / "providers")
    dirs.append(BUILTIN)
    return [d / name / "provider.py" for d in dirs]


def available(workspace=None):
    names = set()
    for base in ([Path(workspace) / "providers"] if workspace else []) + [BUILTIN]:
        if base.is_dir():
            names.update(p.parent.name for p in base.glob("*/provider.py"))
    return sorted(names)


def load(tracker_cfg, workspace=None):
    name = str(tracker_cfg.get("provider") or "").strip()
    if not name:
        raise ProviderError("relay.yaml: tracker.provider is empty.")
    for path in candidates(name, tracker_cfg, workspace):
        if path.is_file():
            spec = importlib.util.spec_from_file_location("relay_provider_%s" % name, str(path))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            if not hasattr(module, "create"):
                raise ProviderError("%s has no create(tracker_cfg) function." % path)
            provider = module.create(tracker_cfg)
            if not isinstance(provider, Provider):
                raise ProviderError("%s create() must return a Provider." % path)
            return provider
    raise ProviderError("Unknown provider '%s'. Available: %s. To add one, see providers/README.md."
                        % (name, ", ".join(available(workspace)) or "none"))
