"""Identify a checkpoint's architecture from its name, then its file, then its folder."""

import json
import os
import re
import struct

from sd_runner.globals import ArchitectureType

# Safetensors stores an 8-byte header length followed by a JSON object of
# tensor names. A few megabytes covers every legitimate header; anything
# larger is treated as a file we should not try to parse.
_MAX_HEADER_BYTES = 8 * 1024 * 1024

_4B_RE = re.compile(r"(?<!\d)4b")
_KREA2_RE = re.compile(r"krea[\W_]*2(?!\d)")
_MINIMAX_H3_RE = re.compile(r"minimax[\W_]*h[\W_]*3(?!\d)")
_FLUX3_RE = re.compile(r"flux[\W_]*3(?!\d)")
_FLUX2_RE = re.compile(r"flux[\W_]*2(?!\d)")
# "flux1-dev" counts. "flux2" / "flux3" are handled by the patterns above.
_FLUX_RE = re.compile(r"(?:^|[^a-z0-9])flux\d?(?:[^a-z0-9]|$)")
_KLEIN_RE = re.compile(r"(?:^|[^a-z0-9])klein(?:[^a-z0-9]|$)")
_TURBO_RE = re.compile(r"(?:^|[^a-z])turbo(?:[^a-z]|$)")
_SD15_RE = re.compile(
    r"(?:^|[^a-z0-9])sd[\W_]?1[\W_.]5(?:[^a-z0-9]|$)"
    r"|(?:^|[^a-z0-9])sd15(?:[^a-z0-9]|$)"
    r"|(?:^|[^a-z0-9])sd_15(?:[^a-z0-9]|$)"
    r"|v1[.\-]5"
)


def _token(text: str, word: str) -> bool:
    return re.search(rf"(?:^|[^a-z0-9]){re.escape(word)}(?:[^a-z0-9]|$)", text) is not None


def _klein_size(*parts: str) -> ArchitectureType:
    blob = " ".join(part for part in parts if part).lower()
    if _4B_RE.search(blob):
        return ArchitectureType.FLUX2_KLEIN_4B
    return ArchitectureType.FLUX2_KLEIN


def _is_flux2(text: str) -> bool:
    """Flux.2, including Flux.2 Klein. Flux.3 is a separate architecture."""
    if re.search(r"(?:^|[^a-z0-9])flux2?klein(?:[^a-z0-9]|$)", text):
        return True
    if _FLUX2_RE.search(text):
        return True
    # "klein" alone is a common word fragment; require a flux token too.
    return _KLEIN_RE.search(text) is not None and _FLUX_RE.search(text) is not None


def _is_sdxl(text: str) -> bool:
    if _token(text, "sdxl") or _token(text, "pony") or _token(text, "xl"):
        return True
    # Glued into the name, then a boundary or a version: juggernautXL_v9, realvisxlV30.
    return re.search(r"xl(?:[^a-z0-9]|v\d|$)", text) is not None


def classify_text(text: str) -> ArchitectureType | None:
    """Classify a filename or path. Returns None when the text has no signal."""
    if not text:
        return None
    lowered = text.lower()
    if "illustrious" in lowered:
        return ArchitectureType.ILLUSTRIOUS
    if _token(lowered, "chroma"):
        return ArchitectureType.CHROMA
    if "zimage" in lowered or "z_image" in lowered or "z-image" in lowered:
        return ArchitectureType.Z_IMAGE_TURBO
    # "krea2" before a bare "flux" token, so flux1_krea_dev stays Flux.1.
    if _KREA2_RE.search(lowered):
        return ArchitectureType.KREA2
    if _MINIMAX_H3_RE.search(lowered):
        return ArchitectureType.MINIMAX_H3
    if "qwen" in lowered:
        return ArchitectureType.QWEN
    # Flux.3 before Flux.2 before Flux.1. "flux-2-klein" must not become Flux.1,
    # and "flux-3" must not become Flux.2 Klein.
    if _FLUX3_RE.search(lowered):
        return ArchitectureType.FLUX3
    if _is_flux2(lowered):
        return _klein_size(lowered)
    if _FLUX_RE.search(lowered):
        return ArchitectureType.FLUX
    if _TURBO_RE.search(lowered):
        return ArchitectureType.TURBO
    if _is_sdxl(lowered):
        return ArchitectureType.SDXL
    if _SD15_RE.search(lowered):
        return ArchitectureType.SD_15
    return None


def _classify_metadata(metadata: dict | None) -> ArchitectureType | None:
    if not metadata:
        return None
    arch = str(metadata.get("modelspec.architecture") or "")
    base = str(metadata.get("ss_base_model_version") or "")
    title = str(metadata.get("modelspec.title") or "")
    found = classify_text(" ".join((arch, base, title)))
    if found:
        return found
    arch_l = arch.lower()
    base_l = base.lower()
    if arch_l.startswith("stable-diffusion-v1") or base_l in {"sd_v1", "sd15", "v1-5", "sd_v1-5"} or base_l.startswith("sd_v1"):
        return ArchitectureType.SD_15
    if arch_l.startswith("stable-diffusion-xl") or base_l.startswith("sdxl"):
        return ArchitectureType.SDXL
    return None


def _has_stem(keys: frozenset, stem: str) -> bool:
    for suffix in (".weight", ".scale"):
        target = stem + suffix
        for key in keys:
            if key == target or key.endswith("." + target):
                return True
    return False


def classify_tensor_keys(keys) -> ArchitectureType | None:
    """Match ComfyUI's model_detection signatures. Size (4B vs 9B) is not in the keys."""
    if not keys:
        return None
    keyset = frozenset(keys)
    if _has_stem(keyset, "txtfusion.projector"):
        return ArchitectureType.KREA2
    if _has_stem(keyset, "video_patch_proj") and _has_stem(keyset, "audio_patch_proj"):
        return ArchitectureType.MINIMAX_H3
    # FLUX.3 — content-mode blocks, not the Flux.2 double-stream modulation.
    if _has_stem(keyset, "content_mode_blocks.image.0.attn_out") and _has_stem(keyset, "single_stream_modulations.txt.lin"):
        return ArchitectureType.FLUX3
    # FLUX.2 (Klein and Flux.2 dev share this). Callers still apply a 4B name hint.
    if _has_stem(keyset, "double_stream_modulation_img.lin") and (
        _has_stem(keyset, "double_blocks.0.img_attn.norm.key_norm") or _has_stem(keyset, "img_in")
    ):
        return ArchitectureType.FLUX2_KLEIN
    if _has_stem(keyset, "double_blocks.0.img_attn.norm.key_norm"):
        return ArchitectureType.FLUX
    if any("middle_block.1.transformer_blocks.9." in key for key in keyset):
        return ArchitectureType.SDXL
    if any("middle_block.1.transformer_blocks.0." in key for key in keyset):
        return ArchitectureType.SD_15
    return None


def _from_flags(model_id, path, is_xl, is_turbo, is_flux, is_chroma, is_z_image_turbo, is_qwen, is_flux2_klein):
    if is_chroma:
        return ArchitectureType.CHROMA
    if is_z_image_turbo:
        return ArchitectureType.Z_IMAGE_TURBO
    if is_qwen:
        return ArchitectureType.QWEN
    if is_xl:
        return ArchitectureType.SDXL
    if is_turbo:
        return ArchitectureType.TURBO
    if is_flux2_klein:
        return _klein_size(model_id or "", path or "")
    if is_flux:
        return ArchitectureType.FLUX
    return None


def classify_architecture(
    model_id,
    path,
    is_xl=False,
    is_turbo=False,
    is_flux=False,
    is_chroma=False,
    is_z_image_turbo=False,
    is_qwen=False,
    is_flux2_klein=False,
    metadata=None,
    tensor_keys=None,
) -> ArchitectureType:
    """Resolve an architecture. Filename beats file contents, which beat the folder."""
    from_name = classify_text(model_id)
    if from_name:
        return from_name

    from_meta = _classify_metadata(metadata)
    if from_meta:
        return _apply_size_hint(from_meta, model_id, path)

    from_keys = classify_tensor_keys(tensor_keys)
    if from_keys:
        return _apply_size_hint(from_keys, model_id, path)

    from_path = classify_text(path)
    if from_path:
        return from_path

    from_flags = _from_flags(
        model_id, path, is_xl, is_turbo, is_flux, is_chroma, is_z_image_turbo, is_qwen, is_flux2_klein
    )
    if from_flags:
        return from_flags
    return ArchitectureType.UNKNOWN


def _apply_size_hint(architecture: ArchitectureType, model_id, path) -> ArchitectureType:
    if architecture in (ArchitectureType.FLUX2_KLEIN, ArchitectureType.FLUX2_KLEIN_4B):
        return _klein_size(model_id or "", path or "")
    return architecture


def read_safetensors_header(path: str) -> tuple[dict, frozenset]:
    """Return (metadata, tensor names) from a safetensors file, or empty values."""
    if not path or not str(path).lower().endswith(".safetensors"):
        return {}, frozenset()
    try:
        with open(path, "rb") as handle:
            raw_len = handle.read(8)
            if len(raw_len) < 8:
                return {}, frozenset()
            header_len = struct.unpack("<Q", raw_len)[0]
            if header_len < 2 or header_len > _MAX_HEADER_BYTES:
                return {}, frozenset()
            header = json.loads(handle.read(header_len))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, struct.error):
        return {}, frozenset()
    if not isinstance(header, dict):
        return {}, frozenset()
    metadata = header.get("__metadata__")
    if not isinstance(metadata, dict):
        metadata = {}
    keys = frozenset(key for key in header if key != "__metadata__")
    return metadata, keys


def header_matches_file(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and str(path).lower().endswith(".safetensors")
