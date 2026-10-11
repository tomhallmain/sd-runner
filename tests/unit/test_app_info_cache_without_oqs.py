"""An app info cache written with quantum (OQS) keys, opened without OQS.

The process must start, leave the encrypted cache and its backups untouched,
and save only to a separate file that is never merged back automatically.
"""

import json
import os

import pytest

import lib.encryptor as encryptor
from sd_runner.persistence import app_info_cache as module


@pytest.fixture
def without_oqs(monkeypatch):
    monkeypatch.setattr(module, "stored_keys_need_unavailable_oqs", lambda *_args: True)


def make_cache_files(cache_dir):
    enc = os.path.join(cache_dir, module.CACHE_FILENAME)
    with open(enc, "wb") as f:
        f.write(b"quantum-encrypted")
    with open(enc + ".bak", "wb") as f:
        f.write(b"quantum-encrypted backup")
    return enc


def test_starts_empty_and_leaves_the_encrypted_cache_alone(without_oqs):
    cache_dir = os.environ["SD_RUNNER_CACHE_DIR"]
    enc = make_cache_files(cache_dir)
    cache = module.AppInfoCache()
    assert cache.encrypted_cache_unreadable
    cache.set("some_key", "some value")
    assert cache.store() is False
    with open(enc, "rb") as f:
        assert f.read() == b"quantum-encrypted"
    with open(enc + ".bak", "rb") as f:
        assert f.read() == b"quantum-encrypted backup"
    assert not os.path.exists(os.path.join(cache_dir, module.JSON_FILENAME))
    with open(os.path.join(cache_dir, module.NO_OQS_JSON_FILENAME), encoding="utf-8") as f:
        assert json.load(f)[module.AppInfoCache.INFO_KEY]["some_key"] == "some value"


def test_continues_from_the_previous_session_without_oqs(without_oqs):
    cache_dir = os.environ["SD_RUNNER_CACHE_DIR"]
    make_cache_files(cache_dir)
    first = module.AppInfoCache()
    first.set("some_key", "kept")
    first.store()
    second = module.AppInfoCache()
    assert second.get("some_key") == "kept"


def test_without_an_encrypted_cache_the_key_type_is_not_looked_up(monkeypatch):
    def fail(*_args):
        raise AssertionError("looked up the stored key type with no cache present")

    monkeypatch.setattr(module, "stored_keys_need_unavailable_oqs", fail)
    module.AppInfoCache()


class TestStoredKeysNeedUnavailableOqs:
    def test_quantum_keys_without_oqs(self, monkeypatch):
        monkeypatch.setattr(encryptor, "KeyEncapsulation", None)
        monkeypatch.setattr(encryptor, "_stored_encryptor_type", lambda *_args: "quantum")
        assert encryptor.stored_keys_need_unavailable_oqs("service", "app")

    def test_standard_keys_without_oqs(self, monkeypatch):
        monkeypatch.setattr(encryptor, "KeyEncapsulation", None)
        monkeypatch.setattr(encryptor, "_stored_encryptor_type", lambda *_args: "standard")
        assert not encryptor.stored_keys_need_unavailable_oqs("service", "app")

    def test_quantum_keys_with_oqs(self, monkeypatch):
        monkeypatch.setattr(encryptor, "KeyEncapsulation", object())
        monkeypatch.setattr(encryptor, "_stored_encryptor_type", lambda *_args: "quantum")
        assert not encryptor.stored_keys_need_unavailable_oqs("service", "app")

    def test_choosing_an_encryptor_raises_a_named_error(self, monkeypatch):
        monkeypatch.setattr(encryptor, "KeyEncapsulation", None)
        monkeypatch.setattr(encryptor, "_stored_encryptor_type", lambda *_args: "quantum")
        with pytest.raises(encryptor.OQSUnavailableError):
            encryptor._determine_encryptor("service", "app")
