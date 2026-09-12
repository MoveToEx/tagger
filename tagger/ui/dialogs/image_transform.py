from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
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
        self.progress_bar.setRange(0, len(candidates))
        failures: list[str] = []
        for number, path in enumerate(candidates, 1):
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
                    self.progress_bar.setValue(number)
                    self.status_label.setText(f"Skipped: {path.name}")
                    continue
                overwrite = True
            self.status_label.setText(f"Transforming: {path.name}")
            try:
                output = convert_image(path, target_format, overwrite=overwrite)
            except (OSError, ValueError) as exc:
                failures.append(f"{path.name}: {exc}")
            else:
                if output is not None:
                    self.converted_paths.append(output)
            self.progress_bar.setValue(number)

        self._running = False
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
