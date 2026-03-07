from __future__ import annotations

from utils.logging_setup import get_logger

logger = get_logger("image_to_prompt.model_download")

def ensure_hf_file(repo_id: str, filename: str, cache_dir: str | None = None) -> str:
    """Download one file from Hugging Face Hub if missing and return its path.

    When ``cache_dir`` is None, Hugging Face default cache resolution is used
    (e.g. HF_HOME / HUGGINGFACE_HUB_CACHE / user .cache locations).
    """
    try:
        from huggingface_hub import hf_hub_download
    except Exception as e:
        raise RuntimeError(
            "huggingface_hub is required for automatic model download. "
            "Install with: pip install huggingface_hub"
        ) from e

    logger.info(f"Ensuring HF file: {repo_id}/{filename}")
    kwargs = {
        "repo_id": repo_id,
        "filename": filename,
    }
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    return hf_hub_download(
        **kwargs,
    )


def ensure_hf_snapshot(
    repo_id: str,
    allow_patterns: list[str] | None = None,
    cache_dir: str | None = None,
) -> str:
    """Download a repo snapshot subset from Hugging Face Hub and return local dir.

    When ``cache_dir`` is None, Hugging Face default cache resolution is used
    (e.g. HF_HOME / HUGGINGFACE_HUB_CACHE / user .cache locations).
    """
    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        raise RuntimeError(
            "huggingface_hub is required for automatic model download. "
            "Install with: pip install huggingface_hub"
        ) from e

    logger.info(f"Ensuring HF snapshot: {repo_id}")
    kwargs = {
        "repo_id": repo_id,
        "allow_patterns": allow_patterns,
    }
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    return snapshot_download(**kwargs)
