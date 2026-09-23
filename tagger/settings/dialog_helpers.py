from __future__ import annotations

from PySide6.QtWidgets import QCheckBox

from tagger.ui.widgets import stabilize_checkbox


def _stabilize_checkbox(checkbox: QCheckBox) -> None:
    stabilize_checkbox(checkbox)


def _format_byte_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
