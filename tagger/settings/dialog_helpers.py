from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QSizePolicy


def _stabilize_checkbox(checkbox: QCheckBox) -> None:
    checkbox.setStyleSheet(
        "QCheckBox::indicator { width: 12px; height: 12px; }"
    )
    checkbox.setSizePolicy(
        QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
    )
    checkbox.setFixedHeight(checkbox.sizeHint().height())


def _format_byte_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
