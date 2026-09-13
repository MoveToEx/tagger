from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QMenu, QMessageBox

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.crop import CropDialog, CropSelectionDialog
import tagger.ui.dialogs.crop as crop_module
import tagger.ui.main_window.dialogs as dialogs_module
from tagger.ui.main_window.window import MainWindow

from .helpers import assert_stable_widget_size


@pytest.fixture(autouse=True)
def discard_unsaved_on_teardown(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)


def _image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (240, 180), (40, 90, 180, 200)).save(path)
    return path


def test_picker_reuses_folder_tree_and_excludes_disabled_images(qtbot, tmp_path) -> None:
    paths = [_image(tmp_path / name) for name in ("a.png", "child/b.png")]
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"invalid")
    entries = [ImageEntry(path, path.with_suffix(".txt")) for path in [*paths, bad]]
    dialog = CropSelectionDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.selected_paths == paths
    root = dialog.folder_tree.topLevelItem(0)
    assert root is not None
    root.setCheckState(0, Qt.CheckState.Unchecked)
    assert not dialog.continue_button.isEnabled()
    root.setCheckState(0, Qt.CheckState.Checked)
    assert dialog.selected_paths == paths
    dialog.continue_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted


def test_navigation_preserves_drafts_and_finish_only_saves_edited_images(qtbot, tmp_path) -> None:
    paths = [_image(tmp_path / name) for name in ("a.png", "b.png", "c.png")]
    originals = [path.read_bytes() for path in paths]
    dialog = CropDialog(paths)
    qtbot.addWidget(dialog)
    assert not dialog.previous_button.isEnabled()
    dialog.ratio_buttons["1:1"].click()
    box = dialog.image_view.crop_box
    assert box == (30, 0, 210, 180)
    dialog.next_button.click()
    dialog.ratio_buttons["Custom"].click()
    dialog.custom_ratio.setText("2:1")
    dialog.next_button.click()
    assert not dialog.next_button.isEnabled()
    dialog.previous_button.click()
    assert dialog.custom_ratio.text() == "2:1"
    dialog.previous_button.click()
    assert dialog.ratio_buttons["1:1"].isChecked()
    assert dialog.image_view.crop_box == box
    assert [path.read_bytes() for path in paths] == originals
    dialog.finish_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.saved_paths == paths[:2]
    with Image.open(paths[0]) as image:
        assert image.size == (180, 180)
    with Image.open(paths[1]) as image:
        assert image.size == (240, 120)
    assert paths[2].read_bytes() == originals[2]


def test_navigation_alone_never_stages_or_rewrites(qtbot, tmp_path) -> None:
    paths = [_image(tmp_path / name) for name in ("a.png", "b.png")]
    original = [path.read_bytes() for path in paths]
    dialog = CropDialog(paths)
    qtbot.addWidget(dialog)
    dialog.next_button.click()
    dialog.previous_button.click()
    dialog.finish_button.click()
    assert not dialog.saved_paths
    assert [path.read_bytes() for path in paths] == original


def test_preset_crop_rounds_dimensions_without_adding_an_extra_pixel(qtbot, tmp_path) -> None:
    dialog = CropDialog([_image(tmp_path / "a.png")])
    qtbot.addWidget(dialog)
    dialog.ratio_buttons["16:9"].click()
    left, top, right, bottom = dialog.image_view.crop_box
    assert (right - left, bottom - top) == (240, 135)


def test_invalid_custom_ratio_blocks_finish_until_fixed_or_reset(qtbot, tmp_path) -> None:
    dialog = CropDialog([_image(tmp_path / "a.png"), _image(tmp_path / "b.png")])
    qtbot.addWidget(dialog)
    dialog.ratio_buttons["Custom"].click()
    for text in ("", "0", "-2:1", "1:0", "nan", "inf", "1:2:3", "1e300:1e-300"):
        dialog.custom_ratio.setText(text)
        assert not dialog.finish_button.isEnabled()
        assert dialog.ratio_error.text()
    dialog.next_button.click()
    assert not dialog.finish_button.isEnabled()
    dialog.previous_button.click()
    dialog.custom_ratio.setText("3/2")
    assert dialog.finish_button.isEnabled()
    left, top, right, bottom = dialog.image_view.crop_box
    assert (right - left, bottom - top) == (240, 160)
    dialog.reset_button.click()
    assert dialog.ratio_buttons["Free"].isChecked()
    assert not dialog.dirty_paths
    assert_stable_widget_size(dialog.custom_ratio)


def test_cancel_discards_without_saving_and_can_be_aborted(qtbot, tmp_path, monkeypatch) -> None:
    path = _image(tmp_path / "a.png")
    original = path.read_bytes()
    dialog = CropDialog([path])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.ratio_buttons["1:1"].click()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    dialog.cancel_button.click()
    assert dialog.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    dialog.cancel_button.click()
    assert not dialog.isVisible()
    assert path.read_bytes() == original


def test_move_and_resize_keep_crop_bounded_and_preserve_ratio(qtbot, tmp_path) -> None:
    dialog = CropDialog([_image(tmp_path / "a.png")])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.ratio_buttons["1:1"].click()
    view = dialog.image_view
    target = view.image_rect()
    assert target.width() / target.height() == pytest.approx(4 / 3)
    start = view.selection_rect().center().toPoint()
    end = QPointF(target.right() + 100, target.center().y()).toPoint()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(view, end)
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=end)
    assert view.crop_box == (60, 0, 240, 180)
    start = view.selection_rect().bottomRight().toPoint()
    end = view.selection_rect().center().toPoint()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(view, end)
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=end)
    left, top, right, bottom = view.crop_box
    assert left == 60 and top == 0
    assert 1 <= right - left < 180
    assert right - left == bottom - top
    box = view.crop_box
    dialog.resize(1200, 800)
    assert view.crop_box == box


def test_save_failure_keeps_failed_drafts_and_retry_does_not_recrop_successes(qtbot, tmp_path, monkeypatch) -> None:
    paths = [_image(tmp_path / name) for name in ("a.png", "b.png")]
    dialog = CropDialog(paths)
    qtbot.addWidget(dialog)
    dialog.ratio_buttons["1:1"].click()
    dialog.next_button.click()
    dialog.ratio_buttons["2:1"].click()
    real_crop = crop_module.crop_image
    calls = []

    def crop(path, box, **kwargs):
        calls.append(path)
        if path == paths[1]:
            raise OSError("disk full")
        return real_crop(path, box, **kwargs)

    warnings = []
    monkeypatch.setattr(crop_module, "crop_image", crop)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    dialog.finish_button.click()
    assert dialog.saved_paths == paths[:1]
    assert dialog.dirty_paths == {paths[1]}
    assert "disk full" in warnings[0]
    first_saved_bytes = paths[0].read_bytes()
    monkeypatch.setattr(crop_module, "crop_image", real_crop)
    dialog.finish_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert paths[0].read_bytes() == first_saved_bytes
    assert dialog.saved_paths == paths


def test_missing_image_can_be_navigated_past(qtbot, tmp_path) -> None:
    dialog = CropDialog([tmp_path / "missing.png", _image(tmp_path / "a.png")])
    qtbot.addWidget(dialog)
    assert "Could not load" in dialog.size_label.text()
    assert not dialog.options_panel.isEnabled()
    dialog.next_button.click()
    assert dialog.options_panel.isEnabled()
    dialog.finish_button.click()


def test_menu_opens_picker_then_editor_and_refreshes_saved_images(qtbot, tmp_path, monkeypatch) -> None:
    path = _image(tmp_path / "a.png")
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window.commands.crop_action.isEnabled()
    window.folders._load_directory(tmp_path, show_issues=False)
    action = window.commands.crop_action
    assert action.isEnabled()
    menu = next(menu for menu in window.menuBar().findChildren(QMenu) if menu.title() == "&Image")
    assert action in menu.actions()
    calls = []

    def select(dialog):
        calls.append("select")
        return dialog.DialogCode.Accepted

    def edit(dialog):
        calls.append("edit")
        assert dialog.paths == [path]
        dialog.saved_paths.append(path)
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs_module.CropSelectionDialog, "exec", select)
    monkeypatch.setattr(dialogs_module.CropDialog, "exec", edit)
    monkeypatch.setattr(window.preview_loader, "clear", lambda: calls.append("clear"))
    monkeypatch.setattr(window.folders, "_load_directory", lambda *args, **kwargs: calls.append("refresh"))
    action.trigger()
    assert calls == ["select", "edit", "clear", "refresh"]


@pytest.mark.parametrize("accept_selection", [True, False])
def test_catalog_send_to_crop_preselects_current_image(qtbot, tmp_path, monkeypatch, accept_selection) -> None:
    paths = [_image(tmp_path / name) for name in ("a.png", "b.png")]
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window._select_row(1)
    selected_paths = []
    edited_paths = []

    def select(dialog):
        qtbot.addWidget(dialog)
        selected_paths.append(dialog.selected_paths)
        return dialog.DialogCode.Accepted if accept_selection else dialog.DialogCode.Rejected

    def edit(dialog):
        qtbot.addWidget(dialog)
        edited_paths.append(dialog.paths)
        return dialog.DialogCode.Rejected

    monkeypatch.setattr(CropSelectionDialog, "exec", select)
    monkeypatch.setattr(CropDialog, "exec", edit)
    menu = window.files._create_image_context_menu()
    send_to = menu.actions()[-1].menu()
    assert isinstance(send_to, QMenu)
    action = next(action for action in send_to.actions() if action.text() == "Crop...")
    assert action.isEnabled()
    action.trigger()
    assert selected_paths == [[paths[1]]]
    assert edited_paths == ([[paths[1]]] if accept_selection else [])


def test_catalog_crop_is_enabled_for_jpeg_and_disabled_for_animation(qtbot, tmp_path) -> None:
    Image.new("RGB", (30, 20), "red").save(tmp_path / "a.jpg")
    Image.new("RGB", (30, 20), "red").save(
        tmp_path / "b.png", save_all=True,
        append_images=[Image.new("RGB", (30, 20), "blue")],
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    for index, enabled in ((0, True), (1, False)):
        window._select_row(index)
        menu = window.files._create_image_context_menu()
        send_to = menu.actions()[-1].menu()
        assert isinstance(send_to, QMenu)
        action = next(action for action in send_to.actions() if action.text() == "Crop...")
        assert action.isEnabled() == enabled
        if not enabled:
            assert "single-frame" in action.toolTip()
