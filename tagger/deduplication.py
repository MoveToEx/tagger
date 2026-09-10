from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import imagehash
from PIL import Image, ImageOps


THRESHOLDS = ((0, "Exact"), (1, "Very similar"), (2, "Similar"), (4, "Speculative"))


@dataclass(frozen=True)
class DuplicatePair:
    left: Path
    right: Path
    distance: int


@dataclass
class DuplicateScanResult:
    pairs: list[DuplicatePair] = field(default_factory=list)
    failures: dict[Path, str] = field(default_factory=dict)


def perceptual_hash(path: Path) -> int:
    with Image.open(path) as image:
        return int(str(imagehash.phash(ImageOps.exif_transpose(image))), 16)


def find_duplicate_pairs(
    paths: Sequence[Path],
    threshold: int,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> DuplicateScanResult:
    """Hash each image once and find pairs within the inclusive Hamming distance."""
    if threshold not in dict(THRESHOLDS):
        raise ValueError("Threshold must be 0, 1, 2, or 4.")
    result = DuplicateScanResult()
    paths = list(dict.fromkeys(paths))
    hashed: list[tuple[Path, int]] = []
    # With at most t differing bits, at least one of t + 1 disjoint chunks
    # must match. Bucketing by those chunks avoids comparing unrelated hashes.
    chunks = threshold + 1
    boundaries = [64 * index // chunks for index in range(chunks + 1)]
    buckets: list[dict[int, list[int]]] = [{} for _ in range(chunks)]
    for number, path in enumerate(paths, 1):
        if cancelled and cancelled():
            return result
        try:
            value = perceptual_hash(path)
        except Exception as exc:
            result.failures[path] = str(exc)
        else:
            keys = [
                (value >> start) & ((1 << (end - start)) - 1)
                for start, end in zip(boundaries, boundaries[1:])
            ]
            candidates: set[int] = set()
            for bucket, key in zip(buckets, keys):
                candidates.update(bucket.get(key, ()))
            for index in sorted(candidates):
                if cancelled and cancelled():
                    return result
                other_path, other_value = hashed[index]
                distance = (value ^ other_value).bit_count()
                if distance <= threshold:
                    result.pairs.append(DuplicatePair(other_path, path, distance))
            for bucket, key in zip(buckets, keys):
                bucket.setdefault(key, []).append(len(hashed))
            hashed.append((path, value))
        if progress:
            progress(number, len(paths))
    return result


class KeepChoice(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"


@dataclass
class DeduplicationSession:
    pairs: list[DuplicatePair]
    decisions: dict[int, KeepChoice] = field(default_factory=dict)

    def review_state(self) -> tuple[list[int], set[Path], set[int]]:
        """Replay decisions in pair order; retain skipped choices for revisions."""
        deleted: set[Path] = set()
        applied: set[int] = set()
        for index, pair in enumerate(self.pairs):
            if pair.left in deleted or pair.right in deleted:
                continue
            choice = self.decisions.get(index)
            if choice is None:
                continue
            applied.add(index)
            if choice == KeepChoice.LEFT:
                deleted.add(pair.right)
            elif choice == KeepChoice.RIGHT:
                deleted.add(pair.left)
        # Decided pairs remain accessible so their own deletion can be undone.
        visible = [
            index for index, pair in enumerate(self.pairs)
            if index in applied or (pair.left not in deleted and pair.right not in deleted)
        ]
        return visible, deleted, applied

    @property
    def pending_indices(self) -> list[int]:
        visible, _, applied = self.review_state()
        return [index for index in visible if index not in applied]
