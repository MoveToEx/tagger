from __future__ import annotations

from pathlib import Path

from tagger.paths import (
    DATA_DIRECTORY_ENV_VAR,
    get_data_directory,
    get_settings_path,
    get_tag_library_path,
)
from tagger.settings import create_app_settings
from tagger.tag_library import TagLibrary


def test_environment_data_directory_is_used_by_app_defaults(
    tmp_path: Path, monkeypatch
) -> None:
    data_directory = tmp_path / "application-data"
    monkeypatch.setenv(DATA_DIRECTORY_ENV_VAR, str(data_directory))

    assert get_data_directory() == data_directory
    assert get_settings_path() == data_directory / "settings.json"
    assert get_tag_library_path() == data_directory / "danbooru_tags.csv"

    settings = create_app_settings()
    assert Path(settings.fileName()) == get_settings_path()
    assert TagLibrary().csv_path == get_tag_library_path()
