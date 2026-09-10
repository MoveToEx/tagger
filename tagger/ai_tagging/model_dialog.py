from __future__ import annotations

from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from tagger.ai_tagging.models import MODEL_REPOSITORIES
from tagger.paths import get_model_directory
from tagger.ui.widgets import stabilize_widget_size

from . import cache


class _ModelDownloadWorker(QObject):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        repo_id: str,
        proxy: str | None,
        cache_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.repo_id = repo_id
        self.proxy = proxy
        self.cache_dir = cache_dir

    def run(self) -> None:
        try:
            from huggingface_hub import snapshot_download

            cache._configure_huggingface_proxy(self.proxy)
            snapshot_download(repo_id=self.repo_id, cache_dir=self.cache_dir)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(self.repo_id)


class ModelManagementDialog(QDialog):
    def __init__(self, parent=None, *, proxy: str | None = None) -> None:
        super().__init__(parent)
        self.proxy = proxy.strip() if proxy is not None else None
        self._thread: QThread | None = None
        self._worker: _ModelDownloadWorker | None = None
        self.setWindowTitle("AI Tagging Models")
        self.resize(680, 360)

        self.download_location_input = QComboBox()
        self.download_location_input.addItem("User home directory", "user")
        self.download_location_input.addItem("Local data directory", "local")
        stabilize_widget_size(self.download_location_input)
        self.download_location_input.currentIndexChanged.connect(
            self._download_location_changed
        )
        self.download_location_path_label = QLabel()
        self.download_location_path_label.setWordWrap(True)
        self.download_location_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        destination_layout = QFormLayout()
        destination_layout.addRow("Download location", self.download_location_input)
        destination_layout.addRow("Directory", self.download_location_path_label)

        self.models = QTreeWidget()
        self.models.setHeaderLabels(["Model", "Repository", "Status", "Location"])
        self.models.setRootIsDecorated(False)
        self.models.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.models.itemSelectionChanged.connect(self._update_buttons)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.download_button = QPushButton("Download Selected")
        self.close_button = QPushButton("Close")
        self.download_button.clicked.connect(self._download_selected)
        self.close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.download_button)
        layout = QVBoxLayout(self)
        layout.addLayout(destination_layout)
        layout.addWidget(self.models, 1)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)
        self._download_location_changed()
        self._refresh_models()

    def _refresh_models(self) -> None:
        self.models.clear()
        for name, repo_id in MODEL_REPOSITORIES.items():
            locations = cache._cached_model_locations(repo_id)
            status = "Available" if locations else "Not downloaded"
            item = QTreeWidgetItem([name, repo_id, status, ", ".join(locations)])
            item.setData(0, Qt.ItemDataRole.UserRole, repo_id)
            self.models.addTopLevelItem(item)
        self.models.resizeColumnToContents(0)
        self.models.resizeColumnToContents(1)
        self.models.resizeColumnToContents(2)
        self.models.resizeColumnToContents(3)
        if self.models.topLevelItemCount():
            first_item = self.models.topLevelItem(0)
            if first_item is not None:
                self.models.setCurrentItem(first_item)
        self._update_buttons()

    def _selected_repo(self) -> str | None:
        item = self.models.currentItem()
        return str(item.data(0, Qt.ItemDataRole.UserRole)) if item else None

    def _update_buttons(self) -> None:
        self.download_button.setEnabled(
            self._thread is None and self._selected_repo() is not None
        )
        self.download_location_input.setEnabled(self._thread is None)

    def _selected_download_cache_directory(self) -> Path | None:
        if self.download_location_input.currentData() == "local":
            return get_model_directory()
        return None

    def _download_location_changed(self, _index: int = -1) -> None:
        directory = self._selected_download_cache_directory()
        if directory is None:
            directory = cache._user_model_cache_directory()
        self.download_location_path_label.setText(str(directory))

    def _download_selected(self) -> None:
        repo_id = self._selected_repo()
        if repo_id is None or self._thread is not None:
            return
        self.status_label.setText(f"Downloading {repo_id}...")
        self.close_button.setEnabled(False)
        thread = QThread(self)
        worker = _ModelDownloadWorker(
            repo_id,
            self.proxy,
            self._selected_download_cache_directory(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._download_completed)
        worker.failed.connect(self._download_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread = thread
        self._worker = worker
        self._update_buttons()
        thread.start()

    def set_proxy(self, proxy: str | None) -> None:
        self.proxy = proxy.strip() if proxy is not None else None

    def _download_completed(self, repo_id: str) -> None:
        self.status_label.setText(f"Downloaded {repo_id}.")
        self._refresh_models()

    def _download_failed(self, message: str) -> None:
        self.status_label.setText(message)
        QMessageBox.critical(self, "Could Not Download Model", message)

    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.close_button.setEnabled(True)
        self._refresh_models()

    @override
    def reject(self) -> None:
        if self._thread is None:
            super().reject()
