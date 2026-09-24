from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import cast, override

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.probing import (
    DEFAULT_PROBE_MINIMUM_LEVEL,
    ProbeResult,
    ProbeRule,
    probe_entries,
)


class _ProbeSignals(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)


class _ProbeWorker(QRunnable):
    def __init__(
        self,
        entries: list[ImageEntry],
        rules: list[ProbeRule],
        *,
        root_directory: Path | None,
        use_tag_set: bool,
        minimum_level: str,
    ) -> None:
        super().__init__()
        self.entries = entries
        self.rules = rules
        self.root_directory = root_directory
        self.use_tag_set = use_tag_set
        self.minimum_level = minimum_level
        self.signals = _ProbeSignals()

    @override
    def run(self) -> None:
        try:
            results = probe_entries(
                self.entries,
                self.rules,
                self.signals.progress.emit,
                root_directory=self.root_directory,
                use_tag_set=self.use_tag_set,
                minimum_level=self.minimum_level,
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.completed.emit(results)


class ProbeProgressDialog(QDialog):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        entries: Sequence[ImageEntry],
        rules: Sequence[ProbeRule],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
        use_tag_set: bool = True,
        minimum_level: str = DEFAULT_PROBE_MINIMUM_LEVEL,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Probing Tags")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(440)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self.current_file_label = QLabel("Preparing probe...")
        self.current_file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(entries))
        self.progress_bar.setValue(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.current_file_label)
        layout.addWidget(self.progress_bar)

        self._running = False
        self._worker = _ProbeWorker(
            list(entries),
            list(rules),
            root_directory=root_directory,
            use_tag_set=use_tag_set,
            minimum_level=minimum_level,
        )
        self._worker.signals.progress.connect(self._update_progress)
        self._worker.signals.completed.connect(self._complete)
        self._worker.signals.failed.connect(self._fail)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        QThreadPool.globalInstance().start(self._worker)

    def _update_progress(
        self, completed: int, total: int, current_file: str
    ) -> None:
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(completed)
        self.current_file_label.setText(f"Probing: {current_file}")

    def _complete(self, results: list[ProbeResult]) -> None:
        self._running = False
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.accept()
        self.completed.emit(results)

    def _fail(self, message: str) -> None:
        self._running = False
        self.reject()
        self.failed.emit(message)

    @override
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


class ProbeDialog(QDialog):
    image_activated = Signal(Path)

    def __init__(
        self,
        results: Sequence[ProbeResult],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
        scanned_count: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.results = list(results)
        self.root_directory = root_directory
        self.setWindowTitle("Tag Probe Results")
        self.resize(880, 580)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        total = scanned_count if scanned_count is not None else len(results)
        self.summary_label = QLabel(
            f"Found questionable tags in {len(results)} of {total} image(s)."
        )
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.summary_label.setWordWrap(True)

        self.image_list = QListWidget()
        self.image_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.image_list.setWordWrap(True)
        self.image_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.image_list.currentRowChanged.connect(self._show_result)
        self.image_list.itemDoubleClicked.connect(self._activate_image)
        self.questionable_images = self.image_list

        for result in self.results:
            item = QListWidgetItem(self._relative_path(result.entry.image_path))
            item.setToolTip(str(result.entry.image_path))
            self.image_list.addItem(item)

        self.current_image_label = QLabel("No questionable image selected")
        self.current_image_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.current_image_label.setWordWrap(True)
        self.problem_list = _IssueTreeWidget()
        self.problem_list.setHeaderLabels(["Level", "Message"])
        self.problem_list.setRootIsDecorated(False)
        self.problem_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.problem_list.setColumnCount(2)
        self.problem_list.setUniformRowHeights(False)
        self.problem_list.setWordWrap(True)
        self.problem_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.problem_list.header().setStretchLastSection(True)
        self.problem_list.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.problem_list.header().resizeSection(0, 84)
        self.problem_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.detected_problems = self.problem_list

        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(0, 0, 8, 0)
        image_layout.addWidget(QLabel("Questionable images"))
        image_layout.addWidget(self.image_list, 1)

        problem_panel = QWidget()
        problem_layout = QVBoxLayout(problem_panel)
        problem_layout.setContentsMargins(8, 0, 0, 0)
        problem_layout.addWidget(QLabel("Detected problems"))
        problem_layout.addWidget(self.current_image_label)
        problem_layout.addWidget(self.problem_list, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(image_panel)
        self.splitter.addWidget(problem_panel)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([340, 540])

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.splitter, 1)
        layout.addLayout(buttons)

        if self.results:
            self.image_list.setCurrentRow(0)

    def _relative_path(self, path: Path) -> str:
        if self.root_directory is not None:
            try:
                return path.relative_to(self.root_directory).as_posix()
            except ValueError:
                pass
        if self.results:
            try:
                root = Path(
                    os.path.commonpath(
                        [str(result.entry.image_path.parent) for result in self.results]
                    )
                )
                return path.relative_to(root).as_posix()
            except (ValueError, OSError):
                pass
        return path.name

    def _show_result(self, row: int) -> None:
        self.problem_list.clear()
        if not 0 <= row < len(self.results):
            self.current_image_label.setText("No questionable image selected")
            return
        result = self.results[row]
        self.current_image_label.setText(
            self._relative_path(result.entry.image_path)
        )
        for issue in result.issues:
            item = _IssueTreeItem(
                [issue.level, issue.message],
                legacy_text=f"{issue.rule_identifier}: {issue.message}",
            )
            item.setToolTip(1, issue.message)
            self.problem_list.addItem(item)

    def _activate_image(self, item: QListWidgetItem) -> None:
        row = self.image_list.row(item)
        if 0 <= row < len(self.results):
            self.image_activated.emit(self.results[row].entry.image_path)


ProbeResultsDialog = ProbeDialog


class _IssueTreeItem(QTreeWidgetItem):
    def __init__(
        self, labels: list[str], *, legacy_text: str = ""
    ) -> None:
        super().__init__(labels)
        self._legacy_text = legacy_text

    def text(self, *args: int) -> str:
        if not args and self._legacy_text:
            return self._legacy_text
        return super().text(args[0] if args else 0)


class _IssueTreeWidget(QTreeWidget):
    """Flat issue tree with the old QListWidget accessors kept for callers."""

    def count(self) -> int:
        return self.topLevelItemCount()

    def item(self, index: int) -> _IssueTreeItem:
        return cast(_IssueTreeItem, super().topLevelItem(index))

    def addItem(self, item: QTreeWidgetItem) -> None:
        self.addTopLevelItem(item)
