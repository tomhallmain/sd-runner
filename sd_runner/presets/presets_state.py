"""Presets, stashed configs and the intermediate pre-pass, as they are stored.

Run configuration: the named prompt presets, the named run-config snapshots,
and the pre-pass a run transforms its reference image with. A command-line
script, a test, or a server running without a window reaches them through here;
``PresetsWindow`` is the editor for the same state.

The ``app_info_cache`` import stays inside each function: it builds its
singleton at import time, and importing this module should not force that.
"""

from sd_runner.presets.intermediate_prompt import IntermediatePrompt
from sd_runner.presets.preset import Preset
from sd_runner.presets.stashed_config import StashedConfig
from utils.translations import I18N

_ = I18N._


class PresetsState:
    """The three lists, and the cache they are loaded from and stored to."""

    recent_presets = []

    STASHED_CONFIGS_KEY = "stashed_configs"
    stashed_configs = []
    MAX_STASHED_CONFIGS = 50

    INTERMEDIATE_PROMPTS_KEY = "intermediate_prompts"
    INTERMEDIATE_PASS_KEY = "intermediate_pass"
    intermediate_prompts = []
    MAX_INTERMEDIATE_PROMPTS = 50
    #: Live state of the pre-pass, as opposed to the saved list: whether it runs
    #: at all, and the prompt it runs with. Held here rather than on
    #: RunnerAppConfig so that prompt text stays out of run history and out of
    #: stashed configs, which deliberately drop it.
    intermediate_enabled = False
    intermediate_current = None

    @staticmethod
    def set_recent_presets():
        from utils.app_info_cache import app_info_cache
        for preset_dict in list(app_info_cache.get("recent_presets", default_val=[])):
            PresetsState.recent_presets.append(Preset.from_dict(preset_dict))

    @staticmethod
    def store_recent_presets(persist: bool = True):
        """Store recent presets to cache.

        Writes through to disk unless *persist* is False. The write is skipped
        when nothing actually changed, so calling this from an edit handler is
        cheap even when the edit was a no-op. store_info_cache passes False
        because it writes once itself after collecting every subsystem.
        """
        from utils.app_info_cache import app_info_cache
        preset_dicts = []
        for preset in PresetsState.recent_presets:
            preset_dicts.append(preset.to_dict())
        app_info_cache.set("recent_presets", preset_dicts)

        if persist:
            app_info_cache.store(only_if_changed=True)

    @staticmethod
    def set_stashed_configs():
        """Load stashed configs from cache, replacing whatever is held."""
        from utils.app_info_cache import app_info_cache
        PresetsState.stashed_configs.clear()
        for stash_dict in list(app_info_cache.get(PresetsState.STASHED_CONFIGS_KEY, default_val=[])):
            stash = StashedConfig.from_dict(stash_dict)
            if stash.is_valid():
                PresetsState.stashed_configs.append(stash)

    @staticmethod
    def store_stashed_configs(persist: bool = True):
        """Store stashed configs to cache.

        Writes through to disk unless *persist* is False, on the same terms as
        ``store_recent_presets``.
        """
        from utils.app_info_cache import app_info_cache
        app_info_cache.set(
            PresetsState.STASHED_CONFIGS_KEY,
            [stash.to_dict() for stash in PresetsState.stashed_configs],
        )
        if persist:
            app_info_cache.store(only_if_changed=True)

    @staticmethod
    def get_stashed_config_by_name(name) -> 'StashedConfig | None':
        for stash in PresetsState.stashed_configs:
            if stash.name == name:
                return stash
        return None

    @staticmethod
    def get_stashed_config_names():
        return sorted(stash.name for stash in PresetsState.stashed_configs)

    @staticmethod
    def set_intermediate_prompts():
        """Load the saved list and the live pre-pass state from cache."""
        from utils.app_info_cache import app_info_cache
        PresetsState.intermediate_prompts.clear()
        for prompt_dict in list(app_info_cache.get(PresetsState.INTERMEDIATE_PROMPTS_KEY, default_val=[])):
            prompt = IntermediatePrompt.from_dict(prompt_dict)
            if prompt.is_valid():
                PresetsState.intermediate_prompts.append(prompt)

        state = app_info_cache.get(PresetsState.INTERMEDIATE_PASS_KEY, default_val={}) or {}
        PresetsState.intermediate_enabled = bool(state.get("enabled", False))
        current = state.get("current")
        PresetsState.intermediate_current = (
            IntermediatePrompt.from_dict(current) if isinstance(current, dict) else None
        )

    @staticmethod
    def store_intermediate_prompts(persist: bool = True):
        """Store the saved list and the live pre-pass state to cache.

        Writes through to disk unless *persist* is False, on the same terms as
        ``store_recent_presets``.
        """
        from utils.app_info_cache import app_info_cache
        app_info_cache.set(
            PresetsState.INTERMEDIATE_PROMPTS_KEY,
            [prompt.to_dict() for prompt in PresetsState.intermediate_prompts],
        )
        current = PresetsState.intermediate_current
        app_info_cache.set(PresetsState.INTERMEDIATE_PASS_KEY, {
            "enabled": PresetsState.intermediate_enabled,
            "current": current.to_dict() if current is not None else None,
        })

        if persist:
            app_info_cache.store(only_if_changed=True)

    @staticmethod
    def get_active_intermediate_prompt() -> 'IntermediatePrompt | None':
        """The prompt a run should pre-pass with, or None when it should not.

        The single seam the run path reads: None means no pre-pass, for any
        reason -- switched off, never configured, or configured with no text.
        """
        if not PresetsState.intermediate_enabled:
            return None
        current = PresetsState.intermediate_current
        if current is None or not current.positive_tags.strip():
            return None
        return current

    @staticmethod
    def get_intermediate_prompt_by_name(name) -> 'IntermediatePrompt | None':
        for prompt in PresetsState.intermediate_prompts:
            if prompt.name == name:
                return prompt
        return None

    @staticmethod
    def get_preset_by_name(name):
        for preset in PresetsState.recent_presets:
            if name == preset.name:
                return preset
        raise Exception(f"No preset found with name: {name}. Set it on the Presets Window.")

    @staticmethod
    def get_preset_by_suffix(suffix: str) -> 'Preset | None':
        """Return the first preset whose edit_suffix matches *suffix*, or None.

        A preset matches if its edit_suffix equals the incoming suffix or is a
        prefix of it (e.g. preset "_cher" matches incoming "_cherry").
        """
        for preset in PresetsState.recent_presets:
            if preset.edit_suffix and suffix.startswith(preset.edit_suffix):
                return preset
        return None

    @staticmethod
    def get_preset_names():
        return sorted(list(map(lambda x: x.name, PresetsState.recent_presets)))

    @staticmethod
    def get_most_recent_preset_name():
        return (
            PresetsState.recent_presets[0].name
            if len(PresetsState.recent_presets) > 0
            else _("New Preset (ERROR no presets found)")
        )

    @staticmethod
    def next_preset(alert_callback):
        if len(PresetsState.recent_presets) == 0:
            alert_callback(_("Not enough presets found."))
        next_preset = PresetsState.recent_presets[-1]
        PresetsState.recent_presets.remove(next_preset)
        PresetsState.recent_presets.insert(0, next_preset)
        return next_preset
