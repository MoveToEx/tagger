from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tagger.domain.models import ImageEntry, TagOperation
from tagger.domain.tags import (
    apply_tag_operation,
    eligible_tags,
    filter_traversal_entries,
    unique_tags,
)


@dataclass(frozen=True)
class TraversalItem:
    image_path: Path
    tag_path: Path
    original_tags: tuple[str, ...]
    source_bytes: bytes

    @classmethod
    def from_entry(cls, entry: ImageEntry) -> TraversalItem:
        if not entry.editable or entry.source_bytes is None:
            raise ValueError(f"Entry is not editable: {entry.image_path}")
        return cls(
            image_path=entry.image_path,
            tag_path=entry.tag_path,
            original_tags=tuple(entry.tags),
            source_bytes=entry.source_bytes,
        )


class TraversalSession:
    def __init__(
        self,
        entries: Sequence[ImageEntry],
        operation: TagOperation,
        requested_tags: Sequence[str] = (),
    ) -> None:
        if operation == TagOperation.NORMALIZE:
            raise ValueError("Normalization is not a traversal operation.")
        if not requested_tags:
            raise ValueError("This operation requires at least one tag.")

        self.operation = operation
        self.requested_tags = tuple(unique_tags(requested_tags))
        filtered_entries = filter_traversal_entries(
            entries, operation, self.requested_tags
        )
        self.items = [TraversalItem.from_entry(entry) for entry in filtered_entries]
        if not self.items:
            raise ValueError("No images match the requested traversal tags.")
        self.current_index = 0
        self.reviewed: set[int] = set()
        self.selections: dict[int, tuple[str, ...]] = {}
        self.extra_tags: dict[int, tuple[str, ...]] = {}
        self.applied_inputs: dict[
            int, tuple[tuple[str, ...], tuple[str, ...]]
        ] = {}
        self.staged: dict[int, tuple[str, ...]] = {}

    @property
    def current_item(self) -> TraversalItem:
        return self.items[self.current_index]

    @property
    def at_first(self) -> bool:
        return self.current_index == 0

    @property
    def at_last(self) -> bool:
        return self.current_index == len(self.items) - 1

    @property
    def has_changes(self) -> bool:
        return bool(self.staged)

    def eligible_for(self, index: int | None = None) -> list[str]:
        item = self.items[self.current_index if index is None else index]
        return eligible_tags(item.original_tags, self.requested_tags, self.operation)

    def selected_for(self, index: int | None = None) -> list[str]:
        target = self.current_index if index is None else index
        if target in self.selections:
            return list(self.selections[target])
        if self.operation in {TagOperation.ADD, TagOperation.DELETE}:
            return []
        if self.operation == TagOperation.TOGGLE:
            item = self.items[target]
            current = set(item.original_tags)
            return [tag for tag in self.requested_tags if tag in current]
        return self.eligible_for(target)

    def extra_tags_for(self, index: int | None = None) -> list[str]:
        target = self.current_index if index is None else index
        return list(self.extra_tags.get(target, ()))

    def set_ephemeral(
        self,
        selected_tags: Sequence[str],
        extra_tags: Sequence[str] = (),
        index: int | None = None,
    ) -> None:
        target = self.current_index if index is None else index
        eligible = set(self.eligible_for(target))
        selected = tuple(
            tag for tag in unique_tags(selected_tags) if tag in eligible
        )
        extras = tuple(
            unique_tags(extra_tags)
            if self.operation in {TagOperation.ADD, TagOperation.DELETE}
            else ()
        )
        self.selections[target] = selected
        self.extra_tags[target] = extras
        applied = self.applied_inputs.get(target)
        if applied is None:
            return
        if applied == (selected, extras):
            result = self.result_for(selected, extras, target)
            self.reviewed.add(target)
            if tuple(result) == self.items[target].original_tags:
                self.staged.pop(target, None)
            else:
                self.staged[target] = tuple(result)
        else:
            self.reviewed.discard(target)
            self.staged.pop(target, None)

    def result_for(
        self,
        selected_tags: Sequence[str],
        extra_tags: Sequence[str] = (),
        index: int | None = None,
    ) -> list[str]:
        target = self.current_index if index is None else index
        item = self.items[target]
        operation_tags = list(selected_tags)
        if self.operation in {TagOperation.ADD, TagOperation.DELETE}:
            operation_tags.extend(extra_tags)
        return apply_tag_operation(item.original_tags, operation_tags, self.operation)

    def apply_current(
        self,
        selected_tags: Sequence[str] = (),
        extra_tags: Sequence[str] = (),
    ) -> list[str]:
        eligible = set(self.eligible_for())
        selected = tuple(tag for tag in unique_tags(selected_tags) if tag in eligible)
        extras = (
            tuple(unique_tags(extra_tags))
            if self.operation in {TagOperation.ADD, TagOperation.DELETE}
            else ()
        )

        result = self.result_for(selected, extras)
        self.set_ephemeral(selected, extras)
        self.applied_inputs[self.current_index] = (selected, extras)
        self.reviewed.add(self.current_index)
        if tuple(result) == self.current_item.original_tags:
            self.staged.pop(self.current_index, None)
        else:
            self.staged[self.current_index] = tuple(result)
        return result

    def skip_current(self) -> None:
        self.set_ephemeral((), ())
        self.applied_inputs[self.current_index] = ((), ())
        self.reviewed.add(self.current_index)
        self.staged.pop(self.current_index, None)

    def move_next(self) -> bool:
        if self.at_last:
            return False
        self.current_index += 1
        return True

    def move_back(self) -> bool:
        if self.at_first:
            return False
        self.current_index -= 1
        return True

    def staged_changes(self) -> list[tuple[TraversalItem, list[str]]]:
        return [
            (self.items[index], list(tags))
            for index, tags in sorted(self.staged.items())
        ]

    def all_available_changes(self) -> list[tuple[TraversalItem, list[str]]]:
        changes: list[tuple[TraversalItem, list[str]]] = []
        for index, item in enumerate(self.items):
            result = self.result_for(self.eligible_for(index), index=index)
            if tuple(result) != item.original_tags:
                changes.append((item, result))
        return changes
