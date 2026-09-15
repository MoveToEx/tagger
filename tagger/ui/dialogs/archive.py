from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.storage import DreamboothConcept, archive_entries
from tagger.ui.widgets import stabilize_widget_size


ENTRY_ROLE = int(Qt.ItemDataRole.UserRole) + 1
CONCEPT_ROLE = ENTRY_ROLE + 1


@dataclass
class _ConceptState:
    name: str
    repeats: int = 1
    selected_paths: set[Path] = field(default_factory=set)


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
        self._updating_concept_checks = False
        self._updating_concept_name = False
        self._updating_repeat_count = False
        self._concepts: dict[int, _ConceptState] = {}
        self._next_concept_id = 1
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

        self.general_tab = QWidget()
        general_layout = QVBoxLayout(self.general_tab)
        general_layout.addWidget(
            QLabel("Select image/tag pairs to add to the archive")
        )
        general_layout.addWidget(self.folder_tree, 1)
        general_layout.addWidget(self.selection_label)
        general_layout.addLayout(output_row)

        self.dreambooth_enabled_checkbox = QCheckBox(
            "Enable Dreambooth-style dataset format"
        )
        self.dreambooth_enabled_checkbox.setStyleSheet(
            "QCheckBox::indicator { width: 12px; height: 12px; }"
        )
        stabilize_widget_size(self.dreambooth_enabled_checkbox)
        self.enable_dreambooth_checkbox = self.dreambooth_enabled_checkbox
        self.dreambooth_enabled_checkbox.toggled.connect(
            self._dreambooth_enabled_changed
        )

        self.concept_list = QListWidget()
        self.concept_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.concept_list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.concept_list.currentItemChanged.connect(
            self._current_concept_changed
        )
        self.concept_list.itemChanged.connect(self._concept_name_changed)

        self.add_concept_button = QPushButton("Add")
        self.add_concept_button.setToolTip("Add a concept")
        self.add_concept_button.clicked.connect(self._add_concept_clicked)
        stabilize_widget_size(self.add_concept_button)
        self.delete_concept_button = QPushButton("Delete")
        self.delete_concept_button.setToolTip("Delete the selected concept")
        self.delete_concept_button.clicked.connect(
            self._delete_selected_concept
        )
        stabilize_widget_size(self.delete_concept_button)

        concept_buttons = QHBoxLayout()
        concept_buttons.setContentsMargins(0, 0, 0, 0)
        concept_buttons.addWidget(self.add_concept_button)
        concept_buttons.addWidget(self.delete_concept_button)
        concept_buttons.addStretch(1)

        self.concept_list_panel = QWidget()
        self.concept_list_panel.setFixedWidth(180)
        concept_list_layout = QVBoxLayout(self.concept_list_panel)
        concept_list_layout.setContentsMargins(0, 0, 0, 0)
        concept_list_layout.addWidget(QLabel("Concepts"))
        concept_list_layout.addWidget(self.concept_list, 1)
        concept_list_layout.addLayout(concept_buttons)

        self.repeat_count_input = QSpinBox()
        self.repeat_count_input.setRange(1, 1_000_000)
        self.repeat_count_input.setValue(1)
        stabilize_widget_size(
            self.repeat_count_input, minimum_width=96, vertical_padding=2
        )
        self.repeat_count_input.valueChanged.connect(
            self._repeat_count_changed
        )
        repeat_row = QHBoxLayout()
        repeat_row.setContentsMargins(0, 0, 0, 0)
        repeat_row.addWidget(QLabel("Repeat count:"))
        repeat_row.addWidget(self.repeat_count_input)
        repeat_row.addStretch(1)

        self.concept_file_tree = QTreeWidget()
        self.concept_file_tree.setHeaderLabel("Folder / Image")
        self.concept_file_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.concept_file_tree.itemChanged.connect(
            self._concept_file_check_changed
        )

        self.concept_options_panel = QWidget()
        concept_options_layout = QVBoxLayout(self.concept_options_panel)
        concept_options_layout.setContentsMargins(0, 0, 0, 0)
        concept_options_layout.addLayout(repeat_row)
        concept_options_layout.addWidget(self.concept_file_tree, 1)

        self.dreambooth_content = QWidget()
        dreambooth_content_layout = QHBoxLayout(self.dreambooth_content)
        dreambooth_content_layout.setContentsMargins(0, 0, 0, 0)
        dreambooth_content_layout.setSpacing(16)
        dreambooth_content_layout.addWidget(self.concept_list_panel)
        dreambooth_content_layout.addWidget(self.concept_options_panel, 1)

        self.dreambooth_error_label = QLabel()
        self.dreambooth_error_label.setWordWrap(True)
        self.dreambooth_tab = QWidget()
        dreambooth_layout = QVBoxLayout(self.dreambooth_tab)
        dreambooth_layout.addWidget(self.dreambooth_enabled_checkbox)
        dreambooth_layout.addWidget(self.dreambooth_content, 1)
        dreambooth_layout.addWidget(self.dreambooth_error_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.general_tab, "General")
        self.tabs.addTab(self.dreambooth_tab, "Dreambooth")

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
        layout.addWidget(self.tabs, 1)
        layout.addLayout(buttons)

        if initial_destination is not None:
            self.output_file_input.setText(
                str(self._with_zip_suffix(initial_destination))
            )

        self._populate_tree()
        self._updating_checks = False
        self._add_concept(
            "concept",
            selected_paths={
                entry.image_path for entry in self._checked_entries()
            },
        )
        self._dreambooth_enabled_changed(False)
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

    def _add_concept_clicked(self, _checked: bool = False) -> None:
        existing_names = {
            state.name.casefold() for state in self._concepts.values()
        }
        number = 1
        while True:
            name = "concept" if number == 1 else f"concept {number}"
            if name.casefold() not in existing_names:
                break
            number += 1
        item = self._add_concept(name)
        self.concept_list.editItem(item)

    def _add_concept(
        self,
        name: str,
        *,
        selected_paths: set[Path] | None = None,
    ) -> QListWidgetItem:
        concept_id = self._next_concept_id
        self._next_concept_id += 1
        self._concepts[concept_id] = _ConceptState(
            name=name,
            selected_paths=set(selected_paths or ()),
        )
        item = QListWidgetItem(name)
        item.setData(CONCEPT_ROLE, concept_id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.concept_list.addItem(item)
        self.concept_list.setCurrentItem(item)
        self._update_action_state()
        return item

    def _delete_selected_concept(self, _checked: bool = False) -> None:
        row = self.concept_list.currentRow()
        if row < 0:
            return
        item = self.concept_list.takeItem(row)
        if item is not None:
            concept_id = item.data(CONCEPT_ROLE)
            if isinstance(concept_id, int):
                self._concepts.pop(concept_id, None)
        if self.concept_list.count() > 0:
            self.concept_list.setCurrentRow(
                min(row, self.concept_list.count() - 1)
            )
        else:
            self._populate_concept_tree()
        self._update_action_state()

    def _current_concept(self) -> _ConceptState | None:
        item = self.concept_list.currentItem()
        if item is None:
            return None
        concept_id = item.data(CONCEPT_ROLE)
        if not isinstance(concept_id, int):
            return None
        return self._concepts.get(concept_id)

    def _current_concept_changed(
        self,
        _current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        self._populate_concept_tree()

    def _concept_name_changed(self, item: QListWidgetItem) -> None:
        if self._updating_concept_name:
            return
        concept_id = item.data(CONCEPT_ROLE)
        if not isinstance(concept_id, int):
            return
        state = self._concepts.get(concept_id)
        if state is None:
            return
        name = item.text().strip()
        state.name = name
        if item.text() != name:
            self._updating_concept_name = True
            try:
                item.setText(name)
            finally:
                self._updating_concept_name = False
        self._update_action_state()

    def _repeat_count_changed(self, repeats: int) -> None:
        if self._updating_repeat_count:
            return
        state = self._current_concept()
        if state is not None:
            state.repeats = repeats
        self._update_action_state()

    def _dreambooth_enabled_changed(self, enabled: bool) -> None:
        self.dreambooth_content.setEnabled(enabled)
        self._populate_concept_tree()
        self._update_action_state()

    def _populate_concept_tree(self) -> None:
        state = self._current_concept()
        enabled = self.dreambooth_enabled_checkbox.isChecked()
        self.delete_concept_button.setEnabled(enabled and state is not None)
        self.concept_options_panel.setEnabled(enabled and state is not None)

        self._updating_repeat_count = True
        try:
            self.repeat_count_input.setValue(
                state.repeats if state is not None else 1
            )
        finally:
            self._updating_repeat_count = False

        self._updating_concept_checks = True
        try:
            self.concept_file_tree.clear()
            if state is None:
                return
            root_path = self._root_directory or Path(".")
            root_item = QTreeWidgetItem(
                [root_path.name or str(root_path)]
            )
            root_item.setFlags(
                root_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)
            self.concept_file_tree.addTopLevelItem(root_item)

            folders: dict[Path, QTreeWidgetItem] = {Path("."): root_item}
            entries = self._checked_entries()
            relative_parents: list[Path] = []
            for entry in entries:
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
                    folder_item = QTreeWidgetItem(
                        [relative_folder.name]
                    )
                    folder_item.setFlags(
                        folder_item.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    folders[relative_folder.parent].addChild(folder_item)
                    folders[relative_folder] = folder_item

            for entry, relative_parent in zip(entries, relative_parents):
                item = QTreeWidgetItem([entry.image_path.name])
                item.setFlags(
                    item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if entry.image_path in state.selected_paths
                    else Qt.CheckState.Unchecked,
                )
                item.setData(0, ENTRY_ROLE, entry)
                item.setToolTip(0, f"{entry.image_path}\n{entry.tag_path}")
                folders[relative_parent].addChild(item)

            self.concept_file_tree.expandAll()
            self._refresh_check_states(root_item)
        finally:
            self._updating_concept_checks = False

    def _concept_file_check_changed(
        self, item: QTreeWidgetItem, column: int
    ) -> None:
        if self._updating_concept_checks or column != 0:
            return
        self._updating_concept_checks = True
        try:
            state = item.checkState(0)
            if state in {Qt.CheckState.Checked, Qt.CheckState.Unchecked}:
                self._set_descendant_check_state(item, state)
            self._update_ancestor_check_states(item.parent())
            concept = self._current_concept()
            if concept is not None:
                concept.selected_paths = self._checked_tree_paths(
                    self.concept_file_tree
                )
        finally:
            self._updating_concept_checks = False
        self._update_action_state()

    @staticmethod
    def _checked_tree_paths(tree: QTreeWidget) -> set[Path]:
        paths: set[Path] = set()
        iterator = QTreeWidgetItemIterator(tree)
        while iterator.value() is not None:
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                entry = item.data(0, ENTRY_ROLE)
                if isinstance(entry, ImageEntry):
                    paths.add(entry.image_path)
            iterator += 1
        return paths

    def _sync_concept_files(self) -> None:
        selected_paths = {
            entry.image_path for entry in self._checked_entries()
        }
        for concept in self._concepts.values():
            concept.selected_paths.intersection_update(selected_paths)
        self._populate_concept_tree()

    def _dreambooth_validation_error(self) -> str | None:
        if not self.dreambooth_enabled_checkbox.isChecked():
            return None
        if not self._concepts:
            return "Add at least one concept."

        selected_paths = {
            entry.image_path for entry in self._checked_entries()
        }
        names: set[str] = set()
        for state in self._concepts.values():
            name = state.name.strip()
            if (
                not name
                or name in {".", ".."}
                or "/" in name
                or "\\" in name
                or "\0" in name
            ):
                return "Concept names cannot be empty or contain / or \\."
            if name.casefold() in names:
                return "Concept names must be unique."
            names.add(name.casefold())
            if not state.selected_paths.intersection(selected_paths):
                return f'Concept "{name}" has no files selected.'
        return None

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
        self._sync_concept_files()
        self._update_action_state()

    def _update_action_state(self, *_args) -> None:
        dreambooth_error = self._dreambooth_validation_error()
        self.dreambooth_error_label.setText(dreambooth_error or "")
        self.archive_button.setEnabled(
            bool(self._checked_entries())
            and bool(self.output_file_input.text().strip())
            and dreambooth_error is None
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

    @property
    def dreambooth_concepts(self) -> list[DreamboothConcept] | None:
        if not self.dreambooth_enabled_checkbox.isChecked():
            return None
        selected_entries = {
            entry.image_path: entry for entry in self._checked_entries()
        }
        concepts: list[DreamboothConcept] = []
        for row in range(self.concept_list.count()):
            item = self.concept_list.item(row)
            if item is None:
                continue
            concept_id = item.data(CONCEPT_ROLE)
            if not isinstance(concept_id, int):
                continue
            state = self._concepts.get(concept_id)
            if state is None:
                continue
            concepts.append(
                DreamboothConcept(
                    name=state.name.strip(),
                    repeats=state.repeats,
                    entries=tuple(
                        entry
                        for path, entry in selected_entries.items()
                        if path in state.selected_paths
                    ),
                )
            )
        return concepts

    def _accept_selection(self) -> None:
        self.accept()

    @override
    def accept(self) -> None:
        selected = self.selected_entries
        output = self.output_file_input.text().strip()
        if (
            not selected
            or not output
            or self._dreambooth_validation_error() is not None
        ):
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
        self,
        entries: list[ImageEntry],
        destination: Path,
        dreambooth_concepts: Sequence[DreamboothConcept] | None = None,
    ) -> None:
        super().__init__()
        self.entries = entries
        self.destination = destination
        self.dreambooth_concepts = dreambooth_concepts
        self.signals = _ArchiveSignals()

    @override
    def run(self) -> None:
        try:
            if self.dreambooth_concepts is None:
                result = archive_entries(
                    self.entries,
                    self.destination,
                    self.signals.progress.emit,
                )
            else:
                result = archive_entries(
                    self.entries,
                    self.destination,
                    self.signals.progress.emit,
                    dreambooth_concepts=self.dreambooth_concepts,
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
        *,
        dreambooth_concepts: Sequence[DreamboothConcept] | None = None,
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
        pair_count = (
            len(entries)
            if dreambooth_concepts is None
            else sum(
                len(concept.entries) for concept in dreambooth_concepts
            )
        )
        self.progress_bar.setRange(0, pair_count * 2)
        self.progress_bar.setValue(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.current_file_label)
        layout.addWidget(self.progress_bar)

        self._running = False
        self._worker = _ArchiveWorker(
            entries, destination, dreambooth_concepts
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
