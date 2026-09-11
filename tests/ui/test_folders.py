from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QModelIndex, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMenu,
    QStyle,
    QStyledItemDelegate,
)
import pytest

from tagger.settings.preferences import OPEN_RECENT_FOLDER_ON_STARTUP_SETTING
from tagger.settings.store import JsonSettings
import tagger.ui.main_window.files as window_files
from tagger.ui.main_window.folders import MAX_RECENT_FOLDERS, RECENT_FOLDERS_SETTING
from tagger.ui.main_window.window import MainWindow
import tagger.ui.main_window.window as main_window_module

from .helpers import create_png


def test_file_menu_opens_recent_folder(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    current = tmp_path / "current"
    recent_a = tmp_path / "recent-a"
    recent_b = tmp_path / "recent-b"
    for folder in (current, recent_a, recent_b):
        folder.mkdir()
        create_png(folder / "sample.png")
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(
        RECENT_FOLDERS_SETTING,
        [str(recent_a), str(recent_b)],
    )
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.directory is None
    assert window.commands.open_recent_action.text() == "Open Recent"
    assert window.commands.open_recent_action.isEnabled()
    assert window.commands.open_recent_menu.title() == "Open Recent"
    assert [action.text() for action in window.commands.open_recent_menu.actions()] == [
        str(recent_a),
        str(recent_b),
    ]
    file_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&File"
    )
    assert file_menu is not None
    assert window.commands.open_recent_action in file_menu.actions()

    window.folders._load_directory(current, show_issues=False)

    assert window.directory == current
    assert window.commands.open_recent_action.isEnabled()
    window.folders._update_recent_folder_menu()
    recent_action = next(
        action
        for action in window.commands.open_recent_menu.actions()
        if action.text() == str(recent_b)
    )
    recent_action.trigger()

    assert window.directory == recent_b
    assert window.commands.open_recent_action.isEnabled()
    assert window.catalog.image_count == 1
    assert settings.value(RECENT_FOLDERS_SETTING) == [
        str(recent_b),
        str(current),
        str(recent_a),
    ]


def test_open_folder_uses_most_recent_folder(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    recent = tmp_path / "recent"
    recent.mkdir()
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(RECENT_FOLDERS_SETTING, [str(recent)])
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )
    starts: list[str] = []

    def get_existing_directory(_parent, _title: str, start: str) -> str:
        starts.append(start)
        return ""

    monkeypatch.setattr(
        window_files.QFileDialog,
        "getExistingDirectory",
        get_existing_directory,
    )

    window = MainWindow()
    qtbot.addWidget(window)
    window.folders.open_folder()

    assert starts == [str(recent)]


def test_main_window_opens_most_recent_folder_on_startup(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    recent_a = tmp_path / "recent-a"
    recent_b = tmp_path / "recent-b"
    for folder in (recent_a, recent_b):
        folder.mkdir()
        create_png(folder / "sample.png")
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(OPEN_RECENT_FOLDER_ON_STARTUP_SETTING, True)
    settings.setValue(
        RECENT_FOLDERS_SETTING,
        [str(recent_a), str(recent_b)],
    )
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.directory == recent_a
    assert window.catalog.image_count == 1
    assert window.windowTitle() == f"{recent_a.name} - Image Tagger"
    qtbot.waitUntil(lambda: "32 × 24 px" in window.image_info_label.text())


def test_folder_load_emits_one_current_image_change(
    qtbot, tmp_path: Path
) -> None:
    for index in range(40):
        create_png(tmp_path / f"image-{index:02d}.png")
        (tmp_path / f"image-{index:02d}.txt").write_text(
            "cat, dog\n", encoding="utf-8"
        )
    window = MainWindow()
    qtbot.addWidget(window)
    current_changes: list[QModelIndex] = []
    window.image_list.selectionModel().currentChanged.connect(
        lambda current, _previous: current_changes.append(current)
    )

    window.folders._load_directory(tmp_path, show_issues=False)

    assert len(current_changes) == 1
    assert window.catalog.entry_for_index(current_changes[0]) is not None
    assert window.preview_loader.wait_for_done()


def test_file_menu_disables_missing_recent_folder(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(
        RECENT_FOLDERS_SETTING,
        [str(tmp_path / "missing")],
    )
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.directory is None
    assert not window.commands.open_recent_action.isEnabled()
    assert window.commands.open_recent_menu.actions() == []
    assert window.commands.open_recent_action.toolTip() == (
        "No recently opened folder is available."
    )


def test_recent_folders_are_deduplicated_and_capped(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )
    folders = [tmp_path / f"folder-{index}" for index in range(12)]
    for folder in folders:
        folder.mkdir()
    window = MainWindow()
    qtbot.addWidget(window)

    for folder in folders:
        window.folders._record_recent_folder(folder)
    window.folders._record_recent_folder(folders[-3])

    recent = settings.value(RECENT_FOLDERS_SETTING)
    assert isinstance(recent, list)
    assert recent == [
        str(folders[-3]),
        *[
            str(folder)
            for folder in reversed(folders)
            if folder != folders[-3]
        ][: MAX_RECENT_FOLDERS - 1],
    ]


def test_image_list_groups_images_by_subfolder(qtbot, tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    deep = nested / "deep"
    nested.mkdir()
    deep.mkdir()
    create_png(tmp_path / "root.png")
    create_png(nested / "child.png")
    create_png(deep / "grandchild.png")
    window = MainWindow()
    qtbot.addWidget(window)

    window.folders._load_directory(tmp_path, show_issues=False)

    assert window.catalog.rowCount() == 2
    nested_index = window.catalog.index(0, 0)
    assert window.catalog.data(nested_index) == "nested"
    assert window.catalog.entry_for_index(nested_index) is None
    assert window.catalog.rowCount(nested_index) == 2
    assert window.catalog.data(window.catalog.index(0, 0, nested_index)) == "deep"
    assert window.catalog.data(
        window.catalog.index(1, 0, nested_index)
    ).startswith("child.png")
    assert window.catalog.data(window.catalog.index(1, 0)).startswith("root.png")
    assert window.catalog.group_for_row(0) == "Root folder"
    assert window.catalog.group_for_row(1) == "nested"
    assert window.catalog.group_for_row(2) == "nested/deep"

    window.image_list.collapse(nested_index)
    assert not window.image_list.isExpanded(nested_index)
    window.image_list.expand(nested_index)
    assert window.image_list.isExpanded(nested_index)
    window.commands.next_action.trigger()
    current = window._current_entry()
    assert current is not None
    assert current.image_path == nested / "child.png"
    window.commands.next_action.trigger()
    current = window._current_entry()
    assert current is not None
    assert current.image_path == deep / "grandchild.png"
    assert not window.commands.next_action.isEnabled()


def test_image_catalog_drag_moves_image_and_sidecar_into_folder(
    qtbot, tmp_path: Path
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    source_image = tmp_path / "source.png"
    source_tag = tmp_path / "source.txt"
    create_png(source_image)
    source_tag.write_text("cat\n", encoding="utf-8")
    create_png(nested / "existing.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.folders._load_directory(tmp_path, show_issues=False)

    folder_index = window.catalog.index(0, 0)
    source_row = window.catalog.row_for_image(source_image)
    assert source_row is not None
    source_index = window.catalog.index_for_row(source_row)
    assert source_index.flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert folder_index.flags() & Qt.ItemFlag.ItemIsDropEnabled
    assert (
        window.image_list.dragDropMode()
        == QAbstractItemView.DragDropMode.DragDrop
    )

    mime_data = window.catalog.mimeData([source_index])
    position = window.image_list.visualRect(folder_index).center()
    drag_event = QDragEnterEvent(
        position,
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dragEnterEvent(drag_event)
    assert drag_event.isAccepted()
    move_event = QDragMoveEvent(
        position,
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dragMoveEvent(move_event)
    assert move_event.isAccepted()
    drop_event = QDropEvent(
        QPointF(position),
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dropEvent(drop_event)

    moved_image = nested / "source.png"
    moved_tag = nested / "source.txt"
    assert drop_event.isAccepted()
    qtbot.waitUntil(moved_image.exists)
    assert not source_image.exists()
    assert not source_tag.exists()
    assert moved_image.exists()
    assert moved_tag.read_text(encoding="utf-8") == "cat\n"
    current = window._current_entry()
    assert current is not None
    assert current.image_path == moved_image
    moved_row = window.catalog.row_for_image(moved_image)
    assert moved_row is not None
    assert window.catalog.destination_for_index(
        window.catalog.index_for_row(moved_row)
    ) == nested
    assert window.image_list.state() == QAbstractItemView.State.NoState
    assert "Moved source.png and source.txt to nested." in (
        window.statusBar().currentMessage()
    )


def test_image_catalog_drop_onto_image_moves_pair_to_its_folder(
    qtbot, tmp_path: Path
) -> None:
    origin = tmp_path / "origin"
    nested = tmp_path / "nested"
    origin.mkdir()
    nested.mkdir()
    source_image = origin / "source.png"
    source_tag = origin / "source.txt"
    create_png(source_image)
    source_tag.write_text("cat\n", encoding="utf-8")
    target_image = nested / "target.png"
    create_png(target_image)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.folders._load_directory(tmp_path, show_issues=False)

    source_row = window.catalog.row_for_image(source_image)
    target_row = window.catalog.row_for_image(target_image)
    assert source_row is not None
    assert target_row is not None
    mime_data = window.catalog.mimeData(
        [window.catalog.index_for_row(source_row)]
    )
    target_index = window.catalog.index_for_row(target_row)
    position = window.image_list.visualRect(target_index).center()
    drag_event = QDragEnterEvent(
        position,
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dragEnterEvent(drag_event)
    move_event = QDragMoveEvent(
        position,
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    window.image_list.dragMoveEvent(move_event)
    drop_event = QDropEvent(
        QPointF(position),
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dropEvent(drop_event)

    moved_image = nested / "source.png"
    assert drag_event.isAccepted()
    assert move_event.isAccepted()
    assert drop_event.isAccepted()
    qtbot.waitUntil(moved_image.exists)
    assert not source_image.exists()
    assert not source_tag.exists()
    assert moved_image.exists()
    assert (nested / "source.txt").read_text(encoding="utf-8") == "cat\n"
    assert window.catalog.rowCount() == 1
    destination_folder = window.catalog.index(0, 0)
    assert window.catalog.data(destination_folder) == "nested"
    assert window.catalog.rowCount(destination_folder) == 2
    assert window.catalog.row_for_image(source_image) is None
    moved_row = window.catalog.row_for_image(moved_image)
    assert moved_row is not None
    assert window.catalog.index_for_row(moved_row).parent() == destination_folder


def test_image_catalog_scrolls_with_wheel_during_drag(
    qtbot, tmp_path: Path
) -> None:
    for index in range(50):
        create_png(tmp_path / f"image-{index:02d}.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(600, 320)
    window.show()
    window.folders._load_directory(tmp_path, show_issues=False)
    scroll_bar = window.image_list.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    scroll_bar.setValue(scroll_bar.maximum() // 2)
    start_value = scroll_bar.value()

    source_index = window.catalog.index_for_row(0)
    mime_data = window.catalog.mimeData([source_index])
    position = window.image_list.viewport().rect().center()
    drag_event = QDragEnterEvent(
        position,
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dragEnterEvent(drag_event)
    wheel_event = QWheelEvent(
        QPointF(position),
        QPointF(window.image_list.viewport().mapToGlobal(position)),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    QApplication.sendEvent(window, wheel_event)
    down_value = scroll_bar.value()
    up_event = QWheelEvent(
        QPointF(position),
        QPointF(window.image_list.viewport().mapToGlobal(position)),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(window, up_event)
    window.image_list.dragLeaveEvent(QDragLeaveEvent())

    assert wheel_event.isAccepted()
    assert down_value > start_value
    assert up_event.isAccepted()
    assert scroll_bar.value() == start_value


@pytest.mark.parametrize("folder_name", ["", "nested"])
def test_image_catalog_drag_hover_follows_files_in_same_folder(
    qtbot, tmp_path: Path, folder_name: str
) -> None:
    directory = tmp_path / folder_name
    directory.mkdir(exist_ok=True)
    image_paths = [directory / f"image-{index}.png" for index in range(3)]
    for path in image_paths:
        create_png(path)
        path.with_suffix(".txt").write_bytes(b"cat\n")
    other = tmp_path / "other"
    other.mkdir()
    create_png(other / "target.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.folders._load_directory(tmp_path, show_issues=False)
    view = window.image_list
    model = window.catalog
    indexes = []
    for path in image_paths:
        row = model.row_for_image(path)
        assert row is not None
        indexes.append(model.index_for_row(row))
    view.setCurrentIndex(indexes[0])
    moves = []
    view.image_move_requested.connect(lambda *args: moves.append(args))
    hovered = set()

    class HoverDelegate(QStyledItemDelegate):
        def paint(self, painter, option, index) -> None:
            if option.state & QStyle.StateFlag.State_MouseOver:
                hovered.add(QModelIndex(index))
            else:
                hovered.discard(index)
            super().paint(painter, option, index)

    view.setItemDelegate(HoverDelegate(view))
    mime_data = model.mimeData([indexes[0]])
    position = view.visualRect(indexes[0]).center()
    enter = QDragEnterEvent(
        position, Qt.DropAction.MoveAction, mime_data,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), enter)
    assert enter.isAccepted()

    other_row = model.row_for_image(other / "target.png")
    assert other_row is not None
    targets = [model.index_for_row(other_row), *indexes[1:], indexes[0]]
    if folder_name:
        targets.append(indexes[0].parent())
    for target in targets:
        position = view.visualRect(target).center()
        move = QDragMoveEvent(
            position, Qt.DropAction.MoveAction, mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(view.viewport(), move)
        assert move.isAccepted()
        qtbot.waitUntil(lambda: hovered == {target})
        assert view.currentIndex() == indexes[0]
        assert view.selectionModel().selectedIndexes() == [indexes[0]]

    drop = QDropEvent(
        QPointF(position), Qt.DropAction.MoveAction, mime_data,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), drop)
    QApplication.processEvents()

    assert not drop.isAccepted()
    assert moves == []
    assert view.state() == QAbstractItemView.State.NoState
    assert not view._edge_scroll_timer.isActive()
    for path in image_paths:
        assert path.is_file()
        assert path.with_suffix(".txt").read_bytes() == b"cat\n"


def test_image_catalog_scrolls_with_mouse_wheel(qtbot, tmp_path: Path) -> None:
    for index in range(50):
        create_png(tmp_path / f"image-{index:02d}.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(600, 320)
    window.show()
    window.folders._load_directory(tmp_path, show_issues=False)
    viewport = window.image_list.viewport()
    scroll_bar = window.image_list.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    assert scroll_bar.value() == 0
    position = viewport.rect().center()
    wheel_event = QWheelEvent(
        QPointF(position),
        QPointF(viewport.mapToGlobal(position)),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    QApplication.sendEvent(viewport, wheel_event)

    assert wheel_event.isAccepted()
    assert scroll_bar.value() > 0


def test_image_catalog_scrolls_while_dragging_near_edges(
    qtbot, tmp_path: Path
) -> None:
    for index in range(50):
        create_png(tmp_path / f"image-{index:02d}.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(600, 320)
    window.show()
    window.folders._load_directory(tmp_path, show_issues=False)
    scroll_bar = window.image_list.verticalScrollBar()
    assert scroll_bar.maximum() > 0

    source_index = window.catalog.index_for_row(0)
    mime_data = window.catalog.mimeData([source_index])
    bottom = QPoint(
        window.image_list.viewport().width() // 2,
        window.image_list.viewport().height() - 2,
    )
    drag_event = QDragEnterEvent(
        bottom,
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dragEnterEvent(drag_event)
    move_event = QDragMoveEvent(
        bottom,
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dragMoveEvent(move_event)
    qtbot.waitUntil(lambda: scroll_bar.value() > 0)

    scroll_bar.setValue(scroll_bar.maximum())
    top = QPoint(window.image_list.viewport().width() // 2, 2)
    move_event = QDragMoveEvent(
        top,
        Qt.DropAction.MoveAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.image_list.dragMoveEvent(move_event)
    qtbot.waitUntil(lambda: scroll_bar.value() < scroll_bar.maximum())
    window.image_list.dragLeaveEvent(QDragLeaveEvent())

    assert not window.image_list._edge_scroll_timer.isActive()


def test_close_folder_empties_program_state(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog, cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.tag_input.setText("bird")
    window.search_input.setText("cat")

    assert window.commands.close_folder_action.isEnabled()
    window.commands.close_folder_action.trigger()

    assert window.directory is None
    assert window.catalog.rowCount() == 0
    assert not window.image_list.currentIndex().isValid()
    assert window.tag_list.count() == 0
    assert window.tag_input.text() == ""
    assert window.search_input.text() == ""
    assert window.image_view._pixmap is None
    assert window.image_view._label.text() == "Open a folder to begin"
    assert window.image_info_label.text() == "No image selected"
    assert window.windowTitle() == "Image Tagger"
    assert window.statusBar().currentMessage() == ""
    assert not window.commands.close_folder_action.isEnabled()
    assert not window.commands.rescan_action.isEnabled()
    assert not window.commands.tidy_action.isEnabled()
    assert not window.commands.archive_action.isEnabled()
    assert not window.search_input.isEnabled()
    assert not window.tag_input.isEnabled()
    assert not window.commands.bulk_operation_action.isEnabled()


def test_close_folder_allows_another_folder_drop(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.folders.close_folder()

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(tmp_path))])
    drag_event = QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    window.dragEnterEvent(drag_event)

    assert drag_event.isAccepted()


def test_dropped_folder_replaces_open_folder(qtbot, tmp_path: Path) -> None:
    first_folder = tmp_path / "first"
    second_folder = tmp_path / "second"
    first_folder.mkdir()
    second_folder.mkdir()
    create_png(first_folder / "first.png")
    create_png(second_folder / "second.png")
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(first_folder))])
    window = MainWindow()
    qtbot.addWidget(window)

    drag_event = QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(drag_event)
    assert drag_event.isAccepted()

    drop_event = QDropEvent(
        QPointF(20, 20),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop_event)
    assert drop_event.isAccepted()
    assert window.directory == first_folder
    assert window.catalog.rowCount() == 1

    window.tag_input.setText("stale tag")
    window.search_input.setText("stale search")
    replacement_mime_data = QMimeData()
    replacement_mime_data.setUrls([QUrl.fromLocalFile(str(second_folder))])
    second_drag = QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        replacement_mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(second_drag)
    assert second_drag.isAccepted()

    second_drop = QDropEvent(
        QPointF(20, 20),
        Qt.DropAction.CopyAction,
        replacement_mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(second_drop)

    assert second_drop.isAccepted()
    assert window.directory == second_folder
    assert window.catalog.rowCount() == 1
    assert window.catalog.entries[0].image_path == second_folder / "second.png"
    assert window.tag_input.text() == ""
    assert window.search_input.text() == ""
