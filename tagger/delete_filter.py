from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast, override

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .domain import ImageEntry
from .preview import ImageView, PreviewLoader
from .trash import move_to_trash


@dataclass
class DeleteFilterCommitResult:
    deleted_images: list[Path]
    moved_files: list[Path]
    failures: dict[Path, str]

    @property
    def complete(self) -> bool:
        return not self.failures


class DeleteFilterDialog(QDialog):
    """Stage image deletion choices and commit them together on Finish."""

    def __init__(
        self,
        entries: list[ImageEntry],
        parent=None,
        *,
        trash_file: Callable[[Path], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.entries = list(entries)
        self.current_index = 0
        self.marked_for_deletion: set[Path] = set()
        self.reviewed_indices: set[int] = set()
        self.commit_result: DeleteFilterCommitResult | None = None
        self._trash_file = trash_file or move_to_trash
        self._allow_close = False

        self.setWindowTitle("Delete Filter")
        self.resize(900, 680)

        self.progress_label = QLabel()
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.image_view = ImageView()
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
            self.image_view.clear_image("No images to review")
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
        self.image_view.clear_image("Loading image...")
        self.preview_loader.load(entry.image_path)
        self.back_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index + 1 < len(self.entries))
        self.delete_checkbox.setEnabled(True)
        self.finish_button.setEnabled(True)
        self.delete_checkbox.setFocus()

    def _preview_loaded(self, image, error: str) -> None:
        if error or image.isNull():
            self.image_view.clear_image(f"Could not display image\n{error}")
        else:
            self.image_view.set_image(image)

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
            answer = QMessageBox.question(
                self,
                "Delete Marked Images?",
                f"Move {count} marked image(s) and their tag files to the Trash?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.preview_loader.clear()
        self.preview_loader.wait_for_done()
        moved_files: list[Path] = []
        deleted_images: list[Path] = []
        failures: dict[Path, str] = {}
        for entry in self.entries:
            if entry.image_path not in self.marked_for_deletion:
                continue
            if self._move_file_to_trash(entry.image_path, failures):
                moved_files.append(entry.image_path)
                deleted_images.append(entry.image_path)
                if entry.tag_path.exists():
                    if self._move_file_to_trash(entry.tag_path, failures):
                        moved_files.append(entry.tag_path)

        self.commit_result = DeleteFilterCommitResult(
            deleted_images=deleted_images,
            moved_files=moved_files,
            failures=failures,
        )
        self._allow_close = True
        if failures:
            QMessageBox.warning(
                self,
                "Could Not Delete All Files",
                "\n".join(
                    f"{path.name}: {message}"
                    for path, message in failures.items()
                ),
            )
        self.accept()

    def _move_file_to_trash(
        self, path: Path, failures: dict[Path, str]
    ) -> bool:
        try:
            moved = self._trash_file(path)
        except OSError as exc:
            failures[path] = str(exc)
            return False
        if not moved:
            failures[path] = "Could not move file to Trash."
        return moved

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
