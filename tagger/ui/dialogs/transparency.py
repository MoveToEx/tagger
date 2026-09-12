from __future__ import annotations

from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.image_processing import remove_transparency


def _folder_ancestors(path: Path) -> list[Path]:
    if path == Path("."):
        return []
    return [Path(*path.parts[:length]) for length in range(1, len(path.parts) + 1)]


class TransparencySelectionDialog(QDialog):
    """Choose images from the currently opened catalog."""

    def __init__(
        self,
        entries: list[ImageEntry],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
        initial_paths: list[Path] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remove Transparency")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(700, 560)

        self.folder_tree = QTreeWidget()
        # Keep the older aliases for callers that treated this as an image picker.
        self.image_selection = self.folder_tree
        self.image_list = self.folder_tree
        self.folder_tree.setHeaderLabel("Folder / Image")
        self.folder_tree.setSelectionMode(
            QTreeWidget.SelectionMode.NoSelection
        )
        self.folder_tree.itemChanged.connect(self._selection_check_changed)
        self.selection_label = QLabel()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.remove_button = QPushButton("Remove Transparency")
        self.remove_button.clicked.connect(self._accept_selection)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.remove_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select images to remove transparency from"))
        layout.addWidget(self.folder_tree, 1)
        layout.addWidget(self.selection_label)
        layout.addLayout(buttons)

        initial = {Path(path) for path in (initial_paths or [])}
        ordered_entries = sorted(
            (entry for entry in entries if entry.image_path.is_file()),
            key=lambda entry: str(entry.image_path).casefold(),
        )
        self._entries = ordered_entries
        self._updating_checks = True
        root_path = root_directory or Path(".")
        root_label = root_path.name or str(root_path)
        root_item = QTreeWidgetItem([root_label])
        root_item.setFlags(root_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)
        self.image_selection.addTopLevelItem(root_item)
        folder_items: dict[Path, QTreeWidgetItem] = {Path("."): root_item}
        relative_parents: list[Path] = []
        for entry in ordered_entries:
            if root_directory is None:
                relative_parent = Path(".")
            else:
                relative_parent = entry.image_path.parent.relative_to(root_directory)
            relative_parents.append(relative_parent)
            for relative_folder in _folder_ancestors(relative_parent):
                if relative_folder in folder_items:
                    continue
                parent_item = folder_items[relative_folder.parent]
                folder_item = QTreeWidgetItem([relative_folder.name])
                folder_item.setFlags(
                    folder_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                folder_item.setCheckState(0, Qt.CheckState.Unchecked)
                folder_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    (root_directory or Path(".")) / relative_folder,
                )
                parent_item.addChild(folder_item)
                folder_items[relative_folder] = folder_item

        for entry, relative_parent in zip(ordered_entries, relative_parents):
            parent_item = folder_items[relative_parent]
            item = QTreeWidgetItem([entry.image_path.name])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(0, Qt.ItemDataRole.UserRole, entry.image_path)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, entry)
            item.setToolTip(0, str(entry.image_path))
            checked = (
                entry.image_path in initial
                if initial_paths is not None
                else True
            )
            item.setCheckState(
                0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            parent_item.addChild(item)

        self.image_selection.expandAll()
        self._refresh_check_states(root_item)
        self._updating_checks = False
        self._update_selection_label()
        self._update_action_state()

    def _selection_check_changed(
        self, item: QTreeWidgetItem, column: int
    ) -> None:
        if self._updating_checks or column != 0:
            return
        self._updating_checks = True
        try:
            state = item.checkState(0)
            if state in {Qt.CheckState.Checked, Qt.CheckState.Unchecked}:
                self._set_descendant_check_state(item, state)
            self._update_ancestor_check_states(item.parent())
        finally:
            self._updating_checks = False
        self._update_selection_label()

    def _set_descendant_check_state(
        self, item: QTreeWidgetItem, state: Qt.CheckState
    ) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            if child is None:
                continue
            child.setCheckState(0, state)
            self._set_descendant_check_state(child, state)

    def _update_ancestor_check_states(
        self, item: QTreeWidgetItem | None
    ) -> None:
        while item is not None:
            states = [
                child.checkState(0)
                for index in range(item.childCount())
                if (child := item.child(index)) is not None
            ]
            if states and all(state == Qt.CheckState.Checked for state in states):
                item.setCheckState(0, Qt.CheckState.Checked)
            elif states and all(state == Qt.CheckState.Unchecked for state in states):
                item.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                item.setCheckState(0, Qt.CheckState.PartiallyChecked)
            item = item.parent()

    def _refresh_check_states(self, item: QTreeWidgetItem) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            if child is not None:
                self._refresh_check_states(child)
        if item.childCount() == 0:
            return
        states = [
            child.checkState(0)
            for index in range(item.childCount())
            if (child := item.child(index)) is not None
        ]
        if states and all(state == Qt.CheckState.Checked for state in states):
            item.setCheckState(0, Qt.CheckState.Checked)
        elif states and all(state == Qt.CheckState.Unchecked for state in states):
            item.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            item.setCheckState(0, Qt.CheckState.PartiallyChecked)

    def _checked_entries(self) -> list[ImageEntry]:
        checked_paths: set[Path] = set()
        iterator = QTreeWidgetItemIterator(self.folder_tree)
        while iterator.value() is not None:
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                value = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if isinstance(value, ImageEntry):
                    checked_paths.add(value.image_path)
            iterator += 1
        return [entry for entry in self._entries if entry.image_path in checked_paths]

    def _update_selection_label(self, *_args) -> None:
        count = len(self._checked_entries())
        self.selection_label.setText(f"{count} image(s) selected.")
        self._update_action_state()

    def _update_action_state(self) -> None:
        self.remove_button.setEnabled(bool(self._checked_entries()))

    @property
    def selected_paths(self) -> list[Path]:
        return [entry.image_path for entry in self._checked_entries()]

    def _accept_selection(self) -> None:
        if not self.selected_paths:
            return
        self.accept()


class _TransparencySignals(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)


class _TransparencyWorker(QRunnable):
    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self.paths = paths
        self.signals = _TransparencySignals()

    @override
    def run(self) -> None:
        changed: list[Path] = []
        failures: list[str] = []
        total = len(self.paths)
        for number, path in enumerate(self.paths, 1):
            self.signals.progress.emit(number - 1, total, f"Processing: {path.name}")
            try:
                if remove_transparency(path):
                    changed.append(path)
            except OSError as exc:
                failures.append(f"{path.name}: {exc}")
            self.signals.progress.emit(number, total, path.name)
        self.signals.completed.emit((changed, failures))


class TransparencyProgressDialog(QDialog):
    completed = Signal(object)

    def __init__(self, paths: list[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Removing Transparency")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(440)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.current_file_label = QLabel("Preparing images...")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(paths))
        self.progress_bar.setValue(0)
        layout = QVBoxLayout(self)
        layout.addWidget(self.current_file_label)
        layout.addWidget(self.progress_bar)
        self._running = False
        self._worker = _TransparencyWorker(paths)
        self._worker.signals.progress.connect(self._update_progress)
        self._worker.signals.completed.connect(self._complete)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        QThreadPool.globalInstance().start(self._worker)

    def _update_progress(self, completed: int, total: int, current: str) -> None:
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(completed)
        self.current_file_label.setText(current)

    def _complete(self, result: tuple[list[Path], list[str]]) -> None:
        self._running = False
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.completed.emit(result)
        self.accept()

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
