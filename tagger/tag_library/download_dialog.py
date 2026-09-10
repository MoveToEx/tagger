from __future__ import annotations

from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from tagger.paths import get_tag_library_path
from tagger.tag_library.download import download_danbooru_tags


class _DownloadWorker(QObject):
    progress = Signal(int, str)
    completed = Signal(int, str)
    failed = Signal(str)

    def __init__(
        self, minimum_posts: int, proxy: str | None, destination: Path
    ) -> None:
        super().__init__()
        self.minimum_posts = minimum_posts
        self.proxy = proxy
        self.destination = destination

    def run(self) -> None:
        try:
            count = download_danbooru_tags(
                self.destination,
                minimum_posts=self.minimum_posts,
                proxy=self.proxy,
                progress=self.progress.emit,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(count, str(self.destination))


class DownloadTagsDialog(QDialog):
    downloaded = Signal(str)
    library_changed = Signal(str)

    def __init__(
        self,
        parent=None,
        destination: Path | None = None,
        *,
        proxy: str | None = "",
    ) -> None:
        super().__init__(parent)
        self.destination = (
            get_tag_library_path() if destination is None else destination
        )
        self.proxy = proxy.strip() if proxy is not None else None
        self._thread: QThread | None = None
        self._worker: _DownloadWorker | None = None
        self.setWindowTitle("Manage Tag Library")
        self.setMinimumWidth(520)

        self.minimum_posts_input = QSpinBox()
        self.minimum_posts_input.setRange(0, 2_000_000_000)
        self.minimum_posts_input.setValue(20)
        self.minimum_posts_input.setSuffix(" posts")
        self.destination_label = QLabel(str(self.destination))
        self.destination_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        form = QFormLayout()
        form.addRow("Minimum post count", self.minimum_posts_input)
        form.addRow("Save to", self.destination_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.status_label = QLabel("Ready to download.")
        self.status_label.setWordWrap(True)
        self.download_button = QPushButton("Download")
        self.close_button = QPushButton("Close")
        self.download_button.clicked.connect(self._start_download)
        self.close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.download_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addLayout(buttons)

    def _start_download(self) -> None:
        if self._thread is not None:
            return
        self.download_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.minimum_posts_input.setEnabled(False)
        self.progress_bar.setValue(0)
        thread = QThread(self)
        worker = _DownloadWorker(
            self.minimum_posts_input.value(),
            self.proxy,
            self.destination,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._show_progress)
        worker.completed.connect(self._download_completed)
        worker.failed.connect(self._download_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _show_progress(self, value: int, message: str) -> None:
        self.progress_bar.setValue(value)
        self.status_label.setText(message)

    def _download_completed(self, count: int, path: str) -> None:
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Saved {count:,} tags to {path}")
        self.downloaded.emit(path)
        self.library_changed.emit(path)

    def _download_failed(self, message: str) -> None:
        self.status_label.setText(message)
        QMessageBox.critical(self, "Could Not Download Tags", message)

    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.close_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self.minimum_posts_input.setEnabled(True)

    def set_proxy(self, proxy: str | None) -> None:
        self.proxy = proxy.strip() if proxy is not None else None

    @override
    def reject(self) -> None:
        if self._thread is None:
            super().reject()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is None:
            event.accept()
        else:
            event.ignore()
