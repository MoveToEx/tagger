from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from tagger.ui.dialogs.bulk_operation import BulkOperationDialog
from tagger.ui.main_window.window import MainWindow

from .helpers import create_png


def test_bulk_operation_folder_selection_cascades(qtbot, tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    create_png(tmp_path / "root.png")
    create_png(nested / "child.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)

    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    assert dialog.pages.count() == 3
    assert dialog.pages.currentWidget() is dialog.selection_page
    assert dialog.code_input.tabStopDistance() == (
        dialog.code_input.fontMetrics().horizontalAdvance(" ") * 4
    )
    root_item = dialog.folder_tree.topLevelItem(0)
    assert root_item is not None
    assert len(dialog._checked_entries()) == 2

    nested_item = next(
        root_item.child(index)
        for index in range(root_item.childCount())
        if root_item.child(index).text(0) == "nested"
    )
    nested_item.setCheckState(0, Qt.CheckState.Unchecked)

    assert [entry.image_path.name for entry in dialog._checked_entries()] == [
        "root.png"
    ]
    assert root_item.checkState(0) == Qt.CheckState.PartiallyChecked
    assert dialog.folder_selection_label.text() == "1 image(s) selected."


def test_bulk_operation_runs_code_and_skips_unchanged_images(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {"cat.png": "cat\n", "dog.png": "dog\n"}.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)

    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'new'} if fn == 'cat.png' else tags\n"
    )
    dialog._run_code()

    assert dialog.pages.currentWidget() is dialog.approval_page
    assert len(dialog._changes) == 1
    assert dialog.current_change.entry.image_path.name == "cat.png"
    assert dialog.original_tags_input.toPlainText() == "cat"
    assert dialog.new_tags_input.toPlainText() == "cat, new"
    assert dialog.original_tags_input.maximumHeight() == 100
    assert dialog.new_tags_input.maximumHeight() == 100
    assert dialog.changes_text.toPlainText() == "[+] new"
    assert dialog.apply_change_checkbox.text() == "Apply change"
    assert dialog.apply_change_checkbox.isChecked()
    assert dialog.apply_change_checkbox.styleSheet() == (
        "QCheckBox::indicator { width: 12px; height: 12px; }"
    )
    assert dialog.discard_button.text() == "Back"
    assert dialog.apply_all_button.text() == "Apply All"
    assert dialog.previous_button.text() == "Previous"
    assert dialog.next_button.text() == "Next"
    assert not dialog.previous_button.isEnabled()
    assert not dialog.next_button.isEnabled()


def test_bulk_operation_reports_invalid_process_return(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return ['not', 'a', 'set']\n"
    )

    dialog._run_code()

    assert dialog.pages.currentWidget() is dialog.code_page
    assert dialog.code_error_label.isVisibleTo(dialog)
    assert "must return set[str]" in dialog.code_error_label.text()


def test_bulk_operation_updates_decisions_while_navigation_only_moves(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {"first.png": "cat\n", "second.png": "dog\n"}.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'processed'}\n"
    )
    dialog._run_code()
    dialog.new_tags_input.setPlainText("cat, edited")
    dialog.apply_change_checkbox.setChecked(False)

    assert not dialog._decisions[0].apply_change
    assert dialog._decisions[0].result_tags == ("cat", "edited")
    dialog.next_button.click()
    assert dialog.current_change.entry.image_path.name == "second.png"
    assert dialog.previous_button.isEnabled()
    assert not dialog.next_button.isEnabled()
    assert dialog.result() == 0
    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "cat\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "dog\n"

    dialog.previous_button.click()

    assert dialog.current_change.entry.image_path.name == "first.png"
    assert dialog.new_tags_input.toPlainText() == "cat, edited"
    assert not dialog.apply_change_checkbox.isChecked()
    assert not dialog.previous_button.isEnabled()
    assert dialog.next_button.isEnabled()


def test_bulk_operation_apply_all_ignores_apply_decisions(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {"first.png": "cat\n", "second.png": "dog\n"}.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'processed'}\n"
    )
    dialog._run_code()
    dialog.new_tags_input.setPlainText("cat, edited")
    dialog.apply_change_checkbox.setChecked(False)
    dialog.next_button.click()
    dialog.apply_change_checkbox.setChecked(False)

    dialog.apply_all_button.click()

    assert dialog.result() == BulkOperationDialog.DialogCode.Accepted
    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "cat, edited\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "dog, processed\n"
    )


def test_bulk_operation_discard_returns_to_code_without_writing(
    qtbot, tmp_path: Path
) -> None:
    for name in ["first", "second"]:
        create_png(tmp_path / f"{name}.png")
        (tmp_path / f"{name}.txt").write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'processed'}\n"
    )
    dialog._run_code()
    assert dialog._decisions

    dialog.discard_button.click()

    assert dialog.pages.currentWidget() is dialog.code_page
    assert not dialog._decisions
    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "cat\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "cat\n"
