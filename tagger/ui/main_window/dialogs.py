from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QMessageBox

from tagger.ai_tagging.dependencies import ai_dependencies_available
from tagger.ai_tagging.dialog import AITaggingDialog
from tagger.domain.models import TagOperation
from tagger.settings.dialog import SettingsDialog
from tagger.settings.preferences import (
    USE_UNLINK_FOR_DEDUPLICATE_SETTING,
    USE_UNLINK_FOR_DELETE_FILTER_SETTING,
    get_deletion_behavior,
    get_image_prefetch_count,
)
from tagger.settings.proxy import get_download_proxy
from tagger.trash import UNLINK, delete_file
from tagger.ui.dialogs.bulk_operation import BulkOperationDialog
from tagger.ui.dialogs.complex_filter import ComplexFilterDialog
from tagger.ui.dialogs.deduplicate import DeduplicateDialog
from tagger.ui.dialogs.delete_filter import DeleteFilterDialog
from tagger.ui.dialogs.global_search import GlobalTagSearchDialog
from tagger.ui.dialogs.review import ReviewDialog
from tagger.ui.dialogs.traversal import TraversalDialog


if TYPE_CHECKING:
    from .window import MainWindow


class DialogController:
    """Launch feature dialogs and refresh the catalog after committed changes."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window
        self._complex_filter_dialog: ComplexFilterDialog | None = None

    def _open_global_search(self, *, initial_pattern: str = "") -> None:
        if not self.window.catalog.entries:
            return
        GlobalTagSearchDialog(
            self.window.catalog.entries,
            self.window,
            tag_library=self.window.tag_library,
            initial_pattern=initial_pattern,
        ).exec()

    def _open_review(self) -> None:
        if not self.window.catalog.entries or self.window.directory is None:
            return
        dialog = ReviewDialog(
            self.window.catalog.entries,
            self.window,
            root_directory=self.window.directory,
            tag_library=self.window.tag_library,
            image_prefetch_count=get_image_prefetch_count(self.window.settings),
        )
        if dialog.exec() == ReviewDialog.DialogCode.Accepted and dialog.commit_result:
            current = self.window._current_entry()
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )

    def _open_delete_filter(self) -> None:
        if not self.window.catalog.entries or self.window.directory is None:
            return
        current = self.window._current_entry()
        deletion_behavior = get_deletion_behavior(
            self.window.settings, USE_UNLINK_FOR_DELETE_FILTER_SETTING
        )
        dialog = DeleteFilterDialog(
            self.window.catalog.entries,
            self.window,
            file_deleter=lambda path: delete_file(path, deletion_behavior),
            deletion_behavior=deletion_behavior,
            image_prefetch_count=get_image_prefetch_count(self.window.settings),
        )
        if (
            dialog.exec() == DeleteFilterDialog.DialogCode.Accepted
            and dialog.commit_result is not None
        ):
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )
            deleted_count = len(dialog.commit_result.deleted_images)
            if deleted_count:
                action = (
                    "Permanently deleted"
                    if deletion_behavior == UNLINK
                    else "Moved to Recycle Bin"
                )
                self.window.statusBar().showMessage(
                    f"{action} {deleted_count} marked image(s).",
                    4000,
                )

    def _open_deduplicate(self) -> None:
        if self.window.directory is None or len(self.window.catalog.entries) < 2:
            return
        current = self.window._current_entry()
        deletion_behavior = get_deletion_behavior(
            self.window.settings, USE_UNLINK_FOR_DEDUPLICATE_SETTING
        )
        dialog = DeduplicateDialog(
            self.window.catalog.entries,
            self.window,
            root_directory=self.window.directory,
            deletion_behavior=deletion_behavior,
        )
        if (
            dialog.exec() == DeduplicateDialog.DialogCode.Accepted
            and dialog.commit_result is not None
        ):
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )
            action = (
                "Permanently deleted"
                if deletion_behavior == UNLINK else "Moved to Recycle Bin"
            )
            self.window.statusBar().showMessage(
                f"{action} {len(dialog.commit_result.deleted_images)} duplicate image(s).",
                4000,
            )

    def _open_complex_filter(self) -> None:
        if not self.window.catalog.entries:
            return
        if self._complex_filter_dialog is not None:
            self._complex_filter_dialog.show()
            self._complex_filter_dialog.raise_()
            self._complex_filter_dialog.activateWindow()
            return

        dialog = ComplexFilterDialog(
            self.window.catalog.entries,
            self.window,
            root_directory=self.window.directory,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowFlag(Qt.WindowType.Window, True)
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.image_activated.connect(self._select_image_from_complex_filter)
        dialog.destroyed.connect(self._complex_filter_destroyed)
        self._complex_filter_dialog = dialog
        dialog.show()

    def _open_bulk_operation(self) -> None:
        if self.window.directory is None:
            return
        editable_entries = [
            entry for entry in self.window.catalog.entries if entry.editable
        ]
        if not editable_entries:
            return
        current = self.window._current_entry()
        dialog = BulkOperationDialog(
            editable_entries,
            self.window,
            root_directory=self.window.directory,
            tag_library=self.window.tag_library,
            image_prefetch_count=get_image_prefetch_count(self.window.settings),
        )
        if (
            dialog.exec() == BulkOperationDialog.DialogCode.Accepted
            and self.window.directory is not None
        ):
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self.window,
            settings=self.window.settings,
            tag_library=self.window.tag_library,
        )
        dialog.scrolling_behavior_changed.connect(
            self.window.image_view.set_scrolling_behavior
        )
        dialog.catalog_click_hold_behavior_changed.connect(
            self.window.image_list.set_click_hold_behavior
        )
        dialog.exec()

    def _open_ai_tagging(
        self, *, initial_image_path: Path | None = None
    ) -> None:
        if not ai_dependencies_available() or self.window.directory is None:
            return
        editable_entries = [
            entry for entry in self.window.catalog.entries if entry.editable
        ]
        if not editable_entries:
            return
        if initial_image_path is not None and all(
            entry.image_path != initial_image_path for entry in editable_entries
        ):
            return
        current = self.window._current_entry()
        dialog = AITaggingDialog(
            editable_entries,
            self.window,
            root_directory=self.window.directory,
            proxy=get_download_proxy(self.window.settings),
            image_prefetch_count=get_image_prefetch_count(self.window.settings),
            initial_image_path=initial_image_path,
        )
        if dialog.exec() == AITaggingDialog.DialogCode.Accepted:
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )

    def _complex_filter_destroyed(self, _object: QObject) -> None:
        self._complex_filter_dialog = None

    def _select_image_from_complex_filter(self, image_path: Path) -> None:
        row = self.window.catalog.row_for_image(image_path)
        self.window._select_optional_row(row)

    def _start_traversal(
        self, operation: TagOperation, *, requested_tags: list[str] | None = None
    ) -> None:
        if operation == TagOperation.NORMALIZE:
            raise ValueError("Normalization is not a traversal operation.")
        editable_entries = [entry for entry in self.window.catalog.entries if entry.editable]
        if not editable_entries:
            QMessageBox.information(
                self.window, "No Editable Images", "Open a folder with editable image tags first."
            )
            return

        current = self.window._current_entry()
        dialog = TraversalDialog(
            editable_entries,
            operation,
            requested_tags=requested_tags,
            parent=self.window,
            root_directory=self.window.directory,
            tag_library=self.window.tag_library,
            image_prefetch_count=get_image_prefetch_count(self.window.settings),
        )
        if dialog.exec() == TraversalDialog.DialogCode.Accepted and self.window.directory:
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )
