from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.transparency import TransparencySelectionDialog


def _entries(root: Path) -> list[ImageEntry]:
    entries = []
    for name in ("root.png", "nested/child.png", "nested/second.png"):
        image_path = root / name
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (16, 16), (10, 20, 30, 100)).save(image_path)
        tag_path = image_path.with_suffix(".txt")
        tag_path.write_text("", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, [], b""))
    return entries


def test_transparency_picker_cascades_and_disables_empty_selection(
    qtbot, tmp_path: Path
) -> None:
    entries = _entries(tmp_path)
    dialog = TransparencySelectionDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)

    root = dialog.folder_tree.topLevelItem(0)
    assert root is not None
    assert {
        entry.image_path for entry in dialog._checked_entries()
    } == {entry.image_path for entry in entries}
    nested = next(
        root.child(index)
        for index in range(root.childCount())
        if root.child(index) is not None
        and root.child(index).text(0) == "nested"
    )
    assert nested.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert nested.checkState(0) == Qt.CheckState.Checked
    assert dialog.selection_label.text() == "3 image(s) selected."
    assert dialog.remove_button.isEnabled()

    root.setCheckState(0, Qt.CheckState.Unchecked)
    assert dialog._checked_entries() == []
    assert not dialog.remove_button.isEnabled()

    nested.setCheckState(0, Qt.CheckState.Checked)
    assert dialog._checked_entries() == entries[1:]
    assert root.checkState(0) == Qt.CheckState.PartiallyChecked
    assert dialog.remove_button.isEnabled()


def test_transparency_picker_honors_initial_paths(qtbot, tmp_path: Path) -> None:
    entries = _entries(tmp_path)
    dialog = TransparencySelectionDialog(
        entries,
        root_directory=tmp_path,
        initial_paths=[entries[1].image_path],
    )
    qtbot.addWidget(dialog)

    assert dialog.selected_paths == [entries[1].image_path]
    assert dialog.selection_label.text() == "1 image(s) selected."
    assert dialog.remove_button.isEnabled()
