from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QMessageBox

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.review import ReviewDialog

from .helpers import assert_stable_widget_size, create_png


def test_review_keyboard_shortcuts_keep_delete_and_navigate(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name, tags in {"first": ["cat", "dog"], "second": ["bird"]}.items():
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        source = (", ".join(tags) + "\n").encode()
        tag_path.write_bytes(source)
        entries.append(ImageEntry(image_path, tag_path, tags, source))

    dialog = ReviewDialog(entries)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.right_splitter.orientation() == Qt.Orientation.Vertical
    assert dialog.right_splitter.widget(0) is dialog.tag_panel
    assert dialog.right_splitter.widget(1) is dialog.controls_panel
    assert dialog.tag_label.minimumHeight() == dialog.tag_label.maximumHeight()
    assert dialog.tag_label.height() >= dialog.tag_label.fontMetrics().lineSpacing() * 3
    assert dialog.tag_status_list.minimumHeight() == 150
    assert dialog.tag_status_list.maximumHeight() == 150
    decision_group = dialog.keep_button.parentWidget()
    navigation_group = dialog.back_button.parentWidget()
    session_group = dialog.finish_button.parentWidget()
    assert isinstance(decision_group, QGroupBox)
    assert isinstance(navigation_group, QGroupBox)
    assert isinstance(session_group, QGroupBox)
    assert decision_group.title() == "Tag decision"
    assert navigation_group.title() == "Navigation"
    assert session_group.title() == "Review session"
    assert dialog.session.current_tag == "cat"
    assert [dialog.tag_status_list.item(row).text() for row in range(dialog.tag_status_list.count())] == [
        "[pending] cat",
        "[pending] dog",
    ]
    assert "#b42318" in dialog.delete_button.styleSheet()
    assert "Reviewed tags 0 of 3" in dialog.progress_label.text()
    qtbot.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.session.current_tag == "dog"
    assert [dialog.tag_status_list.item(row).text() for row in range(dialog.tag_status_list.count())] == [
        "[kept] cat",
        "[pending] dog",
    ]
    assert "Reviewed tags 1 of 3" in dialog.progress_label.text()
    qtbot.keyClick(dialog, Qt.Key.Key_Space)
    assert dialog.session.current_index == 1
    assert dialog.session.current_tag == "bird"
    qtbot.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.session.current_index == 0
    assert dialog.session.current_tag == "dog"
    qtbot.keyClick(dialog, Qt.Key.Key_Right)
    assert dialog.session.current_index == 1
    assert dialog.session.current_tag == "bird"
    assert dialog.session.working_tags[0] == ["cat"]


def test_review_extra_tag_input_accepts_spaces(qtbot, tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat\n")
    dialog = ReviewDialog(
        [ImageEntry(image_path, tag_path, ["cat"], b"cat\n")]
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.temporary_input.setFocus()

    assert_stable_widget_size(dialog.temporary_input, minimum_width=256)

    qtbot.keyClicks(dialog.temporary_input, "two words")

    assert dialog.temporary_input.text() == "two words"
    assert dialog.session.current_tags == ["cat"]


def test_review_discard_button_closes_without_writing(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(image_path, tag_path, ["cat"], b"cat\n")
    dialog = ReviewDialog([entry])
    qtbot.addWidget(dialog)

    dialog._delete()
    assert dialog.session.has_changes
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Discard,
    )
    dialog.discard_button.click()

    assert dialog.result() == ReviewDialog.DialogCode.Rejected
    assert tag_path.read_bytes() == b"cat\n"


def test_review_temporary_tags_are_kept_and_consumed(
    qtbot, tmp_path: Path
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(image_path, tag_path, ["cat"], b"cat\n")
    dialog = ReviewDialog([entry])
    qtbot.addWidget(dialog)

    dialog.temporary_input.setText("new, cat")
    assert dialog.temporary_add_button.isEnabled()
    dialog.temporary_add_button.click()

    assert dialog.temporary_input.text() == ""
    assert dialog.session.current_tags == ["cat", "new"]
    assert "new" in dialog.session.reviewed_tags[0]
    assert "[kept] new" in [
        dialog.tag_status_list.item(row).text()
        for row in range(dialog.tag_status_list.count())
    ]
    assert tag_path.read_bytes() == b"cat\n"


def test_review_finish_confirms_total_tag_deletions(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat, dog\n")
    entry = ImageEntry(image_path, tag_path, ["cat", "dog"], b"cat, dog\n")
    dialog = ReviewDialog([entry])
    qtbot.addWidget(dialog)
    dialog._delete()

    prompts: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, _title, message, *_args: (
            prompts.append(message) or QMessageBox.StandardButton.Cancel
        ),
    )
    dialog._finish()

    assert "delete 1 tag(s)" in prompts[0]
    assert tag_path.read_bytes() == b"cat, dog\n"
