"""Password-gate bypass for tests.

Actions behind ``@require_password`` route through
``password_utils.check_password_required``, which would open a modal dialog and,
via PasswordManager, read the developer's real OS credential store. Both are
unacceptable in a test run, so install this before exercising any protected
action.

The decorator looks ``check_password_required`` up in the password_utils module
globals at call time, so patching the module attribute reaches every already
decorated method -- no need to touch the individual windows.
"""


def install_password_bypass(monkeypatch, granted: bool = True) -> list:
    """Auto-answer every password prompt.

    Args:
        monkeypatch: the test's monkeypatch fixture.
        granted: what the gate should answer. ``True`` runs the protected
            function; ``False`` simulates a cancelled or failed prompt, which is
            how you test that a gate is actually enforced.

    Returns:
        A list that records one entry per gate crossed, as
        ``(action_names, granted)`` -- assert against it to prove a protected
        action really is gated rather than silently unprotected.
    """
    import ui_qt.auth.password_utils as password_utils

    crossings = []

    def fake_check_password_required(
        action_names,
        master,
        callback=None,
        app_actions=None,
        custom_text=None,
        allow_unauthenticated=True,
    ):
        crossings.append((list(action_names), granted))
        if callback is None:
            return granted
        return callback(granted)

    monkeypatch.setattr(
        password_utils, "check_password_required", fake_check_password_required
    )

    # Some call sites consult the manager directly rather than going through the
    # decorator; keep those off the credential store too.
    try:
        import ui_qt.auth.password_core as password_core

        monkeypatch.setattr(
            password_core.PasswordManager, "_security_configured_cache", False
        )
        monkeypatch.setattr(
            password_core.PasswordManager, "is_security_configured",
            staticmethod(lambda: False),
        )
    except Exception:
        pass

    return crossings
