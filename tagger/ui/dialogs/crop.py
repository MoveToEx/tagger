from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path
from typing import override

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIntValidator
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressDialog, QPushButton, QRadioButton, QStyle,
    QToolButton, QVBoxLayout, QWidget,
)

from tagger.crop_storage import (
    CropBox, FileStamp, crop_disabled_reason, crop_image, file_stamp, load_crop_image,
)
from tagger.domain.models import ImageEntry
from tagger.preprocess import PreprocessOptions, closest_bucket
from tagger.ui.dialogs.transparency import TransparencySelectionDialog
from tagger.ui.mouse_navigation import MouseNavigation
from tagger.ui.preview.crop import CropImageView
from tagger.ui.widgets import stabilize_widget_size


ASPECT_RATIOS = ("Free", "Original", "1:1", "4:3", "3:4", "16:9", "9:16", "1:2", "2:1", "3:2", "2:3", "Custom")
ASPECT_RATIO_MODE = "Aspect ratio"
ARB_MODE = "ARB"


def _arb_bounds(options: PreprocessOptions) -> tuple[int, int]:
    minimum = max(1, min(options.arb_min_size, options.arb_max_size))
    maximum = max(minimum, max(options.arb_min_size, options.arb_max_size))
    return minimum, maximum


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
    mode: str = ASPECT_RATIO_MODE
    ratio_name: str = "Free"
    custom_text: str = "4:3"
    arb_width_text: str | None = None
    arb_height_text: str | None = None

    def initialize_arb_bucket(self, options: PreprocessOptions) -> None:
        if self.arb_width_text is None or self.arb_height_text is None:
            width, height = closest_bucket(self.original_size, options)
            self.arb_width_text = str(width)
            self.arb_height_text = str(height)

    @property
    def original_size(self) -> tuple[int, int]:
        left, top, right, bottom = self.original_box
        return right - left, bottom - top

    def arb_bucket(self, options: PreprocessOptions) -> tuple[int, int]:
        self.initialize_arb_bucket(options)
        assert self.arb_width_text is not None
        assert self.arb_height_text is not None
        minimum, maximum = _arb_bounds(options)
        try:
            width = int(self.arb_width_text)
            height = int(self.arb_height_text)
        except ValueError as exc:
            raise ValueError("Bucket width and height must be whole numbers.") from exc
        if not minimum <= width <= maximum or not minimum <= height <= maximum:
            raise ValueError(
                f"Bucket width and height must be from {minimum} to {maximum}."
            )
        return width, height

    def ratio(self, options: PreprocessOptions) -> float | None:
        if self.mode == ARB_MODE:
            width, height = self.arb_bucket(options)
            return width / height
        if self.ratio_name == "Free":
            return None
        if self.ratio_name == "Original":
            width, height = self.original_size
            return width / height
        ratio = _parse_ratio(self.custom_text if self.ratio_name == "Custom" else self.ratio_name)
        width, height = self.original_size
        if not 1 / height <= ratio <= width:
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
    def __init__(
        self,
        paths: list[Path],
        parent: QWidget | None = None,
        *,
        options: PreprocessOptions | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Crop Images")
        self.resize(1060, 720)
        self.paths = list(paths)
        self.current_index = 0
        self.saved_paths: list[Path] = []
        self._arb_options = replace(
            options or PreprocessOptions(), arb_enabled=True
        )
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
        options_layout = QVBoxLayout(self.options_panel)
        options_layout.setContentsMargins(12, 0, 0, 0)

        def radio_button(text: str) -> QRadioButton:
            button = QRadioButton(text)
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
            return button

        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[str, QRadioButton] = {}

        arb_button = radio_button(ARB_MODE)
        self.mode_group.addButton(arb_button)
        self.mode_buttons[ARB_MODE] = arb_button
        options_layout.addWidget(arb_button)

        self.arb_options_panel = QWidget()
        arb_layout = QVBoxLayout(self.arb_options_panel)
        arb_layout.setContentsMargins(20, 0, 0, 6)
        arb_layout.setSpacing(4)
        minimum, maximum = _arb_bounds(self._arb_options)

        def arb_input(name: str) -> QLineEdit:
            field = QLineEdit(str(maximum))
            field.setValidator(QIntValidator(minimum, maximum, field))
            field.setAlignment(Qt.AlignmentFlag.AlignRight)
            field.setAccessibleName(f"ARB bucket {name}")
            stabilize_widget_size(field, minimum_width=96)
            return field

        def step_button(text: str, tooltip: str) -> QToolButton:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setFixedSize(26, 26)
            return button

        self.arb_width_input = arb_input("width")
        self.arb_height_input = arb_input("height")
        self.arb_width_decrease_button = step_button(
            "-", "Decrease bucket width"
        )
        self.arb_width_increase_button = step_button(
            "+", "Increase bucket width"
        )
        self.arb_height_decrease_button = step_button(
            "-", "Decrease bucket height"
        )
        self.arb_height_increase_button = step_button(
            "+", "Increase bucket height"
        )
        for label, field, decrease, increase in (
            (
                "Width",
                self.arb_width_input,
                self.arb_width_decrease_button,
                self.arb_width_increase_button,
            ),
            (
                "Height",
                self.arb_height_input,
                self.arb_height_decrease_button,
                self.arb_height_increase_button,
            ),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addStretch(1)
            row.addWidget(field)
            row.addWidget(decrease)
            row.addWidget(increase)
            arb_layout.addLayout(row)
        options_layout.addWidget(self.arb_options_panel)

        aspect_ratio_button = radio_button(ASPECT_RATIO_MODE)
        self.mode_group.addButton(aspect_ratio_button)
        self.mode_buttons[ASPECT_RATIO_MODE] = aspect_ratio_button
        options_layout.addWidget(aspect_ratio_button)

        self.aspect_ratio_options = QWidget()
        ratios_layout = QGridLayout(self.aspect_ratio_options)
        ratios_layout.setContentsMargins(20, 0, 0, 0)
        self.ratio_group = QButtonGroup(self)
        self.ratio_buttons: dict[str, QRadioButton] = {}
        for index, name in enumerate(ASPECT_RATIOS):
            button = radio_button(name)
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
        options_layout.addWidget(self.aspect_ratio_options)

        self.mode_group.buttonClicked.connect(self._mode_changed)
        self.arb_width_input.textChanged.connect(self._arb_size_changed)
        self.arb_height_input.textChanged.connect(self._arb_size_changed)
        self.arb_width_decrease_button.clicked.connect(
            lambda: self._step_arb_dimension("width", -1)
        )
        self.arb_width_increase_button.clicked.connect(
            lambda: self._step_arb_dimension("width", 1)
        )
        self.arb_height_decrease_button.clicked.connect(
            lambda: self._step_arb_dimension("height", -1)
        )
        self.arb_height_increase_button.clicked.connect(
            lambda: self._step_arb_dimension("height", 1)
        )
        self.ratio_error = QLabel()
        self.ratio_error.setWordWrap(True)
        options_layout.addWidget(self.ratio_error)
        self.size_label = QLabel()
        options_layout.addWidget(self.size_label)
        self.reset_button = QPushButton("Reset Crop")
        self.reset_button.clicked.connect(self._reset)
        options_layout.addWidget(self.reset_button)
        options_layout.addStretch(1)
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
            draft.initialize_arb_bucket(self._arb_options)
            assert draft.arb_width_text is not None
            assert draft.arb_height_text is not None
            self.mode_buttons[draft.mode].setChecked(True)
            self.ratio_buttons[draft.ratio_name].setChecked(True)
            self.arb_width_input.setText(draft.arb_width_text)
            self.arb_height_input.setText(draft.arb_height_text)
            self.custom_ratio.setText(draft.custom_text)
            self._update_mode_controls(draft)
            try:
                ratio = draft.ratio(self._arb_options)
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

    def _update_mode_controls(self, draft: _CropDraft) -> None:
        aspect_ratio_mode = draft.mode == ASPECT_RATIO_MODE
        self.arb_options_panel.setEnabled(not aspect_ratio_mode)
        self.aspect_ratio_options.setEnabled(aspect_ratio_mode)
        self.image_view.set_resize_enabled(aspect_ratio_mode)
        self.custom_ratio.setEnabled(
            aspect_ratio_mode and draft.ratio_name == "Custom"
        )
        self._update_arb_step_buttons()

    def _update_arb_step_buttons(self) -> None:
        minimum, maximum = _arb_bounds(self._arb_options)
        step = max(1, self._arb_options.arb_step)

        def value(field: QLineEdit) -> int | None:
            try:
                result = int(field.text())
            except ValueError:
                return None
            return result if minimum <= result <= maximum else None

        width = value(self.arb_width_input)
        height = value(self.arb_height_input)
        self.arb_width_decrease_button.setEnabled(
            width is not None and width - step >= minimum
        )
        self.arb_width_increase_button.setEnabled(
            width is not None and width + step <= maximum
        )
        self.arb_height_decrease_button.setEnabled(
            height is not None and height - step >= minimum
        )
        self.arb_height_increase_button.setEnabled(
            height is not None and height + step <= maximum
        )

    def _update_size_label(self) -> None:
        left, top, right, bottom = self.image_view.crop_box
        self.size_label.setText(f"Crop: {right - left} × {bottom - top} pixels")

    def _crop_changed(self, box: CropBox) -> None:
        if self._loading or not self._current_loaded:
            return
        self._drafts[self.paths[self.current_index]].box = box
        self._update_size_label()
        self._update_buttons()

    def _mode_changed(self, *_args) -> None:
        if self._loading or not self._current_loaded:
            return
        button = self.mode_group.checkedButton()
        assert button is not None
        draft = self._drafts[self.paths[self.current_index]]
        draft.mode = button.text()
        self._update_mode_controls(draft)
        self._apply_ratio(draft)
        self._update_buttons()

    def _arb_size_changed(self, *_args) -> None:
        if self._loading or not self._current_loaded:
            return
        draft = self._drafts[self.paths[self.current_index]]
        draft.arb_width_text = self.arb_width_input.text()
        draft.arb_height_text = self.arb_height_input.text()
        self._update_arb_step_buttons()
        if draft.mode == ARB_MODE:
            self._apply_ratio(draft)
        self._update_buttons()

    def _step_arb_dimension(self, dimension: str, direction: int) -> None:
        field = (
            self.arb_width_input
            if dimension == "width"
            else self.arb_height_input
        )
        try:
            current = int(field.text())
        except ValueError:
            return
        minimum, maximum = _arb_bounds(self._arb_options)
        updated = current + direction * max(1, self._arb_options.arb_step)
        if minimum <= updated <= maximum:
            field.setText(str(updated))

    def _ratio_changed(self, *_args) -> None:
        if self._loading or not self._current_loaded:
            return
        button = self.ratio_group.checkedButton()
        assert button is not None
        draft = self._drafts[self.paths[self.current_index]]
        draft.ratio_name = button.text()
        draft.custom_text = self.custom_ratio.text()
        self._update_mode_controls(draft)
        self._apply_ratio(draft)
        self._update_buttons()

    def _apply_ratio(self, draft: _CropDraft) -> None:
        try:
            ratio = draft.ratio(self._arb_options)
        except ValueError as exc:
            self.ratio_error.setText(str(exc))
        else:
            self.ratio_error.clear()
            self.image_view.set_aspect_ratio(ratio)

    def _reset(self) -> None:
        if not self._current_loaded:
            return
        draft = self._drafts[self.paths[self.current_index]]
        draft.box = draft.original_box
        draft.mode = ASPECT_RATIO_MODE
        draft.ratio_name = "Free"
        draft.arb_width_text = None
        draft.arb_height_text = None
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
                draft.ratio(self._arb_options)
            except ValueError:
                invalid = True
        self.finish_button.setEnabled(bool(self.paths) and not self._saving and not invalid)
        text = f"{len(self.dirty_paths)} crop(s) staged."
        if invalid:
            text += " Fix invalid crop options to finish."
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
