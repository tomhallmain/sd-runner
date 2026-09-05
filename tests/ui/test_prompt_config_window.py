"""Prompt configuration widgets writing through to the shared config.

This window owns no state. It is handed ``AppWindow.runner_app_config`` and
edits it in place, so every widget is wired to a handler that rewrites the whole
config -- there is no Apply button, and a value that fails to write through is
silently lost at the next run rather than reported.

Two class-level references carry that arrangement past the widgets: the config
itself, which ``set_args_from_prompter_config`` reads when a run is built, and
the open instance, which is how a run in progress picks up edits that are on
screen but not yet applied. Both are asserted here, including their release on
close.
"""

import pytest

from sd_runner.globals import Sampler, Scheduler
from sd_runner.runs.runner_app_config import RunnerAppConfig
from sd_runner.ui.prompts.prompt_config_window import PromptConfigWindow
from tests.utils import close_window, make_app_actions, make_run_config


@pytest.fixture
def config():
    return RunnerAppConfig()


@pytest.fixture
def window(qapp, config):
    win = PromptConfigWindow(None, make_app_actions(), config)
    try:
        yield win
    finally:
        close_window(win)


def category(config, name):
    return config.prompter_config.get_category_config(name)


# ---------------------------------------------------------------------------
# Generation parameters
# ---------------------------------------------------------------------------

class TestGenerationParameters:
    def test_the_sampler_combo_writes_through(self, window, config):
        window._sampler_combo.setCurrentText(Sampler.DDIM.display())
        assert config.sampler == Sampler.DDIM.name

    def test_the_scheduler_combo_writes_through(self, window, config):
        window._scheduler_combo.setCurrentText(Scheduler.KARRAS.display())
        assert config.scheduler == Scheduler.KARRAS.name

    def test_a_numeric_field_writes_through(self, window, config):
        window._edit_steps.setText("42")
        assert config.steps == "42"

    def test_an_emptied_field_falls_back_rather_than_raising(self, window, config):
        """The handler runs on every keystroke, so it sees the field mid-edit."""
        window._edit_steps.setText("")
        assert config.steps == "-1"

    def test_the_multiplier_combo_writes_through(self, window, config):
        window._multiplier_combo.setCurrentText("2")
        assert config.prompter_config.multiplier == 2.0


# ---------------------------------------------------------------------------
# Option checkboxes
# ---------------------------------------------------------------------------

class TestOptionCheckboxes:
    def test_checking_an_option_writes_through(self, window, config):
        window._cb_tags_at_start.setChecked(not config.tags_apply_to_start)
        assert config.tags_apply_to_start is window._cb_tags_at_start.isChecked()

    def test_unchecking_it_writes_through_too(self, window, config):
        window._cb_tags_at_start.setChecked(True)
        window._cb_tags_at_start.setChecked(False)
        assert config.tags_apply_to_start is False

    def test_sparse_mix_reaches_the_prompter_config_as_well(self, window, config):
        """Held in both places; the prompter reads its own copy."""
        window._cb_sparse_mix.setChecked(True)
        assert config.sparse_mixed_tags is True
        assert config.prompter_config.sparse_mixed_tags is True


# ---------------------------------------------------------------------------
# Category counts
# ---------------------------------------------------------------------------

class TestCategoryCounts:
    def test_the_low_combo_writes_through(self, window, config):
        low, high = window._cat_combos["colors"]
        high.setCurrentText("5")
        low.setCurrentText("2")
        assert category(config, "colors").low == 2

    def test_the_high_combo_writes_through(self, window, config):
        low, high = window._cat_combos["colors"]
        high.setCurrentText("5")
        assert category(config, "colors").high == 5

    def test_a_high_below_the_low_is_raised_to_it(self, window, config):
        """An inverted range samples nothing, so the widget pair cannot express
        one."""
        low, high = window._cat_combos["colors"]
        low.setCurrentText("4")
        high.setCurrentText("1")
        assert category(config, "colors").high == 4

    def test_every_category_on_screen_is_editable(self, window, config):
        """Each pair is built in a loop, so one name that does not match a real
        category writes into a discarded default and never reports it."""
        for name, (low, _high) in window._cat_combos.items():
            low.setCurrentText("3")
            assert category(config, name).low == 3, name

    def test_the_range_and_the_inclusion_chance_do_not_overwrite_each_other(
        self, window, config,
    ):
        """Both live on one ConceptConfiguration and the handler rewrites the
        whole config on every edit, so editing either must leave the other."""
        window._sliders["animals_inclusion"].setValue(42)
        low, _high = window._cat_combos["animals"]
        low.setCurrentText("1")
        assert category(config, "animals").low == 1
        assert category(config, "animals").inclusion_chance == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Chance sliders
# ---------------------------------------------------------------------------

class TestChanceSliders:
    def test_a_slider_writes_a_fraction_not_a_percentage(self, window, config):
        window._sliders["emphasis"].setValue(30)
        assert config.prompter_config.emphasis_chance == pytest.approx(0.30)

    def test_zero_is_written_rather_than_skipped(self, window, config):
        """0.0 is a meaningful setting -- it turns the behaviour off."""
        window._sliders["emphasis"].setValue(50)
        window._sliders["emphasis"].setValue(0)
        assert config.prompter_config.emphasis_chance == 0.0

    def test_the_witticisms_slider_splits_the_weights(self, window, config):
        window._witticisms_slider.setValue(75)
        sayings, puns = config.prompter_config.get_witticisms_weights()
        assert puns == pytest.approx(1.5)
        assert sayings == pytest.approx(0.5)

    def test_an_inclusion_slider_reaches_its_category(self, window, config):
        window._sliders["dress_inclusion"].setValue(20)
        assert category(config, "dress").inclusion_chance == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# The class-level references a run reads
# ---------------------------------------------------------------------------

class TestTheOpenInstance:
    def test_opening_registers_the_window(self, window):
        assert PromptConfigWindow.get_prompt_config_window_instance() is window

    def test_opening_registers_the_config(self, window, config):
        assert PromptConfigWindow.get_runner_app_config() is config

    def test_the_class_level_sync_reaches_the_open_window(self, window, config):
        """A run calls this so an open window's edits are not left behind."""
        window._edit_steps.setText("7")
        config.steps = "clobbered"
        PromptConfigWindow.sync_config_from_widgets()
        assert config.steps == "7"

    def test_it_is_a_no_op_once_the_window_is_closed(self, qapp, config):
        win = PromptConfigWindow(None, make_app_actions(), config)
        win._edit_steps.setText("7")
        win.close()
        config.steps = "set after closing"
        PromptConfigWindow.sync_config_from_widgets()
        assert config.steps == "set after closing"

    def test_closing_clears_the_instance(self, qapp, config):
        win = PromptConfigWindow(None, make_app_actions(), config)
        win.close()
        assert PromptConfigWindow.get_prompt_config_window_instance() is None

    def test_escape_clears_it_too(self, qapp, config):
        """Escape reaches reject(), which does not fire closeEvent."""
        win = PromptConfigWindow(None, make_app_actions(), config)
        win.reject()
        assert PromptConfigWindow.get_prompt_config_window_instance() is None

    def test_closing_applies_what_was_on_screen(self, qapp, config):
        win = PromptConfigWindow(None, make_app_actions(), config)
        win._edit_steps.setText("7")
        config.steps = "clobbered"
        win.close()
        assert config.steps == "7"


# ---------------------------------------------------------------------------
# Pushing onto a run
# ---------------------------------------------------------------------------

class TestSetArgsFromPrompterConfig:
    def test_the_numeric_settings_reach_the_run(self, window, config):
        window._edit_steps.setText("33")
        window._edit_cfg.setText("7.5")
        args = make_run_config()
        PromptConfigWindow.set_args_from_prompter_config(args)
        assert (args.steps, args.cfg) == (33, 7.5)

    def test_the_sampler_reaches_the_run_as_an_enum(self, window, config):
        window._sampler_combo.setCurrentText(Sampler.DDIM.display())
        args = make_run_config()
        PromptConfigWindow.set_args_from_prompter_config(args)
        assert args.sampler is Sampler.DDIM

    def test_unapplied_edits_are_picked_up_first(self, window, config):
        """It syncs before it reads, so a value typed but not yet applied is
        not lost when the run is built."""
        window._edit_steps.setText("33")
        config.steps = "clobbered"
        args = make_run_config()
        PromptConfigWindow.set_args_from_prompter_config(args)
        assert args.steps == 33
