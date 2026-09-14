from __future__ import annotations

from typing import override

from PySide6.QtCore import (
    QEvent,
    QLineF,
    QObject,
    QPoint,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QLabel, QScrollArea

from tagger.image_processing import (
    ALPHA_DISPLAY_FILTERS,
    apply_alpha_display_filter,
)
from tagger.ui.preview.config import (
    SCROLLING_BEHAVIORS,
    SCROLL_NAVIGATE_AT_END,
    SCROLL_NAVIGATE_WHEN_FITTED,
    SCROLL_PAN,
    SCROLL_ZOOM,
)


class _ImageCanvas(QLabel):
    """Paint only the exposed portion instead of storing a scaled pixmap."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._source_pixmap: QPixmap | None = None
        self._lower_pixmap: QPixmap | None = None
        self._divider_y: int | None = None
        self._grid_size: int | None = None
        self._grid_selection: tuple[int, int, int, int] | None = None
        self.setMouseTracking(True)

    def set_grid_size(self, size: int | None) -> None:
        self._grid_size = size if size is not None and size > 0 else None
        self._grid_selection = None
        self.update()

    def set_grid_selection(
        self, start: tuple[int, int], end: tuple[int, int]
    ) -> tuple[int, int]:
        left, right = sorted((start[0], end[0]))
        top, bottom = sorted((start[1], end[1]))
        self._grid_selection = (left, top, right + 1, bottom + 1)
        self.update()
        return right - left + 1, bottom - top + 1

    def clear_grid_selection(self) -> None:
        self._grid_selection = None
        self.update()

    def _source_draw_rect(self) -> QRectF:
        if self._source_pixmap is None:
            return QRectF()
        source_size = self._source_pixmap.size()
        scale = min(
            self.width() / source_size.width(),
            self.height() / source_size.height(),
        )
        draw_width = source_size.width() * scale
        draw_height = source_size.height() * scale
        return QRectF(
            (self.width() - draw_width) / 2,
            (self.height() - draw_height) / 2,
            draw_width,
            draw_height,
        )

    def grid_cell_at(
        self, position: QPoint, *, clamp: bool = False
    ) -> tuple[int, int] | None:
        if self._source_pixmap is None or self._grid_size is None:
            return None
        draw_rect = self._source_draw_rect()
        if not clamp and not draw_rect.contains(position):
            return None
        x = max(draw_rect.left(), min(draw_rect.right(), position.x()))
        y = max(draw_rect.top(), min(draw_rect.bottom(), position.y()))
        source_width = self._source_pixmap.width()
        source_height = self._source_pixmap.height()
        source_x = min(
            source_width - 1,
            int((x - draw_rect.left()) * source_width / draw_rect.width()),
        )
        source_y = min(
            source_height - 1,
            int((y - draw_rect.top()) * source_height / draw_rect.height()),
        )
        return source_x // self._grid_size, source_y // self._grid_size

    def set_source_pixmap(self, pixmap: QPixmap, size: QSize) -> None:
        self._source_pixmap = pixmap
        self._lower_pixmap = None
        self._divider_y = None
        self.setMinimumSize(0, 0)
        self.setText("")
        self.resize(size)
        self.update()

    def set_comparison_pixmaps(
        self, upper: QPixmap, lower: QPixmap, size: QSize
    ) -> None:
        self._source_pixmap = upper
        self._lower_pixmap = lower
        if self._divider_y is None:
            self._divider_y = size.height() // 2
        self.setMinimumSize(0, 0)
        self.setText("")
        self.resize(size)
        self._divider_y = max(0, min(self.height(), self._divider_y))
        self.update()

    @override
    def clear(self) -> None:
        self._source_pixmap = None
        self._lower_pixmap = None
        self._divider_y = None
        self._grid_selection = None
        self.setMinimumSize(240, 180)
        super().clear()

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self._source_pixmap is None or self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        source_size = self._source_pixmap.size()
        draw_rect = self._source_draw_rect()
        scale = draw_rect.width() / source_size.width()
        if self._lower_pixmap is not None:
            painter.drawPixmap(
                draw_rect,
                self._lower_pixmap,
                QRectF(self._lower_pixmap.rect()),
            )
            painter.save()
            divider_y = self._divider_y if self._divider_y is not None else 0
            painter.setClipRect(QRectF(0, 0, self.width(), divider_y))
            painter.drawPixmap(
                draw_rect,
                self._source_pixmap,
                QRectF(self._source_pixmap.rect()),
            )
            painter.restore()
            painter.setPen(self.palette().highlight().color())
            painter.drawLine(0, divider_y, self.width(), divider_y)
        else:
            painter.drawPixmap(
                draw_rect,
                self._source_pixmap,
                QRectF(self._source_pixmap.rect()),
            )
        if self._grid_size is not None:
            grid_size = self._grid_size
            selection_rect = QRectF()
            selection_size: tuple[int, int] | None = None
            if self._grid_selection is not None:
                left, top, right, bottom = self._grid_selection
                selection_rect = QRectF(
                    draw_rect.left() + left * grid_size * scale,
                    draw_rect.top() + top * grid_size * scale,
                    min(right * grid_size, source_size.width()) * scale
                    - left * grid_size * scale,
                    min(bottom * grid_size, source_size.height()) * scale
                    - top * grid_size * scale,
                )
                selection_size = right - left, bottom - top
                painter.fillRect(selection_rect, QColor(47, 111, 237, 64))
            lines: list[QLineF] = []
            for x in range(grid_size, source_size.width(), grid_size):
                draw_x = draw_rect.left() + x * scale
                lines.append(
                    QLineF(draw_x, draw_rect.top(), draw_x, draw_rect.bottom())
                )
            for y in range(grid_size, source_size.height(), grid_size):
                draw_y = draw_rect.top() + y * scale
                lines.append(
                    QLineF(draw_rect.left(), draw_y, draw_rect.right(), draw_y)
                )
            for color, width in (
                (QColor(0, 0, 0, 180), 2),
                (QColor(255, 255, 255, 210), 1),
            ):
                pen = QPen(color, width)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.drawLines(lines)
            if selection_size is not None:
                selection_pen = QPen(QColor("#2f6fed"), 2)
                selection_pen.setCosmetic(True)
                painter.setPen(selection_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(selection_rect)
                text = f"{selection_size[0]} x {selection_size[1]} grids"
                text_rect = painter.fontMetrics().boundingRect(text)
                badge = QRectF(
                    selection_rect.left() + 5,
                    selection_rect.top() + 5,
                    text_rect.width() + 12,
                    text_rect.height() + 8,
                )
                if badge.right() > draw_rect.right():
                    badge.moveRight(draw_rect.right() - 3)
                if badge.bottom() > draw_rect.bottom():
                    badge.moveBottom(draw_rect.bottom() - 3)
                painter.fillRect(badge, QColor(16, 24, 40, 220))
                painter.setPen(QColor("white"))
                painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._lower_pixmap is not None:
            self._divider_y = max(
                0, min(self.height(), round(event.position().y()))
            )
            self.update()
        super().mouseMoveEvent(event)


class ImageView(QScrollArea):
    fit_to_window_changed = Signal(bool)
    navigation_requested = Signal(int)
    grid_measurement_changed = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        self._label = _ImageCanvas("Open a folder to begin")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumSize(240, 180)
        self._label.setStyleSheet("QLabel { color: #667085; background: #f2f4f7; }")
        self.setWidget(self._label)

        self._pixmap: QPixmap | None = None
        self._source_image: QImage | None = None
        self._comparison_image: QImage | None = None
        self._comparison_pixmap: QPixmap | None = None
        self._alpha_mode = "keep"
        self._fit_to_window = True
        self._scrolling_behavior = SCROLL_PAN
        self._zoom = 1.0
        self._ctrl_wheel_zoom_enabled = True
        self._grid_measurement_enabled = False
        self._grid_drag_start: tuple[int, int] | None = None
        self._drag_start: QPoint | None = None
        self._drag_scroll_start: tuple[int, int] | None = None
        self._label.installEventFilter(self)
        self.viewport().installEventFilter(self)

    @property
    def fit_to_window(self) -> bool:
        return self._fit_to_window

    def clear_image(self, message: str = "No image selected") -> None:
        self._end_drag()
        self._pixmap = None
        self._source_image = None
        self._comparison_image = None
        self._comparison_pixmap = None
        self._label.clear()
        self._label.setText(message)
        self._label.resize(self.viewport().size())

    def set_image(self, image: QImage) -> None:
        self.clear_grid_measurement()
        self._source_image = image
        self._comparison_image = None
        self._comparison_pixmap = None
        self._pixmap = QPixmap.fromImage(
            apply_alpha_display_filter(image, self._alpha_mode)
        )
        self._label.setText("")
        self._update_pixmap()

    def set_grid_size(self, size: int | None) -> None:
        self._label.set_grid_size(size)
        self._grid_drag_start = None
        self.grid_measurement_changed.emit(0, 0)

    def set_grid_measurement_enabled(self, enabled: bool) -> None:
        self._grid_measurement_enabled = bool(enabled)
        if enabled:
            self._label.setCursor(Qt.CursorShape.CrossCursor)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._label.unsetCursor()
            self.viewport().unsetCursor()
            self._grid_drag_start = None

    def set_ctrl_wheel_zoom_enabled(self, enabled: bool) -> None:
        self._ctrl_wheel_zoom_enabled = bool(enabled)

    def clear_grid_measurement(self) -> None:
        self._grid_drag_start = None
        self._label.clear_grid_selection()
        self.grid_measurement_changed.emit(0, 0)

    def set_comparison_images(self, original: QImage, decoded: QImage) -> None:
        self._source_image = decoded
        self._comparison_image = original
        self._pixmap = QPixmap.fromImage(
            apply_alpha_display_filter(decoded, self._alpha_mode)
        )
        self._comparison_pixmap = QPixmap.fromImage(
            apply_alpha_display_filter(original, self._alpha_mode)
        )
        self._label.setText("")
        self._update_pixmap()

    @property
    def alpha_mode(self) -> str:
        return self._alpha_mode

    def set_alpha_mode(self, mode: str) -> None:
        mode = mode.casefold()
        if mode not in ALPHA_DISPLAY_FILTERS:
            mode = "keep"
        if self._alpha_mode == mode:
            return
        self._alpha_mode = mode
        if self._source_image is not None:
            self._pixmap = QPixmap.fromImage(
                apply_alpha_display_filter(self._source_image, mode)
            )
            if self._comparison_image is not None:
                self._comparison_pixmap = QPixmap.fromImage(
                    apply_alpha_display_filter(self._comparison_image, mode)
                )
            self._update_pixmap()

    def set_fit_to_window(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._fit_to_window != enabled:
            self._fit_to_window = enabled
            self.fit_to_window_changed.emit(enabled)
        if enabled:
            self._zoom = 1.0
        self._update_pixmap()

    def set_scrolling_behavior(self, behavior: str) -> None:
        self._scrolling_behavior = (
            behavior if behavior in SCROLLING_BEHAVIORS else SCROLL_PAN
        )

    def actual_size(self) -> None:
        self._set_manual_zoom()
        self._zoom = 1.0
        self._update_pixmap()

    def zoom_in(self) -> None:
        self._set_manual_zoom()
        self._zoom = min(8.0, self._zoom * 1.25)
        self._update_pixmap()

    def zoom_out(self) -> None:
        self._set_manual_zoom()
        self._zoom = max(0.1, self._zoom / 1.25)
        self._update_pixmap()

    def _set_manual_zoom(self) -> None:
        if self._fit_to_window:
            self._fit_to_window = False
            self.fit_to_window_changed.emit(False)

    def _zoom_at(self, position: QPoint, factor: float) -> None:
        if self._pixmap is None:
            return
        old_size = self._label.size()
        if old_size.width() <= 0 or old_size.height() <= 0:
            return

        label_position = self._label.mapFrom(self.viewport(), position)
        image_x = max(0.0, min(1.0, label_position.x() / old_size.width()))
        image_y = max(0.0, min(1.0, label_position.y() / old_size.height()))
        old_zoom = self._zoom
        self._set_manual_zoom()
        self._zoom = max(0.1, min(8.0, old_zoom * factor))
        if self._zoom == old_zoom:
            return
        self._update_pixmap()

        new_position = QPoint(
            round(image_x * self._label.width()),
            round(image_y * self._label.height()),
        )
        old_origin = self._label.mapTo(self.viewport(), QPoint(0, 0))
        desired_origin = position - new_position
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value()
            + old_origin.x()
            - desired_origin.x()
        )
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value()
            + old_origin.y()
            - desired_origin.y()
        )

    def _handle_wheel(self, event: QWheelEvent, position: QPoint) -> bool:
        vertical_delta = event.angleDelta().y() or event.pixelDelta().y()
        horizontal_delta = event.angleDelta().x() or event.pixelDelta().x()
        use_horizontal = bool(
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ) or abs(horizontal_delta) > abs(vertical_delta)
        delta = (
            horizontal_delta or vertical_delta
            if use_horizontal
            else vertical_delta or horizontal_delta
        )
        if (
            self._scrolling_behavior == SCROLL_ZOOM
            or (
                self._ctrl_wheel_zoom_enabled
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            )
        ):
            if delta != 0:
                self._zoom_at(position, 1.25 if delta > 0 else 0.8)
            event.accept()
            return True

        if (
            self._scrolling_behavior == SCROLL_PAN
            or (
                self._scrolling_behavior == SCROLL_NAVIGATE_WHEN_FITTED
                and not self._fit_to_window
            )
            or delta == 0
        ):
            return False
        if self._scrolling_behavior == SCROLL_NAVIGATE_AT_END:
            scrollbar = (
                self.horizontalScrollBar()
                if use_horizontal
                else self.verticalScrollBar()
            )
            if delta > 0 and scrollbar.value() > scrollbar.minimum():
                return False
            if delta < 0 and scrollbar.value() < scrollbar.maximum():
                return False
        self.navigation_requested.emit(-1 if delta > 0 else 1)
        event.accept()
        return True

    def _event_position(self, event: QMouseEvent) -> QPoint:
        position = event.globalPosition().toPoint()
        return self.viewport().mapFromGlobal(position)

    def _end_drag(self) -> None:
        self._drag_start = None
        self._drag_scroll_start = None
        if self._grid_measurement_enabled:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().unsetCursor()

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        position = self.viewport().mapFrom(
            self, event.position().toPoint()
        )
        if self._handle_wheel(event, position):
            return
        super().wheelEvent(event)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched not in (self._label, self.viewport()):
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.Wheel:
            wheel_event = event
            if isinstance(wheel_event, QWheelEvent):
                if watched is self._label:
                    position = self._label.mapTo(
                        self.viewport(), wheel_event.position().toPoint()
                    )
                else:
                    position = wheel_event.position().toPoint()
                return self._handle_wheel(wheel_event, position)
        if event.type() == QEvent.Type.MouseButtonPress:
            mouse_event = event
            if (
                isinstance(mouse_event, QMouseEvent)
                and mouse_event.button() == Qt.MouseButton.LeftButton
                and self._grid_measurement_enabled
            ):
                position = self._label.mapFromGlobal(
                    mouse_event.globalPosition().toPoint()
                )
                cell = self._label.grid_cell_at(position)
                if cell is None:
                    self.clear_grid_measurement()
                else:
                    self._grid_drag_start = cell
                    width, height = self._label.set_grid_selection(cell, cell)
                    self.grid_measurement_changed.emit(width, height)
                return True
            if (
                isinstance(mouse_event, QMouseEvent)
                and mouse_event.button() == Qt.MouseButton.LeftButton
                and self._pixmap is not None
            ):
                self._drag_start = self._event_position(mouse_event)
                self._drag_scroll_start = (
                    self.horizontalScrollBar().value(),
                    self.verticalScrollBar().value(),
                )
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
        elif event.type() == QEvent.Type.MouseMove:
            mouse_event = event
            if (
                isinstance(mouse_event, QMouseEvent)
                and self._grid_measurement_enabled
                and self._grid_drag_start is not None
            ):
                position = self._label.mapFromGlobal(
                    mouse_event.globalPosition().toPoint()
                )
                cell = self._label.grid_cell_at(position, clamp=True)
                if cell is not None:
                    width, height = self._label.set_grid_selection(
                        self._grid_drag_start, cell
                    )
                    self.grid_measurement_changed.emit(width, height)
                return True
            if (
                isinstance(mouse_event, QMouseEvent)
                and self._drag_start is not None
                and self._drag_scroll_start is not None
            ):
                position = self._event_position(mouse_event)
                delta = position - self._drag_start
                self.horizontalScrollBar().setValue(
                    self._drag_scroll_start[0] - delta.x()
                )
                self.verticalScrollBar().setValue(
                    self._drag_scroll_start[1] - delta.y()
                )
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            mouse_event = event
            if (
                isinstance(mouse_event, QMouseEvent)
                and mouse_event.button() == Qt.MouseButton.LeftButton
                and self._grid_measurement_enabled
            ):
                self._grid_drag_start = None
                return True
            if (
                isinstance(mouse_event, QMouseEvent)
                and mouse_event.button() == Qt.MouseButton.LeftButton
                and self._drag_start is not None
            ):
                self._end_drag()
                return True
        return super().eventFilter(watched, event)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._fit_to_window:
            self._update_pixmap()
        elif self._pixmap is None:
            self._label.resize(self.viewport().size())

    def _update_pixmap(self) -> None:
        if self._pixmap is None:
            return
        if self._fit_to_window:
            target = self.viewport().size()
            size = self._pixmap.size().scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        else:
            size = self._pixmap.size() * self._zoom
        if self._comparison_pixmap is None:
            self._label.set_source_pixmap(self._pixmap, size)
        else:
            self._label.set_comparison_pixmaps(
                self._pixmap, self._comparison_pixmap, size
            )
