from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, QProcess
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMenu, QMessageBox

from tagger.settings.preferences import (
    USE_UNLINK_FOR_MANUAL_DELETE_SETTING,
    USE_UNLINK_FOR_TIDY_SETTING,
    get_deletion_behavior,
)
from tagger.storage import find_unrecognized_files, rename_image_pair
from tagger.trash import UNLINK, delete_file
from tagger.ui.dialogs.archive import ArchiveProgressDialog


if TYPE_CHECKING:
    from .window import MainWindow


class FileActions:
    """Run image file operations and own the active archive dialog."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window
        self._archive_dialog: ArchiveProgressDialog | None = None
        self._archive_destination: Path | None = None

    def _tidy_folder(self) -> None:
        directory = self.window.directory
        if directory is None:
            return

        try:
            candidates = find_unrecognized_files(
                directory, self.window.folders._supported_extensions()
            )
        except OSError as exc:
            QMessageBox.critical(self.window, "Could Not Tidy Folder", str(exc))
            return

        if not candidates:
            self.window.statusBar().showMessage("Folder is already tidy.", 4000)
            return

        deletion_behavior = get_deletion_behavior(
            self.window.settings, USE_UNLINK_FOR_TIDY_SETTING
        )
        deleting_permanently = deletion_behavior == UNLINK
        count = len(candidates)
        answer = QMessageBox.question(
            self.window,
            (
                "Permanently Delete Unrecognized Files?"
                if deleting_permanently
                else "Delete Unrecognized Files?"
            ),
            (
                f"Permanently delete {count} unrecognized file(s)?\n\n"
                "This cannot be undone."
                if deleting_permanently
                else (
                    f"Move {count} unrecognized file(s) to the system "
                    "Recycle Bin?"
                )
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        deleted: list[Path] = []
        failures: list[str] = []
        for path in candidates:
            try:
                succeeded = delete_file(path, deletion_behavior)
            except OSError as exc:
                failures.append(f"Could not delete {path.name}: {exc}")
                continue
            if succeeded:
                deleted.append(path)
            else:
                destination = (
                    "permanently" if deleting_permanently else "to Recycle Bin"
                )
                failures.append(f"Could not delete {path.name} {destination}.")

        if deleted:
            current = self.window._current_entry()
            self.window.folders._load_directory(
                directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )

        if failures:
            QMessageBox.warning(
                self.window,
                "Could Not Tidy All Files",
                "\n".join(failures),
            )
        elif deleted:
            action = (
                "Permanently deleted"
                if deleting_permanently
                else "Moved to Recycle Bin"
            )
            self.window.statusBar().showMessage(
                f"{action} {len(deleted)} unrecognized file(s).", 4000
            )

    def _archive_folder(self) -> None:
        if not self.window.catalog.entries:
            return
        directory = self.window.directory
        start = (
            directory / f"{directory.name}.zip"
            if directory is not None
            else Path("images.zip")
        )
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self.window,
            "Archive Image and Tag Pairs",
            str(start),
            "Zip archives (*.zip)",
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.casefold() != ".zip":
            destination = Path(f"{destination}.zip")
        dialog = ArchiveProgressDialog(
            list(self.window.catalog.entries), destination, self.window
        )
        dialog.completed.connect(self._archive_completed)
        dialog.failed.connect(self._archive_failed)
        self._archive_dialog = dialog
        self._archive_destination = destination
        self.window.commands._update_action_states()
        dialog.show()
        dialog.start()

    def _archive_completed(self, archived_count: int) -> None:
        destination = self._archive_destination
        self._archive_dialog = None
        self._archive_destination = None
        self.window.commands._update_action_states()
        self.window.statusBar().showMessage(
            f"Archived {archived_count} image/tag pair(s) to {destination}.",
            5000,
        )

    def _archive_failed(self, message: str) -> None:
        self._archive_dialog = None
        self._archive_destination = None
        self.window.commands._update_action_states()
        QMessageBox.critical(self.window, "Could Not Create Archive", message)

    def _show_image_context_menu(self, position) -> None:
        index = self.window.image_list.indexAt(position)
        entry = self.window.catalog.entry_for_index(index)
        if entry is None:
            return

        self.window.image_list.setCurrentIndex(index)
        self.window.image_list.selectionModel().select(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        menu = self._create_image_context_menu()
        menu.exec(self.window.image_list.viewport().mapToGlobal(position))

    def _create_image_context_menu(self) -> QMenu:
        has_entry = self.window._current_entry() is not None and self.window.directory is not None
        reveal_action = QAction("Reveal in Explorer", self.window)
        reveal_action.setEnabled(has_entry)
        reveal_action.triggered.connect(self._reveal_current_image_in_explorer)
        rename_action = QAction("Rename...", self.window)
        rename_action.setEnabled(has_entry)
        rename_action.triggered.connect(self._rename_current_image_and_tag)
        delete_action = QAction("Delete", self.window)
        delete_action.setEnabled(has_entry)
        delete_action.triggered.connect(self._delete_current_image_and_tag)
        menu = QMenu(self.window)
        menu.addAction(rename_action)
        menu.addAction(delete_action)
        menu.addSeparator()
        menu.addAction(reveal_action)
        return menu

    def _reveal_current_image_in_explorer(self) -> None:
        entry = self.window._current_entry()
        if entry is None:
            return

        started, _process_id = QProcess.startDetached(
            "explorer.exe",
            ["/select,", str(entry.image_path)],
        )
        if not started:
            QMessageBox.critical(
                self.window,
                "Could Not Open File Explorer",
                f"Could not reveal {entry.image_path.name} in File Explorer.",
            )

    def _rename_current_image_and_tag(self) -> None:
        entry = self.window._current_entry()
        directory = self.window.directory
        if entry is None or directory is None:
            return

        new_stem, accepted = QInputDialog.getText(
            self.window,
            "Rename Image and Tag",
            "New base name:",
            QLineEdit.EchoMode.Normal,
            entry.image_path.stem,
        )
        if not accepted:
            return
        new_stem = new_stem.strip()
        if new_stem == entry.image_path.stem:
            return

        self.window.preview_loader.clear()
        self.window.preview_loader.wait_for_done()
        try:
            new_image_path, new_tag_path = rename_image_pair(entry, new_stem)
        except (OSError, ValueError) as exc:
            self.window.folders._load_directory(
                directory,
                preferred_image=entry.image_path,
                show_issues=False,
            )
            QMessageBox.critical(
                self.window,
                "Could Not Rename Image and Tag",
                str(exc),
            )
            return

        self.window.folders._load_directory(
            directory,
            preferred_image=new_image_path,
            show_issues=False,
        )
        self.window.statusBar().showMessage(
            f"Renamed pair to {new_image_path.name} and {new_tag_path.name}.",
            4000,
        )

    def _delete_current_image_and_tag(self) -> None:
        row = self.window.catalog.row_for_index(self.window.image_list.currentIndex())
        entry = self.window.catalog.entry(row) if row is not None else None
        if row is None or entry is None or self.window.directory is None:
            return

        deletion_behavior = get_deletion_behavior(
            self.window.settings, USE_UNLINK_FOR_MANUAL_DELETE_SETTING
        )
        deleting_permanently = deletion_behavior == UNLINK
        answer = QMessageBox.question(
            self.window,
            (
                "Permanently Delete Image and Tag?"
                if deleting_permanently
                else "Delete Image and Tag?"
            ),
            (
                "Permanently delete both files?\n\n"
                if deleting_permanently
                else "Move both files to the system Recycle Bin?\n\n"
            )
            + f"Image: {entry.image_path.name}\n"
            + f"Tag: {entry.tag_path.name}"
            + ("\n\nThis cannot be undone." if deleting_permanently else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        preferred = self.window.catalog.entry(row + 1)
        if preferred is None:
            preferred = self.window.catalog.entry(row - 1)
        preferred_path = preferred.image_path if preferred is not None else None

        self.window.preview_loader.clear()
        self.window.preview_loader.wait_for_done()
        deleted: list[Path] = []
        failures: list[str] = []

        def delete_path(path: Path) -> bool:
            try:
                succeeded = delete_file(path, deletion_behavior)
            except OSError as exc:
                failures.append(f"Could not delete {path.name}: {exc}")
                return False
            if not succeeded:
                destination = (
                    "permanently" if deleting_permanently else "to Recycle Bin"
                )
                failures.append(f"Could not delete {path.name} {destination}.")
            return succeeded

        image_deleted = delete_path(entry.image_path)
        if image_deleted:
            deleted.append(entry.image_path)
            if entry.tag_path.exists():
                if delete_path(entry.tag_path):
                    deleted.append(entry.tag_path)

        if deleted:
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=preferred_path,
                show_issues=False,
            )
        if failures:
            QMessageBox.warning(
                self.window,
                "Could Not Delete All Files",
                "\n".join(failures),
            )
        elif deleted:
            action = (
                "Permanently deleted"
                if deleting_permanently
                else "Moved to Recycle Bin"
            )
            self.window.statusBar().showMessage(
                f"{action}: {entry.image_path.name} and {entry.tag_path.name}.",
                4000,
            )
