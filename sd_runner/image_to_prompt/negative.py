"""Where a negative prompt comes from when one is asked for.

No backend produces a negative -- a tagger and a captioner describe what is in
an image, and asking a VLM what to avoid is a second call. So the negative is
resolved here instead, from two sources that need no model:

1. The image's own generation metadata. An image reaching this window is often
   one a diffusion backend wrote, and those carry the prompt that made them --
   a ComfyUI workflow dict or an SDWebUI ``parameters`` summary. That negative
   is specific to this image, so it wins.
2. The configured default, resolved the way ``Run.load_and_run`` resolves it so
   the answer here is the negative a run would actually use.

Both readers are best-effort: a photograph carries neither, which is not an
error, and a metadata block that cannot be parsed must not fail a generate that
otherwise succeeded.
"""

from __future__ import annotations

from lib.logging_setup import get_logger

logger = get_logger("image_to_prompt.negative")


def resolve_negative(image_path: str) -> str:
    """The negative to hand on for *image_path*, or ``""`` when there is none."""
    return _embedded_negative(image_path) or _configured_default()


def _embedded_negative(image_path: str) -> str:
    """The negative recorded in the image, from whichever backend wrote it."""
    if not image_path:
        return ""
    for read in (_comfy_negative, _a1111_negative):
        try:
            negative = read(image_path)
        except Exception as e:
            logger.debug(f"Could not read negative from {image_path}: {e}")
            continue
        if negative and negative.strip():
            return negative.strip()
    return ""


def _comfy_negative(image_path: str) -> str:
    from sd_runner.globals import Globals

    _positive, negative = Globals.get_image_data_extractor().extract(image_path)
    return negative or ""


def _a1111_negative(image_path: str) -> str:
    from sd_runner.globals import Globals
    from sd_runner.metadata.a1111 import parse_a1111_parameters

    raw = Globals.get_image_data_extractor().extract_a1111_parameters(image_path)
    if not raw:
        return ""
    return parse_a1111_parameters(raw).negative or ""


def _configured_default() -> str:
    """The base negative a run would start from.

    ``OVERRIDE_BASE_NEGATIVE`` means the user has said not to apply it, so
    honouring it here is what keeps this in step with a real run.
    """
    from sd_runner.globals import Globals

    if Globals.OVERRIDE_BASE_NEGATIVE:
        return ""
    return str(Globals.DEFAULT_NEGATIVE_PROMPT or "")
