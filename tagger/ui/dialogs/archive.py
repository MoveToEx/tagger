from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.storage import archive_entries
from tagger.ui.widgets import stabilize_widget_size


ENTRY_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def _folder_ancestors(path: Path) -> list[Path]:
    if path == Path("."):
        return []
    return [
        Path(*path.parts[:length])
        for length in range(1, len(path.parts) + 1)
    ]


class ArchiveDialog(QDialog):
    """Choose image/tag pairs and an output archive before starting work."""

    def __init__(
        self,
        entries: Sequence[ImageEntry],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
        initial_destination: Path | None = None,
        initial_paths: Sequence[Path] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Archive Image and Tag Pairs")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(760, 600)

        self._root_directory = root_directory
        self._entries = sorted(
            list(entries), key=lambda entry: str(entry.image_path).casefold()
        )
        self._initial_paths = (
            {Path(path) for path in initial_paths}
            if initial_paths is not None
            else None
        )
        self._updating_checks = True
        self._destination: Path | None = None

        self.folder_tree = QTreeWidget()
        # Keep the same aliases used by the other image selection dialogs.
        self.image_selection = self.folder_tree
        self.image_list = self.folder_tree
        self.folder_tree.setHeaderLabel("Folder / Image")
        self.folder_tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.folder_tree.itemChanged.connect(self._selection_check_changed)

        self.selection_label = QLabel()
        self.output_file_input = QLineEdit()
        self.output_file_input.setPlaceholderText("Archive output file (.zip)")
        self.output_file_input.setClearButtonEnabled(True)
        stabilize_widget_size(self.output_file_input, minimum_width=360)
        self.output_path_input = self.output_file_input
        self.output_input = self.output_file_input
        self.output_file = self.output_file_input
        self.output_line_edit = self.output_file_input

        self.browse_output_button = QPushButton("Browse...")
        self.browse_output_button.setToolTip("Choose the archive output file")
        self.browse_output_button.clicked.connect(self._browse_output)
        stabilize_widget_size(self.browse_output_button)
        self.browse_button = self.browse_output_button
        self.select_output_button = self.browse_output_button

        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.addWidget(QLabel("Output file:"))
        output_row.addWidget(self.output_file_input)
        output_row.addWidget(self.browse_output_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.archive_button = QPushButton("Archive")
        self.archive_button.clicked.connect(self._accept_selection)
        self.output_file_input.textChanged.connect(self._update_action_state)
        self.output_file_input.returnPressed.connect(self._accept_selection)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.archive_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select image/tag pairs to add to the archive"))
        layout.addWidget(self.folder_tree, 1)
        layout.addWidget(self.selection_label)
        layout.addLayout(output_row)
        layout.addLayout(buttons)

        if initial_destination is not None:
            self.output_file_input.setText(
                str(self._with_zip_suffix(initial_destination))
            )

        self._populate_tree()
        self._updating_checks = False
        self._update_selection_label()

    @staticmethod
    def _with_zip_suffix(path: Path) -> Path:
        return path if path.suffix.casefold() == ".zip" else Path(f"{path}.zip")

    def _populate_tree(self) -> None:
        root_path = self._root_directory or Path(".")
        root_item = QTreeWidgetItem([root_path.name or str(root_path)])
        root_item.setFlags(root_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)
        self.folder_tree.addTopLevelItem(root_item)

        folders: dict[Path, QTreeWidgetItem] = {Path("."): root_item}
        relative_parents: list[Path] = []
        for entry in self._entries:
            if self._root_directory is None:
                relative_parent = Path(".")
            else:
                try:
                    relative_parent = entry.image_path.parent.relative_to(
                        self._root_directory
                    )
                except ValueError:
                    relative_parent = Path(".")
            relative_parents.append(relative_parent)
            for relative_folder in _folder_ancestors(relative_parent):
                if relative_folder in folders:
                    continue
                parent_item = folders[relative_folder.parent]
                folder_item = QTreeWidgetItem([relative_folder.name])
                folder_item.setFlags(
                    folder_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                folder_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    (self._root_directory or Path(".")) / relative_folder,
                )
                parent_item.addChild(folder_item)
                folders[relative_folder] = folder_item

        for entry, relative_parent in zip(self._entries, relative_parents):
            item = QTreeWidgetItem([entry.image_path.name])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = (
                self._initial_paths is None
                or entry.image_path in self._initial_paths
            )
            item.setCheckState(
                0,
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked,
            )
            item.setData(0, Qt.ItemDataRole.UserRole, entry.image_path)
            item.setData(0, ENTRY_ROLE, entry)
            item.setToolTip(0, f"{entry.image_path}\n{entry.tag_path}")
            folders[relative_parent].addChild(item)

        self.folder_tree.expandAll()
        self._refresh_check_states(root_item)

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
            if child is not None:
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
            if states and all(
                state == Qt.CheckState.Checked for state in states
            ):
                item.setCheckState(0, Qt.CheckState.Checked)
            elif states and all(
                state == Qt.CheckState.Unchecked for state in states
            ):
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
        if states and all(
            state == Qt.CheckState.Checked for state in states
        ):
            item.setCheckState(0, Qt.CheckState.Checked)
        elif states and all(
            state == Qt.CheckState.Unchecked for state in states
        ):
            item.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            item.setCheckState(0, Qt.CheckState.PartiallyChecked)

    def _checked_entries(self) -> list[ImageEntry]:
        checked_paths: set[Path] = set()
        iterator = QTreeWidgetItemIterator(self.folder_tree)
        while iterator.value() is not None:
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                entry = item.data(0, ENTRY_ROLE)
                if isinstance(entry, ImageEntry):
                    checked_paths.add(entry.image_path)
            iterator += 1
        return [
            entry for entry in self._entries if entry.image_path in checked_paths
        ]

    def _update_selection_label(self, *_args) -> None:
        count = len(self._checked_entries())
        self.selection_label.setText(f"{count} image(s) selected.")
        self._update_action_state()

    def _update_action_state(self, *_args) -> None:
        self.archive_button.setEnabled(
            bool(self._checked_entries())
            and bool(self.output_file_input.text().strip())
        )

    def _browse_output(self) -> None:
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Archive Image and Tag Pairs",
            self.output_file_input.text().strip(),
            "Zip archives (*.zip)",
        )
        if selected:
            self.output_file_input.setText(
                str(self._with_zip_suffix(Path(selected)))
            )

    @property
    def selected_entries(self) -> list[ImageEntry]:
        return self._checked_entries()

    @property
    def selected_paths(self) -> list[Path]:
        return [entry.image_path for entry in self.selected_entries]

    @property
    def destination(self) -> Path | None:
        return self._destination

    @property
    def output_path(self) -> Path | None:
        return self.destination

    @property
    def output_file_path(self) -> Path | None:
        return self.destination

    @property
    def archive_path(self) -> Path | None:
        return self.destination

    def _accept_selection(self) -> None:
        self.accept()

    @override
    def accept(self) -> None:
        selected = self.selected_entries
        output = self.output_file_input.text().strip()
        if not selected or not output:
            return
        self._destination = self._with_zip_suffix(Path(output).expanduser())
        self.output_file_input.setText(str(self._destination))
        super().accept()


# Keep the more explicit name available to callers that distinguish the
# configuration step from the background progress dialog.
ArchiveSelectionDialog = ArchiveDialog


class _ArchiveSignals(QObject):
    progress = Signal(int, int, str)
    completed = Signal(int)
    failed = Signal(str)


class _ArchiveWorker(QRunnable):
    def __init__(
        self, entries: list[ImageEntry], destination: Path
    ) -> None:
        super().__init__()
        self.entries = entries
        self.destination = destination
        self.signals = _ArchiveSignals()

    @override
    def run(self) -> None:
        try:
            result = archive_entries(
                self.entries,
                self.destination,
                self.signals.progress.emit,
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.completed.emit(len(result.archived))


class ArchiveProgressDialog(QDialog):
    completed = Signal(int)
    failed = Signal(str)

    def __init__(
        self,
        entries: list[ImageEntry],
        destination: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Creating Archive")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(440)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self.current_file_label = QLabel("Preparing archive...")
        self.current_file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, len(entries) * 2)
        self.progress_bar.setValue(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.current_file_label)
        layout.addWidget(self.progress_bar)

        self._running = False
        self._worker = _ArchiveWorker(entries, destination)
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
        self.current_file_label.setText(f"Archiving: {current_file}")

    def _complete(self, archived_count: int) -> None:
        self._running = False
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.accept()
        self.completed.emit(archived_count)

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
