from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Event
from typing import override

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QCloseEvent, QImage
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from .deduplication import (
    THRESHOLDS,
    DeduplicationSession,
    DuplicateScanResult,
    KeepChoice,
    find_duplicate_pairs,
)
from .delete_filter import DeleteFilterCommitResult, DeleteFilterProgressDialog
from .domain import ImageEntry
from .preview import ImageView, PreviewLoader
from .trash import SYSTEM_RECYCLE_BIN, UNLINK, delete_file
from .widgets import stabilize_widget_size


ENTRY_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class _ScanSignals(QObject):
    progress = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)


class _ScanWorker(QRunnable):
    def __init__(self, paths: list[Path], threshold: int) -> None:
        super().__init__()
        self.paths = paths
        self.threshold = threshold
        self.cancelled = Event()
        self.signals = _ScanSignals()

    @override
    def run(self) -> None:
        try:
            result = find_duplicate_pairs(
                self.paths,
                self.threshold,
                progress=self.signals.progress.emit,
                cancelled=self.cancelled.is_set,
            )
            if not self.cancelled.is_set():
                self.signals.completed.emit(result)
        except Exception as exc:
            if not self.cancelled.is_set():
                self.signals.failed.emit(str(exc))


class DeduplicateDialog(QDialog):
    """Review similar images and defer all file removal until Finish."""

    def __init__(
        self,
        entries: Sequence[ImageEntry],
        parent=None,
        *,
        root_directory: Path,
        file_deleter: Callable[[Path], bool] | None = None,
        deletion_behavior: str = SYSTEM_RECYCLE_BIN,
    ) -> None:
        super().__init__(parent)
        self.entries = list(entries)
        self._root_directory = root_directory
        self.deletion_behavior = deletion_behavior
        self._file_deleter = file_deleter or (
            lambda path: delete_file(path, deletion_behavior)
        )
        self._worker: _ScanWorker | None = None
        self._allow_close = False
        self._committing = False
        self.session = DeduplicationSession([])
        self.current_index = -1
        self.commit_result: DeleteFilterCommitResult | None = None

        self.setWindowTitle("Deduplicate")
        self.resize(1200, 760)
        self.pages = QStackedWidget()
        self.selection_page = self._create_selection_page()
        self.review_page = self._create_review_page()
        self.pages.addWidget(self.selection_page)
        self.pages.addWidget(self.review_page)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.back_button = QPushButton("Previous")
        self.back_button.clicked.connect(lambda: self._navigate(-1))
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(lambda: self._navigate(1))
        self.finish_button = QPushButton("Finish")
        self.finish_button.clicked.connect(self._finish)
        self.review_controls = QWidget()
        navigation = QHBoxLayout(self.review_controls)
        navigation.setContentsMargins(0, 0, 0, 0)
        navigation.addWidget(self.back_button)
        navigation.addWidget(self.next_button)
        navigation.addWidget(self.finish_button)
        self.review_controls.hide()
        footer = QHBoxLayout()
        footer.addWidget(self.cancel_button)
        footer.addStretch(1)
        footer.addWidget(self.review_controls)
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)
        layout.addLayout(footer)
        self._populate_tree()
        self.folder_tree.itemChanged.connect(self._update_selection)
        self._update_selection()
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)

    def _create_selection_page(self) -> QWidget:
        page = QWidget()
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabel("Folder / Image")
        self.folder_tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.selection_label = QLabel()
        self.threshold_combo = QComboBox()
        for value, label in THRESHOLDS:
            self.threshold_combo.addItem(f"{label} ({value})", value)
        stabilize_widget_size(self.threshold_combo)
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Similarity threshold"))
        threshold_row.addWidget(self.threshold_combo)
        threshold_row.addStretch(1)
        self.scan_button = QPushButton("Find Duplicates")
        self.scan_button.clicked.connect(self._start_scan)
        threshold_row.addWidget(self.scan_button)
        self.scan_progress = QProgressBar()
        self.scan_progress.hide()
        self.scan_status = QLabel()
        self.scan_status.setWordWrap(True)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Select images to deduplicate"))
        layout.addWidget(self.folder_tree, 1)
        layout.addWidget(self.selection_label)
        layout.addLayout(threshold_row)
        layout.addWidget(QLabel("Exact means identical perceptual hashes."))
        layout.addWidget(self.scan_progress)
        layout.addWidget(self.scan_status)
        return page

    def _create_review_page(self) -> QWidget:
        page = QWidget()
        self.progress_label = QLabel()
        self.scan_issues_label = QLabel()
        self.scan_issues_label.setWordWrap(True)
        self.decision_label = QLabel()
        self.left_view = ImageView()
        self.right_view = ImageView()
        self.left_path_label = QLabel()
        self.right_path_label = QLabel()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        for view, label in (
            (self.left_view, self.left_path_label),
            (self.right_view, self.right_path_label),
        ):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.addWidget(label)
            layout.addWidget(view, 1)
            splitter.addWidget(panel)
        splitter.setSizes([600, 600])
        self.left_loader = PreviewLoader(self)
        self.right_loader = PreviewLoader(self)
        self.left_loader.loaded.connect(self._left_loaded)
        self.right_loader.loaded.connect(self._right_loaded)

        self.choice_group = QButtonGroup(self)
        self.choice_buttons: dict[KeepChoice, QPushButton] = {}
        choices = QHBoxLayout()
        for choice, text in (
            (KeepChoice.LEFT, "Keep Left"),
            (KeepChoice.BOTH, "Keep Both"),
            (KeepChoice.RIGHT, "Keep Right"),
        ):
            button = QPushButton(text)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=choice: self._choose(value))
            self.choice_group.addButton(button)
            self.choice_buttons[choice] = button
            choices.addWidget(button)

        layout = QVBoxLayout(page)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.scan_issues_label)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.decision_label)
        layout.addLayout(choices)
        finish_description = (
            "Finish permanently deletes marked images and their tag files."
            if self.deletion_behavior == UNLINK
            else "Finish moves marked images and their tag files to the Recycle Bin."
        )
        commit_note = QLabel(
            f"Choices are saved in memory. {finish_description} Undecided images are kept. "
            "Cancel discards all choices."
        )
        commit_note.setWordWrap(True)
        layout.addWidget(commit_note)
        return page

    def _populate_tree(self) -> None:
        root = QTreeWidgetItem([self._root_directory.name or str(self._root_directory)])
        self.folder_tree.addTopLevelItem(root)
        folders = {Path("."): root}
        root.setFlags(root.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
        for entry in self.entries:
            relative = entry.image_path.relative_to(self._root_directory)
            parent = root
            for depth in range(1, len(relative.parts)):
                folder = Path(*relative.parts[:depth])
                if folder not in folders:
                    item = QTreeWidgetItem(parent, [folder.name])
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                    folders[folder] = item
                parent = folders[folder]
            item = QTreeWidgetItem(parent, [relative.name])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(0, ENTRY_ROLE, entry)
            item.setCheckState(0, Qt.CheckState.Checked)
        root.setCheckState(0, Qt.CheckState.Checked)
        self.folder_tree.expandAll()

    def _checked_entries(self) -> list[ImageEntry]:
        checked: set[Path] = set()
        iterator = QTreeWidgetItemIterator(self.folder_tree)
        while (item := iterator.value()) is not None:
            entry = item.data(0, ENTRY_ROLE)
            if isinstance(entry, ImageEntry) and item.checkState(0) == Qt.CheckState.Checked:
                checked.add(entry.image_path)
            iterator += 1
        return [entry for entry in self.entries if entry.image_path in checked]

    def _update_selection(self) -> None:
        count = len(self._checked_entries())
        self.selection_label.setText(f"{count} image(s) selected.")
        self.scan_button.setEnabled(count >= 2 and self._worker is None)

    def _start_scan(self) -> None:
        entries = self._checked_entries()
        if len(entries) < 2 or self._worker is not None:
            return
        self.scan_status.setText("Calculating perceptual hashes and finding similar images...")
        self.scan_progress.setRange(0, len(entries))
        self.scan_progress.setValue(0)
        self.scan_progress.show()
        self.folder_tree.setEnabled(False)
        self.threshold_combo.setEnabled(False)
        self._worker = _ScanWorker(
            [entry.image_path for entry in entries], int(self.threshold_combo.currentData())
        )
        self._worker.signals.progress.connect(self._scan_progress)
        self._worker.signals.completed.connect(self._scan_completed)
        self._worker.signals.failed.connect(self._scan_failed)
        self._update_selection()
        QThreadPool.globalInstance().start(self._worker)

    def _scan_progress(self, completed: int, total: int) -> None:
        self.scan_progress.setValue(completed)
        self.scan_status.setText(f"Processed {completed} of {total} images.")

    def _scan_completed(self, result: DuplicateScanResult) -> None:
        if self._allow_close:
            return
        self._worker = None
        self.session = DeduplicationSession(result.pairs)
        self.current_index = 0 if result.pairs else -1
        self.scan_issues_label.setText(
            f"Skipped {len(result.failures)} unreadable image(s). See details in the tooltip."
            if result.failures else ""
        )
        self.scan_issues_label.setToolTip("\n".join(
            f"{path}: {error}" for path, error in result.failures.items()
        ))
        self.pages.setCurrentWidget(self.review_page)
        self.review_controls.show()
        self._load_current()

    def _scan_failed(self, message: str) -> None:
        self._worker = None
        self.scan_status.setText(f"Could not scan images: {message}")
        self.scan_progress.hide()
        self.folder_tree.setEnabled(True)
        self.threshold_combo.setEnabled(True)
        self._update_selection()

    def _left_loaded(self, image: QImage, error: str) -> None:
        self._show_preview(self.left_view, image, error)

    def _right_loaded(self, image: QImage, error: str) -> None:
        self._show_preview(self.right_view, image, error)

    @staticmethod
    def _show_preview(view: ImageView, image: QImage, error: str) -> None:
        if error or image.isNull():
            view.clear_image(f"Could not display image\n{error}")
        else:
            view.set_image(image)

    def _load_current(self) -> None:
        visible, deleted, applied = self.session.review_state()
        pending = len(self.session.pending_indices)
        position = visible.index(self.current_index) if self.current_index in visible else -1
        self.back_button.setEnabled(position > 0)
        self.next_button.setEnabled(0 <= position < len(visible) - 1)
        self.choice_group.setExclusive(False)
        for choice, button in self.choice_buttons.items():
            button.setEnabled(position >= 0)
            button.setChecked(self.session.decisions.get(self.current_index) == choice)
        self.choice_group.setExclusive(True)
        if position < 0:
            self.progress_label.setText("No duplicate pairs found.")
            self.left_view.clear_image("No duplicate pairs")
            self.right_view.clear_image("No duplicate pairs")
            return
        pair = self.session.pairs[self.current_index]
        self.progress_label.setText(
            f"Pair {position + 1} of {len(visible)} | Hash distance: {pair.distance}"
            f" | {pending} undecided | {len(deleted)} image(s) marked for deletion"
        )
        choice = self.session.decisions.get(self.current_index)
        self.decision_label.setText(
            f"Saved choice: Keep {choice}." if self.current_index in applied
            else "Choose which image to keep."
        )
        for path, label, view, loader in (
            (pair.left, self.left_path_label, self.left_view, self.left_loader),
            (pair.right, self.right_path_label, self.right_view, self.right_loader),
        ):
            suffix = " — marked for deletion" if path in deleted else ""
            label.setText(str(path.relative_to(self._root_directory)) + suffix)
            label.setToolTip(str(path))
            view.clear_image("Loading image...")
            loader.load(path)

    def _navigate(self, offset: int) -> None:
        visible, _, _ = self.session.review_state()
        if self.current_index not in visible:
            return
        position = visible.index(self.current_index) + offset
        if 0 <= position < len(visible):
            self.current_index = visible[position]
            self._load_current()

    def _choose(self, choice: KeepChoice) -> None:
        if self.current_index < 0:
            return
        self.session.decisions[self.current_index] = choice
        pending = self.session.pending_indices
        if pending:
            self.current_index = next(
                (index for index in pending if index > self.current_index), pending[0]
            )
        self._load_current()

    def _finish(self) -> None:
        if self._worker is not None or self._committing:
            return
        _, deleted, _ = self.session.review_state()
        if not deleted:
            self._allow_close = True
            self.accept()
            return
        answer = QMessageBox.question(
            self,
            (
                "Permanently Delete Duplicate Images?"
                if self.deletion_behavior == UNLINK else "Delete Duplicate Images?"
            ),
            (
                f"Permanently delete {len(deleted)} marked image(s) and their tag files?"
                "\n\nThis cannot be undone."
                if self.deletion_behavior == UNLINK
                else f"Move {len(deleted)} marked image(s) and their tag files to the system Recycle Bin?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._committing = True
        self.left_loader.clear()
        self.right_loader.clear()
        progress = DeleteFilterProgressDialog(
            [entry for entry in self.entries if entry.image_path in deleted],
            self._file_deleter,
            self.left_loader.wait_for_done,
            self,
            deletion_behavior=self.deletion_behavior,
        )
        progress.start()
        progress.exec()
        self._committing = False
        self.commit_result = progress.commit_result
        if self.commit_result is None:
            QMessageBox.critical(self, "Could Not Delete Files", progress.error or "Deletion failed.")
            return
        if self.commit_result.failures:
            QMessageBox.warning(self, "Could Not Delete All Files", "\n".join(
                f"{path}: {error}" for path, error in self.commit_result.failures.items()
            ))
        self._allow_close = True
        self.accept()

    def _confirm_discard(self) -> bool:
        if self._committing:
            return False
        if not self._allow_close and self.session.decisions:
            answer = QMessageBox.question(
                self, "Discard Deduplication Choices?", "Discard all uncommitted choices?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return False
        self._allow_close = True
        if self._worker is not None:
            self._worker.cancelled.set()
        self.left_loader.clear()
        self.right_loader.clear()
        return True

    @override
    def reject(self) -> None:
        if self._confirm_discard():
            super().reject()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
