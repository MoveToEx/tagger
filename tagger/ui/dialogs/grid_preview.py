from __future__ import annotations

from pathlib import Path
from typing import override

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QIcon,
    QImage,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.paths import PROJECT_ROOT
from tagger.preprocess import (
    DEFAULT_GRID_TYPE,
    GRID_TYPES,
    PreprocessOptions,
    PreprocessPlan,
    create_preprocess_plan,
)
from tagger.ui.mouse_navigation import MouseNavigation
from tagger.ui.preview.config import DEFAULT_IMAGE_PREFETCH_COUNT, SCROLL_PAN
from tagger.ui.preview.loader import PreviewLoader
from tagger.ui.preview.view import ImageView


_ICON_DIRECTORY = PROJECT_ROOT / "assets" / "icons"


class GridPreviewDialog(QDialog):
    def __init__(
        self,
        entries: list[ImageEntry],
        parent: QWidget | None = None,
        *,
        options: PreprocessOptions,
        grid_type: str = DEFAULT_GRID_TYPE,
        initial_image_path: Path | None = None,
        image_prefetch_count: int = DEFAULT_IMAGE_PREFETCH_COUNT,
    ) -> None:
        super().__init__(parent)
        if not entries:
            raise ValueError("Grid preview requires at least one image.")
        self._entries = entries
        self._options = options
        self._current_index = next(
            (
                index
                for index, entry in enumerate(entries)
                if entry.image_path == initial_image_path
            ),
            0,
        )
        self._image_prefetch_count = max(0, image_prefetch_count)
        self._grid_type = (
            grid_type if grid_type in GRID_TYPES else DEFAULT_GRID_TYPE
        )
        self._plan: PreprocessPlan | None = None
        self._measurement: tuple[int, int] | None = None

        self.setWindowTitle("Grid Preview")
        self.resize(1000, 720)
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_label.setWordWrap(True)
        self.image_view = ImageView()
        self.image_view.set_scrolling_behavior(SCROLL_PAN)
        self.image_view.set_ctrl_wheel_zoom_enabled(False)
        self.image_view.set_grid_size(self.grid_size)
        self.image_view.set_grid_measurement_enabled(True)
        self.image_view.grid_measurement_changed.connect(
            self._measurement_changed
        )
        self.image_view.navigation_requested.connect(self._move)
        self.status_label = QLabel()
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.status_label.setWordWrap(True)

        self.previous_button = self._tool_button(
            "previous.svg", "Previous image", self._previous
        )
        self.next_button = self._tool_button(
            "next.svg", "Next image", self._next
        )
        self.zoom_out_button = self._tool_button(
            "zoom-out.svg", "Zoom out", self.image_view.zoom_out
        )
        self.fit_button = self._tool_button(
            "fit.svg", "Fit to window", self._toggle_fit, checkable=True
        )
        self.fit_button.setChecked(True)
        self.zoom_in_button = self._tool_button(
            "zoom-in.svg", "Zoom in", self.image_view.zoom_in
        )
        self.image_view.fit_to_window_changed.connect(self.fit_button.setChecked)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        controls = QHBoxLayout()
        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)
        controls.addStretch(1)
        controls.addWidget(self.zoom_out_button)
        controls.addWidget(self.fit_button)
        controls.addWidget(self.zoom_in_button)
        controls.addStretch(1)
        controls.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.path_label)
        layout.addWidget(self.image_view, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(controls)

        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        self._mouse_navigation = MouseNavigation(
            self, back=[self.previous_button], forward=[self.next_button]
        )
        self.preview_loader = PreviewLoader(self)
        self.preview_loader.loaded.connect(self._image_loaded)
        self._load_current()

    @property
    def grid_size(self) -> int:
        return GRID_TYPES[self._grid_type][1]

    def _tool_button(
        self,
        icon_name: str,
        tooltip: str,
        callback,
        *,
        checkable: bool = False,
    ) -> QToolButton:
        button = QToolButton()
        button.setIcon(QIcon(str(_ICON_DIRECTORY / icon_name)))
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setFixedSize(32, 32)
        button.clicked.connect(callback)
        return button

    def _toggle_fit(self, checked: bool) -> None:
        self.image_view.set_fit_to_window(checked)

    def _current_path(self) -> Path:
        return self._entries[self._current_index].image_path

    def _load_current(self) -> None:
        path = self._current_path()
        self._plan = None
        self._measurement = None
        self.path_label.setText(
            f"{self._current_index + 1}/{len(self._entries)} | {path}"
        )
        self.image_view.clear_image("Loading image...")
        self.status_label.setText("Preparing grid preview...")
        next_index = self._current_index + 1
        prefetch_paths = [
            entry.image_path
            for entry in self._entries[
                next_index : next_index + self._image_prefetch_count
            ]
        ]
        self.preview_loader.load(path, prefetch_paths)
        self.previous_button.setEnabled(self._current_index > 0)
        self.next_button.setEnabled(self._current_index + 1 < len(self._entries))

    def _image_loaded(self, image: QImage, error: str) -> None:
        if error or image.isNull():
            message = error or "Could not read image"
            self.image_view.clear_image(f"Could not display image\n{message}")
            self.status_label.setText(message)
            return
        plan = create_preprocess_plan((image.width(), image.height()), self._options)
        processed = image
        if plan.resized_size != plan.source_size:
            processed = image.scaled(
                *plan.resized_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        left, top, right, bottom = plan.crop_box
        if plan.output_size != plan.resized_size:
            processed = processed.copy(
                left, top, right - left, bottom - top
            )
        self._plan = plan
        self.image_view.set_image(processed)
        self._update_status()

    def _measurement_changed(self, width: int, height: int) -> None:
        self._measurement = (width, height) if width and height else None
        self._update_status()

    def _update_status(self) -> None:
        if self._plan is None:
            return
        plan = self._plan
        grid_width = (plan.output_size[0] + self.grid_size - 1) // self.grid_size
        grid_height = (plan.output_size[1] + self.grid_size - 1) // self.grid_size
        label = GRID_TYPES[self._grid_type][0].split(" (")[0]
        self.status_label.setText(
            f"Original {plan.source_size[0]} x {plan.source_size[1]} | "
            f"Bucket {plan.target_size[0]} x {plan.target_size[1]} | "
            f"Resized {plan.resized_size[0]} x {plan.resized_size[1]} | "
            f"Output {plan.output_size[0]} x {plan.output_size[1]} | "
            f"{label} grid {grid_width} x {grid_height}"
            + (
                f" | Selection {self._measurement[0]} x "
                f"{self._measurement[1]} grids"
                if self._measurement is not None
                else ""
            )
        )

    def _move(self, offset: int) -> None:
        target = self._current_index + offset
        if 0 <= target < len(self._entries):
            self._current_index = target
            self._load_current()

    def _previous(self) -> None:
        self._move(-1)

    def _next(self) -> None:
        self._move(1)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and isinstance(watched, QWidget)
            and watched.window() is self
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            if event.key() in {Qt.Key.Key_Left, Qt.Key.Key_Back}:
                self._previous()
                return True
            if event.key() in {Qt.Key.Key_Right, Qt.Key.Key_Forward}:
                self._next()
                return True
        return super().eventFilter(watched, event)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self.preview_loader.clear()
        event.accept()

    @override
    def done(self, result: int) -> None:
        self.preview_loader.clear()
        super().done(result)
