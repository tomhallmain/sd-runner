"""Parser for the A1111 ``parameters`` PNG metadata string.

Named for the format rather than a backend because SDWebUI, Forge and SDNext all
emit it -- the latter two subclass ``SDWebuiGen``.

ComfyUI embeds its complete API payload in the PNG, so redoing a generation is
"load the old JSON, change a field, resubmit". A1111 embeds a human-readable
summary instead, so the same feature needs the summary parsed back into values.
This module does that half and nothing else: it is pure text in, dataclass out,
with no file or network access, so it can be tested against real metadata
strings without a backend.

The format is a positive prompt, an optional ``Negative prompt:`` section, and a
trailing comma-separated settings line::

    beautiful woman, red dress
    Negative prompt: ugly, blurry
    Steps: 25, Sampler: DPM++ 2M Karras, CFG scale: 7.0, Seed: 384, Size: 768x512,
    Model hash: 4bdfc29c, Model: realisticVision, Clip skip: 2

Two things make the settings line harder than ``split(",")``: values may contain
commas inside quotes or parentheses (ControlNet blocks do), and older SDWebUI
builds fold the scheduler into the sampler name (``DPM++ 2M Karras``) where
newer ones emit a separate ``Schedule type`` field.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from sd_runner.globals import Sampler, Scheduler
from lib.logging_setup import get_logger

logger = get_logger("a1111_metadata")

NEGATIVE_PROMPT_MARKER = "Negative prompt:"

#: A1111 sampler display name -> Sampler. Keys are lowercased and stripped of any
#: scheduler suffix before lookup, so "DPM++ 2M Karras" resolves via "dpm++ 2m".
SAMPLER_ALIASES = {
    "euler": Sampler.EULER,
    "euler a": Sampler.EULER_ANCESTRAL,
    "euler ancestral": Sampler.EULER_ANCESTRAL,
    "dpm2": Sampler.DPM_2,
    "dpm 2": Sampler.DPM_2,
    "dpm2 a": Sampler.DPM_2_ANCESTRAL,
    "dpm 2 a": Sampler.DPM_2_ANCESTRAL,
    "dpm++ sde": Sampler.DPMPP_SDE,
    "dpm++ 2m": Sampler.DPMPP_2M,
    "dpm++ 2m sde": Sampler.DPMPP_2M_SDE,
    "dpm++ 2m sde heun": Sampler.DPMPP_2M_SDE,
    "dpm++ 3m sde": Sampler.DPMPP_3M_SDE,
    "ddim": Sampler.DDIM,
    "ddpm": Sampler.DDPM,
    "lcm": Sampler.LCM,
}

#: Scheduler suffixes A1111 appends to a sampler name in older builds, and the
#: values its newer separate "Schedule type" field uses.
SCHEDULER_ALIASES = {
    "karras": Scheduler.KARRAS,
    "exponential": Scheduler.EXPONENTIAL,
    "sgm uniform": Scheduler.SGM_UNIFORM,
    "sgm_uniform": Scheduler.SGM_UNIFORM,
    "simple": Scheduler.SIMPLE,
    "normal": Scheduler.NORMAL,
    "automatic": Scheduler.ACCEPT_ANY,
    "uniform": Scheduler.ACCEPT_ANY,
}

#: <lora:name:strength>, strength optional.
LORA_TAG_PATTERN = re.compile(r"<lora:([^:>]+)(?::([0-9.]+))?>", re.IGNORECASE)

#: Keys that identify the trailing settings line. A prompt can itself contain
#: "something: value" text, so shape alone is not enough to tell them apart --
#: the line has to carry at least one setting SDWebUI actually emits.
SETTINGS_LINE_KEYS = (
    "Steps:",
    "Sampler:",
    "CFG scale:",
    "Seed:",
    "Size:",
    "Model hash:",
    "Denoising strength:",
    "Schedule type:",
)


@dataclass
class A1111Parameters:
    """Values recovered from an SDWebUI ``parameters`` string.

    Every field is optional: metadata from other tools, older builds, or a
    hand-edited PNG may carry any subset. Callers decide what a missing value
    means rather than getting a fabricated default here.
    """

    positive: str = ""
    negative: str = ""
    steps: Optional[int] = None
    cfg_scale: Optional[float] = None
    seed: Optional[int] = None
    sampler: Optional[Sampler] = None
    sampler_name: str = ""
    scheduler: Optional[Scheduler] = None
    width: Optional[int] = None
    height: Optional[int] = None
    model_name: str = ""
    model_hash: str = ""
    clip_skip: Optional[int] = None
    denoising_strength: Optional[float] = None
    loras: list = field(default_factory=list)
    has_control_net: bool = False
    raw_settings: dict = field(default_factory=dict)

    def is_img2img(self) -> bool:
        """Denoising strength only appears for img2img generations."""
        return self.denoising_strength is not None

    def has_usable_prompt(self) -> bool:
        return bool(self.positive.strip())

    def template_filename(self) -> str:
        """The SDWebUI template a redo of this generation should start from.

        Chosen from what the metadata proves was used, so an img2img original
        does not come back as txt2img. Note the source *image* for img2img or
        ControlNet is not recoverable -- A1111 never records it -- so the caller
        still has to supply one; see requires_source_image.
        """
        from sd_runner.globals import PromptTypeSDWebUI

        if self.is_img2img() and self.has_control_net:
            return PromptTypeSDWebUI.IMG2IMG_CONTROLNET.value
        if self.is_img2img():
            return PromptTypeSDWebUI.IMG2IMG.value
        if self.has_control_net:
            return PromptTypeSDWebUI.CONTROLNET.value
        return PromptTypeSDWebUI.TXT2IMG.value

    def requires_source_image(self) -> bool:
        """True when the original used an input image that metadata cannot restore.

        A1111 records that ControlNet ran and with what settings, but never the
        path of the image fed to it, and the same is true of the img2img source.
        Redoing those workflows needs the user to supply the image again.
        """
        return self.is_img2img() or self.has_control_net


def split_settings(line: str) -> list:
    """Split a settings line on top-level commas.

    Commas inside quotes or parentheses belong to a value -- a ControlNet block
    is one quoted value containing several of both -- so a plain split would
    shred it into fragments that parse as nonsense keys.
    """
    parts = []
    current = ""
    depth = 0
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
            current += char
        elif char in "([" and not in_quotes:
            depth += 1
            current += char
        elif char in ")]" and not in_quotes:
            depth -= 1
            current += char
        elif char == "," and depth <= 0 and not in_quotes:
            if current.strip():
                parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def resolve_sampler(name: str):
    """Map an A1111 sampler display name to ``(Sampler, Scheduler)``.

    Either may be None when the name is unrecognised. The scheduler comes back
    populated only when the name carried it as a suffix, which is how older
    builds emit it; newer ones use a separate field the caller merges in.
    """
    if not name:
        return None, None
    cleaned = name.strip().lower()
    scheduler = None
    for suffix, value in SCHEDULER_ALIASES.items():
        if cleaned.endswith(" " + suffix):
            scheduler = value
            cleaned = cleaned[: -(len(suffix) + 1)].strip()
            break
    sampler = SAMPLER_ALIASES.get(cleaned)
    if sampler is None:
        logger.warning(f"Unrecognised A1111 sampler name: {name!r}")
    return sampler, scheduler


def extract_loras(prompt: str) -> list:
    """Pull ``<lora:name:strength>`` tags out of a prompt.

    Returns ``[(name, strength), ...]``; strength defaults to 1.0 when the tag
    omits it. The tags are left in the prompt text -- SDWebUI parses them itself
    on the way back in, so stripping them would drop the LoRA from the redo.
    """
    loras = []
    for match in LORA_TAG_PATTERN.finditer(prompt or ""):
        name = match.group(1).strip()
        try:
            strength = float(match.group(2)) if match.group(2) else 1.0
        except ValueError:
            strength = 1.0
        if name:
            loras.append((name, strength))
    return loras


def _to_int(value: str):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: str):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _split_prompt_sections(text: str):
    """Return ``(positive, negative, settings_line)``.

    The settings line is found from the end rather than the start: a prompt can
    itself contain "Key: value" text, but the settings are always last.
    """
    lines = text.splitlines()
    settings_index = None
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        if any(key in line for key in SETTINGS_LINE_KEYS):
            settings_index = i
            # Keep walking up: the settings can wrap across several lines, and
            # the earliest wrapped line is where the prompt actually ends.
            continue
        if settings_index is not None:
            break
    settings_line = ""
    if settings_index is not None:
        settings_line = " ".join(part.strip() for part in lines[settings_index:])
        lines = lines[:settings_index]

    body = "\n".join(lines)
    negative = ""
    marker_at = body.find(NEGATIVE_PROMPT_MARKER)
    if marker_at >= 0:
        negative = body[marker_at + len(NEGATIVE_PROMPT_MARKER):].strip()
        body = body[:marker_at]
    return body.strip(), negative, settings_line


def parse_a1111_parameters(text: str) -> A1111Parameters:
    """Parse an SDWebUI ``parameters`` string.

    Never raises: unparseable input yields a result whose ``has_usable_prompt``
    is False, so a caller can fall back rather than abort a run on odd metadata.
    """
    result = A1111Parameters()
    if not text or not str(text).strip():
        return result

    positive, negative, settings_line = _split_prompt_sections(str(text))
    result.positive = positive
    result.negative = negative
    result.loras = extract_loras(positive)

    for part in split_settings(settings_line):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        key = key.strip()
        value = value.strip()
        result.raw_settings[key] = value
        lowered = key.lower()

        if lowered == "steps":
            result.steps = _to_int(value)
        elif lowered == "cfg scale":
            result.cfg_scale = _to_float(value)
        elif lowered == "seed":
            result.seed = _to_int(value)
        elif lowered == "sampler":
            result.sampler_name = value
            result.sampler, result.scheduler = resolve_sampler(value)
        elif lowered in ("schedule type", "scheduler"):
            resolved = SCHEDULER_ALIASES.get(value.strip().lower())
            if resolved is not None:
                result.scheduler = resolved
        elif lowered == "size":
            dimensions = value.lower().split("x")
            if len(dimensions) == 2:
                result.width = _to_int(dimensions[0])
                result.height = _to_int(dimensions[1])
        elif lowered == "model":
            result.model_name = value
        elif lowered == "model hash":
            result.model_hash = value
        elif lowered == "clip skip":
            result.clip_skip = _to_int(value)
        elif lowered == "denoising strength":
            result.denoising_strength = _to_float(value)
        elif lowered.startswith("controlnet"):
            result.has_control_net = True

    return result
