from __future__ import annotations

from pathlib import Path
from typing import Callable, cast

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QTimer, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QPixmap, QImage, QFont, QResizeEvent, QCloseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget, QProgressBar, QDialog

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.transparency import TransparencySelectionDialog
from tagger.ui.python_syntax import PythonSyntaxHighlighter

DEFAULT_PIXEL_TRANSFORM = """import numpy as np

def transform(pixels: np.array) -> np.array:
\treturn pixels
"""

class PixelTransformDialog(TransparencySelectionDialog):
    def __init__(self, entries: list[ImageEntry], parent: QWidget | None = None, *, root_directory: Path | None = None) -> None:
        super().__init__(entries, parent, root_directory=root_directory, title="Pixel Transform", prompt="Select images to transform", action_text="Next")
        self.selected_paths_for_transform: list[Path] = []
        self.setMinimumSize(900, 650)

    def _accept_selection(self) -> None:
        paths = self.selected_paths
        if not paths:
            return
        self.selected_paths_for_transform = paths
        self._show_script_stage()

    def _show_script_stage(self) -> None:
        layout = cast(QVBoxLayout, self.layout())
        self._selection_widgets = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None:
                self._selection_widgets.append(widget)
        for widget in self._selection_widgets:
            widget.hide()
        # The original action row is a layout, so hide its child buttons too.
        self.cancel_button.hide()
        self.remove_button.hide()
        self.setWindowTitle("Pixel Transform")
        self.code_input = QPlainTextEdit(); self.code_input.setPlainText(DEFAULT_PIXEL_TRANSFORM)
        font = QFont("Consolas"); font.setStyleHint(QFont.StyleHint.Monospace)
        self.code_input.setFont(font)
        self.code_input.setTabStopDistance(self.code_input.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter = PythonSyntaxHighlighter(self.code_input.document())
        self.preview_button = QPushButton("Preview"); self.preview_button.clicked.connect(self.preview_transform)
        self.run_button = QPushButton("Run"); self.run_button.clicked.connect(self.run_transform)
        self.back_button = QPushButton("Back"); self.back_button.clicked.connect(self._show_selection_stage)
        self.original_label = QLabel(); self.transformed_label = QLabel();
        self.error_label = QLabel(); self.error_label.setStyleSheet("QLabel { color: #b42318; }"); self.error_label.setWordWrap(True); self.error_label.hide()
        for label in (self.original_label, self.transformed_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter); label.setMinimumSize(280, 220)
        right = QVBoxLayout(); right.addWidget(QLabel("Original")); right.addWidget(self.original_label, 1); right.addWidget(QLabel("Transformed preview")); right.addWidget(self.transformed_label, 1)
        right_widget = QWidget(); right_widget.setLayout(right)
        split = QSplitter(Qt.Orientation.Horizontal); split.addWidget(self.code_input); split.addWidget(right_widget); split.setSizes([560, 340])
        self._script_widgets = [split]
        layout.addWidget(split)
        buttons = QHBoxLayout(); buttons.addWidget(self.back_button); buttons.addStretch(1); buttons.addWidget(self.preview_button); buttons.addWidget(self.run_button); layout.addLayout(buttons)
        self._script_button_layout = buttons
        layout.addWidget(self.error_label)
        self._load_original_preview()
        if getattr(self, "_original_pixmap", None) is not None:
            self._transformed_pixmap = self._original_pixmap
            self._fit_previews()
        QTimer.singleShot(0, self._fit_previews)

    def _show_selection_stage(self) -> None:
        layout = cast(QVBoxLayout, self.layout())
        if hasattr(self, "_script_button_layout"):
            while self._script_button_layout.count():
                item = self._script_button_layout.takeAt(0)
                widget = item.widget() if item is not None else None
                if widget is not None: widget.setParent(None)
            layout.removeItem(self._script_button_layout)
        for widget in getattr(self, "_script_widgets", []):
            widget.setParent(None); widget.deleteLater()
        for widget in getattr(self, "_selection_widgets", []):
            widget.show()
        self.cancel_button.show(); self.remove_button.show()

    def _load_original_preview(self) -> None:
        try:
            image = Image.open(self.selected_paths_for_transform[0]).convert("RGBA")
            data = image.tobytes(); q = QImage(data, image.width, image.height, QImage.Format.Format_RGBA8888).copy()
            self._original_pixmap = QPixmap.fromImage(q)
            self._fit_previews()
        except Exception: pass

    def _fit_previews(self) -> None:
        for label, pixmap in ((self.original_label, getattr(self, "_original_pixmap", None)), (self.transformed_label, getattr(self, "_transformed_pixmap", None))):
            if pixmap is not None and label.size().isValid():
                label.setPixmap(pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "original_label"):
            self._fit_previews()

    def _execute(self, path: Path) -> Image.Image:
        image = Image.open(path).convert("RGBA"); pixels = np.array(image)
        namespace: dict[str, object] = {"np": np}
        exec(compile(self.code_input.toPlainText(), "<pixel-transform>", "exec"), namespace)
        fn = namespace.get("transform")
        if not callable(fn): raise ValueError("Script must define transform(pixels: np.array) -> np.array")
        result = np.asarray(cast(Callable[[np.ndarray], object], fn)(pixels))
        if result.ndim not in (2, 3) or result.size == 0:
            raise ValueError("transform() must return a non-empty 2D or 3D image array")
        if result.ndim == 3 and result.shape[2] not in (1, 3, 4):
            raise ValueError("transform() must return 1, 3, or 4 channels")
        if not np.issubdtype(result.dtype, np.number):
            raise ValueError("transform() must return numeric pixel data")
        if result.dtype != np.uint8: result = np.clip(result, 0, 255).astype(np.uint8)
        return Image.fromarray(result).convert("RGBA")

    def preview_transform(self) -> None:
        try:
            self.error_label.hide()
            image = self._execute(self.selected_paths_for_transform[0]); q = QImage(image.tobytes(), image.width, image.height, QImage.Format.Format_RGBA8888).copy(); self._transformed_pixmap = QPixmap.fromImage(q); self._fit_previews()
        except Exception as exc:
            self._transformed_pixmap = None; self.transformed_label.clear(); self.error_label.setText(str(exc)); self.error_label.show()

    def run_transform(self) -> None:
        if QMessageBox.question(self, "Overwrite Images?", "The selected images will be overwritten. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes: return
        progress = PixelTransformProgressDialog(self.selected_paths_for_transform, self.code_input.toPlainText(), self)
        progress.failed.connect(lambda message: (self.error_label.setText(message), self.error_label.show()))
        progress.completed.connect(lambda: self.accept())
        progress.start(); progress.exec()


class _PixelSignals(QObject):
    progress = Signal(int, int, str)
    completed = Signal()
    failed = Signal(str)

class _PixelWorker(QRunnable):
    def __init__(self, paths: list[Path], code: str) -> None:
        super().__init__(); self.paths = paths; self.code = code; self.signals = _PixelSignals()
    def run(self) -> None:
        try:
            namespace: dict[str, object] = {"np": np}; exec(compile(self.code, "<pixel-transform>", "exec"), namespace)
            fn = namespace.get("transform")
            if not callable(fn): raise ValueError("Script must define transform(pixels: np.array) -> np.array")
            for number, path in enumerate(self.paths, 1):
                self.signals.progress.emit(number - 1, len(self.paths), path.name)
                with Image.open(path) as source: pixels = np.array(source.convert("RGBA"))
                result = np.asarray(cast(Callable[[np.ndarray], object], fn)(pixels))
                if result.ndim not in (2, 3) or result.size == 0 or (result.ndim == 3 and result.shape[2] not in (1, 3, 4)) or not np.issubdtype(result.dtype, np.number): raise ValueError("transform() returned invalid image data")
                result = np.clip(result, 0, 255).astype(np.uint8)
                image = Image.fromarray(result).convert("RGBA")
                if path.suffix.casefold() in {".jpg", ".jpeg"}: image = image.convert("RGB")
                image.save(path)
                self.signals.progress.emit(number, len(self.paths), path.name)
            self.signals.completed.emit()
        except Exception as exc: self.signals.failed.emit(str(exc))

class PixelTransformProgressDialog(QDialog):
    completed = Signal(); failed = Signal(str)
    def __init__(self, paths: list[Path], code: str, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.setWindowTitle("Applying Pixel Transform"); self.setWindowModality(Qt.WindowModality.WindowModal); self.setMinimumWidth(440)
        self.current_file_label = QLabel("Preparing images..."); self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, len(paths))
        layout = QVBoxLayout(self); layout.addWidget(self.current_file_label); layout.addWidget(self.progress_bar)
        self._running = False; self._worker = _PixelWorker(paths, code); self._worker.signals.progress.connect(self._update); self._worker.signals.completed.connect(self._complete); self._worker.signals.failed.connect(self._fail)
    def start(self) -> None:
        if not self._running: self._running = True; QThreadPool.globalInstance().start(self._worker)
    def _update(self, completed: int, total: int, name: str) -> None: self.progress_bar.setValue(completed); self.current_file_label.setText(f"Processing: {name}")
    def _complete(self) -> None: self._running = False; self.progress_bar.setValue(self.progress_bar.maximum()); self.completed.emit(); self.accept()
    def _fail(self, message: str) -> None: self._running = False; self.failed.emit(message); self.reject()
    def reject(self) -> None:
        if not self._running: super().reject()
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._running: event.ignore()
        else: super().closeEvent(event)
