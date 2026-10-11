"""SD Runner's version, and what a compiled build records about itself.

``build_exe.py`` executes this file on its own, before anything else is
installed, so it imports nothing at load time (functions import what they
need).
"""

#: Up to four dot-separated numbers: Windows file version information
#: allows nothing else.
APP_VERSION = "1.0.0"

#: Written by build_exe.py and bundled at the resource root.
BUILD_INFO_FILE = "build_info.json"


def build_info() -> dict:
    """The build's recorded details (build id, interpreter, key package
    versions, source commit), or an empty dict in a source checkout."""
    import json
    import os

    from sd_runner.app_paths import resource_path

    path = resource_path(BUILD_INFO_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def describe() -> str:
    """One line naming the version and, in a build, the build id, the source
    commit and the versions it was built with."""
    try:
        info = build_info()
    except (OSError, ValueError) as e:
        return f"SD Runner {APP_VERSION} (build info unreadable: {e})"
    if not info:
        return f"SD Runner {APP_VERSION} (source checkout)"
    source = info.get("source", {})
    commit = source.get("commit")
    commit = commit[:10] if commit else "unknown commit"
    if source.get("changes"):
        commit += " with uncommitted changes"
    packages = ", ".join(f"{name} {version}" for name, version in sorted(info.get("packages", {}).items()))
    return f"SD Runner {APP_VERSION}, build {info.get('build_id', '?')} from {commit} ({packages})"


def read_git_commit(checkout: str) -> str:
    """The commit a git checkout has checked out, read from its .git
    directory without running git, or ""."""
    import os

    git_dir = os.path.join(checkout, ".git")
    try:
        with open(os.path.join(git_dir, "HEAD"), "r", encoding="utf-8") as f:
            head = f.read().strip()
        if not head.startswith("ref: "):
            return head
        ref = head[len("ref: "):]
        ref_path = os.path.join(git_dir, *ref.split("/"))
        if os.path.isfile(ref_path):
            with open(ref_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        with open(os.path.join(git_dir, "packed-refs"), "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except OSError:
        pass
    return ""


def run_git(repo: str, *args: str):
    """git's stdout for a command in *repo*, or None when git is not installed
    or the command fails."""
    import subprocess
    import sys

    # A windowed exe would otherwise flash a console window for git.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, encoding="utf-8", errors="replace",
            timeout=15, creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def source_state(repo: str) -> dict:
    """The checkout's commit, and a fingerprint of its uncommitted changes to
    tracked files ("" when there are none, None when git cannot tell)."""
    import hashlib

    commit = (run_git(repo, "rev-parse", "HEAD") or "").strip() or read_git_commit(repo)
    diff = run_git(repo, "diff", "HEAD", "--binary")
    if diff is None:
        changes = None
    else:
        changes = hashlib.sha1(diff.encode("utf-8")).hexdigest() if diff else ""
    return {"commit": commit, "changes": changes}


def source_drift():
    """In a build, compare the source it was built from with that checkout
    as it is now. Returns (drifted, message), or None in a source checkout
    or a build that recorded no source."""
    import os

    try:
        source = build_info().get("source")
    except (OSError, ValueError):
        return None
    if not source or not source.get("repo"):
        return None
    repo, built = source["repo"], source.get("commit") or ""
    if not os.path.isdir(os.path.join(repo, ".git")):
        return False, f"Source checkout {repo} not found; cannot compare it with this build."
    current = source_state(repo)
    if not built or not current["commit"]:
        return False, f"Commit unknown for this build or for {repo}; cannot compare."
    if current["commit"] == built:
        if current["changes"] is None or current["changes"] == source.get("changes"):
            return False, f"This build matches the source checkout {repo} ({built[:10]})."
        return True, (f"The source checkout {repo} is at this build's commit {built[:10]}, "
                      f"but its uncommitted changes differ from the build's.")
    newer = run_git(repo, "rev-list", "--count", f"{built}..{current['commit']}")
    missing = run_git(repo, "rev-list", "--count", f"{current['commit']}..{built}")
    if newer is None or missing is None:
        detail = "a different commit"
    else:
        detail = f"{int(newer)} commit(s) not in this build"
        if int(missing):
            detail += f", and lacks {int(missing)} commit(s) this build has"
    return True, (f"This build is from commit {built[:10]}; the source checkout {repo} is at "
                  f"{current['commit'][:10]}: {detail}.")
