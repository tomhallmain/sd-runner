import json
import os
import struct

import pytest
from sd_runner.models.model import Model
from tests.utils import make_model
from sd_runner.globals import ArchitectureType, ResolutionGroup


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
            metadata=flags.get("metadata"),
            tensor_keys=flags.get("tensor_keys"),
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

    def test_illustrious_is_case_insensitive(self):
        assert self._det("illustriousXL_v1.safetensors") == ArchitectureType.ILLUSTRIOUS

    def test_filename_detects_families_without_a_folder(self):
        assert self._det("juggernautXL_v9.safetensors") == ArchitectureType.SDXL
        assert self._det("realvisxlV20.safetensors") == ArchitectureType.SDXL
        assert self._det("flux1-dev-fp8.safetensors") == ArchitectureType.FLUX
        assert self._det("flux-2-klein-4b.safetensors") == ArchitectureType.FLUX2_KLEIN_4B
        assert self._det("flux-2-klein-9b.safetensors") == ArchitectureType.FLUX2_KLEIN
        assert self._det("z_image_turbo.safetensors") == ArchitectureType.Z_IMAGE_TURBO
        assert self._det("chroma-v1.safetensors") == ArchitectureType.CHROMA

    def test_flux3_is_not_flux2_klein_or_flux1(self):
        assert self._det("flux-3-dev.safetensors") == ArchitectureType.FLUX3
        assert self._det("flux3.safetensors") == ArchitectureType.FLUX3
        assert self._det("flux-2-klein-4b.safetensors") == ArchitectureType.FLUX2_KLEIN_4B

    def test_krea2_and_minimax_h3_are_their_own_families(self):
        assert self._det("krea2_turbo_fp8_scaled.safetensors") == ArchitectureType.KREA2
        assert self._det("krea-2-turbo.safetensors") == ArchitectureType.KREA2
        assert self._det("flux1_krea_dev.safetensors") == ArchitectureType.FLUX
        assert self._det("minimax_h3_fl2va_pruned.safetensors") == ArchitectureType.MINIMAX_H3
        assert self._det("minimax-h3.safetensors") == ArchitectureType.MINIMAX_H3
        assert self._det("minimax_music3.safetensors") == ArchitectureType.UNKNOWN
        assert make_model("krea2_turbo.safetensors").get_standard_resolution_group() == ResolutionGroup.THIRTEEN_TWENTY_EIGHT
        assert make_model("minimax_h3.safetensors").get_standard_resolution_group() == ResolutionGroup.SEVEN_SIXTY_EIGHT

    def test_krea2_and_minimax_h3_tensor_keys(self):
        assert self._det("renamed.safetensors", tensor_keys={"txtfusion.projector.weight"}) == ArchitectureType.KREA2
        keys = {"video_patch_proj.weight", "audio_patch_proj.weight"}
        assert self._det("renamed.safetensors", tensor_keys=keys) == ArchitectureType.MINIMAX_H3

    def test_comfy_diffusion_models_path_is_not_a_folder_prefix(self):
        assert self._det(path="diffusion_models/flux/flux1-dev.safetensors") == ArchitectureType.FLUX
        assert self._det(path="diffusion_models/FluxKlein/flux-2-klein-4b.safetensors") == ArchitectureType.FLUX2_KLEIN_4B

    def test_unknown_family_is_not_assumed_sd15(self):
        assert self._det(path="Hi Dream\\model.safetensors") == ArchitectureType.UNKNOWN

    def test_sdxl_tensor_keys(self):
        keys = {"model.diffusion_model.middle_block.1.transformer_blocks.9.attn2.to_k.weight"}
        assert self._det("renamed.safetensors", tensor_keys=keys) == ArchitectureType.SDXL

    def test_sd15_tensor_keys(self):
        keys = {"middle_block.1.transformer_blocks.0.attn1.to_q.weight"}
        assert self._det("renamed.safetensors", tensor_keys=keys) == ArchitectureType.SD_15

    def test_flux2_tensor_keys_are_klein_family(self):
        keys = {
            "double_stream_modulation_img.lin.weight",
            "double_blocks.0.img_attn.norm.key_norm.weight",
        }
        assert self._det("renamed.safetensors", tensor_keys=keys) == ArchitectureType.FLUX2_KLEIN

    def test_flux2_tensor_keys_honor_4b_in_the_filename(self):
        keys = {
            "double_stream_modulation_img.lin.weight",
            "double_blocks.0.img_attn.norm.key_norm.weight",
        }
        assert self._det("custom-4b.safetensors", tensor_keys=keys) == ArchitectureType.FLUX2_KLEIN_4B

    def test_flux3_tensor_keys_beat_a_fluxklein_folder(self):
        keys = {
            "content_mode_blocks.image.0.attn_out.weight",
            "single_stream_modulations.txt.lin.weight",
        }
        result = self._det("renamed.safetensors", path="FluxKlein\\renamed.safetensors", tensor_keys=keys)
        assert result == ArchitectureType.FLUX3

    def test_flux1_tensor_keys(self):
        keys = {"double_blocks.0.img_attn.norm.key_norm.weight", "img_in.weight"}
        assert self._det("renamed.safetensors", tensor_keys=keys) == ArchitectureType.FLUX

    def test_metadata_modelspec_sd15(self):
        metadata = {"modelspec.architecture": "stable-diffusion-v1"}
        assert self._det("renamed.safetensors", metadata=metadata) == ArchitectureType.SD_15


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


def _write_safetensors(path, metadata=None, keys=()):
    header = {}
    if metadata:
        header["__metadata__"] = metadata
    for key in keys:
        header[key] = {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}
    raw = json.dumps(header).encode("utf-8")
    with open(path, "wb") as handle:
        handle.write(struct.pack("<Q", len(raw)))
        handle.write(raw)
        handle.write(b"\0\0\0\0")


class TestModelPaths:
    def test_full_path_finds_comfy_diffusion_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Model, "MODELS_DIR", str(tmp_path))
        dest = tmp_path / "diffusion_models" / "flux"
        dest.mkdir(parents=True)
        weight = dest / "flux1-dev.safetensors"
        weight.write_bytes(b"not a real header")
        model = Model(
            "flux1-dev.safetensors",
            path=os.path.join("flux", "flux1-dev.safetensors"),
            source_subdir="diffusion_models",
        )
        assert os.path.normcase(model.get_full_path()) == os.path.normcase(str(weight))

    def test_full_path_finds_comfy_lora_and_a1111_checkpoint(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Model, "MODELS_DIR", str(tmp_path))
        lora = tmp_path / "loras" / "detail.safetensors"
        lora.parent.mkdir()
        lora.write_bytes(b"x")
        checkpoint = tmp_path / "Stable-diffusion" / "XL" / "sdxl.safetensors"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"x")

        lora_model = Model("detail.safetensors", path="detail.safetensors", is_lora=True)
        checkpoint_model = Model("sdxl.safetensors", path=os.path.join("XL", "sdxl.safetensors"))
        assert os.path.normcase(lora_model.get_full_path()) == os.path.normcase(str(lora))
        assert os.path.normcase(checkpoint_model.get_full_path()) == os.path.normcase(str(checkpoint))

    def test_creation_date_uses_resolved_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Model, "MODELS_DIR", str(tmp_path))
        dest = tmp_path / "checkpoints"
        dest.mkdir()
        weight = dest / "model.safetensors"
        weight.write_bytes(b"x")
        model = Model("model.safetensors", path="model.safetensors")
        assert model.get_file_creation_date() != "Unknown"

    def test_header_overrides_fluxklein_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Model, "MODELS_DIR", str(tmp_path))
        dest = tmp_path / "diffusion_models" / "FluxKlein"
        dest.mkdir(parents=True)
        weight = dest / "renamed.safetensors"
        _write_safetensors(weight, keys=(
            "content_mode_blocks.image.0.attn_out.weight",
            "single_stream_modulations.txt.lin.weight",
        ))
        model = Model(
            "renamed.safetensors",
            path=os.path.join("FluxKlein", "renamed.safetensors"),
            source_subdir="diffusion_models",
        )
        assert model.is_flux3() is True
        assert model.is_flux2_klein() is False

    def test_load_models_scans_comfy_and_webui_layouts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Model, "MODELS_DIR", str(tmp_path))
        monkeypatch.setattr(Model, "CHECKPOINTS", {})
        monkeypatch.setattr(Model, "LORAS", {})
        diffusion = tmp_path / "diffusion_models"
        diffusion.mkdir()
        (diffusion / "flux-2-klein-4b.safetensors").write_bytes(b"x")
        loras = tmp_path / "loras"
        loras.mkdir()
        (loras / "detail.safetensors").write_bytes(b"x")
        webui = tmp_path / "Stable-diffusion" / "SD1.5"
        webui.mkdir(parents=True)
        (webui / "realistic.safetensors").write_bytes(b"x")

        Model.load_models(is_lora=False)
        Model.load_models(is_lora=True)

        klein = Model.CHECKPOINTS["flux-2-klein-4b.safetensors"]
        assert klein.is_flux2_klein_4b() is True
        assert klein.source_subdir == "diffusion_models"
        realistic = Model.CHECKPOINTS["realistic.safetensors"]
        assert realistic.is_sd_15() is True
        assert realistic.source_subdir == "Stable-diffusion"
        assert "detail.safetensors" in Model.LORAS
        assert Model.LORAS["detail.safetensors"].source_subdir == "loras"


class TestSimpleGenWorkflowSelection:
    def _setup(self, model_id, workflow_type):
        from sd_runner.generators.comfy import ComfyGen
        from sd_runner.globals import WorkflowType

        gen = ComfyGen()
        model = make_model(model_id)
        kwargs = {"lora": None} if workflow_type == WorkflowType.SIMPLE_IMAGE_GEN_LORA else {}
        prompt, returned, _vae = gen.prompt_setup(workflow_type, "test", None, model, **kwargs)
        return prompt, returned

    def test_simple_gen_uses_the_template_for_each_family(self):
        from sd_runner.globals import WorkflowType

        cases = {
            "krea2_turbo.safetensors": ("30:19", "value"),
            "minimax_h3.safetensors": ("140:131", "prompt"),
            "flux-3-dev.safetensors": ("18:17", "value"),
            "flux-2-klein-9b.safetensors": ("18:17", "value"),
        }
        for model_id, (node_id, key) in cases.items():
            prompt, model = self._setup(model_id, WorkflowType.SIMPLE_IMAGE_GEN)
            assert prompt.json[node_id]["inputs"][key] == ""
            assert model.architecture_type != ArchitectureType.UNKNOWN
            unets = [
                node["inputs"]["unet_name"]
                for node in prompt.json.values()
                if node["class_type"] == "UNETLoader"
            ]
            assert unets and all("\\" in name for name in unets)

    def test_flux2_klein_lora_keeps_its_existing_workflow(self):
        from sd_runner.globals import WorkflowType

        prompt, model = self._setup("flux-2-klein-4b.safetensors", WorkflowType.SIMPLE_IMAGE_GEN_LORA)
        assert model.is_flux2_klein_4b()
        assert prompt.workflow_filename == "image_flux2_text_to_image_4b.json"

    def test_flux3_image_edit_is_not_offered(self):
        from sd_runner.globals import WorkflowType

        with pytest.raises(Exception):
            self._setup("flux-3-dev.safetensors", WorkflowType.IMAGE_EDIT)

    def test_a_source_image_keeps_its_output_size(self):
        from sd_runner.models.resolution import Resolution
        from sd_runner.workflow_prompts.comfy import WorkflowPromptComfy

        prompt = WorkflowPromptComfy.__new__(WorkflowPromptComfy)
        prompt.json = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "in.png"}},
            "2": {"class_type": "GetImageSize", "inputs": {"image": ["1", 0]}},
            "3": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": ["2", 0], "height": ["2", 1], "batch_size": 1},
            },
        }
        prompt.set_latent_dimensions(Resolution(width=1328, height=1328))
        assert prompt.json["3"]["inputs"]["width"] == ["2", 0]
        assert prompt.json["3"]["inputs"]["height"] == ["2", 1]

    def test_a_resolution_selector_can_be_overwritten(self):
        from sd_runner.models.resolution import Resolution
        from sd_runner.workflow_prompts.comfy import WorkflowPromptComfy

        prompt = WorkflowPromptComfy("image_krea2_turbo_t2i.json")
        prompt.set_latent_dimensions(Resolution(width=1328, height=1328))
        latent = next(
            node for node in prompt.json.values() if node["class_type"] == "EmptyLatentImage"
        )
        assert latent["inputs"]["width"] == 1328
        assert latent["inputs"]["height"] == 1328
