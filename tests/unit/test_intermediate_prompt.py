"""Intermediate-pass prompts -- the pre-pass on the reference image.

Only prompt text is configurable; everything else the pass needs is inherited
from the main configuration. These cover the saved list, the live state that a
run reads, and the single seam the run path will call.

``PresetsWindow`` is imported inside each test to keep PySide6 out of collection
for the rest of the unit suite.
"""

from ui_qt.presets.intermediate_prompt import IntermediatePrompt
from utils.globals import WorkflowType


def _window():
    from ui_qt.presets.presets_window import PresetsWindow
    return PresetsWindow


def _prompt(name="bw", positive="black and white", **kwargs):
    return IntermediatePrompt(name=name, positive_tags=positive, **kwargs)


# ---------------------------------------------------------------------------
# The data class
# ---------------------------------------------------------------------------

class TestIntermediatePrompt:
    def test_it_round_trips(self):
        original = _prompt(negative_tags="colour", use_negative=True)
        restored = IntermediatePrompt.from_dict(original.to_dict())
        assert restored.name == "bw"
        assert restored.positive_tags == "black and white"
        assert restored.negative_tags == "colour"
        assert restored.use_negative is True

    def test_the_negative_is_opt_out_by_default(self):
        """Most runs want the main configuration's negative prompt."""
        assert _prompt().use_negative is False

    def test_a_prompt_with_no_text_is_invalid(self):
        assert not _prompt(positive="   ").is_valid()

    def test_a_prompt_with_no_name_is_invalid(self):
        assert not _prompt(name="").is_valid()

    def test_the_workflow_defaults_to_image_edit(self):
        assert _prompt().workflow_type == WorkflowType.IMAGE_EDIT.name

    def test_the_workflow_is_stored_by_name(self):
        prompt = _prompt(workflow_type=WorkflowType.CONTROLNET)
        assert prompt.workflow_type == "CONTROLNET"
        assert IntermediatePrompt.from_dict(prompt.to_dict()).workflow_type == "CONTROLNET"

    def test_only_image_consuming_workflows_are_eligible(self):
        """A pass with no image to transform has nothing to do."""
        eligible = IntermediatePrompt.eligible_workflows()
        assert WorkflowType.IMG2IMG in eligible
        assert WorkflowType.SIMPLE_IMAGE_GEN not in eligible

    def test_an_old_entry_without_a_workflow_gets_the_default(self):
        restored = IntermediatePrompt.from_dict({"name": "bw", "positive_tags": "mono"})
        assert restored.workflow_type == WorkflowType.IMAGE_EDIT.name


# ---------------------------------------------------------------------------
# What a run reads
# ---------------------------------------------------------------------------

class TestActivePrompt:
    def test_nothing_is_active_when_the_pass_is_off(self, app_cache):
        w = _window()
        w.intermediate_enabled = False
        w.intermediate_current = _prompt()
        assert w.get_active_intermediate_prompt() is None

    def test_nothing_is_active_when_never_configured(self, app_cache):
        w = _window()
        w.intermediate_enabled = True
        w.intermediate_current = None
        assert w.get_active_intermediate_prompt() is None

    def test_nothing_is_active_without_a_positive_prompt(self, app_cache):
        """Enabled but empty must not run a pass with no instruction."""
        w = _window()
        w.intermediate_enabled = True
        w.intermediate_current = _prompt(positive="  ")
        assert w.get_active_intermediate_prompt() is None

    def test_the_prompt_is_active_when_enabled_and_filled(self, app_cache):
        w = _window()
        w.intermediate_enabled = True
        w.intermediate_current = _prompt()
        active = w.get_active_intermediate_prompt()
        assert active is not None
        assert active.positive_tags == "black and white"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_saved_prompts_round_trip_through_the_cache(self, app_cache):
        w = _window()
        w.intermediate_prompts.append(_prompt())
        w.store_intermediate_prompts(persist=False)
        w.intermediate_prompts.clear()
        w.set_intermediate_prompts()
        assert [p.name for p in w.intermediate_prompts] == ["bw"]

    def test_the_live_state_round_trips_too(self, app_cache):
        w = _window()
        w.intermediate_enabled = True
        w.intermediate_current = _prompt(negative_tags="colour", use_negative=True)
        w.store_intermediate_prompts(persist=False)
        w.intermediate_enabled = False
        w.intermediate_current = None
        w.set_intermediate_prompts()
        assert w.intermediate_enabled is True
        assert w.intermediate_current.negative_tags == "colour"
        assert w.intermediate_current.use_negative is True

    def test_loading_replaces_rather_than_appends(self, app_cache):
        w = _window()
        w.intermediate_prompts.append(_prompt())
        w.store_intermediate_prompts(persist=False)
        w.set_intermediate_prompts()
        w.set_intermediate_prompts()
        assert len(w.intermediate_prompts) == 1

    def test_an_invalid_saved_entry_is_dropped_on_load(self, app_cache):
        w = _window()
        w.intermediate_prompts.append(_prompt(name="stale"))
        app_cache.set(w.INTERMEDIATE_PROMPTS_KEY,
                      [{"name": "empty", "positive_tags": ""}])
        w.set_intermediate_prompts()
        # Empty rather than ["stale"]: proves the load ran and filtered, rather
        # than passing because nothing was ever there.
        assert w.intermediate_prompts == []

    def test_an_absent_live_state_loads_as_off(self, app_cache):
        """Loading clears live state rather than leaving the previous value.

        Set first, or this passes on the reset fixture's defaults without ever
        exercising the load.
        """
        w = _window()
        w.intermediate_enabled = True
        w.intermediate_current = _prompt()
        w.set_intermediate_prompts()
        assert w.intermediate_enabled is False
        assert w.intermediate_current is None


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestLookup:
    def test_it_finds_a_prompt_by_name(self, app_cache):
        w = _window()
        prompt = _prompt()
        w.intermediate_prompts.append(prompt)
        assert w.get_intermediate_prompt_by_name("bw") is prompt

    def test_an_unknown_name_returns_none(self, app_cache):
        assert _window().get_intermediate_prompt_by_name("nope") is None
