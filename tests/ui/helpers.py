from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QSizePolicy,
    QStyle,
    QStyleOptionSpinBox,
    QWidget,
)


def create_png(path: Path, color: str = "#2f6fed") -> None:
    image = QImage(32, 24, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def create_cached_model(cache_directory: Path, repo_id: str) -> None:
    snapshot = (
        cache_directory
        / f"models--{repo_id.replace('/', '--')}"
        / "snapshots"
        / "revision"
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").touch()
    (snapshot / "selected_tags.csv").touch()


def assert_stable_widget_size(
    widget: QWidget,
    *,
    minimum_width: int = 0,
    vertical_padding: int = 0,
) -> None:
    assert widget.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
    assert widget.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert widget.minimumWidth() == widget.maximumWidth()
    assert widget.width() >= max(widget.sizeHint().width() + 8, minimum_width)
    assert widget.width() % 2 == 0
    assert widget.minimumHeight() == widget.maximumHeight()
    assert widget.height() >= widget.sizeHint().height() + vertical_padding
    assert widget.height() % 2 == 0


def render_spin_box_control(
    spin_box: QDoubleSpinBox, *, hovered: bool
) -> QImage:
    option = QStyleOptionSpinBox()
    spin_box.initStyleOption(option)
    option.state &= ~QStyle.StateFlag.State_MouseOver
    option.activeSubControls = QStyle.SubControl.SC_None
    if hovered:
        option.state |= QStyle.StateFlag.State_MouseOver
        option.activeSubControls = QStyle.SubControl.SC_SpinBoxUp

    image = QImage(spin_box.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    spin_box.style().drawComplexControl(
        QStyle.ComplexControl.CC_SpinBox, option, painter, spin_box
    )
    assert painter.end()
    return image
