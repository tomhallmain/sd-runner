"""Choosing a catalog when the config has no language preference.

An empty locale follows the system language. A language that has no catalog
directory falls back to English, including a system language such as Swedish.
"""

from lib.translations import I18N, resolve_locale
from lib.utils import Utils


def _system_language(monkeypatch, language):
    monkeypatch.setattr(Utils, "get_default_user_language", staticmethod(lambda: language))


def test_an_empty_preference_uses_the_system_language(monkeypatch):
    _system_language(monkeypatch, "de")
    assert resolve_locale(None) == "de"
    assert resolve_locale("") == "de"
    assert resolve_locale("   ") == "de"


def test_a_regional_system_language_uses_its_catalog(monkeypatch):
    _system_language(monkeypatch, "de_DE.UTF-8")
    assert resolve_locale(None) == "de"


def test_an_explicit_regional_code_uses_its_catalog():
    assert resolve_locale("pt-BR") == "pt"


def test_an_unsupported_language_uses_english(monkeypatch):
    _system_language(monkeypatch, "sv_SE")
    assert resolve_locale(None) == "en"
    assert resolve_locale("sv") == "en"


def test_an_explicit_english_preference_stays_english(monkeypatch):
    _system_language(monkeypatch, "de")
    assert resolve_locale("en") == "en"


def test_install_locale_records_the_resolved_language(monkeypatch):
    _system_language(monkeypatch, "de")
    I18N.install_locale(None, verbose=False)
    try:
        assert I18N.locale == "de"
    finally:
        I18N.install_locale("en", verbose=False)
