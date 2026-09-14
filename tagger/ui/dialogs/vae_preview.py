from __future__ import annotations

from pathlib import Path
from typing import override

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QCloseEvent, QIcon, QImage, QImageReader, QKeyEvent
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

from tagger.ai_tagging import cache
from tagger.ai_tagging.models import QWEN_IMAGE_VAE
from tagger.domain.models import ImageEntry
from tagger.paths import PROJECT_ROOT
from tagger.ui.mouse_navigation import MouseNavigation
from tagger.ui.preview.config import DEFAULT_IMAGE_PREFETCH_COUNT
from tagger.ui.preview.loader import PreviewLoader
from tagger.ui.preview.view import ImageView
from tagger.vae_preview.process import VaePreviewProcess


_ICON_DIRECTORY = PROJECT_ROOT / "assets" / "icons"


class VaePreviewDialog(QDialog):
    def __init__(
        self,
        entries: list[ImageEntry],
        parent=None,
        *,
        initial_image_path: Path | None = None,
        scrolling_behavior: str,
        image_prefetch_count: int = DEFAULT_IMAGE_PREFETCH_COUNT,
    ) -> None:
        super().__init__(parent)
        if not entries:
            raise ValueError("VAE preview requires at least one image.")
        self._entries = entries
        self._current_index = next(
            (
                index
                for index, entry in enumerate(entries)
                if entry.image_path == initial_image_path
            ),
            0,
        )
        self._image_prefetch_count = max(0, image_prefetch_count)
        self._original_image: QImage | None = None
        self._decoded_images: dict[Path, QImage] = {}
        self._decode_failures: dict[Path, str] = {}
        self._request_paths: dict[int, Path] = {}
        self._active_request_id: int | None = None

        self.setWindowTitle("VAE Preview")
        self.resize(1000, 720)
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_label.setWordWrap(True)
        self.image_view = ImageView()
        self.image_view.set_scrolling_behavior(scrolling_behavior)
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
        self.preview_loader.loaded.connect(self._original_loaded)
        cache_dir = cache._preferred_model_cache_directory(
            QWEN_IMAGE_VAE.repo_id, QWEN_IMAGE_VAE.required_files
        )
        self.vae_process = VaePreviewProcess(
            QWEN_IMAGE_VAE, cache_dir, self
        )
        self.vae_process.progress.connect(self._decode_progressed)
        self.vae_process.decoded.connect(self._decode_completed)
        self.vae_process.failed.connect(self._decode_failed)
        self.vae_process.start()
        self._load_current()

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
        self._original_image = None
        self.path_label.setText(
            f"{self._current_index + 1}/{len(self._entries)} | {path}"
        )
        self.image_view.clear_image("Loading image...")
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
        failure = self._decode_failures.get(path)
        self.status_label.setText(failure or "Encoding and decoding image...")
        self._ensure_current_decode()

    def _ensure_current_decode(self) -> None:
        path = self._current_path()
        if (
            path in self._decoded_images
            or path in self._decode_failures
            or self._active_request_id is not None
        ):
            self._show_current()
            return
        request_id = self.vae_process.decode(path)
        self._request_paths[request_id] = path
        self._active_request_id = request_id

    def _show_current(self) -> None:
        if self._original_image is None:
            return
        decoded = self._decoded_images.get(self._current_path())
        if decoded is None:
            self.image_view.set_image(self._original_image)
            return
        self.image_view.set_comparison_images(self._original_image, decoded)
        self.status_label.setText("Decoded / Original")

    def _original_loaded(self, image: QImage, error: str) -> None:
        if error or image.isNull():
            message = error or "Could not read image"
            self.image_view.clear_image(f"Could not display image\n{message}")
            return
        self._original_image = image
        self._show_current()

    def _decode_progressed(self, request_id: int, message: str) -> None:
        if request_id == -1 or request_id == self._active_request_id:
            self.status_label.setText(message)

    def _decode_completed(
        self, request_id: int, image_path: Path, output_path: Path
    ) -> None:
        requested_path = self._request_paths.pop(request_id, image_path)
        if request_id == self._active_request_id:
            self._active_request_id = None
        reader = QImageReader(str(output_path))
        decoded = reader.read()
        if decoded.isNull():
            self._decode_failures[requested_path] = (
                reader.errorString() or "Could not read the decoded image."
            )
        else:
            self._decoded_images[requested_path] = decoded
        if requested_path == self._current_path():
            self._show_current()
        self._ensure_current_decode()

    def _decode_failed(self, request_id: int, message: str) -> None:
        requested_path = self._request_paths.pop(request_id, None)
        if request_id == self._active_request_id:
            self._active_request_id = None
        if requested_path is not None:
            self._decode_failures[requested_path] = message
        if request_id == -1 or requested_path == self._current_path():
            self.status_label.setText(message)
        if request_id != -1:
            self._ensure_current_decode()

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
        self.vae_process.stop()
        event.accept()

    @override
    def done(self, result: int) -> None:
        self.preview_loader.clear()
        self.vae_process.stop()
        super().done(result)
