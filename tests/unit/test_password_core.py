"""
PasswordManager logic, with the credential store replaced by an in-memory dict.

The real implementation calls through lib.encryptor into the OS keyring, so
these tests must never run unstubbed -- they would write to the developer's
actual credential store. The stub is autouse for that reason.

What is covered is the decision logic an auth bypass or a lockout would live in:
verify against a stored password, the absent-password case, and the
_security_configured_cache that short-circuits the storage read.
"""

import pytest

import sd_runner.ui.auth.password_core as password_core
from sd_runner.ui.auth.password_core import PasswordManager


@pytest.fixture(autouse=True)
def fake_credential_store(monkeypatch):
    """Replace the keyring-backed storage with a dict, and clear the cache."""
    store = {}

    def _key(service, app, password_id):
        return (service, app, password_id)

    def store_password(service, app, password_id, password):
        store[_key(service, app, password_id)] = password
        return True

    def retrieve_password(service, app, password_id):
        return store.get(_key(service, app, password_id))

    def delete_password(service, app, password_id):
        store.pop(_key(service, app, password_id), None)
        return True

    monkeypatch.setattr(password_core, "store_encrypted_password", store_password)
    monkeypatch.setattr(password_core, "retrieve_encrypted_password", retrieve_password)
    monkeypatch.setattr(password_core, "delete_stored_password", delete_password)
    monkeypatch.setattr(PasswordManager, "_security_configured_cache", None)
    return store


# ---------------------------------------------------------------------------
# verify_password
# ---------------------------------------------------------------------------

class TestVerifyPassword:
    def test_correct_password_verifies(self):
        PasswordManager.set_password("hunter2")
        assert PasswordManager.verify_password("hunter2") is True

    def test_wrong_password_is_rejected(self):
        PasswordManager.set_password("hunter2")
        assert PasswordManager.verify_password("hunter3") is False

    def test_verification_is_case_sensitive(self):
        PasswordManager.set_password("hunter2")
        assert PasswordManager.verify_password("HUNTER2") is False

    def test_no_stored_password_rejects_everything(self):
        assert PasswordManager.verify_password("anything") is False

    def test_no_stored_password_rejects_the_empty_string(self):
        assert PasswordManager.verify_password("") is False

    def test_whitespace_is_not_trimmed(self):
        PasswordManager.set_password("hunter2")
        assert PasswordManager.verify_password(" hunter2 ") is False

    def test_storage_failure_rejects_rather_than_raising(self, monkeypatch):
        """A broken credential store must lock out, never fall open."""
        def boom(*args, **kwargs):
            raise RuntimeError("keyring unavailable")
        monkeypatch.setattr(password_core, "retrieve_encrypted_password", boom)
        assert PasswordManager.verify_password("hunter2") is False


# ---------------------------------------------------------------------------
# set_password / clear_password
# ---------------------------------------------------------------------------

class TestSetPassword:
    def test_returns_true_on_success(self):
        assert PasswordManager.set_password("hunter2") is True

    def test_password_reaches_the_store(self, fake_credential_store):
        PasswordManager.set_password("hunter2")
        assert "hunter2" in fake_credential_store.values()

    def test_replacing_the_password_invalidates_the_old_one(self):
        PasswordManager.set_password("first")
        PasswordManager.set_password("second")
        assert PasswordManager.verify_password("first") is False
        assert PasswordManager.verify_password("second") is True

    def test_storage_failure_returns_false(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("keyring unavailable")
        monkeypatch.setattr(password_core, "store_encrypted_password", boom)
        assert PasswordManager.set_password("hunter2") is False


class TestClearPassword:
    def test_clears_the_stored_password(self):
        PasswordManager.set_password("hunter2")
        PasswordManager.clear_password()
        assert PasswordManager.verify_password("hunter2") is False

    def test_clearing_marks_security_unconfigured(self):
        PasswordManager.set_password("hunter2")
        assert PasswordManager.is_security_configured() is True
        PasswordManager.clear_password()
        assert PasswordManager.is_security_configured() is False

    def test_clearing_when_nothing_is_set_is_harmless(self):
        assert PasswordManager.clear_password() is True


# ---------------------------------------------------------------------------
# is_security_configured — cached, so the cache is part of the contract
# ---------------------------------------------------------------------------

class TestIsSecurityConfigured:
    def test_false_before_any_password_is_set(self):
        assert PasswordManager.is_security_configured() is False

    def test_true_after_setting_a_password(self):
        PasswordManager.set_password("hunter2")
        assert PasswordManager.is_security_configured() is True

    def test_result_is_cached(self, fake_credential_store, monkeypatch):
        """Once cached, the storage read is skipped entirely."""
        PasswordManager.set_password("hunter2")
        assert PasswordManager.is_security_configured() is True

        calls = []
        monkeypatch.setattr(
            password_core, "retrieve_encrypted_password",
            lambda *a, **kw: calls.append(1) or "hunter2",
        )
        PasswordManager.is_security_configured()
        assert calls == []

    def test_storage_failure_reports_unconfigured(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("keyring unavailable")
        monkeypatch.setattr(password_core, "retrieve_encrypted_password", boom)
        assert PasswordManager.is_security_configured() is False

    def test_empty_stored_password_is_not_configured(self, monkeypatch):
        monkeypatch.setattr(password_core, "retrieve_encrypted_password", lambda *a, **kw: "")
        assert PasswordManager.is_security_configured() is False
