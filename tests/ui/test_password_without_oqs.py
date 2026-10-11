"""The password gate when the stored password cannot be decrypted, and the
decorators that wrap slot methods.

A build without OQS meeting quantum (OQS) keys must refuse protected actions
rather than treat the password as unset. The decorators must keep the wrapped
function's name: in a compiled build PySide6 connected every method named
``wrapper`` to the last one connected.
"""

import pytest

import sd_runner.ui.auth.app_startup_auth as app_startup_auth
import sd_runner.ui.auth.password_core as password_core
import sd_runner.ui.auth.password_utils as password_utils
from sd_runner.globals import ProtectedActions


@pytest.fixture
def unreadable(monkeypatch):
    """Quantum keys without OQS; records the alerts instead of showing them."""
    alerts = []
    monkeypatch.setattr(password_core.PasswordManager, "is_password_unreadable", staticmethod(lambda: True))
    monkeypatch.setattr(password_core.PasswordManager, "_security_configured_cache", None)
    monkeypatch.setattr(password_core, "_security_config", None)
    monkeypatch.setattr(password_utils, "qt_alert", lambda *args, **kwargs: alerts.append(args))
    return alerts


class TestCheckPasswordRequired:
    def test_a_protected_action_is_refused(self, unreadable):
        answers = []
        result = password_utils.check_password_required(
            [ProtectedActions.EDIT_BLACKLIST], None, callback=answers.append,
        )
        assert result is False
        assert answers == [False]
        assert len(unreadable) == 1

    def test_an_unprotected_action_proceeds(self, unreadable):
        answers = []
        result = password_utils.check_password_required(
            [ProtectedActions.EDIT_PRESETS], None, callback=answers.append,
        )
        assert result is True
        assert answers == [True]
        assert unreadable == []

    def test_requiring_authentication_is_refused_even_unprotected(self, unreadable):
        result = password_utils.check_password_required(
            [ProtectedActions.EDIT_PRESETS], None, allow_unauthenticated=False,
        )
        assert result is False

    def test_an_unreadable_password_counts_as_configured(self, unreadable):
        assert password_core.PasswordManager.is_security_configured()


class TestStartupGate:
    def test_a_protected_start_is_refused(self, unreadable):
        password_core.get_security_config().set_action_protected(
            ProtectedActions.OPEN_APPLICATION.value, True,
        )
        answers = []
        assert app_startup_auth.check_startup_password_required(callback=answers.append) is False
        assert answers == [False]
        assert len(unreadable) == 1

    def test_an_unprotected_start_proceeds(self, unreadable):
        password_core.get_security_config().set_action_protected(
            ProtectedActions.OPEN_APPLICATION.value, False,
        )
        answers = []
        assert app_startup_auth.check_startup_password_required(callback=answers.append) is True


class TestDecoratorsKeepNames:
    def test_require_password(self):
        class Window:
            @password_utils.require_password(ProtectedActions.EDIT_BLACKLIST)
            def open_blacklist(self):
                pass

            @password_utils.require_password(ProtectedActions.EDIT_PRESETS)
            def open_presets(self):
                pass

        assert Window.open_blacklist.__name__ == "open_blacklist"
        assert Window.open_presets.__name__ == "open_presets"

    def test_key_binding_guard(self):
        from sd_runner.ui.app_window.key_binding_manager import KeyBindingManager

        def next_preset():
            pass

        assert KeyBindingManager._guarded(next_preset).__name__ == "next_preset"

    def test_periodic(self):
        from lib.utils import Utils

        async def poll():
            pass

        assert Utils.periodic(1)(poll).__name__ == "poll"
