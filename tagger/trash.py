from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import QFile


def move_to_trash(path: Path) -> bool:
    """Move a file to the platform Trash using Qt's instance API."""
    trash_file = QFile(str(path))
    move = cast(Callable[[], bool], trash_file.moveToTrash)
    return move()
