from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMenu, QMessageBox
import pytest

from tagger.domain.models import TagOperation
from tagger.settings.preferences import PARENTHESES_SETTING, UNDERSCORES_SETTING
from tagger.settings.store import JsonSettings
from tagger.tag_library.format import write_tag_library
from tagger.tag_library.library import TagLibrary
from tagger.ui.dialogs.global_search import GlobalTagSearchDialog
from tagger.ui.dialogs.traversal import TraversalDialog
from tagger.ui.main_window.window import MainWindow
import tagger.ui.main_window.window as main_window_module

from .helpers import create_png


def test_main_window_loads_folder_and_edits_current_tags(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog, cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)

    window.folders._load_directory(tmp_path, show_issues=False)

    assert window.catalog.rowCount() == 1
    assert window.add_tag_button.text() == "+"
    assert window.add_tag_button.width() == 34
    assert window.image_list.currentIndex().row() == 0
    assert [window.tag_list.item(i).text() for i in range(window.tag_list.count())] == [
        "dog",
        "cat",
    ]
    assert window.windowTitle() == f"{tmp_path.name} - Image Tagger"
    assert window.commands.bulk_operation_action.isEnabled()

    qtbot.waitUntil(lambda: "32 × 24 px" in window.image_info_label.text())
    image_info = window.image_info_label.text()
    assert "sample.png" not in image_info
    assert "PNG" in image_info
    assert image_info.endswith(" B")

    window.tag_input.setText("bird")
    window.tags._add_current_tags()
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == (
        "bird, cat, dog\n"
    )


def test_main_window_uses_saved_tag_transformations_before_settings_open(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(UNDERSCORES_SETTING, True)
    settings.setValue(PARENTHESES_SETTING, True)
    settings.sync()
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("red_hair_(long)", 100)])

    def create_library(*, parent=None, **options):
        return TagLibrary(library_path, parent=parent, **options)

    monkeypatch.setattr(main_window_module, "create_app_settings", lambda: settings)
    monkeypatch.setattr(main_window_module, "TagLibrary", create_library)

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.tag_library.suggestions("red") == [r"red hair \(long\)"]


def test_toolbar_tag_search_cycles_and_supports_wildcards(qtbot, tmp_path: Path) -> None:
    for name, tags in {
        "a.png": "cat\n",
        "b.png": "dog\n",
        "c.png": "cat, night_scene\n",
    }.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    window.search_input.setText("cat")
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 2
    assert [item.text() for item in window.tag_list.selectedItems()] == ["cat"]
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 0
    assert [item.text() for item in window.tag_list.selectedItems()] == ["cat"]

    window.search_input.setText("night*")
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 2
    assert [item.text() for item in window.tag_list.selectedItems()] == [
        "night_scene"
    ]


def test_toolbar_tag_search_enter_accepts_active_completion(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog\n", encoding="utf-8")
    library_path = tmp_path / "data" / "tag-lib" / "danbooru_tags.bin"
    write_tag_library(library_path, [("red", 100)])

    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    window.search_input.setFocus()
    window.search_input.setText("red")
    completer = window.search_completer
    assert completer is not None
    qtbot.waitUntil(lambda: completer.popup().isVisible())
    first_index = completer.popup().model().index(0, 0)
    completion = str(first_index.data())

    qtbot.keyClick(window.search_input, Qt.Key.Key_Down)
    assert completer.popup().currentIndex().isValid()

    searches: list[int] = []
    monkeypatch.setattr(
        window, "_find_tag", lambda direction=1: searches.append(direction)
    )
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)

    assert searches == []
    assert window.search_input.text() == completion


def test_toolbar_tag_search_finds_remaining_matches_in_current_file(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {
        "a.png": "\n",
        "b.png": "match_one, match_two\n",
        "c.png": "match_three\n",
    }.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    window.search_input.setText("match_*")
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 1
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_one"]

    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 1
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_two"]

    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 2
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_three"]


def test_toolbar_tag_search_moves_backwards_with_shift_enter(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {
        "a.png": "match_one\n",
        "b.png": "match_two, match_three\n",
        "c.png": "match_four\n",
    }.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)
    window.search_input.setText("match_*")

    qtbot.keyClick(
        window.search_input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.image_list.currentIndex().row() == 2
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_four"]

    qtbot.keyClick(
        window.search_input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.image_list.currentIndex().row() == 1
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_three"]

    qtbot.keyClick(
        window.search_input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.image_list.currentIndex().row() == 1
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_two"]


def test_normalize_applies_to_all_images_after_confirmation(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    for name, tags in {
        "first": "zebra, apple\n",
        "second": "night, bird\n",
    }.items():
        create_png(tmp_path / f"{name}.png")
        (tmp_path / f"{name}.txt").write_text(
            tags, encoding="utf-8", newline="\n"
        )

    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window._select_row(1)
    assert TagOperation.NORMALIZE not in window.commands.folder_tag_actions
    assert window.commands.normalize_action.isEnabled()
    confirmations: list[str] = []

    def cancel(_parent, _title, message, *_args):
        confirmations.append(message)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    window.commands.normalize_action.trigger()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "zebra, apple\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "night, bird\n"
    )
    assert "all 2 editable image(s)" in confirmations[0]
    assert "2 sidecar file(s) will change" in confirmations[0]

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    window.commands.normalize_action.trigger()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "apple, zebra\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "bird, night\n"
    )
    assert window.image_list.currentIndex().row() == 1
    assert window.statusBar().currentMessage() == "Normalized tags in 2 file(s)."


def test_tag_context_copy_uses_comma_space_separator(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog, cat, bird\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)

    window.tag_list.item(0).setSelected(True)
    window.tag_list.item(2).setSelected(True)
    assert window.tag_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    window.tags._copy_selected_tags()

    assert QGuiApplication.clipboard().text() == "dog, bird"


@pytest.mark.parametrize(
    ("label", "operation"),
    [
        ("Add tags", TagOperation.ADD),
        ("Delete tags", TagOperation.DELETE),
        ("Toggle tags", TagOperation.TOGGLE),
    ],
)
@pytest.mark.parametrize("selected_rows", [(1,), (2, 0)])
def test_tag_context_send_to_prefills_traversal(
    qtbot, tmp_path: Path, monkeypatch, label, operation, selected_rows
) -> None:
    create_png(tmp_path / "sample.png")
    tag_path = tmp_path / "sample.txt"
    tag_path.write_text("dog, cat, blue sky\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.tag_list.clearSelection()
    for row in selected_rows:
        window.tag_list.item(row).setSelected(True)
    opened: list[tuple[TagOperation, str]] = []

    def inspect_dialog(dialog):
        qtbot.addWidget(dialog)
        opened.append((dialog._operation, dialog.tag_input.text()))
        assert not dialog._started
        return TraversalDialog.DialogCode.Rejected

    monkeypatch.setattr(TraversalDialog, "exec", inspect_dialog)
    menu = window.tags._create_tag_context_menu()
    assert menu.actions()[-2].isSeparator()
    send_to = menu.actions()[-1].menu()
    assert isinstance(send_to, QMenu)
    assert send_to.title() == "Send to"
    assert [action.text() for action in send_to.actions()] == [
        "Add tags", "Delete tags", "Toggle tags", "Global search"
    ]
    next(action for action in send_to.actions() if action.text() == label).trigger()

    expected_tags = ", ".join(
        window.tag_list.item(row).text() for row in sorted(selected_rows)
    )
    assert opened == [(operation, expected_tags)]
    assert tag_path.read_text(encoding="utf-8") == "dog, cat, blue sky\n"


@pytest.mark.parametrize("selected_rows", [(), (2,), (0, 2)])
def test_tag_context_send_to_global_search_requires_one_tag(
    qtbot, tmp_path: Path, monkeypatch, selected_rows
) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog, cat, blue sky\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.tag_list.clearSelection()
    for row in selected_rows:
        window.tag_list.item(row).setSelected(True)
    opened: list[str] = []

    def inspect_dialog(dialog):
        qtbot.addWidget(dialog)
        opened.append(dialog.pattern_input.text())
        return GlobalTagSearchDialog.DialogCode.Rejected

    monkeypatch.setattr(GlobalTagSearchDialog, "exec", inspect_dialog)
    send_to = window.tags._create_tag_context_menu().actions()[-1].menu()
    assert isinstance(send_to, QMenu)
    assert send_to.isEnabled() == bool(selected_rows)
    search_action = send_to.actions()[-1]
    assert search_action.isEnabled() == (len(selected_rows) == 1)
    search_action.trigger()
    assert opened == (["blue sky"] if len(selected_rows) == 1 else [])

    window.commands.global_search_action.trigger()
    assert opened[-1] == ""


def test_main_tag_deletion_requires_confirmation_from_button_and_context_menu(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    tag_path = tmp_path / "sample.txt"
    tag_path.write_text("dog, cat, bird\n", encoding="utf-8", newline="\n")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)

    window.tag_list.item(0).setSelected(True)
    window.tag_list.item(2).setSelected(True)
    confirmations: list[tuple[str, str]] = []
    answers = iter(
        [
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        ]
    )

    def confirm(_parent, title, message, *_args):
        confirmations.append((title, message))
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", confirm)

    window.delete_tag_button.click()
    assert tag_path.read_text(encoding="utf-8") == "dog, cat, bird\n"

    context_menu = window.tags._create_tag_context_menu()
    assert context_menu.actions()[1].text() == "Delete"
    context_menu.actions()[1].trigger()

    assert tag_path.read_text(encoding="utf-8") == "cat\n"
    assert len(confirmations) == 2
    assert all(title == "Delete Selected Tags?" for title, _ in confirmations)
    assert all("2 selected tag(s)" in message for _, message in confirmations)
    assert all("dog, bird" in message for _, message in confirmations)
    assert [item.text() for item in window.tag_list.selectedItems()] == []
