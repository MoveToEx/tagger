from __future__ import annotations

from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.image_processing import convert_image


class _TransformSignals(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)


class _TransformOperation:
    def __init__(
        self,
        path: Path,
        *,
        overwrite: bool = False,
        skipped: bool = False,
    ) -> None:
        self.path = path
        self.overwrite = overwrite
        self.skipped = skipped


class _TransformWorker(QRunnable):
    def __init__(self, operations: list[_TransformOperation], target_format: str) -> None:
        super().__init__()
        self.operations = operations
        self.target_format = target_format
        self.signals = _TransformSignals()

    @override
    def run(self) -> None:
        converted: list[Path] = []
        failures: list[str] = []
        total = len(self.operations)
        for number, operation in enumerate(self.operations, 1):
            if operation.skipped:
                self.signals.progress.emit(
                    number, total, f"Skipped: {operation.path.name}"
                )
                continue

            self.signals.progress.emit(
                number - 1, total, f"Transforming: {operation.path.name}"
            )
            try:
                output = convert_image(
                    operation.path,
                    self.target_format,
                    overwrite=operation.overwrite,
                )
            except (OSError, ValueError) as exc:
                failures.append(f"{operation.path.name}: {exc}")
            else:
                if output is not None:
                    converted.append(output)
            self.signals.progress.emit(number, total, operation.path.name)

        self.signals.completed.emit((converted, failures))


class ImageTransformDialog(QDialog):
    """Convert catalog images to a selected format."""

    completed = Signal(int)

    def __init__(
        self,
        entries: list[ImageEntry],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Transform Images")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(420)

        self.format_combo = QComboBox()
        self.format_combo.addItem("JPG", "jpg")
        self.format_combo.addItem("PNG", "png")
        self.format_combo.addItem("WEBP", "webp")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(entries))
        self.progress_bar.setValue(0)
        self.status_label = QLabel("Choose an output format.")
        self.status_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Transform")
        self.buttons.accepted.connect(self._start)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Output format:"))
        layout.addWidget(self.format_combo)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.buttons)

        self._entries = list(entries)
        self.converted_paths: list[Path] = []
        self._running = False
        self._worker: _TransformWorker | None = None

    def _start(self) -> None:
        if self._running:
            return
        target_format = str(self.format_combo.currentData())
        candidates = [
            entry.image_path
            for entry in self._entries
            if entry.image_path.suffix.casefold().removeprefix(".")
            != target_format
        ]
        if not candidates:
            self.status_label.setText("No images need conversion.")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return

        self._running = True
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(False)
        self.format_combo.setEnabled(False)
        operations: list[_TransformOperation] = []
        for path in candidates:
            destination = path.with_suffix(f".{target_format}")
            overwrite = False
            if destination.exists():
                answer = QMessageBox.question(
                    self,
                    "Overwrite Existing Image?",
                    f"{destination.name} already exists. Overwrite it?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Cancel:
                    break
                if answer != QMessageBox.StandardButton.Yes:
                    operations.append(_TransformOperation(path, skipped=True))
                    continue
                overwrite = True
            operations.append(
                _TransformOperation(path, overwrite=overwrite)
            )

        if not operations:
            self._finish(([], []))
            return

        self.progress_bar.setRange(0, len(operations))
        self.progress_bar.setValue(0)
        self._worker = _TransformWorker(operations, target_format)
        self._worker.signals.progress.connect(self._update_progress)
        self._worker.signals.completed.connect(self._finish)
        QThreadPool.globalInstance().start(self._worker)

    def _update_progress(self, completed: int, total: int, status: str) -> None:
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(completed)
        self.status_label.setText(status)

    def _finish(self, result: tuple[list[Path], list[str]]) -> None:
        converted, failures = result
        self.converted_paths = converted
        self._worker = None
        self._running = False
        self.progress_bar.setValue(self.progress_bar.maximum())
        if failures:
            QMessageBox.warning(
                self,
                "Some Images Could Not Be Transformed",
                "\n".join(failures),
            )
        self.completed.emit(len(self.converted_paths))
        self.accept()

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
