"""xAI Grok image generation backend (Aurora model, OpenAI-compatible API)."""

from sd_runner.gen_config import GenConfig
from sd_runner.generators.openai_gen import OpenAIGen

_BASE_URL = "https://api.x.ai/v1/images/generations"
_DEFAULT_MODEL = "grok-2-image-1212"

# xAI's image API does not currently support size selection; the model
# produces images at its own native resolution regardless of the size field.
_GROK_SIZES = ["1024x1024"]


class GrokGen(OpenAIGen):
    """Generator for xAI's Grok image generation (Aurora model).

    Grok's image API is OpenAI-compatible, so this subclass simply overrides
    the endpoint URL, the default model name, and the API-key lookup.

    Set ``model_tags`` to the model name (e.g. ``"grok-2-image-1212"``).
    Negative prompts are accepted in the request body but may be ignored
    by the model.
    """

    BACKEND_NAME = "grok"
    BASE_URL = _BASE_URL

    def __init__(self, config: GenConfig = None, ui_callbacks=None):
        super().__init__(config, ui_callbacks)
