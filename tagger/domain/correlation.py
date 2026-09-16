from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tagger.domain.models import ImageEntry


@dataclass(frozen=True)
class TagCorrelation:
    """Counts for a tag split by whether the query tag is present."""

    tag: str
    positive: int
    negative: int

    @property
    def total(self) -> int:
        return self.positive + self.negative

    @property
    def positive_rate(self) -> float:
        return self.positive / self.total if self.total else 0.0


def analyze_tag_correlations(
    entries: Sequence[ImageEntry], query_tag: str
) -> list[TagCorrelation]:
    """Return tag occurrence counts grouped by presence of *query_tag*.

    Each image contributes at most once to a tag count, even if an entry was
    constructed with duplicate tag values. The query tag itself is omitted
    because it is the grouping criterion rather than a useful correlation.
    Results are sorted by total occurrence and then tag name, making the most
    common correlations appear first while keeping ties deterministic.
    """
    query = query_tag.strip()
    if not query:
        return []

    positive_tags: list[set[str]] = []
    negative_tags: list[set[str]] = []
    for entry in entries:
        tags = {tag.strip() for tag in entry.tags if tag.strip()}
        if query in tags:
            positive_tags.append(tags)
        else:
            negative_tags.append(tags)

    candidates = {
        tag
        for tags in [*positive_tags, *negative_tags]
        for tag in tags
        if tag != query
    }
    correlations = [
        TagCorrelation(
            tag=tag,
            positive=sum(tag in tags for tags in positive_tags),
            negative=sum(tag in tags for tags in negative_tags),
        )
        for tag in candidates
    ]
    return sorted(
        correlations,
        key=lambda result: (
            -result.total,
            -result.positive,
            result.tag.casefold(),
            result.tag,
        ),
    )
