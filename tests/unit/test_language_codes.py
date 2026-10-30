"""Tests for how language codes are normalised and judged."""

import pytest

from sd_runner.prompts.language_codes import is_invalid_language_code, normalize_language_code


@pytest.mark.parametrize("code", [None, "", "  ", "en", "EN", "en-US", "en_GB"])
def test_english_and_blank_have_no_code(code):
    assert normalize_language_code(code) is None


@pytest.mark.parametrize("code, expected", [
    ("de", "de"),
    ("DE", "de"),
    ("de-AT", "de"),
    ("fr-CA-u-sd-caqc", "fr"),
    ("fil", "fil"),
])
def test_a_code_becomes_its_primary_subtag(code, expected):
    assert normalize_language_code(code) == expected


@pytest.mark.parametrize("code", ["deutsch", "1", 5])
def test_an_unusable_code_gives_none(code):
    assert normalize_language_code(code) is None
    assert is_invalid_language_code(code) is True


@pytest.mark.parametrize("code", [None, "", "  ", "en", "EN-us", "de"])
def test_english_blank_and_real_codes_are_not_invalid(code):
    assert is_invalid_language_code(code) is False
