from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractScrollArea, QDialog, QLineEdit, QVBoxLayout
import pytest

from tagger.ai_tagging.dialog import AITaggingDialog
from tagger.deduplication import DuplicatePair, DuplicateScanResult
from tagger.domain.models import ImageEntry, TagOperation
from tagger.ui.dialogs.bulk_operation import BulkOperationDialog
from tagger.ui.dialogs.deduplicate import DeduplicateDialog
from tagger.ui.dialogs.delete_filter import DeleteFilterDialog
from tagger.ui.dialogs.review import ReviewDialog
from tagger.ui.dialogs.traversal import TraversalDialog
from tagger.ui.main_window.window import MainWindow

from .helpers import create_png


@pytest.fixture
def entries(tmp_path: Path) -> list[ImageEntry]:
    result = []
    for name in ("a", "b", "c"):
        image_path = tmp_path / f"{name}.png"
        tag_path = image_path.with_suffix(".txt")
        create_png(image_path)
        tag_path.write_bytes(b"cat\n")
        result.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))
    return result


@pytest.mark.parametrize(
    "kind", ["review", "traversal", "delete", "deduplicate", "ai", "bulk"]
)
def test_dialog_mouse_navigation_over_children_and_at_boundaries(
    qtbot, tmp_path: Path, entries, kind: str
) -> None:
    if kind == "review":
        dialog = ReviewDialog(entries)
        position = lambda dialog=dialog: dialog.session.current_index
        child = dialog.temporary_input
    elif kind == "traversal":
        dialog = TraversalDialog(entries, TagOperation.ADD, ["dog"])
        position = lambda dialog=dialog: dialog.session.current_index
        child = dialog.choices.viewport()
    elif kind == "delete":
        dialog = DeleteFilterDialog(entries)
        position = lambda dialog=dialog: dialog.current_index
        child = dialog.delete_checkbox
    elif kind == "deduplicate":
        dialog = DeduplicateDialog(entries, root_directory=tmp_path)
        paths = [entry.image_path for entry in entries]
        dialog._scan_completed(DuplicateScanResult([
            DuplicatePair(paths[0], paths[1], 0),
            DuplicatePair(paths[0], paths[2], 0),
            DuplicatePair(paths[1], paths[2], 0),
        ]))
        position = lambda dialog=dialog: dialog.current_index
        child = dialog.right_view.viewport()
    elif kind == "ai":
        dialog = AITaggingDialog(entries, root_directory=tmp_path)
        dialog._selected_entries = entries
        dialog._inference_completed({})
        position = lambda dialog=dialog: dialog._current_index
        child = dialog.ai_tags.viewport()
    else:
        dialog = BulkOperationDialog(entries, root_directory=tmp_path)
        dialog.code_input.setPlainText(
            "def process(fn: str, tags: set[str]) -> set[str]:\n"
            "    return tags | {'dog'}\n"
        )
        dialog._run_code()
        position = lambda dialog=dialog: dialog._current_index
        child = dialog.new_tags_input.viewport()

    qtbot.addWidget(dialog)
    if not isinstance(dialog, AITaggingDialog):
        dialog._allow_close = True
    dialog.show()
    qtbot.waitExposed(dialog)
    preview = dialog.left_view if isinstance(dialog, DeduplicateDialog) else dialog.image_view
    preview_target = preview.viewport() if isinstance(preview, QAbstractScrollArea) else preview
    for target in (dialog, preview_target, child):
        qtbot.mouseClick(target, Qt.MouseButton.BackButton)
        assert position() == 0
        qtbot.mouseClick(target, Qt.MouseButton.ForwardButton)
        assert position() == 1
        qtbot.mouseClick(target, Qt.MouseButton.ForwardButton)
        assert position() == 2
        qtbot.mouseClick(target, Qt.MouseButton.ForwardButton)
        assert position() == 2
        qtbot.mouseClick(target, Qt.MouseButton.BackButton)
        assert position() == 1
        qtbot.mouseClick(target, Qt.MouseButton.BackButton)
        assert position() == 0
    assert all(entry.tag_path.read_bytes() == b"cat\n" for entry in entries)


def test_main_window_mouse_navigation_and_dialog_isolation(
    qtbot, tmp_path: Path, entries
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)
    for target in (window, window.image_view.viewport(), window.image_list.viewport(), window.tag_input):
        qtbot.mouseClick(target, Qt.MouseButton.BackButton)
        assert window.image_list.currentIndex().row() == 0
        qtbot.mouseClick(target, Qt.MouseButton.ForwardButton)
        assert window.image_list.currentIndex().row() == 1
        qtbot.mouseClick(target, Qt.MouseButton.BackButton)
        assert window.image_list.currentIndex().row() == 0

    dialog = DeleteFilterDialog(entries, window)
    qtbot.addWidget(dialog)
    dialog._allow_close = True
    dialog.show()
    qtbot.mouseClick(dialog.image_view, Qt.MouseButton.ForwardButton)
    assert dialog.current_index == 1
    assert window.image_list.currentIndex().row() == 0
    dialog.close()

    modal = QDialog(window)
    qtbot.addWidget(modal)
    field = QLineEdit()
    QVBoxLayout(modal).addWidget(field)
    modal.setModal(True)
    modal.show()
    qtbot.waitExposed(modal)
    qtbot.mouseClick(field, Qt.MouseButton.ForwardButton)
    qtbot.mouseClick(window.tag_input, Qt.MouseButton.ForwardButton)
    assert window.image_list.currentIndex().row() == 0
    modal.close()
    qtbot.mouseClick(window.tag_input, Qt.MouseButton.ForwardButton)
    assert window.image_list.currentIndex().row() == 1


@pytest.mark.parametrize("kind", ["review", "traversal", "deduplicate", "ai"])
def test_setup_pages_do_not_navigate_hidden_review_controls(
    qtbot, tmp_path: Path, entries, kind: str
) -> None:
    if kind == "review":
        dialog = ReviewDialog(entries, root_directory=tmp_path)
    elif kind == "traversal":
        dialog = TraversalDialog(
            entries, TagOperation.ADD, ["dog"], root_directory=tmp_path
        )
    elif kind == "deduplicate":
        dialog = DeduplicateDialog(entries, root_directory=tmp_path)
    else:
        dialog = AITaggingDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    clicks = []
    dialog.next_button.clicked.connect(lambda: clicks.append("next"))
    dialog.back_button.clicked.connect(lambda: clicks.append("back"))
    qtbot.mouseClick(dialog.folder_tree.viewport(), Qt.MouseButton.ForwardButton)
    qtbot.mouseClick(dialog.folder_tree.viewport(), Qt.MouseButton.BackButton)
    assert clicks == []


def test_bulk_mouse_navigation_between_setup_pages(qtbot, tmp_path: Path, entries) -> None:
    dialog = BulkOperationDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)
    dialog._allow_close = True
    dialog.show()
    qtbot.mouseClick(dialog.folder_tree.viewport(), Qt.MouseButton.ForwardButton)
    assert dialog.pages.currentWidget() is dialog.code_page
    qtbot.mouseClick(dialog.code_input.viewport(), Qt.MouseButton.BackButton)
    assert dialog.pages.currentWidget() is dialog.selection_page
    qtbot.mouseClick(dialog.folder_tree.viewport(), Qt.MouseButton.ForwardButton)
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'dog'}\n"
    )
    qtbot.mouseClick(dialog.code_input.viewport(), Qt.MouseButton.ForwardButton)
    assert dialog.pages.currentWidget() is dialog.approval_page
    assert dialog._current_index == 0
    qtbot.mouseClick(dialog, Qt.MouseButton.BackButton)
    assert dialog.pages.currentWidget() is dialog.approval_page
    assert dialog._current_index == 0
