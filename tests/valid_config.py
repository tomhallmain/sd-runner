"""A config.json for tests whose every location exists.

The example config names folders on a developer's own drives. Config drops a
folder it cannot find, and code that assumes the folder was set then fails in
ways that depend on which machine runs the suite. Every directory setting here
points at a folder created under *root* instead.

Kept free of sd_runner imports: the root conftest calls this before Config is
first constructed.
"""

import json
import os

EXAMPLE_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sd_runner", "data", "config_example.json",
)

_DIRECTORY_SUFFIXES = ("_dir", "_dir2", "_loc")

_FILE_KEYS = (
    "interrogator_initial_questions_file",
    "interrogator_questions_file",
    "interrogator_folder_category_mappings_file",
)


def write_valid_config(configs_dir, root) -> str:
    """Write config.json into *configs_dir* with every location under *root*.

    Returns the path written. A setting the example leaves null stays null, so
    optional features stay off exactly as they are for a new user.
    """
    with open(EXAMPLE_CONFIG, "r", encoding="utf-8") as f:
        data = json.load(f)

    for key, value in list(data.items()):
        if not isinstance(value, str) or not value.strip():
            continue
        if key.endswith(_DIRECTORY_SUFFIXES):
            folder = os.path.join(str(root), key)
            os.makedirs(folder, exist_ok=True)
            data[key] = folder

    for key in _FILE_KEYS:
        if key in data:
            data[key] = None

    os.makedirs(str(configs_dir), exist_ok=True)
    path = os.path.join(str(configs_dir), "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path
