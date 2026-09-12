from __future__ import annotations

from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFontMetrics
from PySide6.QtWidgets import (
    QComboBox, QDialog, QLabel, QMessageBox, QProgressBar, QVBoxLayout, QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.image_processing import convert_image, image_has_alpha
from tagger.ui.dialogs.transparency import TransparencySelectionDialog
from tagger.ui.widgets import stabilize_widget_size


class ImageTransformDialog(TransparencySelectionDialog):
    def __init__(
        self,
        entries: list[ImageEntry],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
    ) -> None:
        super().__init__(
            entries, parent, root_directory=root_directory,
            title="Convert Images", prompt="Select images to convert", action_text="Convert",
        )
        self.format_combo = QComboBox(self)
        self.format_combo.addItems(["PNG", "JPEG", "WEBP"])
        stabilize_widget_size(self.format_combo)
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        layout.insertWidget(2, QLabel("Target format:"))
        layout.insertWidget(3, self.format_combo)

    @override
    def _accept_selection(self) -> None:
        paths = self.selected_paths
        target = self.format_combo.currentText().lower()
        target = "jpg" if target == "jpeg" else target
        candidates = [path for path in paths if path.suffix.lower().lstrip(".") != target]
        destinations = [path.with_suffix("." + target) for path in candidates]
        seen: set[Path] = set()
        conflicts: list[Path] = []
        for destination in destinations:
            if destination.exists() or destination in seen:
                conflicts.append(destination)
            seen.add(destination)
        if conflicts:
            QMessageBox.warning(
                self, "Conversion Conflict",
                "The following files already exist:\n" + "\n".join(path.name for path in conflicts),
            )
            return
        if target == "jpg" and any(image_has_alpha(path) for path in candidates):
            if QMessageBox.question(
                self, "JPEG Transparency", "JPEG cannot preserve transparency. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
        self.selected_paths_for_conversion = candidates
        self.target_format = target
        self.accept()


class _Signals(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)


class _Worker(QRunnable):
    def __init__(self, paths: list[Path], target: str) -> None:
        super().__init__()
        self.paths = paths
        self.target = target
        self.signals = _Signals()

    @override
    def run(self) -> None:
        done: list[Path] = []
        failures: list[str] = []
        for index, path in enumerate(self.paths, 1):
            self.signals.progress.emit(index - 1, len(self.paths), path.name)
            try:
                done.append(convert_image(path, self.target) or path)
            except (OSError, ValueError) as exc:
                failures.append(f"{path.name}: {exc}")
            self.signals.progress.emit(index, len(self.paths), path.name)
        self.signals.completed.emit((done, failures))


class ConvertProgressDialog(QDialog):
    completed = Signal(object)

    def __init__(
        self, paths: list[Path], target: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Converting Images")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setFixedWidth(640)
        self.label = QLabel("Preparing images...")
        self.label.setMinimumWidth(600)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(paths))
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        self._running = False
        self._worker = _Worker(paths, target)
        self._worker.signals.progress.connect(self._update)
        self._worker.signals.completed.connect(self._complete)

    def start(self) -> None:
        self._running = True
        QThreadPool.globalInstance().start(self._worker)

    def _update(self, completed: int, total: int, name: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(completed)
        self.label.setToolTip(name)
        self.label.setText(QFontMetrics(self.label.font()).elidedText(
            name, Qt.TextElideMode.ElideMiddle, self.label.width(),
        ))

    def _complete(self, result: tuple[list[Path], list[str]]) -> None:
        self._running = False
        self.completed.emit(result)
        self.accept()

    @override
    def reject(self) -> None:
        if not self._running:
            super().reject()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._running:
            event.ignore()
        else:
            super().closeEvent(event)
