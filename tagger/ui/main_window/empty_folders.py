from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

from tagger.settings.preferences import (
    REMOVE_EMPTY_FOLDER_ALWAYS,
    REMOVE_EMPTY_FOLDER_ASK,
    get_remove_empty_folder_behavior,
)
from tagger.settings.store import JsonSettings
from tagger.trash import remove_empty_folder


def maybe_remove_empty_folder(
    folder: Path,
    *,
    root_directory: Path,
    settings: JsonSettings,
    parent: QWidget,
) -> bool:
    """Remove a deleted image's now-empty subfolder according to settings."""
    try:
        if folder.absolute() == root_directory.absolute():
            return False
    except OSError:
        if folder == root_directory:
            return False

    behavior = get_remove_empty_folder_behavior(settings)
    if behavior not in {REMOVE_EMPTY_FOLDER_ALWAYS, REMOVE_EMPTY_FOLDER_ASK}:
        return False

    try:
        is_empty = folder.is_dir() and not any(folder.iterdir())
    except OSError:
        return False
    if not is_empty:
        return False

    if behavior == REMOVE_EMPTY_FOLDER_ASK:
        answer = QMessageBox.question(
            parent,
            "Remove Empty Folder?",
            f"The folder is now empty:\n{folder}\n\nRemove it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

    try:
        return remove_empty_folder(folder)
    except OSError:
        return False
