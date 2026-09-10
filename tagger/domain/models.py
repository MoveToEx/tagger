from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class TagOperation(StrEnum):
    ADD = "add"
    DELETE = "delete"
    TOGGLE = "toggle"
    NORMALIZE = "normalize"


@dataclass
class ImageEntry:
    image_path: Path
    tag_path: Path
    tags: list[str] = field(default_factory=list)
    source_bytes: bytes | None = None
    warnings: tuple[str, ...] = ()
    error: str | None = None

    @property
    def editable(self) -> bool:
        return self.error is None and self.source_bytes is not None


@dataclass(frozen=True)
class ScanIssue:
    message: str
    paths: tuple[Path, ...] = ()


@dataclass
class ScanResult:
    entries: list[ImageEntry] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)
