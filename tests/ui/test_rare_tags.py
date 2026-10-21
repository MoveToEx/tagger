from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from tagger.domain.models import ImageEntry
from tagger.tag_library.format import write_tag_library
from tagger.tag_library.library import TagLibrary
from tagger.ui.dialogs.rare_tags import RareTagsDialog
from tagger.ui.main_window.window import MainWindow

from .helpers import create_png


def test_rare_tags_dialog_counts_images_and_percentages(
    qtbot, tmp_path: Path
) -> None:
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("known", 100)])
    library = TagLibrary(library_path)
    entries = [
        ImageEntry(
            tmp_path / "one.png", tmp_path / "one.txt", ["known", "custom"]
        ),
        ImageEntry(tmp_path / "two.png", tmp_path / "two.txt", ["custom"]),
        ImageEntry(tmp_path / "three.png", tmp_path / "three.txt", ["unique"]),
    ]

    dialog = RareTagsDialog(entries, library)
    qtbot.addWidget(dialog)

    assert dialog.results.rowCount() == 2
    values: list[tuple[str, str, str]] = []
    for row in range(dialog.results.rowCount()):
        items = [dialog.results.item(row, column) for column in range(3)]
        assert all(item is not None for item in items)
        assert items[0] is not None
        assert items[1] is not None
        assert items[2] is not None
        values.append((items[0].text(), items[1].text(), items[2].text()))
    assert values == [("custom", "2", "66.7%"), ("unique", "1", "33.3%")]


def test_rare_tags_action_is_disabled_without_local_library(
    qtbot, tmp_path: Path
) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)

    tags_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&Tags"
    )
    assert [action.text() for action in tags_menu.actions()[:3]] == [
        "Global Search...",
        "Find Rare Tags...",
        "",
    ]
    assert not window.commands.rare_tags_action.isEnabled()


def test_rare_tag_dialogs_are_modeless_and_select_main_window_image(
    qtbot, tmp_path: Path
) -> None:
    library_path = tmp_path / "data" / "tag-lib" / "danbooru_tags.bin"
    write_tag_library(library_path, [("known", 100)])
    for name, tags in {
        "first.png": "known, custom\n",
        "second.png": "custom\n",
        "third.png": "known\n",
    }.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.dialogs._open_rare_tags()

    rare_dialog = window.dialogs._rare_tags_dialog
    assert rare_dialog is not None
    assert not rare_dialog.isModal()
    assert rare_dialog.windowModality() == Qt.WindowModality.NonModal
    assert window.image_list.isEnabled()

    result_item = rare_dialog.results.item(0, 0)
    assert result_item is not None
    rare_dialog.results.itemDoubleClicked.emit(result_item)

    image_dialog = window.dialogs._rare_tag_images_dialog
    assert image_dialog is not None
    assert not image_dialog.isModal()
    assert image_dialog.windowModality() == Qt.WindowModality.NonModal
    assert image_dialog.image_tree.topLevelItemCount() == 2
    image_item = image_dialog.image_tree.topLevelItem(1)
    assert image_item is not None
    image_dialog.image_tree.itemDoubleClicked.emit(image_item, 0)

    current = window._current_entry()
    assert current is not None
    assert current.image_path == tmp_path / "second.png"

