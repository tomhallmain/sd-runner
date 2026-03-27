"""
Per-process sleep / idle inhibition with **granular wake levels**, reference
counting, and shared **machine-local** JSON state (not in the application
repository).

Wake levels use ``enum.IntFlag`` (**bit flags**): independent booleans packed in
an integer, combined with **bitwise OR** (``|``) and tested with ``&``. That
matches how Win32 execution-state flags are composed.

NOTE: To run the tests, run ``python -m lib.sleep_prevention`` from the repo root.

**Semantics**

* ``WakeLevel.SYSTEM`` — resist idle/system sleep paths (platform-specific).
* ``WakeLevel.DISPLAY`` — keep the display awake; **implies** ``SYSTEM`` in the
  **effective** mask (requesting the display without system is meaningless).

* ``WakeLevel.FULL`` (``SYSTEM | DISPLAY``) — default for :func:`prevent_sleep`
  and legacy :func:`acquire` / :func:`release`.

**OS hooks** are owned by *this process only*. File totals do not defer
``release_wake`` for other PIDs.

**Shared JSON** (see :func:`state_path`, :func:`state_dir`), version 3:

* Top-level keys are **application IDs** (e.g. ``sd_runner``), not
  ``app:pid`` strings.
* Under each app, **process id strings** hold per-PID state so dead processes
  can be pruned and this PID's row reset on bootstrap:

  * ``prevention_requests[app_id][pid_str]`` — map of capability name → refcount
    (``SYSTEM``, ``DISPLAY`` only).
  * ``capable_instances[app_id][pid_str]`` — ``1`` while the process is alive.

* ``totals`` — recomputed aggregate prevention refcount sums and capable PID
  count.

If the state file or lock is unavailable, local acquire/release still work;
file updates are skipped (debug log).
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from enum import IntFlag
from typing import Any, Dict, Iterator, Optional, Tuple

from utils.logging_setup import get_logger

logger = get_logger("sleep_prevention")

# How often to re-apply Windows flags (some environments reset them over time).
_REFRESH_INTERVAL_SEC = 60.0

_STATE_VERSION = 3

_lock = threading.Lock()
_bootstrapped = False

# Local refcount buckets (primitive capabilities only, not implied SYSTEM from DISPLAY).
_local_refs: Dict[str, int] = {"SYSTEM": 0, "DISPLAY": 0}
_prev_effective: Optional[WakeLevel] = None

_darwin_proc: Optional[subprocess.Popen] = None
_linux_proc: Optional[subprocess.Popen] = None
_last_darwin_argv: Optional[Tuple[str, ...]] = None
_last_linux_what: Optional[str] = None

_refresh_stop = threading.Event()
_refresh_thread: Optional[threading.Thread] = None


class WakeLevel(IntFlag):
    """Bit-flag wake / inhibition request (combine with ``|``)."""

    NONE = 0
    SYSTEM = 0x1
    DISPLAY = 0x2
    FULL = SYSTEM | DISPLAY


def _app_identifier() -> str:
    """Avoid importing ``utils.globals`` at module load (circular import with ``utils.utils``)."""
    try:
        from utils.globals import Globals

        return Globals.APP_IDENTIFIER
    except Exception:
        return "sd_runner"


def state_dir() -> str:
    """Directory for sleep-prevention JSON + lock (user / machine-local, not the repo)."""
    app = _app_identifier()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
        path = os.path.join(base, app, "sleep_prevention")
    elif sys.platform == "darwin":
        path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", app, "sleep_prevention")
    else:
        xdg = os.environ.get("XDG_STATE_HOME")
        if xdg:
            path = os.path.join(xdg, app, "sleep_prevention")
        else:
            path = os.path.join(os.path.expanduser("~"), ".local", "state", app, "sleep_prevention")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        logger.debug("sleep_prevention state_dir makedirs failed: %s", e)
    return path


def state_path() -> str:
    """Path to the shared JSON state file."""
    return os.path.join(state_dir(), "state.json")


def _lock_path() -> str:
    return os.path.join(state_dir(), "state.lock")


def _empty_state() -> Dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "prevention_requests": {},
        "capable_instances": {},
        "totals": {"prevention_requests": 0, "capable_instances": 0},
    }


def _capability_keys() -> Tuple[str, str]:
    return ("SYSTEM", "DISPLAY")


def _normalize_requested(level: WakeLevel) -> WakeLevel:
    """Restrict to supported bits; collapse ``SYSTEM|DISPLAY`` to ``FULL``."""
    w = WakeLevel(level) & WakeLevel.FULL
    if w == WakeLevel.FULL:
        return WakeLevel.FULL
    return w


def effective_wake(refs: Optional[Dict[str, int]] = None) -> WakeLevel:
    """Effective mask: DISPLAY implies SYSTEM."""
    if refs is None:
        refs = dict(_local_refs)
    sys_n = int(refs.get("SYSTEM", 0) or 0)
    dsp_n = int(refs.get("DISPLAY", 0) or 0)
    eff = WakeLevel.NONE
    if sys_n > 0:
        eff |= WakeLevel.SYSTEM
    if dsp_n > 0:
        eff |= WakeLevel.SYSTEM | WakeLevel.DISPLAY
    return eff


def _apply_ref_delta(level: WakeLevel, delta: int) -> None:
    """Update primitive refcount buckets for one acquire (delta=+1) or release (-1)."""
    n = _normalize_requested(level)
    if n == WakeLevel.NONE or delta == 0:
        return
    if n == WakeLevel.FULL:
        _local_refs["SYSTEM"] = max(0, _local_refs["SYSTEM"] + delta)
        _local_refs["DISPLAY"] = max(0, _local_refs["DISPLAY"] + delta)
        return
    if n & WakeLevel.DISPLAY:
        _local_refs["DISPLAY"] = max(0, _local_refs["DISPLAY"] + delta)
    if n & WakeLevel.SYSTEM and not (n & WakeLevel.DISPLAY):
        _local_refs["SYSTEM"] = max(0, _local_refs["SYSTEM"] + delta)


def _pid_str() -> str:
    return str(os.getpid())


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            kernel32.CloseHandle(h)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _coerce_nested_process_maps(raw_pr: Any) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Normalize ``prevention_requests[app_id][pid][cap]``."""
    if not isinstance(raw_pr, dict):
        return {}
    out: Dict[str, Dict[str, Dict[str, int]]] = {}
    for app_id, node in raw_pr.items():
        sa = str(app_id)
        if not isinstance(node, dict):
            continue
        per_pid: Dict[str, Dict[str, int]] = {}
        for pid_s, cap_map in node.items():
            ps = str(pid_s)
            if not ps.isdigit():
                continue
            if isinstance(cap_map, int):
                per_pid[ps] = _coerce_cap_map_from_int(cap_map)
            elif isinstance(cap_map, dict):
                per_pid[ps] = _coerce_capability_row(cap_map)
        if per_pid:
            out[sa] = _merge_pid_rows(out.get(sa, {}), per_pid)
    return out


def _merge_pid_rows(a: Dict[str, Dict[str, int]], b: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    merged = {k: dict(v) for k, v in a.items()}
    for pid, row in b.items():
        if pid not in merged:
            merged[pid] = dict(row)
        else:
            for ck, cv in row.items():
                merged[pid][ck] = merged[pid].get(ck, 0) + cv
    return merged


def _coerce_cap_map_from_int(n: int) -> Dict[str, int]:
    """Legacy single int → treat as FULL tier (both primitives)."""
    if n <= 0:
        return {"SYSTEM": 0, "DISPLAY": 0}
    return {"SYSTEM": n, "DISPLAY": n}


def _coerce_capability_row(m: Any) -> Dict[str, int]:
    row = {"SYSTEM": 0, "DISPLAY": 0}
    if not isinstance(m, dict):
        return row
    for k in _capability_keys():
        v = m.get(k, 0)
        try:
            row[k] = max(0, int(v))
        except (TypeError, ValueError):
            row[k] = 0
    return row


def _coerce_capable_maps(raw_ci: Any) -> Dict[str, Dict[str, int]]:
    if not isinstance(raw_ci, dict):
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for app_id, node in raw_ci.items():
        sa = app_id if isinstance(app_id, str) else str(app_id)
        if isinstance(node, dict) and node:
            if all(isinstance(v, int) for v in node.values()):
                first = next(iter(node.keys()))
                if isinstance(first, str) and first.isdigit():
                    out[sa] = {str(k): int(v) for k, v in node.items() if str(k).isdigit()}
                    continue
        if isinstance(node, int):
            if sa.isdigit() and node:
                out.setdefault(_app_identifier(), {})[sa] = 1
        elif isinstance(node, dict):
            for k, v in node.items():
                if str(k).isdigit():
                    out.setdefault(sa, {})[str(k)] = 1 if int(v) > 0 else 0
    return out


def _set_totals(data: Dict[str, Any]) -> None:
    pr = data.get("prevention_requests") or {}
    ci = data.get("capable_instances") or {}
    t_req = 0
    if isinstance(pr, dict):
        for _app, pmap in pr.items():
            if not isinstance(pmap, dict):
                continue
            for _pid, caps in pmap.items():
                if not isinstance(caps, dict):
                    continue
                for c in _capability_keys():
                    v = caps.get(c, 0)
                    if isinstance(v, int) and v > 0:
                        t_req += v
    t_cap = 0
    if isinstance(ci, dict):
        for _app, pmap in ci.items():
            if not isinstance(pmap, dict):
                continue
            for _pid, v in pmap.items():
                if isinstance(v, int) and v > 0 and str(_pid).isdigit():
                    t_cap += 1
    data["totals"] = {"prevention_requests": t_req, "capable_instances": t_cap}


def _migrate_v2_flat_maps(raw: Dict[str, Any]) -> Dict[str, Any]:
    """session_key -> int to v3 nested by app_id and pid."""
    pr_old = raw.get("prevention_requests")
    ci_old = raw.get("capable_instances")
    if not isinstance(pr_old, dict) or not pr_old:
        return raw
    first_k = next(iter(pr_old.keys()))
    if not isinstance(first_k, str) or ":" not in first_k:
        return raw
    pr_new: Dict[str, Dict[str, Dict[str, int]]] = {}
    for sk, val in pr_old.items():
        if not isinstance(sk, str) or ":" not in sk:
            continue
        app, tail = sk.rsplit(":", 1)
        if not tail.isdigit():
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        row = _coerce_cap_map_from_int(n)
        pr_new.setdefault(app, {})[tail] = row
    ci_new: Dict[str, Dict[str, int]] = {}
    if isinstance(ci_old, dict):
        for sk, val in ci_old.items():
            if not isinstance(sk, str) or ":" not in sk:
                continue
            app, tail = sk.rsplit(":", 1)
            if not tail.isdigit():
                continue
            try:
                vi = int(val)
            except (TypeError, ValueError):
                continue
            if vi > 0:
                ci_new.setdefault(app, {})[tail] = 1
    out = {
        "version": _STATE_VERSION,
        "prevention_requests": pr_new,
        "capable_instances": ci_new,
        "totals": {},
    }
    _set_totals(out)
    return out


def _migrate_legacy_sessions(raw: Dict[str, Any]) -> Dict[str, Any]:
    sessions = raw.get("sessions")
    if not isinstance(sessions, dict):
        return raw
    pr_new: Dict[str, Dict[str, Dict[str, int]]] = {}
    ci_new: Dict[str, Dict[str, int]] = {}
    for key, entry in sessions.items():
        if not isinstance(entry, dict):
            continue
        sk = key if isinstance(key, str) else str(key)
        if ":" not in sk:
            continue
        app, tail = sk.rsplit(":", 1)
        if not tail.isdigit():
            continue
        pid = entry.get("pid")
        pc = entry.get("prevention_count", 0)
        if isinstance(pc, int) and pc > 0:
            pr_new.setdefault(app, {})[tail] = _coerce_cap_map_from_int(pc)
        if isinstance(pid, int) and _pid_is_alive(pid):
            ci_new.setdefault(app, {})[str(pid)] = 1
    out = {
        "version": _STATE_VERSION,
        "prevention_requests": pr_new,
        "capable_instances": ci_new,
        "totals": {},
    }
    _set_totals(out)
    return out


def _normalize_state(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _empty_state()
    if "sessions" in raw and "prevention_requests" not in raw:
        raw = _migrate_legacy_sessions(raw)
    data = dict(raw)
    pr_raw = data.get("prevention_requests")
    if isinstance(pr_raw, dict) and pr_raw:
        sample_k, sample_v = next(iter(pr_raw.items()))
        if (
            isinstance(sample_v, int)
            and isinstance(sample_k, str)
            and ":" in sample_k
        ):
            data = _migrate_v2_flat_maps(data)
    try:
        vnum = int(data.get("version") or 0)
    except (TypeError, ValueError):
        vnum = 0
    data["version"] = max(vnum, _STATE_VERSION)
    data["prevention_requests"] = _coerce_nested_process_maps(data.get("prevention_requests", {}))
    data["capable_instances"] = _coerce_capable_maps(data.get("capable_instances", {}))
    data.pop("sessions", None)
    _set_totals(data)
    return data


@contextmanager
def _file_lock() -> Iterator[None]:
    """Exclusive lock for read-modify-write on the state file."""
    lp = _lock_path()
    try:
        os.makedirs(os.path.dirname(lp) or ".", exist_ok=True)
    except OSError:
        pass
    try:
        lock_f = open(lp, "a+b")
    except OSError as e:
        logger.debug("sleep_prevention lock open failed: %s", e)
        yield
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            lock_f.seek(0)
            msvcrt.locking(lock_f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt

                lock_f.seek(0)
                msvcrt.locking(lock_f.fileno(), msvcrt.LK_UNLOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_f.close()


def _load_state_unlocked(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return _empty_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return _normalize_state(raw)
    except Exception as e:
        logger.debug("sleep_prevention load failed, resetting: %s", e)
        return _empty_state()


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _prune_nested_maps(prevention_requests: Dict[str, Any], capable_instances: Dict[str, Any]) -> None:
    for app_id in list(prevention_requests.keys()):
        pmap = prevention_requests.get(app_id)
        if not isinstance(pmap, dict):
            prevention_requests.pop(app_id, None)
            continue
        for pid_s in list(pmap.keys()):
            if not str(pid_s).isdigit():
                pmap.pop(pid_s, None)
                continue
            pid = int(pid_s)
            if not _pid_is_alive(pid):
                pmap.pop(pid_s, None)
        if not pmap:
            prevention_requests.pop(app_id, None)
    for app_id in list(capable_instances.keys()):
        cmap = capable_instances.get(app_id)
        if not isinstance(cmap, dict):
            capable_instances.pop(app_id, None)
            continue
        for pid_s in list(cmap.keys()):
            if not str(pid_s).isdigit():
                cmap.pop(pid_s, None)
                continue
            if not _pid_is_alive(int(pid_s)):
                cmap.pop(pid_s, None)
        if not cmap:
            capable_instances.pop(app_id, None)


def _ensure_row(
    prevention_requests: Dict[str, Any], app_id: str, pid_s: str
) -> Dict[str, int]:
    app_map: Dict[str, Any] = prevention_requests.setdefault(app_id, {})
    raw = app_map.get(pid_s)
    row = _coerce_capability_row(raw if isinstance(raw, dict) else {})
    app_map[pid_s] = row
    return row


def _bootstrap_file_state() -> None:
    global _prev_effective
    path = state_path()
    app_id = _app_identifier()
    pid_s = _pid_str()
    total_prev = 0
    try:
        with _file_lock():
            data = _load_state_unlocked(path)
            pr = data["prevention_requests"]
            ci = data["capable_instances"]
            _prune_nested_maps(pr, ci)
            row = _ensure_row(pr, app_id, pid_s)
            row["SYSTEM"] = 0
            row["DISPLAY"] = 0
            if not row["SYSTEM"] and not row["DISPLAY"]:
                pr.get(app_id, {}).pop(pid_s, None)
                if app_id in pr and not pr[app_id]:
                    pr.pop(app_id, None)
            ci.setdefault(app_id, {})[pid_s] = 1
            _set_totals(data)
            total_prev = int(data["totals"]["prevention_requests"])
            _atomic_write_json(path, data)
    except Exception as e:
        logger.debug("sleep_prevention bootstrap write skipped: %s", e)
        return

    _prev_effective = None
    if total_prev == 0:
        _apply_os(WakeLevel.NONE)


def _persist_capabilities_delta(level: WakeLevel, delta: int) -> None:
    if delta == 0:
        return
    path = state_path()
    app_id = _app_identifier()
    pid_s = _pid_str()
    n = _normalize_requested(level)
    caps_to_touch: list[str] = []
    if n == WakeLevel.FULL:
        caps_to_touch = ["SYSTEM", "DISPLAY"]
    else:
        if n & WakeLevel.DISPLAY:
            caps_to_touch.append("DISPLAY")
        if n & WakeLevel.SYSTEM and not (n & WakeLevel.DISPLAY):
            caps_to_touch.append("SYSTEM")
    if not caps_to_touch:
        return
    try:
        with _file_lock():
            data = _load_state_unlocked(path)
            pr = data["prevention_requests"]
            ci = data["capable_instances"]
            _prune_nested_maps(pr, ci)
            row = _ensure_row(pr, app_id, pid_s)
            ci.setdefault(app_id, {})[pid_s] = 1
            for c in caps_to_touch:
                cur = int(row.get(c, 0) or 0)
                row[c] = max(0, cur + delta)
            empty = row["SYSTEM"] == 0 and row["DISPLAY"] == 0
            if empty:
                pr.get(app_id, {}).pop(pid_s, None)
                if app_id in pr and not pr[app_id]:
                    pr.pop(app_id, None)
            _set_totals(data)
            _atomic_write_json(path, data)
    except Exception as e:
        logger.debug("sleep_prevention persist failed: %s", e)


def _clear_session_row_best_effort() -> None:
    path = state_path()
    app_id = _app_identifier()
    pid_s = _pid_str()
    try:
        with _file_lock():
            data = _load_state_unlocked(path)
            pr = data["prevention_requests"]
            ci = data["capable_instances"]
            if isinstance(pr.get(app_id), dict):
                pr[app_id].pop(pid_s, None)
                if not pr[app_id]:
                    pr.pop(app_id, None)
            if isinstance(ci.get(app_id), dict):
                ci[app_id].pop(pid_s, None)
                if not ci[app_id]:
                    ci.pop(app_id, None)
            _set_totals(data)
            _atomic_write_json(path, data)
    except Exception as e:
        logger.debug("sleep_prevention atexit state write failed: %s", e)


def _ensure_bootstrap() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    with _lock:
        if _bootstrapped:
            return
        _bootstrap_file_state()
        _bootstrapped = True


def _windows_available() -> bool:
    return sys.platform == "win32"


def _win_apply(effective: WakeLevel) -> None:
    if not _windows_available():
        return
    try:
        from ctypes import WinDLL

        ES_SYSTEM_REQUIRED = 0x0001
        ES_DISPLAY_REQUIRED = 0x0002
        ES_CONTINUOUS = 0x8000_0000
        kernel32 = WinDLL("kernel32", use_last_error=True)
        if effective == WakeLevel.NONE:
            kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            return
        flags = ES_CONTINUOUS
        if effective & WakeLevel.SYSTEM:
            flags |= ES_SYSTEM_REQUIRED
        if effective & WakeLevel.DISPLAY:
            flags |= ES_DISPLAY_REQUIRED
        kernel32.SetThreadExecutionState(flags)
    except Exception as e:
        logger.debug("Windows sleep prevention failed: %s", e)


def _darwin_argv_for(effective: WakeLevel) -> Optional[Tuple[str, ...]]:
    exe = shutil.which("caffeinate")
    if not exe:
        logger.debug("caffeinate not found; macOS sleep prevention unavailable")
        return None
    if effective == WakeLevel.NONE:
        return None
    # -i idle, -s system sleep (on AC), -d display; -m disk spins (legacy parity with previous module)
    if effective & WakeLevel.DISPLAY:
        return (exe, "-dims")
    return (exe, "-is")


def _darwin_apply(effective: WakeLevel) -> None:
    global _darwin_proc, _last_darwin_argv
    desired = _darwin_argv_for(effective)
    if desired == _last_darwin_argv and _darwin_proc and _darwin_proc.poll() is None:
        return
    if _darwin_proc is not None:
        try:
            _darwin_proc.terminate()
            try:
                _darwin_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                _darwin_proc.kill()
        except Exception as e:
            logger.debug("Error stopping caffeinate: %s", e)
        finally:
            _darwin_proc = None
            _last_darwin_argv = None
    if not desired:
        return
    try:
        _darwin_proc = subprocess.Popen(
            list(desired),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        _last_darwin_argv = desired
    except Exception as e:
        logger.debug("Failed to start caffeinate: %s", e)
        _darwin_proc = None
        _last_darwin_argv = None


def _linux_what_for(_effective: WakeLevel) -> str:
    # ``systemd-inhibit`` does not mirror Win32 display vs system split. Using a
    # single stable ``--what`` avoids optional tokens (e.g. lid-switch) that
    # vary by systemd version or policy.
    return "idle:sleep"


def _linux_apply(effective: WakeLevel) -> None:
    global _linux_proc, _last_linux_what
    if effective == WakeLevel.NONE:
        if _linux_proc is not None:
            try:
                _linux_proc.terminate()
                try:
                    _linux_proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    _linux_proc.kill()
            except Exception as e:
                logger.debug("Error stopping systemd-inhibit: %s", e)
            finally:
                _linux_proc = None
                _last_linux_what = None
        return
    exe = shutil.which("systemd-inhibit")
    if not exe:
        logger.debug("systemd-inhibit not found; Linux sleep prevention unavailable")
        return
    what = _linux_what_for(effective)
    if what == _last_linux_what and _linux_proc and _linux_proc.poll() is None:
        return
    if _linux_proc is not None:
        try:
            _linux_proc.terminate()
            try:
                _linux_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                _linux_proc.kill()
        except Exception as e:
            logger.debug("Error restarting systemd-inhibit: %s", e)
        finally:
            _linux_proc = None
    try:
        _linux_proc = subprocess.Popen(
            [
                exe,
                f"--what={what}",
                f"--who={_app_identifier()}",
                "--why=image-generation",
                "--mode=block",
                "sleep",
                "999999999",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        _last_linux_what = what
    except Exception as e:
        logger.debug("Failed to start systemd-inhibit: %s", e)
        _linux_proc = None
        _last_linux_what = None


def _apply_os(effective: WakeLevel) -> None:
    global _prev_effective
    if _prev_effective is not None and effective == _prev_effective:
        return
    _prev_effective = effective
    plat = sys.platform
    if plat == "win32":
        _win_apply(effective)
    elif plat == "darwin":
        _darwin_apply(effective)
    else:
        _linux_apply(effective)


def _refresh_worker() -> None:
    while not _refresh_stop.wait(timeout=_REFRESH_INTERVAL_SEC):
        with _lock:
            if effective_wake() == WakeLevel.NONE:
                break
        if sys.platform == "win32":
            _win_apply(effective_wake())


def _ensure_refresh_thread() -> None:
    global _refresh_thread
    if _refresh_thread is not None and _refresh_thread.is_alive():
        return
    _refresh_stop.clear()
    _refresh_thread = threading.Thread(target=_refresh_worker, name="sleep-prevention-refresh", daemon=True)
    _refresh_thread.start()


def _stop_refresh_thread() -> None:
    global _refresh_thread
    _refresh_stop.set()
    t = _refresh_thread
    _refresh_thread = None
    if t is not None and t.is_alive():
        t.join(timeout=2.0)


def acquire_wake(level: WakeLevel = WakeLevel.FULL) -> None:
    """Increment refcount for ``level``; update OS hooks from :func:`effective_wake`."""
    _ensure_bootstrap()
    with _lock:
        before = effective_wake()
        _apply_ref_delta(level, +1)
        after = effective_wake()
    if after != before:
        _apply_os(after)
    if sys.platform == "win32":
        if after != WakeLevel.NONE:
            _ensure_refresh_thread()
        elif after == WakeLevel.NONE:
            _stop_refresh_thread()
    _persist_capabilities_delta(level, +1)


def _can_release_wake(level: WakeLevel) -> bool:
    n = _normalize_requested(level)
    if n == WakeLevel.FULL:
        ok = _local_refs["SYSTEM"] > 0 and _local_refs["DISPLAY"] > 0
        if not ok:
            logger.debug("release_wake(FULL) with empty local refs; ignored")
        return ok
    if n & WakeLevel.DISPLAY:
        ok = _local_refs["DISPLAY"] > 0
        if not ok:
            logger.debug("release_wake(DISPLAY) with empty display refs; ignored")
        return ok
    if n & WakeLevel.SYSTEM:
        ok = _local_refs["SYSTEM"] > 0
        if not ok:
            logger.debug("release_wake(SYSTEM) with empty system refs; ignored")
        return ok
    return False


def release_wake(level: WakeLevel = WakeLevel.FULL) -> None:
    """Decrement refcount for ``level``; update OS hooks."""
    _ensure_bootstrap()
    with _lock:
        if not _can_release_wake(level):
            return
        before = effective_wake()
        _apply_ref_delta(level, -1)
        after = effective_wake()
    if after != before:
        _apply_os(after)
    if sys.platform == "win32" and after == WakeLevel.NONE:
        _stop_refresh_thread()
    _persist_capabilities_delta(level, -1)


def acquire() -> None:
    acquire_wake(WakeLevel.FULL)


def release() -> None:
    release_wake(WakeLevel.FULL)


def prevent_sleep(enable: bool) -> None:
    """Backward-compatible API: ``True`` → :func:`acquire` / ``WakeLevel.FULL``."""
    if enable:
        acquire()
    else:
        release()


def ref_count() -> int:
    """Sum of local primitive ref buckets (SYSTEM + DISPLAY counts, not implied duplicates)."""
    _ensure_bootstrap()
    with _lock:
        return int(_local_refs["SYSTEM"]) + int(_local_refs["DISPLAY"])


def aggregate_prevention_count() -> int:
    """``totals.prevention_requests`` from shared state after pruning dead PIDs."""
    _ensure_bootstrap()
    path = state_path()
    try:
        with _file_lock():
            data = _load_state_unlocked(path)
            _prune_nested_maps(data["prevention_requests"], data["capable_instances"])
            _set_totals(data)
            _atomic_write_json(path, data)
            return int(data["totals"]["prevention_requests"])
    except Exception as e:
        logger.debug("aggregate_prevention_count failed: %s", e)
        return ref_count()


def live_instance_count() -> int:
    """``totals.capable_instances`` from shared state after pruning dead PIDs."""
    _ensure_bootstrap()
    path = state_path()
    try:
        with _file_lock():
            data = _load_state_unlocked(path)
            _prune_nested_maps(data["prevention_requests"], data["capable_instances"])
            _set_totals(data)
            _atomic_write_json(path, data)
            return int(data["totals"]["capable_instances"])
    except Exception as e:
        logger.debug("live_instance_count failed: %s", e)
        return 1 if _bootstrapped else 0


def persisted_totals() -> Tuple[int, int]:
    """``(prevention_requests_total, capable_instances_total)`` from file (prunes + writes)."""
    _ensure_bootstrap()
    path = state_path()
    try:
        with _file_lock():
            data = _load_state_unlocked(path)
            _prune_nested_maps(data["prevention_requests"], data["capable_instances"])
            _set_totals(data)
            _atomic_write_json(path, data)
            t = data["totals"]
            return (int(t["prevention_requests"]), int(t["capable_instances"]))
    except Exception as e:
        logger.debug("persisted_totals failed: %s", e)
        return (ref_count(), 1 if _bootstrapped else 0)


def reset_state_for_application(app_id: Optional[str] = None) -> None:
    """
    Remove ``app_id`` from the shared JSON (default: current :func:`_app_identifier`),
    clear in-process refcounts, stop the refresh thread, and release OS inhibition.

    Next API use will bootstrap again (new capable row for this PID, etc.).
    """
    global _bootstrapped, _local_refs, _prev_effective
    aid = app_id if app_id is not None else _app_identifier()
    with _lock:
        _local_refs = {"SYSTEM": 0, "DISPLAY": 0}
        _bootstrapped = False
    _stop_refresh_thread()
    _apply_os(WakeLevel.NONE)
    _prev_effective = None
    path = state_path()
    try:
        with _file_lock():
            data = _load_state_unlocked(path)
            pr = data.get("prevention_requests")
            ci = data.get("capable_instances")
            if isinstance(pr, dict):
                pr.pop(aid, None)
            if isinstance(ci, dict):
                ci.pop(aid, None)
            _set_totals(data)
            _atomic_write_json(path, data)
    except Exception as e:
        logger.debug("reset_state_for_application file write failed: %s", e)


@contextmanager
def hold_wake(level: WakeLevel = WakeLevel.FULL):
    acquire_wake(level)
    try:
        yield
    finally:
        release_wake(level)


@contextmanager
def hold():
    acquire()
    try:
        yield
    finally:
        release()


def _atexit() -> None:
    global _local_refs, _prev_effective
    with _lock:
        leaked_sys = _local_refs["SYSTEM"]
        leaked_dsp = _local_refs["DISPLAY"]
    if leaked_sys or leaked_dsp:
        logger.warning(
            "sleep_prevention: exiting with local SYSTEM=%s DISPLAY=%s; clearing hooks + file row",
            leaked_sys,
            leaked_dsp,
        )
        with _lock:
            _local_refs = {"SYSTEM": 0, "DISPLAY": 0}
            _stop_refresh_thread()
            _apply_os(WakeLevel.NONE)
            _prev_effective = None
    _clear_session_row_best_effort()


atexit.register(_atexit)


__all__ = [
    "WakeLevel",
    "acquire",
    "release",
    "acquire_wake",
    "release_wake",
    "prevent_sleep",
    "hold",
    "hold_wake",
    "effective_wake",
    "ref_count",
    "aggregate_prevention_count",
    "live_instance_count",
    "persisted_totals",
    "reset_state_for_application",
    "state_path",
    "state_dir",
]


if __name__ == "__main__":
    # Allow ``python lib/sleep_prevention.py`` (repo root resolves ``utils``, etc.).
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    # Smoke tests (run from repo root).
    assert WakeLevel.FULL == WakeLevel.SYSTEM | WakeLevel.DISPLAY

    acquire_wake(WakeLevel.SYSTEM)
    assert effective_wake() & WakeLevel.SYSTEM
    release_wake(WakeLevel.SYSTEM)
    assert effective_wake() == WakeLevel.NONE

    acquire_wake(WakeLevel.DISPLAY)
    e = effective_wake()
    assert e & WakeLevel.DISPLAY and e & WakeLevel.SYSTEM
    release_wake(WakeLevel.DISPLAY)
    assert effective_wake() == WakeLevel.NONE

    acquire()
    assert ref_count() == 2
    release()
    assert ref_count() == 0

    acquire_wake(WakeLevel.FULL)
    acquire_wake(WakeLevel.FULL)
    assert ref_count() == 4
    release_wake(WakeLevel.FULL)
    release_wake(WakeLevel.FULL)
    assert ref_count() == 0

    with hold():
        assert ref_count() == 2
    assert ref_count() == 0

    assert effective_wake() == WakeLevel.NONE

    reset_state_for_application()

    print("All tests passed, state reset for application: " + _app_identifier())
