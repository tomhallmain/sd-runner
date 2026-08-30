"""The VLM image-to-prompt backend.

Covers everything that does not need the model itself: lead-in stripping, the
prompt the model is asked, the load-time argument choices, and the provider and
registry wiring. The load and the generate call are driven through fakes, so
none of this downloads or runs a 14 GB checkpoint.
"""

import pytest

from sd_runner.image_to_prompt import ImageToPromptBackend, ImageToPromptService
from sd_runner.image_to_prompt.providers.llava_transformers import (
    LlavaTransformersImpl,
    strip_lead_in,
)
from sd_runner.image_to_prompt.providers.vlm_provider import VLMProvider
from sd_runner.image_to_prompt.registry import ImageToPromptProviderRegistry
from sd_runner.image_to_prompt.types import ImageToPromptRequest


class FakeVlmImpl:
    """Records what it was asked, returns a fixed description."""

    def __init__(self, text="a red car, golden hour, shallow depth of field"):
        self.text = text
        self.calls = []

    def describe_image(self, image_path, prompt_hint=""):
        self.calls.append((image_path, prompt_hint))
        return self.text


# ---------------------------------------------------------------------------
# Lead-in stripping
# ---------------------------------------------------------------------------

class TestStripLeadIn:
    """Chat-tuned models open with framing prose; a prompt cannot use it."""

    @pytest.mark.parametrize("text", [
        "The image shows a red car on a wet street",
        "This image depicts a red car on a wet street",
        "The picture features a red car on a wet street",
        "In this photo, we see a red car on a wet street",
        "This photograph captures a red car on a wet street",
        "Sure! Here's a description: a red car on a wet street",
    ])
    def test_the_opener_goes_and_the_description_stays(self, text):
        assert strip_lead_in(text) == "a red car on a wet street"

    def test_a_description_with_no_opener_is_untouched(self):
        text = "a red car, wet asphalt, neon reflections, cinematic lighting"
        assert strip_lead_in(text) == text

    def test_only_the_first_opener_is_stripped(self):
        """A second match is more likely description than another lead-in."""
        assert strip_lead_in(
            "The image shows the image of a painting"
        ) == "the image of a painting"

    def test_text_that_is_only_an_opener_is_kept(self):
        """Better shown to the user than silently blanked."""
        assert strip_lead_in("The image shows") == "The image shows"

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_input_is_empty_output(self, value):
        assert strip_lead_in(value) == ""

    def test_a_leading_capital_is_lowered_after_a_strip(self):
        """The remainder is now a fragment, not a sentence."""
        assert strip_lead_in("The image shows A red car").startswith("a red car")


# ---------------------------------------------------------------------------
# The instruction the model is given
# ---------------------------------------------------------------------------

class _RecordingProcessor:
    def __init__(self):
        self.text_seen = None

    def apply_chat_template(self, messages, add_generation_prompt=False):
        self.text_seen = messages[0]["content"][1]["text"]
        return "TEMPLATED"


class TestInstructionAssembly:
    def build(self):
        impl = LlavaTransformersImpl()
        impl._processor = _RecordingProcessor()
        return impl

    def test_the_default_instruction_asks_for_prompt_shaped_output(self):
        """Not prose: a chat model returns sentences unless told otherwise."""
        instruction = LlavaTransformersImpl.DEFAULT_INSTRUCTION
        assert "comma-separated" in instruction
        assert "Do not write full sentences" in instruction

    def test_a_hint_is_added_to_the_instruction_not_swapped_for_it(self):
        """A hint narrows the subject; it does not say what shape to answer in."""
        impl = LlavaTransformersImpl()
        instruction = impl._instruction_for("focus on the clothing")
        assert instruction.startswith(impl.DEFAULT_INSTRUCTION)
        assert instruction.endswith("focus on the clothing")

    @pytest.mark.parametrize("hint", ["", "   ", None])
    def test_no_hint_leaves_the_instruction_alone(self, hint):
        impl = LlavaTransformersImpl()
        assert impl._instruction_for(hint) == impl.DEFAULT_INSTRUCTION

    def test_the_processors_chat_template_is_preferred(self):
        """Turn markers differ per model family; a hand-written one is silently worse."""
        impl = self.build()
        assert impl._build_prompt("describe it") == "TEMPLATED"

    def test_a_processor_with_no_template_falls_back_to_the_llava_format(self):
        class NoTemplate:
            def apply_chat_template(self, *a, **k):
                raise ValueError("no chat template")

        impl = LlavaTransformersImpl()
        impl._processor = NoTemplate()
        prompt = impl._build_prompt("describe it")
        assert "<image>" in prompt
        assert prompt.endswith("ASSISTANT:")


# ---------------------------------------------------------------------------
# Load-time choices
# ---------------------------------------------------------------------------

class _FakeTorch:
    float16 = "float16"

    class cuda:
        @staticmethod
        def is_available():
            return True


class TestLoadKwargs:
    def test_cuda_loads_at_half_precision(self):
        kwargs = LlavaTransformersImpl()._load_kwargs(_FakeTorch, "cuda")
        assert kwargs["torch_dtype"] == "float16"

    def test_cpu_does_not_force_a_dtype(self):
        """Half precision on CPU is slower than float32, not faster."""
        kwargs = LlavaTransformersImpl()._load_kwargs(_FakeTorch, "cpu")
        assert "torch_dtype" not in kwargs

    @pytest.mark.parametrize("missing", ["bitsandbytes", "accelerate"])
    def test_four_bit_without_its_deps_refuses_rather_than_degrading(
        self, monkeypatch, missing
    ):
        """Silently loading fp16 would use four times the asked-for VRAM."""
        import builtins
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == missing:
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)
        impl = LlavaTransformersImpl(load_in_4bit=True)
        with pytest.raises(RuntimeError) as excinfo:
            impl._load_kwargs(_FakeTorch, "cuda")
        # The message is translated, so the missing dependency is asserted
        # through the chained cause rather than by matching display text.
        assert isinstance(excinfo.value.__cause__, ImportError)

    def test_a_full_precision_load_does_not_need_those_deps(self, monkeypatch):
        """accelerate only improves the load; its absence must not block one."""
        import builtins
        real_import = builtins.__import__

        def no_accelerate(name, *args, **kwargs):
            if name == "accelerate":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_accelerate)
        kwargs = LlavaTransformersImpl()._load_kwargs(_FakeTorch, "cuda")
        assert "low_cpu_mem_usage" not in kwargs

    def test_quantisation_is_part_of_the_cache_key(self):
        """The same repo at 4-bit and fp16 are different models in memory."""
        plain = LlavaTransformersImpl(repo_id="some/repo")
        quantised = LlavaTransformersImpl(repo_id="some/repo", load_in_4bit=True)
        assert plain._cache_key() != quantised._cache_key()

    def test_the_repo_id_is_part_of_the_cache_key(self):
        assert (
            LlavaTransformersImpl(repo_id="a/one")._cache_key()
            != LlavaTransformersImpl(repo_id="b/two")._cache_key()
        )

    def test_the_default_repo_is_the_transformers_layout_of_llava(self):
        assert LlavaTransformersImpl().DEFAULT_REPO_ID.startswith("llava-hf/")


# ---------------------------------------------------------------------------
# Provider wiring
# ---------------------------------------------------------------------------

class TestVLMProvider:
    def request(self):
        return ImageToPromptRequest(image_path="/tmp/an_image.png")

    def test_an_injected_impl_is_used_as_is(self):
        impl = FakeVlmImpl()
        result = VLMProvider(vlm_impl=impl).generate(self.request())
        assert result.positive_prompt == impl.text
        assert result.backend is ImageToPromptBackend.VLM

    def test_the_prompt_hint_reaches_the_impl(self):
        impl = FakeVlmImpl()
        VLMProvider(vlm_impl=impl).generate(
            ImageToPromptRequest(image_path="/tmp/a.png", prompt_hint="the clothing")
        )
        assert impl.calls == [("/tmp/a.png", "the clothing")]

    def test_no_impl_is_built_until_a_request_arrives(self):
        """Constructing a provider must stay cheap -- importing torch is not."""
        provider = VLMProvider()
        assert provider._vlm_impl is None

    def test_the_default_impl_is_the_transformers_one(self):
        provider = VLMProvider(repo_id="some/repo")
        assert isinstance(provider._ensure_impl(), LlavaTransformersImpl)

    def test_the_configured_repo_reaches_the_impl(self):
        provider = VLMProvider(repo_id="some/repo")
        assert provider._ensure_impl()._repo_id == "some/repo"

    def test_the_impl_is_built_once_and_reused(self):
        provider = VLMProvider()
        assert provider._ensure_impl() is provider._ensure_impl()

    def test_the_result_names_the_model_it_came_from(self):
        result = VLMProvider(vlm_impl=FakeVlmImpl()).generate(self.request())
        assert result.metadata["provider"] == "VLM"

    def test_whitespace_around_the_description_is_dropped(self):
        result = VLMProvider(vlm_impl=FakeVlmImpl(text="  a red car  ")).generate(
            self.request()
        )
        assert result.positive_prompt == "a red car"

    def test_the_negative_prompt_is_empty(self):
        """The backend produces one description; there is no second call yet."""
        result = VLMProvider(vlm_impl=FakeVlmImpl()).generate(self.request())
        assert result.negative_prompt == ""


class TestRegistryWiring:
    def test_the_vlm_backend_builds_a_vlm_provider(self):
        provider = ImageToPromptProviderRegistry.create(ImageToPromptBackend.VLM)
        assert isinstance(provider, VLMProvider)

    def test_the_repo_id_is_routed_through(self):
        provider = ImageToPromptProviderRegistry.create(
            ImageToPromptBackend.VLM, vlm_repo_id="some/repo"
        )
        assert provider._repo_id == "some/repo"

    def test_the_quantisation_flag_is_routed_through(self):
        provider = ImageToPromptProviderRegistry.create(
            ImageToPromptBackend.VLM, vlm_load_in_4bit=True
        )
        assert provider._load_in_4bit is True

    def test_an_injected_impl_still_wins(self):
        impl = FakeVlmImpl()
        provider = ImageToPromptProviderRegistry.create(
            ImageToPromptBackend.VLM, vlm_impl=impl
        )
        assert provider._ensure_impl() is impl

    def test_the_service_carries_the_options_through(self):
        impl = FakeVlmImpl()
        service = ImageToPromptService.from_backend(
            ImageToPromptBackend.VLM, vlm_impl=impl
        )
        result = service.generate(image_path="/tmp/a.png")
        assert result.positive_prompt == impl.text
