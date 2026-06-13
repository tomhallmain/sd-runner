"""
Tests for sd_runner/source_prompts.py.

SourcePrompt.has_valid_path() is pure logic.
get_source_prompts() has two main branches:
  - list of file paths  → each wrapped in SourcePrompt, empty/whitespace paths filtered
  - single directory    → is_dir=True, image files scanned from disk
"""

import pytest
from sd_runner.source_prompts import SourcePrompt, get_source_prompts


# ---------------------------------------------------------------------------
# SourcePrompt.has_valid_path
# ---------------------------------------------------------------------------

class TestSourcePromptHasValidPath:
    def test_none_image_path_is_invalid(self):
        assert SourcePrompt(image_path=None).has_valid_path() is False

    def test_empty_string_is_invalid(self):
        assert SourcePrompt(image_path="").has_valid_path() is False

    def test_whitespace_only_is_invalid(self):
        assert SourcePrompt(image_path="   ").has_valid_path() is False

    def test_valid_path_string(self):
        assert SourcePrompt(image_path="/some/image.png").has_valid_path() is True

    def test_relative_path_is_valid(self):
        assert SourcePrompt(image_path="image.jpg").has_valid_path() is True

    def test_path_with_internal_spaces_is_valid(self):
        assert SourcePrompt(image_path="/some/my image.png").has_valid_path() is True


# ---------------------------------------------------------------------------
# get_source_prompts — list-of-paths branch
# ---------------------------------------------------------------------------

class TestGetSourcePromptsListBranch:
    def test_none_files_returns_empty(self, monkeypatch):
        # preset_source_prompts is [] by default
        import sd_runner.source_prompts as sp_mod
        monkeypatch.setattr(sp_mod, "preset_source_prompts", [])
        source_prompts, is_dir = get_source_prompts(None)
        assert source_prompts == []
        assert is_dir is False

    def test_empty_list_returns_empty(self):
        source_prompts, is_dir = get_source_prompts([])
        assert source_prompts == []
        assert is_dir is False

    def test_list_of_paths_returns_source_prompts(self, tmp_path):
        f1 = tmp_path / "a.png"
        f2 = tmp_path / "b.png"
        f1.touch()
        f2.touch()
        source_prompts, is_dir = get_source_prompts([str(f1), str(f2)])
        assert len(source_prompts) == 2
        assert is_dir is False

    def test_each_result_is_source_prompt_instance(self, tmp_path):
        f = tmp_path / "img.png"
        f.touch()
        source_prompts, _ = get_source_prompts([str(f)])
        assert all(isinstance(sp, SourcePrompt) for sp in source_prompts)

    def test_all_source_prompts_have_valid_paths(self, tmp_path):
        f = tmp_path / "image.png"
        f.touch()
        source_prompts, _ = get_source_prompts([str(f)])
        assert all(sp.has_valid_path() for sp in source_prompts)

    def test_whitespace_only_path_filtered_out(self):
        # "   " → SourcePrompt.has_valid_path() is False → excluded
        source_prompts, _ = get_source_prompts(["   "])
        assert source_prompts == []

    def test_two_paths_not_treated_as_directory(self, tmp_path):
        f = tmp_path / "img.png"
        f.touch()
        _, is_dir = get_source_prompts([str(f), str(f)])
        assert is_dir is False

    def test_path_preserved_on_source_prompt(self, tmp_path):
        f = tmp_path / "unique_name.png"
        f.touch()
        source_prompts, _ = get_source_prompts([str(f)])
        assert any(str(f) in sp.image_path for sp in source_prompts)


# ---------------------------------------------------------------------------
# get_source_prompts — single-directory branch
# ---------------------------------------------------------------------------

class TestGetSourcePromptsDirectoryBranch:
    def _make_png(self, path, name):
        p = path / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        return p

    def test_single_directory_sets_is_dir(self, tmp_path):
        self._make_png(tmp_path, "img.png")
        _, is_dir = get_source_prompts([str(tmp_path)])
        assert is_dir is True

    def test_single_directory_returns_image_files(self, tmp_path):
        self._make_png(tmp_path, "a.png")
        self._make_png(tmp_path, "b.jpg")
        source_prompts, _ = get_source_prompts([str(tmp_path)])
        assert len(source_prompts) == 2

    def test_empty_directory_returns_empty_list(self, tmp_path):
        source_prompts, is_dir = get_source_prompts([str(tmp_path)])
        assert source_prompts == []
        assert is_dir is True

    def test_non_image_files_excluded(self, tmp_path):
        (tmp_path / "notes.txt").write_text("hello")
        (tmp_path / "data.json").write_text("{}")
        source_prompts, _ = get_source_prompts([str(tmp_path)])
        assert source_prompts == []
