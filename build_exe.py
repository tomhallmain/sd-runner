"""
Build SD Runner with Nuitka: ``python build_exe.py``.

Nuitka compiles the code to C, then to a native executable that embeds the
Python runtime. Needs a C compiler: Xcode Command Line Tools on macOS; on
Windows, Visual Studio Build Tools, or Nuitka downloads MinGW itself. Nuitka
does not cross-compile, so run this on each target OS.

Builds inside a dedicated ``.venv-build`` at the repo root, populated from
requirements-build.txt, so packages from the active conda env or venv aren't
bundled. The venv is based on the interpreter running this script, and the
build embeds that interpreter's runtime, so run it with the development
Python (3.11). pip installs torch from PyPI there, which on Windows is the CPU
build; for CUDA torch, install it into .venv-build from the PyTorch index
first, or use ``--current-env``, which builds with the running interpreter
instead (it must already have requirements-build.txt installed).

Builds a single-file executable in dist/ (``.exe`` on Windows), SDRunner from
app_gui.py. ``--with-headless`` also builds SDRunnerHeadless from
app_headless.py, which serves the request front ends with no window and
contains no Qt; it takes about as long again. At its first start each unpacks its runtime to ``unpacked/<prefix>-<build id>`` in the SD
Runner app data directory; later starts of the same build reuse that folder,
and the app removes older builds' folders (sd_runner/runtime/unpack_cleanup.py).
Each is smoke-tested with ``--smoke-test``. Other args are forwarded to Nuitka,
e.g. ``--show-scons`` or ``--jobs=4``.

Before compressing the onefile payload, the last step of each compile, the
build waits for enough free memory (the memory-wait plugin, from
app-release when installed), since a failed allocation there loses the
whole compile. ``--min-free-memory=<GiB>``
sets the amount instead of the estimate; 0 turns the wait off. Each step is
timed, and the log goes to ``build/logs/build_exe-<build id>.log`` as well
(Nuitka's own output only to the console).

``--with-oqs`` adds quantum-safe (OQS) key encapsulation: it installs
liboqs-python, finds the liboqs shared library the build interpreter loads, and
bundles it. liboqs-python builds liboqs on first import if none is installed,
which needs git, CMake and a C compiler; or point OQS_INSTALL_PATH at an
existing install. Without the option the build has no OQS: it cannot read
data encrypted with OQS keys, and refuses password-protected actions when the
stored keys are OQS keys.

The executables' version information comes from the VERSION file at the repo
root, which is also bundled, with the build id (build time) in its
description. Each build writes ``build/nuitka/build_info.json`` (version, build
id, whether it has OQS, Python and key package versions, and this checkout's
path, commit, the commit's tree and a fingerprint of its uncommitted changes),
bundled so the app logs it at startup and compares itself with this checkout,
and ``build/nuitka/build-requirements.lock.txt``, the build venv's ``pip
freeze``. ``--lock=<file>`` installs the build venv from such a file instead of
requirements-build.txt, to repeat a known good build; packages already in the
venv but absent from the file stay installed, so delete .venv-build first for
an exact copy. app-release publishes the executables in dist/ as a GitHub
release.
"""
import contextlib
import json
import logging
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import venv

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(REPO_ROOT, ".venv-build")
BUILD_DIR = os.path.join(REPO_ROOT, "build", "nuitka")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
# lib.logging_setup.app_data_dir() spelled for Nuitka, which has no variable
# for %APPDATA%.
APP_DATA_SPEC = "{HOME}/AppData/Roaming/sd_runner" if sys.platform == "win32" else "{HOME}/.local/share/sd_runner"
LOCK_PATH = os.path.join(BUILD_DIR, "build-requirements.lock.txt")
VERSION_FILE = "VERSION"
VERSION_MODULE = os.path.join("sd_runner", "runtime", "version.py")
BUILD_INFO_PATH = os.path.join(BUILD_DIR, "build_info.json")
LOG_DIR = os.path.join(REPO_ROOT, "build", "logs")
# Set by app-release, which ships the memory-wait plugin, when it runs this script.
MEMORY_WAIT_PLUGIN_ENV = "NUITKA_MEMORY_WAIT_PLUGIN"
# Read by the memory-wait plugin.
MIN_FREE_MEMORY_ENV = "BUILD_MIN_FREE_MEMORY_GB"
# Versions the build output and build_info.json record.
RECORDED_DISTRIBUTIONS = (
    "Nuitka", "PySide6", "torch", "torchvision", "transformers", "onnxruntime", "mcp",
)
# Additions to Nuitka's own configuration for packages this build follows.
PACKAGE_CONFIG = os.path.join(REPO_ROOT, "nuitka-package.config.yml")
ICON_PNG = os.path.join("assets", "icon.png")
ICON_ICO = os.path.join(BUILD_DIR, "sd_runner_icon.ico")

# Shipped files, at the same relative paths the modules reading them resolve
# from their own location.
DATA_DIRS = (os.path.join("lib", "sounds"),)
DATA_FILES = (
    VERSION_FILE,
    ICON_PNG,
    os.path.join("sd_runner", "data", "blacklist_default.enc"),
    os.path.join("sd_runner", "data", "urban_dictionary.enc"),
    os.path.join("sd_runner", "data", "config_example.json"),
)
WORKFLOWS_DIR = os.path.join("sd_runner", "data", "workflows")
# test.json is the last prompt the app writes when save_last_prompt is on;
# stableDiffusion3* are not shipped (.gitignore).
WORKFLOWS_EXCLUDED = re.compile(r"^(test\.json|stableDiffusion3.*)$")
# The concept sets config.json can name by a relative path, every list in
# each, tracked or not; their subfolders hold editing and translation material.
CONCEPT_SET_DIRS = ("concepts", "Konzepte")

# lib/pillow_plugins.py imports these by name, which Nuitka can't follow.
PILLOW_PLUGINS = ("pillow_avif", "pillow_heif", "pillow_jxl")
# transformers reads the installed version of these packages when it finds
# them importable (_is_package_available(..., return_version=True)); without
# their metadata it imports the whole package to look for __version__, and
# Nuitka's own transformers configuration ends the process when that fails.
# Those of its probed packages that are in requirements-build.txt.
TRANSFORMERS_PROBED_DISTRIBUTIONS = ("huggingface_hub", "numpy", "torch", "torchvision")
# The transformers release the list above was taken from.
TRANSFORMERS_PROBED_VERSION = "5.19"

# Same source as requirements-optional.txt; not on PyPI.
LIBOQS_PYTHON = "git+https://github.com/open-quantum-safe/liboqs-python.git"
# Prints the path of the liboqs shared library liboqs-python loaded.
_LIBOQS_PROBE = (
    "import oqs.oqs as m\n"
    "lib = m.native() if hasattr(m, 'native') else m._liboqs\n"
    "print(lib._name)\n"
)
# Prints {"python": ..., "packages": {name: version}} for the names in argv.
_VERSIONS_PROBE = (
    "import json, sys\n"
    "from importlib.metadata import PackageNotFoundError, version\n"
    "def get(name):\n"
    "    try:\n"
    "        return version(name)\n"
    "    except PackageNotFoundError:\n"
    "        return None\n"
    "print(json.dumps({'python': sys.version.split()[0],\n"
    "                  'packages': {n: get(n) for n in sys.argv[1:]}}))\n"
)

logger = logging.getLogger("build_exe")


class _LevelPrefix(logging.Filter):
    def filter(self, record):
        record.level_prefix = "" if record.levelno == logging.INFO else f"{record.levelname}: "
        return True


def _setup_logging(build_id: str) -> str:
    """Log to the console and to a file for this build; returns the file's path."""
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"build_exe-{build_id}.log")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("[%(asctime)s] %(level_prefix)s%(message)s", "%H:%M:%S"))
    log_file = logging.FileHandler(path, encoding="utf-8")
    log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    for handler in (console, log_file):
        handler.addFilter(_LevelPrefix())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return path


def _duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


@contextlib.contextmanager
def _timed(step: str):
    """Log how long *step* took, or after how long it failed."""
    started = time.monotonic()
    logger.info(f"{step}...")
    try:
        yield
    except BaseException:
        logger.error(f"{step} failed after {_duration(time.monotonic() - started)}")
        raise
    logger.info(f"{step} done in {_duration(time.monotonic() - started)}")


def _exe_name(base_name: str) -> str:
    return f"{base_name}.exe" if sys.platform == "win32" else base_name


def _venv_python(venv_dir: str) -> str:
    if sys.platform == "win32":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _ensure_build_venv(extra_packages=(), requirements=None) -> str:
    """The build venv's interpreter, after installing *requirements*
    (requirements-build.txt by default, or a lock file) and *extra_packages*."""
    python = _venv_python(VENV_DIR)
    if not os.path.exists(python):
        logger.info(f"Creating build venv at {VENV_DIR}")
        venv.create(VENV_DIR, with_pip=True)
    requirements = requirements or os.path.join(REPO_ROOT, "requirements-build.txt")
    subprocess.run(
        [python, "-m", "pip", "install", "-q", "-r", requirements, *extra_packages],
        check=True,
    )
    return python


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_has(lock_path: str, distribution: str) -> bool:
    """Whether the lock file pins *distribution* (``name==...`` or ``name @ url``)."""
    with open(lock_path, "r", encoding="utf-8") as f:
        for line in f:
            name = re.split(r"[=@<>~!\s;\[]", line.strip(), maxsplit=1)[0]
            if name and _canonical_name(name) == _canonical_name(distribution):
                return True
    return False


def _write_lock_file(python: str) -> None:
    freeze = subprocess.run([python, "-m", "pip", "freeze"], capture_output=True, text=True, check=True)
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(freeze.stdout)
    logger.info(f"Build environment recorded in {LOCK_PATH}")


def _version_module() -> dict:
    """sd_runner/runtime/version.py's globals, loaded without importing the app."""
    return runpy.run_path(os.path.join(REPO_ROOT, VERSION_MODULE))


def _app_version() -> str:
    with open(os.path.join(REPO_ROOT, VERSION_FILE), "r", encoding="utf-8") as f:
        version = f.read().strip()
    if not re.fullmatch(r"\d+(\.\d+){0,3}", version):
        sys.exit(f"{VERSION_FILE} holds {version!r}; it must be up to four dot-separated numbers.")
    return version


def _environment_versions(python: str) -> dict:
    probe = subprocess.run(
        [python, "-c", _VERSIONS_PROBE, *RECORDED_DISTRIBUTIONS], capture_output=True, text=True, check=True,
    )
    return json.loads(probe.stdout.strip().splitlines()[-1])


def _check_transformers_version(packages: dict) -> None:
    installed = packages.get("transformers")
    if installed and installed.split(".")[:2] != TRANSFORMERS_PROBED_VERSION.split("."):
        logger.warning(
            f"transformers {installed} is installed, but TRANSFORMERS_PROBED_DISTRIBUTIONS "
            f"was taken from transformers {TRANSFORMERS_PROBED_VERSION}. If the app exits at a "
            "package metadata lookup, update the list from transformers' "
            "_is_package_available(..., return_version=True) calls."
        )


def _write_build_info(version: str, build_id: str, environment: dict, with_oqs: bool) -> None:
    """build_info.json, bundled at the resource root (sd_runner/runtime/version.py reads it)."""
    info = {
        "version": version,
        "build_id": build_id,
        # app-release rebuilds with --with-oqs when this is true.
        "with_oqs": with_oqs,
        "python": environment["python"],
        "packages": {name: v for name, v in environment["packages"].items() if v},
        # Lets the build compare itself with this checkout at startup.
        "source": {"repo": REPO_ROOT, **_version_module()["source_state"](REPO_ROOT)},
    }
    os.makedirs(BUILD_DIR, exist_ok=True)
    with open(BUILD_INFO_PATH, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    logger.info("Building " + ", ".join(
        [f"SD Runner {version}", f"build {build_id}",
         f"from {info['source']['commit'][:10] or 'unknown commit'}"
         + (" with uncommitted changes" if info["source"]["changes"] else ""),
         f"Python {info['python']}"]
        + [f"{name} {v}" for name, v in sorted(info["packages"].items())]
    ))


def _write_windows_icon(python: str) -> None:
    """Render the PNG app icon to the .ico Nuitka needs, with the build venv's Qt."""
    os.makedirs(BUILD_DIR, exist_ok=True)
    script = (
        "import sys\n"
        "from PySide6.QtCore import Qt\n"
        "from PySide6.QtGui import QGuiApplication, QImage\n"
        "app = QGuiApplication(sys.argv[:1])\n"
        "image = QImage(sys.argv[1]).scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)\n"
        "sys.exit(0 if not image.isNull() and image.save(sys.argv[2], 'ICO') else 1)\n"
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([python, "-c", script, os.path.join(REPO_ROOT, ICON_PNG), ICON_ICO], env=env, check=True)


def _locale_files() -> list:
    """The compiled catalogs; .po and .pot are translation sources."""
    files = []
    for root, _dirs, names in os.walk(os.path.join(REPO_ROOT, "locale")):
        files += [os.path.relpath(os.path.join(root, n), REPO_ROOT) for n in names if n.endswith(".mo")]
    return sorted(files)


def _workflow_files() -> list:
    files = []
    for root, _dirs, names in os.walk(os.path.join(REPO_ROOT, WORKFLOWS_DIR)):
        files += [
            os.path.relpath(os.path.join(root, n), REPO_ROOT)
            for n in names if n.endswith(".json") and not WORKFLOWS_EXCLUDED.match(n)
        ]
    return sorted(files)


def _concept_files() -> list:
    files = []
    for set_dir in CONCEPT_SET_DIRS:
        folder = os.path.join(REPO_ROOT, set_dir)
        files += [
            os.path.join(set_dir, n) for n in os.listdir(folder)
            if n.endswith(".txt") and os.path.isfile(os.path.join(folder, n))
        ]
    return sorted(files)


def _data_files() -> list:
    return [*DATA_FILES, *_locale_files(), *_workflow_files(), *_concept_files()]


def _memory_wait_plugin():
    """The memory-wait plugin's path: from app-release's variable, else from an
    installed app-release, else None (the build does not wait)."""
    path = os.environ.get(MEMORY_WAIT_PLUGIN_ENV)
    tool = None if path else shutil.which("app-release")
    if tool:
        try:
            result = subprocess.run([tool, "--memory-wait-plugin"], capture_output=True, text=True,
                                    stdin=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"Cannot ask {tool} for the memory-wait plugin: {e}")
        else:
            if result.returncode == 0:
                path = result.stdout.strip()
    if path and os.path.isfile(path):
        logger.info(f"Memory-wait plugin: {path}")
        return path
    logger.warning("No memory-wait plugin: the onefile step will not wait for free memory. "
                   "Install app-release, or build through it.")
    return None


def _common_args(exe_name: str, unpack_prefix: str, version: str, build_id: str,
                 memory_wait_plugin=None) -> list:
    args = [
        "--onefile",
        # The exe unpacks its runtime to this folder. A fixed path (no
        # {PID}/{TIME}) makes Nuitka keep it between runs, so only the first
        # run pays the unpacking cost; the build id gives each build its own
        # folder, so a rebuilt exe never reuses a previous build's files.
        f"--onefile-tempdir-spec={APP_DATA_SPEC}/unpacked/{unpack_prefix}-{build_id}",
        f"--output-dir={BUILD_DIR}",
        f"--output-filename={exe_name}",
        # Lets Nuitka fetch build helpers (e.g. MinGW on Windows) without prompting.
        "--assume-yes-for-downloads",
        # Version information; Windows shows it in the executable's properties
        # and crash reports. The file version takes numbers only, so the build
        # id goes in the description.
        "--product-name=SD Runner",
        f"--product-version={version}",
        f"--file-version={version}",
        f"--file-description=SD Runner, build {build_id}",
        f"--include-data-files={BUILD_INFO_PATH}=build_info.json",
        # keyring finds its backends, including the OS one, through package
        # metadata entry points; without it encrypted saves cannot work.
        "--include-distribution-metadata=keyring",
        *[f"--include-distribution-metadata={p}" for p in TRANSFORMERS_PROBED_DISTRIBUTIONS],
        # TorchScript compiles Python functions from their source, which a
        # build does not ship; nothing in SD Runner uses it.
        "--module-parameter=torch-disable-jit=yes",
        # The MCP SDK reads its own version from package metadata, and uvicorn
        # loads its protocol and event-loop modules by name.
        "--include-distribution-metadata=mcp",
        "--include-package=uvicorn",
        *[f"--include-package={p}" for p in PILLOW_PLUGINS],
        # SD Prompt Reader is loaded from its own checkout (sd_prompt_reader_loc)
        # at runtime, so its dependencies must be in the build.
        "--include-package=piexif",
        f"--user-package-configuration-file={PACKAGE_CONFIG}",
        *([f"--user-plugin={memory_wait_plugin}"] if memory_wait_plugin else []),
        "--nofollow-import-to=pytest",
        "--nofollow-import-to=_pytest",
        "--nofollow-import-to=pytestqt",
    ]
    args += [f"--include-data-dir={d}={d}" for d in DATA_DIRS]
    args += [f"--include-data-files={f}={f}" for f in _data_files()]
    if sys.platform == "win32":
        args.append(f"--windows-icon-from-ico={ICON_ICO}")
    return args


def _gui_args() -> list:
    args = [
        "--enable-plugin=pyside6",
        # sound_player uses QSoundEffect.
        "--include-qt-plugins=multimedia",
    ]
    if sys.platform == "win32":
        # No console window when started from Explorer; when started from a
        # terminal, output goes to that terminal.
        args.append("--windows-console-mode=attach")
    return args


def _headless_args() -> list:
    # app_headless.py and what it constructs import no Qt
    # (tests/unit/test_headless_app.py); it keeps its console window.
    return ["--nofollow-import-to=PySide6"]


def _oqs_args(python: str, with_oqs: bool) -> list:
    if not with_oqs:
        # Keep liboqs-python out even if the build environment has it: without
        # its shared library it would try to build liboqs at the app's startup.
        return ["--nofollow-import-to=oqs"]
    probe = subprocess.run([python, "-c", _LIBOQS_PROBE], capture_output=True, text=True)
    library = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ""
    if probe.returncode != 0 or not os.path.isabs(library) or not os.path.isfile(library):
        sys.exit(
            "--with-oqs: could not locate the liboqs shared library through liboqs-python.\n"
            f"{probe.stdout}{probe.stderr}\n"
            "Install liboqs (or let liboqs-python build it: needs git, CMake and a C "
            "compiler) or set OQS_INSTALL_PATH to an existing install, then rebuild."
        )
    # The layout liboqs-python searches under OQS_INSTALL_PATH.
    lib_dir = "bin" if sys.platform == "win32" else "lib"
    logger.info(f"Bundling liboqs: {library}")
    return [
        "--include-package=oqs",
        "--include-distribution-metadata=liboqs-python",
        f"--include-data-files={library}=liboqs/{lib_dir}/{os.path.basename(library)}",
    ]


def _nuitka_env(min_free_memory=None) -> dict:
    env = dict(os.environ)
    if min_free_memory is not None:
        env[MIN_FREE_MEMORY_ENV] = min_free_memory
    return env


def _min_free_memory(value):
    """``--min-free-memory``'s value, checked, or None when not given."""
    if value is None:
        return None
    try:
        if float(value) >= 0:
            return value
    except ValueError:
        pass
    sys.exit(f"--min-free-memory={value}: give a number of GiB, or 0 to not wait for memory.")


def _copy_to_dist(exe_name: str) -> str:
    exe_path = os.path.join(DIST_DIR, exe_name)
    if os.path.isdir(exe_path):
        # Left by a folder build; on macOS/Linux it has the executable's name.
        logger.info(f"Removing the folder build at {exe_path}")
        shutil.rmtree(exe_path)
    os.makedirs(DIST_DIR, exist_ok=True)
    shutil.copy2(os.path.join(BUILD_DIR, exe_name), exe_path)
    return exe_path


def _pop_option(args: list, name: str):
    """Remove ``name=value`` from *args* and return the value, or None."""
    for arg in list(args):
        if arg.startswith(name + "="):
            args.remove(arg)
            return arg.split("=", 1)[1]
    return None


def _smoke_test(exe_path: str, with_oqs: bool) -> None:
    # Run from outside the repo so a passing test can't depend on the checkout,
    # with all app data (logs included), config, caches and the key store in a
    # scratch directory so the user's are untouched. The exe still unpacks to
    # the real unpacked/ folder, which a later start of this build reuses.
    command = [exe_path, "--smoke-test", *(["--expect-oqs"] if with_oqs else [])]
    with tempfile.TemporaryDirectory(prefix="sd-runner-smoke-") as scratch:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["SD_RUNNER_APP_DATA_DIR"] = scratch
        env["SD_RUNNER_CONFIGS_DIR"] = os.path.join(scratch, "configs")
        env["SD_RUNNER_CACHE_DIR"] = os.path.join(scratch, "cache")
        env["SD_RUNNER_SERVER_PORT"] = "0"
        for name in ("SD_RUNNER_CONFIGS_DIR", "SD_RUNNER_CACHE_DIR"):
            os.makedirs(env[name], exist_ok=True)
        result = subprocess.run(command, cwd=os.path.expanduser("~"), env=env)
    if result.returncode != 0:
        sys.exit(f"Smoke test failed: `{' '.join(command)}` exited {result.returncode}.")


# exe base name, entry script, unpack folder prefix, target-specific args
TARGETS = (
    ("SDRunner", "app_gui.py", "sdrunner", _gui_args),
    ("SDRunnerHeadless", "app_headless.py", "sdrunner-headless", _headless_args),
)
HEADLESS_TARGET = "SDRunnerHeadless"


def _targets(with_headless: bool) -> tuple:
    return tuple(t for t in TARGETS if with_headless or t[0] != HEADLESS_TARGET)


def main() -> None:
    args = sys.argv[1:]
    with_oqs = "--with-oqs" in args
    if with_oqs:
        args.remove("--with-oqs")
    with_headless = "--with-headless" in args
    if with_headless:
        args.remove("--with-headless")
    lock = _pop_option(args, "--lock")
    min_free_memory = _min_free_memory(_pop_option(args, "--min-free-memory"))
    version = _app_version()
    build_id = time.strftime("%Y%m%d-%H%M%S")
    logger.info(f"Log: {_setup_logging(build_id)}")

    if "--current-env" in args:
        args.remove("--current-env")
        if lock:
            sys.exit("--lock installs into the build venv; it cannot be combined with --current-env.")
        python = sys.executable
    else:
        if lock:
            lock = os.path.abspath(lock)
            if not os.path.isfile(lock):
                sys.exit(f"--lock: {lock} not found.")
        # A lock file from an OQS build already pins liboqs-python.
        needs_liboqs = with_oqs and not (lock and _lock_has(lock, "liboqs-python"))
        with _timed("Installing the build venv"):
            python = _ensure_build_venv((LIBOQS_PYTHON,) if needs_liboqs else (), requirements=lock)

    _write_lock_file(python)
    environment = _environment_versions(python)
    _check_transformers_version(environment["packages"])
    _write_build_info(version, build_id, environment, with_oqs)
    if sys.platform == "win32":
        _write_windows_icon(python)
    oqs_args = _oqs_args(python, with_oqs)
    memory_wait_plugin = _memory_wait_plugin()

    for base_name, entry, unpack_prefix, target_args in _targets(with_headless):
        exe_name = _exe_name(base_name)
        nuitka_args = [
            *_common_args(exe_name, unpack_prefix, version, build_id, memory_wait_plugin),
            *target_args(), *oqs_args,
            *args, os.path.join(REPO_ROOT, entry),
        ]
        with _timed(f"Compiling {base_name} with Nuitka"):
            result = subprocess.run([python, "-m", "nuitka", *nuitka_args], cwd=REPO_ROOT,
                                    env=_nuitka_env(min_free_memory))
            if result.returncode != 0:
                sys.exit(f"Nuitka exited {result.returncode} compiling {base_name}; its output is above.")
        exe_path = _copy_to_dist(exe_name)
        with _timed(f"Smoke-testing {exe_name}"):
            _smoke_test(exe_path, with_oqs)
        logger.info(f"Built {exe_path}")


if __name__ == "__main__":
    started = time.monotonic()
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            if isinstance(e.code, str):
                logger.error(e.code)
            logger.error(f"Build failed after {_duration(time.monotonic() - started)}")
            sys.exit(1)
        raise
    except KeyboardInterrupt:
        logger.error(f"Build stopped after {_duration(time.monotonic() - started)}")
        sys.exit(1)
    except BaseException:
        logger.exception(f"Build failed after {_duration(time.monotonic() - started)}")
        sys.exit(1)
    logger.info(f"Build finished in {_duration(time.monotonic() - started)}")
