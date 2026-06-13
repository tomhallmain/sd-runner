import pytest
from utils.globals import (
    ArchitectureType,
    BlacklistMode,
    BlacklistPromptMode,
    ModelBlacklistMode,
    PromptMode,
    ResolutionGroup,
    SoftwareType,
    WorkflowType,
)


class TestPromptMode:
    def test_all_members_round_trip_via_get(self):
        for mode in PromptMode:
            assert PromptMode.get(mode.name) == mode

    def test_get_unknown_name_raises(self):
        with pytest.raises(Exception):
            PromptMode.get("NONEXISTENT_MODE")

    def test_display_returns_nonempty_string(self):
        for mode in PromptMode:
            assert isinstance(mode.display(), str) and mode.display()

    def test_display_values_covers_all_members(self):
        vals = PromptMode.display_values()
        assert len(vals) == len(PromptMode)

    def test_nsfw_flag(self):
        assert PromptMode.SFW.is_nsfw() is False
        assert PromptMode.NSFW.is_nsfw() is True
        assert PromptMode.NSFL.is_nsfw() is True
        assert PromptMode.RANDOM.is_nsfw() is False


class TestWorkflowType:
    def test_get_translation_nonempty_for_all(self):
        for wt in WorkflowType:
            translation = wt.get_translation()
            assert isinstance(translation, str) and translation, (
                f"WorkflowType.{wt.name} returned empty translation"
            )

    def test_get_by_name(self):
        for wt in WorkflowType:
            assert WorkflowType.get(wt.name) == wt

    def test_get_unknown_raises(self):
        with pytest.raises(Exception):
            WorkflowType.get("COMPLETELY_NONEXISTENT_XYZ")


class TestBlacklistMode:
    def test_display_round_trip(self):
        for mode in BlacklistMode:
            display_str = mode.display()
            assert BlacklistMode.from_display(display_str) == mode

    def test_display_values_covers_all(self):
        vals = BlacklistMode.display_values()
        assert len(vals) == len(BlacklistMode)


class TestBlacklistPromptMode:
    def test_display_round_trip(self):
        for mode in BlacklistPromptMode:
            display_str = mode.display()
            assert BlacklistPromptMode.from_display(display_str) == mode


class TestModelBlacklistMode:
    def test_display_round_trip(self):
        for mode in ModelBlacklistMode:
            display_str = mode.display()
            assert ModelBlacklistMode.from_display(display_str) == mode


class TestArchitectureType:
    def test_is_xl_true_for_xl_and_illustrious(self):
        assert ArchitectureType.SDXL.is_xl() is True
        assert ArchitectureType.ILLUSTRIOUS.is_xl() is True

    def test_is_xl_false_for_others(self):
        non_xl = [a for a in ArchitectureType if a not in (ArchitectureType.SDXL, ArchitectureType.ILLUSTRIOUS)]
        for arch in non_xl:
            assert arch.is_xl() is False, f"{arch.name} should not be XL"

    def test_display_returns_nonempty_for_all(self):
        for arch in ArchitectureType:
            d = arch.display()
            assert isinstance(d, str) and d


class TestSoftwareType:
    _LOCAL = {
        SoftwareType.ComfyUI,
        SoftwareType.SDWebUI,
        SoftwareType.Forge,
        SoftwareType.SDNext,
        SoftwareType.SwarmUI,
        SoftwareType.InvokeAI,
        SoftwareType.Fooocus,
    }

    def test_local_types_are_not_cloud(self):
        for st in self._LOCAL:
            assert st.is_cloud() is False, f"{st.name} should be local"

    def test_non_local_types_are_cloud(self):
        for st in SoftwareType:
            if st not in self._LOCAL:
                assert st.is_cloud() is True, f"{st.name} should be cloud"


class TestResolutionGroup:
    def test_description_nonempty_for_all(self):
        for rg in ResolutionGroup:
            d = rg.get_description()
            assert isinstance(d, str) and d

    def test_display_values_covers_all_members(self):
        vals = ResolutionGroup.display_values()
        assert len(vals) == len(ResolutionGroup)

    def test_get_by_name_round_trip(self):
        for rg in ResolutionGroup:
            assert ResolutionGroup.get(rg.name) == rg
