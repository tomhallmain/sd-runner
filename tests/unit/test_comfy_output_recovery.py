"""Recovering an output image whose filename could not be read.

ComfyUI reports what it wrote through its history endpoint. When that request
fails after the prompt has already executed, the image is on disk and only its
name is unknown -- so it can be identified by elimination instead, provided
exactly one new file appeared. Several generations share one output directory,
so anything less certain than that is not guessed at.
"""

import os
import time

import pytest

from sd_runner.generators import comfy as comfy_module
from sd_runner.generators.comfy import ComfyGen
from tests.utils import captured_logs


@pytest.fixture
def output_dir(tmp_path, monkeypatch):
    """Point the ComfyUI save path at a temp directory."""
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(comfy_module.config, "comfyui_output_dir", str(out))
    return out


def write_image(directory, name: str, mtime: float) -> str:
    """Create a file with an explicit modification time."""
    path = directory / name
    path.write_bytes(b"not really a png")
    os.utime(path, (mtime, mtime))
    return str(path)


# ---------------------------------------------------------------------------
# Where the output directory comes from
# ---------------------------------------------------------------------------

class TestOutputPathConfig:
    def test_an_explicit_output_dir_wins(self, monkeypatch):
        monkeypatch.setattr(comfy_module.config, "comfyui_loc", "/comfy")
        monkeypatch.setattr(comfy_module.config, "comfyui_output_dir", "/elsewhere/out")
        assert comfy_module.config.get_comfyui_save_path() == "/elsewhere/out"

    def test_it_falls_back_to_the_install_output_folder(self, monkeypatch):
        monkeypatch.setattr(comfy_module.config, "comfyui_loc", os.path.join("/comfy"))
        monkeypatch.setattr(comfy_module.config, "comfyui_output_dir", None)
        assert comfy_module.config.get_comfyui_save_path() == os.path.join("/comfy", "output")

    def test_with_neither_set_it_is_the_working_directory(self, monkeypatch):
        monkeypatch.setattr(comfy_module.config, "comfyui_loc", None)
        monkeypatch.setattr(comfy_module.config, "comfyui_output_dir", None)
        assert comfy_module.config.get_comfyui_save_path() == "."


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

class TestRecoverUnnamedOutput:
    def test_one_new_image_is_recovered(self, output_dir):
        queued_at = time.time()
        expected = write_image(output_dir, "new.png", queued_at + 1)
        assert ComfyGen._recover_unnamed_output(queued_at) == expected

    def test_images_predating_the_prompt_are_ignored(self, output_dir):
        """The directory holds every image the user has ever generated."""
        queued_at = time.time()
        write_image(output_dir, "old_a.png", queued_at - 500)
        write_image(output_dir, "old_b.png", queued_at - 100)
        expected = write_image(output_dir, "new.png", queued_at + 1)
        assert ComfyGen._recover_unnamed_output(queued_at) == expected

    def test_two_new_images_are_not_guessed_between(self, output_dir):
        """Generations run concurrently against one directory."""
        queued_at = time.time()
        write_image(output_dir, "new_a.png", queued_at + 1)
        write_image(output_dir, "new_b.png", queued_at + 1)
        assert ComfyGen._recover_unnamed_output(queued_at) is None

    def test_no_new_image_recovers_nothing(self, output_dir):
        queued_at = time.time()
        write_image(output_dir, "old.png", queued_at - 100)
        assert ComfyGen._recover_unnamed_output(queued_at) is None

    def test_an_empty_directory_recovers_nothing(self, output_dir):
        assert ComfyGen._recover_unnamed_output(time.time()) is None

    @pytest.mark.parametrize("name", ["notes.txt", "workflow.json", "archive.zip"])
    def test_non_image_files_are_not_candidates(self, output_dir, name):
        queued_at = time.time()
        write_image(output_dir, name, queued_at + 1)
        expected = write_image(output_dir, "new.png", queued_at + 1)
        assert ComfyGen._recover_unnamed_output(queued_at) == expected

    @pytest.mark.parametrize("name", ["a.png", "b.jpg", "c.jpeg", "d.webp", "e.gif"])
    def test_every_image_extension_comfyui_writes_is_a_candidate(self, output_dir, name):
        queued_at = time.time()
        expected = write_image(output_dir, name, queued_at + 1)
        assert ComfyGen._recover_unnamed_output(queued_at) == expected

    def test_the_extension_check_is_case_insensitive(self, output_dir):
        queued_at = time.time()
        expected = write_image(output_dir, "NEW.PNG", queued_at + 1)
        assert ComfyGen._recover_unnamed_output(queued_at) == expected

    def test_a_new_subdirectory_is_not_a_candidate(self, output_dir):
        queued_at = time.time()
        (output_dir / "subfolder").mkdir()
        expected = write_image(output_dir, "new.png", queued_at + 1)
        assert ComfyGen._recover_unnamed_output(queued_at) == expected

    def test_a_missing_output_directory_recovers_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            comfy_module.config, "comfyui_output_dir", str(tmp_path / "does_not_exist")
        )
        assert ComfyGen._recover_unnamed_output(time.time()) is None


# ---------------------------------------------------------------------------
# What it says when it declines
# ---------------------------------------------------------------------------

class TestRecoveryLogging:
    def test_ambiguity_is_reported_with_the_count(self, output_dir, caplog):
        queued_at = time.time()
        write_image(output_dir, "new_a.png", queued_at + 1)
        write_image(output_dir, "new_b.png", queued_at + 1)
        with captured_logs(caplog, comfy_module.logger):
            ComfyGen._recover_unnamed_output(queued_at)
        assert "found 2 new files" in caplog.text

    def test_a_missing_directory_points_at_the_config_field(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(
            comfy_module.config, "comfyui_output_dir", str(tmp_path / "nope")
        )
        with captured_logs(caplog, comfy_module.logger):
            ComfyGen._recover_unnamed_output(time.time())
        assert "comfyui_output_dir" in caplog.text

    def test_a_recovery_is_recorded_as_a_warning(self, output_dir, caplog):
        """It is a guess, however well founded, and the log should say so."""
        queued_at = time.time()
        write_image(output_dir, "new.png", queued_at + 1)
        with captured_logs(caplog, comfy_module.logger, level="WARNING"):
            ComfyGen._recover_unnamed_output(queued_at)
        assert "Recovered output image" in caplog.text
