from __future__ import annotations

from typing import override

from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QProxyStyle,
    QSizePolicy,
    QStyle,
    QStyleOption,
    QStyleOptionComplex,
    QStyleOptionSpinBox,
    QToolButton,
    QWidget,
)


DEFAULT_HORIZONTAL_PADDING = 8


class _StableSpinBoxStyle(QProxyStyle):
    @override
    def drawComplexControl(
        self,
        control: QStyle.ComplexControl,
        option: QStyleOptionComplex,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        if (
            control == QStyle.ComplexControl.CC_SpinBox
            and isinstance(option, QStyleOptionSpinBox)
        ):
            option = QStyleOptionSpinBox(option)
            option.state &= ~QStyle.StateFlag.State_MouseOver
            if not option.state & QStyle.StateFlag.State_Sunken:
                option.activeSubControls = QStyle.SubControl.SC_None
        super().drawComplexControl(control, option, painter, widget)


class _StableCheckedToolButtonStyle(QProxyStyle):
    @override
    def pixelMetric(
        self,
        metric: QStyle.PixelMetric,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> int:
        if (
            metric
            in {
                QStyle.PixelMetric.PM_ButtonShiftHorizontal,
                QStyle.PixelMetric.PM_ButtonShiftVertical,
            }
            and isinstance(widget, QToolButton)
            and widget.isChecked()
            and not widget.isDown()
        ):
            return 0
        return super().pixelMetric(metric, option, widget)


def stabilize_checked_tool_button(button: QToolButton) -> None:
    stable_style = _StableCheckedToolButtonStyle(button.style().objectName())
    stable_style.setParent(button)
    button.setStyle(stable_style)


def stabilize_widget_size(
    widget: QWidget,
    *,
    minimum_width: int = 0,
    horizontal_padding: int = DEFAULT_HORIZONTAL_PADDING,
    vertical_padding: int = 0,
) -> None:
    if isinstance(widget, QAbstractSpinBox):
        stable_style = _StableSpinBoxStyle()
        stable_style.setParent(widget)
        widget.setStyle(stable_style)
    widget.setSizePolicy(
        QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
    )
    size_hint = widget.sizeHint()
    width = max(size_hint.width() + horizontal_padding, minimum_width)
    height = size_hint.height() + vertical_padding
    widget.setFixedWidth(width + width % 2)
    widget.setFixedHeight(height + height % 2)
