from __future__ import annotations

import os
import re
import threading

from extensions.hf_hub_api import ensure_hf_snapshot
from lib.logging_setup import get_logger
from lib.translations import I18N

_ = I18N._
logger = get_logger("image_to_prompt.llava")

#: Lead-ins a LLaVA-family model habitually opens with. They are prose framing,
#: not image content, so they are noise in a generation prompt. Anchored at the
#: start and matched case-insensitively; only one is stripped, because a second
#: match is more likely to be real description than another lead-in.
_LEAD_IN_PATTERN = re.compile(
    r"^\s*(?:"
    r"(?:in\s+)?(?:the|this)\s+(?:image|picture|photo|photograph|artwork|illustration|scene)"
    r"(?:\s+\w+){0,3}?\s*(?:,|:|\s)\s*(?:we\s+see|you\s+can\s+see|there\s+is|there\s+are|"
    r"shows|depicts|features|displays|captures|portrays|is\s+of)"
    r"|sure[,!]?\s+(?:here(?:'s| is)[^.:]*[.:])?"
    r")\s*",
    re.IGNORECASE,
)


def strip_lead_in(text: str) -> str:
    """Drop a natural-language opener from a model's description.

    "The image shows a red car" is not a usable generation prompt; "a red car"
    is. Returns the text unchanged when nothing matches, and never returns an
    empty string in place of a non-empty one -- a description that is *only* a
    lead-in is better shown to the user than silently blanked.
    """
    if not text:
        return ""
    stripped = _LEAD_IN_PATTERN.sub("", text, count=1).strip()
    if not stripped:
        return text.strip()
    return stripped[0].lower() + stripped[1:] if stripped[:1].isupper() else stripped


class LlavaTransformersImpl:
    """``vlm_impl`` driving a LLaVA-family model through Transformers.

    Satisfies the interface ``VLMProvider`` asks for --
    ``describe_image(image_path, prompt_hint="") -> str`` -- with no external
    runtime: the model is downloaded from the Hub and runs in this process,
    like the BLIP captioner rather than like a server-backed backend.

    The load follows the captioner's pattern for the same reasons: a
    class-level model/processor cache behind a lock, so opening the window
    repeatedly or switching backends and back does not reload several
    gigabytes, and so two threads racing the first load cannot both build one.

    Weight of the default model is the thing to know before enabling this:
    roughly 14 GB on disk and 7 GB of VRAM at fp16, resident for the life of
    the process and competing with the image-generation backend for the same
    card. ``load_in_4bit`` trades quality for about a third of that, and needs
    bitsandbytes installed.
    """

    #: The original LLaVA-1.5 weights in the Transformers layout, published by
    #: the LLaVA authors' own org. Same architecture and outputs as the
    #: research repo, without vendoring model code pinned to an old
    #: Transformers.
    DEFAULT_REPO_ID = "llava-hf/llava-1.5-7b-hf"

    DEFAULT_MAX_NEW_TOKENS = 256

    #: Asks for the comma-separated phrasing a generation prompt wants, rather
    #: than the prose a chat-tuned model defaults to. Used whenever the caller
    #: supplies no hint of their own.
    DEFAULT_INSTRUCTION = (
        "Describe this image as a Stable Diffusion generation prompt. "
        "Give comma-separated descriptive phrases covering subject, setting, "
        "composition, lighting, colour palette, artistic style and mood. "
        "Be specific and concrete. Do not write full sentences and do not "
        "explain what you are doing."
    )

    _load_lock = threading.Lock()
    _shared_processor = None
    _shared_model = None
    _shared_device = "cpu"
    _shared_key = None

    def __init__(
        self,
        repo_id: str | None = None,
        max_new_tokens: int | None = None,
        load_in_4bit: bool = False,
    ):
        self._repo_id = repo_id or self.DEFAULT_REPO_ID
        self._max_new_tokens = max_new_tokens or self.DEFAULT_MAX_NEW_TOKENS
        self._load_in_4bit = bool(load_in_4bit)
        self._processor = None
        self._model = None
        self._device = "cpu"

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def _cache_key(self) -> tuple:
        # Quantisation is part of the identity: the same repo loaded 4-bit and
        # fp16 are different models in memory, and one must not be served for
        # a request that asked for the other.
        return (self._repo_id, self._load_in_4bit)

    def _ensure_model(self) -> None:
        if self._processor is not None and self._model is not None:
            return
        with self.__class__._load_lock:
            if (
                self.__class__._shared_processor is not None
                and self.__class__._shared_model is not None
                and self.__class__._shared_key == self._cache_key()
            ):
                self._processor = self.__class__._shared_processor
                self._model = self.__class__._shared_model
                self._device = self.__class__._shared_device
                return

            try:
                import torch
                from transformers import (
                    AutoProcessor,
                    LlavaForConditionalGeneration,
                    logging as transformers_logging,
                )
            except Exception as e:
                # Surfaced to the user in the window's error dialog, so it is
                # translated even though it names packages.
                raise RuntimeError(_(
                    "VLM backend requires torch + transformers. Install optional deps "
                    "(e.g. `pip install -r requirements-optional.txt`). The VLM model "
                    "class needs transformers 4.36 or newer."
                )) from e

            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

            # Weights are sharded safetensors for a model this size, so the
            # index has to come down with them or from_pretrained cannot tell
            # which shard holds what.
            ensure_hf_snapshot(
                self._repo_id,
                allow_patterns=[
                    "config.json",
                    "generation_config.json",
                    "preprocessor_config.json",
                    "processor_config.json",
                    "chat_template.json",
                    "tokenizer_config.json",
                    "special_tokens_map.json",
                    "tokenizer.json",
                    "tokenizer.model",
                    "*.safetensors",
                    "*.safetensors.index.json",
                ],
            )

            device = "cuda" if torch.cuda.is_available() else "cpu"
            load_kwargs = self._load_kwargs(torch, device)

            prev_verbosity = transformers_logging.get_verbosity()
            try:
                transformers_logging.set_verbosity_error()
                processor = AutoProcessor.from_pretrained(self._repo_id)
                model = LlavaForConditionalGeneration.from_pretrained(
                    self._repo_id, **load_kwargs
                )
            finally:
                transformers_logging.set_verbosity(prev_verbosity)

            # A 4-bit load already placed the weights, and moving a quantised
            # model afterwards is an error rather than a no-op.
            if not self._load_in_4bit:
                model.to(device)
            model.eval()

            self.__class__._shared_processor = processor
            self.__class__._shared_model = model
            self.__class__._shared_device = device
            self.__class__._shared_key = self._cache_key()
            self._processor = processor
            self._model = model
            self._device = device
            logger.info(f"Loaded VLM {self._repo_id} on {device}")

    def _load_kwargs(self, torch, device: str) -> dict:
        """Build from_pretrained kwargs, degrading rather than failing.

        ``low_cpu_mem_usage`` needs accelerate, which is not a declared
        dependency; without it a 14 GB load briefly holds the weights twice in
        RAM, which is worth avoiding but not worth refusing over. 4-bit needs
        bitsandbytes and *is* worth refusing over, because silently loading
        fp16 instead would use four times the VRAM the user asked for.
        """
        kwargs: dict = {}
        if device == "cuda":
            kwargs["torch_dtype"] = torch.float16

        try:
            import accelerate  # noqa: F401
            has_accelerate = True
        except Exception:
            has_accelerate = False

        if has_accelerate:
            kwargs["low_cpu_mem_usage"] = True
        else:
            logger.info("accelerate not installed; loading VLM without low_cpu_mem_usage")

        if self._load_in_4bit:
            try:
                if not has_accelerate:
                    raise ImportError("accelerate")
                import bitsandbytes  # noqa: F401
                from transformers import BitsAndBytesConfig
            except Exception as e:
                raise RuntimeError(_(
                    "vlm_load_in_4bit is set but bitsandbytes and accelerate are not "
                    "both installed. Install them, or turn the setting off to load at "
                    "full precision."
                )) from e
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
            )
            kwargs["device_map"] = "auto"
        return kwargs

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def _build_prompt(self, instruction: str) -> str:
        """Wrap the instruction in the conversation format the model expects.

        Prefers the processor's own chat template, which is what keeps this
        correct across model families -- llava-1.5, llava-next and Qwen-VL all
        use different turn markers, and a hand-written one silently produces
        worse output rather than an error. Falls back to the llava-1.5 format
        for a processor that ships no template.
        """
        messages = [{
            "role": "user",
            "content": [{"type": "image"}, {"type": "text", "text": instruction}],
        }]
        try:
            return self._processor.apply_chat_template(
                messages, add_generation_prompt=True
            )
        except Exception:
            return f"USER: <image>\n{instruction} ASSISTANT:"

    def _instruction_for(self, prompt_hint: str = "") -> str:
        """Combine the user's hint with the standing instruction.

        A hint narrows what to look at; it does not say what shape the answer
        should take. Replacing the instruction with it would drop the request
        for comma-separated phrases and the model would return prose again, so
        the hint is appended rather than substituted.
        """
        hint = (prompt_hint or "").strip()
        return f"{self.DEFAULT_INSTRUCTION} {hint}" if hint else self.DEFAULT_INSTRUCTION

    def describe_image(self, image_path: str, prompt_hint: str = "") -> str:
        """Return a generation-prompt description of the image at *image_path*."""
        import torch
        from PIL import Image
        from lib.pillow_plugins import ensure_pillow_plugins_registered

        self._ensure_model()

        ensure_pillow_plugins_registered()
        image = Image.open(image_path).convert("RGB")

        prompt = self._build_prompt(self._instruction_for(prompt_hint))
        inputs = self._processor(images=image, text=prompt, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                do_sample=False,
            )

        # The prompt is echoed back as part of the sequence, so decode only the
        # tokens generated past it rather than string-matching it back out.
        prompt_length = inputs["input_ids"].shape[1]
        text = self._processor.decode(
            output[0][prompt_length:], skip_special_tokens=True
        )
        return strip_lead_in(text.strip())

    @classmethod
    def unload_shared(cls) -> None:
        """Drop the cached model so its VRAM returns to the generation backend.

        Not called on a timer: a reload costs a multi-second read of several
        gigabytes, so when to give the memory back is the user's call, exposed
        through the window rather than guessed at here.
        """
        with cls._load_lock:
            cls._shared_processor = None
            cls._shared_model = None
            cls._shared_key = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
