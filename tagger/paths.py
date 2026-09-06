from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIRECTORY_ENV_VAR = "TAGGER_DATA_DIRECTORY"
DEFAULT_DATA_DIRECTORY = PROJECT_ROOT / "data"


def get_data_directory() -> Path:
    configured = os.environ.get(DATA_DIRECTORY_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATA_DIRECTORY


DATA_DIRECTORY = get_data_directory()
TAG_LIBRARY_PATH = DATA_DIRECTORY / "danbooru_tags.csv"
SETTINGS_PATH = DATA_DIRECTORY / "settings.json"


def get_tag_library_path() -> Path:
    return get_data_directory() / "danbooru_tags.csv"


def get_settings_path() -> Path:
    return get_data_directory() / "settings.json"


def ensure_data_directory() -> Path:
    directory = get_data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    return directory
