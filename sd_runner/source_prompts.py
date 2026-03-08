from __future__ import annotations

import os
from dataclasses import dataclass

from sd_runner.adapter_sorting import _sort_adapters_by_recency
from utils.logging_setup import get_logger
from utils.utils import Utils

logger = get_logger("source_prompts")

preset_source_prompts: list[str] = []


@dataclass(slots=True)
class SourcePrompt:
    image_path: str

    def has_valid_path(self) -> bool:
        # Keep path filtering lightweight for very large directories.
        return bool(self.image_path and str(self.image_path).strip())


def get_source_prompts(
    source_prompt_files: list[str] | None = None,
    random_sort: bool = True,
    app_actions=None,
) -> tuple[list[SourcePrompt], bool]:
    """Get source prompt image paths with recency-based sorting."""
    files = source_prompt_files or preset_source_prompts[:]

    is_dir = False
    if len(files) == 1 and os.path.isdir(files[0]):
        files = Utils.get_files_from_dir(
            files[0],
            recursive=False,
            random_sort=random_sort,
            allowed_extensions=Utils.IMAGE_EXTENSIONS,
        )
        is_dir = True

    ordered_files = _sort_adapters_by_recency(
        files,
        random_sort,
        app_actions,
        lambda p: str(p),
    )

    source_prompts: list[SourcePrompt] = []
    for path in ordered_files:
        sp = SourcePrompt(image_path=str(path))
        if sp.has_valid_path():
            source_prompts.append(sp)
        else:
            logger.debug("Invalid source prompt image path: %s", path)

    return source_prompts, is_dir
