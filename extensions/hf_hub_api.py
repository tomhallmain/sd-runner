from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from utils.globals import HfHubSortDirection, HfHubSortOption, HfHubVisualMediaTask
from utils.logging_setup import get_logger

logger = get_logger("image_to_prompt.model_download")

# Reduce known HF Hub console noise on Windows/non-symlink setups and repeated cached fetches.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

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


@dataclass(slots=True)
class HfModelSearchResult:
    repo_id: str
    task: str
    downloads: int
    likes: int
    license: str
    gated: bool
    private: bool
    tags: list[str]
    created_at: str
    last_modified: str


class HfHubApiBackend:
    """Hugging Face Hub API backend for model search + download."""

    VISUAL_MEDIA_TASKS = HfHubVisualMediaTask.api_values()

    def __init__(self):
        try:
            from huggingface_hub import HfApi
        except Exception as e:
            raise RuntimeError(
                "huggingface_hub is required for HF Hub search. "
                "Install with: pip install huggingface_hub"
            ) from e
        self._api = HfApi()

    @staticmethod
    def _safe_list(v: Any) -> list[str]:
        if not v:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]

    @staticmethod
    def _to_int(v: Any) -> int:
        try:
            return int(v or 0)
        except Exception:
            return 0

    def search_models(
        self,
        query: str = "",
        *,
        task: Optional[str | HfHubVisualMediaTask] = None,
        visual_only: bool = True,
        limit: int = 100,
        sort: str | HfHubSortOption = HfHubSortOption.DOWNLOADS,
        direction: int | HfHubSortDirection = HfHubSortDirection.DESCENDING,
        include_gated: bool = True,
    ) -> list[HfModelSearchResult]:
        """Search models on HF Hub with metadata useful for UI filtering."""
        sort_value = sort.value if isinstance(sort, HfHubSortOption) else str(sort)
        direction_value = direction.value if isinstance(direction, HfHubSortDirection) else int(direction)
        if isinstance(task, HfHubVisualMediaTask):
            task_value = task.value
        else:
            task_value = str(task or "")

        logger.info(
            "Searching HF models: query=%s task=%s limit=%s sort=%s direction=%s",
            query, task_value, limit, sort_value, direction_value,
        )
        model_iter = self._api.list_models(
            search=(query or None),
            task=(task_value or None),
            sort=sort_value,
            direction=direction_value,
            full=True,
            limit=limit,
        )

        results: list[HfModelSearchResult] = []
        for m in model_iter:
            gated = bool(getattr(m, "gated", False))
            if gated and not include_gated:
                continue
            tags = self._safe_list(getattr(m, "tags", []))
            pipeline_tag = getattr(m, "pipeline_tag", "") or ""
            if visual_only and not task_value and pipeline_tag not in self.VISUAL_MEDIA_TASKS:
                continue
            license_tag = ""
            for t in tags:
                if str(t).startswith("license:"):
                    license_tag = str(t).split(":", 1)[1]
                    break
            results.append(
                HfModelSearchResult(
                    repo_id=str(getattr(m, "id", "")),
                    task=str(pipeline_tag),
                    downloads=self._to_int(getattr(m, "downloads", 0)),
                    likes=self._to_int(getattr(m, "likes", 0)),
                    license=license_tag or "unknown",
                    gated=gated,
                    private=bool(getattr(m, "private", False)),
                    tags=tags,
                    created_at=str(getattr(m, "created_at", "") or ""),
                    last_modified=str(getattr(m, "last_modified", "") or ""),
                )
            )
        return results

    @staticmethod
    def download_file(repo_id: str, filename: str, cache_dir: str | None = None) -> str:
        """Download one file from a model repo (wrapper preserving old behavior)."""
        return ensure_hf_file(repo_id=repo_id, filename=filename, cache_dir=cache_dir)

    @staticmethod
    def download_snapshot(
        repo_id: str,
        allow_patterns: list[str] | None = None,
        cache_dir: str | None = None,
    ) -> str:
        """Download a repo snapshot (wrapper preserving old behavior)."""
        return ensure_hf_snapshot(
            repo_id=repo_id,
            allow_patterns=allow_patterns,
            cache_dir=cache_dir,
        )
