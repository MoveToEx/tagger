from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu
import pytest
import shiboken6

from tagger.frame_extraction import ExtractionResult
from tagger.ui.dialogs.frame_extraction import (
    FrameExtractionDialog, FrameExtractionProgressDialog, FrameExtractionVideoDialog,
)
import tagger.ui.dialogs.frame_extraction as frame_dialog_module
from tagger.ui.main_window.window import MainWindow
import tagger.ui.main_window.dialogs as controller_module

from .helpers import assert_stable_widget_size


def _open_video(qtbot, tmp_path: Path, video_file: Path) -> FrameExtractionDialog:
    dialog = FrameExtractionDialog(video_file, tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._ready)
    return dialog


def _wait_for_frame(qtbot, dialog: FrameExtractionDialog, index: int) -> None:
    qtbot.waitUntil(lambda: dialog.current_frame == index and dialog._ready)


def test_tools_menu_available_for_empty_open_folder(qtbot, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    menu = next(menu for menu in window.menuBar().findChildren(QMenu) if menu.title() == "&Tools")
    assert menu.actions() == [window.commands.frame_extraction_action]
    assert window.commands.frame_extraction_action.text() == "Frame Extraction..."
    assert not window.commands.frame_extraction_action.isEnabled()
    window.folders._load_directory(tmp_path, show_issues=False)
    assert window.commands.frame_extraction_action.isEnabled()
    window.folders.close_folder()
    assert not window.commands.frame_extraction_action.isEnabled()


def test_file_stage_is_compact_and_closes_after_video_validation(
    qtbot, tmp_path: Path, video_file: Path, monkeypatch,
) -> None:
    dialog = FrameExtractionVideoDialog(tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.height() < 220
    assert dialog.size() == dialog.sizeHint()
    assert_stable_widget_size(dialog.file_input, minimum_width=420)
    def browse(parent, title, directory, file_filter):
        assert directory == str(tmp_path)
        return str(video_file), ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", browse)
    dialog.browse_button.click()
    assert dialog.file_input.text() == str(video_file)
    dialog.next_button.click()
    qtbot.waitUntil(lambda: not dialog.isVisible())
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.video_path == video_file
    assert dialog._preview_thread is None
    assert not list(tmp_path.glob("*.png"))


def test_video_picker_accepts_file_drops_on_dialog_and_input(
    qtbot, tmp_path: Path, video_file: Path,
) -> None:
    video_file = video_file.rename(tmp_path / "视频 with spaces.avi")
    dialog = FrameExtractionVideoDialog(tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(video_file))])
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    for target in (dialog, dialog.file_input):
        dialog.file_input.setText("previous choice")
        enter = QDragEnterEvent(
            QPoint(5, 5), actions, mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(target, enter)
        assert enter.isAccepted()
        move = QDragMoveEvent(
            QPoint(5, 5), actions, mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(target, move)
        assert move.isAccepted()
        drop = QDropEvent(
            QPointF(5, 5), actions, mime_data,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(target, drop)
        assert drop.isAccepted()
        assert drop.dropAction() == Qt.DropAction.CopyAction
        assert dialog.file_input.text() == str(video_file)
        assert dialog.isVisible()
        assert video_file.is_file()
    dialog.next_button.click()
    qtbot.waitUntil(lambda: not dialog.isVisible())
    assert dialog.video_path == video_file


@pytest.mark.parametrize("source", ["folder", "remote", "multiple", "missing", "text", "busy"])
def test_video_picker_rejects_invalid_or_busy_drops(
    qtbot, tmp_path: Path, video_file: Path, source: str,
) -> None:
    dialog = FrameExtractionVideoDialog(tmp_path)
    qtbot.addWidget(dialog)
    dialog.file_input.setText("previous choice")
    mime_data = QMimeData()
    urls = {
        "folder": [QUrl.fromLocalFile(str(tmp_path))],
        "remote": [QUrl("https://example.com/video.mp4")],
        "multiple": [QUrl.fromLocalFile(str(video_file))] * 2,
        "missing": [QUrl.fromLocalFile(str(tmp_path / "missing.mp4"))],
        "busy": [QUrl.fromLocalFile(str(video_file))],
        "text": [],
    }
    mime_data.setUrls(urls[source])
    mime_data.setText("https://example.com/video.mp4")
    if source == "busy":
        dialog.next_button.setEnabled(False)
    enter = QDragEnterEvent(
        QPoint(5, 5), Qt.DropAction.CopyAction, mime_data,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    dialog.dragEnterEvent(enter)
    assert not enter.isAccepted()
    drop = QDropEvent(
        QPointF(5, 5), Qt.DropAction.CopyAction, mime_data,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    dialog.dropEvent(drop)
    assert not drop.isAccepted()
    assert dialog.file_input.text() == "previous choice"


def test_invalid_video_can_be_corrected(qtbot, tmp_path: Path, video_file: Path) -> None:
    dialog = FrameExtractionVideoDialog(tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.next_button.click()
    assert dialog.error_label.text() == "Choose an existing video file."
    invalid = tmp_path / "broken.mp4"
    invalid.write_text("not a video")
    dialog.file_input.setText(str(invalid))
    dialog.next_button.click()
    qtbot.waitUntil(lambda: dialog.next_button.isEnabled())
    assert dialog.isVisible()
    assert "Could not open" in dialog.error_label.text()
    dialog.file_input.setText(str(video_file))
    dialog.next_button.click()
    qtbot.waitUntil(lambda: not dialog.isVisible())
    assert dialog.result() == dialog.DialogCode.Accepted


def test_frame_and_two_second_seeking_stop_at_boundaries(qtbot, tmp_path: Path, video_file: Path) -> None:
    dialog = _open_video(qtbot, tmp_path, video_file)
    assert dialog.splitter.orientation() == Qt.Orientation.Horizontal
    assert not dialog.finish_button.isEnabled()
    assert not dialog.back_frame_button.isEnabled()
    dialog.forward_frame_button.click()
    _wait_for_frame(qtbot, dialog, 1)
    dialog.forward_seconds_button.click()
    _wait_for_frame(qtbot, dialog, 11)
    dialog.back_seconds_button.click()
    _wait_for_frame(qtbot, dialog, 1)
    dialog.back_frame_button.click()
    _wait_for_frame(qtbot, dialog, 0)
    dialog.position_slider.setValue(14)
    _wait_for_frame(qtbot, dialog, 14)
    assert not dialog.forward_frame_button.isEnabled()
    assert not dialog.forward_seconds_button.isEnabled()
    assert "Frame 15 / 15" in dialog.position_label.text()
    assert "00:00:02.800" in dialog.position_label.text()
    dialog.reject()


def test_selection_thumbnails_are_unique_ordered_and_removable(qtbot, tmp_path: Path, video_file: Path) -> None:
    dialog = _open_video(qtbot, tmp_path, video_file)
    dialog.position_slider.setValue(9)
    _wait_for_frame(qtbot, dialog, 9)
    dialog.select_checkbox.click()
    dialog.position_slider.setValue(2)
    _wait_for_frame(qtbot, dialog, 2)
    dialog.select_checkbox.click()
    assert dialog.selected_frames == [2, 9]
    assert dialog.finish_button.isEnabled()
    assert dialog.select_checkbox.isChecked()
    assert_stable_widget_size(dialog.select_checkbox)
    assert dialog.frame_list.count() == 2
    assert not dialog.frame_list.item(0).icon().isNull()
    assert dialog.frame_list.item(0).text().startswith("Frame 3\n")
    dialog.select_checkbox.click()
    assert not dialog.select_checkbox.isChecked()
    assert dialog.selected_frames == [9]
    item = dialog.frame_list.item(0)
    dialog.frame_list.setCurrentItem(item)
    dialog.frame_list.itemClicked.emit(item)
    _wait_for_frame(qtbot, dialog, 9)
    assert dialog.select_checkbox.isChecked()
    dialog.remove_button.click()
    assert dialog.selected_frames == []
    assert not dialog.select_checkbox.isChecked()
    assert not dialog.finish_button.isEnabled()
    dialog.reject()


def _scroll_video(dialog: FrameExtractionDialog, angle: int, pixels: int = 0) -> QWheelEvent:
    position = dialog.preview.rect().center()
    event = QWheelEvent(
        QPointF(position), QPointF(dialog.preview.mapToGlobal(position)),
        QPoint(0, pixels), QPoint(0, angle),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate, False,
    )
    QApplication.sendEvent(dialog.preview, event)
    return event


def test_mouse_wheel_seeks_frames_and_preserves_selection(qtbot, tmp_path: Path, video_file: Path) -> None:
    dialog = _open_video(qtbot, tmp_path, video_file)
    dialog.select_checkbox.click()
    for delta, frame in [(-120, 1), (120, 0), (120, 0), (-240, 2), (-1440, 14), (-120, 14)]:
        assert _scroll_video(dialog, delta).isAccepted()
        _wait_for_frame(qtbot, dialog, frame)
        assert dialog.selected_frames == [0]
        assert dialog.select_checkbox.isChecked() == (frame == 0)
    dialog.reject()


def test_smooth_wheel_scrolling_accumulates_and_pauses_playback(qtbot, tmp_path: Path, video_file: Path) -> None:
    dialog = _open_video(qtbot, tmp_path, video_file)
    for _ in range(3):
        _scroll_video(dialog, -30)
        assert dialog.current_frame == 0
        assert dialog._ready
    _scroll_video(dialog, -30)
    _wait_for_frame(qtbot, dialog, 1)
    _scroll_video(dialog, 0, pixels=5)
    _wait_for_frame(qtbot, dialog, 0)
    dialog.play_button.click()
    qtbot.waitUntil(lambda: dialog.current_frame >= 2)
    target = dialog._target_frame - 1
    _scroll_video(dialog, 120)
    _wait_for_frame(qtbot, dialog, target)
    assert not dialog._playing
    assert not dialog._timer.isActive()
    dialog.reject()


def test_rapid_scrubbing_selects_the_frame_actually_shown(qtbot, tmp_path: Path, video_file: Path) -> None:
    dialog = _open_video(qtbot, tmp_path, video_file)
    for index in [12, 3, 10, 6]:
        dialog.position_slider.setValue(index)
    _wait_for_frame(qtbot, dialog, 6)
    color = dialog._current_image.pixelColor(0, 0)
    assert (color.red(), color.green(), color.blue()) == (30, 195, 60)
    dialog.select_checkbox.click()
    assert dialog.selected_frames == [6]
    dialog.reject()


@pytest.mark.parametrize("focus", [
    "select_checkbox", "position_slider", "frame_list", "play_button", "cancel_button",
])
def test_frame_shortcuts_work_with_focused_child_controls(
    qtbot, tmp_path: Path, video_file: Path, focus: str,
) -> None:
    dialog = _open_video(qtbot, tmp_path, video_file)
    dialog.activateWindow()
    target = getattr(dialog, focus)
    target.setFocus()
    qtbot.waitUntil(target.hasFocus)
    qtbot.keyClick(target, Qt.Key.Key_Space)
    assert dialog.selected_frames == [0]
    assert dialog.select_checkbox.isChecked()
    qtbot.keyClick(target, Qt.Key.Key_Space)
    assert dialog.selected_frames == []
    assert not dialog.select_checkbox.isChecked()
    assert not dialog._playing
    assert dialog.isVisible()

    for key, modifiers, frame in [
        (Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier, 0),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier, 1),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier, 11),
        (Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier, 1),
        (Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier, 0),
    ]:
        target.setFocus()
        qtbot.keyClick(target, key, modifier=modifiers)
        _wait_for_frame(qtbot, dialog, frame)
        assert dialog.selected_frames == []
    dialog.reject()


def test_destroying_dialog_releases_background_decoder(qtbot, tmp_path: Path, video_file: Path) -> None:
    dialog = _open_video(qtbot, tmp_path, video_file)
    worker = dialog._preview_thread
    assert worker is not None
    assert worker.isRunning()
    dialog.deleteLater()
    qtbot.waitUntil(lambda: not shiboken6.isValid(dialog))
    assert not shiboken6.isValid(worker)
    # On Windows a live VideoCapture would keep this file open.
    video_file.unlink()


def test_playback_pauses_and_restarts_at_end(qtbot, tmp_path: Path, video_file: Path) -> None:
    dialog = _open_video(qtbot, tmp_path, video_file)
    dialog.play_button.click()
    assert dialog.play_button.text() == "Pause"
    qtbot.waitUntil(lambda: dialog.current_frame >= 2)
    dialog.play_button.click()
    # Let any pending decode finish before checking that playback stays paused.
    qtbot.waitUntil(lambda: dialog._ready)
    paused = dialog.current_frame
    qtbot.wait(260)
    assert dialog.current_frame == paused
    dialog.position_slider.setValue(13)
    _wait_for_frame(qtbot, dialog, 13)
    dialog.play_button.click()
    qtbot.waitUntil(lambda: dialog.current_frame == 14 and not dialog._playing)
    assert dialog.play_button.text() == "Play"
    dialog.play_button.click()
    _wait_for_frame(qtbot, dialog, 0)
    dialog.select_checkbox.click()
    assert not dialog._playing
    assert dialog.selected_frames == [0]
    dialog.finish_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog._preview_thread is None


def test_progress_extracts_and_reports_unreadable_video(qtbot, tmp_path: Path, video_file: Path) -> None:
    progress = FrameExtractionProgressDialog(video_file, [0, 5, 14], tmp_path)
    qtbot.addWidget(progress)
    progress.show()
    assert progress.height() < 160
    assert progress.size() == progress.sizeHint()
    progress.start()
    progress.start()  # Starting twice must not schedule duplicate writes.
    qtbot.waitUntil(lambda: not progress._running)
    assert progress.progress.value() == 3
    assert len(progress.result_data.paths) == 3
    assert not progress.result_data.failures
    assert all(path.parent == tmp_path for path in progress.result_data.paths)
    failure = FrameExtractionProgressDialog(tmp_path / "missing.avi", [0], tmp_path)
    qtbot.addWidget(failure)
    failure.start()
    qtbot.waitUntil(lambda: not failure._running)
    assert failure.result_data.failures


def test_progress_cancel_waits_for_worker(qtbot, tmp_path: Path, video_file: Path, monkeypatch) -> None:
    started = Event()
    released = Event()

    def slow_extract(*args, cancelled, **kwargs):
        started.set()
        assert released.wait(5)
        return ExtractionResult(cancelled=cancelled())

    monkeypatch.setattr(frame_dialog_module, "extract_frames", slow_extract)
    progress = FrameExtractionProgressDialog(video_file, [0], tmp_path)
    qtbot.addWidget(progress)
    progress.show()
    progress.start()
    try:
        qtbot.waitUntil(started.is_set)
        progress.close()
        assert progress._running
        assert not progress.cancel_button.isEnabled()
    finally:
        released.set()
        qtbot.waitUntil(lambda: not progress._running)
    assert progress.result_data.cancelled
    assert not progress._worker.isRunning()


def test_menu_workflow_extracts_to_root_and_refreshes_catalog(
    qtbot, tmp_path: Path, video_file: Path, monkeypatch,
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    destination = tmp_path / "destination"
    destination.mkdir()
    window.folders._load_directory(destination, show_issues=False)
    extract = frame_dialog_module.extract_frames
    released = Event()

    def slow_extract(*args, **kwargs):
        assert released.wait(5)
        return extract(*args, **kwargs)

    monkeypatch.setattr(frame_dialog_module, "extract_frames", slow_extract)
    window.commands.frame_extraction_action.trigger()
    picker = window.dialogs._frame_extraction_video_dialog
    assert picker is not None
    assert picker.isVisible()
    assert not window.commands.frame_extraction_action.isEnabled()
    # A second invocation must keep the existing workflow.
    window.dialogs._open_frame_extraction()
    assert window.dialogs._frame_extraction_video_dialog is picker
    closed: list[bool] = []
    picker.finished.connect(lambda result: closed.append(not picker.isVisible()))
    picker.file_input.setText(str(video_file))
    picker.next_button.click()
    qtbot.waitUntil(lambda: window.dialogs._frame_extraction_dialog is not None)
    review = window.dialogs._frame_extraction_dialog
    assert review is not None
    qtbot.waitUntil(lambda: review._ready)
    assert closed == [True]
    assert window.dialogs._frame_extraction_video_dialog is None
    assert review.isVisible()
    review.finished.connect(lambda result: closed.append(not review.isVisible()))
    review.select_checkbox.click()
    review.finish_button.click()
    try:
        progress = window.dialogs._frame_extraction_progress_dialog
        assert progress is not None
        assert progress.isVisible()
        assert progress.height() < 160
        assert closed == [True, True]
        assert window.dialogs._frame_extraction_dialog is None
        assert not window.commands.frame_extraction_action.isEnabled()
    finally:
        released.set()
        qtbot.waitUntil(lambda: window.dialogs._frame_extraction_progress_dialog is None)
    assert (destination / "sample_frame_000001.png").is_file()
    assert window.catalog.image_count == 1
    current = window._current_entry()
    assert current is not None
    assert current.image_path == destination / "sample_frame_000001.png"
    assert "Extracted 1 frame" in window.statusBar().currentMessage()
    assert window.commands.frame_extraction_action.isEnabled()


def test_cancelling_selection_never_starts_extraction(qtbot, tmp_path: Path, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    def unexpected_progress(*args, **kwargs):
        raise AssertionError("Extraction should not start after Cancel")

    monkeypatch.setattr(controller_module, "FrameExtractionProgressDialog", unexpected_progress)
    window.commands.frame_extraction_action.trigger()
    picker = window.dialogs._frame_extraction_video_dialog
    assert picker is not None
    picker.cancel_button.click()
    assert window.dialogs._frame_extraction_video_dialog is None
    assert window.commands.frame_extraction_action.isEnabled()
    assert not list(tmp_path.glob("*.png"))
