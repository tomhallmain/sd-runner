import pytest
from sd_runner.models import Model
from utils.globals import ArchitectureType, ResolutionGroup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_model(id="model.safetensors", path="some/path", **kwargs):
    """Construct a Model with an explicit path to avoid MODELS_DIR dependency."""
    return Model(id=id, path=path, **kwargs)


# ---------------------------------------------------------------------------
# determine_architecture_type — flag combinations
# ---------------------------------------------------------------------------

class TestDetermineArchitectureType:
    def _det(self, model_id="model.safetensors", path=None, **flags):
        return Model.determine_architecture_type(
            model_id,
            path,
            is_xl=flags.get("is_xl", False),
            is_turbo=flags.get("is_turbo", False),
            is_flux=flags.get("is_flux", False),
            is_chroma=flags.get("is_chroma", False),
            is_z_image_turbo=flags.get("is_z_image_turbo", False),
            is_qwen=flags.get("is_qwen", False),
            is_flux2_klein=flags.get("is_flux2_klein", False),
        )

    def test_illustrious_by_model_id(self):
        assert self._det("IllustriousXL_v1.safetensors") == ArchitectureType.ILLUSTRIOUS

    def test_chroma_by_flag(self):
        assert self._det(is_chroma=True) == ArchitectureType.CHROMA

    def test_chroma_by_path(self):
        assert self._det(path="chroma/model.safetensors") == ArchitectureType.CHROMA

    def test_qwen_by_flag(self):
        assert self._det(is_qwen=True) == ArchitectureType.QWEN

    def test_qwen_by_path(self):
        assert self._det(path="qwen2vl/model.safetensors") == ArchitectureType.QWEN

    def test_sdxl_by_flag(self):
        assert self._det(is_xl=True) == ArchitectureType.SDXL

    def test_sdxl_by_path_prefix(self):
        assert self._det(path="XL\\sdxl_base.safetensors") == ArchitectureType.SDXL

    def test_turbo_by_flag(self):
        assert self._det(is_turbo=True) == ArchitectureType.TURBO

    def test_turbo_by_path_prefix(self):
        assert self._det(path="Turbo\\turbo_model.safetensors") == ArchitectureType.TURBO

    def test_flux_by_flag(self):
        assert self._det(is_flux=True) == ArchitectureType.FLUX

    def test_flux_by_path_prefix(self):
        assert self._det(path="flux/flux_dev.safetensors") == ArchitectureType.FLUX

    def test_flux2_klein_9b_by_flag(self):
        assert self._det(is_flux2_klein=True) == ArchitectureType.FLUX2_KLEIN

    def test_flux2_klein_4b_by_id_contains_4b(self):
        assert self._det("fluxklein4b_model.safetensors", is_flux2_klein=True) == ArchitectureType.FLUX2_KLEIN_4B

    def test_flux2_klein_4b_not_confused_with_version_string(self):
        # "v14base" contains "4b" as part of "14" — should not be classified as 4B
        result = self._det("fluxklein_v14base.safetensors", is_flux2_klein=True)
        assert result == ArchitectureType.FLUX2_KLEIN

    def test_flux2_klein_by_path_prefix(self):
        assert self._det(path="fluxklein/model.safetensors") == ArchitectureType.FLUX2_KLEIN

    def test_sd15_by_path_scope(self):
        assert self._det(path="SD1.5\\realistic_vision.safetensors") == ArchitectureType.SD_15

    def test_unknown_fallback(self):
        assert self._det("unknown_model.safetensors", path="misc/model.safetensors") == ArchitectureType.UNKNOWN

    def test_illustrious_beats_xl_flag(self):
        # model_id check runs first, so Illustrious wins even with is_xl=True
        result = self._det("IllustriousXL_v1.safetensors", is_xl=True)
        assert result == ArchitectureType.ILLUSTRIOUS


# ---------------------------------------------------------------------------
# Model.is_* predicates — consistent with architecture_type
# ---------------------------------------------------------------------------

class TestModelPredicates:
    def test_flux_predicate(self):
        m = make_model(is_flux=True)
        assert m.is_flux() is True
        assert m.is_xl() is False
        assert m.is_chroma() is False

    def test_sdxl_predicate(self):
        m = make_model(is_xl=True)
        assert m.is_xl() is True
        assert m.is_flux() is False

    def test_illustrious_is_xl(self):
        m = make_model("IllustriousXL_v1.safetensors")
        assert m.is_xl() is True
        assert m.is_illustrious() is True

    def test_chroma_predicate(self):
        m = make_model(is_chroma=True)
        assert m.is_chroma() is True
        assert m.is_flux() is False

    def test_flux2_klein_9b_predicate(self):
        m = make_model(is_flux2_klein=True)
        assert m.is_flux2_klein() is True
        assert m.is_flux2_klein_9b() is True
        assert m.is_flux2_klein_4b() is False
        assert m.is_flux() is False

    def test_flux2_klein_4b_predicate(self):
        m = make_model("fluxklein4b.safetensors", is_flux2_klein=True)
        assert m.is_flux2_klein() is True
        assert m.is_flux2_klein_4b() is True
        assert m.is_flux2_klein_9b() is False

    def test_lora_predicates_always_false(self):
        # When is_lora=True the is_* predicates all return False
        m = make_model(is_flux=True, is_lora=True)
        assert m.is_flux() is False
        assert m.is_xl() is False

    def test_sd15_predicate(self):
        m = make_model(path="SD1.5\\model.safetensors")
        assert m.is_sd_15() is True
        assert m.is_xl() is False

    def test_qwen_predicate(self):
        m = make_model(is_qwen=True)
        assert m.is_qwen() is True

    def test_unknown_architecture_no_predicate_true(self):
        m = make_model("unknown.safetensors", path="misc/unknown.safetensors")
        assert m.is_flux() is False
        assert m.is_xl() is False
        assert m.is_chroma() is False
        assert m.is_qwen() is False


# ---------------------------------------------------------------------------
# get_standard_resolution_group
# ---------------------------------------------------------------------------

class TestGetStandardResolutionGroup:
    def test_sd15_resolution(self):
        m = make_model(path="SD1.5\\model.safetensors")
        assert m.get_standard_resolution_group() == ResolutionGroup.SEVEN_SIXTY_EIGHT

    def test_sdxl_resolution(self):
        m = make_model(is_xl=True)
        assert m.get_standard_resolution_group() == ResolutionGroup.TEN_TWENTY_FOUR

    def test_flux_resolution(self):
        m = make_model(is_flux=True)
        assert m.get_standard_resolution_group() == ResolutionGroup.TEN_TWENTY_FOUR

    def test_flux2_klein_resolution(self):
        m = make_model(is_flux2_klein=True)
        assert m.get_standard_resolution_group() == ResolutionGroup.TEN_TWENTY_FOUR

    def test_chroma_resolution(self):
        m = make_model(is_chroma=True)
        assert m.get_standard_resolution_group() == ResolutionGroup.TEN_TWENTY_FOUR

    def test_qwen_resolution(self):
        m = make_model(is_qwen=True)
        assert m.get_standard_resolution_group() == ResolutionGroup.THIRTEEN_TWENTY_EIGHT

    def test_illustrious_resolution(self):
        m = make_model("IllustriousXL_v1.safetensors")
        assert m.get_standard_resolution_group() == ResolutionGroup.FIFTEEN_THIRTY_SIX

    def test_unknown_falls_back_to_512(self):
        m = make_model("unknown.safetensors", path="misc/unknown.safetensors")
        assert m.get_standard_resolution_group() == ResolutionGroup.FIVE_ONE_TWO


# ---------------------------------------------------------------------------
# get_lora_text
# ---------------------------------------------------------------------------

class TestGetLoraText:
    def test_basic_lora_text(self):
        m = make_model("my_lora.safetensors", is_lora=True, lora_strength=0.8)
        text = m.get_lora_text()
        assert text == " <lora:my_lora:0.8>"

    def test_extension_stripped(self):
        m = make_model("detail.pt", is_lora=True, lora_strength=0.6)
        text = m.get_lora_text()
        assert text == " <lora:detail:0.6>"

    def test_no_extension_in_id(self):
        m = make_model("add_detail", is_lora=True, lora_strength=0.7)
        text = m.get_lora_text()
        assert text == " <lora:add_detail:0.7>"

    def test_raises_when_not_lora(self):
        m = make_model(is_lora=False)
        with pytest.raises(Exception):
            m.get_lora_text()


# ---------------------------------------------------------------------------
# __eq__ and __str__
# ---------------------------------------------------------------------------

class TestModelEquality:
    def test_equal_same_id(self):
        a = make_model("model.safetensors")
        b = make_model("model.safetensors")
        assert a == b

    def test_not_equal_different_id(self):
        a = make_model("model_a.safetensors")
        b = make_model("model_b.safetensors")
        assert a != b

    def test_not_equal_to_string(self):
        m = make_model("model.safetensors")
        assert m != "model.safetensors"

    def test_not_equal_to_none(self):
        m = make_model("model.safetensors")
        assert m != None  # noqa: E711


class TestModelStr:
    def test_str_non_lora_contains_architecture(self):
        m = make_model(is_flux=True)
        s = str(m)
        assert "FLUX" in s

    def test_str_lora_contains_strength(self):
        m = make_model("detail.safetensors", is_lora=True, lora_strength=0.75)
        s = str(m)
        assert "LoRA" in s or "lora" in s.lower()
        assert "0.75" in s
