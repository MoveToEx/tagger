from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from pathlib import Path
import tempfile
from urllib.request import ProxyHandler, Request, build_opener

from tagger.paths import get_tag_library_path
from tagger.tag_library.config import DATASET_TAGS_URL
from tagger.tag_library.format import write_tag_library
from tagger.tag_library.text import _search_key


def download_danbooru_tags(
    destination: Path | None = None,
    *,
    minimum_posts: int = 20,
    proxy: str | None = "",
    progress: Callable[[int, str], None] | None = None,
    source_url: str | None = None,
) -> int:
    destination = (
        get_tag_library_path() if destination is None else destination
    )
    proxy_url = proxy.strip() if proxy is not None else None
    proxy_handler = (
        ProxyHandler()
        if proxy_url is None
        else ProxyHandler(
            {"http": proxy_url, "https": proxy_url} if proxy_url else {}
        )
    )
    opener = build_opener(proxy_handler)
    url = source_url or DATASET_TAGS_URL
    request = Request(url, headers={"User-Agent": "tag-gui/0.1"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with opener.open(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length", 0) or 0)
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".jsonl", delete=False, dir=destination.parent
            ) as download_stream:
                temporary_path = Path(download_stream.name)
                downloaded = 0
                while chunk := response.read(1024 * 1024):
                    download_stream.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        percent = int(downloaded * 70 / total) if total else 0
                        progress(percent, "Downloading tag data...")

        with temporary_path.open("r", encoding="utf-8-sig") as source:
            records: dict[str, tuple[str, int]] = {}
            for row_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON in tags.jsonl at line {row_number}: {exc.msg}"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(
                        f"Expected a JSON object in tags.jsonl at line {row_number}."
                    )
                name_value = _mapping_value(row, ("name", "tag", "tag_name"))
                count_value = _mapping_value(
                    row, ("post_count", "count", "posts", "tag_count")
                )
                name = str(name_value).strip() if name_value is not None else ""
                try:
                    count = (
                        int(float(str(count_value)))
                        if count_value is not None
                        else 0
                    )
                except (TypeError, ValueError):
                    continue
                if name and count >= minimum_posts:
                    key = _search_key(name)
                    existing = records.get(key)
                    if existing is None or count > existing[1]:
                        records[key] = (name, count)
                if progress and row_number % 20_000 == 0:
                    progress(75, f"Filtering tags ({row_number:,} rows)...")

        sorted_records: list[tuple[str, int]] = sorted(
            records.values(), key=_record_sort_key
        )
        write_tag_library(destination, sorted_records)
        if progress:
            progress(100, "Tag library ready.")
        return len(records)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _record_sort_key(item: tuple[str, int]) -> tuple[int, str]:
    return -item[1], _search_key(item[0])


def _mapping_value(
    mapping: dict[object, object], choices: Sequence[str]
) -> object | None:
    fields = {
        str(key).strip().casefold(): value for key, value in mapping.items()
    }
    return next((fields[choice] for choice in choices if choice in fields), None)
