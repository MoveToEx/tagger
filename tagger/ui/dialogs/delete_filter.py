from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast, override

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.trash import SYSTEM_RECYCLE_BIN, UNLINK, delete_file
from tagger.ui.preview.config import DEFAULT_IMAGE_PREFETCH_COUNT
from tagger.ui.preview.loader import PreviewLoader


@dataclass
class DeleteFilterCommitResult:
    deleted_images: list[Path]
    deleted_files: list[Path]
    failures: dict[Path, str]

    @property
    def complete(self) -> bool:
        return not self.failures


class _DeleteFilterWorker(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        entries: list[ImageEntry],
        file_deleter: Callable[[Path], bool],
        preview_waiter: Callable[[], bool],
        deletion_behavior: str,
    ) -> None:
        super().__init__()
        self.entries = entries
        self._file_deleter = file_deleter
        self._preview_waiter = preview_waiter
        self._deletion_behavior = deletion_behavior

    @Slot()
    def run(self) -> None:
        total = len(self.entries) * 2
        try:
            self.progress.emit(
                0, total, "Waiting for image previews..."
            )
            self._preview_waiter()

            deleted_files: list[Path] = []
            deleted_images: list[Path] = []
            failures: dict[Path, str] = {}
            completed = 0
            deleting_permanently = self._deletion_behavior == UNLINK
            for entry in self.entries:
                action = (
                    "Deleting permanently"
                    if deleting_permanently
                    else "Moving to Recycle Bin"
                )
                self.progress.emit(
                    completed,
                    total,
                    f"{action}: {entry.image_path.name}",
                )
                image_moved = self._move_file(entry.image_path, failures)
                if image_moved:
                    deleted_files.append(entry.image_path)
                    deleted_images.append(entry.image_path)
                completed += 1

                if image_moved and entry.tag_path.exists():
                    self.progress.emit(
                        completed,
                        total,
                        f"{action}: {entry.tag_path.name}",
                    )
                    if self._move_file(entry.tag_path, failures):
                        deleted_files.append(entry.tag_path)
                    tag_status = f"Deleted: {entry.tag_path.name}"
                else:
                    tag_status = f"Skipped {entry.tag_path.name}"
                completed += 1
                self.progress.emit(completed, total, tag_status)

            self.completed.emit(
                DeleteFilterCommitResult(
                    deleted_images=deleted_images,
                    deleted_files=deleted_files,
                    failures=failures,
                )
            )
        except Exception as exc:
            self.failed.emit(str(exc))

    def _move_file(
        self, path: Path, failures: dict[Path, str]
    ) -> bool:
        try:
            deleted = self._file_deleter(path)
        except OSError as exc:
            failures[path] = str(exc)
            return False
        if not deleted:
            failures[path] = "Could not delete file."
        return deleted


class DeleteFilterProgressDialog(QDialog):
    """Show progress while the delete filter commit runs in the background."""

    def __init__(
        self,
        entries: list[ImageEntry],
        file_deleter: Callable[[Path], bool],
        preview_waiter: Callable[[], bool],
        parent: QWidget | None = None,
        *,
        deletion_behavior: str = SYSTEM_RECYCLE_BIN,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deleting Images")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(440)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self.current_file_label = QLabel("Preparing deletion...")
        self.current_file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(entries) * 2)
        self.progress_bar.setValue(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.current_file_label)
        layout.addWidget(self.progress_bar)

        self.commit_result: DeleteFilterCommitResult | None = None
        self.error: str | None = None
        self._running = False
        thread = QThread(self)
        worker = _DeleteFilterWorker(
            entries,
            file_deleter,
            preview_waiter,
            deletion_behavior,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._update_progress)
        worker.completed.connect(self._worker_completed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(self._worker_failed)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread: QThread | None = thread
        self._worker: _DeleteFilterWorker | None = worker

    def start(self) -> None:
        if self._running:
            return
        if self._thread is None:
            return
        self._running = True
        self._thread.start()

    def _update_progress(
        self, completed: int, total: int, current_file: str
    ) -> None:
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(completed)
        self.current_file_label.setText(current_file)

    def _worker_completed(self, result: DeleteFilterCommitResult) -> None:
        self.commit_result = result

    def _worker_failed(self, message: str) -> None:
        self.error = message

    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._running = False
        if self.commit_result is not None:
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.accept()
        else:
            self.reject()

    @override
    def reject(self) -> None:
        if self._running:
            return
        super().reject()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._running:
            event.ignore()
            return
        super().closeEvent(event)


class DeleteFilterDialog(QDialog):
    """Stage image deletion choices and commit them together on Finish."""

    def __init__(
        self,
        entries: list[ImageEntry],
        parent=None,
        *,
        file_deleter: Callable[[Path], bool] | None = None,
        deletion_behavior: str = SYSTEM_RECYCLE_BIN,
        image_prefetch_count: int = DEFAULT_IMAGE_PREFETCH_COUNT,
    ) -> None:
        super().__init__(parent)
        self.entries = list(entries)
        self.current_index = 0
        self.marked_for_deletion: set[Path] = set()
        self.reviewed_indices: set[int] = set()
        self.commit_result: DeleteFilterCommitResult | None = None
        self.deletion_behavior = deletion_behavior
        self._file_deleter = file_deleter or (
            lambda path: delete_file(path, deletion_behavior)
        )
        self._allow_close = False
        self._image_prefetch_count = max(0, image_prefetch_count)

        self.setWindowTitle("Delete Filter")
        self.resize(900, 680)

        self.progress_label = QLabel()
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.image_view = QLabel("Loading image...")
        self.image_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_view.setMinimumSize(240, 180)
        self.image_view.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self.image_view.setStyleSheet(
            "QLabel { color: #667085; background: #f2f4f7; }"
        )
        self._image_pixmap: QPixmap | None = None
        self.preview_loader = PreviewLoader(self)
        self.preview_loader.loaded.connect(self._preview_loaded)

        self.delete_checkbox = QCheckBox("Delete this image")
        self.delete_checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 12px; height: 12px; }"
        )
        self.delete_checkbox.toggled.connect(self._deletion_toggled)

        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")
        self.back_button.clicked.connect(self._back)
        self.next_button.clicked.connect(self._next)

        self.cancel_button = QPushButton("Cancel")
        self.finish_button = QPushButton("Finish")
        self.cancel_button.clicked.connect(self.reject)
        self.finish_button.clicked.connect(self._finish)

        self.right_controls = QWidget()
        right_controls_layout = QVBoxLayout(self.right_controls)
        right_controls_layout.setContentsMargins(0, 0, 0, 0)
        right_controls_layout.setSpacing(8)
        right_controls_layout.addWidget(
            self.delete_checkbox,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        right_buttons_layout = QHBoxLayout()
        right_buttons_layout.setContentsMargins(0, 0, 0, 0)
        right_buttons_layout.setSpacing(8)
        right_buttons_layout.addWidget(self.back_button)
        right_buttons_layout.addWidget(self.next_button)
        right_buttons_layout.addWidget(self.finish_button)
        right_controls_layout.addLayout(right_buttons_layout)

        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(
            self.cancel_button,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.right_controls)

        layout = QVBoxLayout(self)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.path_label)
        layout.addWidget(self.image_view, 1)
        layout.addLayout(bottom_layout)

        self.installEventFilter(self)
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)
        self._load_current()

    @property
    def current_entry(self) -> ImageEntry | None:
        if not self.entries:
            return None
        return self.entries[self.current_index]

    @property
    def has_changes(self) -> bool:
        return bool(self.marked_for_deletion)

    def _load_current(self) -> None:
        entry = self.current_entry
        if entry is None:
            self.progress_label.setText("No images to review")
            self.path_label.clear()
            self._clear_image("No images to review")
            self.delete_checkbox.setEnabled(False)
            self.back_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return

        self.progress_label.setText(
            f"Image {self.current_index + 1} of {len(self.entries)}"
            f" | Reviewed {len(self.reviewed_indices)} of {len(self.entries)}"
            f" | Marked for deletion {len(self.marked_for_deletion)}"
        )
        self.path_label.setText(str(entry.image_path))
        blocker = QSignalBlocker(self.delete_checkbox)
        self.delete_checkbox.setChecked(
            entry.image_path in self.marked_for_deletion
        )
        del blocker
        self._clear_image("Loading image...")
        next_index = self.current_index + 1
        prefetch_paths = [
            future_entry.image_path
            for future_entry in self.entries[
                next_index : next_index + self._image_prefetch_count
            ]
        ]
        self.preview_loader.load(entry.image_path, prefetch_paths)
        self.back_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index + 1 < len(self.entries))
        self.delete_checkbox.setEnabled(True)
        self.finish_button.setEnabled(True)
        self.delete_checkbox.setFocus()

    def _preview_loaded(self, image, error: str) -> None:
        if error or image.isNull():
            self._clear_image(f"Could not display image\n{error}")
        else:
            self._image_pixmap = QPixmap.fromImage(image)
            self.image_view.setText("")
            self._fit_current_image()

    def _clear_image(self, message: str) -> None:
        self._image_pixmap = None
        self.image_view.clear()
        self.image_view.setText(message)

    def _fit_current_image(self) -> None:
        if self._image_pixmap is None:
            return
        available = self.image_view.contentsRect().size()
        if available.isEmpty():
            return
        self.image_view.setPixmap(
            self._image_pixmap.scaled(
                available,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _deletion_toggled(self, delete_image: bool) -> None:
        entry = self.current_entry
        if entry is None:
            return
        self.reviewed_indices.add(self.current_index)
        if delete_image:
            self.marked_for_deletion.add(entry.image_path)
        else:
            self.marked_for_deletion.discard(entry.image_path)
        self.progress_label.setText(
            f"Image {self.current_index + 1} of {len(self.entries)}"
            f" | Reviewed {len(self.reviewed_indices)} of {len(self.entries)}"
            f" | Marked for deletion {len(self.marked_for_deletion)}"
        )

    def _toggle_current(self) -> None:
        if self.current_entry is not None:
            self.delete_checkbox.toggle()

    def _set_current_decision(self, *, delete_image: bool) -> None:
        entry = self.current_entry
        if entry is None:
            return
        self.reviewed_indices.add(self.current_index)
        if delete_image:
            self.marked_for_deletion.add(entry.image_path)
        else:
            self.marked_for_deletion.discard(entry.image_path)
        blocker = QSignalBlocker(self.delete_checkbox)
        self.delete_checkbox.setChecked(delete_image)
        del blocker
        if self.current_index + 1 < len(self.entries):
            self.current_index += 1
            self._load_current()
        else:
            self.progress_label.setText(
                f"Image {self.current_index + 1} of {len(self.entries)}"
                f" | Reviewed {len(self.reviewed_indices)} of {len(self.entries)}"
                f" | Marked for deletion {len(self.marked_for_deletion)}"
            )

    def _back(self) -> None:
        if self.current_index <= 0:
            return
        self.reviewed_indices.add(self.current_index)
        self.current_index -= 1
        self._load_current()

    def _next(self) -> None:
        if self.current_index + 1 >= len(self.entries):
            return
        self.reviewed_indices.add(self.current_index)
        self.current_index += 1
        self._load_current()

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.image_view:
            if event.type() == QEvent.Type.Resize:
                self._fit_current_image()
            elif event.type() == QEvent.Type.MouseButtonRelease:
                mouse_event = cast(QMouseEvent, event)
                if self._image_pixmap is not None:
                    if mouse_event.button() == Qt.MouseButton.LeftButton:
                        self._set_current_decision(delete_image=False)
                        return True
                    if mouse_event.button() == Qt.MouseButton.RightButton:
                        self._set_current_decision(delete_image=True)
                        return True
        if event.type() == QEvent.Type.KeyPress:
            key_event = cast(QKeyEvent, event)
            if key_event.key() == Qt.Key.Key_Space:
                self._toggle_current()
                return True
            if key_event.key() == Qt.Key.Key_Left:
                self._back()
                return True
            if key_event.key() in {
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Right,
            }:
                self._next()
                return True
        return super().eventFilter(watched, event)

    def _finish(self) -> None:
        count = len(self.marked_for_deletion)
        if count:
            deleting_permanently = self.deletion_behavior == UNLINK
            answer = QMessageBox.question(
                self,
                (
                    "Permanently Delete Marked Images?"
                    if deleting_permanently
                    else "Delete Marked Images?"
                ),
                (
                    f"Permanently delete {count} marked image(s) and their "
                    "tag files?\n\nThis cannot be undone."
                    if deleting_permanently
                    else f"Move {count} marked image(s) and their tag files "
                    "to the system Recycle Bin?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.preview_loader.clear()
        selected_entries = [
            entry
            for entry in self.entries
            if entry.image_path in self.marked_for_deletion
        ]
        progress_dialog = DeleteFilterProgressDialog(
            selected_entries,
            self._file_deleter,
            self.preview_loader.wait_for_done,
            self,
            deletion_behavior=self.deletion_behavior,
        )
        progress_dialog.start()
        progress_dialog.exec()
        if progress_dialog.commit_result is None:
            if progress_dialog.error:
                QMessageBox.critical(
                    self,
                    "Could Not Delete Files",
                    progress_dialog.error,
                )
            return

        self.commit_result = progress_dialog.commit_result
        self._allow_close = True
        if self.commit_result.failures:
            QMessageBox.warning(
                self,
                "Could Not Delete All Files",
                "\n".join(
                    f"{path.name}: {message}"
                    for path, message in self.commit_result.failures.items()
                ),
            )
        self.accept()

    def _confirm_discard(self) -> bool:
        if not self.has_changes:
            return True
        answer = QMessageBox.question(
            self,
            "Discard Delete Filter Changes?",
            "The delete filter has uncommitted changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    @override
    def reject(self) -> None:
        if self._allow_close or self._confirm_discard():
            self._allow_close = True
            super().reject()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close or self._confirm_discard():
            self._allow_close = True
            event.accept()
        else:
            event.ignore()
