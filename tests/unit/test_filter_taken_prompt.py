"""
Blacklist interception for PromptMode.TAKE.

TAKE is the one mode whose prompt is not user-authored: it is read out of an
image's metadata during the run, after RunController.validate_blacklist has
already passed on the (empty) sidebar text. filter_taken_prompt is the runtime
equivalent of that check, so it has to honour the same settings.

The negative prompt is deliberately never filtered -- extracted negatives carry
safety terms that exist to suppress the very content the blacklist targets.
"""

import pytest

from sd_runner.prompts.blacklist import Blacklist, BlacklistException, BlacklistItem
from sd_runner.prompts.prompter import Prompter
from sd_runner.globals import BlacklistMode, BlacklistPromptMode


TAKEN_POSITIVE = "a calm lake, forbidden, golden hour"
TAKEN_NEGATIVE = "nsfw, explicit, blurry"


@pytest.fixture(autouse=True)
def blocked(app_config):
    """A blacklist with one blocked term, and execution-blocking enabled."""
    app_config.blacklist_prevent_execution = True
    Blacklist.add_item(BlacklistItem("forbidden"))
    return "forbidden"


class RecordingCallbacks:
    """Stands in for the app's AppActions, recording instead of showing UI.

    Mirrors the real class's shape: warn() is a toast variant there, so it
    delegates here too -- which keeps the "never a modal" assertion meaningful.
    """

    def __init__(self):
        self.toasts = []
        self.warnings = []
        self.alerts = []

    def toast(self, message, *args, **kwargs):
        self.toasts.append(message)

    def warn(self, message, duration_ms=3000):
        self.warnings.append(message)
        return self.toast(message)

    def alert(self, title, message, kind=None, **kwargs):
        self.alerts.append((title, message, kind))
        return True


def set_mode(mode, silent=False):
    Blacklist.blacklist_mode = mode
    Blacklist.blacklist_silent_removal = silent


# ---------------------------------------------------------------------------
# Removal modes — strip and continue
# ---------------------------------------------------------------------------

class TestRemovalModes:
    @pytest.mark.parametrize(
        "mode", [BlacklistMode.REMOVE_ENTIRE_TAG, BlacklistMode.REMOVE_WORD_OR_PHRASE]
    )
    def test_blocked_tag_is_removed(self, mode):
        set_mode(mode)
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert "forbidden" not in positive

    @pytest.mark.parametrize(
        "mode", [BlacklistMode.REMOVE_ENTIRE_TAG, BlacklistMode.REMOVE_WORD_OR_PHRASE]
    )
    def test_clean_tags_survive(self, mode):
        set_mode(mode)
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert "a calm lake" in positive
        assert "golden hour" in positive

    def test_run_is_not_aborted(self):
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        # No exception: removal continues the run with what is left.
        Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)

    def test_clean_prompt_is_unchanged(self):
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        clean = "a calm lake, golden hour"
        positive, _negative = Prompter.filter_taken_prompt(clean, TAKEN_NEGATIVE)
        assert positive == clean

    def test_result_is_still_a_usable_tag_list(self):
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert not positive.startswith(",")
        assert not positive.endswith(",")
        assert ",," not in positive


# ---------------------------------------------------------------------------
# FAIL_PROMPT — abort the run
# ---------------------------------------------------------------------------

class TestFailPromptMode:
    def test_blocked_tag_raises(self):
        set_mode(BlacklistMode.FAIL_PROMPT)
        with pytest.raises(BlacklistException):
            Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)

    def test_raises_even_when_silent(self):
        """Silent removal suppresses the alert, never the abort."""
        set_mode(BlacklistMode.FAIL_PROMPT, silent=True)
        with pytest.raises(BlacklistException):
            Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)

    def test_clean_prompt_does_not_raise(self):
        set_mode(BlacklistMode.FAIL_PROMPT)
        positive, _negative = Prompter.filter_taken_prompt("a calm lake", TAKEN_NEGATIVE)
        assert positive == "a calm lake"

    def test_exception_carries_the_filtered_items(self):
        set_mode(BlacklistMode.FAIL_PROMPT)
        with pytest.raises(BlacklistException) as excinfo:
            Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert "forbidden" in excinfo.value.filtered


# ---------------------------------------------------------------------------
# LOG_ONLY — observe, change nothing
# ---------------------------------------------------------------------------

class TestLogOnlyMode:
    def test_prompt_is_returned_unchanged(self):
        set_mode(BlacklistMode.LOG_ONLY)
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert positive == TAKEN_POSITIVE

    def test_does_not_raise(self):
        set_mode(BlacklistMode.LOG_ONLY)
        Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)


# ---------------------------------------------------------------------------
# Opt-outs, matching validate_blacklist
# ---------------------------------------------------------------------------

class TestOptOuts:
    def test_disabled_prevent_execution_skips_filtering(self, app_config):
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        app_config.blacklist_prevent_execution = False
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert positive == TAKEN_POSITIVE

    def test_disabled_prevent_execution_skips_fail_prompt(self, app_config):
        """The opt-out must short-circuit before the abort, not after."""
        set_mode(BlacklistMode.FAIL_PROMPT)
        app_config.blacklist_prevent_execution = False
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert positive == TAKEN_POSITIVE

    def test_allow_in_nsfw_does_not_exempt_take_mode(self):
        """TAKE is not an NSFW mode, just an uncontrolled one, so it is not exempt.

        The exemption is decided by the shared is_allowed_prompt_mode helper,
        whose ALLOW_IN_NSFW branch tests prompt_mode.is_nsfw() -- false for TAKE.
        So filtering still applies, which falls out of reusing the helper rather
        than being special-cased here.
        """
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        Blacklist.blacklist_prompt_mode = BlacklistPromptMode.ALLOW_IN_NSFW
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert "forbidden" not in positive

    def test_empty_prompt_is_returned_as_is(self):
        set_mode(BlacklistMode.FAIL_PROMPT)
        assert Prompter.filter_taken_prompt("", "neg") == ("", "neg")

    def test_whitespace_prompt_is_returned_as_is(self):
        set_mode(BlacklistMode.FAIL_PROMPT)
        assert Prompter.filter_taken_prompt("   ", "neg") == ("   ", "neg")


# ---------------------------------------------------------------------------
# The negative prompt is never touched
# ---------------------------------------------------------------------------

class TestNegativeIsUntouched:
    @pytest.mark.parametrize(
        "mode",
        [BlacklistMode.REMOVE_ENTIRE_TAG, BlacklistMode.LOG_ONLY],
    )
    def test_negative_survives_filtering(self, mode):
        set_mode(mode)
        _positive, negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert negative == TAKEN_NEGATIVE

    def test_blocked_term_in_the_negative_is_kept(self):
        """A safety term in the negative must not be stripped -- it is the protection."""
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        _positive, negative = Prompter.filter_taken_prompt(
            "a calm lake", "forbidden, blurry"
        )
        assert "forbidden" in negative

    def test_blocked_term_in_the_negative_does_not_abort(self):
        set_mode(BlacklistMode.FAIL_PROMPT)
        _positive, negative = Prompter.filter_taken_prompt("a calm lake", "forbidden")
        assert negative == "forbidden"


# ---------------------------------------------------------------------------
# Notification, without a UI attached
# ---------------------------------------------------------------------------

class TestNotification:
    def test_no_ui_callbacks_is_not_fatal(self, monkeypatch):
        """The run thread has no UI reference in CLI use; filtering must still work."""
        monkeypatch.setattr(Blacklist, "_ui_callbacks", None)
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert "forbidden" not in positive

    def test_removal_notifies_when_not_silent(self, monkeypatch):
        callbacks = RecordingCallbacks()
        monkeypatch.setattr(Blacklist, "_ui_callbacks", callbacks)
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG, silent=False)
        Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert callbacks.warnings, "removal was not surfaced to the user"
        assert "forbidden" in callbacks.warnings[0]

    def test_notification_carries_warning_severity(self, monkeypatch):
        """Removal is a warning, not a neutral notice -- warn(), not toast()."""
        callbacks = RecordingCallbacks()
        monkeypatch.setattr(Blacklist, "_ui_callbacks", callbacks)
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG, silent=False)
        Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert callbacks.warnings

    def test_notification_never_opens_a_modal(self, monkeypatch):
        """A removal is informational and the run continues, so it must not block.

        qt_alert calls exec(); over a batch of taken prompts an alert would stop
        the run on every affected image waiting to be dismissed. This assertion
        is also what keeps the test suite from hanging on a leaked UI callback.
        """
        callbacks = RecordingCallbacks()
        monkeypatch.setattr(Blacklist, "_ui_callbacks", callbacks)
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG, silent=False)
        Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert callbacks.alerts == [], "a modal alert would block the run thread"

    def test_removal_is_silent_when_configured(self, monkeypatch):
        callbacks = RecordingCallbacks()
        monkeypatch.setattr(Blacklist, "_ui_callbacks", callbacks)
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG, silent=True)
        Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert callbacks.warnings == []

    def test_a_broken_callback_does_not_break_the_run(self, monkeypatch):
        class Exploding:
            def warn(self, *args, **kwargs):
                raise RuntimeError("UI is gone")

        monkeypatch.setattr(Blacklist, "_ui_callbacks", Exploding())
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert "forbidden" not in positive

    def test_callbacks_do_not_leak_in_from_an_earlier_test(self):
        """Regression: a leaked AppWindow callback hung the suite.

        Blacklist._ui_callbacks is set by AppWindow construction and is
        thread-bridged to that window. Left set, a later test notifying through
        it opened a modal nobody could dismiss and the run blocked forever --
        which looked like a hang rather than a failure. The root conftest now
        clears it between tests.
        """
        assert getattr(Blacklist, "_ui_callbacks", None) is None


# ---------------------------------------------------------------------------
# Blacklist.is_active — what decides whether TAKE mode needs authentication
#
# The sidebar gates entry into TAKE mode on this: with nothing filtering the
# extracted prompt, the mode is as unconstrained as NSFW. Both halves are
# required, because either one alone leaves the prompt unfiltered.
# ---------------------------------------------------------------------------

class TestBlacklistIsActive:
    def test_active_when_enforcing_with_an_enabled_item(self, app_config):
        app_config.blacklist_prevent_execution = True
        assert Blacklist.is_active() is True

    def test_inactive_when_enforcement_is_off(self, app_config):
        app_config.blacklist_prevent_execution = False
        assert Blacklist.is_active() is False

    def test_inactive_when_the_list_is_empty(self, app_config):
        app_config.blacklist_prevent_execution = True
        Blacklist.clear()
        assert Blacklist.is_active() is False

    def test_inactive_when_every_item_is_disabled(self, app_config):
        """A disabled item filters nothing, so it is not protection."""
        app_config.blacklist_prevent_execution = True
        Blacklist.clear()
        Blacklist.add_item(BlacklistItem("forbidden", enabled=False))
        assert Blacklist.is_active() is False

    def test_active_when_at_least_one_item_is_enabled(self, app_config):
        app_config.blacklist_prevent_execution = True
        Blacklist.clear()
        Blacklist.add_item(BlacklistItem("disabled_one", enabled=False))
        Blacklist.add_item(BlacklistItem("enabled_one", enabled=True))
        assert Blacklist.is_active() is True

    def test_enforcement_off_beats_an_enabled_item(self, app_config):
        """Both halves are required -- neither alone makes it active."""
        app_config.blacklist_prevent_execution = False
        Blacklist.clear()
        Blacklist.add_item(BlacklistItem("forbidden", enabled=True))
        assert Blacklist.is_active() is False


class TestTakeModeGateDecision:
    """The predicate as the sidebar uses it: gate TAKE when nothing filters it.

    The sidebar branch is a thin layer over this; asserting the decision here
    keeps it testable without constructing a real widget.
    """

    def test_take_has_its_own_protected_action(self):
        """TAKE is gated by TAKE_PROMPT, not by NSFW_PROMPTS.

        The two are separate decisions -- choosing to generate adult content is
        deliberate, while taking a prompt from a file is content of unknown
        character -- so a user can gate one without the other.
        """
        from sd_runner.globals import ProtectedActions

        assert ProtectedActions.TAKE_PROMPT != ProtectedActions.NSFW_PROMPTS
        assert ProtectedActions.TAKE_PROMPT.get_description()

    def test_new_actions_default_to_protected(self):
        """A newly added action must not silently start unprotected."""
        from sd_runner.ui.auth.password_core import get_security_config
        from sd_runner.globals import ProtectedActions

        config = get_security_config()
        assert config.is_action_protected(ProtectedActions.TAKE_PROMPT.value) is True

    def test_take_is_gated_when_the_blacklist_is_inactive(self, app_config):
        app_config.blacklist_prevent_execution = False
        assert not Blacklist.is_active()

    def test_take_is_not_gated_when_the_blacklist_is_active(self, app_config):
        app_config.blacklist_prevent_execution = True
        assert Blacklist.is_active()

    def test_the_gate_and_the_filter_agree(self, app_config):
        """If entry is ungated, filtering must actually happen at run time.

        These are the two halves of the same guarantee: the mode is allowed
        without a password precisely because the extracted prompt gets filtered.
        """
        app_config.blacklist_prevent_execution = True
        set_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        assert Blacklist.is_active(), "ungated entry requires an active blacklist"
        positive, _negative = Prompter.filter_taken_prompt(TAKEN_POSITIVE, TAKEN_NEGATIVE)
        assert "forbidden" not in positive
