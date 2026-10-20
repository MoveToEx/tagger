from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QMessageBox

from tagger.ai_tagging.dependencies import ai_dependencies_available
from tagger.ai_tagging.dialog import (
    AITaggingProgressDialog,
    AITaggingReviewDialog,
    AITaggingSelectionDialog,
)
from tagger.domain.models import TagOperation
from tagger.probing import (
    ProbeResult,
    ProbeRuleError,
    get_enabled_probe_rules,
    get_probe_minimum_level,
)
from tagger.settings.dialog import SettingsDialog
from tagger.settings.preferences import (
    USE_UNLINK_FOR_DEDUPLICATE_SETTING,
    USE_UNLINK_FOR_DELETE_FILTER_SETTING,
    get_deletion_behavior,
    get_grid_type,
    get_image_prefetch_count,
    get_preprocess_options,
    get_scripting_use_tag_set,
)
from tagger.settings.proxy import get_download_proxy
from tagger.trash import UNLINK, delete_file
from tagger.ui.dialogs.bulk_operation import BulkOperationDialog
from tagger.ui.dialogs.complex_filter import ComplexFilterDialog
from tagger.ui.dialogs.correlation_analysis import CorrelationAnalysisDialog
from tagger.ui.dialogs.crop import CropDialog, CropSelectionDialog
from tagger.ui.dialogs.deduplicate import DeduplicateDialog
from tagger.ui.dialogs.delete_filter import DeleteFilterDialog
from tagger.ui.dialogs.global_search import GlobalTagSearchDialog
from tagger.ui.dialogs.frame_extraction import (
    FrameExtractionDialog,
    FrameExtractionProgressDialog,
    FrameExtractionVideoDialog,
)
from tagger.ui.dialogs.mask_editor import MaskEditorDialog, MaskSelectionDialog
from tagger.ui.dialogs.review import ReviewDialog
from tagger.ui.dialogs.grid_preview import GridPreviewDialog
from tagger.ui.dialogs.traversal import TraversalDialog
from tagger.ui.dialogs.image_transform import ImageTransformDialog, ConvertProgressDialog
from tagger.ui.dialogs.pixel_transform import PixelTransformDialog
from tagger.ui.dialogs.probe import ProbeDialog, ProbeProgressDialog
from tagger.ui.dialogs.transparency import (
    TransparencyProgressDialog,
    TransparencySelectionDialog,
)
from tagger.ui.main_window.empty_folders import maybe_remove_empty_folder


if TYPE_CHECKING:
    from .window import MainWindow


class DialogController:
    """Launch feature dialogs and refresh the catalog after committed changes."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window
        self._complex_filter_dialog: ComplexFilterDialog | None = None
        self._probe_progress_dialog: ProbeProgressDialog | None = None
        self._probe_dialog: ProbeDialog | None = None
        self._ai_tagging_progress_dialog: AITaggingProgressDialog | None = None
        self._ai_tagging_review_dialog: AITaggingReviewDialog | None = None
        self._frame_extraction_video_dialog: FrameExtractionVideoDialog | None = None
        self._frame_extraction_dialog: FrameExtractionDialog | None = None
        self._frame_extraction_progress_dialog: FrameExtractionProgressDialog | None = None

    def _open_frame_extraction(self) -> None:
        directory = self.window.directory
        if directory is None or any((
            self._frame_extraction_video_dialog,
            self._frame_extraction_dialog,
            self._frame_extraction_progress_dialog,
        )):
            return
        dialog = FrameExtractionVideoDialog(directory, self.window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.finished.connect(partial(self._frame_extraction_video_finished, dialog, directory))
        self._frame_extraction_video_dialog = dialog
        self.window.commands._update_action_states()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _frame_extraction_video_finished(
        self, dialog: FrameExtractionVideoDialog, directory: Path, result: int,
    ) -> None:
        if self._frame_extraction_video_dialog is dialog:
            self._frame_extraction_video_dialog = None
        if result != FrameExtractionVideoDialog.DialogCode.Accepted or dialog.video_path is None:
            self.window.commands._update_action_states()
            return
        review = FrameExtractionDialog(dialog.video_path, directory, self.window)
        review.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        review.finished.connect(partial(self._frame_extraction_review_finished, review, directory))
        self._frame_extraction_dialog = review
        self.window.commands._update_action_states()
        review.show()
        review.raise_()
        review.activateWindow()

    def _frame_extraction_review_finished(
        self, dialog: FrameExtractionDialog, directory: Path, result: int,
    ) -> None:
        if self._frame_extraction_dialog is dialog:
            self._frame_extraction_dialog = None
        if result != FrameExtractionDialog.DialogCode.Accepted or not dialog.selected_frames:
            self.window.commands._update_action_states()
            return
        progress = FrameExtractionProgressDialog(
            dialog.video_path, dialog.selected_frames, directory, self.window,
        )
        progress.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        progress.finished.connect(partial(self._frame_extraction_finished, progress, directory))
        self._frame_extraction_progress_dialog = progress
        self.window.commands._update_action_states()
        progress.show()
        progress.start()

    def _frame_extraction_finished(
        self, progress: FrameExtractionProgressDialog, directory: Path, _result: int,
    ) -> None:
        if self._frame_extraction_progress_dialog is progress:
            self._frame_extraction_progress_dialog = None
        self.window.commands._update_action_states()
        result = progress.result_data
        if result.paths and self.window.directory == directory:
            current = self.window._current_entry()
            self.window.folders._load_directory(
                directory,
                preferred_image=current.image_path if current else result.paths[0],
                show_issues=False,
            )
        message = (
            f"Frame extraction cancelled. Kept {len(result.paths)} extracted frame(s)."
            if result.cancelled
            else f"Extracted {len(result.paths)} frame(s) into the root folder."
        )
        self.window.statusBar().showMessage(message, 6000)
        if result.failures:
            QMessageBox.warning(
                self.window, "Frame Extraction Failed",
                f"Saved {len(result.paths)} frame(s).\n\n" + "\n".join(result.failures[:12]),
            )

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
            for image_path in dialog.commit_result.deleted_images:
                maybe_remove_empty_folder(
                    image_path.parent,
                    root_directory=self.window.directory,
                    settings=self.window.settings,
                    parent=self.window,
                )
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
            for image_path in dialog.commit_result.deleted_images:
                maybe_remove_empty_folder(
                    image_path.parent,
                    root_directory=self.window.directory,
                    settings=self.window.settings,
                    parent=self.window,
                )
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
            use_tag_set=get_scripting_use_tag_set(self.window.settings),
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
            use_tag_set=get_scripting_use_tag_set(self.window.settings),
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

    def _open_probe(self) -> None:
        if not self.window.catalog.entries:
            return
        if self._probe_progress_dialog is not None:
            self._probe_progress_dialog.show()
            self._probe_progress_dialog.raise_()
            self._probe_progress_dialog.activateWindow()
            return
        if self._probe_dialog is not None:
            self._probe_dialog.show()
            self._probe_dialog.raise_()
            self._probe_dialog.activateWindow()
            return
        try:
            rules = get_enabled_probe_rules(self.window.settings)
            minimum_level = get_probe_minimum_level(self.window.settings)
        except ProbeRuleError as exc:
            QMessageBox.critical(
                self.window,
                "Could Not Load Probing Rules",
                str(exc),
            )
            return
        if not rules:
            QMessageBox.information(
                self.window,
                "No Probing Rules Enabled",
                "Enable a built-in or user rule in Settings > Tag > Probing.",
            )
            return

        dialog = ProbeProgressDialog(
            list(self.window.catalog.entries),
            rules,
            self.window,
            root_directory=self.window.directory,
            use_tag_set=get_scripting_use_tag_set(self.window.settings),
            minimum_level=minimum_level,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.completed.connect(self._probe_completed)
        dialog.failed.connect(self._probe_failed)
        self._probe_progress_dialog = dialog
        self.window.commands._update_action_states()
        dialog.show()
        dialog.start()

    def _probe_completed(self, value: object) -> None:
        self._probe_progress_dialog = None
        results = cast(list[ProbeResult], value)
        if not results:
            self.window.commands._update_action_states()
            QMessageBox.information(
                self.window,
                "No Issues Found",
                "No tag issues were found.",
            )
            return
        dialog = ProbeDialog(
            results,
            self.window,
            root_directory=self.window.directory,
            scanned_count=len(self.window.catalog.entries),
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowFlag(Qt.WindowType.Window, True)
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.image_activated.connect(self._select_image_from_probe)
        dialog.finished.connect(self._probe_finished)
        dialog.destroyed.connect(self._probe_destroyed)
        self._probe_dialog = dialog
        self.window.commands._update_action_states()
        dialog.show()

    def _probe_failed(self, message: str) -> None:
        self._probe_progress_dialog = None
        self.window.commands._update_action_states()
        QMessageBox.critical(
            self.window, "Could Not Probe Tags", message
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

    def _open_image_transform(self) -> None:
        if not self.window.catalog.entries:
            return
        current = self.window._current_entry()
        dialog = ImageTransformDialog(
            list(self.window.catalog.entries), self.window,
            root_directory=self.window.directory,
        )
        if dialog.exec() == ImageTransformDialog.DialogCode.Accepted:
            progress = ConvertProgressDialog(
                dialog.selected_paths_for_conversion, dialog.target_format, self.window
            )
            result = []
            progress.completed.connect(lambda value: result.append(value))
            progress.start()
            progress.exec()
            if self.window.directory is not None:
                self.window.folders._load_directory(
                    self.window.directory,
                    preferred_image=current.image_path if current else None,
                    show_issues=False,
                )
            if result and result[0][0]:
                self.window.statusBar().showMessage(
                    f"Converted {len(result[0][0])} image(s).", 4000
                )

    def _open_pixel_transform(self) -> None:
        if not self.window.catalog.entries:
            return
        current = self.window._current_entry()
        dialog = PixelTransformDialog(list(self.window.catalog.entries), self.window, root_directory=self.window.directory)
        if dialog.exec() == PixelTransformDialog.DialogCode.Accepted and self.window.directory is not None:
            self.window.preview_loader.clear()
            self.window.folders._load_directory(self.window.directory, preferred_image=current.image_path if current else None, show_issues=False)

    def _open_grid_preview(self) -> None:
        current = self.window._current_entry()
        if current is None or not self.window.catalog.entries:
            return
        GridPreviewDialog(
            list(self.window.catalog.entries),
            self.window,
            options=get_preprocess_options(self.window.settings),
            grid_type=get_grid_type(self.window.settings),
            initial_image_path=current.image_path,
            image_prefetch_count=get_image_prefetch_count(self.window.settings),
        ).exec()

    def _open_correlation_analysis(self) -> None:
        if not self.window.catalog.entries or self.window.directory is None:
            return
        CorrelationAnalysisDialog(
            self.window.catalog.entries,
            self.window,
            root_directory=self.window.directory,
            tag_library=self.window.tag_library,
        ).exec()

    def _open_crop(self, *, initial_paths: list[Path] | None = None) -> None:
        if not self.window.catalog.entries:
            return
        selection = CropSelectionDialog(
            list(self.window.catalog.entries), self.window,
            root_directory=self.window.directory,
            initial_paths=initial_paths,
        )
        if selection.exec() != CropSelectionDialog.DialogCode.Accepted:
            return
        editor = CropDialog(
            selection.selected_paths,
            self.window,
            options=get_preprocess_options(self.window.settings),
        )
        editor.exec()
        if editor.saved_paths and self.window.directory is not None:
            current = self.window._current_entry()
            self.window.preview_loader.clear()
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )
            self.window.statusBar().showMessage(
                f"Cropped {len(editor.saved_paths)} image(s).", 4000,
            )

    def _open_mask_editor(self, *, initial_paths: list[Path] | None = None) -> None:
        if not self.window.catalog.entries:
            return
        selection = MaskSelectionDialog(
            list(self.window.catalog.entries), self.window,
            root_directory=self.window.directory,
            initial_paths=initial_paths,
        )
        if selection.exec() != MaskSelectionDialog.DialogCode.Accepted:
            return
        editor = MaskEditorDialog(selection.selected_paths, self.window)
        editor.exec()
        if editor.saved_paths and self.window.directory is not None:
            current = self.window._current_entry()
            self.window.preview_loader.clear()
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=current.image_path if current else None,
                show_issues=False,
            )
            self.window.statusBar().showMessage(
                f"Saved masks for {len(editor.saved_paths)} image(s).", 4000
            )

    def _open_remove_transparency(
        self, *, initial_paths: list[Path] | None = None
    ) -> None:
        if self.window.directory is None or not self.window.catalog.entries:
            return
        selection = TransparencySelectionDialog(
            list(self.window.catalog.entries),
            self.window,
            root_directory=self.window.directory,
            initial_paths=initial_paths,
        )
        if selection.exec() != TransparencySelectionDialog.DialogCode.Accepted:
            return
        paths = selection.selected_paths
        dialog = TransparencyProgressDialog(paths, self.window)

        def finished(result: tuple[list[Path], list[str]]) -> None:
            changed, failures = result
            if changed and self.window.directory is not None:
                current = self.window._current_entry()
                self.window.preview_loader.clear()
                self.window.folders._load_directory(
                    self.window.directory,
                    preferred_image=current.image_path if current else None,
                    show_issues=False,
                )
            if failures:
                QMessageBox.warning(
                    self.window,
                    "Some Images Could Not Be Updated",
                    "\n".join(failures),
                )
            elif changed:
                self.window.statusBar().showMessage(
                    f"Removed transparency from {len(changed)} image(s).", 4000
                )

        dialog.completed.connect(finished)
        dialog.show()
        dialog.start()

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
        dialog = AITaggingSelectionDialog(
            editable_entries,
            self.window,
            root_directory=self.window.directory,
            proxy=get_download_proxy(self.window.settings),
            image_prefetch_count=get_image_prefetch_count(self.window.settings),
            initial_image_path=initial_image_path,
        )
        if dialog.exec() != AITaggingSelectionDialog.DialogCode.Accepted:
            return
        parameters = dialog.parameters
        selected_entries = dialog.selected_entries
        if parameters is None or not selected_entries:
            return

        progress_dialog = AITaggingProgressDialog(
            selected_entries,
            parameters,
            self.window,
            proxy=get_download_proxy(self.window.settings),
        )
        progress_dialog.completed.connect(
            lambda results, progress=progress_dialog, entries=selected_entries:
            self._ai_tagging_inference_completed(
                progress, entries, results, current
            )
        )
        progress_dialog.failed.connect(
            lambda message, progress=progress_dialog:
            self._ai_tagging_inference_failed(progress, message)
        )
        self._ai_tagging_progress_dialog = progress_dialog
        self.window.commands._update_action_states()
        progress_dialog.show()
        progress_dialog.raise_()
        progress_dialog.activateWindow()
        progress_dialog.start()

    def _ai_tagging_inference_completed(
        self,
        progress_dialog: AITaggingProgressDialog,
        entries: list,
        results: object,
        current,
    ) -> None:
        if self._ai_tagging_progress_dialog is progress_dialog:
            self._ai_tagging_progress_dialog = None
        self.window.commands._update_action_states()
        normalized_results = results if isinstance(results, dict) else {}
        review_dialog = AITaggingReviewDialog(
            entries,
            normalized_results,
            self.window,
            root_directory=self.window.directory,
            image_prefetch_count=get_image_prefetch_count(self.window.settings),
        )
        review_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        review_dialog.finished.connect(
            lambda result, review=review_dialog, preferred=current.image_path
            if current is not None
            else None: self._ai_tagging_review_finished(
                review, result, preferred
            )
        )
        self._ai_tagging_review_dialog = review_dialog
        self.window.commands._update_action_states()
        review_dialog.show()
        review_dialog.raise_()
        review_dialog.activateWindow()

    def _ai_tagging_inference_failed(
        self, progress_dialog: AITaggingProgressDialog, message: str
    ) -> None:
        if self._ai_tagging_progress_dialog is progress_dialog:
            self._ai_tagging_progress_dialog = None
        self.window.commands._update_action_states()
        QMessageBox.critical(self.window, "AI Inference Failed", message)

    def _ai_tagging_review_finished(
        self, dialog: AITaggingReviewDialog, result: int, preferred: Path | None
    ) -> None:
        if self._ai_tagging_review_dialog is dialog:
            self._ai_tagging_review_dialog = None
        self.window.commands._update_action_states()
        if (
            result == AITaggingReviewDialog.DialogCode.Accepted
            and dialog.commit_result is not None
            and self.window.directory is not None
        ):
            self.window.folders._load_directory(
                self.window.directory,
                preferred_image=preferred,
                show_issues=False,
            )

    def _complex_filter_destroyed(self, _object: QObject) -> None:
        self._complex_filter_dialog = None

    def _probe_destroyed(self, _object: QObject) -> None:
        self._probe_dialog = None

    def _probe_finished(self, _result: int) -> None:
        self._probe_dialog = None
        self.window.commands._update_action_states()

    def _select_image_from_complex_filter(self, image_path: Path) -> None:
        row = self.window.catalog.row_for_image(image_path)
        self.window._select_optional_row(row)

    def _select_image_from_probe(self, image_path: Path) -> None:
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
