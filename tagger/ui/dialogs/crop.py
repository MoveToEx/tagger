from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import override

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressDialog, QPushButton, QRadioButton, QStyle,
    QVBoxLayout, QWidget,
)

from tagger.crop_storage import (
    CropBox, FileStamp, crop_disabled_reason, crop_image, file_stamp, load_crop_image,
)
from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.transparency import TransparencySelectionDialog
from tagger.ui.mouse_navigation import MouseNavigation
from tagger.ui.preview.crop import CropImageView
from tagger.ui.widgets import stabilize_widget_size


ASPECT_RATIOS = ("Free", "Original", "1:1", "4:3", "3:4", "16:9", "9:16", "1:2", "2:1", "3:2", "2:3", "Custom")


def _parse_ratio(text: str) -> float:
    parts = text.strip().replace("/", ":").split(":")
    if len(parts) not in {1, 2}:
        raise ValueError("Use a positive ratio, such as 4:3 or 1.5.")
    values = [float(part) for part in parts]
    if any(not isfinite(value) or value <= 0 for value in values):
        raise ValueError("The aspect ratio must be positive and finite.")
    ratio = values[0] / values[1] if len(values) == 2 else values[0]
    if not isfinite(ratio) or ratio <= 0:
        raise ValueError("The aspect ratio must be positive and finite.")
    return ratio


@dataclass
class _CropDraft:
    box: CropBox
    original_box: CropBox
    stamp: FileStamp
    ratio_name: str = "Free"
    custom_text: str = "4:3"

    def ratio(self) -> float | None:
        if self.ratio_name == "Free":
            return None
        if self.ratio_name == "Original":
            return self.original_box[2] / self.original_box[3]
        ratio = _parse_ratio(self.custom_text if self.ratio_name == "Custom" else self.ratio_name)
        if not 1 / self.original_box[3] <= ratio <= self.original_box[2]:
            raise ValueError("This ratio is too narrow or wide for the image dimensions.")
        return ratio


class CropSelectionDialog(TransparencySelectionDialog):
    def __init__(
        self, entries: list[ImageEntry], parent: QWidget | None = None,
        *, root_directory: Path | None = None,
        initial_paths: list[Path] | None = None,
    ) -> None:
        super().__init__(
            entries, parent, root_directory=root_directory,
            initial_paths=initial_paths,
            disabled_reason=crop_disabled_reason,
            title="Crop — Select Images", prompt="Select images to crop",
            action_text="Continue",
        )
        self.continue_button = self.remove_button


class CropDialog(QDialog):
    def __init__(self, paths: list[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crop Images")
        self.resize(1060, 720)
        self.paths = list(paths)
        self.current_index = 0
        self.saved_paths: list[Path] = []
        self._drafts: dict[Path, _CropDraft] = {}
        self._loading = False
        self._saving = False
        self._allow_close = False
        self._current_loaded = False

        self.progress_label = QLabel()
        self.path_label = QLabel()
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.image_view = CropImageView()
        self.image_view.crop_changed.connect(self._crop_changed)

        self.options_panel = QWidget()
        options = QVBoxLayout(self.options_panel)
        options.setContentsMargins(12, 0, 0, 0)
        ratio_box = QGroupBox("Aspect ratio")
        ratios_layout = QGridLayout(ratio_box)
        self.ratio_group = QButtonGroup(self)
        self.ratio_buttons: dict[str, QRadioButton] = {}
        for index, name in enumerate(ASPECT_RATIOS):
            button = QRadioButton(name)
            indicator_width = button.style().pixelMetric(
                QStyle.PixelMetric.PM_ExclusiveIndicatorWidth, None, button,
            ) - 1
            indicator_height = button.style().pixelMetric(
                QStyle.PixelMetric.PM_ExclusiveIndicatorHeight, None, button,
            ) - 1
            button.setStyleSheet(
                "QRadioButton::indicator { "
                f"width: {indicator_width}px; height: {indicator_height}px; "
                "}"
            )
            stabilize_widget_size(button)
            self.ratio_group.addButton(button)
            self.ratio_buttons[name] = button
            ratios_layout.addWidget(button, index // 2, index % 2)
        self.ratio_group.buttonClicked.connect(self._ratio_changed)
        self.custom_ratio = QLineEdit("4:3")
        self.custom_ratio.setPlaceholderText("Width:height, e.g. 4:3")
        self.custom_ratio.setAccessibleName("Custom aspect ratio")
        self.custom_ratio.textChanged.connect(self._ratio_changed)
        stabilize_widget_size(self.custom_ratio, minimum_width=220)
        ratios_layout.addWidget(self.custom_ratio, 6, 0, 1, 2)
        options.addWidget(ratio_box)
        self.ratio_error = QLabel()
        self.ratio_error.setWordWrap(True)
        options.addWidget(self.ratio_error)
        self.size_label = QLabel()
        options.addWidget(self.size_label)
        instructions = QLabel(
            "Drag inside the crop to move it. Drag a corner to resize, or drag "
            "outside the crop to draw a new region.\n\n"
            "Previous and Next keep your drafts. Finish replaces the edited images."
        )
        instructions.setWordWrap(True)
        options.addWidget(instructions)
        self.reset_button = QPushButton("Reset Crop")
        self.reset_button.clicked.connect(self._reset)
        options.addWidget(self.reset_button)
        options.addStretch(1)
        self.options_panel.setFixedWidth(280)

        row = QHBoxLayout()
        row.addWidget(self.image_view, 1)
        row.addWidget(self.options_panel)
        self.previous_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.finish_button = QPushButton("Finish")
        self.cancel_button = QPushButton("Cancel")
        for button in (self.previous_button, self.next_button, self.finish_button, self.cancel_button):
            button.setAutoDefault(False)
        self.previous_button.clicked.connect(lambda: self._navigate(-1))
        self.next_button.clicked.connect(lambda: self._navigate(1))
        self.finish_button.clicked.connect(self._finish)
        self.cancel_button.clicked.connect(self.reject)
        self._mouse_navigation = MouseNavigation(
            self, back=[self.previous_button], forward=[self.next_button],
        )
        self.pending_label = QLabel()
        buttons = QHBoxLayout()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.pending_label)
        buttons.addStretch(1)
        buttons.addWidget(self.previous_button)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.finish_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.path_label)
        layout.addLayout(row, 1)
        layout.addLayout(buttons)
        self._load_current()

    @property
    def dirty_paths(self) -> set[Path]:
        return {path for path, draft in self._drafts.items() if draft.box != draft.original_box}

    def _load_current(self) -> None:
        self._current_loaded = False
        if not self.paths:
            self.path_label.setText("No images selected.")
            self._update_buttons()
            return
        path = self.paths[self.current_index]
        self.progress_label.setText(f"Image {self.current_index + 1} of {len(self.paths)}")
        self.path_label.setText(str(path))
        try:
            stamp = file_stamp(path)
            draft = self._drafts.get(path)
            if draft is not None and stamp != draft.stamp:
                raise OSError("Image changed since it was opened. Reopen the crop dialog.")
            image = load_crop_image(path)
            if stamp != file_stamp(path):
                raise OSError("Image changed while loading. Reopen the crop dialog.")
        except (OSError, ValueError) as exc:
            self.image_view.set_image(None)
            self.size_label.setText(f"Could not load image: {exc}")
            self._update_buttons()
            return
        if draft is None:
            box = (0, 0, image.width, image.height)
            draft = _CropDraft(box, box, stamp)
            self._drafts[path] = draft
        self._loading = True
        try:
            self.ratio_buttons[draft.ratio_name].setChecked(True)
            self.custom_ratio.setText(draft.custom_text)
            self.custom_ratio.setEnabled(draft.ratio_name == "Custom")
            try:
                ratio = draft.ratio()
                self.ratio_error.clear()
            except ValueError as exc:
                ratio = None
                self.ratio_error.setText(str(exc))
            self.image_view.set_image(image, draft.box, ratio)
            self._current_loaded = True
        finally:
            self._loading = False
        self._update_size_label()
        self._update_buttons()

    def _update_size_label(self) -> None:
        left, top, right, bottom = self.image_view.crop_box
        self.size_label.setText(f"Crop: {right - left} × {bottom - top} pixels")

    def _crop_changed(self, box: CropBox) -> None:
        if self._loading or not self._current_loaded:
            return
        self._drafts[self.paths[self.current_index]].box = box
        self._update_size_label()
        self._update_buttons()

    def _ratio_changed(self, *_args) -> None:
        if self._loading or not self._current_loaded:
            return
        button = self.ratio_group.checkedButton()
        assert button is not None
        draft = self._drafts[self.paths[self.current_index]]
        draft.ratio_name = button.text()
        draft.custom_text = self.custom_ratio.text()
        self.custom_ratio.setEnabled(draft.ratio_name == "Custom")
        try:
            ratio = draft.ratio()
        except ValueError as exc:
            self.ratio_error.setText(str(exc))
        else:
            self.ratio_error.clear()
            self.image_view.set_aspect_ratio(ratio)
        self._update_buttons()

    def _reset(self) -> None:
        if not self._current_loaded:
            return
        draft = self._drafts[self.paths[self.current_index]]
        draft.box = draft.original_box
        draft.ratio_name = "Free"
        self._load_current()

    def _navigate(self, delta: int) -> None:
        index = self.current_index + delta
        if not self._saving and 0 <= index < len(self.paths):
            self.current_index = index
            self._load_current()

    def _update_buttons(self) -> None:
        self.previous_button.setEnabled(not self._saving and self.current_index > 0)
        self.next_button.setEnabled(not self._saving and self.current_index + 1 < len(self.paths))
        self.options_panel.setEnabled(self._current_loaded and not self._saving)
        self.image_view.setEnabled(self._current_loaded and not self._saving)
        self.cancel_button.setEnabled(not self._saving)
        invalid = False
        for draft in self._drafts.values():
            try:
                draft.ratio()
            except ValueError:
                invalid = True
        self.finish_button.setEnabled(bool(self.paths) and not self._saving and not invalid)
        text = f"{len(self.dirty_paths)} crop(s) staged."
        if invalid:
            text += " Fix invalid custom ratios to finish."
        self.pending_label.setText(text)

    def _finish(self) -> None:
        if self._saving or not self.finish_button.isEnabled():
            return
        dirty = self.dirty_paths
        paths = [path for path in self.paths if path in dirty]
        self._saving = True
        self._update_buttons()
        progress = QProgressDialog("Saving crops...", "", 0, len(paths), self)
        progress.setWindowTitle("Cropping Images")
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setFixedWidth(440)
        label = progress.findChild(QLabel)
        if label is not None:
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        failures: list[str] = []
        try:
            for index, path in enumerate(paths):
                progress.setLabelText(f"Cropping: {path.name}")
                progress.setValue(index)
                QApplication.processEvents()
                draft = self._drafts[path]
                try:
                    if crop_image(path, draft.box, expected_stamp=draft.stamp):
                        if path not in self.saved_paths:
                            self.saved_paths.append(path)
                    del self._drafts[path]
                except (OSError, ValueError) as exc:
                    failures.append(f"{path.name}: {exc}")
            progress.setValue(len(paths))
        finally:
            progress.close()
            self._saving = False
        if failures:
            self._load_current()
            QMessageBox.warning(self, "Some Images Could Not Be Cropped", "\n".join(failures))
            return
        self._allow_close = True
        self.accept()

    def _confirm_discard(self) -> bool:
        if self._saving:
            return False
        if self._allow_close or not self.dirty_paths:
            return True
        return QMessageBox.question(
            self, "Discard Crops?", "Discard the uncommitted crops?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Discard

    @override
    def reject(self) -> None:
        if self._confirm_discard():
            self._allow_close = True
            super().reject()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard():
            self._allow_close = True
            event.accept()
        else:
            event.ignore()
