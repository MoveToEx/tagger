from __future__ import annotations

import json
from pathlib import Path

import pytest

import tagger.tag_library as tag_library_module
from tagger.tag_library import (
    TagLibrary,
    download_danbooru_tags,
    get_tag_library_file_info,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        payload, self._payload = self._payload, b""
        return payload


class _Opener:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, *_args: object, **_kwargs: object) -> _Response:
        return _Response(self.payload)


def test_download_writes_binary_library(tmp_path: Path, monkeypatch) -> None:
    payload = b"\n".join(
        json.dumps(row).encode("utf-8")
        for row in (
            {"name": "red_hair", "post_count": 100},
            {"name": "blue_eyes", "post_count": 10},
            {"name": "red_hair", "post_count": 120},
        )
    )
    monkeypatch.setattr(
        tag_library_module, "build_opener", lambda _handler: _Opener(payload)
    )
    destination = tmp_path / "tag-lib" / "danbooru_tags.bin"

    count = download_danbooru_tags(
        destination,
        minimum_posts=20,
        source_url="https://example.invalid/tags.jsonl",
    )

    assert count == 1
    assert destination.read_bytes().startswith(b"TAGGER_TAG_LIBRARY\x01")
    library = TagLibrary(destination)
    assert library.suggestions("red") == ["red_hair"]
    assert get_tag_library_file_info(destination).tag_count == 1


def test_csv_content_is_not_treated_as_a_binary_library(tmp_path: Path) -> None:
    path = tmp_path / "danbooru_tags.csv"
    path.write_text("name,post_count\nred,100\n", encoding="utf-8")

    with pytest.raises(ValueError, match="supported binary file"):
        TagLibrary(path)
