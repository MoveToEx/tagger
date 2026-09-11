from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QTreeView
import pytest

from tagger.domain.models import ImageEntry
from tagger.ui.catalog import ImageCatalogModel, ImageCatalogView


pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows native drag message handling"
)


@pytest.fixture
def catalog(qtbot, tmp_path: Path, monkeypatch) -> ImageCatalogView:
    view = ImageCatalogView()
    qtbot.addWidget(view)
    model = ImageCatalogModel(view)
    paths = [tmp_path / "source.png"] + [
        tmp_path / f"folder-{index:02d}" / "image.png" for index in range(50)
    ]
    model.set_entries([
        ImageEntry(path, path.with_suffix(".txt"), [], b"") for path in paths
    ], tmp_path)
    view.setModel(model)
    view.resize(300, 240)
    view.expandAll()
    view.show()
    qtbot.waitExposed(view)
    view.setCurrentIndex(model.index_for_row(0))
    scroll_bar = view.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    scroll_bar.setValue(scroll_bar.maximum() // 2)
    position = view.viewport().mapToGlobal(view.viewport().rect().center())
    monkeypatch.setattr(QCursor, "pos", lambda: position)
    return view


@pytest.fixture
def wheel_messages():
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.PostThreadMessageW.argtypes = (
        wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = (
        ctypes.POINTER(wintypes.MSG), wintypes.HWND,
        wintypes.UINT, wintypes.UINT, wintypes.UINT,
    )
    user32.PeekMessageW.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def post(delta: int) -> None:
        assert user32.PostThreadMessageW(
            kernel32.GetCurrentThreadId(), 0x020A, (delta & 0xFFFF) << 16, 0
        )

    def take(*, remove: bool = True) -> int:
        message = wintypes.MSG()
        # Retrieve the OS message without dispatching it to Qt, as OLE can do.
        assert user32.PeekMessageW(
            ctypes.byref(message), None, 0x020A, 0x020A, int(remove)
        )
        return message.message

    return post, take


@pytest.mark.parametrize("cancel_with_error", [False, True])
def test_native_drag_wheel_scrolls_once_and_cleans_up(
    catalog, wheel_messages, monkeypatch, cancel_with_error: bool
) -> None:
    post, take = wheel_messages
    scroll_bar = catalog.verticalScrollBar()
    start_value = scroll_bar.value()

    def native_drag(_view, _actions) -> None:
        post(-120)
        assert take(remove=False) == 0x020A
        assert take(remove=False) == 0x020A
        assert scroll_bar.value() == start_value
        assert take() == 0  # WM_NULL prevents a second delivery to Qt.
        assert scroll_bar.value() > start_value
        post(120)
        assert take() == 0
        assert scroll_bar.value() == start_value

        outside = catalog.viewport().mapToGlobal(QPoint(-20, -20))
        monkeypatch.setattr(QCursor, "pos", lambda: outside)
        post(-120)
        assert take() == 0x020A
        assert scroll_bar.value() == start_value
        if cancel_with_error:
            raise RuntimeError("Drag interrupted")

    monkeypatch.setattr(QTreeView, "startDrag", native_drag)
    if cancel_with_error:
        with pytest.raises(RuntimeError, match="Drag interrupted"):
            catalog.startDrag(Qt.DropAction.MoveAction)
    else:
        catalog.startDrag(Qt.DropAction.MoveAction)

    position = catalog.viewport().mapToGlobal(catalog.viewport().rect().center())
    monkeypatch.setattr(QCursor, "pos", lambda: position)
    post(-120)
    assert take() == 0x020A
    assert scroll_bar.value() == start_value
    assert not catalog._catalog_drag_active
    assert not catalog._native_drag_running
    assert not catalog._edge_scroll_timer.isActive()
    assert catalog.state() == QAbstractItemView.State.NoState


def test_native_wheel_then_drop_uses_folder_now_under_pointer(
    qtbot, catalog, wheel_messages, monkeypatch
) -> None:
    post, take = wheel_messages
    model = catalog.model()
    entry = model.entry(0)
    mime_data = model.mimeData([model.index_for_row(0)])
    position = catalog.viewport().rect().center()
    original_destination = model.destination_for_index(catalog.indexAt(position))
    moves = []
    catalog.image_move_requested.connect(lambda *args: moves.append(args))
    destinations = []

    def native_drag(_view, _actions) -> None:
        enter = QDragEnterEvent(
            position, Qt.DropAction.MoveAction, mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        catalog.dragEnterEvent(enter)
        assert enter.isAccepted()
        post(-120)
        assert take() == 0
        destination = model.destination_for_index(catalog.indexAt(position))
        assert destination is not None
        assert destination != original_destination
        destinations.append(destination)
        drop = QDropEvent(
            QPointF(position), Qt.DropAction.MoveAction, mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        catalog.dropEvent(drop)
        assert drop.isAccepted()
        assert moves == []

    monkeypatch.setattr(QTreeView, "startDrag", native_drag)
    catalog.startDrag(Qt.DropAction.MoveAction)

    qtbot.waitUntil(lambda: len(moves) == 1)
    assert moves == [(entry, destinations[0])]
