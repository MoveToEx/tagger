from pathlib import Path

from tagger.domain.correlation import analyze_tag_correlations
from tagger.domain.models import ImageEntry


def test_analyze_tag_correlations_counts_each_image_once() -> None:
    entries = [
        ImageEntry(Path("one.png"), Path("one.txt"), ["query", "cat", "cat"]),
        ImageEntry(Path("two.png"), Path("two.txt"), ["cat", "bird"]),
        ImageEntry(Path("three.png"), Path("three.txt"), ["query", "bird"]),
    ]

    results = analyze_tag_correlations(entries, " query ")

    assert [(result.tag, result.positive, result.negative) for result in results] == [
        ("bird", 1, 1),
        ("cat", 1, 1),
    ]


def test_analyze_tag_correlations_ignores_empty_query() -> None:
    assert analyze_tag_correlations([], " ") == []
