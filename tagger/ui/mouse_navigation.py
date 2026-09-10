from __future__ import annotations

from collections.abc import Sequence
from typing import override

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget


class MouseNavigation(QObject):
    """Route side buttons to the visible navigation controls in one window."""

    def __init__(
        self,
        window: QWidget,
        *,
        back: Sequence[QAction | QAbstractButton],
        forward: Sequence[QAction | QAbstractButton],
    ) -> None:
        super().__init__(window)
        self._back = back
        self._forward = forward
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() not in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseButtonRelease,
        }:
            return False
        if not isinstance(event, QMouseEvent) or not isinstance(watched, QWidget):
            return False
        window = self.parent()
        if not isinstance(window, QWidget) or watched.window() is not window:
            return False
        if not window.isVisible() or not window.isEnabled():
            return False
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not window:
            return False
        if event.button() == Qt.MouseButton.BackButton:
            controls = self._back
        elif event.button() == Qt.MouseButton.ForwardButton:
            controls = self._forward
        else:
            return False

        # Consume the whole click so child widgets cannot handle it a second time.
        if event.type() == QEvent.Type.MouseButtonRelease:
            for control in controls:
                if control.isVisible() and control.isEnabled():
                    if isinstance(control, QAction):
                        control.trigger()
                    else:
                        control.click()
                    break
        event.accept()
        return True
