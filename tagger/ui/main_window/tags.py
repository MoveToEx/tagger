from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QMenu, QMessageBox

from tagger.domain.models import TagOperation
from tagger.domain.tags import apply_tag_operation, normalize_tags, parse_requested_tags
from tagger.storage import (
    BatchPreflightError,
    ExternalChangeError,
    WriteRequest,
    write_tags_atomic,
    write_tags_batch,
)


if TYPE_CHECKING:
    from .window import MainWindow


class TagEditor:
    """Edit current tags and apply folder-wide normalization."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    def _requested_from_input(self) -> list[str] | None:
        try:
            return parse_requested_tags(self.window.tag_input.text())
        except ValueError as exc:
            self.window.statusBar().showMessage(str(exc), 4000)
            self.window.tag_input.setFocus()
            return None

    def _add_current_tags(self) -> None:
        requested = self._requested_from_input()
        if requested is not None:
            self._apply_current_operation(TagOperation.ADD, requested)

    def _delete_selected_tags(self) -> None:
        requested = [item.text() for item in self.window.tag_list.selectedItems()]
        if not requested:
            self.window.statusBar().showMessage("Select one or more tags to delete.", 4000)
            return
        entry = self.window._current_entry()
        if entry is None or not entry.editable:
            return
        answer = QMessageBox.question(
            self.window,
            "Delete Selected Tags?",
            f"Delete {len(requested)} selected tag(s) from "
            f"{entry.image_path.name}?\n\n{', '.join(requested)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._apply_current_operation(TagOperation.DELETE, requested)

    def _selected_tag_text(self) -> str:
        return ", ".join(
            self.window.tag_list.item(row).text()
            for row in range(self.window.tag_list.count())
            if self.window.tag_list.item(row).isSelected()
        )

    def _copy_selected_tags(self) -> None:
        selected = self._selected_tag_text()
        if not selected:
            return
        QGuiApplication.clipboard().setText(selected)
        self.window.statusBar().showMessage("Copied selected tags.", 3000)

    def _show_tag_context_menu(self, position) -> None:
        item = self.window.tag_list.itemAt(position)
        if item is not None and not item.isSelected():
            self.window.tag_list.clearSelection()
            item.setSelected(True)

        menu = self._create_tag_context_menu()
        menu.exec(self.window.tag_list.viewport().mapToGlobal(position))

    def _create_tag_context_menu(self) -> QMenu:
        copy_action = QAction("Copy", self.window)
        copy_action.setEnabled(bool(self._selected_tag_text()))
        copy_action.triggered.connect(self._copy_selected_tags)
        delete_action = QAction("Delete", self.window)
        delete_action.setEnabled(bool(self.window.tag_list.selectedItems()))
        delete_action.triggered.connect(self._delete_selected_tags)
        menu = QMenu(self.window)
        menu.addAction(copy_action)
        menu.addAction(delete_action)
        menu.addSeparator()
        send_to_menu = QMenu("Send to", menu)
        menu.addMenu(send_to_menu)
        selected_tags = [
            self.window.tag_list.item(row).text()
            for row in range(self.window.tag_list.count())
            if self.window.tag_list.item(row).isSelected()
        ]
        send_to_menu.setEnabled(bool(selected_tags))
        for operation, label in (
            (TagOperation.ADD, "Add tags"),
            (TagOperation.DELETE, "Delete tags"),
            (TagOperation.TOGGLE, "Toggle tags"),
        ):
            action = send_to_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, op=operation: self.window.dialogs._start_traversal(
                    op, requested_tags=selected_tags
                )
            )
        search_action = send_to_menu.addAction("Global search")
        search_action.setEnabled(len(selected_tags) == 1)
        search_action.triggered.connect(
            lambda: self.window.dialogs._open_global_search(initial_pattern=selected_tags[0])
        )
        return menu

    def _apply_current_operation(
        self, operation: TagOperation, requested_tags: list[str]
    ) -> None:
        row = self.window.catalog.row_for_index(self.window.image_list.currentIndex())
        entry = self.window.catalog.entry(row) if row is not None else None
        if row is None or entry is None or not entry.editable:
            return

        result = apply_tag_operation(entry.tags, requested_tags, operation)
        if result == entry.tags:
            self.window.statusBar().showMessage("No tag changes were needed.", 3000)
            return
        try:
            new_bytes = write_tags_atomic(
                entry.tag_path, result, expected_bytes=entry.source_bytes
            )
        except (OSError, ExternalChangeError) as exc:
            QMessageBox.critical(self.window, "Could Not Save Tags", str(exc))
            return

        entry.tags = result
        entry.source_bytes = new_bytes
        self.window.catalog.notify_entry_changed(row)
        self.window.tag_list.clear()
        self.window.tag_list.addItems(result)
        self.window.tag_input.clear()
        self.window.statusBar().showMessage(f"Saved {entry.tag_path.name}", 3000)

    def _normalize_all_tags(self) -> None:
        editable_entries = [entry for entry in self.window.catalog.entries if entry.editable]
        if not editable_entries:
            QMessageBox.information(
                self.window,
                "No Editable Images",
                "Open a folder with editable image tags first.",
            )
            return

        changes = [
            (entry, normalized)
            for entry in editable_entries
            if (normalized := normalize_tags(entry.tags)) != entry.tags
        ]
        if not changes:
            QMessageBox.information(
                self.window,
                "Tags Already Normalized",
                "All editable image tags are already normalized.",
            )
            return

        answer = QMessageBox.question(
            self.window,
            "Normalize All Tags?",
            "This will normalize tags on all "
            f"{len(editable_entries)} editable image(s) in the open folder.\n\n"
            f"{len(changes)} sidecar file(s) will change.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        requests = [
            WriteRequest(
                path=entry.tag_path,
                tags=normalized,
                expected_bytes=entry.source_bytes,
            )
            for entry, normalized in changes
        ]
        try:
            result = write_tags_batch(requests)
        except BatchPreflightError as exc:
            QMessageBox.critical(self.window, "Could Not Normalize Tags", str(exc))
            return

        current = self.window._current_entry()
        if self.window.directory is not None:
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )
        if result.failures:
            details = "\n".join(
                f"{path.name}: {message}"
                for path, message in result.failures.items()
            )
            QMessageBox.warning(
                self.window,
                "Some Files Were Not Normalized",
                f"Normalized {len(result.succeeded)} file(s).\n\n{details}",
            )
        else:
            self.window.statusBar().showMessage(
                f"Normalized tags in {len(result.succeeded)} file(s).", 4000
            )
