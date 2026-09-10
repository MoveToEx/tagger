from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QWidget

from tagger.tag_library.completion import attach_tag_completer
from tagger.tag_library.format import write_tag_library
from tagger.tag_library.library import TagLibrary


def test_tag_autocomplete_double_click_inserts_tag(qtbot, tmp_path: Path) -> None:
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("red_hair", 100), ("blue_eyes", 80)])
    library = TagLibrary(library_path)
    host = QWidget()
    line_edit = QLineEdit(host)
    line_edit.resize(240, 28)
    host.resize(240, 28)
    qtbot.addWidget(host)
    completer = attach_tag_completer(line_edit, library)
    assert completer is not None

    host.show()
    line_edit.setFocus()
    line_edit.setText("red")
    qtbot.waitUntil(lambda: completer.popup().isVisible())

    index = completer.popup().model().index(0, 0)
    qtbot.mouseDClick(
        completer.popup().viewport(),
        Qt.MouseButton.LeftButton,
        pos=completer.popup().visualRect(index).center(),
    )

    assert line_edit.text() == "red_hair"
    qtbot.wait(100)
    assert not completer.popup().isVisible()


def test_tag_autocomplete_single_click_keeps_popup_visible(
    qtbot, tmp_path: Path
) -> None:
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("red_hair", 100), ("blue_eyes", 80)])
    library = TagLibrary(library_path)
    host = QWidget()
    line_edit = QLineEdit(host)
    line_edit.resize(240, 28)
    host.resize(240, 28)
    qtbot.addWidget(host)
    completer = attach_tag_completer(line_edit, library)
    assert completer is not None

    host.show()
    line_edit.setFocus()
    line_edit.setText("red")
    qtbot.waitUntil(lambda: completer.popup().isVisible())

    index = completer.popup().model().index(0, 0)
    qtbot.mouseClick(
        completer.popup().viewport(),
        Qt.MouseButton.LeftButton,
        pos=completer.popup().visualRect(index).center(),
    )

    assert line_edit.text() == "red"
    assert completer.popup().isVisible()
    assert completer.popup().currentIndex() == index
