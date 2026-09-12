from __future__ import annotations

from typing import override

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QImage,
    QMouseEvent,
    QPaintEvent,
    QPainter,
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

    def set_source_pixmap(self, pixmap: QPixmap, size: QSize) -> None:
        self._source_pixmap = pixmap
        self.setMinimumSize(0, 0)
        self.setText("")
        self.resize(size)
        self.update()

    @override
    def clear(self) -> None:
        self._source_pixmap = None
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
        scale = min(
            self.width() / source_size.width(),
            self.height() / source_size.height(),
        )
        draw_width = source_size.width() * scale
        draw_height = source_size.height() * scale
        draw_rect = QRectF(
            (self.width() - draw_width) / 2,
            (self.height() - draw_height) / 2,
            draw_width,
            draw_height,
        )
        painter.drawPixmap(
            draw_rect,
            self._source_pixmap,
            QRectF(self._source_pixmap.rect()),
        )


class ImageView(QScrollArea):
    fit_to_window_changed = Signal(bool)
    navigation_requested = Signal(int)

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
        self._alpha_mode = "keep"
        self._fit_to_window = True
        self._scrolling_behavior = SCROLL_PAN
        self._zoom = 1.0
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
        self._label.clear()
        self._label.setText(message)
        self._label.resize(self.viewport().size())

    def set_image(self, image: QImage) -> None:
        self._source_image = image
        self._pixmap = QPixmap.fromImage(
            apply_alpha_display_filter(image, self._alpha_mode)
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
            or event.modifiers() & Qt.KeyboardModifier.ControlModifier
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
        self._label.set_source_pixmap(self._pixmap, size)
