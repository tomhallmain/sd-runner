"""Stage a Nuitka build from dist/ as GitHub release assets.

Run on the machine that builds, from any directory:

    python scripts/package_release.py [--variant cuda] [--products Weidr ...]
        [--no-build] [--force] [--notes FILE] [--no-upload] [--publish] [--yes]
        [-- <build_exe.py args>]

First it rebuilds those executables in dist/ that are behind the checkout's
HEAD, by running build_exe.py with the arguments after ``--`` (e.g.
``-- --jobs=4``), plus ``--with-oqs`` when build_info.json records it.
An <App>Headless executable is rebuilt with build_exe.py's ``--headless``, or
its ``--with-headless``, which rebuilds the GUI executable too. It builds
nothing that is not already in dist/, and nothing while tracked files have
uncommitted changes. ``--no-build`` skips this step.

Then it copies each executable in dist/ to dist/release/v<version>/ as
``<Product>-<version>-<os>-<arch>[-<variant>][.exe]``, adds the build's pip
lock file and a SHA256SUMS file named for the same platform, and writes
release notes (commit subjects since the previous v* tag, versions, OQS),
unless ``--notes`` names a file to use. A rerun regenerates the notes only
while the file is as last generated, so edits to it are kept.

Last, it tags the build's commit v<version>, pushes the current branch to
``--remote`` when the remote's copy of it lacks that commit, pushes the tag, and with the GitHub CLI (gh, logged in) creates a draft release with the
assets, or adds them to the release when it exists. Before creating the
release it shows the notes to approve, edit in $EDITOR (Notepad on Windows
when unset) or abort, then asks once to run the commands; ``--yes`` skips
both prompts. Steps already done are skipped, so a rerun resumes,
and a rerun with ``--publish`` publishes the draft. ``--no-upload`` stops
after staging and prints the commands.

The version comes from VERSION at the repo root or, in a repo that has none,
from ``APP_VERSION`` in the module build_exe.py's ``VERSION_FILE`` names.
Before copying, it checks against build/nuitka/build_info.json, when the build
wrote one, that the build has this version, had no uncommitted changes, came
from the checkout's HEAD or an ancestor with the same files, and is not older
than any executable it ships, and that tag v<version>, if it exists, points at
that commit. ``--force`` packages
despite failed checks.

Each step is timed. The log goes to the console and to
build/logs/package_release-<time>.log; a build it runs writes its own log.

Standard library only and imports nothing from the repo, so the same file
works in each app's repo.
"""
import argparse
import contextlib
import hashlib
import json
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time

VERSION_PATTERN = r"\d+(\.\d+){0,3}"
# GitHub refuses release assets of 2 GiB or more.
MAX_ASSET_BYTES = 2 * 1024 ** 3

logger = logging.getLogger("package_release")


class _LevelPrefix(logging.Filter):
    def filter(self, record):
        record.level_prefix = "" if record.levelno == logging.INFO else f"{record.levelname}: "
        return True


def _setup_logging(repo: str) -> str:
    """Log to the console and to a file for this run; returns the file's path."""
    log_dir = os.path.join(repo, "build", "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"package_release-{time.strftime('%Y%m%d-%H%M%S')}.log")
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


def _platform_tag() -> str:
    os_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{os_name}-{arch}"


def _read_version(repo: str) -> str:
    path = os.path.join(repo, "VERSION")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    # A repo that keeps the version in a module: build_exe.py names that
    # module as VERSION_FILE = os.path.join("...", "version.py").
    build_exe = os.path.join(repo, "build_exe.py")
    if os.path.isfile(build_exe):
        with open(build_exe, "r", encoding="utf-8") as f:
            match = re.search(r"^VERSION_FILE\s*=\s*(.+)$", f.read(), re.M)
        parts = re.findall(r"[\"']([^\"']+)[\"']", match.group(1)) if match else []
        module = os.path.join(repo, *parts) if parts else ""
        if module.endswith(".py") and os.path.isfile(module):
            with open(module, "r", encoding="utf-8") as f:
                match = re.search(r"^APP_VERSION\s*=\s*[\"']([^\"']+)[\"']", f.read(), re.M)
            if match:
                return match.group(1)
    sys.exit(f"No version found: put it in {path}.")


def _executables(dist: str) -> dict:
    """{product name: path} for the executables directly in *dist*."""
    found = {}
    for name in sorted(os.listdir(dist)):
        path = os.path.join(dist, name)
        if not os.path.isfile(path):
            continue
        base, ext = os.path.splitext(name)
        if sys.platform == "win32":
            if ext.lower() == ".exe":
                found[base] = path
        elif not ext and os.access(path, os.X_OK):
            found[base] = path
    return found


def _git(repo: str, *args: str):
    """git's stripped stdout, or None when git is missing or the command fails."""
    try:
        result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _load_build_info(info_path: str):
    if not os.path.isfile(info_path):
        return None
    with open(info_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _in_history(repo: str, commit: str, head: str) -> bool:
    """Whether *commit* is *head* or one of its ancestors."""
    return _git(repo, "merge-base", "--is-ancestor", commit, head) is not None


def _behind(repo, path, version, info, info_path, head, head_tree, head_time):
    """Why the executable at *path* is behind commit *head*, or None when it
    was built from it, or from an ancestor with the same files (tree)."""
    if info is None:
        # No build_info.json (RefacDir writes none): only the time is known.
        if os.path.getmtime(path) < head_time:
            return "it is older than the checkout's last commit"
        return None
    if os.path.getmtime(path) < os.path.getmtime(info_path):
        return "it predates the last build, so its source is unknown"
    source = info.get("source", {})
    built = source.get("commit") or ""
    if built != head:
        if not source.get("tree") or source["tree"] != head_tree:
            return f"it was built from {built[:10] or 'an unknown commit'}, the checkout is at {head[:10]}"
        if not _in_history(repo, built, head):
            # The release tag goes on the build's commit, so it has to be in the history.
            return (f"it was built from {built[:10]}, which has the checkout's files but is not "
                    "in its history (rewritten since), so it cannot be tagged")
    if source.get("changes"):
        return "it was built with uncommitted changes"
    if info.get("version") != version:
        return f"it is version {info.get('version')}, the checkout says {version}"
    return None


def _build_runs(repo: str, app_name: str, stale) -> list:
    """build_exe.py's target options for each run that rebuilds the *stale* products."""
    with open(os.path.join(repo, "build_exe.py"), "r", encoding="utf-8") as f:
        source = f.read()
    headless = [p for p in stale if p != app_name]
    for product in headless:
        if product != f"{app_name}Headless":
            sys.exit(f"Cannot tell how build_exe.py builds {product}; build it yourself, "
                     "or leave it out with --products.")
    runs = [[]] if app_name in stale else []
    if headless:
        if '"--with-headless"' in source:
            # Builds the GUI executable as well.
            runs = [["--with-headless"]]
        elif '"--headless"' in source:
            runs.append(["--headless"])
        else:
            sys.exit(f"build_exe.py has no option that builds {headless[0]}; build it yourself, "
                     "or leave it out with --products.")
    return runs


def _rebuild_stale(repo, version, executables, app_name, info_path, build_args) -> None:
    head = _git(repo, "rev-parse", "HEAD")
    head_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    head_time = _git(repo, "log", "-1", "--format=%ct")
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if not head or not head_tree or not head_time or dirty is None:
        sys.exit("git cannot tell which commit the checkout is at; build yourself and pass --no-build.")
    info = _load_build_info(info_path)
    stale = {}
    for product, path in executables.items():
        reason = _behind(repo, path, version, info, info_path, head, head_tree, int(head_time))
        if reason:
            logger.info(f"{product} is behind: {reason}.")
            stale[product] = reason
    if not stale:
        logger.info(f"Every executable was built from {head[:10]} or a commit with its files; nothing to rebuild.")
        return
    if dirty:
        sys.exit("Tracked files have uncommitted changes; commit or stash them, so the build "
                 "matches a commit, and run this again.")
    for target_args in _build_runs(repo, app_name, stale):
        command = [sys.executable, os.path.join(repo, "build_exe.py"), *target_args, *build_args]
        with _timed(f"Building: {_command_line(command)}"):
            if subprocess.run(command, cwd=repo).returncode != 0:
                sys.exit("The build failed; nothing packaged.")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command_line(args: list) -> str:
    return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)


def _check(repo, version, tag, info, info_path, executables, variant):
    """(errors, warnings) found before packaging."""
    errors, warnings = [], []
    if not re.fullmatch(VERSION_PATTERN, version):
        errors.append(f"Version {version!r} is not up to four dot-separated numbers.")
    head = _git(repo, "rev-parse", "HEAD")
    built = None
    if info is None:
        warnings.append(f"No {info_path}: cannot check what the executables were built from.")
    else:
        built = info.get("source", {}).get("commit") or None
        changes = info.get("source", {}).get("changes")
        if info.get("version") != version:
            errors.append(f"The build is version {info.get('version')}, the checkout says {version}.")
        if changes:
            errors.append("The build was made with uncommitted changes; commit them and rebuild.")
        elif changes is None:
            warnings.append("The build could not tell whether it had uncommitted changes.")
        if built and head and built != head:
            tree = info.get("source", {}).get("tree")
            if not tree or tree != _git(repo, "rev-parse", "HEAD^{tree}"):
                errors.append(f"The build is from commit {built[:10]}, the checkout is at {head[:10]}.")
            elif not _in_history(repo, built, head):
                errors.append(f"The build is from commit {built[:10]}, which has the checkout's files but "
                              "is not in its history (rewritten since the build), so it cannot be tagged; "
                              "rebuild it.")
        if info.get("source", {}).get("repo"):
            warnings.append(f"The build embeds the text of its checkout path, {info['source']['repo']} "
                            "(not the folder's contents), where anyone who downloads it can read it.")
        torch = info.get("packages", {}).get("torch") or ""
        if "+cu" in torch and not variant:
            warnings.append(f"torch {torch} is a CUDA build; consider --variant cuda.")
        built_at = os.path.getmtime(info_path)
        for path in executables.values():
            if os.path.getmtime(path) < built_at:
                errors.append(f"{path} predates the last build; rebuild it, or leave it out with --products.")
    tagged = _git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}")
    expected = built or head
    if tagged and expected and tagged != expected:
        errors.append(f"Tag {tag} points at {tagged[:10]}, not the build's commit {expected[:10]}.")
    for path in executables.values():
        if os.path.getsize(path) >= MAX_ASSET_BYTES:
            errors.append(f"{path} is 2 GiB or larger, which GitHub does not accept as a release asset.")
    return errors, warnings


def _changes(repo: str, commit: str) -> list:
    """Subjects of the commits since the previous v* tag, as notes lines."""
    previous = _git(repo, "describe", "--tags", "--abbrev=0", "--match", "v*", f"{commit}^")
    if not previous:
        return ["- First release."]
    log = _git(repo, "log", "--no-merges", "--format=- %s", f"{previous}..{commit}")
    return (log.splitlines() if log else ["- No changes."]) + ["", f"Changes since {previous}."]


def _release_notes(repo, title, platform_tag, info, commit, assets) -> str:
    lines = [f"# {title}", "", f"Built for {platform_tag} from commit {commit[:10]}."]
    if info:
        packages = ", ".join(f"{n} {v}" for n, v in sorted(info.get("packages", {}).items()))
        lines.append(f"Python {info.get('python', '?')}" + (f", {packages}." if packages else "."))
    lines += ["", "## Changes", "", *_changes(repo, commit), "", "## Downloads", ""]
    lines += [f"- `{name}` ({os.path.getsize(path) / 1024 ** 2:.0f} MB)" for name, path in assets]
    lines += ["", "## Notes", "",
              "- At its first start the executable unpacks its runtime into the app's data folder; "
              "later starts of the same build reuse it."]
    with_oqs = (info or {}).get("with_oqs")
    if with_oqs is not None:
        lines.append(f"- OQS (post-quantum) encryption: {'included' if with_oqs else 'not included'}.")
    if platform_tag.startswith("windows"):
        lines.append("- The executable is unsigned: Windows SmartScreen asks for confirmation "
                     "(More info, then Run anyway).")
    return "\n".join(lines) + "\n"


def _write_generated_notes(path: str, text: str) -> bool:
    """Write the generated notes *text* to *path*, unless the file there was
    edited since this script last wrote it. Returns whether it wrote."""
    # Holds the hash of the last generated text; a file whose hash differs was edited.
    stamp = path + ".generated"
    if os.path.isfile(path) and os.path.isfile(stamp):
        with open(stamp, "r", encoding="utf-8") as f:
            if f.read().strip() != _sha256(path):
                return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    with open(stamp, "w", encoding="utf-8") as f:
        f.write(_sha256(path) + "\n")
    return True


def _edit(path: str) -> None:
    """Open *path* in $EDITOR (Notepad on Windows when unset) and wait for it to close."""
    editor = os.environ.get("EDITOR") or ("notepad" if sys.platform == "win32" else "vi")
    try:
        if sys.platform == "win32":
            # A Windows command line is one string; this keeps any quotes $EDITOR has.
            result = subprocess.run(f'{editor} "{path}"')
        else:
            result = subprocess.run([*shlex.split(editor), path])
    except OSError as e:
        logger.warning(f"Cannot start the editor {editor!r}: {e}")
        return
    if result.returncode != 0:
        logger.warning(f"The editor {editor!r} exited with code {result.returncode}.")


def _approve_notes(path: str) -> None:
    """Show the release notes at *path* and ask to approve, edit or abort;
    exits on abort."""
    while True:
        with open(path, "r", encoding="utf-8") as f:
            print(f"\n----- {path} -----\n{f.read().rstrip()}\n-----")
        answer = input("Release notes: [a]pprove, [e]dit, or abort? [a/e/N] ").strip().lower()
        if answer in ("a", "approve"):
            return
        if answer not in ("e", "edit"):
            sys.exit("Not run.")
        print("Waiting for the editor to close (an editor that returns at once, such as "
              "`code`, needs its wait option, e.g. EDITOR=\"code --wait\").")
        _edit(path)


def _publish_steps(repo, tag, commit, remote, title, files, notes, publish) -> list:
    """The git and gh commands that put *files* on release *tag*, leaving out
    what is done already, so that a rerun resumes."""
    if not shutil.which("gh"):
        sys.exit("gh (GitHub CLI) is not installed; install it, run `gh auth login`, "
                 "or pass --no-upload.")
    # Checked before anything runs, so a missing login cannot stop the run after the tag is pushed.
    if subprocess.run(["gh", "auth", "status"], cwd=repo, capture_output=True).returncode != 0:
        sys.exit("gh is not logged in to GitHub; run `gh auth login` (or set GH_TOKEN) and run this again.")
    on_remote = _git(repo, "ls-remote", "--tags", remote, f"refs/tags/{tag}")
    if on_remote is None:
        sys.exit(f"Cannot reach the git remote {remote}.")
    steps = []
    if not _git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{tag}"):
        steps.append(["git", "tag", tag, commit])
    # A pushed tag carries its commits, but the branch on the remote stays where it was.
    branch = _git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    if not branch:
        logger.warning(f"HEAD is not on a branch; push the branch with {commit[:10]} to {remote} yourself.")
    else:
        remote_head = (_git(repo, "ls-remote", remote, f"refs/heads/{branch}") or "").split("\t")[0]
        # False also when the remote has commits not fetched here; the push then fails and says so.
        if not remote_head or not _in_history(repo, commit, remote_head):
            steps.append(["git", "push", remote, f"refs/heads/{branch}"])
    if not on_remote:
        steps.append(["git", "push", remote, f"refs/tags/{tag}"])
    release = subprocess.run(["gh", "release", "view", tag, "--json", "assets"],
                             cwd=repo, capture_output=True, text=True)
    if release.returncode == 0:
        uploaded = {(a["name"], a["size"]) for a in json.loads(release.stdout)["assets"]}
        missing = [f for f in files
                   if (os.path.basename(f), os.path.getsize(os.path.join(repo, f))) not in uploaded]
        if missing:
            steps.append(["gh", "release", "upload", tag, *missing, "--clobber"])
    else:
        steps.append(["gh", "release", "create", tag, *files, "--title", title,
                      "--notes-file", notes, "--draft", "--verify-tag"])
    if publish:
        steps.append(["gh", "release", "edit", tag, "--draft=false"])
    return steps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        help="repo root (default: the parent of this script's folder)")
    parser.add_argument("--variant", help="suffix for a build variant, e.g. cuda")
    parser.add_argument("--products", nargs="+", help="package only these executables (names without .exe)")
    parser.add_argument("--no-build", action="store_true", help="package dist/ as it is, without rebuilding")
    parser.add_argument("--force", action="store_true", help="package even when checks fail")
    parser.add_argument("--notes", help="release notes file to use instead of the generated one")
    parser.add_argument("--no-upload", action="store_true", help="stage the assets and print the commands only")
    parser.add_argument("--publish", action="store_true", help="publish the release instead of leaving a draft")
    parser.add_argument("--remote", default="origin", help="git remote to push the tag to (default: origin)")
    parser.add_argument("--yes", action="store_true", help="approve the release notes and upload without asking first")
    argv = sys.argv[1:]
    build_args = []
    if "--" in argv:
        build_args = argv[argv.index("--") + 1:]
        argv = argv[:argv.index("--")]
    opts = parser.parse_args(argv)

    repo = os.path.abspath(opts.repo)
    logger.info(f"Log: {_setup_logging(repo)}")
    version = _read_version(repo)
    tag = f"v{version}"
    dist = os.path.join(repo, "dist")
    executables = _executables(dist) if os.path.isdir(dist) else {}
    if opts.products:
        missing = [p for p in opts.products if p not in executables]
        if missing:
            sys.exit(f"Not in {dist}: {', '.join(missing)}")
        executables = {p: executables[p] for p in opts.products}
    if not executables:
        sys.exit(f"No executables in {dist}; run build_exe.py first.")
    if opts.notes and not os.path.isfile(opts.notes):
        sys.exit(f"--notes: {opts.notes} not found.")

    # The app's own name: Weidr for both Weidr and WeidrHeadless.
    app_name = min(executables, key=len).removesuffix("Headless")
    info_path = os.path.join(repo, "build", "nuitka", "build_info.json")
    if not opts.no_build:
        info = _load_build_info(info_path)
        # Keep the OQS choice of the build being replaced.
        if info and info.get("with_oqs") and "--with-oqs" not in build_args:
            build_args = [*build_args, "--with-oqs"]
        _rebuild_stale(repo, version, executables, app_name, info_path, build_args)
    info = _load_build_info(info_path)
    errors, warnings = _check(repo, version, tag, info, info_path, executables, opts.variant)
    for message in warnings:
        logger.warning(message)
    for message in errors:
        logger.error(message)
    if errors and not opts.force:
        sys.exit("Nothing packaged; fix the errors above or pass --force.")
    commit = (info or {}).get("source", {}).get("commit") or _git(repo, "rev-parse", "HEAD")
    if not commit:
        sys.exit("Cannot tell which commit the build is from.")

    suffix = f"{version}-{_platform_tag()}" + (f"-{opts.variant}" if opts.variant else "")
    out_dir = os.path.join(dist, "release", tag)
    os.makedirs(out_dir, exist_ok=True)
    assets = []
    sums_name = f"SHA256SUMS-{suffix}.txt"
    with _timed(f"Staging the assets in {out_dir}"):
        for product, path in executables.items():
            name = f"{product}-{suffix}{os.path.splitext(path)[1]}"
            logger.info(f"Copying {path} -> {name}")
            shutil.copy2(path, os.path.join(out_dir, name))
            assets.append((name, os.path.join(out_dir, name)))
        lock = os.path.join(repo, "build", "nuitka", "build-requirements.lock.txt")
        if os.path.isfile(lock):
            name = f"{app_name}-{suffix}-requirements.lock.txt"
            shutil.copy2(lock, os.path.join(out_dir, name))
            assets.append((name, os.path.join(out_dir, name)))
        with open(os.path.join(out_dir, sums_name), "w", encoding="utf-8", newline="\n") as f:
            for name, path in assets:
                f.write(f"{_sha256(path)}  {name}\n")
    downloads = list(assets)
    assets.append((sums_name, os.path.join(out_dir, sums_name)))

    title = f"{app_name} {version}"
    notes = os.path.abspath(opts.notes) if opts.notes else os.path.join(out_dir, "RELEASE_NOTES.md")
    if not opts.notes:
        if not _write_generated_notes(notes, _release_notes(repo, title, _platform_tag(), info, commit, downloads)):
            logger.info(f"Keeping the edited release notes in {notes}; delete the file to regenerate them.")
    logger.info(f"Staged in {out_dir}; release notes: {notes}")

    files = [os.path.relpath(path, repo).replace(os.sep, "/") for _, path in assets]
    notes_rel = os.path.relpath(notes, repo).replace(os.sep, "/")
    if opts.no_upload:
        print(f"\nTo publish, from {repo}, tag {commit[:10]} as {tag}, push the branch with "
              "that commit and the tag, then run")
        print("  " + _command_line(["gh", "release", "create", tag, *files, "--title", title,
                                    "--notes-file", notes_rel, "--draft", "--verify-tag"]))
        print("or, for a release that exists already,")
        print("  " + _command_line(["gh", "release", "upload", tag, *files, "--clobber"]))
        return

    steps = _publish_steps(repo, tag, commit, opts.remote, title, files, notes_rel, opts.publish)
    if not steps:
        logger.info(f"{title} already has these assets.")
        return
    confirm = not opts.yes and sys.stdin.isatty()
    # Only `gh release create` reads the notes; an existing release keeps its own.
    if confirm and not opts.notes and any(step[:3] == ["gh", "release", "create"] for step in steps):
        _approve_notes(notes)
    print(f"\nIn {repo}:")
    for step in steps:
        print("  " + _command_line(step))
    if not opts.yes:
        if not confirm:
            sys.exit("Not run: pass --yes to upload without a terminal to confirm in.")
        if input("Run these? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Not run.")
    for step in steps:
        with _timed(f"> {_command_line(step)}"):
            if subprocess.run(step, cwd=repo).returncode != 0:
                sys.exit("Stopped: the command above failed. Running this script again resumes from there.")
    if opts.publish:
        logger.info(f"Published {title}.")
    else:
        logger.info(f"{title} is a draft release; publish it on GitHub, or run this again with --publish.")


if __name__ == "__main__":
    started = time.monotonic()
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            if isinstance(e.code, str):
                logger.error(e.code)
            logger.error(f"Stopped after {_duration(time.monotonic() - started)}")
            sys.exit(1)
        raise
    except KeyboardInterrupt:
        logger.error(f"Interrupted after {_duration(time.monotonic() - started)}")
        sys.exit(1)
    except BaseException:
        logger.exception(f"Failed after {_duration(time.monotonic() - started)}")
        sys.exit(1)
    logger.info(f"Done in {_duration(time.monotonic() - started)}")
