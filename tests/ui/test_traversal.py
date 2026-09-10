from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from tagger.domain.models import ImageEntry, TagOperation
from tagger.ui.dialogs.traversal import TraversalDialog

from .helpers import create_png


def test_traversal_does_not_write_until_finish(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    tag_path = tmp_path / "sample.txt"
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(
        image_path=tmp_path / "sample.png",
        tag_path=tag_path,
        tags=["cat"],
        source_bytes=b"cat\n",
    )
    dialog = TraversalDialog([entry], TagOperation.ADD, ["dog"])
    qtbot.addWidget(dialog)

    assert dialog.choices.item(0).checkState() == Qt.CheckState.Unchecked
    dialog.choices.item(0).setCheckState(Qt.CheckState.Checked)
    assert tag_path.read_bytes() == b"cat\n"
    assert dialog.finish_button.isEnabled()

    dialog._finish()
    assert tag_path.read_bytes() == b"cat, dog\n"


def test_toggle_traversal_checks_existing_tags_and_hides_apply_all(
    qtbot, tmp_path: Path
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat, bird\n")
    entry = ImageEntry(image_path, tag_path, ["cat", "bird"], b"cat, bird\n")

    dialog = TraversalDialog([entry], TagOperation.TOGGLE, ["cat", "dog"])
    qtbot.addWidget(dialog)

    checked = [
        dialog.choices.item(row).text()
        for row in range(dialog.choices.count())
        if dialog.choices.item(row).checkState() == Qt.CheckState.Checked
    ]
    assert checked == ["cat"]
    assert not dialog.apply_all_button.isVisible()
    assert not dialog.apply_all_button.isEnabled()


def test_traversal_apply_all_requires_confirmation_and_commits_all_options(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    entries: list[ImageEntry] = []
    for name, tags in {"first": "cat\n", "second": "bird\n"}.items():
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_bytes(tags.encode())
        entries.append(
            ImageEntry(
                image_path=image_path,
                tag_path=tag_path,
                tags=tags.strip().split(", "),
                source_bytes=tags.encode(),
            )
        )

    dialog = TraversalDialog(entries, TagOperation.ADD, ["dog", "night"])
    qtbot.addWidget(dialog)
    confirmations: list[str] = []

    def cancel(_parent, _title, message, *_args):
        confirmations.append(message)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    dialog.apply_all_button.click()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "cat\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "bird\n"
    assert "2 sidecar file(s) will change" in confirmations[0]

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    dialog.apply_all_button.click()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "cat, dog, night\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "bird, dog, night\n"
    )
    assert dialog.commit_result is not None
    assert dialog.commit_result.complete


def test_traversal_keyboard_navigation_selects_toggles_and_moves(qtbot, tmp_path: Path) -> None:
    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    create_png(first_image)
    create_png(second_image)
    first_tag = tmp_path / "first.txt"
    second_tag = tmp_path / "second.txt"
    first_tag.write_bytes(b"cat\n")
    second_tag.write_bytes(b"dog\n")
    entries = [
        ImageEntry(first_image, first_tag, ["cat"], b"cat\n"),
        ImageEntry(second_image, second_tag, ["dog"], b"dog\n"),
    ]
    dialog = TraversalDialog(entries, TagOperation.ADD, ["bird", "night"])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.choices.currentRow() == 0
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Down)
    assert dialog.choices.currentRow() == 1
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Up)
    assert dialog.choices.currentRow() == 0
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Down)
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Space)
    assert dialog.choices.item(1).checkState() == Qt.CheckState.Checked

    qtbot.keyClick(dialog.choices, Qt.Key.Key_Return)
    assert dialog.session.current_index == 1
    assert dialog.session.staged[0] == ("cat", "night")
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Left)
    assert dialog.session.current_index == 0
    assert dialog.choices.item(1).checkState() == Qt.CheckState.Checked
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Right)
    assert dialog.session.current_index == 1


def test_traversal_a_shortcut_toggles_all_options(qtbot, tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(image_path, tag_path, ["cat"], b"cat\n")
    dialog = TraversalDialog(
        entries=[entry],
        operation=TagOperation.ADD,
        requested_tags=["dog", "bird"],
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert [
        dialog.choices.item(row).checkState()
        for row in range(dialog.choices.count())
    ] == [Qt.CheckState.Unchecked, Qt.CheckState.Unchecked]
    qtbot.keyClick(dialog.choices, Qt.Key.Key_A)
    assert all(
        dialog.choices.item(row).checkState() == Qt.CheckState.Checked
        for row in range(dialog.choices.count())
    )
    qtbot.keyClick(dialog.choices, Qt.Key.Key_A)
    assert all(
        dialog.choices.item(row).checkState() == Qt.CheckState.Unchecked
        for row in range(dialog.choices.count())
    )


def test_traversal_temporary_input_is_consumed_or_cleared_on_navigation(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_bytes(b"cat\n")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))

    dialog = TraversalDialog(entries, TagOperation.ADD, ["base"])
    qtbot.addWidget(dialog)
    assert not dialog.temporary_input.isHidden()

    dialog.temporary_input.setText("temporary, image_only")
    assert dialog.temporary_add_button.isEnabled()
    assert dialog.result_tags.toPlainText() == "cat"
    dialog.temporary_add_button.click()
    assert dialog.temporary_input.text() == ""
    assert dialog.result_tags.toPlainText() == "cat, image_only, temporary"
    assert dialog.session.extra_tags_for() == ["temporary", "image_only"]
    dialog.choices.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.temporary_input.setText("discard_me")
    dialog._next()

    assert dialog.session.current_index == 1
    assert dialog.temporary_input.text() == ""
    assert dialog.session.staged[0] == (
        "base",
        "cat",
        "image_only",
        "temporary",
    )
    dialog._back()
    assert dialog.temporary_input.text() == ""
    assert dialog.choices.item(0).checkState() == Qt.CheckState.Checked
    assert dialog.session.extra_tags_for() == ["temporary", "image_only"]


def test_traversal_finish_early_commits_applied_and_skips_remaining(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second", "third"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_bytes(b"cat\n")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))

    dialog = TraversalDialog(entries, TagOperation.ADD, ["dog"])
    qtbot.addWidget(dialog)
    assert dialog.finish_button.isEnabled()
    assert dialog.next_button.text() == "Next"

    dialog.choices.item(0).setCheckState(Qt.CheckState.Checked)
    assert dialog.session.current_index == 0
    dialog._next()
    assert dialog.session.current_index == 1
    assert dialog.finish_button.isEnabled()
    dialog._finish()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "cat, dog\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "cat\n"
    assert (tmp_path / "third.txt").read_text(encoding="utf-8") == "cat\n"


def test_traversal_folder_tree_combines_checked_subtrees(
    qtbot, tmp_path: Path
) -> None:
    nested = tmp_path / "nested"
    deep = nested / "deep"
    other = tmp_path / "other"
    deep.mkdir(parents=True)
    other.mkdir()
    entries: list[ImageEntry] = []
    for image_path in [
        tmp_path / "root.png",
        nested / "child.png",
        deep / "grandchild.png",
        other / "other.png",
    ]:
        create_png(image_path)
        tag_path = image_path.with_suffix(".txt")
        tag_path.write_text("cat\n", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))

    dialog = TraversalDialog(
        entries,
        TagOperation.ADD,
        ["dog"],
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.folder_setup.isVisibleTo(dialog)
    assert not dialog.traversal_widget.isVisibleTo(dialog)
    assert dialog.tag_input.text() == "dog"
    assert dialog.focusWidget() is dialog.tag_input
    assert dialog.tag_input.selectedText() == "dog"
    root_item = dialog.folder_tree.topLevelItem(0)
    assert root_item is not None
    assert root_item.text(0) == tmp_path.name
    assert root_item.childCount() == 3
    nested_item = None
    for index in range(root_item.childCount()):
        child = root_item.child(index)
        if child is not None and child.text(0) == "nested":
            nested_item = child
            break
    assert nested_item is not None
    assert nested_item.childCount() == 2
    deep_item = nested_item.child(0)
    assert deep_item is not None
    assert deep_item.text(0) == "deep"
    child_image = nested_item.child(1)
    assert child_image is not None
    assert child_image.text(0) == "child.png"
    other_item = None
    for index in range(root_item.childCount()):
        child = root_item.child(index)
        if child is not None and child.text(0) == "other":
            other_item = child
            break
    assert other_item is not None

    assert root_item.checkState(0) == Qt.CheckState.Checked
    assert nested_item.checkState(0) == Qt.CheckState.Checked
    assert deep_item.checkState(0) == Qt.CheckState.Checked
    root_item.setCheckState(0, Qt.CheckState.Unchecked)
    nested_item.setCheckState(0, Qt.CheckState.Checked)
    assert deep_item.checkState(0) == Qt.CheckState.Checked
    assert child_image.checkState(0) == Qt.CheckState.Checked
    child_image.setCheckState(0, Qt.CheckState.Unchecked)
    assert dialog.folder_selection_label.text() == (
        "1 matching image(s) will be included."
    )
    child_image.setCheckState(0, Qt.CheckState.Checked)
    assert dialog.folder_selection_label.text() == (
        "2 matching image(s) will be included."
    )
    other_item.setCheckState(0, Qt.CheckState.Checked)
    assert root_item.checkState(0) == Qt.CheckState.PartiallyChecked
    assert dialog.folder_selection_label.text() == (
        "3 matching image(s) will be included."
    )
    dialog.start_button.click()

    assert dialog._started
    assert not dialog.folder_setup.isVisibleTo(dialog)
    assert dialog.traversal_widget.isVisibleTo(dialog)
    assert [item.image_path for item in dialog.session.items] == [
        nested / "child.png",
        deep / "grandchild.png",
        other / "other.png",
    ]
