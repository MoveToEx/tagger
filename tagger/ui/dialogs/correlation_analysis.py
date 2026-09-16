from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.correlation import TagCorrelation, analyze_tag_correlations
from tagger.domain.models import ImageEntry
from tagger.tag_library.completion import attach_tag_completer
from tagger.tag_library.library import TagLibrary
from tagger.ui.widgets import stabilize_widget_size


ENTRY_ROLE = int(Qt.ItemDataRole.UserRole) + 1
MAX_RELATED_TAGS = 100
HIGH_CORRELATION_THRESHOLD = 0.9
HIGH_CORRELATION_BACKGROUND = QColor("#e0f2fe")


def _folder_ancestors(path: Path) -> list[Path]:
    if path == Path("."):
        return []
    return [Path(*path.parts[:length]) for length in range(1, len(path.parts) + 1)]


class CorrelationAnalysisDialog(QDialog):
    """Select images and inspect tag occurrence correlations."""

    def __init__(
        self,
        entries: Sequence[ImageEntry],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
        tag_library: TagLibrary | None = None,
    ) -> None:
        super().__init__(parent)
        self.entries = list(entries)
        self._root_directory = root_directory or self._common_root_directory(
            self.entries
        )
        self._updating_checks = False
        self._results: list[TagCorrelation] = []

        self.setWindowTitle("Correlation Analysis")
        self.resize(760, 620)

        self.pages = QStackedWidget()
        self.selection_page = self._create_selection_page(tag_library)
        self.results_page = self._create_results_page()
        self.pages.addWidget(self.selection_page)
        self.pages.addWidget(self.results_page)

        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)

        self._populate_tree()
        self._update_selection()
        self.tag_input.setFocus()

    def _create_selection_page(self, tag_library: TagLibrary | None) -> QWidget:
        page = QWidget()
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabel("Folder / Image")
        self.folder_tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.folder_tree.itemChanged.connect(self._check_changed)

        self.folder_selection_label = QLabel()
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Exact tag to analyze")
        self.tag_input.setClearButtonEnabled(True)
        self.tag_input.setToolTip(
            "Count tag occurrences among images with and without this tag."
        )
        self.tag_completer = attach_tag_completer(self.tag_input, tag_library)
        stabilize_widget_size(self.tag_input, minimum_width=300)
        self.tag_input.textChanged.connect(self._update_selection)
        self.tag_input.returnPressed.connect(self.analyze)

        self.validation_label = QLabel()
        self.validation_label.setStyleSheet("QLabel { color: #b42318; }")
        self.validation_label.hide()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.analyze)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.next_button)

        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Tag to analyze"))
        input_layout.addWidget(self.tag_input, 1)

        layout = QVBoxLayout(page)
        layout.addWidget(
            QLabel("Select images to include in the correlation analysis.")
        )
        layout.addWidget(self.folder_tree, 1)
        layout.addWidget(self.folder_selection_label)
        layout.addLayout(input_layout)
        layout.addWidget(self.validation_label)
        layout.addLayout(buttons)
        return page

    def _create_results_page(self) -> QWidget:
        page = QWidget()
        self.result_label = QLabel("Enter a tag to see its correlations.")
        self.result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(
            ["Tag", "Positive", "Negative", "Positive %"]
        )
        positive_header = self.results.horizontalHeaderItem(1)
        if positive_header is not None:
            positive_header.setToolTip(
                "Count and percentage of selected images containing both "
                "the analyzed tag and this tag."
            )
        negative_header = self.results.horizontalHeaderItem(2)
        if negative_header is not None:
            negative_header.setToolTip(
                "Count and percentage of selected images containing this tag "
                "without the analyzed tag."
            )
        percentage_header = self.results.horizontalHeaderItem(3)
        if percentage_header is not None:
            percentage_header.setToolTip(
                "Positive images divided by all images containing this tag."
            )
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.results.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        header = self.results.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, header.ResizeMode.ResizeToContents)

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._show_selection_page)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(page)
        layout.addWidget(self.result_label)
        layout.addWidget(self.results, 1)
        layout.addLayout(buttons)
        return page

    @staticmethod
    def _common_root_directory(entries: Sequence[ImageEntry] = ()) -> Path:
        if not entries:
            return Path(".")
        try:
            return Path(
                os.path.commonpath([str(entry.image_path.parent) for entry in entries])
            )
        except ValueError:
            return entries[0].image_path.parent

    @staticmethod
    def _make_checkable(item: QTreeWidgetItem, path: Path) -> None:
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(0, Qt.ItemDataRole.UserRole, str(path))
        item.setCheckState(0, Qt.CheckState.Unchecked)

    def _populate_tree(self) -> None:
        self._updating_checks = True
        try:
            self.folder_tree.clear()
            root = self._root_directory
            root_item = QTreeWidgetItem([root.name or str(root)])
            self._make_checkable(root_item, root)
            self.folder_tree.addTopLevelItem(root_item)
            folders: dict[Path, QTreeWidgetItem] = {Path("."): root_item}

            relative_folders = {
                ancestor
                for entry in self.entries
                for ancestor in self._entry_folder_ancestors(entry, root)
            }
            for folder in sorted(
                relative_folders,
                key=lambda path: (len(path.parts), path.as_posix().casefold()),
            ):
                item = QTreeWidgetItem([folder.name])
                self._make_checkable(item, root / folder)
                parent = folders.get(folder.parent)
                if parent is None:
                    continue
                parent.addChild(item)
                folders[folder] = item

            for entry in self.entries:
                relative_parent = self._relative_parent(entry.image_path.parent, root)
                parent = folders.get(relative_parent, root_item)
                item = QTreeWidgetItem([entry.image_path.name])
                self._make_checkable(item, entry.image_path)
                item.setData(0, ENTRY_ROLE, entry)
                parent.addChild(item)

            self.folder_tree.expandAll()
            root_item.setCheckState(0, Qt.CheckState.Checked)
            self._set_descendants(root_item, Qt.CheckState.Checked)
        finally:
            self._updating_checks = False

    @staticmethod
    def _relative_parent(path: Path, root: Path) -> Path:
        try:
            return path.relative_to(root)
        except ValueError:
            return Path(".")

    @classmethod
    def _entry_folder_ancestors(cls, entry: ImageEntry, root: Path) -> list[Path]:
        return _folder_ancestors(cls._relative_parent(entry.image_path.parent, root))

    def _check_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating_checks or column != 0:
            return
        self._updating_checks = True
        try:
            state = item.checkState(0)
            if state in (Qt.CheckState.Checked, Qt.CheckState.Unchecked):
                self._set_descendants(item, state)
            self._update_ancestors(item.parent())
        finally:
            self._updating_checks = False
        self._update_selection()

    def _set_descendants(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            if child is not None:
                child.setCheckState(0, state)
                self._set_descendants(child, state)

    def _update_ancestors(self, item: QTreeWidgetItem | None) -> None:
        while item is not None:
            states = [
                item.child(index).checkState(0)
                for index in range(item.childCount())
                if item.child(index) is not None
            ]
            if states and all(state == Qt.CheckState.Checked for state in states):
                item.setCheckState(0, Qt.CheckState.Checked)
            elif states and all(state == Qt.CheckState.Unchecked for state in states):
                item.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                item.setCheckState(0, Qt.CheckState.PartiallyChecked)
            item = item.parent()

    def _checked_entries(self) -> list[ImageEntry]:
        checked: set[Path] = set()
        iterator = QTreeWidgetItemIterator(self.folder_tree)
        while iterator.value() is not None:
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                entry = item.data(0, ENTRY_ROLE)
                if isinstance(entry, ImageEntry):
                    checked.add(entry.image_path)
            iterator += 1
        return [entry for entry in self.entries if entry.image_path in checked]

    def _update_selection(self) -> None:
        count = len(self._checked_entries())
        self.folder_selection_label.setText(f"{count} image(s) selected.")
        self.next_button.setEnabled(count > 0 and bool(self.tag_input.text().strip()))
        if self.tag_input.text().strip():
            self.validation_label.hide()

    def analyze(self) -> None:
        """Calculate correlations for the current selection and show them."""
        selected = self._checked_entries()
        query = self.tag_input.text().strip()
        if not selected:
            self.validation_label.setText("Select at least one image.")
            self.validation_label.show()
            return
        if not query:
            self.validation_label.setText("Enter a tag to analyze.")
            self.validation_label.show()
            self.tag_input.setFocus()
            return

        all_results = analyze_tag_correlations(selected, query)
        self._results = all_results[:MAX_RELATED_TAGS]
        positive_count = sum(
            query in {tag.strip() for tag in entry.tags} for entry in selected
        )
        negative_count = len(selected) - positive_count
        self.result_label.setText(
            f"{len(selected)} image(s) analyzed: {positive_count} positive, "
            f"{negative_count} negative for {query!r}."
        )
        self.results.setRowCount(len(self._results))
        total_images = len(selected)
        for row, result in enumerate(self._results):
            positive_share = result.positive / total_images
            negative_share = result.negative / total_images
            row_items = [
                QTableWidgetItem(result.tag),
                QTableWidgetItem(
                    f"{result.positive} ({positive_share:.1%})"
                ),
                QTableWidgetItem(
                    f"{result.negative} ({negative_share:.1%})"
                ),
                QTableWidgetItem(f"{result.positive_rate:.1%}"),
            ]
            for column, item in enumerate(row_items):
                self.results.setItem(row, column, item)
            for column in (1, 2, 3):
                item = row_items[column]
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if (
                positive_share > HIGH_CORRELATION_THRESHOLD
                and result.positive_rate > HIGH_CORRELATION_THRESHOLD
            ):
                for item in row_items:
                    item.setBackground(HIGH_CORRELATION_BACKGROUND)
        self.pages.setCurrentWidget(self.results_page)

    def _show_results_page(self) -> None:
        """Compatibility wrapper for callers that treat the first page as a step."""
        self.analyze()

    def _show_selection_page(self) -> None:
        self.pages.setCurrentWidget(self.selection_page)
        self.tag_input.setFocus()
