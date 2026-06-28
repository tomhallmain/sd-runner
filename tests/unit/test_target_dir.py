import os
import tempfile

from sd_runner.generators.base import BaseImageGenerator


class TestMoveToTargetDir:
    def test_returns_original_path_when_target_dir_empty(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            path = tmp.name
        try:
            assert BaseImageGenerator.move_to_target_dir(path, "") == path
            assert BaseImageGenerator.move_to_target_dir(path, None) == path
        finally:
            os.remove(path)

    def test_moves_file_into_valid_target_dir(self):
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dest_dir:
            src_path = os.path.join(src_dir, "output.png")
            with open(src_path, "wb") as fh:
                fh.write(b"png")

            final_path = BaseImageGenerator.move_to_target_dir(src_path, dest_dir)

            assert final_path == os.path.join(dest_dir, "output.png")
            assert os.path.isfile(final_path)
            assert not os.path.exists(src_path)

    def test_skips_move_for_invalid_target_dir(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            path = tmp.name
        try:
            assert BaseImageGenerator.move_to_target_dir(path, "/nonexistent/path") == path
            assert os.path.isfile(path)
        finally:
            os.remove(path)

    def test_rename_to_edit_suffix_returns_renamed_path(self):
        with tempfile.TemporaryDirectory() as work_dir:
            save_path = os.path.join(work_dir, "output.png")
            with open(save_path, "wb") as fh:
                fh.write(b"png")
            related = os.path.join(work_dir, "source.png")

            renamed = BaseImageGenerator.rename_to_edit_suffix(save_path, related, "_edit")

            assert renamed == os.path.join(work_dir, "source__edit.png")
            assert os.path.isfile(renamed)
            assert not os.path.exists(save_path)

    def test_apply_output_postprocessing_renames_before_move(self):
        with tempfile.TemporaryDirectory() as work_dir, tempfile.TemporaryDirectory() as target_dir:
            save_path = os.path.join(work_dir, "output.png")
            with open(save_path, "wb") as fh:
                fh.write(b"png")
            related = os.path.join(work_dir, "source.png")

            final_path = BaseImageGenerator.apply_output_postprocessing(
                save_path,
                target_dir,
                "_edit",
                related,
            )

            assert final_path == os.path.join(target_dir, "source__edit.png")
            assert os.path.isfile(final_path)
            assert not os.path.exists(save_path)
