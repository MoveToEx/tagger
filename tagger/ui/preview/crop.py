from __future__ import annotations

from typing import override

from PIL import Image, ImageQt
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPaintEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from tagger.crop_storage import CropBox


class CropImageView(QWidget):
    crop_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 260)
        self.setMouseTracking(True)
        self._pixmap = QPixmap()
        self.crop_box: CropBox = (0, 0, 0, 0)
        self.aspect_ratio: float | None = None
        self._drag_mode = ""
        self._drag_start = QPointF()
        self._anchor = QPointF()
        self._original = self.crop_box
        tile = QPixmap(24, 24)
        tile.fill(QColor("#eeeeee"))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 12, 12, QColor("#c8c8c8"))
        painter.fillRect(12, 12, 12, 12, QColor("#c8c8c8"))
        painter.end()
        self._checker = QBrush(tile)

    def set_image(
        self, image: Image.Image | None, box: CropBox | None = None,
        aspect_ratio: float | None = None,
    ) -> None:
        self._drag_mode = ""
        self._pixmap = ImageQt.toqpixmap(image.convert("RGBA")) if image else QPixmap()
        self.crop_box = box or (0, 0, self._pixmap.width(), self._pixmap.height())
        self.aspect_ratio = aspect_ratio
        self.update()

    def image_rect(self) -> QRectF:
        if self._pixmap.isNull():
            return QRectF()
        scale = min(
            (self.width() - 24) / self._pixmap.width(),
            (self.height() - 24) / self._pixmap.height(),
        )
        width, height = self._pixmap.width() * scale, self._pixmap.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def selection_rect(self) -> QRectF:
        target = self.image_rect()
        if target.isEmpty():
            return QRectF()
        scale = target.width() / self._pixmap.width()
        left, top, right, bottom = self.crop_box
        return QRectF(
            target.left() + left * scale, target.top() + top * scale,
            (right - left) * scale, (bottom - top) * scale,
        )

    def set_aspect_ratio(self, ratio: float | None) -> None:
        self.aspect_ratio = ratio
        if self._pixmap.isNull() or ratio is None:
            return
        width = min(float(self._pixmap.width()), self._pixmap.height() * ratio)
        height = width / ratio
        left, top = (self._pixmap.width() - width) / 2, (self._pixmap.height() - height) / 2
        self._set_rect(QRectF(left, top, width, height))

    def _set_rect(self, rect: QRectF) -> None:
        width, height = self._pixmap.width(), self._pixmap.height()
        crop_width = max(1, min(width, round(rect.width())))
        crop_height = max(1, min(height, round(rect.height())))
        left = max(0, min(width - crop_width, round(rect.left())))
        top = max(0, min(height - crop_height, round(rect.top())))
        box = (left, top, left + crop_width, top + crop_height)
        if box != self.crop_box:
            self.crop_box = box
            self.crop_changed.emit(box)
            self.update()

    def _handles(self) -> dict[str, QPointF]:
        rect = self.selection_rect()
        return {
            "nw": rect.topLeft(), "ne": rect.topRight(),
            "sw": rect.bottomLeft(), "se": rect.bottomRight(),
        }

    def _hit_handle(self, position: QPointF) -> str:
        for name, point in self._handles().items():
            if abs(point.x() - position.x()) <= 8 and abs(point.y() - position.y()) <= 8:
                return name
        return ""

    def _image_point(self, position: QPointF) -> QPointF:
        target = self.image_rect()
        scale = self._pixmap.width() / target.width()
        return QPointF(
            max(0, min(self._pixmap.width(), (position.x() - target.left()) * scale)),
            max(0, min(self._pixmap.height(), (position.y() - target.top()) * scale)),
        )

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if self._pixmap.isNull():
            return
        target = self.image_rect()
        selection = self.selection_rect()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(target, self._checker)
        painter.setOpacity(0.25)
        source = QRectF(self._pixmap.rect())
        painter.drawPixmap(target, self._pixmap, source)
        painter.setOpacity(1.0)
        painter.save()
        painter.setClipRect(selection)
        # Clear the faint image first so intrinsic alpha is preserved in the crop.
        painter.fillRect(target, self._checker)
        painter.drawPixmap(target, self._pixmap, source)
        painter.restore()
        painter.setPen(QPen(QColor("#202020"), 2))
        painter.drawRect(selection)
        painter.setPen(QPen(QColor("white"), 1, Qt.PenStyle.DashLine))
        painter.drawRect(selection)
        painter.setPen(QPen(QColor("#202020"), 1))
        painter.setBrush(QColor("white"))
        for point in self._handles().values():
            painter.drawRect(QRectF(point.x() - 4, point.y() - 4, 8, 8))

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._pixmap.isNull():
            super().mousePressEvent(event)
            return
        handle = self._hit_handle(event.position())
        if not handle and not self.image_rect().contains(event.position()):
            return
        self._drag_start = self._image_point(event.position())
        self._original = self.crop_box
        left, top, right, bottom = self.crop_box
        if handle:
            self._drag_mode = "resize"
            self._anchor = QPointF(left if "e" in handle else right, top if "s" in handle else bottom)
        elif self.selection_rect().contains(event.position()):
            self._drag_mode = "move"
        else:
            self._drag_mode = "resize"
            self._anchor = self._drag_start
        event.accept()

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pixmap.isNull():
            return
        if not self._drag_mode:
            handle = self._hit_handle(event.position())
            if handle:
                cursor = Qt.CursorShape.SizeFDiagCursor if handle in {"nw", "se"} else Qt.CursorShape.SizeBDiagCursor
            elif self.selection_rect().contains(event.position()):
                cursor = Qt.CursorShape.SizeAllCursor
            else:
                cursor = Qt.CursorShape.CrossCursor
            self.setCursor(cursor)
            return
        point = self._image_point(event.position())
        if self._drag_mode == "move":
            left, top, right, bottom = self._original
            delta = point - self._drag_start
            x = max(0, min(self._pixmap.width() - (right - left), left + delta.x()))
            y = max(0, min(self._pixmap.height() - (bottom - top), top + delta.y()))
            self._set_rect(QRectF(x, y, right - left, bottom - top))
        else:
            delta = point - self._anchor
            sx, sy = (1 if delta.x() >= 0 else -1), (1 if delta.y() >= 0 else -1)
            max_width = self._pixmap.width() - self._anchor.x() if sx > 0 else self._anchor.x()
            max_height = self._pixmap.height() - self._anchor.y() if sy > 0 else self._anchor.y()
            width, height = abs(delta.x()), abs(delta.y())
            if self.aspect_ratio is not None:
                width = min(max(width, height * self.aspect_ratio), max_width, max_height * self.aspect_ratio)
                height = width / self.aspect_ratio
            end = self._anchor + QPointF(sx * width, sy * height)
            self._set_rect(QRectF(self._anchor, end).normalized())
        event.accept()

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_mode:
            self.mouseMoveEvent(event)
            self._drag_mode = ""
            event.accept()
        else:
            super().mouseReleaseEvent(event)
