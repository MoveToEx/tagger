from __future__ import annotations

from collections import Counter
import re
from typing import Iterable, Sequence

from tagger.domain.models import ImageEntry, TagOperation
from tagger.scripting import TagSet


def unique_tags(tags: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


def parse_tags(text: str) -> list[str]:
    return unique_tags(text.split(","))


def parse_requested_tags(text: str) -> list[str]:
    tags = parse_tags(text)
    if not tags:
        raise ValueError("Enter at least one tag.")
    return tags


def normalize_tags(tags: Iterable[str]) -> list[str]:
    return sorted(unique_tags(tags))


def serialize_tags(tags: Iterable[str]) -> str:
    return ", ".join(normalize_tags(tags)) + "\n"


def tag_matches_pattern(tag: str, pattern: str) -> bool:
    """Match a complete tag, treating only ``*`` as a wildcard."""
    if not pattern:
        return False
    expression = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(expression, tag, flags=re.DOTALL) is not None


def matching_tag_counts(
    entries: Iterable[ImageEntry], pattern: str
) -> list[tuple[str, int]]:
    if not pattern:
        return []
    counts = Counter(
        tag
        for entry in entries
        for tag in entry.tags
        if tag_matches_pattern(tag, pattern)
    )
    return sorted(counts.items(), key=lambda item: (item[0].casefold(), item[0]))


def eligible_tags(
    current_tags: Sequence[str],
    requested_tags: Sequence[str],
    operation: TagOperation,
) -> list[str]:
    current = set(current_tags)
    if operation == TagOperation.ADD:
        return [tag for tag in requested_tags if tag not in current]
    if operation == TagOperation.DELETE:
        return [tag for tag in requested_tags if tag in current]
    if operation == TagOperation.TOGGLE:
        return list(requested_tags)
    return []


def should_traverse_entry(
    current_tags: Sequence[str],
    requested_tags: Sequence[str],
    operation: TagOperation,
) -> bool:
    """Return whether an entry should be shown in a folder traversal.

    Add skips entries that already contain every requested tag. Delete skips
    entries that contain none of the requested tags, so both workflows avoid
    presenting no-op candidates by default.
    """
    if operation == TagOperation.NORMALIZE:
        raise ValueError("Normalization is not a traversal operation.")
    if operation == TagOperation.TOGGLE:
        return True
    current = set(current_tags)
    requested = set(requested_tags)
    if operation == TagOperation.ADD:
        return not requested.issubset(current)
    return not current.isdisjoint(requested)


def filter_traversal_entries(
    entries: Sequence[ImageEntry],
    operation: TagOperation,
    requested_tags: Sequence[str] = (),
) -> list[ImageEntry]:
    requested = unique_tags(requested_tags)
    return [
        entry
        for entry in entries
        if should_traverse_entry(entry.tags, requested, operation)
    ]


def apply_tag_operation(
    current_tags: Sequence[str],
    requested_tags: Sequence[str],
    operation: TagOperation,
) -> list[str]:
    if operation == TagOperation.NORMALIZE:
        return normalize_tags(current_tags)

    requested = unique_tags(requested_tags)
    current = list(current_tags)
    current_set = set(current)

    if operation == TagOperation.ADD:
        result = [*current, *(tag for tag in requested if tag not in current_set)]
    elif operation == TagOperation.DELETE:
        requested_set = set(requested)
        result = [tag for tag in current if tag not in requested_set]
    elif operation == TagOperation.TOGGLE:
        requested_set = set(requested)
        result = [tag for tag in current if tag not in requested_set]
        result.extend(tag for tag in requested if tag not in current_set)
    else:
        raise ValueError(f"Unsupported tag operation: {operation}")

    return normalize_tags(result)
