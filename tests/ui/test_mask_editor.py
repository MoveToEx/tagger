from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.mask_editor import MaskEditorDialog, MaskList, MaskRow, MaskSelectionDialog
import tagger.ui.dialogs.mask_editor as mask_editor_module
import tagger.ui.main_window.dialogs as dialogs_module
from tagger.ui.main_window.window import MainWindow

from .helpers import assert_stable_widget_size


@pytest.fixture(autouse=True)
def discard_unsaved_on_teardown(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)


def _image(path: Path) -> Path:
    Image.new("RGBA", (100, 80), (40, 90, 180, 50)).save(path)
    return path


def _draw_rectangle(qtbot, dialog: MaskEditorDialog) -> None:
    rect = dialog.image_view.image_rect()
    start = rect.topLeft().toPoint() + QPoint(30, 30)
    end = rect.center().toPoint()
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(dialog.image_view, end)
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=end)


def _mask_view_point(dialog: MaskEditorDialog, x: float, y: float) -> QPoint:
    rect = dialog.image_view.image_rect()
    return QPointF(rect.left() + x * rect.width() / 100, rect.top() + y * rect.height() / 80).toPoint()


def test_pointer_selects_polygon_interiors_in_stack_order_and_clears_on_empty_space(qtbot, tmp_path) -> None:
    dialog = MaskEditorDialog([_image(tmp_path / "a.png")])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._add_mask(((10, 10), (90, 10), (90, 70), (10, 70)))
    dialog._add_mask(((30, 20), (70, 20), (30, 60)))
    dialog.save_button.click()
    dialog.pointer_button.click()
    assert dialog.pointer_button.isChecked()
    assert not dialog.rectangle_button.isChecked()
    assert not dialog.pointer_button.icon().isNull()
    assert dialog.image_view.cursor().shape() == Qt.CursorShape.ArrowCursor
    dialog.mask_list.setCurrentRow(1)
    qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=_mask_view_point(dialog, 40, 30))
    assert dialog.mask_list.currentRow() == dialog.image_view.selected_mask == 0
    # This point is inside the triangle's bounds but outside the triangle itself.
    qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=_mask_view_point(dialog, 60, 50))
    assert dialog.mask_list.currentRow() == dialog.image_view.selected_mask == 1
    qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert dialog.mask_list.currentRow() == dialog.image_view.selected_mask == -1
    assert dialog.mask_list.model().moveRow(QModelIndex(), 1, QModelIndex(), 0)
    qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=_mask_view_point(dialog, 40, 30))
    assert dialog.mask_list.currentRow() == dialog.image_view.selected_mask == 0
    assert len(dialog.current_masks[0].points) == 4
    assert dialog.mask_list.count() == 2


@pytest.mark.parametrize("points", [
    ((20, 15), (60, 15), (60, 50), (20, 50)),
    ((20, 25), (40, 15), (60, 50), (30, 45)),
])
def test_move_tool_translates_without_resizing_and_saves_preview(qtbot, tmp_path, points) -> None:
    path = _image(tmp_path / "a.png")
    dialog = MaskEditorDialog([path])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.new_mask_alpha_input.setValue(0.5)
    dialog._add_mask(points)
    original = dialog.current_masks[0]
    dialog.save_button.click()
    dialog.mask_list.setCurrentRow(-1)
    dialog.move_button.click()
    assert not dialog.move_button.icon().isNull()
    assert dialog.image_view.cursor().shape() == Qt.CursorShape.OpenHandCursor
    dialog.actual_opacity_button.click()
    start = _mask_view_point(dialog, 40, 30)
    end = _mask_view_point(dialog, 55, 40)
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    assert dialog.mask_list.currentRow() == dialog.image_view.selected_mask == 0
    assert dialog.image_view.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    qtbot.mouseMove(dialog.image_view, end)
    assert dialog.current_masks[0] == original
    assert not dialog.dirty_paths
    preview = dialog.image_view._drag_preview
    assert preview is not None
    assert preview.bounds == pytest.approx((35, 25, 75, 60), abs=0.25)
    qtbot.waitUntil(lambda: not dialog.image_view._alpha_pixmap.isNull())
    assert dialog.image_view._alpha_pixmap.toImage().pixelColor(55, 40).alpha() == 128
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=end)
    moved = dialog.current_masks[0]
    dx = moved.points[0][0] - original.points[0][0]
    dy = moved.points[0][1] - original.points[0][1]
    for (x, y), (old_x, old_y) in zip(moved.points, original.points):
        assert (x - old_x, y - old_y) == pytest.approx((dx, dy))
    assert moved.alpha == original.alpha
    assert moved.color == original.color
    assert dialog.image_view.cursor().shape() == Qt.CursorShape.OpenHandCursor
    dialog.save_button.click()
    with Image.open(path) as result:
        assert result.getchannel("A").getpixel((55, 40)) == 128
        assert result.getchannel("A").getpixel((25, 25)) == 255


def test_move_keeps_selected_mask_at_overlap_and_clamps_whole_shape(qtbot, tmp_path) -> None:
    dialog = MaskEditorDialog([_image(tmp_path / "a.png")])
    qtbot.addWidget(dialog)
    dialog.show()
    points = ((20, 15), (60, 15), (60, 50), (20, 50))
    dialog._add_mask(points)
    dialog._add_mask(points)
    top = dialog.current_masks[0]
    dialog.mask_list.setCurrentRow(1)
    dialog.move_button.click()
    start = _mask_view_point(dialog, 40, 30)
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert dialog.current_masks[0] == top
    assert dialog.current_masks[1].bounds == (0, 0, 40, 35)
    assert dialog.image_view.selected_mask == dialog.mask_list.currentRow() == 1
    start = _mask_view_point(dialog, 10, 10)
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=dialog.image_view.rect().bottomRight())
    assert dialog.current_masks[1].bounds == (59, 44, 99, 79)
    assert dialog.current_masks[0] == top


@pytest.mark.parametrize("cancel", ["escape", "tool", "navigate"])
def test_move_can_be_cancelled_without_changing_mask(qtbot, tmp_path, cancel) -> None:
    dialog = MaskEditorDialog([_image(tmp_path / name) for name in ("a.png", "b.png")])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._add_mask(((20, 15), (60, 15), (60, 50), (20, 50)))
    original = dialog.current_masks[0]
    dialog.save_button.click()
    dialog.move_button.click()
    start, end = _mask_view_point(dialog, 40, 30), _mask_view_point(dialog, 55, 40)
    qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    assert not dialog.dirty_paths
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(dialog.image_view, end)
    if cancel == "escape":
        qtbot.keyClick(dialog.image_view, Qt.Key.Key_Escape)
    elif cancel == "tool":
        dialog.pointer_button.click()
    else:
        dialog.next_button.click()
        dialog.previous_button.click()
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=end)
    assert dialog.current_masks[0] == original
    assert not dialog.dirty_paths
    assert dialog.image_view._drag_preview is None


@pytest.mark.parametrize("start,end,bounds", [
    ((20, 15), (10, 5), (10, 5, 60, 50)),
    ((40, 15), (40, 5), (20, 5, 60, 50)),
    ((60, 15), (80, 5), (20, 5, 80, 50)),
    ((60, 32.5), (80, 32.5), (20, 15, 80, 50)),
    ((60, 50), (80, 65), (20, 15, 80, 65)),
    ((40, 50), (40, 65), (20, 15, 60, 65)),
    ((20, 50), (10, 65), (10, 15, 60, 65)),
    ((20, 32.5), (10, 32.5), (10, 15, 60, 50)),
])
def test_resize_polygon_from_each_bounding_box_handle(qtbot, tmp_path, start, end, bounds) -> None:
    dialog = MaskEditorDialog([_image(tmp_path / "a.png")])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.new_mask_alpha_input.setValue(0.4)
    dialog._add_mask(((20, 25), (40, 15), (60, 50), (30, 45)))
    original = dialog.current_masks[0]
    dialog.save_button.click()
    assert dialog.image_view.selected_mask == 0
    start_position = _mask_view_point(dialog, *start)
    end_position = _mask_view_point(dialog, *end)
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start_position)
    qtbot.mouseMove(dialog.image_view, end_position)
    assert dialog.current_masks == [original]
    assert not dialog.dirty_paths
    assert dialog.image_view._drag_preview is not None
    assert dialog.image_view._drag_preview.bounds == pytest.approx(bounds, abs=0.25)
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=end_position)
    resized = dialog.current_masks[0]
    assert resized.bounds == pytest.approx(bounds, abs=0.25)
    assert len(resized.points) == 4
    assert resized.alpha == original.alpha
    assert resized.color == original.color
    assert dialog.dirty_paths == {dialog.current_path}
    assert dialog.mask_list.count() == 1
    assert dialog.image_view.selected_mask == 0


def test_resize_rectangle_preview_and_saved_alpha_match(qtbot, tmp_path) -> None:
    path = _image(tmp_path / "a.png")
    dialog = MaskEditorDialog([path])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.new_mask_alpha_input.setValue(0.5)
    dialog._add_mask(((20, 15), (60, 15), (60, 50), (20, 50)))
    dialog.actual_opacity_button.click()
    start = _mask_view_point(dialog, 60, 50)
    end = _mask_view_point(dialog, 80, 65)
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(dialog.image_view, end)
    qtbot.waitUntil(lambda: not dialog.image_view._alpha_pixmap.isNull())
    assert dialog.image_view._alpha_pixmap.toImage().pixelColor(70, 55).alpha() == 128
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=end)
    dialog.save_button.click()
    with Image.open(path) as result:
        assert result.getchannel("A").getpixel((70, 55)) == 128
        assert result.getchannel("A").getpixel((90, 70)) == 255


def test_resize_cancels_and_clamps_without_inverting_the_mask(qtbot, tmp_path) -> None:
    dialog = MaskEditorDialog([_image(tmp_path / "a.png")])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._add_mask(((20, 15), (60, 15), (60, 50), (20, 50)))
    original = dialog.current_masks[0]
    dialog.save_button.click()
    start = _mask_view_point(dialog, 20, 15)
    end = _mask_view_point(dialog, 80, 65)
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(dialog.image_view, end)
    assert dialog.image_view._drag_preview is not None
    assert dialog.image_view._drag_preview.bounds == (59, 49, 60, 50)
    qtbot.keyClick(dialog.image_view, Qt.Key.Key_Escape)
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=end)
    assert dialog.current_masks == [original]
    assert not dialog.dirty_paths
    assert dialog.isVisible()
    # A click without dragging is also a no-op.
    qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    assert dialog.current_masks == [original]
    assert not dialog.dirty_paths
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert dialog.current_masks[0].bounds == (0, 0, 60, 50)
    qtbot.keyClick(dialog.image_view, Qt.Key.Key_Escape)
    assert dialog.mask_list.currentRow() == dialog.image_view.selected_mask == -1
    assert dialog.image_view._resize_handles() == {}


def test_resize_targets_selected_mask_after_reordering_and_navigation_cancels_drag(qtbot, tmp_path) -> None:
    dialog = MaskEditorDialog([_image(tmp_path / name) for name in ("a.png", "b.png")])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._add_mask(((20, 15), (60, 15), (60, 50), (20, 50)))
    dialog._add_mask(((5, 5), (10, 5), (10, 10), (5, 10)))
    other = dialog.current_masks[0]
    dialog.mask_list.setCurrentRow(1)
    assert dialog.mask_list.model().moveRow(QModelIndex(), 1, QModelIndex(), 0)
    assert dialog.image_view.selected_mask == dialog.mask_list.currentRow() == 0
    start = _mask_view_point(dialog, 60, 50)
    end = _mask_view_point(dialog, 80, 65)
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseRelease(dialog.image_view, Qt.MouseButton.LeftButton, pos=end)
    assert dialog.current_masks[0].bounds == pytest.approx((20, 15, 80, 65), abs=0.25)
    assert dialog.current_masks[1] == other
    resized = dialog.current_masks[0]
    qtbot.mousePress(dialog.image_view, Qt.MouseButton.LeftButton, pos=end)
    qtbot.mouseMove(dialog.image_view, _mask_view_point(dialog, 70, 55))
    dialog.next_button.click()
    assert dialog.image_view._drag_preview is None
    assert dialog.image_view.selected_mask == -1
    dialog.previous_button.click()
    assert dialog.current_masks[0] == resized
    dialog.mask_list.setCurrentRow(0)
    dialog.delete_button.click()
    assert dialog.image_view.selected_mask == -1
    assert dialog.image_view._resize_handles() == {}


def test_picker_disables_jpeg_even_when_checking_parent_and_warns(qtbot, tmp_path, monkeypatch) -> None:
    png = _image(tmp_path / "a.png")
    jpeg = tmp_path / "b.JPEG"
    Image.new("RGB", (10, 10)).save(jpeg)
    entries = [ImageEntry(path, path.with_suffix(".txt")) for path in (png, jpeg)]
    picker = MaskSelectionDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(picker)
    root = picker.folder_tree.topLevelItem(0)
    assert root is not None
    assert root.child(1).isDisabled()
    assert "JPEG" in root.child(1).toolTip(0)
    assert picker.selected_paths == [png]
    root.setCheckState(0, Qt.CheckState.Unchecked)
    assert not picker.continue_button.isEnabled()
    root.setCheckState(0, Qt.CheckState.Checked)
    assert picker.selected_paths == [png]
    assert root.child(1).checkState(0) == Qt.CheckState.Unchecked
    messages = []

    def warning(*args):
        messages.append(args[2])
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "warning", warning)
    picker.continue_button.click()
    assert picker.result() == picker.DialogCode.Rejected
    assert "does not preserve existing alpha channel masks" in messages[0]
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    picker.continue_button.click()
    assert picker.result() == picker.DialogCode.Accepted


def test_draw_edit_hover_preview_and_save_across_images(qtbot, tmp_path) -> None:
    paths = [_image(tmp_path / name) for name in ("a.png", "b.png")]
    originals = [path.read_bytes() for path in paths]
    dialog = MaskEditorDialog(paths)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.image_view.width() > 320)
    _draw_rectangle(qtbot, dialog)
    assert len(dialog.current_masks) == dialog.mask_list.count() == 1
    assert len(dialog.current_masks[0].points) == 4
    row = dialog.mask_list.itemWidget(dialog.mask_list.item(0))
    assert isinstance(row, MaskRow)
    assert_stable_widget_size(row.alpha_input, minimum_width=88, vertical_padding=2)
    assert_stable_widget_size(dialog.base_alpha_input, minimum_width=88, vertical_padding=2)
    row.alpha_input.setValue(0.5)
    assert dialog.current_masks[0].alpha == 0.5
    qtbot.waitUntil(row.alpha_input.isVisible)
    qtbot.mouseMove(dialog.image_view, QPoint(1, 1))
    qtbot.mouseMove(row.alpha_input, row.alpha_input.rect().center())
    qtbot.waitUntil(lambda: dialog.image_view.hovered_mask == 0)
    qtbot.mouseMove(dialog.image_view, QPoint(1, 1))
    qtbot.waitUntil(lambda: dialog.image_view.hovered_mask == -1)
    assert dialog.image_view.overlay_opacity == 0.15
    dialog.actual_opacity_button.click()
    dialog.image_view.repaint()
    assert dialog.image_view.actual_opacity
    assert not dialog.image_view._alpha_pixmap.isNull()
    dialog.next_button.click()
    assert dialog.mask_list.count() == 0
    dialog.previous_button.click()
    assert dialog.current_masks[0].alpha == 0.5
    assert paths[0].read_bytes() == originals[0]
    dialog.save_button.click()
    assert dialog.saved_paths == [paths[0]]
    assert not dialog.dirty_paths
    with Image.open(paths[0]) as result:
        assert result.getchannel("A").getpixel((25, 20)) == 128
        assert result.getchannel("A").getpixel((0, 0)) == 255
    assert paths[1].read_bytes() == originals[1]


def test_base_alpha_is_per_image_and_saves_without_polygons(qtbot, tmp_path) -> None:
    paths = [_image(tmp_path / name) for name in ("a.png", "b.png")]
    dialog = MaskEditorDialog(paths)
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.image_label.parentWidget() is dialog.image_view.parentWidget()
    assert not hasattr(dialog, "opacity_input")
    assert not hasattr(dialog, "instructions")
    dialog.base_alpha_input.setValue(0.25)
    dialog.actual_opacity_button.click()
    qtbot.waitUntil(lambda: not dialog.image_view._alpha_pixmap.isNull())
    assert dialog.image_view._alpha_pixmap.toImage().pixelColor(0, 0).alpha() == 64
    dialog.next_button.click()
    assert dialog.base_alpha_input.value() == 1.0
    assert dialog.dirty_paths == {paths[0]}
    dialog.previous_button.click()
    assert dialog.base_alpha_input.value() == 0.25
    dialog.save_button.click()
    with Image.open(paths[0]) as result:
        assert result.getchannel("A").getextrema() == (64, 64)
    assert dialog.image_label.text().startswith("1 / 2")


def test_new_mask_alpha_applies_to_new_shapes_and_persists_during_navigation(qtbot, tmp_path) -> None:
    dialog = MaskEditorDialog([_image(tmp_path / name) for name in ("a.png", "b.png")])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.image_view.width() > 320)
    assert dialog.new_mask_alpha_input.value() == 0.0
    assert_stable_widget_size(dialog.new_mask_alpha_input, minimum_width=88, vertical_padding=2)
    dialog.new_mask_alpha_input.setValue(0.35)
    assert not dialog.dirty_paths
    _draw_rectangle(qtbot, dialog)
    assert dialog.current_masks[0].alpha == 0.35
    dialog.new_mask_alpha_input.setValue(0.8)
    assert dialog.current_masks[0].alpha == 0.35
    assert dialog.base_alpha_input.value() == 1.0
    dialog.next_button.click()
    assert dialog.new_mask_alpha_input.value() == 0.8
    dialog.polygon_button.click()
    rect = dialog.image_view.image_rect()
    for point in (
        rect.topLeft().toPoint() + QPoint(40, 40),
        rect.topRight().toPoint() + QPoint(-40, 40),
        rect.center().toPoint(),
    ):
        qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=point)
    qtbot.keyClick(dialog.image_view, Qt.Key.Key_Return)
    assert dialog.current_masks[0].alpha == 0.8
    row = dialog.mask_list.itemWidget(dialog.mask_list.item(0))
    assert isinstance(row, MaskRow)
    assert row.alpha_input.value() == 0.8
    dialog.previous_button.click()
    assert dialog.current_masks[0].alpha == 0.35


def test_drag_handle_starts_native_list_drag(qtbot, tmp_path, monkeypatch) -> None:
    dialog = MaskEditorDialog([_image(tmp_path / "a.png")])
    qtbot.addWidget(dialog)
    dialog._add_mask(((1, 1), (50, 1), (50, 40)))
    dialog.show()
    row = dialog.mask_list.itemWidget(dialog.mask_list.item(0))
    assert isinstance(row, MaskRow)
    qtbot.waitUntil(row.drag_handle.isVisible)
    drags = []
    monkeypatch.setattr(MaskList, "startDrag", lambda self, actions: drags.append(self.currentRow()))
    handle = row.drag_handle
    start = handle.rect().center()
    qtbot.mousePress(handle, Qt.MouseButton.LeftButton, pos=start)
    end = QPointF(start + QPoint(0, QApplication.startDragDistance() + 10))
    move = QMouseEvent(
        QEvent.Type.MouseMove, end, handle.mapToGlobal(end),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(handle, move)
    qtbot.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=end.toPoint())
    assert drags == [0]


def test_reordering_updates_overlap_hover_alpha_editing_and_saved_output(qtbot, tmp_path) -> None:
    paths = [_image(tmp_path / name) for name in ("a.png", "b.png")]
    dialog = MaskEditorDialog(paths)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._add_mask(((1, 1), (50, 1), (50, 40), (1, 40)))
    dialog._set_alpha(0, 0.25)
    lower_color = dialog.current_masks[0].color
    dialog._add_mask(((10, 10), (60, 10), (60, 50), (10, 50)))
    dialog._set_alpha(0, 0.75)
    dialog._rebuild_mask_list()
    dialog.actual_opacity_button.click()
    qtbot.waitUntil(lambda: not dialog.image_view._alpha_pixmap.isNull())
    assert dialog.image_view._alpha_pixmap.toImage().pixelColor(20, 20).alpha() == 191
    model = dialog.mask_list.model()
    assert model.moveRow(QModelIndex(), 1, QModelIndex(), 0)
    assert dialog.current_masks[0].color == lower_color
    dialog.image_view.repaint()
    assert dialog.image_view._alpha_pixmap.toImage().pixelColor(20, 20).alpha() == 64
    row = dialog.mask_list.itemWidget(dialog.mask_list.item(0))
    assert isinstance(row, MaskRow)
    row.alpha_input.setValue(0.5)
    assert dialog.current_masks[0].alpha == 0.5
    assert dialog.current_masks[1].alpha == 0.75
    qtbot.mouseMove(dialog.image_view, QPoint(1, 1))
    qtbot.mouseMove(row.alpha_input, row.alpha_input.rect().center())
    qtbot.waitUntil(lambda: dialog.image_view.hovered_mask == 0)
    # Moving down must update row bindings just as moving up does.
    assert model.moveRow(QModelIndex(), 0, QModelIndex(), 2)
    row.alpha_input.setValue(0.2)
    assert dialog.current_masks[1].alpha == 0.2
    assert model.moveRow(QModelIndex(), 1, QModelIndex(), 0)
    dialog.next_button.click()
    dialog.previous_button.click()
    assert dialog.current_masks[0].color == lower_color
    dialog.base_alpha_input.setValue(0.1)
    dialog.save_button.click()
    with Image.open(paths[0]) as result:
        assert result.getchannel("A").getpixel((20, 20)) == 51
        assert result.getchannel("A").getpixel((55, 45)) == 191
        assert result.getchannel("A").getpixel((90, 70)) == 26


def test_picker_disables_folders_with_only_jpegs(qtbot, tmp_path) -> None:
    nested = tmp_path / "jpeg-only"
    nested.mkdir()
    jpeg = nested / "image.jpg"
    Image.new("RGB", (10, 10)).save(jpeg)
    png = _image(tmp_path / "image.png")
    entries = [ImageEntry(path, path.with_suffix(".txt")) for path in (jpeg, png)]
    dialog = MaskSelectionDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)
    root = dialog.folder_tree.topLevelItem(0)
    assert root is not None
    assert root.child(0).isDisabled()
    assert root.checkState(0) == Qt.CheckState.Checked
    assert dialog.selected_paths == [png]


def test_polygon_finish_cancel_delete_and_close_without_saving(qtbot, tmp_path, monkeypatch) -> None:
    path = _image(tmp_path / "a.png")
    original = path.read_bytes()
    dialog = MaskEditorDialog([path])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.polygon_button.click()
    rect = dialog.image_view.image_rect()
    points = [rect.topLeft().toPoint() + QPoint(40, 40),
              rect.topRight().toPoint() + QPoint(-40, 40), rect.center().toPoint()]
    for point in points:
        qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=point)
    qtbot.keyClick(dialog.image_view, Qt.Key.Key_Return)
    assert len(dialog.current_masks) == 1
    assert len(dialog.current_masks[0].points) == 3
    for point in points[:2]:
        qtbot.mouseClick(dialog.image_view, Qt.MouseButton.LeftButton, pos=point)
    qtbot.keyClick(dialog.image_view, Qt.Key.Key_Escape)
    assert len(dialog.current_masks) == 1
    assert not dialog.image_view._points
    assert dialog.isVisible()
    dialog.rectangle_button.click()
    _draw_rectangle(qtbot, dialog)
    assert dialog.current_masks[0].color != dialog.current_masks[1].color
    dialog.delete_button.click()
    assert dialog.mask_list.count() == 1
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    dialog.close()
    assert dialog.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    dialog.close()
    assert not dialog.isVisible()
    assert path.read_bytes() == original


def test_failed_save_stays_dirty_and_can_be_retried(qtbot, tmp_path, monkeypatch) -> None:
    path = _image(tmp_path / "a.png")
    dialog = MaskEditorDialog([path])
    qtbot.addWidget(dialog)
    dialog._add_mask(((1, 1), (50, 1), (50, 40)))
    real_save = mask_editor_module.save_masks

    def fail(*args):
        raise OSError("disk full")

    warnings = []
    monkeypatch.setattr(mask_editor_module, "save_masks", fail)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    dialog.save_button.click()
    assert dialog.dirty_paths == {path}
    assert dialog.saved_paths == []
    assert "disk full" in warnings[0]
    monkeypatch.setattr(mask_editor_module, "save_masks", real_save)
    dialog.save_button.click()
    assert not dialog.dirty_paths


def test_menu_opens_picker_then_editor_and_refreshes_saved_images(qtbot, tmp_path, monkeypatch) -> None:
    path = _image(tmp_path / "a.png")
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window.commands.mask_editor_action.isEnabled()
    window.folders._load_directory(tmp_path, show_issues=False)
    action = window.commands.mask_editor_action
    assert action.isEnabled()
    menus = window.menuBar().findChildren(QMenu)
    image_menu = next(menu for menu in menus if menu.title() == "&Image")
    assert action in image_menu.actions()
    called = []

    def select(dialog):
        called.append("select")
        return dialog.DialogCode.Accepted

    def edit(dialog):
        called.append("edit")
        assert dialog.paths == [path]
        dialog.saved_paths.append(path)
        return dialog.DialogCode.Rejected

    monkeypatch.setattr(dialogs_module.MaskSelectionDialog, "exec", select)
    monkeypatch.setattr(dialogs_module.MaskEditorDialog, "exec", edit)
    monkeypatch.setattr(window.preview_loader, "clear", lambda: called.append("clear"))
    monkeypatch.setattr(window.folders, "_load_directory", lambda *args, **kwargs: called.append("refresh"))
    action.trigger()
    assert called == ["select", "edit", "clear", "refresh"]


def test_catalog_send_to_mask_editor_preselects_only_current_image(qtbot, tmp_path, monkeypatch) -> None:
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
        return dialog.DialogCode.Accepted

    def edit(dialog):
        qtbot.addWidget(dialog)
        edited_paths.append(dialog.paths)
        return dialog.DialogCode.Rejected

    monkeypatch.setattr(MaskSelectionDialog, "exec", select)
    monkeypatch.setattr(MaskEditorDialog, "exec", edit)
    menu = window.files._create_image_context_menu()
    send_to = menu.actions()[-1].menu()
    assert isinstance(send_to, QMenu)
    action = next(action for action in send_to.actions() if action.text() == "Mask Editor...")
    assert action.isEnabled()
    action.trigger()
    assert selected_paths == [[paths[1]]]
    assert edited_paths == [[paths[1]]]


def test_catalog_mask_editor_is_available_for_opaque_png_but_disabled_for_jpeg(qtbot, tmp_path) -> None:
    for name, image_format in (("a.png", "PNG"), ("b.jpg", "JPEG")):
        Image.new("RGB", (20, 20)).save(tmp_path / name, format=image_format)
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    for index, enabled in ((0, True), (1, False)):
        window._select_row(index)
        menu = window.files._create_image_context_menu()
        send_to = menu.actions()[-1].menu()
        assert isinstance(send_to, QMenu)
        action = next(action for action in send_to.actions() if action.text() == "Mask Editor...")
        assert action.isEnabled() == enabled
        if not enabled:
            assert "JPEG" in action.toolTip()
