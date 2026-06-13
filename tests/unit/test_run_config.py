import pytest
from sd_runner.run_config import RunConfig
from utils.globals import WorkflowType


def make_run_config(**kwargs):
    return RunConfig(args=kwargs if kwargs else None)


# ---------------------------------------------------------------------------
# get() — dict args, object args, None args
# ---------------------------------------------------------------------------

class TestRunConfigGet:
    def test_get_returns_none_when_no_args(self):
        rc = RunConfig(args=None)
        assert rc.seed is None

    def test_get_returns_value_from_dict(self):
        rc = make_run_config(seed=42)
        assert rc.seed == 42

    def test_get_returns_value_from_object(self):
        class Namespace:
            seed = 99
            model_tags = None  # prevent spurious model_switch_detected
        rc = RunConfig(args=Namespace())
        assert rc.seed == 99

    def test_get_returns_none_for_absent_dict_key(self):
        rc = make_run_config(seed=5)
        assert rc.steps is None

    def test_get_with_object_missing_attribute_returns_none(self):
        class Namespace:
            seed = 7
            model_tags = None
        rc = RunConfig(args=Namespace())
        assert rc.steps is None  # not on Namespace


# ---------------------------------------------------------------------------
# Model switch detection — class-level flag
# ---------------------------------------------------------------------------

class TestModelSwitchDetected:
    def test_same_model_tags_no_switch(self):
        RunConfig.previous_model_tags = "model_a"
        make_run_config(model_tags="model_a")
        assert RunConfig.model_switch_detected is False

    def test_different_model_tags_sets_switch(self):
        RunConfig.previous_model_tags = "model_a"
        make_run_config(model_tags="model_b")
        assert RunConfig.model_switch_detected is True

    def test_none_previous_to_value_sets_switch(self):
        RunConfig.previous_model_tags = None
        make_run_config(model_tags="model_a")
        assert RunConfig.model_switch_detected is True

    def test_previous_model_tags_updated_after_init(self):
        make_run_config(model_tags="my_model")
        assert RunConfig.previous_model_tags == "my_model"


# ---------------------------------------------------------------------------
# _get_workflow_type()
# ---------------------------------------------------------------------------

class TestGetWorkflowType:
    def test_valid_workflow_tag_returns_enum(self):
        rc = make_run_config(workflow_tag="IP_ADAPTER")
        assert rc._get_workflow_type() == WorkflowType.IP_ADAPTER

    def test_case_insensitive_match(self):
        rc = make_run_config(workflow_tag="controlnet")
        assert rc._get_workflow_type() == WorkflowType.CONTROLNET

    def test_invalid_workflow_tag_returns_none(self):
        rc = make_run_config(workflow_tag="DOES_NOT_EXIST_XYZ")
        assert rc._get_workflow_type() is None

    def test_none_workflow_tag_returns_none(self):
        rc = make_run_config(workflow_tag=None)
        assert rc._get_workflow_type() is None


# ---------------------------------------------------------------------------
# _is_ip_adapter_missing() / _is_control_net_missing()
# ---------------------------------------------------------------------------

class TestIpAdapterMissing:
    def test_none_is_missing(self):
        rc = make_run_config()
        assert rc._is_ip_adapter_missing() is True

    def test_empty_string_is_missing(self):
        rc = make_run_config(ip_adapters="")
        assert rc._is_ip_adapter_missing() is True

    def test_whitespace_only_is_missing(self):
        rc = make_run_config(ip_adapters="   ")
        assert rc._is_ip_adapter_missing() is True

    def test_valid_path_not_missing(self):
        rc = make_run_config(ip_adapters="some/image.png")
        assert rc._is_ip_adapter_missing() is False


class TestControlNetMissing:
    def test_none_is_missing(self):
        rc = make_run_config()
        assert rc._is_control_net_missing() is True

    def test_empty_string_is_missing(self):
        rc = make_run_config(control_nets="")
        assert rc._is_control_net_missing() is True

    def test_valid_path_not_missing(self):
        rc = make_run_config(control_nets="depth_map.png")
        assert rc._is_control_net_missing() is False


# ---------------------------------------------------------------------------
# _validate_workflow_requirements()
# ---------------------------------------------------------------------------

class TestValidateWorkflowRequirements:
    def test_ip_adapter_workflow_missing_adapter_raises(self):
        rc = make_run_config(workflow_tag="IP_ADAPTER", ip_adapters="")
        with pytest.raises(Exception, match="requires an IP adapter"):
            rc._validate_workflow_requirements()

    def test_ip_adapter_workflow_with_adapter_passes(self):
        rc = make_run_config(workflow_tag="IP_ADAPTER", ip_adapters="image.png")
        rc._validate_workflow_requirements()  # must not raise

    def test_img2img_workflow_missing_adapter_raises(self):
        rc = make_run_config(workflow_tag="IMG2IMG", ip_adapters=None)
        with pytest.raises(Exception, match="requires an IP adapter"):
            rc._validate_workflow_requirements()

    def test_image_edit_workflow_missing_adapter_raises(self):
        rc = make_run_config(workflow_tag="IMAGE_EDIT", ip_adapters="")
        with pytest.raises(Exception, match="requires an IP adapter"):
            rc._validate_workflow_requirements()

    def test_controlnet_workflow_missing_control_net_raises(self):
        rc = make_run_config(workflow_tag="CONTROLNET", control_nets="")
        with pytest.raises(Exception, match="requires a control net"):
            rc._validate_workflow_requirements()

    def test_controlnet_workflow_with_control_net_passes(self):
        rc = make_run_config(workflow_tag="CONTROLNET", control_nets="depth.png")
        rc._validate_workflow_requirements()

    def test_instant_lora_missing_ip_adapter_raises_first(self):
        # IP adapter check runs before control net check
        rc = make_run_config(workflow_tag="INSTANT_LORA", ip_adapters="", control_nets="")
        with pytest.raises(Exception, match="requires an IP adapter"):
            rc._validate_workflow_requirements()

    def test_instant_lora_missing_control_net_raises(self):
        rc = make_run_config(workflow_tag="INSTANT_LORA", ip_adapters="image.png", control_nets="")
        with pytest.raises(Exception, match="requires a control net"):
            rc._validate_workflow_requirements()

    def test_renoiser_with_multiple_resolutions_raises(self):
        rc = make_run_config(workflow_tag="RENOISER", control_nets="depth.png",
                             res_tags="landscape,portrait")
        with pytest.raises(Exception, match="Multiple resolutions"):
            rc._validate_workflow_requirements()

    def test_renoiser_with_single_resolution_passes(self):
        rc = make_run_config(workflow_tag="RENOISER", control_nets="depth.png",
                             res_tags="landscape")
        rc._validate_workflow_requirements()

    def test_simple_image_gen_no_requirements(self):
        rc = make_run_config(workflow_tag="SIMPLE_IMAGE_GEN")
        rc._validate_workflow_requirements()

    def test_no_workflow_tag_is_always_valid(self):
        rc = make_run_config()
        rc._validate_workflow_requirements()
