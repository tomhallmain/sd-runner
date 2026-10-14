"""Helpers of scripts/package_release.py, loaded by file path; git is stubbed,
so nothing is built, tagged or uploaded."""

import builtins
import importlib.util
import json
import os

import pytest

from sd_runner.app_paths import REPO_ROOT

_PACKAGE_RELEASE = os.path.join(REPO_ROOT, "scripts", "package_release.py")

HEAD = "a" * 40
BUILT = "b" * 40
TREE = "t" * 40


@pytest.fixture(scope="module")
def package_release():
    spec = importlib.util.spec_from_file_location("package_release_under_test", _PACKAGE_RELEASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_git(head=HEAD, tree=TREE, ancestors=(), tag=None):
    """A stand-in for _git that knows HEAD, its tree, which commits are
    ancestors of HEAD and what an existing tag points at."""
    def git(repo, *args):
        if args == ("rev-parse", "HEAD"):
            return head
        if args == ("rev-parse", "HEAD^{tree}"):
            return tree
        if args[:2] == ("merge-base", "--is-ancestor"):
            return "" if args[2] in ancestors else None
        if args[:3] == ("rev-parse", "-q", "--verify"):
            return tag
        return None
    return git


def _build(tmp_path, commit=BUILT, tree=TREE, changes="", version="1.0.0"):
    """A build_info.json from *commit*, and an executable written after it."""
    info = {"version": version, "source": {"commit": commit, "changes": changes}}
    if tree:
        info["source"]["tree"] = tree
    info_path = tmp_path / "build_info.json"
    info_path.write_text(json.dumps(info), encoding="utf-8")
    exe = tmp_path / "SDRunner.exe"
    exe.write_bytes(b"exe")
    built_at = os.path.getmtime(info_path)
    os.utime(exe, (built_at + 10, built_at + 10))
    return info, str(info_path), str(exe)


# _write_generated_notes

def test_generated_notes_are_written_with_a_stamp(package_release, tmp_path):
    notes = tmp_path / "RELEASE_NOTES.md"
    assert package_release._write_generated_notes(str(notes), "first\n") is True
    assert notes.read_text(encoding="utf-8") == "first\n"
    assert (tmp_path / "RELEASE_NOTES.md.generated").is_file()


def test_unedited_notes_are_regenerated(package_release, tmp_path):
    notes = tmp_path / "RELEASE_NOTES.md"
    package_release._write_generated_notes(str(notes), "first\n")
    assert package_release._write_generated_notes(str(notes), "second\n") is True
    assert notes.read_text(encoding="utf-8") == "second\n"


def test_edited_notes_are_kept(package_release, tmp_path):
    notes = tmp_path / "RELEASE_NOTES.md"
    package_release._write_generated_notes(str(notes), "first\n")
    notes.write_text("edited by hand\n", encoding="utf-8")
    assert package_release._write_generated_notes(str(notes), "second\n") is False
    assert notes.read_text(encoding="utf-8") == "edited by hand\n"


def test_notes_without_a_stamp_are_regenerated(package_release, tmp_path):
    notes = tmp_path / "RELEASE_NOTES.md"
    notes.write_text("from an earlier run\n", encoding="utf-8")
    assert package_release._write_generated_notes(str(notes), "fresh\n") is True
    assert notes.read_text(encoding="utf-8") == "fresh\n"


# _approve_notes

@pytest.fixture
def notes_file(tmp_path):
    path = tmp_path / "RELEASE_NOTES.md"
    path.write_text("# SDRunner 1.0.0\n", encoding="utf-8")
    return str(path)


def _answers(monkeypatch, *answers):
    replies = iter(answers)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(replies))


def test_approving_the_notes_returns(package_release, notes_file, monkeypatch, capsys):
    _answers(monkeypatch, "a")
    package_release._approve_notes(notes_file)
    assert "# SDRunner 1.0.0" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["", "n", "q"])
def test_anything_but_approve_or_edit_aborts(package_release, notes_file, monkeypatch, answer):
    _answers(monkeypatch, answer)
    with pytest.raises(SystemExit):
        package_release._approve_notes(notes_file)


def test_edit_opens_the_editor_then_asks_again(package_release, notes_file, monkeypatch, capsys):
    edited = []

    def fake_edit(path):
        edited.append(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Edited notes\n")

    monkeypatch.setattr(package_release, "_edit", fake_edit)
    _answers(monkeypatch, "e", "a")
    package_release._approve_notes(notes_file)
    assert edited == [notes_file]
    assert "# Edited notes" in capsys.readouterr().out


# _behind

def _behind(package_release, tmp_path, info, info_path, exe, head=HEAD, head_tree=TREE):
    return package_release._behind(str(tmp_path), exe, "1.0.0", info, info_path, head, head_tree,
                                   head_time=0)


def test_a_build_from_head_is_current(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git())
    info, info_path, exe = _build(tmp_path, commit=HEAD)
    assert _behind(package_release, tmp_path, info, info_path, exe) is None


def test_an_ancestor_with_the_same_tree_is_current(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git(ancestors={BUILT}))
    info, info_path, exe = _build(tmp_path)
    assert _behind(package_release, tmp_path, info, info_path, exe) is None


def test_a_rewritten_commit_with_the_same_tree_is_behind(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git())
    info, info_path, exe = _build(tmp_path)
    assert "cannot be tagged" in _behind(package_release, tmp_path, info, info_path, exe)


def test_a_different_tree_is_behind(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git(ancestors={BUILT}))
    info, info_path, exe = _build(tmp_path)
    reason = _behind(package_release, tmp_path, info, info_path, exe, head_tree="u" * 40)
    assert BUILT[:10] in reason and HEAD[:10] in reason


def test_a_build_without_a_recorded_tree_is_judged_by_commit(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git(ancestors={BUILT}))
    info, info_path, exe = _build(tmp_path, tree=None)
    assert BUILT[:10] in _behind(package_release, tmp_path, info, info_path, exe)


def test_a_build_with_uncommitted_changes_is_behind(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git())
    info, info_path, exe = _build(tmp_path, commit=HEAD, changes="f" * 40)
    assert "uncommitted" in _behind(package_release, tmp_path, info, info_path, exe)


def test_an_executable_older_than_the_build_info_is_behind(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git())
    info, info_path, exe = _build(tmp_path, commit=HEAD)
    built_at = os.path.getmtime(info_path)
    os.utime(exe, (built_at - 10, built_at - 10))
    assert "predates" in _behind(package_release, tmp_path, info, info_path, exe)


# _check

def _check(package_release, tmp_path, info, info_path, exe):
    return package_release._check(str(tmp_path), "1.0.0", "v1.0.0", info, info_path,
                                  {"SDRunner": exe}, variant=None)


def test_check_accepts_an_ancestor_with_the_same_tree(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git(ancestors={BUILT}))
    info, info_path, exe = _build(tmp_path)
    errors, _ = _check(package_release, tmp_path, info, info_path, exe)
    assert errors == []


def test_check_refuses_a_rewritten_commit_with_the_same_tree(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git())
    info, info_path, exe = _build(tmp_path)
    errors, _ = _check(package_release, tmp_path, info, info_path, exe)
    assert len(errors) == 1
    assert "cannot be tagged" in errors[0]


def test_check_refuses_a_build_from_a_different_tree(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git(tree="u" * 40, ancestors={BUILT}))
    info, info_path, exe = _build(tmp_path)
    errors, _ = _check(package_release, tmp_path, info, info_path, exe)
    assert len(errors) == 1
    assert HEAD[:10] in errors[0] and BUILT[:10] in errors[0]


def test_check_refuses_a_tag_on_another_commit(package_release, tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "_git", _fake_git(tag="c" * 40))
    info, info_path, exe = _build(tmp_path, commit=HEAD)
    errors, _ = _check(package_release, tmp_path, info, info_path, exe)
    assert len(errors) == 1
    assert "v1.0.0" in errors[0]


# timing

def test_timed_logs_the_duration_of_a_step(package_release, caplog):
    with caplog.at_level("INFO", logger="package_release"):
        with package_release._timed("Uploading"):
            pass
    assert caplog.messages[0] == "Uploading..."
    assert caplog.messages[-1].startswith("Uploading done in ")


def test_timed_logs_a_failed_step(package_release, caplog):
    with caplog.at_level("INFO", logger="package_release"):
        with pytest.raises(SystemExit):
            with package_release._timed("Uploading"):
                raise SystemExit("broken")
    assert caplog.messages[-1].startswith("Uploading failed after ")


def test_duration(package_release):
    assert package_release._duration(3 * 3600 + 4 * 60 + 5) == "3h 04m 05s"


# _publish_steps

REMOTE_HEAD = "r" * 40


def _gh(monkeypatch, package_release, logged_in=True):
    """Stubs gh: logged in or not, and no release exists yet. Returns the commands run."""
    import subprocess

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        code = 0 if args == ["gh", "auth", "status"] and logged_in else 1
        return subprocess.CompletedProcess(args, code, stdout="", stderr="")

    monkeypatch.setattr(package_release.shutil, "which", lambda name: "gh")
    monkeypatch.setattr(package_release.subprocess, "run", fake_run)
    return calls


def _publish_git(remote_has_commit, branch="master"):
    def git(repo, *args):
        if args[:2] == ("symbolic-ref", "--short"):
            return branch
        if args[:2] == ("ls-remote", "--tags"):
            return ""
        if args[0] == "ls-remote":
            return f"{REMOTE_HEAD}\trefs/heads/{branch}"
        if args[:2] == ("merge-base", "--is-ancestor"):
            return "" if remote_has_commit and args[3] == REMOTE_HEAD else None
        return None
    return git


def _steps(package_release, tmp_path):
    return package_release._publish_steps(str(tmp_path), "v1.0.0", HEAD, "origin", "SDRunner 1.0.0",
                                          [], "RELEASE_NOTES.md", publish=False)


def test_publish_stops_before_tagging_when_gh_is_not_logged_in(package_release, tmp_path, monkeypatch):
    calls = _gh(monkeypatch, package_release, logged_in=False)
    monkeypatch.setattr(package_release, "_git", _publish_git(remote_has_commit=False))
    with pytest.raises(SystemExit) as excinfo:
        _steps(package_release, tmp_path)
    assert "gh auth login" in str(excinfo.value)
    assert calls == [["gh", "auth", "status"]]


def test_branch_is_pushed_before_the_tag_when_the_remote_lacks_the_commit(package_release, tmp_path,
                                                                           monkeypatch):
    _gh(monkeypatch, package_release)
    monkeypatch.setattr(package_release, "_git", _publish_git(remote_has_commit=False))
    steps = _steps(package_release, tmp_path)
    assert steps[:3] == [["git", "tag", "v1.0.0", HEAD],
                         ["git", "push", "origin", "refs/heads/master"],
                         ["git", "push", "origin", "refs/tags/v1.0.0"]]
    assert steps[3][:3] == ["gh", "release", "create"]


def test_branch_is_not_pushed_when_the_remote_has_the_commit(package_release, tmp_path, monkeypatch):
    _gh(monkeypatch, package_release)
    monkeypatch.setattr(package_release, "_git", _publish_git(remote_has_commit=True))
    steps = _steps(package_release, tmp_path)
    assert ["git", "push", "origin", "refs/heads/master"] not in steps
    assert ["git", "push", "origin", "refs/tags/v1.0.0"] in steps
