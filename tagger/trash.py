from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import QFile


SYSTEM_RECYCLE_BIN = "system_recycle_bin"
UNLINK = "unlink"
DELETION_BEHAVIORS = {SYSTEM_RECYCLE_BIN, UNLINK}


def move_to_trash(path: Path) -> bool:
    """Move a file to the platform Trash using Qt's instance API."""
    trash_file = QFile(str(path))
    move = cast(Callable[[], bool], trash_file.moveToTrash)
    return move()


def delete_file(path: Path, behavior: str) -> bool:
    if behavior == SYSTEM_RECYCLE_BIN:
        return move_to_trash(path)
    if behavior == UNLINK:
        path.unlink()
        return True
    raise ValueError(f"Unsupported deletion behavior: {behavior}")
