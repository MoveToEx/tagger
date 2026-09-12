from __future__ import annotations

from collections.abc import Generator, Iterable
import re


TagMatch = tuple[str, list[str]] | tuple[str, str]


class TagSet(set[str]):
    """A set of tags whose membership checks accept ``*`` patterns."""

    def __init__(self, tags: Iterable[str] = ()) -> None:
        super().__init__(tags)

    def __contains__(self, pattern: object) -> bool:
        if not isinstance(pattern, str) or not pattern:
            return False
        return any(
            self._match_tag(tag, pattern) is not None
            for tag in set.__iter__(self)
        )

    def matching(self, pattern: str) -> Generator[TagMatch, None, None]:
        """Yield each tag matching ``pattern`` and its wildcard captures.

        A pattern with one wildcard returns its capture as a string. Patterns
        with zero or multiple wildcards return a list of captures.
        """
        if not pattern:
            return
        for tag in set.__iter__(self):
            captures = self._match_tag(tag, pattern)
            if captures is None:
                continue
            if pattern.count("*") == 1:
                yield tag, captures[0]
            else:
                yield tag, captures

    def matches(self, pattern: str) -> Generator[TagMatch, None, None]:
        """Alias for :meth:`matching` for concise scripts."""
        yield from self.matching(pattern)

    def match(self, pattern: str) -> Generator[TagMatch, None, None]:
        """Alias for :meth:`matching`."""
        yield from self.matching(pattern)

    def iter_matching(self, pattern: str) -> Generator[TagMatch, None, None]:
        """Alias for :meth:`matching` emphasizing lazy iteration."""
        yield from self.matching(pattern)

    def find(self, pattern: str) -> Generator[TagMatch, None, None]:
        """Alias for :meth:`matching`."""
        yield from self.matching(pattern)

    def _match_tag(self, tag: str, pattern: str) -> list[str] | None:
        if not isinstance(tag, str):
            return None
        parts = pattern.split("*")
        expression = "(.*)".join(re.escape(part) for part in parts)
        match = re.fullmatch(expression, tag, flags=re.DOTALL)
        return list(match.groups()) if match is not None else None
