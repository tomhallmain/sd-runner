"""Removes folders older builds unpacked to.

A onefile build unpacks to ``<app data>/unpacked/<prefix>-<build id>``
(``build_exe.py``), one folder per build and executable, and Nuitka never
removes them. Folders of the running build's own id are kept, the other
executable's included. A build runs its executable from its own folder, so a
folder holding the executable of a running process is skipped. On Windows each
folder is also renamed before it is deleted, which Windows refuses while a
running exe holds files in it; macOS and Linux allow that rename, so there
the process check alone decides, and nothing is removed when processes
cannot be listed.
"""

import os
import shutil
import sys
from typing import Optional

from lib.logging_setup import get_logger
from sd_runner.app_paths import IS_BUILD, RESOURCE_ROOT

logger = get_logger("runtime.unpack_cleanup")

#: The unpack folder prefixes build_exe.py gives its two executables. The
#: longer one first: a name is matched against the first that fits.
UNPACK_DIR_PREFIXES = ("sdrunner-headless-", "sdrunner-")
_REMOVING_SUFFIX = ".removing"
_IS_WINDOWS = sys.platform == "win32"


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _build_id(name: str) -> Optional[str]:
    """The build id in an unpack folder's name, or None for another folder."""
    if name.endswith(_REMOVING_SUFFIX):
        name = name[:-len(_REMOVING_SUFFIX)]
    for prefix in UNPACK_DIR_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return None


def _is_same_folder(a: str, b: str) -> bool:
    """Whether *a* and *b* are one folder. On Windows the build can see its own
    folder under its 8.3 short name while os.listdir returns the long one, so a
    string comparison alone would miss it."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return _normalize(a) == _normalize(b)


def _running_executables() -> Optional[set]:
    """Normalized executable paths of the running processes this user can
    see, or None when they cannot be listed."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        # A process this user may not inspect reports exe as None.
        return {_normalize(p.info["exe"]) for p in psutil.process_iter(["exe"]) if p.info.get("exe")}
    except Exception as e:
        logger.warning(f"Could not list running processes: {e}")
        return None


def _holds_running_executable(folder: str, executables: set) -> bool:
    prefix = _normalize(folder) + os.sep
    return any(exe.startswith(prefix) for exe in executables)


def remove_stale_unpack_dirs(resource_root: str = RESOURCE_ROOT, is_build: bool = IS_BUILD) -> list:
    """Delete unpack folders of other builds; returns the paths removed."""
    if not is_build:
        return []
    parent = os.path.dirname(os.path.normpath(resource_root))
    current_id = _build_id(os.path.basename(os.path.normpath(resource_root)))
    if os.path.basename(parent) != "unpacked" or current_id is None:
        logger.warning(f"Not cleaning up old build folders: {resource_root} is not an unpack folder")
        return []
    executables = _running_executables()
    if executables is None:
        if not _IS_WINDOWS:
            logger.info("Not cleaning up old build folders: running processes cannot be listed")
            return []
        executables = set()  # the rename alone guards running builds
    try:
        names = sorted(os.listdir(parent))
    except OSError as e:
        logger.error(f"Could not list {parent}: {e}")
        return []
    removed = []
    for name in names:
        path = os.path.join(parent, name)
        build_id = _build_id(name)
        if build_id is None or build_id == current_id or not os.path.isdir(path):
            continue
        if _is_same_folder(path, resource_root):
            continue
        if _holds_running_executable(path, executables):
            logger.info(f"Not removing {path}: a running build uses it")
            continue
        if not name.endswith(_REMOVING_SUFFIX):
            # Marks the folder so a delete cut short is finished at the next
            # start; on Windows, failing here also means it is in use.
            renamed = path + _REMOVING_SUFFIX
            try:
                os.rename(path, renamed)
            except OSError as e:
                logger.info(f"Not removing {path}, possibly in use: {e}")
                continue
            path = renamed
        shutil.rmtree(path, ignore_errors=True)
        if os.path.exists(path):
            logger.warning(f"Could not fully remove {path}; trying again at the next start")
        else:
            logger.info(f"Removed old build folder {path}")
            removed.append(path)
    return removed
