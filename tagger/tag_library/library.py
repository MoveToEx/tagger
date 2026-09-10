from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from heapq import merge
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from tagger.domain.models import ImageEntry
from tagger.paths import get_tag_library_path
from tagger.tag_library.config import _RankedTag
from tagger.tag_library.format import _read_binary_records
from tagger.tag_library.text import _search_key, pending_tag, transform_tag_name


class TagLibrary(QObject):
    changed = Signal()

    def __init__(
        self,
        library_path: Path | None = None,
        parent: QObject | None = None,
        *,
        underscores_to_spaces: bool = False,
        escape_parentheses: bool = False,
    ) -> None:
        super().__init__(parent)
        self.library_path = (
            get_tag_library_path() if library_path is None else library_path
        )
        self.underscores_to_spaces = underscores_to_spaces
        self.escape_parentheses = escape_parentheses
        self._danbooru: dict[str, tuple[str, int]] = {}
        self._folder: dict[str, tuple[str, int]] = {}
        self._ranked: list[_RankedTag] = []
        self._folder_ranked: list[_RankedTag] = []
        self._trigrams: dict[str, list[int]] = {}
        self.reload_danbooru()

    def reload_danbooru(self) -> None:
        records: dict[str, tuple[str, int]] = {}
        try:
            raw_records = _read_binary_records(self.library_path)
        except FileNotFoundError:
            raw_records = []
        for raw_name, count in raw_records:
            name = transform_tag_name(
                raw_name,
                underscores_to_spaces=self.underscores_to_spaces,
                escape_parentheses=self.escape_parentheses,
            )
            key = _search_key(name)
            existing = records.get(key)
            if existing is None or count > existing[1]:
                records[key] = (name, count)
        self._danbooru = records
        self._rebuild_index()
        self._rebuild_folder_ranking()
        self.changed.emit()

    def set_transform_options(
        self, *, underscores_to_spaces: bool, escape_parentheses: bool
    ) -> None:
        changed = (
            self.underscores_to_spaces != underscores_to_spaces
            or self.escape_parentheses != escape_parentheses
        )
        self.underscores_to_spaces = underscores_to_spaces
        self.escape_parentheses = escape_parentheses
        if changed:
            self.reload_danbooru()

    def set_folder_entries(self, entries: Iterable[ImageEntry]) -> None:
        counts = Counter(tag for entry in entries for tag in entry.tags)
        self._folder = {
            _search_key(name): (name, count) for name, count in counts.items()
        }
        self._rebuild_folder_ranking()
        self.changed.emit()

    def clear_folder_tags(self) -> None:
        if not self._folder:
            return
        self._folder.clear()
        self._folder_ranked.clear()
        self.changed.emit()

    def suggestions(self, text: str, limit: int = 12) -> list[str]:
        query = _search_key(pending_tag(text))
        if not query or limit <= 0:
            return []
        completed_text, separator, _pending = text.rpartition(",")
        completed = (
            {
                _search_key(tag)
                for tag in completed_text.split(",")
                if tag.strip()
            }
            if separator
            else set()
        )
        result: list[str] = []
        matches = merge(
            self._matching_danbooru_tags(query, completed),
            self._matching_folder_tags(query, completed),
            key=_ranked_tag_key,
        )
        for name, _key, _count in matches:
            result.append(name)
            if len(result) == limit:
                break
        return result

    @property
    def size(self) -> int:
        return len(self._danbooru) + sum(
            key not in self._danbooru for key in self._folder
        )

    def _matching_danbooru_tags(
        self, query: str, completed: set[str]
    ) -> Iterable[_RankedTag]:
        if len(query) >= 3:
            grams = {query[index : index + 3] for index in range(len(query) - 2)}
            posting_lists = [self._trigrams.get(gram, ()) for gram in grams]
            if not posting_lists or any(not posting for posting in posting_lists):
                return
            candidates: Iterable[int] = min(posting_lists, key=len)
        else:
            candidates = range(len(self._ranked))

        for index in candidates:
            item = self._ranked[index]
            _name, key, _count = item
            if key not in self._folder and key not in completed and query in key:
                yield item

    def _matching_folder_tags(
        self, query: str, completed: set[str]
    ) -> Iterable[_RankedTag]:
        return (
            item
            for item in self._folder_ranked
            if item[1] not in completed and query in item[1]
        )

    def _rebuild_index(self) -> None:
        self._ranked = sorted(
            ((name, key, count) for key, (name, count) in self._danbooru.items()),
            key=_ranked_tag_key,
        )
        trigrams: dict[str, list[int]] = {}
        for index, (_name, key, _count) in enumerate(self._ranked):
            for gram in {key[offset : offset + 3] for offset in range(len(key) - 2)}:
                trigrams.setdefault(gram, []).append(index)
        self._trigrams = trigrams

    def _rebuild_folder_ranking(self) -> None:
        ranked: list[_RankedTag] = []
        for key, (name, count) in self._folder.items():
            existing = self._danbooru.get(key)
            ranked.append((name, key, max(count, existing[1] if existing else 0)))
        self._folder_ranked = sorted(ranked, key=_ranked_tag_key)


def _ranked_tag_key(item: _RankedTag) -> tuple[int, str, str]:
    name, key, count = item
    return (-count, key, name)
