"""
Model.validate_model_blacklist raises BlacklistException for a blacklisted
checkpoint or LoRA, naming the offenders unless silent removal is on.
"""

from types import SimpleNamespace

import pytest

from sd_runner.models.model import Model
from sd_runner.prompts.blacklist import Blacklist, BlacklistException


@pytest.fixture(autouse=True)
def models_on_disk(monkeypatch):
    """Two models, one of them blacklisted; no files needed."""
    models = [SimpleNamespace(id="blocked_model.safetensors"), SimpleNamespace(id="fine_model.safetensors")]
    monkeypatch.setattr(Model, "get_models", staticmethod(lambda *args, **kwargs: models))
    Blacklist.add_to_model_blacklist("blocked_model")


@pytest.mark.parametrize("is_lora", [False, True], ids=["checkpoint", "lora"])
class TestValidateModelBlacklist:
    def test_a_blacklisted_model_raises(self, is_lora):
        with pytest.raises(BlacklistException):
            Model.validate_model_blacklist("any", is_lora=is_lora)

    def test_the_message_names_the_blacklisted_model(self, is_lora):
        with pytest.raises(BlacklistException) as excinfo:
            Model.validate_model_blacklist("any", is_lora=is_lora)
        assert "blocked_model.safetensors" in str(excinfo.value)

    def test_silent_removal_does_not_name_it(self, is_lora):
        Blacklist.set_blacklist_silent_removal(True)
        with pytest.raises(BlacklistException) as excinfo:
            Model.validate_model_blacklist("any", is_lora=is_lora)
        assert "blocked_model" not in str(excinfo.value)

    def test_the_exception_separates_allowed_from_blocked(self, is_lora):
        with pytest.raises(BlacklistException) as excinfo:
            Model.validate_model_blacklist("any", is_lora=is_lora)
        assert excinfo.value.whitelist == ["fine_model.safetensors"]
        assert excinfo.value.filtered == ["blocked_model.safetensors"]
