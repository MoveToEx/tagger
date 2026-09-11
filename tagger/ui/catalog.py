from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import override

from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QModelIndex,
    QObject,
    QPoint,
    QPersistentModelIndex,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QStandardItem,
    QStandardItemModel,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTreeView

from tagger.domain.models import ImageEntry
from tagger.settings.preferences import (
    CATALOG_CLICK_HOLD_BEHAVIORS,
    CATALOG_DRAG_AND_DROP,
)
from tagger.ui.drag_wheel import forward_native_drag_wheel


class ImageCatalogModel(QStandardItemModel):
    """Hierarchical folder model with a stable flat image order for navigation."""

    EntryRole = int(Qt.ItemDataRole.UserRole) + 1
    GroupRole = int(Qt.ItemDataRole.UserRole) + 2
    FolderRole = int(Qt.ItemDataRole.UserRole) + 3
    ImageMimeType = "application/x-tagger-image-path"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.entries: list[ImageEntry] = []
        self.groups: list[str] = []
        self._image_items: list[QStandardItem] = []
        self.root_directory: Path | None = None
        self.setHorizontalHeaderLabels(["Images"])

    def set_entries(
        self, entries: list[ImageEntry], root_directory: Path | None = None
    ) -> None:
        self.clear()
        self.setHorizontalHeaderLabels(["Images"])
        self.entries = entries
        self.groups = []
        self._image_items = []
        self.root_directory = root_directory

        root_item = self.invisibleRootItem()
        folder_items: dict[Path, QStandardItem] = {Path("."): root_item}
        relative_parents: list[Path] = []

        for entry in entries:
            if root_directory is None:
                relative_parent = Path(entry.image_path.parent.name or ".")
            else:
                relative_parent = entry.image_path.parent.relative_to(root_directory)
            relative_parents.append(relative_parent)
            self.groups.append(
                "Root folder"
                if relative_parent == Path(".")
                else relative_parent.as_posix()
            )

        folders = sorted(
            {
                ancestor
                for relative_parent in relative_parents
                for ancestor in _folder_ancestors(relative_parent)
            },
            key=lambda path: (
                len(path.parts),
                tuple(part.casefold() for part in path.parts),
                path.as_posix(),
            ),
        )
        for relative_folder in folders:
            parent_path = relative_folder.parent
            parent_item = folder_items[parent_path]
            folder_item = QStandardItem(relative_folder.name)
            folder_item.setEditable(False)
            folder_item.setSelectable(False)
            folder_item.setDragEnabled(False)
            folder_item.setDropEnabled(True)
            folder_item.setToolTip(relative_folder.as_posix())
            if root_directory is not None:
                folder_item.setData(
                    str(root_directory / relative_folder), self.FolderRole
                )
            parent_item.appendRow(folder_item)
            folder_items[relative_folder] = folder_item

        image_items: list[QStandardItem | None] = [None] * len(entries)
        for row, entry in enumerate(entries):
            if relative_parents[row] != Path("."):
                continue
            item = QStandardItem()
            item.setEditable(False)
            item.setDragEnabled(True)
            item.setDropEnabled(True)
            self._update_image_item(item, entry, self.groups[row])
            root_item.appendRow(item)
            image_items[row] = item
        for row, entry in enumerate(entries):
            if relative_parents[row] == Path("."):
                continue
            item = QStandardItem()
            item.setEditable(False)
            item.setDragEnabled(True)
            item.setDropEnabled(True)
            self._update_image_item(item, entry, self.groups[row])
            folder_items[relative_parents[row]].appendRow(item)
            image_items[row] = item
        self._image_items = [
            item for item in image_items if item is not None
        ]

    def entry(self, row: int) -> ImageEntry | None:
        if 0 <= row < len(self.entries):
            return self.entries[row]
        return None

    def entry_for_index(
        self, index: QModelIndex | QPersistentModelIndex
    ) -> ImageEntry | None:
        if not index.isValid():
            return None
        value = index.data(self.EntryRole)
        return value if isinstance(value, ImageEntry) else None

    def row_for_index(
        self, index: QModelIndex | QPersistentModelIndex
    ) -> int | None:
        entry = self.entry_for_index(index)
        if entry is None:
            return None
        return self.row_for_image(entry.image_path)

    def index_for_row(self, row: int) -> QModelIndex:
        if not 0 <= row < len(self._image_items):
            return QModelIndex()
        return self.indexFromItem(self._image_items[row])

    def row_for_image(self, image_path: Path) -> int | None:
        target = str(image_path.absolute()).casefold()
        for row, entry in enumerate(self.entries):
            if str(entry.image_path.absolute()).casefold() == target:
                return row
        return None

    def folder_for_index(
        self, index: QModelIndex | QPersistentModelIndex
    ) -> Path | None:
        if not index.isValid():
            return None
        value = index.data(self.FolderRole)
        return Path(value) if isinstance(value, str) else None

    def destination_for_index(
        self, index: QModelIndex | QPersistentModelIndex
    ) -> Path | None:
        folder = self.folder_for_index(index)
        if folder is not None:
            return folder
        entry = self.entry_for_index(index)
        return entry.image_path.parent if entry is not None else None

    @override
    def mimeTypes(self) -> list[str]:
        return [self.ImageMimeType]

    @override
    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:
        mime_data = QMimeData()
        entries = [
            entry
            for index in indexes
            if (entry := self.entry_for_index(index)) is not None
        ]
        if len(entries) == 1:
            mime_data.setData(
                self.ImageMimeType,
                str(entries[0].image_path).encode("utf-8"),
            )
        return mime_data

    def entry_from_mime_data(self, mime_data: QMimeData) -> ImageEntry | None:
        if not mime_data.hasFormat(self.ImageMimeType):
            return None
        try:
            image_path = Path(
                bytes(mime_data.data(self.ImageMimeType).data()).decode("utf-8")
            )
        except UnicodeError:
            return None
        row = self.row_for_image(image_path)
        return self.entry(row) if row is not None else None

    @override
    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    @override
    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    @override
    def canDropMimeData(
        self,
        data: QMimeData,
        action: Qt.DropAction,
        _row: int,
        _column: int,
        parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if action != Qt.DropAction.MoveAction:
            return False
        entry = self.entry_from_mime_data(data)
        destination = (
            self.destination_for_index(parent)
            if parent.isValid()
            else self.root_directory
        )
        # Qt also uses this check to update the drag hover indicator. Keep
        # same-folder targets active; the view rejects no-op moves on drop.
        return entry is not None and destination is not None

    def group_for_row(self, row: int) -> str | None:
        if 0 <= row < len(self.groups):
            return self.groups[row]
        return None

    @property
    def image_count(self) -> int:
        return len(self.entries)

    def image_position(self, row: int) -> int | None:
        return row + 1 if self.entry(row) is not None else None

    def first_image_row(self) -> int | None:
        return 0 if self.entries else None

    def last_image_row(self) -> int | None:
        return len(self.entries) - 1 if self.entries else None

    def next_image_row(self, row: int) -> int | None:
        return row + 1 if row + 1 < len(self.entries) else None

    def previous_image_row(self, row: int) -> int | None:
        return row - 1 if 0 < row < len(self.entries) else None

    def notify_entry_changed(self, row: int) -> None:
        entry = self.entry(row)
        if entry is None or not 0 <= row < len(self._image_items):
            return
        self._update_image_item(self._image_items[row], entry, self.groups[row])

    def _update_image_item(
        self, item: QStandardItem, entry: ImageEntry, group: str
    ) -> None:
        suffix = " [read-only]" if not entry.editable else ""
        item.setText(f"{entry.image_path.name}  ({len(entry.tags)}){suffix}")
        details = [str(entry.image_path), f"Tags: {entry.tag_path.name}"]
        details.extend(entry.warnings)
        if entry.error:
            details.append(entry.error)
            item.setForeground(QColor("#b42318"))
        else:
            item.setData(None, Qt.ItemDataRole.ForegroundRole)
        item.setToolTip("\n".join(details))
        item.setData(entry, self.EntryRole)
        item.setData(group, self.GroupRole)


class _CatalogDragWheelFilter(QObject):
    """Route wheel events back to a catalog during Qt's native drag loop."""

    def __init__(self, view: ImageCatalogView) -> None:
        super().__init__(view)
        self._view = view

    @override
    def eventFilter(self, _watched: QObject, event: QEvent) -> bool:
        if (
            not isinstance(event, QWheelEvent)
            or not self._view._catalog_drag_active
        ):
            return False
        viewport = self._view.viewport()
        position = viewport.mapFromGlobal(event.globalPosition().toPoint())
        return (
            viewport.rect().contains(position)
            and self._view._handle_drag_wheel(event)
        )


class ImageCatalogView(QTreeView):
    """Catalog tree that requests paired file moves for internal drops."""

    image_move_requested = Signal(object, object)
    EDGE_SCROLL_MARGIN = 28
    EDGE_SCROLL_INTERVAL = 75

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setAutoScroll(False)
        self._click_hold_behavior = CATALOG_DRAG_AND_DROP
        self._catalog_drag_active = False
        self._native_drag_running = False
        self._pending_move: tuple[ImageEntry, Path] | None = None
        self._edge_scroll_direction = 0
        self._edge_scroll_timer = QTimer(self)
        self._edge_scroll_timer.setInterval(self.EDGE_SCROLL_INTERVAL)
        self._edge_scroll_timer.timeout.connect(self._scroll_at_drag_edge)
        self._drag_wheel_filter = _CatalogDragWheelFilter(self)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self._drag_wheel_filter)

    @property
    def click_hold_behavior(self) -> str:
        return self._click_hold_behavior

    def set_click_hold_behavior(self, behavior: str) -> None:
        if behavior not in CATALOG_CLICK_HOLD_BEHAVIORS:
            behavior = CATALOG_DRAG_AND_DROP
        self._click_hold_behavior = behavior
        self.setDragDropMode(
            QAbstractItemView.DragDropMode.DragDrop
            if behavior == CATALOG_DRAG_AND_DROP
            else QAbstractItemView.DragDropMode.DropOnly
        )

    def set_catalog_click_hold_behavior(self, behavior: str) -> None:
        self.set_click_hold_behavior(behavior)

    def _catalog_model(self) -> ImageCatalogModel | None:
        model = self.model()
        return model if isinstance(model, ImageCatalogModel) else None

    def _dragged_entry(
        self, event: QDragEnterEvent | QDragMoveEvent | QDropEvent
    ) -> ImageEntry | None:
        model = self._catalog_model()
        return model.entry_from_mime_data(event.mimeData()) if model else None

    def _destination_at(self, position: QPoint) -> Path | None:
        model = self._catalog_model()
        if model is None:
            return None
        index = self.indexAt(position)
        if index.isValid():
            return model.destination_for_index(index)
        if self.viewport().rect().contains(position):
            return model.root_directory
        return None

    @staticmethod
    def _same_directory(first: Path, second: Path) -> bool:
        return str(first.absolute()).casefold() == str(second.absolute()).casefold()

    def _update_edge_scroll(self, position: QPoint | None) -> None:
        direction = 0
        if position is not None:
            if position.y() <= self.EDGE_SCROLL_MARGIN:
                direction = -1
            elif (
                position.y()
                >= self.viewport().height() - self.EDGE_SCROLL_MARGIN
            ):
                direction = 1
        self._edge_scroll_direction = direction
        if direction:
            self._edge_scroll_timer.start()
        else:
            self._edge_scroll_timer.stop()

    def _scroll_at_drag_edge(self) -> None:
        scroll_bar = self.verticalScrollBar()
        step = max(1, scroll_bar.singleStep())
        scroll_bar.setValue(
            scroll_bar.value() + self._edge_scroll_direction * step
        )

    def _finish_drag_tracking(self) -> None:
        self._catalog_drag_active = False
        self._update_edge_scroll(None)
        self.setState(QAbstractItemView.State.NoState)
        self.viewport().update()

    def _dispatch_pending_move(self) -> None:
        pending_move = self._pending_move
        self._pending_move = None
        if pending_move is not None:
            self.image_move_requested.emit(*pending_move)

    @override
    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        if self._click_hold_behavior != CATALOG_DRAG_AND_DROP:
            return
        self._catalog_drag_active = True
        self._native_drag_running = True
        self._pending_move = None
        try:
            with forward_native_drag_wheel(self.viewport()):
                super().startDrag(supported_actions)
        finally:
            self._native_drag_running = False
            self._finish_drag_tracking()
        if self._pending_move is not None:
            QTimer.singleShot(0, self._dispatch_pending_move)

    def _handle_drag_wheel(self, event: QWheelEvent) -> bool:
        if not self._catalog_drag_active:
            return False

        pixel_delta = event.pixelDelta().y()
        if pixel_delta:
            scroll_amount = pixel_delta
        else:
            angle_delta = event.angleDelta().y()
            scroll_amount = round(
                angle_delta
                / 120
                * QApplication.wheelScrollLines()
                * max(1, self.verticalScrollBar().singleStep())
            )
        if event.inverted():
            scroll_amount = -scroll_amount
        if scroll_amount:
            scroll_bar = self.verticalScrollBar()
            scroll_bar.setValue(scroll_bar.value() - scroll_amount)
        event.accept()
        return True

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._handle_drag_wheel(event):
            super().wheelEvent(event)

    @override
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        super().dragEnterEvent(event)
        if (
            self._click_hold_behavior != CATALOG_DRAG_AND_DROP
            or self._dragged_entry(event) is None
        ):
            self._finish_drag_tracking()
            event.ignore()
            return
        self._catalog_drag_active = True
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    @override
    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        super().dragMoveEvent(event)
        entry = self._dragged_entry(event)
        if self._click_hold_behavior != CATALOG_DRAG_AND_DROP:
            entry = None
        self._update_edge_scroll(
            event.position().toPoint() if entry is not None else None
        )
        destination = self._destination_at(event.position().toPoint())
        if entry is None or destination is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    @override
    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._finish_drag_tracking()
        super().dragLeaveEvent(event)

    @override
    def dropEvent(self, event: QDropEvent) -> None:
        entry = self._dragged_entry(event)
        destination = self._destination_at(event.position().toPoint())
        self._finish_drag_tracking()
        if (
            self._click_hold_behavior != CATALOG_DRAG_AND_DROP
            or entry is None
            or destination is None
            or self._same_directory(entry.image_path.parent, destination)
        ):
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self._pending_move = (entry, destination)
        if not self._native_drag_running:
            QTimer.singleShot(0, self._dispatch_pending_move)


def _folder_ancestors(path: Path) -> list[Path]:
    if path == Path("."):
        return []
    return [Path(*path.parts[:length]) for length in range(1, len(path.parts) + 1)]
