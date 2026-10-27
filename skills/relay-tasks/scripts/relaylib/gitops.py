"""Create the feature branch in each code repo.

Safety rules: only ever creates a new branch and pushes that one branch. Never checks out,
never merges, never pushes to the base branch or any branch that already exists.
"""

import subprocess
from pathlib import Path

PROTECTED = {"main", "master", "dev", "develop", "development", "release", "staging", "production"}


class GitError(Exception):
    pass


def git(path, *args, timeout=120):
    try:
        out = subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True,
                             timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise GitError("git %s failed: %s" % (" ".join(args), e))
    return out.returncode, (out.stdout or "").strip(), (out.stderr or "").strip()


def is_repo(path):
    return Path(path).is_dir() and git(path, "rev-parse", "--is-inside-work-tree")[0] == 0


def has_remote(path, remote="origin"):
    return git(path, "remote", "get-url", remote)[0] == 0


def local_branch_exists(path, name):
    return git(path, "rev-parse", "--verify", "--quiet", "refs/heads/" + name)[0] == 0


def remote_branch_exists(path, name, remote="origin"):
    code, out, _ = git(path, "ls-remote", "--heads", remote, "refs/heads/" + name)
    return code == 0 and bool(out)


def safe_name(name, base):
    if name == base or (name or "").lower() in PROTECTED:
        return "Branch name '%s' is a protected branch. Relay never writes to it." % name
    if not name or "/" not in name:
        return "Branch name '%s' must have a prefix like feature/." % name
    if git(".", "check-ref-format", "refs/heads/" + name)[0] != 0:
        return "'%s' is not a valid branch name." % name
    return None


def create_branch(path, name, base, push=True, remote="origin"):
    """Returns {"status": created | exists | failed, "message": ...}."""
    problem = safe_name(name, base)
    if problem:
        return {"status": "failed", "message": problem}
    if not is_repo(path):
        return {"status": "failed", "message": "%s is not a git repo" % path}

    online = has_remote(path, remote)
    if online:
        code, _, err = git(path, "fetch", remote, base)
        if code != 0:
            return {"status": "failed", "message": "could not fetch %s from %s: %s" % (base, remote, err)}
        if remote_branch_exists(path, name, remote):
            return {"status": "exists", "message": "already on %s, left as is" % remote}
    if local_branch_exists(path, name):
        return {"status": "exists", "message": "already exists locally, left as is (not pushed)"}

    start = "%s/%s" % (remote, base) if online else base
    if git(path, "rev-parse", "--verify", "--quiet", start + "^{commit}")[0] != 0:
        return {"status": "failed", "message": "base branch %s not found" % start}
    code, _, err = git(path, "branch", "--no-track", name, start)
    if code != 0:
        return {"status": "failed", "message": "git branch failed: %s" % err}

    if not online:
        return {"status": "created", "message": "created from %s (no remote, not pushed)" % start}
    if not push:
        return {"status": "created", "message": "created from %s (not pushed: --no-push)" % start}
    code, _, err = git(path, "push", "--set-upstream", remote, "refs/heads/%s:refs/heads/%s" % (name, name))
    if code != 0:
        return {"status": "failed", "message": "created locally but push failed: %s" % err}
    return {"status": "created", "message": "created from %s and pushed to %s" % (start, remote)}
