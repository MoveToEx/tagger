from __future__ import annotations

from pathlib import Path
from random import Random

from PIL import Image
import pytest

import tagger.deduplication as deduplication
from tagger.deduplication import (
    DeduplicationSession,
    DuplicatePair,
    KeepChoice,
    find_duplicate_pairs,
)


@pytest.mark.parametrize("threshold", [0, 1, 2, 4])
def test_hash_matching_matches_exhaustive_search(threshold: int, monkeypatch) -> None:
    random = Random(42)
    values = [random.getrandbits(64) for _ in range(20)]
    values += [value ^ ((1 << bits) - 1) for value in values for bits in range(6)]
    paths = [Path(f"{index}.png") for index in range(len(values))]
    hashes = dict(zip(paths, values))
    calls = []

    def hash_image(path: Path) -> int:
        calls.append(path)
        return hashes[path]

    monkeypatch.setattr(deduplication, "perceptual_hash", hash_image)
    result = find_duplicate_pairs(paths + paths[:1], threshold)
    expected = {
        (left, right, (hashes[left] ^ hashes[right]).bit_count())
        for index, right in enumerate(paths)
        for left in paths[:index]
        if (hashes[left] ^ hashes[right]).bit_count() <= threshold
    }
    assert {(pair.left, pair.right, pair.distance) for pair in result.pairs} == expected
    assert calls == paths


def test_perceptual_hash_reads_images_and_reports_unreadable_files(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.bmp"
    broken = tmp_path / "broken.png"
    image = Image.new("RGB", (64, 64))
    for x in range(64):
        for y in range(64):
            image.putpixel((x, y), (x * 4, y * 4, (x * y) % 256))
    image.save(first)
    image.save(second)
    broken.write_bytes(b"invalid image")
    progress = []
    result = find_duplicate_pairs(
        [first, broken, second], 0,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert result.pairs == [DuplicatePair(first, second, 0)]
    assert list(result.failures) == [broken]
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_cancelled_scan_does_not_read_images(monkeypatch) -> None:
    def unexpected_hash(path: Path) -> int:
        pytest.fail("Cancelled scan must not read an image")

    monkeypatch.setattr(deduplication, "perceptual_hash", unexpected_hash)
    result = find_duplicate_pairs([Path("a.png")], 0, cancelled=lambda: True)
    assert not result.pairs
    assert not result.failures


def test_decision_revisions_restore_skipped_pairs_without_erasing_choices() -> None:
    a, b, c = map(Path, ["a.png", "b.png", "c.png"])
    session = DeduplicationSession([
        DuplicatePair(a, b, 0), DuplicatePair(a, c, 0), DuplicatePair(b, c, 0),
    ])
    session.decisions[0] = KeepChoice.LEFT
    assert session.pending_indices == [1]
    session.decisions[1] = KeepChoice.RIGHT
    assert session.review_state() == ([0, 1], {a, b}, {0, 1})
    assert session.pending_indices == []
    session.decisions[0] = KeepChoice.RIGHT
    assert session.review_state() == ([0, 2], {a}, {0})
    assert session.decisions[1] == KeepChoice.RIGHT
    assert session.pending_indices == [2]
    session.decisions[0] = KeepChoice.BOTH
    assert session.review_state() == ([0, 1, 2], {a}, {0, 1})
    session.decisions[2] = KeepChoice.BOTH
    assert session.pending_indices == []


def test_undecided_pairs_skip_images_deleted_by_a_later_decision() -> None:
    a, b, c = map(Path, ["a.png", "b.png", "c.png"])
    session = DeduplicationSession([DuplicatePair(a, b, 0), DuplicatePair(b, c, 0)])
    session.decisions[1] = KeepChoice.RIGHT
    assert session.review_state() == ([1], {b}, {1})
    assert session.pending_indices == []
