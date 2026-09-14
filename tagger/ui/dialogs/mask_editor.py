from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import random
from typing import cast, override

from PIL import Image, ImageQt
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QEnterEvent, QIcon, QKeyEvent, QMouseEvent, QPaintEvent,
    QPainter, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QDoubleSpinBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QProgressDialog,
    QPushButton, QToolButton, QVBoxLayout, QWidget, QSlider, QComboBox,
    QDialogButtonBox, QFormLayout, QMenu,
)

from tagger.domain.masks import MaskRegion
from tagger.domain.models import ImageEntry
from tagger.mask_storage import (
    load_mask_image, mask_editing_disabled_reason, render_masks, save_masks,
)
from tagger.paths import PROJECT_ROOT
from tagger.ui.dialogs.transparency import TransparencySelectionDialog
from tagger.ui.widgets import stabilize_checked_tool_button, stabilize_widget_size


class MaskSelectionDialog(TransparencySelectionDialog):
    def __init__(
        self,
        entries: list[ImageEntry],
        parent: QWidget | None = None,
        *,
        root_directory: Path | None = None,
        initial_paths: list[Path] | None = None,
    ) -> None:
        super().__init__(
            entries, parent, root_directory=root_directory,
            initial_paths=initial_paths,
            disabled_reason=mask_editing_disabled_reason,
            title="Mask Editor — Select Images",
            prompt="Select images to edit masks. JPEG cannot store an alpha channel.",
            action_text="Continue",
        )
        self.continue_button = self.remove_button

    @override
    def _accept_selection(self) -> None:
        if not self.selected_paths:
            return
        answer = QMessageBox.warning(
            self,
            "Existing Alpha Masks Will Be Replaced",
            "Editing masks does not preserve existing alpha channel masks. "
            "Saving replaces the alpha channel of edited images. Continue?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Ok:
            self.accept()


class MaskImageView(QWidget):
    polygon_created = Signal(object)
    mask_transformed = Signal(int, object)
    mask_selected = Signal(int)
    navigation_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 260)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.tool = "rectangle"
        self.masks: list[MaskRegion] = []
        self.overlay_opacity = 0.15
        self.base_alpha = 1.0
        self.actual_opacity = False
        self.hovered_mask = -1
        self.selected_mask = -1
        self._drag_original: MaskRegion | None = None
        self._drag_preview: MaskRegion | None = None
        self._drag_handle = ""
        self._drag_start = QPointF()
        self._image: Image.Image | None = None
        self._pixmap = QPixmap()
        self._alpha_pixmap = QPixmap()
        self._points: list[QPointF] = []
        self._cursor: QPointF | None = None
        tile = QPixmap(24, 24)
        tile.fill(QColor("#eeeeee"))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 12, 12, QColor("#c8c8c8"))
        painter.fillRect(12, 12, 12, 12, QColor("#c8c8c8"))
        painter.end()
        self._checker = QBrush(tile)

    def set_image(self, image: Image.Image | None, masks: list[MaskRegion]) -> None:
        self.cancel_drawing()
        self.selected_mask = -1
        self._image = image
        self._pixmap = ImageQt.toqpixmap(image) if image is not None else QPixmap()
        self.hovered_mask = -1
        self.set_masks(masks)

    def set_masks(self, masks: list[MaskRegion]) -> None:
        self._cancel_drag()
        self.masks = masks
        self._alpha_pixmap = QPixmap()
        self.update()

    def set_tool(self, tool: str) -> None:
        self.cancel_drawing()
        self.tool = tool
        self._set_resize_cursor("")

    def set_selected_mask(self, index: int) -> None:
        self.cancel_drawing()
        self.selected_mask = index if 0 <= index < len(self.masks) else -1
        self.update()

    def _selected_region(self) -> MaskRegion | None:
        if 0 <= self.selected_mask < len(self.masks):
            return self._drag_preview or self.masks[self.selected_mask]
        return None

    def _selection_rect(self) -> QRectF:
        mask = self._selected_region()
        target = self.image_rect()
        if mask is None or target.isEmpty():
            return QRectF()
        left, top, right, bottom = mask.bounds
        scale = target.width() / self._pixmap.width()
        return QRectF(
            target.left() + left * scale, target.top() + top * scale,
            (right - left) * scale, (bottom - top) * scale,
        )

    def _resize_handles(self) -> dict[str, QPointF]:
        rect = self._selection_rect()
        if rect.isEmpty() or self.tool == "move":
            return {}
        return {
            "nw": rect.topLeft(), "n": QPointF(rect.center().x(), rect.top()),
            "ne": rect.topRight(), "e": QPointF(rect.right(), rect.center().y()),
            "se": rect.bottomRight(), "s": QPointF(rect.center().x(), rect.bottom()),
            "sw": rect.bottomLeft(), "w": QPointF(rect.left(), rect.center().y()),
        }

    def _resize_hit_test(self, position: QPointF) -> str:
        if self._points:
            return ""
        handles = self._resize_handles()
        if not handles:
            return ""
        closest = min(handles, key=lambda name: (handles[name] - position).manhattanLength())
        delta = handles[closest] - position
        if abs(delta.x()) <= 6 and abs(delta.y()) <= 6:
            return closest
        rect = self._selection_rect()
        if rect.top() <= position.y() <= rect.bottom():
            if abs(position.x() - rect.left()) <= 5:
                return "w"
            if abs(position.x() - rect.right()) <= 5:
                return "e"
        if rect.left() <= position.x() <= rect.right():
            if abs(position.y() - rect.top()) <= 5:
                return "n"
            if abs(position.y() - rect.bottom()) <= 5:
                return "s"
        return ""

    def _mask_at(self, position: QPointF, *, prefer_selected: bool = False) -> int:
        point = self._image_point(position)
        if point is None:
            return -1
        indices = list(range(len(self.masks)))
        if prefer_selected and self.selected_mask in indices:
            indices.remove(self.selected_mask)
            indices.insert(0, self.selected_mask)
        for index in indices:
            if self._polygon(self.masks[index]).containsPoint(point, Qt.FillRule.OddEvenFill):
                return index
        return -1

    def _set_resize_cursor(self, handle: str) -> None:
        cursors = {
            "nw": Qt.CursorShape.SizeFDiagCursor, "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor, "sw": Qt.CursorShape.SizeBDiagCursor,
            "n": Qt.CursorShape.SizeVerCursor, "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor, "w": Qt.CursorShape.SizeHorCursor,
        }
        default = {
            "pointer": Qt.CursorShape.ArrowCursor,
            "move": Qt.CursorShape.OpenHandCursor,
        }.get(self.tool, Qt.CursorShape.CrossCursor)
        self.setCursor(cursors.get(handle, default))

    def _update_drag(self, position: QPointF) -> None:
        original = self._drag_original
        target = self.image_rect()
        if original is None or target.isEmpty():
            return
        left, top, right, bottom = original.bounds
        delta = (position - self._drag_start) * self._pixmap.width() / target.width()
        if self._drag_handle == "move":
            dx = max(-left, min(self._pixmap.width() - 1.0 - right, delta.x()))
            dy = max(-top, min(self._pixmap.height() - 1.0 - bottom, delta.y()))
            self._drag_preview = original.translated(dx, dy)
            self._alpha_pixmap = QPixmap()
            self.update()
            return
        minimum_width = min(1.0, right - left)
        minimum_height = min(1.0, bottom - top)
        if "w" in self._drag_handle:
            left = max(0.0, min(right - minimum_width, left + delta.x()))
        if "e" in self._drag_handle:
            right = min(self._pixmap.width() - 1.0, max(left + minimum_width, right + delta.x()))
        if "n" in self._drag_handle:
            top = max(0.0, min(bottom - minimum_height, top + delta.y()))
        if "s" in self._drag_handle:
            bottom = min(self._pixmap.height() - 1.0, max(top + minimum_height, bottom + delta.y()))
        self._drag_preview = (
            original if (left, top, right, bottom) == original.bounds
            else original.resized((left, top, right, bottom))
        )
        self._alpha_pixmap = QPixmap()
        self.update()

    def _cancel_drag(self) -> None:
        self._drag_original = None
        self._drag_preview = None
        self._drag_handle = ""
        self._alpha_pixmap = QPixmap()
        self._set_resize_cursor("")

    def set_actual_opacity(self, enabled: bool) -> None:
        self.actual_opacity = enabled
        self.update()

    def set_base_alpha(self, alpha: float) -> None:
        self.base_alpha = alpha
        self._alpha_pixmap = QPixmap()
        self.update()

    def set_hovered_mask(self, index: int) -> None:
        self.hovered_mask = index
        self.update()

    def image_rect(self) -> QRectF:
        if self._pixmap.isNull():
            return QRectF()
        available = QRectF(self.rect()).adjusted(12, 12, -12, -12)
        scale = min(
            available.width() / self._pixmap.width(),
            available.height() / self._pixmap.height(),
        )
        size = QPointF(self._pixmap.width() * scale, self._pixmap.height() * scale)
        return QRectF(available.center() - size / 2, available.center() + size / 2)

    def _image_point(self, position: QPointF, *, clamp: bool = False) -> QPointF | None:
        rect = self.image_rect()
        if rect.isEmpty() or (not clamp and not rect.contains(position)):
            return None
        return QPointF(
            min(self._pixmap.width() - 1, max(0.0,
                (position.x() - rect.left()) * self._pixmap.width() / rect.width())),
            min(self._pixmap.height() - 1, max(0.0,
                (position.y() - rect.top()) * self._pixmap.height() / rect.height())),
        )

    def _polygon(self, mask: MaskRegion) -> QPolygonF:
        return QPolygonF([QPointF(x, y) for x, y in mask.points])

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        target = self.image_rect()
        if target.isEmpty():
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Image unavailable")
            painter.end()
            return
        painter.fillRect(target, self._checker)
        masks = list(self.masks)
        if self._drag_preview is not None and 0 <= self.selected_mask < len(masks):
            masks[self.selected_mask] = self._drag_preview
        pixmap = self._pixmap
        if self.actual_opacity and self._image is not None:
            if self._alpha_pixmap.isNull():
                self._alpha_pixmap = ImageQt.toqpixmap(
                    render_masks(self._image, masks, self.base_alpha)
                )
            pixmap = self._alpha_pixmap
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.save()
        painter.setClipRect(target)
        painter.translate(target.topLeft())
        painter.scale(target.width() / pixmap.width(), target.height() / pixmap.height())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index in reversed(range(len(masks))):
            mask = masks[index]
            color = QColor(mask.color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.setOpacity(self.overlay_opacity)
            if not self.actual_opacity and index != self.hovered_mask:
                painter.drawPolygon(self._polygon(mask))
            painter.setOpacity(1.0)
            if mask.fadeout_mode != "none" and mask.fadeout_width > 0:
                left, top, right, bottom = mask.bounds
                amount = mask.fadeout_width
                if mask.fadeout_mode == "outside":
                    left, top = max(0.0, left - amount), max(0.0, top - amount)
                    right, bottom = min(self._pixmap.width(), right + amount), min(self._pixmap.height(), bottom + amount)
                else:
                    left, top = min(right, left + amount), min(bottom, top + amount)
                    right, bottom = max(left, right - amount), max(top, bottom - amount)
                painter.setPen(QPen(color, 2))
                painter.setBrush(QColor(color).lighter(165))
                painter.setOpacity(0.3)
                painter.drawRect(QRectF(left, top, max(0.0, right - left), max(0.0, bottom - top)))
                painter.setOpacity(1.0)
            pen = QPen(color, 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(self._polygon(mask))
        # Draw the hovered fill last so higher-priority masks cannot hide it.
        if 0 <= self.hovered_mask < len(self.masks):
            mask = masks[self.hovered_mask]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(mask.color))
            painter.setOpacity(0.85)
            # The normal pass only draws non-hovered fills below this highlight.
            painter.drawPolygon(self._polygon(mask))
            painter.setOpacity(1.0)
        if self._points and self._cursor is not None:
            pen = QPen(QColor("#ffffff"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self.tool == "rectangle":
                painter.drawRect(QRectF(self._points[0], self._cursor).normalized())
            else:
                painter.drawPolyline(QPolygonF(self._points + [self._cursor]))
        painter.restore()
        handles = self._resize_handles() if not self._points else {}
        if not self._points and not self._selection_rect().isEmpty():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#202020"), 2))
            painter.drawRect(self._selection_rect())
            painter.setPen(QPen(QColor("white"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self._selection_rect())
            painter.setPen(QPen(QColor("#202020"), 1))
            painter.setBrush(QColor("white"))
            for point in handles.values():
                painter.drawRect(QRectF(point.x() - 4, point.y() - 4, 8, 8))
        painter.end()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.BackButton:
            self.navigation_requested.emit(-1)
            event.accept()
            return
        if event.button() == Qt.MouseButton.ForwardButton:
            self.navigation_requested.emit(1)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.finish_polygon()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.tool == "move":
            self.setFocus()
            index = self._mask_at(event.position(), prefer_selected=True)
            self.set_selected_mask(index)
            self.mask_selected.emit(index)
            if index >= 0:
                self._drag_original = self.masks[index]
                self._drag_preview = self._drag_original
                self._drag_handle = "move"
                self._drag_start = event.position()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        handle = self._resize_hit_test(event.position())
        if handle:
            self.setFocus()
            self._drag_original = self.masks[self.selected_mask]
            self._drag_preview = self._drag_original
            self._drag_handle = handle
            self._drag_start = event.position()
            self._set_resize_cursor(handle)
            return
        if self.tool == "pointer":
            self.setFocus()
            index = self._mask_at(event.position())
            self.set_selected_mask(index)
            self.mask_selected.emit(index)
            return
        point = self._image_point(event.position())
        if point is None:
            return
        self.setFocus()
        self._cursor = point
        if self.tool == "rectangle":
            self._points = [point]
        else:
            if len(self._points) >= 3:
                distance = point - self._points[0]
                scale = self.image_rect().width() / self._pixmap.width()
                if (distance.x() ** 2 + distance.y() ** 2) * scale ** 2 <= 64:
                    self.finish_polygon()
                    return
            self._points.append(point)
        self.update()

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_original is not None:
            self._update_drag(event.position())
            return
        self._set_resize_cursor(self._resize_hit_test(event.position()))
        self._cursor = self._image_point(event.position(), clamp=True)
        if self._points:
            self.update()

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_original is not None:
            self._update_drag(event.position())
            original, resized = self._drag_original, self._drag_preview
            index = self.selected_mask
            self._cancel_drag()
            if resized is not None and resized != original:
                self.mask_transformed.emit(index, resized)
            self.update()
            return
        if (event.button() != Qt.MouseButton.LeftButton or self.tool != "rectangle"
                or not self._points):
            return
        end = self._image_point(event.position(), clamp=True)
        if end is not None:
            rect = QRectF(self._points[0], end).normalized()
            if rect.width() >= 1 and rect.height() >= 1:
                self.polygon_created.emit((
                    (rect.left(), rect.top()), (rect.right(), rect.top()),
                    (rect.right(), rect.bottom()), (rect.left(), rect.bottom()),
                ))
        self.cancel_drawing()

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.tool == "polygon":
            point = self._image_point(event.position())
            if point is not None and (not self._points or point != self._points[-1]):
                self._points.append(point)
            self.finish_polygon()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._drag_original is not None:
            self._cancel_drag()
            self.update()
        elif event.key() == Qt.Key.Key_Escape and self._points:
            self.cancel_drawing()
        elif event.key() == Qt.Key.Key_Escape and self.selected_mask >= 0:
            self.set_selected_mask(-1)
            self.mask_selected.emit(-1)
        elif event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.finish_polygon()
        elif event.key() == Qt.Key.Key_Backspace and self._points:
            self._points.pop()
            self.update()
        elif event.key() == Qt.Key.Key_Left:
            self.navigation_requested.emit(-1)
        elif event.key() == Qt.Key.Key_Right:
            self.navigation_requested.emit(1)
        else:
            super().keyPressEvent(event)

    def finish_polygon(self) -> None:
        if self.tool != "polygon":
            return
        points = tuple((point.x(), point.y()) for point in self._points)
        # Reject collinear clicks, including repeated double-click positions.
        if len(set(points)) >= 3 and any(
            abs((x - points[0][0]) * (points[1][1] - points[0][1])
                - (y - points[0][1]) * (points[1][0] - points[0][0])) > 0.001
            for x, y in points[2:]
        ):
            self.polygon_created.emit(points)
            self.cancel_drawing()

    def cancel_drawing(self) -> None:
        self._cancel_drag()
        self._points.clear()
        self._cursor = None
        self.update()


class MaskList(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QLabel) and isinstance(event, QMouseEvent) and event.type() in {
            QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease,
        }:
            position = watched.mapTo(self.viewport(), event.position())
            forwarded = QMouseEvent(event.type(), position, event.globalPosition(), event.button(), event.buttons(), event.modifiers())
            QApplication.sendEvent(self.viewport(), forwarded)
            return True
        return super().eventFilter(watched, event)


class AlphaSlider(QSlider):
    """Slider exposing alpha as a 0..1 value while moving in 0.1 steps."""
    def __init__(self, value: float = 0.0, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        super().setRange(0, 10)
        super().setSingleStep(1)
        self.setValue(value)

    def setValue(self, value: float | int) -> None:  # type: ignore[override]
        numeric = float(value)
        super().setValue(round(numeric * 10) if isinstance(value, float) else round(numeric))

    def value(self) -> int:  # type: ignore[override]
        return cast(int, super().value() / 10.0)


class MaskRow(QWidget):
    hovered = Signal(int)
    alpha_changed = Signal(int, float)
    context_requested = Signal(int, object)

    def __init__(self, index: int, mask: MaskRegion) -> None:
        super().__init__()
        self.index = index
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda position: self.context_requested.emit(self.index, self.mapToGlobal(position)))
        self.drag_handle = QLabel()
        self.drag_handle.setPixmap(QIcon(
            str(PROJECT_ROOT / "assets" / "icons" / "drag-handle.svg")
        ).pixmap(16, 20))
        self.drag_handle.setFixedSize(20, 24)
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_handle.setToolTip("Drag to reorder")
        self.drag_handle.setAccessibleName("Drag mask to reorder")
        swatch = QLabel()
        swatch.setFixedSize(20, 20)
        swatch.setStyleSheet(f"background-color: {mask.color}; border: 1px solid #555;")
        swatch.setToolTip(mask.color)
        self.alpha_input = AlphaSlider()
        self.alpha_input.setValue(float(mask.alpha))
        self.alpha_input.setAccessibleName(f"Mask {index + 1} alpha")
        self.alpha_input.setToolTip("Alpha: 0 = transparent, 1 = opaque (step 0.1)")
        stabilize_widget_size(self.alpha_input, minimum_width=88, vertical_padding=2)
        self.alpha_value_label = QLabel(f"{mask.alpha:.1f}")
        self.alpha_value_label.setAccessibleName(f"Mask {index + 1} alpha value")
        self.alpha_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.alpha_value_label.setMinimumWidth(30)
        self.alpha_input.valueChanged.connect(self._alpha_slider_changed)
        self.alpha_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.alpha_input.customContextMenuRequested.connect(lambda position: self.context_requested.emit(self.index, self.alpha_input.mapToGlobal(position)))
        self.name_label = QLabel(f"Mask {index + 1}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addWidget(self.drag_handle)
        layout.addWidget(swatch)
        layout.addWidget(self.name_label)
        layout.addStretch()
        layout.addWidget(self.alpha_value_label)
        layout.addWidget(self.alpha_input)

    def _alpha_slider_changed(self, _value: int) -> None:
        alpha = self.alpha_input.value()
        self.alpha_value_label.setText(f"{alpha:.1f}")
        self.alpha_changed.emit(self.index, alpha)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        self.hovered.emit(self.index)
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        self.hovered.emit(-1)
        super().leaveEvent(event)


class MaskPropertyDialog(QDialog):
    def __init__(self, mask: MaskRegion, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mask Properties")
        self.alpha_input = QDoubleSpinBox(); self.alpha_input.setRange(0, 1); self.alpha_input.setDecimals(2); self.alpha_input.setSingleStep(0.1); self.alpha_input.setValue(mask.alpha)
        self.fadeout_mode = QComboBox(); self.fadeout_mode.addItem("No fadeout", "none"); self.fadeout_mode.addItem("Fade from outside border", "outside"); self.fadeout_mode.addItem("Fade within border", "inside")
        self.fadeout_mode.setCurrentIndex(max(0, self.fadeout_mode.findData(mask.fadeout_mode)))
        self.destination_alpha = QDoubleSpinBox(); self.destination_alpha.setRange(0, 1); self.destination_alpha.setDecimals(2); self.destination_alpha.setSingleStep(0.1); self.destination_alpha.setValue(mask.destination_alpha)
        self.fadeout_width = QDoubleSpinBox(); self.fadeout_width.setRange(0, 10000); self.fadeout_width.setDecimals(1); self.fadeout_width.setSingleStep(1); self.fadeout_width.setValue(mask.fadeout_width)
        for control in (self.alpha_input, self.destination_alpha, self.fadeout_width):
            stabilize_widget_size(control, minimum_width=96, vertical_padding=2)
        stabilize_widget_size(self.fadeout_mode, minimum_width=180)
        form = QFormLayout(self); form.addRow("Alpha", self.alpha_input); form.addRow("Fadeout", self.fadeout_mode); form.addRow("Destination alpha", self.destination_alpha); form.addRow("Fadeout width (pixels)", self.fadeout_width)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); form.addRow(buttons)
        self.fadeout_mode.currentIndexChanged.connect(self._update_enabled); self._update_enabled()

    def _update_enabled(self, *_args: object) -> None:
        enabled = self.fadeout_mode.currentData() != "none"
        self.destination_alpha.setEnabled(enabled); self.fadeout_width.setEnabled(enabled)

    def values(self) -> tuple[float, str, float, float]:
        return (self.alpha_input.value(), str(self.fadeout_mode.currentData()), self.destination_alpha.value(), self.fadeout_width.value())


class FadeoutOptionsDialog(QDialog):
    """Configure fadeout defaults for masks drawn in the editor."""
    def __init__(self, mode: str, destination_alpha: float, width: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fadeout Options")
        self.fadeout_mode = QComboBox(); self.fadeout_mode.addItem("No fadeout", "none"); self.fadeout_mode.addItem("Fade from outside border", "outside"); self.fadeout_mode.addItem("Fade within border", "inside")
        self.fadeout_mode.setCurrentIndex(max(0, self.fadeout_mode.findData(mode)))
        self.destination_alpha = QDoubleSpinBox(); self.destination_alpha.setRange(0, 1); self.destination_alpha.setDecimals(2); self.destination_alpha.setSingleStep(0.1); self.destination_alpha.setValue(destination_alpha)
        self.fadeout_width = QDoubleSpinBox(); self.fadeout_width.setRange(0, 10000); self.fadeout_width.setDecimals(1); self.fadeout_width.setSingleStep(1); self.fadeout_width.setValue(width)
        stabilize_widget_size(self.fadeout_mode, minimum_width=180)
        for control in (self.destination_alpha, self.fadeout_width):
            stabilize_widget_size(control, minimum_width=96, vertical_padding=2)
        form = QFormLayout(self); form.addRow("Fadeout", self.fadeout_mode); form.addRow("Destination alpha", self.destination_alpha); form.addRow("Fadeout width (pixels)", self.fadeout_width)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); form.addRow(buttons)
        self.fadeout_mode.currentIndexChanged.connect(self._update_enabled); self._update_enabled()

    def _update_enabled(self, *_args: object) -> None:
        enabled = self.fadeout_mode.currentData() != "none"
        self.destination_alpha.setEnabled(enabled); self.fadeout_width.setEnabled(enabled)

    def values(self) -> tuple[str, float, float]:
        return (str(self.fadeout_mode.currentData()), self.destination_alpha.value(), self.fadeout_width.value())


class MaskEditorDialog(QDialog):
    def __init__(self, paths: list[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if not paths:
            raise ValueError("Select at least one image.")
        self.setWindowTitle("Mask Editor")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1160, 760)
        self.paths = list(paths)
        self.current_index = 0
        self.masks_by_path: dict[Path, list[MaskRegion]] = {path: [] for path in paths}
        self.base_alpha_by_path: dict[Path, float] = {path: 1.0 for path in paths}
        # Base alpha is a session setting: once the user changes it, retain
        # that value while moving between images.  Each image still keeps a
        # stored value for saving, but newly visited images inherit this one.
        self._base_alpha = 1.0
        self.dirty_paths: set[Path] = set()
        self.saved_paths: list[Path] = []
        self._hue = random.random()
        self.image_view = MaskImageView()
        self.image_view.polygon_created.connect(self._add_mask)
        self.image_view.mask_transformed.connect(self._transform_mask)
        self.image_view.navigation_requested.connect(self._navigate)
        self.image_label = QLabel()
        self.image_label.setTextFormat(Qt.TextFormat.PlainText)
        self.image_label.setContentsMargins(12, 4, 12, 4)

        toolbar = QWidget()
        tools = QVBoxLayout(toolbar)
        tools.setContentsMargins(0, 0, 0, 0)
        self.tool_group = QButtonGroup(self)
        self.pointer_button = self._tool_button("pointer.svg", "Pointer — select mask")
        self.move_button = self._tool_button("move.svg", "Move mask")
        self.rectangle_button = self._tool_button("rectangle.svg", "Rectangle")
        self.polygon_button = self._tool_button("polygon.svg", "Polygon")
        for button, tool in (
            (self.pointer_button, "pointer"), (self.move_button, "move"),
            (self.rectangle_button, "rectangle"), (self.polygon_button, "polygon"),
        ):
            self.tool_group.addButton(button)
            button.clicked.connect(lambda _checked=False, name=tool: self.image_view.set_tool(name))
            tools.addWidget(button)
        self.rectangle_button.setChecked(True)
        self.actual_opacity_button = self._tool_button("view.svg", "Preview actual alpha opacity")
        self.actual_opacity_button.toggled.connect(self.image_view.set_actual_opacity)
        tools.addWidget(self.actual_opacity_button)
        tools.addStretch()

        mask_panel = QWidget()
        mask_panel.setMinimumWidth(280)
        mask_layout = QVBoxLayout(mask_panel)
        mask_layout.setContentsMargins(0, 0, 0, 0)
        self.base_alpha_input = QDoubleSpinBox()
        self.base_alpha_input.setRange(0.0, 1.0)
        self.base_alpha_input.setDecimals(3)
        self.base_alpha_input.setSingleStep(0.05)
        self.base_alpha_input.setValue(1.0)
        self.base_alpha_input.setAccessibleName("Base alpha")
        self.base_alpha_input.setToolTip("Alpha for areas outside all masks")
        stabilize_widget_size(self.base_alpha_input, minimum_width=88, vertical_padding=2)
        self.base_alpha_input.valueChanged.connect(self._set_base_alpha)
        base_alpha_row = QHBoxLayout()
        base_alpha_row.addWidget(QLabel("Base alpha"))
        base_alpha_row.addStretch()
        base_alpha_row.addWidget(self.base_alpha_input)
        mask_layout.addLayout(base_alpha_row)
        self.new_mask_alpha_input = QDoubleSpinBox()
        self.new_mask_alpha_input.setRange(0.0, 1.0)
        self.new_mask_alpha_input.setDecimals(3)
        self.new_mask_alpha_input.setSingleStep(0.05)
        self.new_mask_alpha_input.setValue(0.0)
        self.new_mask_alpha_input.setAccessibleName("New mask alpha")
        self.new_mask_alpha_input.setToolTip("Alpha for newly drawn masks")
        stabilize_widget_size(self.new_mask_alpha_input, minimum_width=88, vertical_padding=2)
        new_mask_alpha_row = QHBoxLayout()
        new_mask_alpha_row.addWidget(QLabel("New mask alpha"))
        new_mask_alpha_row.addStretch()
        new_mask_alpha_row.addWidget(self.new_mask_alpha_input)
        mask_layout.addLayout(new_mask_alpha_row)
        self.new_mask_fadeout_enabled = False
        self.new_mask_fadeout_mode = "none"
        self.new_mask_destination_alpha = 0.0
        self.new_mask_fadeout_width = 0.0
        self.new_mask_fadeout_button = QToolButton()
        self.new_mask_fadeout_button.setIcon(QIcon(str(PROJECT_ROOT / "assets" / "icons" / "fadeout.svg")))
        self.new_mask_fadeout_button.setIconSize(QSize(22, 22))
        self.new_mask_fadeout_button.setFixedSize(34, 34)
        self.new_mask_fadeout_button.setCheckable(True)
        self.new_mask_fadeout_button.setAccessibleName("New mask fadeout")
        self.new_mask_fadeout_button.setToolTip("Enable fadeout for newly drawn masks (right-click to configure)")
        stabilize_checked_tool_button(self.new_mask_fadeout_button)
        self.new_mask_fadeout_button.toggled.connect(self._set_new_mask_fadeout_enabled)
        self.new_mask_fadeout_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.new_mask_fadeout_button.customContextMenuRequested.connect(self._edit_new_mask_properties)
        fadeout_row = QHBoxLayout()
        fadeout_row.addStretch(); fadeout_row.addWidget(self.new_mask_fadeout_button)
        mask_layout.addLayout(fadeout_row)
        mask_layout.addWidget(QLabel("Current masks · Alpha"))
        self.mask_list = MaskList()
        self.mask_list.customContextMenuRequested.connect(self._mask_context_menu)
        self.image_view.mask_selected.connect(self.mask_list.setCurrentRow)
        self.mask_list.setMinimumWidth(280)
        self.mask_list.model().rowsMoved.connect(self._masks_reordered)
        mask_layout.addWidget(self.mask_list, 1)
        self.delete_button = QPushButton("Delete Selected Mask")
        self.delete_button.clicked.connect(self._delete_mask)
        self.mask_list.currentRowChanged.connect(lambda row: self.delete_button.setEnabled(row >= 0))
        self.mask_list.currentRowChanged.connect(self.image_view.set_selected_mask)
        mask_layout.addWidget(self.delete_button)
        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)
        image_layout.addWidget(self.image_label)
        image_layout.addWidget(self.image_view, 1)
        panels = QHBoxLayout()
        panels.addWidget(toolbar)
        panels.addWidget(image_panel, 1)
        panels.addWidget(mask_panel)

        self.previous_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.previous_button.clicked.connect(lambda: self._navigate(-1))
        self.next_button.clicked.connect(lambda: self._navigate(1))
        self.save_button = QPushButton("Finish")
        self.save_button.setAccessibleName("Finish")
        self.save_button.clicked.connect(self._finish)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.previous_button)
        buttons.addWidget(self.next_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.save_button)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        layout = QVBoxLayout(self)
        layout.addLayout(panels, 1)
        layout.addLayout(buttons)
        self._load_current()

    def _tool_button(self, filename: str, label: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(QIcon(str(PROJECT_ROOT / "assets" / "icons" / filename)))
        button.setIconSize(QSize(26, 26))
        button.setFixedSize(42, 42)
        button.setCheckable(True)
        button.setToolTip(label)
        button.setAccessibleName(label)
        stabilize_checked_tool_button(button)
        return button

    @property
    def current_path(self) -> Path:
        return self.paths[self.current_index]

    @property
    def current_masks(self) -> list[MaskRegion]:
        return self.masks_by_path[self.current_path]

    def _load_current(self) -> None:
        self.image_label.setText(f"{self.current_index + 1} / {len(self.paths)} — {self.current_path.name}")
        self.image_label.setToolTip(str(self.current_path))
        try:
            image = load_mask_image(self.current_path)
        except (OSError, ValueError) as exc:
            image = None
            self.image_label.setText(f"Could not load {self.current_path.name}: {exc}")
        self.image_view.set_image(image, self.current_masks)
        # Carry the current setting across image navigation instead of
        # resetting to a per-image default.
        base_alpha = self._base_alpha
        self.base_alpha_by_path[self.current_path] = base_alpha
        self.base_alpha_input.blockSignals(True)
        self.base_alpha_input.setValue(base_alpha)
        self.base_alpha_input.blockSignals(False)
        self.image_view.set_base_alpha(base_alpha)
        self.previous_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index < len(self.paths) - 1)
        self._rebuild_mask_list()
        self._update_save_button()

    def _navigate(self, offset: int) -> None:
        index = self.current_index + offset
        if 0 <= index < len(self.paths):
            self.current_index = index
            self._load_current()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Left:
            self._navigate(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self._navigate(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _add_mask(self, points: tuple[tuple[float, float], ...]) -> None:
        # Spread consecutive hues around the wheel, with a random starting color.
        self._hue = (self._hue + 0.61803398875) % 1.0
        color = QColor.fromHsvF(self._hue, 0.72, 0.92).name()
        self.current_masks.insert(0, MaskRegion(
            points, alpha=self.new_mask_alpha_input.value(), color=color,
            fadeout_mode=self.new_mask_fadeout_mode if self.new_mask_fadeout_enabled else "none",
            destination_alpha=self.new_mask_destination_alpha,
            fadeout_width=self.new_mask_fadeout_width,
        ))
        self._changed()
        self._rebuild_mask_list()
        self.mask_list.setCurrentRow(0)

    def _set_new_mask_fadeout_enabled(self, enabled: bool) -> None:
        self.new_mask_fadeout_enabled = enabled

    def _edit_new_mask_properties(self, _position) -> None:
        dialog = FadeoutOptionsDialog(
            self.new_mask_fadeout_mode, self.new_mask_destination_alpha,
            self.new_mask_fadeout_width, self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        mode, destination, width = dialog.values()
        self.new_mask_fadeout_mode = mode
        self.new_mask_destination_alpha = destination
        self.new_mask_fadeout_width = width
        self.new_mask_fadeout_button.setChecked(mode != "none")

    def _set_base_alpha(self, alpha: float) -> None:
        self._base_alpha = alpha
        self.base_alpha_by_path[self.current_path] = alpha
        self.image_view.set_base_alpha(alpha)
        self._changed()

    def _masks_reordered(self, *_args) -> None:
        self.current_masks[:] = [
            self.current_masks[self.mask_list.item(index).data(Qt.ItemDataRole.UserRole)]
            for index in range(self.mask_list.count())
        ]
        for index in range(self.mask_list.count()):
            item = self.mask_list.item(index)
            item.setData(Qt.ItemDataRole.UserRole, index)
            row = self.mask_list.itemWidget(item)
            if isinstance(row, MaskRow):
                row.index = index
                row.name_label.setText(f"Mask {index + 1}")
                row.alpha_input.setAccessibleName(f"Mask {index + 1} alpha")
        self.image_view.set_hovered_mask(-1)
        self.image_view.set_selected_mask(self.mask_list.currentRow())
        self._changed()

    def _transform_mask(self, index: int, mask: MaskRegion) -> None:
        self.current_masks[index] = mask
        self._changed()

    def _set_alpha(self, index: int, alpha: float) -> None:
        self.current_masks[index] = replace(self.current_masks[index], alpha=alpha)
        self._changed()

    def _mask_context_menu(self, position) -> None:
        item = self.mask_list.itemAt(position)
        if item is None:
            return
        index = self.mask_list.row(item)
        self.mask_list.setCurrentRow(index)
        self._show_mask_menu(index, self.mask_list.viewport().mapToGlobal(position))

    def _show_mask_menu(self, index: int, global_position) -> None:
        menu = QMenu(self.mask_list)
        properties = menu.addAction("Properties...")
        properties.triggered.connect(lambda: self._edit_mask_properties(index))
        menu.exec(global_position)

    def _edit_mask_properties(self, index: int) -> None:
        if not 0 <= index < len(self.current_masks):
            return
        dialog = MaskPropertyDialog(self.current_masks[index], self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        alpha, mode, destination, width = dialog.values()
        self.current_masks[index] = replace(self.current_masks[index], alpha=alpha, fadeout_mode=mode, destination_alpha=destination, fadeout_width=width)
        self._changed()
        self._rebuild_mask_list()
        self.mask_list.setCurrentRow(index)

    def _delete_mask(self) -> None:
        index = self.mask_list.currentRow()
        if 0 <= index < len(self.current_masks):
            del self.current_masks[index]
            self._changed()
            self._rebuild_mask_list()

    def _changed(self) -> None:
        self.dirty_paths.add(self.current_path)
        self.image_view.set_masks(self.current_masks)
        self._update_save_button()

    def _update_save_button(self) -> None:
        self.save_button.setEnabled(bool(self.dirty_paths))

    def _rebuild_mask_list(self) -> None:
        self.image_view.set_hovered_mask(-1)
        self.mask_list.clear()
        for index, mask in enumerate(self.current_masks):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            row = MaskRow(index, mask)
            row.context_requested.connect(self._show_mask_menu)
            row.drag_handle.installEventFilter(self.mask_list)
            row.hovered.connect(self.image_view.set_hovered_mask)
            row.alpha_changed.connect(self._set_alpha)
            item.setSizeHint(row.sizeHint())
            self.mask_list.addItem(item)
            self.mask_list.setItemWidget(item, row)
        self.delete_button.setEnabled(False)

    def _save_changes(self) -> None:
        failures: list[str] = []
        dirty = [path for path in self.paths if path in self.dirty_paths]
        progress = QProgressDialog("", "Cancel", 0, len(dirty), self)
        progress.setWindowTitle("Saving Masks")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        # Match the wider progress dialogs used by other batch operations;
        # the label above the bar is updated with the file currently written.
        progress.setFixedWidth(640)
        label = progress.findChild(QLabel)
        if label is not None:
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
        progress.setAutoClose(True)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()
        for index, path in enumerate(dirty, 1):
            if progress.wasCanceled():
                break
            progress.setLabelText(path.name)
            QApplication.processEvents()
            try:
                save_masks(path, self.masks_by_path[path], self.base_alpha_by_path[path])
            except (OSError, ValueError) as exc:
                failures.append(f"{path.name}: {exc}")
                continue
            self.dirty_paths.remove(path)
            if path not in self.saved_paths:
                self.saved_paths.append(path)
            progress.setValue(index)
            QApplication.processEvents()
        progress.close()
        self._update_save_button()
        if failures:
            QMessageBox.warning(self, "Some Masks Could Not Be Saved", "\n".join(failures))
        else:
            self.image_label.setText(
                f"{self.current_index + 1} / {len(self.paths)} — "
                f"{self.current_path.name} — Saved changes"
            )

    @override
    def reject(self) -> None:
        if self.dirty_paths:
            answer = QMessageBox.question(
                self, "Unsaved Masks", "Save mask changes before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save:
                self._save_changes()
                if self.dirty_paths:
                    return
        super().reject()

    def _finish(self) -> None:
        self._save_changes()
        if not self.dirty_paths:
            self.accept()
