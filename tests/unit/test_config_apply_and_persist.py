"""Tests for Config.apply_and_persist() and Config.persist() atomic swap."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import sd_runner.config as _cfg_module
from sd_runner.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config() -> Config:
    """Return the per-test config instance (patched by isolated_singletons)."""
    return _cfg_module.config


# ---------------------------------------------------------------------------
# DIALOG_FIELDS registry
# ---------------------------------------------------------------------------

class TestDialogFieldsRegistry:
    def test_all_dialog_fields_are_real_attributes(self):
        """Every key in DIALOG_FIELDS must exist on a fresh Config instance."""
        c = _config()
        for key in Config.DIALOG_FIELDS:
            assert hasattr(c, key), f"DIALOG_FIELDS key {key!r} has no matching attribute"

    def test_all_dialog_fields_have_valid_type_sentinel(self):
        """Every value in DIALOG_FIELDS must be bool, int, float, str, or None."""
        allowed = {bool, int, float, str, None}
        for key, expected in Config.DIALOG_FIELDS.items():
            assert expected in allowed, (
                f"DIALOG_FIELDS[{key!r}] = {expected!r} is not an allowed type sentinel"
            )


# ---------------------------------------------------------------------------
# apply_and_persist — field type handling
# ---------------------------------------------------------------------------

class TestApplyAndPersistFieldTypes:
    def test_bool_field_set_true(self):
        c = _config()
        c.debug = False
        errors = c.apply_and_persist({"debug": True})
        assert errors == []
        assert c.debug is True
        assert c.dict["debug"] is True

    def test_bool_field_set_false(self):
        c = _config()
        c.debug = True
        errors = c.apply_and_persist({"debug": False})
        assert errors == []
        assert c.debug is False

    def test_int_field_parsed_from_str(self):
        c = _config()
        errors = c.apply_and_persist({"max_executor_threads": "8"})
        assert errors == []
        assert c.max_executor_threads == 8
        assert c.dict["max_executor_threads"] == 8

    def test_int_field_invalid_str_returns_error(self):
        original = _config().max_executor_threads
        errors = _config().apply_and_persist({"max_executor_threads": "not_a_number"})
        assert len(errors) == 1
        assert "max_executor_threads" in errors[0]
        assert _config().max_executor_threads == original  # unchanged

    def test_float_field_parsed_from_str(self):
        c = _config()
        errors = c.apply_and_persist({"ui_scale_factor": "1.5"})
        assert errors == []
        assert c.ui_scale_factor == pytest.approx(1.5)
        assert c.dict["ui_scale_factor"] == pytest.approx(1.5)

    def test_float_field_invalid_str_returns_error(self):
        c = _config()
        original = c.ui_scale_factor
        errors = c.apply_and_persist({"ui_scale_factor": "abc"})
        assert len(errors) == 1
        assert c.ui_scale_factor == original  # unchanged

    def test_str_field_stored_stripped(self):
        c = _config()
        errors = c.apply_and_persist({"locale": "  de  "})
        assert errors == []
        assert c.locale == "de"
        assert c.dict["locale"] == "de"

    def test_nullable_str_empty_becomes_none(self):
        c = _config()
        c.comfyui_url = "http://127.0.0.1:8188"
        errors = c.apply_and_persist({"comfyui_url": ""})
        assert errors == []
        assert c.comfyui_url is None
        assert c.dict["comfyui_url"] is None

    def test_nullable_str_whitespace_only_becomes_none(self):
        c = _config()
        errors = c.apply_and_persist({"comfyui_url": "   "})
        assert errors == []
        assert c.comfyui_url is None

    def test_nullable_str_nonempty_stored_as_str(self):
        c = _config()
        errors = c.apply_and_persist({"comfyui_url": "http://localhost:8188"})
        assert errors == []
        assert c.comfyui_url == "http://localhost:8188"
        assert c.dict["comfyui_url"] == "http://localhost:8188"


# ---------------------------------------------------------------------------
# apply_and_persist — error accumulation and atomicity
# ---------------------------------------------------------------------------

class TestApplyAndPersistErrorHandling:
    def test_multiple_errors_all_collected(self):
        errors = _config().apply_and_persist({
            "max_executor_threads": "bad",
            "server_port": "also_bad",
        })
        assert len(errors) == 2
        keys_in_errors = " ".join(errors)
        assert "max_executor_threads" in keys_in_errors
        assert "server_port" in keys_in_errors

    def test_on_validation_error_attr_not_modified(self):
        c = _config()
        original_threads = c.max_executor_threads
        original_debug = c.debug
        c.apply_and_persist({"max_executor_threads": "bad", "debug": False})
        # debug is valid but nothing should be applied when any error exists
        assert c.max_executor_threads == original_threads
        assert c.debug == original_debug

    def test_on_validation_error_dict_not_modified(self):
        c = _config()
        original_dict_threads = c.dict.get("max_executor_threads")
        c.apply_and_persist({"max_executor_threads": "bad"})
        assert c.dict.get("max_executor_threads") == original_dict_threads

    def test_on_validation_error_persist_not_called(self):
        c = _config()
        with patch.object(c, "persist") as mock_persist:
            c.apply_and_persist({"max_executor_threads": "bad"})
        mock_persist.assert_not_called()

    def test_unknown_key_is_ignored_not_applied(self):
        c = _config()
        errors = c.apply_and_persist({"__nonexistent_key__": "value"})
        assert errors == []
        assert not hasattr(c, "__nonexistent_key__")

    def test_unknown_key_does_not_pollute_dict(self):
        c = _config()
        c.apply_and_persist({"__nonexistent_key__": "value"})
        assert "__nonexistent_key__" not in c.dict


# ---------------------------------------------------------------------------
# apply_and_persist — successful persist interaction
# ---------------------------------------------------------------------------

class TestApplyAndPersistSuccess:
    def test_successful_apply_persists_to_disk(self):
        """Changes appear in the config file after a successful apply_and_persist."""
        c = _config()
        c.apply_and_persist({"max_executor_threads": "8"})
        data = json.loads(Path(c.config_path).read_text(encoding="utf-8"))
        assert data["max_executor_threads"] == 8

    def test_successful_apply_updates_config_dict(self):
        c = _config()
        c.apply_and_persist({"max_executor_threads": "8"})
        assert c.dict["max_executor_threads"] == 8

    def test_successful_apply_updates_attr(self):
        c = _config()
        c.apply_and_persist({"max_executor_threads": "8"})
        assert c.max_executor_threads == 8

    def test_multiple_fields_applied_together(self):
        c = _config()
        errors = c.apply_and_persist({
            "debug": False,
            "max_executor_threads": "2",
            "locale": "de",
        })
        assert errors == []
        assert c.debug is False
        assert c.max_executor_threads == 2
        assert c.locale == "de"

    def test_returns_empty_list_on_success(self):
        errors = _config().apply_and_persist({"debug": True})
        assert errors == []

    def test_persist_exception_propagates(self):
        c = _config()
        with patch.object(c, "persist", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                c.apply_and_persist({"debug": False})


# ---------------------------------------------------------------------------
# persist() — atomic swap
# ---------------------------------------------------------------------------

class TestPersistAtomicSwap:
    def test_writes_valid_json(self):
        c = _config()
        c.persist()
        data = json.loads(Path(c.config_path).read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_no_tmp_file_left_after_success(self):
        c = _config()
        c.persist()
        assert not Path(c.config_path + ".tmp").exists()

    def test_original_preserved_when_write_fails(self):
        c = _config()
        original_content = Path(c.config_path).read_text(encoding="utf-8")
        with patch("json.dump", side_effect=IOError("disk full")):
            with pytest.raises(IOError):
                c.persist()
        assert Path(c.config_path).read_text(encoding="utf-8") == original_content

    def test_no_tmp_file_left_after_write_failure(self):
        c = _config()
        with patch("json.dump", side_effect=IOError("disk full")):
            with pytest.raises(IOError):
                c.persist()
        assert not Path(c.config_path + ".tmp").exists()

    def test_updates_self_dict_after_successful_persist(self):
        c = _config()
        c.debug = False
        c.dict["debug"] = False
        c.persist()
        assert c.dict["debug"] is False
