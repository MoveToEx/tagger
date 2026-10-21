from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.tag_library.library import TagLibrary


class FlatImageTree(QTreeWidget):
    """A flat image list with tree-view selection and activation behavior."""

    image_activated = Signal(Path)
    ImagePathRole = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(
        self,
        entries: Sequence[ImageEntry],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.entries = list(entries)
        self.root_directory = root_directory
        self.setColumnCount(1)
        self.setHeaderLabels(["Image"])
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.itemDoubleClicked.connect(self._activate_image)
        self._populate()

    def _populate(self) -> None:
        self.clear()
        for entry in self.entries:
            item = QTreeWidgetItem([self._display_path(entry.image_path)])
            item.setData(0, self.ImagePathRole, entry.image_path)
            item.setToolTip(0, str(entry.image_path))
            self.addTopLevelItem(item)

    def _display_path(self, path: Path) -> str:
        if self.root_directory is not None:
            try:
                return path.relative_to(self.root_directory).as_posix()
            except ValueError:
                pass
        return path.name

    def _activate_image(self, item: QTreeWidgetItem, _column: int) -> None:
        path = item.data(0, self.ImagePathRole)
        if isinstance(path, Path):
            self.image_activated.emit(path)


def rare_tag_counts(
    entries: Sequence[ImageEntry], tag_library: TagLibrary
) -> list[tuple[str, int]]:
    """Count images containing tags absent from the local Danbooru library."""
    counts: Counter[str] = Counter()
    for entry in entries:
        for tag in set(entry.tags):
            tag = tag.strip()
            if tag and not tag_library.is_danbooru_tag(tag):
                counts[tag] += 1
    return sorted(
        counts.items(), key=lambda item: (-item[1], item[0].casefold(), item[0])
    )


class RareTagsDialog(QDialog):
    tag_activated = Signal(str)

    def __init__(
        self,
        entries: Sequence[ImageEntry],
        tag_library: TagLibrary,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.entries = list(entries)
        self.tag_library = tag_library
        self.setWindowTitle("Find Rare Tags")
        self.resize(560, 480)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)

        self.count_label = QLabel()
        self.count_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.results = QTableWidget(0, 3)
        self.results.setHorizontalHeaderLabels(
            ["Tag name", "Image count", "Percentage"]
        )
        self.results.horizontalHeader().setStretchLastSection(False)
        self.results.horizontalHeader().setSectionResizeMode(
            0, self.results.horizontalHeader().ResizeMode.Stretch
        )
        for column in (1, 2):
            self.results.horizontalHeader().setSectionResizeMode(
                column, self.results.horizontalHeader().ResizeMode.ResizeToContents
            )
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.results.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.results.itemDoubleClicked.connect(self._activate_tag)
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(
            self._show_results_context_menu
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.count_label)
        layout.addWidget(self.results, 1)
        layout.addWidget(buttons)
        self._populate_results()

    def _populate_results(self) -> None:
        total_images = len(self.entries)
        matches = rare_tag_counts(self.entries, self.tag_library)
        self.count_label.setText(
            f"{len(matches)} rare tag(s) across {total_images} image(s)."
        )
        self.results.setRowCount(len(matches))
        for row, (tag, count) in enumerate(matches):
            self.results.setItem(row, 0, QTableWidgetItem(tag))
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results.setItem(row, 1, count_item)
            percentage = count / total_images * 100 if total_images else 0.0
            percentage_item = QTableWidgetItem(f"{percentage:.1f}%")
            percentage_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.results.setItem(row, 2, percentage_item)

    def _selected_tags(self) -> list[str]:
        rows = sorted({index.row() for index in self.results.selectedIndexes()})
        tags: list[str] = []
        for row in rows:
            item = self.results.item(row, 0)
            if item is not None:
                tags.append(item.text())
        return tags

    def _copy_selected_tags(self) -> None:
        tags = self._selected_tags()
        if tags:
            QGuiApplication.clipboard().setText(", ".join(tags))

    def _show_results_context_menu(self, position) -> None:
        index = self.results.indexAt(position)
        if index.isValid() and index.row() not in {
            selected.row() for selected in self.results.selectedIndexes()
        }:
            self.results.clearSelection()
            self.results.selectRow(index.row())
        copy_action = QAction("Copy", self)
        copy_action.setEnabled(bool(self._selected_tags()))
        copy_action.triggered.connect(self._copy_selected_tags)
        menu = QMenu(self)
        menu.addAction(copy_action)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.results.viewport().mapToGlobal(position))

    def _activate_tag(self, item: QTableWidgetItem) -> None:
        tag = item.text().strip()
        if tag:
            self.tag_activated.emit(tag)


class RareTagImagesDialog(QDialog):
    image_activated = Signal(Path)

    def __init__(
        self,
        tag: str,
        entries: Sequence[ImageEntry],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.tag = tag
        self.entries = [entry for entry in entries if tag in entry.tags]
        self.setWindowTitle(f"Images with Tag: {tag}")
        self.resize(560, 480)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)

        self.count_label = QLabel(
            f"{len(self.entries)} image(s) contain the tag \"{tag}\"."
        )
        self.count_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.image_tree = FlatImageTree(
            self.entries,
            root_directory=root_directory,
        )
        self.image_tree.image_activated.connect(self.image_activated)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.count_label)
        layout.addWidget(self.image_tree, 1)
        layout.addWidget(buttons)
