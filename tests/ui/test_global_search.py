from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtGui import QGuiApplication

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.global_search import GlobalTagSearchDialog
from tagger.ui.main_window.window import MainWindow

from .helpers import create_png


def test_global_tag_search_shows_matching_tag_counts(qtbot, tmp_path: Path) -> None:
    entries = [
        ImageEntry(tmp_path / "one.png", tmp_path / "one.txt", ["cat", "dog"]),
        ImageEntry(
            tmp_path / "two.png",
            tmp_path / "two.txt",
            ["cat", "cathedral"],
        ),
    ]
    dialog = GlobalTagSearchDialog(entries)
    qtbot.addWidget(dialog)

    dialog.pattern_input.setText("cat*")
    dialog.search()

    tag_header = dialog.results.horizontalHeaderItem(0)
    count_header = dialog.results.horizontalHeaderItem(1)
    assert tag_header is not None
    assert count_header is not None
    assert tag_header.text() == "Tag name"
    assert count_header.text() == "Tag count"
    assert dialog.count_label.text() == (
        "2 matching tag(s) across 3 image occurrence(s)."
    )
    assert dialog.results.rowCount() == 2
    values: list[tuple[str, str]] = []
    for row in range(dialog.results.rowCount()):
        tag_item = dialog.results.item(row, 0)
        count_item = dialog.results.item(row, 1)
        assert tag_item is not None
        assert count_item is not None
        values.append((tag_item.text(), count_item.text()))
    assert values == [("cat", "2"), ("cathedral", "1")]

    dialog.pattern_input.setText("dog")
    dialog.search()

    tag_header = dialog.results.horizontalHeaderItem(0)
    count_header = dialog.results.horizontalHeaderItem(1)
    assert tag_header is not None
    assert count_header is not None
    assert tag_header.text() == "Tag name"
    assert count_header.text() == "Tag count"


def test_global_tag_search_copies_selected_table_rows(qtbot, tmp_path: Path) -> None:
    entries = [
        ImageEntry(tmp_path / "one.png", tmp_path / "one.txt", ["cat", "dog"]),
        ImageEntry(tmp_path / "two.png", tmp_path / "two.txt", ["cat", "bird"]),
    ]
    dialog = GlobalTagSearchDialog(entries)
    qtbot.addWidget(dialog)
    dialog.pattern_input.setText("*")
    dialog.search()

    dialog.results.clearSelection()
    for row in (0, 2):
        dialog.results.selectionModel().select(
            dialog.results.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )
    dialog._copy_selected_tags()

    assert QGuiApplication.clipboard().text() == "bird, dog"


def test_global_search_action_requires_an_open_folder(qtbot, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window.commands.global_search_action.isEnabled()

    create_png(tmp_path / "sample.png")
    window.folders._load_directory(tmp_path, show_issues=False)

    assert window.commands.global_search_action.isEnabled()
