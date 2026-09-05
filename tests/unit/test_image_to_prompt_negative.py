"""What ``include_negative`` actually decides.

No backend produces a negative, so the flag is settled in the service rather
than by any provider: unticked means none is passed on at all, ticked means one
is resolved from the image's own generation metadata, falling back to the
configured default. The window displays whatever comes back, so this is the
whole of the behaviour -- there is no separate UI path.
"""

import pytest

from sd_runner.globals import Globals
from sd_runner.image_to_prompt.negative import resolve_negative
from sd_runner.image_to_prompt.service import ImageToPromptService
from sd_runner.image_to_prompt.types import (
    ImageToPromptBackend,
    ImageToPromptRequest,
    ImageToPromptResult,
)


IMAGE = "some/image.png"


class StubProvider:
    """A provider that returns whatever the test wants it to."""

    def __init__(self, negative=""):
        self.negative = negative
        self.requests = []

    @property
    def name(self):
        return "stub"

    def generate(self, request: ImageToPromptRequest) -> ImageToPromptResult:
        self.requests.append(request)
        return ImageToPromptResult(
            backend=ImageToPromptBackend.FAST_TAGGER,
            positive_prompt="a cat",
            negative_prompt=self.negative,
        )


class StubExtractor:
    """Stands in for ImageDataExtractor's two metadata readers."""

    def __init__(self, comfy="", a1111=None, raises=False):
        self.comfy = comfy
        self.a1111 = a1111
        self.raises = raises

    def extract(self, image_path):
        if self.raises:
            raise OSError("cannot identify image file")
        return ("a cat", self.comfy)

    def extract_a1111_parameters(self, image_path):
        if self.raises:
            raise OSError("cannot identify image file")
        return self.a1111


@pytest.fixture
def extractor(monkeypatch):
    """Install a stub extractor and return a setter for what it finds."""
    def install(**kwargs):
        stub = StubExtractor(**kwargs)
        monkeypatch.setattr(
            Globals, "get_image_data_extractor", classmethod(lambda cls: stub)
        )
        return stub
    install()
    return install


@pytest.fixture
def default_negative(monkeypatch):
    """Set the configured base negative, with the override off."""
    def install(text, override=False):
        monkeypatch.setattr(Globals, "DEFAULT_NEGATIVE_PROMPT", text)
        monkeypatch.setattr(Globals, "OVERRIDE_BASE_NEGATIVE", override)
    install("")
    return install


def generate(provider, include_negative):
    return ImageToPromptService(provider).generate(
        image_path=IMAGE, include_negative=include_negative,
    )


# ---------------------------------------------------------------------------
# The flag itself
# ---------------------------------------------------------------------------

class TestUnticked:
    def test_no_negative_is_passed_on(self, extractor, default_negative):
        default_negative("blurry, watermark")
        assert generate(StubProvider(), include_negative=False).negative_prompt == ""

    def test_a_provider_that_produced_one_is_overruled(self, extractor, default_negative):
        """The flag is the user's answer, so a backend that starts returning a
        negative cannot reinstate it."""
        assert generate(StubProvider("ugly"), include_negative=False).negative_prompt == ""

    def test_the_positive_is_untouched(self, extractor, default_negative):
        assert generate(StubProvider(), include_negative=False).positive_prompt == "a cat"


class TestTicked:
    def test_a_providers_own_negative_is_kept(self, extractor, default_negative):
        default_negative("blurry, watermark")
        result = generate(StubProvider("six fingers"), include_negative=True)
        assert result.negative_prompt == "six fingers"

    def test_otherwise_one_is_resolved(self, extractor, default_negative):
        default_negative("blurry, watermark")
        assert generate(StubProvider(), include_negative=True).negative_prompt == (
            "blurry, watermark"
        )

    def test_the_flag_still_reaches_the_provider(self, extractor, default_negative):
        """It is settled afterwards, not instead: a provider that can produce a
        negative needs to know it was asked."""
        provider = StubProvider()
        generate(provider, include_negative=True)
        assert provider.requests[0].include_negative is True


# ---------------------------------------------------------------------------
# Where a resolved negative comes from
# ---------------------------------------------------------------------------

class TestEmbeddedMetadata:
    def test_a_comfy_negative_is_read_from_the_image(self, extractor, default_negative):
        extractor(comfy="watermark, text")
        assert resolve_negative(IMAGE) == "watermark, text"

    def test_an_a1111_negative_is_read_from_the_image(self, extractor, default_negative):
        extractor(a1111="a cat\nNegative prompt: lowres, jpeg artifacts\nSteps: 20")
        assert resolve_negative(IMAGE) == "lowres, jpeg artifacts"

    def test_the_comfy_reader_is_tried_first(self, extractor, default_negative):
        """Both can be present on an image that has been through two tools."""
        extractor(comfy="from comfy",
                  a1111="a cat\nNegative prompt: from a1111\nSteps: 20")
        assert resolve_negative(IMAGE) == "from comfy"

    def test_it_beats_the_configured_default(self, extractor, default_negative):
        """Specific to this image, so it wins over a setting that applies to
        every run."""
        default_negative("blurry, watermark")
        extractor(comfy="watermark, text")
        assert resolve_negative(IMAGE) == "watermark, text"

    def test_whitespace_only_metadata_is_not_a_negative(self, extractor, default_negative):
        default_negative("blurry, watermark")
        extractor(comfy="   ")
        assert resolve_negative(IMAGE) == "blurry, watermark"

    def test_a_reader_that_raises_does_not_fail_the_generate(self, extractor, default_negative):
        """A photograph has no metadata and an unreadable block is not an error
        -- the generate itself succeeded."""
        default_negative("blurry, watermark")
        extractor(raises=True)
        assert resolve_negative(IMAGE) == "blurry, watermark"


class TestTheConfiguredDefault:
    def test_it_is_used_when_the_image_carries_nothing(self, extractor, default_negative):
        default_negative("blurry, watermark")
        assert resolve_negative(IMAGE) == "blurry, watermark"

    def test_overriding_the_base_negative_means_none(self, extractor, default_negative):
        """The same switch a run honours, so the answer here matches what a run
        would actually send."""
        default_negative("blurry, watermark", override=True)
        assert resolve_negative(IMAGE) == ""

    def test_an_embedded_negative_survives_the_override(self, extractor, default_negative):
        """The override is about the base negative, not about the image."""
        default_negative("blurry, watermark", override=True)
        extractor(comfy="watermark, text")
        assert resolve_negative(IMAGE) == "watermark, text"

    def test_nothing_configured_and_nothing_embedded_is_empty(self, extractor, default_negative):
        assert resolve_negative(IMAGE) == ""

    def test_no_image_path_falls_back_to_the_default(self, extractor, default_negative):
        default_negative("blurry, watermark")
        assert resolve_negative("") == "blurry, watermark"
