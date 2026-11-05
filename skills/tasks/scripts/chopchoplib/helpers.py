"""Helper (subagent) settings from chopchop.yaml, and how many helpers a job gets.

  agents:
    max: 3            # most helpers at the same time. 0 = no helpers
    model: inherit    # inherit, sonnet, opus, haiku or fable
    effort: inherit   # inherit, low, medium, high, xhigh or max
    roles:            # optional, per role
      explorer: {model: haiku}

"inherit" means: leave the setting out, so the helper runs like the main chat. A per-call
model can only be an alias (sonnet, opus, haiku, fable), so full model ids are not allowed.
"""

import re
from pathlib import Path

MODELS = ["inherit", "sonnet", "opus", "haiku", "fable"]
EFFORTS = ["inherit", "low", "medium", "high", "xhigh", "max"]
ROLES = ["explorer", "architect", "reviewer", "verifier"]
DEFAULT_MAX = 3
MAX_LIMIT = 20  # Claude Code runs at most 20 subagents at once by default
SIZES = ["small", "medium", "large"]


def settings(cfg):
    """Returns {"set", "max", "model", "effort", "roles", "problems"}. Bad values fall back to defaults."""
    raw = (cfg or {}).get("agents")
    out = {"set": isinstance(raw, dict), "max": DEFAULT_MAX, "model": "inherit", "effort": "inherit",
           "roles": {}, "problems": []}
    if not isinstance(raw, dict):
        return out
    mx = raw.get("max")
    if isinstance(mx, bool) or not isinstance(mx, int) or not 0 <= mx <= MAX_LIMIT:
        if mx is not None:
            out["problems"].append("agents.max must be a whole number from 0 to %d (got %r)" % (MAX_LIMIT, mx))
    else:
        out["max"] = mx
    for key, allowed in (("model", MODELS), ("effort", EFFORTS)):
        val = raw.get(key)
        if val is None:
            continue
        if str(val) in allowed:
            out[key] = str(val)
        else:
            out["problems"].append("agents.%s must be one of %s (got %r)" % (key, ", ".join(allowed), val))
    roles = raw.get("roles") or {}
    if not isinstance(roles, dict):
        out["problems"].append("agents.roles must be a map, such as explorer: {model: haiku}")
        roles = {}
    for role, conf in roles.items():
        if role not in ROLES:
            out["problems"].append("agents.roles.%s is not a role. Roles: %s" % (role, ", ".join(ROLES)))
            continue
        if not isinstance(conf, dict):
            out["problems"].append("agents.roles.%s must be a map, such as {model: haiku}" % role)
            continue
        clean = {}
        for key, allowed in (("model", MODELS), ("effort", EFFORTS)):
            if conf.get(key) is None:
                continue
            if str(conf[key]) in allowed:
                clean[key] = str(conf[key])
            else:
                out["problems"].append("agents.roles.%s.%s must be one of %s" % (role, key, ", ".join(allowed)))
        out["roles"][role] = clean
    return out


def for_role(s, role):
    """What to pass on the Agent call for one role. None means: leave the parameter out."""
    conf = s["roles"].get(role, {})
    model = conf.get("model", s["model"])
    effort = conf.get("effort", s["effort"])
    return {"model": None if model == "inherit" else model, "effort": None if effort == "inherit" else effort}


def describe(s):
    """One sentence: which model and effort the helpers run on."""
    model = "the same model as this chat" if s["model"] == "inherit" else s["model"]
    effort = "the default effort" if s["effort"] == "inherit" else "effort " + s["effort"]
    text = "They run on %s, %s." % (model, effort)
    extra = []
    for role in ROLES:
        conf = s["roles"].get(role) or {}
        parts = [conf["model"]] if conf.get("model") else []
        parts += ["effort " + conf["effort"]] if conf.get("effort") else []
        if parts:
            extra.append("%s on %s" % (role, ", ".join(parts)))
    if extra:
        text += " Except: %s." % "; ".join(extra)
    if not s["set"]:
        text += " Helper settings are not saved yet: ask the 3 helper questions before starting any helper."
    return text


def plan(size, repos, s, choices=True):
    """How many helpers of each role a job gets. max is a ceiling, not a target.

    small:  chopchop reads the code itself, 1 reviewer.
    medium: 1 explorer per repo, 1 architect when there are real choices, 2 reviewers.
    large:  1 explorer per repo, 1 architect, 4 reviewers.
    """
    if size not in SIZES:
        raise ValueError("size must be one of %s" % ", ".join(SIZES))
    if s["max"] == 0:
        return {"explorer": 0, "architect": 0, "reviewer": 0, "at_once": 0, "rounds": 0,
                "line": "No helpers (agents.max is 0). chopchop does every step itself."}
    explore = 0 if size == "small" else len(repos)
    architect = 0 if size == "small" or not choices else 1
    review = {"small": 1, "medium": 2, "large": 4}[size]
    widest = max(explore, review, architect)
    at_once = min(s["max"], widest)
    rounds = -(-explore // at_once) if explore and at_once else 0
    parts = []
    if explore:
        parts.append("%d explorer%s (%s)" % (explore, "" if explore == 1 else "s", ", ".join(repos)))
    if architect:
        parts.append("1 architect")
    parts.append("%d reviewer%s" % (review, "" if review == 1 else "s"))
    total = explore + architect + review
    line = "Using %d helper%s: %s." % (total, "" if total == 1 else "s", ", ".join(parts))
    if explore > at_once:
        line += " At most %d at once, so the explorers run in %d turns." % (at_once, rounds)
    line += " " + describe(s)
    return {"explorer": explore, "architect": architect, "reviewer": review, "at_once": at_once,
            "rounds": rounds, "line": line}


# --------------------------------------------------------------------------- chopchop.yaml


def render_block(mx, model, effort, roles=None):
    lines = ["# Helpers (subagents). max is a ceiling: chopchop uses only as many as a job needs.",
             "agents:",
             "  max: %d            # most helpers at the same time. 0 = no helpers" % mx,
             "  model: %s    # inherit, sonnet, opus, haiku or fable" % model,
             "  effort: %s   # inherit, low, medium, high, xhigh or max" % effort]
    if roles:
        lines.append("  roles:")
        for role in ROLES:
            conf = roles.get(role)
            if conf:
                inner = ", ".join("%s: %s" % (k, conf[k]) for k in ("model", "effort") if conf.get(k))
                lines.append("    %s: {%s}" % (role, inner))
    return "\n".join(lines) + "\n"


def check_values(mx, model, effort, roles=None):
    problems = settings({"agents": {"max": mx, "model": model, "effort": effort, "roles": roles or {}}})["problems"]
    if problems:
        raise ValueError("; ".join(problems))


def write_block(cfg_path, mx, model, effort, roles=None):
    """Replace (or add) the top-level agents: block in chopchop.yaml. Other text stays as it is."""
    check_values(mx, model, effort, roles)
    path = Path(cfg_path)
    original = path.read_text(encoding="utf-8")
    path.with_name(path.name + ".bak").write_text(original, encoding="utf-8")
    lines = original.split("\n")
    start = next((i for i, l in enumerate(lines) if re.match(r"^agents\s*:", l)), None)
    if start is not None:
        end = start + 1
        while end < len(lines) and (not lines[end].strip() or lines[end][:1] in " \t"):
            end += 1
        while start > 0 and lines[start - 1].startswith("#"):
            start -= 1  # its comment lines go too
        while end > start and not lines[end - 1].strip():
            end -= 1
        lines[start:end] = render_block(mx, model, effort, roles).rstrip("\n").split("\n")
        text = "\n".join(lines)
    else:
        text = "\n".join(lines).rstrip("\n") + "\n\n" + render_block(mx, model, effort, roles)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    return str(path)
