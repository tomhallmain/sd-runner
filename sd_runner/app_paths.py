"""Where SD Runner's files live.

Bundled read-only files resolve through ``resource_path``: in a checkout that
is the repo, in a compiled build the folder the executable unpacks to, where
``build_exe.py`` places them at the same relative paths. Everything the app
writes lives in the app data dir (``lib.logging_setup.app_data_dir``) in a
checkout as well as a build, so the two share configuration and cache.

Nothing here imports from ``sd_runner``: modules across the package resolve
their paths through this one.
"""

import os
import shutil
import threading

from lib.logging_setup import adopt_legacy_file, app_data_dir, get_logger

logger = get_logger("app_paths")

#: The repo checkout, or the folder a compiled build runs from.
RESOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Where earlier versions wrote user files. In a build it holds only bundled
#: files, which is why nothing is migrated from it there.
REPO_ROOT = RESOURCE_ROOT
#: Nuitka defines __compiled__ in every module it compiles.
IS_BUILD = "__compiled__" in globals()

_seeded: set = set()
_seed_lock = threading.Lock()


def resource_path(*parts: str) -> str:
    """Absolute path of a bundled, read-only file or folder."""
    return os.path.join(RESOURCE_ROOT, *parts)


def user_data_path(*parts: str) -> str:
    """Absolute path under the app data dir; the dir itself is created."""
    return os.path.join(str(app_data_dir()), *parts)


def cache_dir() -> str:
    """SD_RUNNER_CACHE_DIR if set, else ``<app data>/cache``; created."""
    path = os.environ.get("SD_RUNNER_CACHE_DIR") or user_data_path("cache")
    os.makedirs(path, exist_ok=True)
    return path


def legacy_migration_allowed(override_var: str = "SD_RUNNER_CACHE_DIR") -> bool:
    """Whether a file at a legacy repo location may be moved into the app data
    dir: only from a checkout, and not while *override_var*, the variable that
    relocates that file, points elsewhere (tests and the build's smoke test)."""
    return not IS_BUILD and not os.environ.get(override_var)


def adopt_legacy_repo_file(legacy_relpath: str, target_path: str,
                           override_var: str = "SD_RUNNER_CACHE_DIR") -> None:
    """Move ``<repo>/<legacy_relpath>`` to *target_path* when migration is allowed."""
    if legacy_migration_allowed(override_var):
        adopt_legacy_file(os.path.join(REPO_ROOT, legacy_relpath), target_path)


def resolve_user_path(path: str) -> str:
    """*path* if absolute, else the same path under the app data dir.

    Relative paths from the configuration would otherwise depend on the
    working directory, which for an executable depends on how it was started.
    """
    if os.path.isabs(path):
        return path
    return os.path.normpath(user_data_path(path))


def concepts_dir(name: str) -> str:
    """The folder of the bundled concept set *name* (e.g. ``concepts``) that
    the app reads and the concept editor writes.

    In a checkout that is the repo's folder. In a build the bundled folder is
    replaced with every build, so the set is copied into the app data dir and
    used from there: lists missing there are copied in, existing ones are
    never overwritten.
    """
    bundled = resource_path(name)
    if not IS_BUILD:
        return bundled
    target = user_data_path(name)
    with _seed_lock:
        if name not in _seeded:
            _seeded.add(name)
            _seed_concepts(bundled, target)
    return target


def _seed_concepts(bundled: str, target: str) -> None:
    try:
        names = sorted(os.listdir(bundled))
    except OSError as e:
        logger.error(f"Could not list bundled concepts in {bundled}: {e}")
        return
    os.makedirs(target, exist_ok=True)
    copied = 0
    for name in names:
        src = os.path.join(bundled, name)
        dest = os.path.join(target, name)
        if not os.path.isfile(src) or os.path.lexists(dest):
            continue
        try:
            shutil.copy2(src, dest)
            copied += 1
        except OSError as e:
            logger.error(f"Could not copy {src} to {dest}: {e}")
    if copied:
        logger.info(f"Copied {copied} bundled concept files into {target}")
