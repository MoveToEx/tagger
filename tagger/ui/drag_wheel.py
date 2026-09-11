from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sys

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget


@contextmanager
def forward_native_drag_wheel(viewport: QWidget) -> Iterator[None]:
    """Deliver wheel input that Windows' OLE drag loop consumes before Qt."""
    if sys.platform != "win32":
        yield
        return

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hook_proc = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )
    user32.SetWindowsHookExW.argtypes = (
        ctypes.c_int, hook_proc, wintypes.HINSTANCE, wintypes.DWORD
    )
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = (
        wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = ()
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    @hook_proc
    def forward_message(code: int, removal: int, address: int) -> int:
        # WH_GETMESSAGE sees messages even when OLE retrieves them without
        # dispatching them to Qt. PM_REMOVE avoids handling a peek twice.
        if code >= 0 and removal == 1:
            message = ctypes.cast(address, ctypes.POINTER(wintypes.MSG)).contents
            if message.message == 0x020A and viewport.isVisible():  # WM_MOUSEWHEEL
                # Qt's cursor coordinates account for fractional display scaling.
                global_position = QCursor.pos()
                position = viewport.mapFromGlobal(global_position)
                if viewport.rect().contains(position):
                    delta = ctypes.c_short(message.wParam >> 16).value
                    wheel = QWheelEvent(
                        QPointF(position),
                        QPointF(global_position),
                        QPoint(),
                        QPoint(0, delta),
                        QApplication.mouseButtons(),
                        QApplication.keyboardModifiers(),
                        Qt.ScrollPhase.NoScrollPhase,
                        False,
                    )
                    # Consume the native message so Qt cannot scroll twice if
                    # the drag loop does dispatch it after our hook returns.
                    message.message = 0  # WM_NULL
                    QApplication.sendEvent(viewport, wheel)
        return user32.CallNextHookEx(None, code, removal, address)

    # A thread-local hook exists only for this drag; other applications and
    # normal wheel input are unaffected. Retain the callback until unhooking.
    hook = user32.SetWindowsHookExW(
        3, forward_message, None, kernel32.GetCurrentThreadId()  # WH_GETMESSAGE
    )
    try:
        yield
    finally:
        if hook:
            user32.UnhookWindowsHookEx(hook)
