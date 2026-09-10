from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QGroupBox, QLabel, QMenu, QMessageBox

from tagger.domain.models import ImageEntry
from tagger.settings.preferences import (
    IMAGE_PREFETCH_COUNT_SETTING,
    USE_UNLINK_FOR_DELETE_FILTER_SETTING,
)
from tagger.trash import UNLINK
from tagger.ui.dialogs.delete_filter import (
    DeleteFilterDialog,
    DeleteFilterProgressDialog,
)
import tagger.ui.main_window.dialogs as window_dialogs
from tagger.ui.main_window.window import MainWindow
from tagger.ui.preview.view import ImageView

from .helpers import create_png


def test_image_menu_exposes_delete_filter_for_open_folder(
    qtbot, tmp_path: Path
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    image_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&Image"
    )
    assert image_menu.actions() == [window.commands.delete_filter_action, window.commands.deduplicate_action]
    assert window.commands.delete_filter_action.text() == "Delete Filter..."
    assert not window.commands.delete_filter_action.isEnabled()

    create_png(tmp_path / "sample.png")
    window.folders._load_directory(tmp_path, show_issues=False)

    assert window.commands.delete_filter_action.isEnabled()


def test_delete_filter_uses_configured_deletion_behavior(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.settings.setValue(
        USE_UNLINK_FOR_DELETE_FILTER_SETTING, True
    )
    window.settings.setValue(IMAGE_PREFETCH_COUNT_SETTING, 4)
    window.folders._load_directory(tmp_path, show_issues=False)
    captured_deleters: list[Callable[[Path], bool]] = []
    captured_behaviors: list[str] = []
    captured_prefetch_counts: list[int] = []

    class FakeDeleteFilterDialog:
        class DialogCode:
            Accepted = 1

        commit_result = None

        def __init__(
            self,
            _entries,
            _parent,
            *,
            file_deleter,
            deletion_behavior: str,
            image_prefetch_count: int,
        ) -> None:
            captured_deleters.append(file_deleter)
            captured_behaviors.append(deletion_behavior)
            captured_prefetch_counts.append(image_prefetch_count)

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(
        window_dialogs, "DeleteFilterDialog", FakeDeleteFilterDialog
    )
    window.dialogs._open_delete_filter()

    assert captured_behaviors == [UNLINK]
    assert captured_prefetch_counts == [4]
    delete_candidate = tmp_path / "delete-me.txt"
    delete_candidate.write_text("content", encoding="utf-8")
    assert captured_deleters[0](delete_candidate)
    assert not delete_candidate.exists()


def test_delete_filter_shortcuts_toggle_and_navigate(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second", "third"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_text("cat\n", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))
    dialog = DeleteFilterDialog(entries)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.current_index == 0
    assert not dialog.delete_checkbox.isChecked()
    assert dialog.findChildren(QGroupBox) == []
    assert dialog.delete_checkbox.styleSheet() == (
        "QCheckBox::indicator { width: 12px; height: 12px; }"
    )
    checkbox_position = dialog.delete_checkbox.mapTo(dialog, QPoint())
    cancel_position = dialog.cancel_button.mapTo(dialog, QPoint())
    back_position = dialog.back_button.mapTo(dialog, QPoint())
    next_position = dialog.next_button.mapTo(dialog, QPoint())
    finish_position = dialog.finish_button.mapTo(dialog, QPoint())
    assert checkbox_position.y() < back_position.y()
    assert cancel_position.x() < back_position.x()
    assert back_position.x() < next_position.x() < finish_position.x()
    assert cancel_position.y() == back_position.y()
    qtbot.keyClick(dialog, Qt.Key.Key_Space)
    assert dialog.delete_checkbox.isChecked()
    assert dialog.marked_for_deletion == {tmp_path / "first.png"}

    qtbot.keyClick(dialog, Qt.Key.Key_Right)
    assert dialog.current_index == 1
    assert not dialog.delete_checkbox.isChecked()
    qtbot.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.current_index == 2
    qtbot.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.current_index == 1
    dialog._back()
    assert dialog.current_index == 0
    assert dialog.delete_checkbox.isChecked()
    assert "Marked for deletion 1" in dialog.progress_label.text()


def test_delete_filter_uses_simple_fitted_image_click_decisions(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second", "third"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_text("cat\n", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))
    dialog = DeleteFilterDialog(entries)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    qtbot.waitUntil(
        lambda: dialog.image_view.pixmap() is not None
        and not dialog.image_view.pixmap().isNull()
    )

    assert isinstance(dialog.image_view, QLabel)
    assert not isinstance(dialog.image_view, ImageView)
    assert not hasattr(dialog.image_view, "zoom_in")
    assert not hasattr(dialog.image_view, "horizontalScrollBar")
    displayed = dialog.image_view.pixmap()
    assert displayed is not None
    assert displayed.width() <= dialog.image_view.contentsRect().width()
    assert displayed.height() <= dialog.image_view.contentsRect().height()
    dialog._toggle_current()
    qtbot.mouseClick(
        dialog.image_view,
        Qt.MouseButton.LeftButton,
    )

    assert dialog.current_index == 1
    assert tmp_path / "first.png" not in dialog.marked_for_deletion
    qtbot.waitUntil(
        lambda: dialog.image_view.pixmap() is not None
        and not dialog.image_view.pixmap().isNull()
    )
    qtbot.mouseClick(
        dialog.image_view,
        Qt.MouseButton.RightButton,
    )

    assert dialog.current_index == 2
    assert dialog.marked_for_deletion == {tmp_path / "second.png"}
    qtbot.waitUntil(
        lambda: dialog.image_view.pixmap() is not None
        and not dialog.image_view.pixmap().isNull()
    )
    qtbot.mouseClick(
        dialog.image_view,
        Qt.MouseButton.RightButton,
    )

    assert dialog.current_index == 2
    assert dialog.delete_checkbox.isChecked()
    assert dialog.marked_for_deletion == {
        tmp_path / "second.png",
        tmp_path / "third.png",
    }


def test_delete_filter_finishes_early_and_keeps_unreviewed_images(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second", "third"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_text("cat\n", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))
    moved: list[Path] = []

    def fake_move_to_trash(path: Path) -> bool:
        moved.append(path)
        path.unlink()
        return True

    dialog = DeleteFilterDialog(entries, file_deleter=fake_move_to_trash)
    qtbot.addWidget(dialog)
    dialog._toggle_current()
    prompts: list[tuple[str, str]] = []
    answers = iter(
        [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes]
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message, *_args: (
            prompts.append((title, message)) or next(answers)
        ),
    )

    dialog._finish()
    assert moved == []
    assert dialog.commit_result is None
    assert all(
        path.exists()
        for entry in entries
        for path in (entry.image_path, entry.tag_path)
    )
    dialog._finish()

    assert prompts == [
        (
            "Delete Marked Images?",
            "Move 1 marked image(s) and their tag files "
            "to the system Recycle Bin?",
        ),
        (
            "Delete Marked Images?",
            "Move 1 marked image(s) and their tag files "
            "to the system Recycle Bin?",
        ),
    ]
    assert moved == [tmp_path / "first.png", tmp_path / "first.txt"]
    assert dialog.result() == DeleteFilterDialog.DialogCode.Accepted
    assert dialog.commit_result is not None
    assert dialog.commit_result.complete
    assert dialog.commit_result.deleted_images == [tmp_path / "first.png"]
    for name in ["second", "third"]:
        assert (tmp_path / f"{name}.png").exists()
        assert (tmp_path / f"{name}.txt").exists()


def test_delete_filter_progress_dialog_updates_while_deleting(
    qtbot, tmp_path: Path
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    entry = ImageEntry(image_path, tag_path, ["cat"], b"cat\n")
    release_worker = threading.Event()

    def fake_move_to_trash(path: Path) -> bool:
        if path == image_path:
            release_worker.wait(timeout=5)
        path.unlink()
        return True

    dialog = DeleteFilterProgressDialog(
        [entry], fake_move_to_trash, lambda: True
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.start()
    try:
        qtbot.waitUntil(
            lambda: dialog.current_file_label.text()
            == "Moving to Recycle Bin: sample.png"
        )
        assert dialog.isVisible()
        assert dialog.progress_bar.value() == 0
        assert dialog.progress_bar.maximum() == 2
        dialog.reject()
        assert dialog.isVisible()
    finally:
        release_worker.set()

    qtbot.waitUntil(lambda: not dialog._running)
    assert dialog.commit_result is not None
    assert dialog.commit_result.complete
    assert dialog.commit_result.deleted_images == [image_path]
    assert dialog.commit_result.deleted_files == [image_path, tag_path]
    assert dialog.progress_bar.value() == 2


def test_delete_filter_unlink_confirmation_warns_deletion_is_permanent(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    dialog = DeleteFilterDialog(
        [ImageEntry(image_path, tag_path, ["cat"], b"cat\n")],
        file_deleter=lambda _path: True,
        deletion_behavior=UNLINK,
    )
    qtbot.addWidget(dialog)
    dialog._toggle_current()
    prompts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message, *_args: (
            prompts.append((title, message))
            or QMessageBox.StandardButton.Cancel
        ),
    )

    dialog._finish()

    assert prompts == [
        (
            "Permanently Delete Marked Images?",
            "Permanently delete 1 marked image(s) and their tag files?\n\n"
            "This cannot be undone.",
        )
    ]
    assert dialog.commit_result is None
    assert image_path.exists()
    assert tag_path.exists()


def test_delete_filter_cancel_confirms_staged_changes(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    dialog = DeleteFilterDialog(
        [ImageEntry(image_path, tag_path, ["cat"], b"cat\n")],
        file_deleter=lambda _path: False,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._toggle_current()
    answers = iter(
        [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard]
    )
    prompts: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, _title, message, *_args: (
            prompts.append(message) or next(answers)
        ),
    )

    dialog.reject()
    assert dialog.isVisible()
    dialog.reject()

    assert len(prompts) == 2
    assert all("uncommitted changes" in message for message in prompts)
    assert dialog.result() == DeleteFilterDialog.DialogCode.Rejected
    assert image_path.exists()
    assert tag_path.exists()
