from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QModelIndex, QSignalBlocker
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QFileDialog, QMessageBox

from tagger.settings.preferences import OPEN_RECENT_FOLDER_ON_STARTUP_SETTING
from tagger.storage import scan_folder


if TYPE_CHECKING:
    from .window import MainWindow


RECENT_FOLDERS_SETTING = "recent_folders"
MAX_RECENT_FOLDERS = 10


class FolderController:
    """Load folders into the window and manage its recent-folder history."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    def _supported_extensions(self) -> set[str]:
        return {
            "."
            + bytes(image_format.data()).decode("ascii", errors="ignore").casefold()
            for image_format in QImageReader.supportedImageFormats()
        }

    def open_folder(self) -> None:
        recent_folders = self._recent_folders()
        start = str(recent_folders[0]) if recent_folders else ""
        selected = QFileDialog.getExistingDirectory(
            self.window, "Open Image Folder", start
        )
        if selected:
            self._load_directory(Path(selected), show_issues=True)

    def open_recent_folder(self, directory: Path) -> None:
        if not directory.is_dir():
            self._update_recent_folder_menu()
            return
        self._load_directory(directory, show_issues=True)

    def _recent_folders(self) -> list[Path]:
        value = self.window.settings.value(RECENT_FOLDERS_SETTING, [])
        if not isinstance(value, list):
            return []
        folders: list[Path] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                continue
            folder = Path(item).expanduser()
            if folder.is_dir() and folder not in folders:
                folders.append(folder)
        return folders[:MAX_RECENT_FOLDERS]

    def _open_recent_folder_on_startup(self) -> None:
        enabled = cast(
            bool,
            self.window.settings.value(
                OPEN_RECENT_FOLDER_ON_STARTUP_SETTING,
                False,
                type=bool,
            ),
        )
        folders = self._recent_folders() if enabled else []
        if folders:
            self._load_directory(folders[0], show_issues=True)

    def _record_recent_folder(self, directory: Path) -> None:
        folders = [
            folder for folder in self._recent_folders() if folder != directory
        ]
        folders.insert(0, directory)
        self.window.settings.setValue(
            RECENT_FOLDERS_SETTING,
            [str(folder) for folder in folders[:MAX_RECENT_FOLDERS]],
        )
        self.window.commands.open_recent_action.setEnabled(True)

    def _update_recent_folder_menu(self) -> None:
        folders = self._recent_folders()
        self.window.commands.open_recent_menu.clear()
        for folder in folders:
            action = self.window.commands.open_recent_menu.addAction(str(folder))
            action.setToolTip(str(folder))
            action.triggered.connect(
                lambda _checked=False, path=folder: self.open_recent_folder(path)
            )
        self.window.commands.open_recent_action.setEnabled(bool(folders))
        self.window.commands.open_recent_action.setToolTip(
            "Open a recently used folder."
            if folders
            else "No recently opened folder is available."
        )

    def close_folder(self) -> None:
        if self.window.directory is None:
            return

        self.window.directory = None
        self.window.preview_loader.clear()
        self.window.image_list.clearSelection()
        self.window.image_list.setCurrentIndex(QModelIndex())
        self.window.catalog.set_entries([])
        self.window.tag_library.clear_folder_tags()
        self.window.image_view.clear_image("Open a folder to begin")
        self.window._set_image_info(None)
        self.window.tag_list.clear()
        self.window.tag_input.clear()
        self.window.search_input.clear()
        self.window.statusBar().clearMessage()
        self.window._update_window_title()
        self.window.commands._update_action_states()

    def rescan(self) -> None:
        if self.window.directory is None:
            return
        current = self.window._current_entry()
        self._load_directory(
            self.window.directory,
            preferred_image=current.image_path if current else None,
            show_issues=True,
        )

    def _load_directory(
        self,
        directory: Path,
        preferred_image: Path | None = None,
        *,
        show_issues: bool,
    ) -> None:
        try:
            result = scan_folder(directory, self._supported_extensions())
        except OSError as exc:
            QMessageBox.critical(self.window, "Could Not Open Folder", str(exc))
            return

        self.window.directory = directory
        self.window._update_window_title()
        self._record_recent_folder(directory)
        selection_model = self.window.image_list.selectionModel()
        selection_blocker = QSignalBlocker(selection_model)
        try:
            self.window.catalog.set_entries(result.entries, directory)
            self.window.image_list.setCurrentIndex(QModelIndex())
        finally:
            selection_blocker.unblock()
        self.window.tag_library.set_folder_entries(result.entries)
        self.window.image_list.expandAll()

        row = (
            self.window.catalog.row_for_image(preferred_image)
            if preferred_image is not None
            else None
        )
        if row is None and result.entries:
            row = self.window.catalog.first_image_row()
        if row is not None:
            self.window._select_row(row)
        else:
            self.window.image_list.clearSelection()
            self.window.preview_loader.clear()
            self.window.image_view.clear_image("No supported images found")
            self.window._set_image_info(None)
            self.window.tag_list.clear()

        self.window.commands._update_action_states()
        self.window.statusBar().showMessage(
            f"{directory} - {len(result.entries)} image(s), "
            f"{len(result.issues)} issue(s)"
        )
        if show_issues and result.issues:
            messages = [issue.message for issue in result.issues[:12]]
            if len(result.issues) > 12:
                messages.append(f"...and {len(result.issues) - 12} more issue(s).")
            QMessageBox.warning(
                self.window, "Folder Scan Issues", "\n".join(messages)
            )
