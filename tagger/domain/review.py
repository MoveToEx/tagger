from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tagger.domain.models import ImageEntry
from tagger.domain.tags import unique_tags


@dataclass(frozen=True)
class ReviewItem:
    image_path: Path
    tag_path: Path
    original_tags: tuple[str, ...]
    source_bytes: bytes

    @classmethod
    def from_entry(cls, entry: ImageEntry) -> "ReviewItem":
        if not entry.editable or entry.source_bytes is None:
            raise ValueError(f"Entry is not editable: {entry.image_path}")
        return cls(
            image_path=entry.image_path,
            tag_path=entry.tag_path,
            original_tags=tuple(entry.tags),
            source_bytes=entry.source_bytes,
        )


class ReviewSession:
    """In-memory review state; sidecars are written only at completion."""

    def __init__(
        self, entries: Sequence[ImageEntry], ignored_tags: Sequence[str] = ()
    ) -> None:
        self.items = [
            ReviewItem.from_entry(entry)
            for entry in entries
            if entry.editable and entry.tags
        ]
        ignored = set(unique_tags(ignored_tags))
        self.review_tags: dict[int, tuple[str, ...]] = {
            index: tuple(tag for tag in item.original_tags if tag not in ignored)
            for index, item in enumerate(self.items)
        }
        self.current_index = 0
        self.current_tag_index = 0
        self.completed = not any(self.review_tags.values())
        for index, tags in self.review_tags.items():
            if tags:
                self.current_index = index
                break
        self.working_tags: dict[int, list[str]] = {
            index: list(item.original_tags) for index, item in enumerate(self.items)
        }
        self.reviewed_tags: dict[int, set[str]] = {
            index: set(item.original_tags) - set(self.review_tags[index])
            for index, item in enumerate(self.items)
        }

    @property
    def current_item(self) -> ReviewItem:
        return self.items[self.current_index]

    @property
    def current_tags(self) -> list[str]:
        if not self.items:
            return []
        return list(self.working_tags[self.current_index])

    @property
    def current_tag(self) -> str:
        if not self.items:
            return ""
        tags = self.review_tags[self.current_index]
        if not tags:
            return ""
        return tags[self.current_tag_index]

    @property
    def current_review_tags(self) -> tuple[str, ...]:
        if not self.items:
            return ()
        return self.review_tags[self.current_index]

    @property
    def finished(self) -> bool:
        return self.completed

    @property
    def total_tag_count(self) -> int:
        return sum(len(tags) for tags in self.review_tags.values())

    @property
    def reviewed_tag_count(self) -> int:
        return sum(
            sum(tag in self.reviewed_tags[index] for tag in self.review_tags[index])
            for index in range(len(self.items))
        )

    @property
    def deleted_tag_count(self) -> int:
        return sum(
            1
            for index, item in enumerate(self.items)
            for tag in item.original_tags
            if tag not in self.working_tags[index]
        )

    @property
    def at_first(self) -> bool:
        return self.current_tag_index == 0 and not any(
            self.review_tags[index] for index in range(self.current_index)
        )

    @property
    def at_last(self) -> bool:
        if not self.items or self.completed:
            return True
        return self._next_position() is None

    @property
    def has_changes(self) -> bool:
        return any(
            tuple(self.working_tags[index]) != item.original_tags
            for index, item in enumerate(self.items)
        )

    def keep_current(self) -> None:
        if self.completed:
            return
        tag = self.current_tag
        self._restore_original_tag(tag)
        self.reviewed_tags[self.current_index].add(tag)
        if not self._advance():
            self.completed = True

    def keep_all_current(self) -> None:
        """Keep every original tag on the current image and advance to the next image."""
        if self.completed:
            return
        index = self.current_index
        for tag in self.current_item.original_tags:
            self._restore_original_tag(tag)
        self.reviewed_tags[index].update(self.current_item.original_tags)
        next_index = self._next_item_index(index + 1)
        if next_index is not None:
            self.current_index = next_index
            self.current_tag_index = 0
        else:
            self.completed = True

    def delete_current(self) -> None:
        if self.completed:
            return
        tags = self.working_tags[self.current_index]
        tag = self.current_tag
        self.reviewed_tags[self.current_index].add(tag)
        if tag in tags:
            tags.remove(tag)
        if not self._advance():
            self.completed = True

    def select_tag(self, tag_index: int) -> bool:
        if self.completed or not self.items:
            return False
        if not 0 <= tag_index < len(self.current_review_tags):
            return False
        self.current_tag_index = tag_index
        return True

    def add_kept_tags(self, tags: Sequence[str]) -> list[str]:
        if self.completed or not self.items:
            return []
        current = self.working_tags[self.current_index]
        additions = [tag for tag in unique_tags(tags) if tag not in current]
        current.extend(additions)
        self.reviewed_tags[self.current_index].update(additions)
        return additions

    def move_back(self) -> bool:
        if self.completed:
            if not any(self.review_tags.values()):
                return False
            self.completed = False
            return True
        if self.current_tag_index > 0:
            self.current_tag_index -= 1
            return True
        index = self.current_index - 1
        while index >= 0:
            tags = self.review_tags[index]
            if tags:
                self.current_index = index
                self.current_tag_index = len(tags) - 1
                return True
            index -= 1
        return False

    def move_forward(self) -> bool:
        if self.completed:
            return False
        position = self._next_position()
        if position is None:
            return False
        self.current_index, self.current_tag_index = position
        return True

    def _advance(self) -> bool:
        position = self._next_position()
        if position is None:
            return False
        self.current_index, self.current_tag_index = position
        return True

    def _next_position(self) -> tuple[int, int] | None:
        if not self.items:
            return None
        if self.current_tag_index + 1 < len(self.current_review_tags):
            return self.current_index, self.current_tag_index + 1
        index = self._next_item_index(self.current_index + 1)
        if index is not None:
            return index, 0
        return None

    def _next_item_index(self, start: int) -> int | None:
        for index in range(start, len(self.items)):
            if self.review_tags[index]:
                return index
        return None

    def _restore_original_tag(self, tag: str) -> None:
        tags = self.working_tags[self.current_index]
        if tag in tags:
            return
        original_tags = self.current_item.original_tags
        original_set = set(original_tags)
        kept_originals = set(tags)
        kept_originals.add(tag)
        extras = [existing for existing in tags if existing not in original_set]
        self.working_tags[self.current_index] = [
            existing for existing in original_tags if existing in kept_originals
        ] + extras

    def staged_changes(self) -> list[tuple[ReviewItem, list[str]]]:
        return [
            (item, list(self.working_tags[index]))
            for index, item in enumerate(self.items)
            if tuple(self.working_tags[index]) != item.original_tags
        ]
