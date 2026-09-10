from __future__ import annotations

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPoint,
    QStringListModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QTextCursor
from PySide6.QtWidgets import QCompleter, QLineEdit, QListView, QPlainTextEdit, QWidget

from tagger.tag_library.library import TagLibrary
from tagger.tag_library.text import pending_tag, replace_pending_tag


class TagCompleter(QObject):
    """Autocomplete for a comma-separated tag line edit.

    The popup is deliberately independent of ``QCompleter``.  Qt's built-in
    completer consumes navigation keys and applies the current row while it
    moves, which makes it impossible to keep the pending text untouched.
    """

    def __init__(self, line_edit: QLineEdit, library: TagLibrary) -> None:
        super().__init__(line_edit)
        self._line_edit = line_edit
        self._library = library
        self._completing = False
        self._suppress_focus_refresh = False
        self._model = QStringListModel(self)
        self._popup = _TagCompletionPopup(line_edit.window())
        self._popup.setModel(self._model)
        self._popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._popup.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._popup.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._popup.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._popup.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._popup.installEventFilter(self)
        self._popup.viewport().installEventFilter(self)
        self._popup.item_double_clicked.connect(self._insert_completion)
        line_edit.installEventFilter(self)
        line_edit.textChanged.connect(self.refresh)
        library.changed.connect(self.refresh)
        self.refresh()

    def popup(self) -> QListView:
        return self._popup

    def splitPath(self, path: str) -> list[str]:
        return [pending_tag(path)]

    def pathFromIndex(self, index) -> str:
        return replace_pending_tag(self._line_edit.text(), str(index.data()))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._line_edit:
            if event.type() == QEvent.Type.FocusIn:
                if self._suppress_focus_refresh:
                    self._suppress_focus_refresh = False
                    self._popup.hide()
                    return False
                if not self._popup.isVisible():
                    self.refresh()
                return False
            if event.type() == QEvent.Type.FocusOut:
                self._suppress_focus_refresh = False
                if not self._cursor_over_popup():
                    self._popup.hide()
                return False
            if event.type() != QEvent.Type.KeyPress:
                return False
            key_event = event if isinstance(event, QKeyEvent) else None
            if key_event is None:
                return False
            key = key_event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                if self._popup.isVisible() and self._model.rowCount() > 0:
                    self._move_popup_selection(key)
                    return True
                return False
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._popup.isVisible():
                    index = self._popup.currentIndex()
                    if index.isValid():
                        self._insert_completion(index)
                        return True
                    self._popup.hide()
                # Returning False preserves QLineEdit.returnPressed.
                return False
            return False

        if obj is self._popup or obj is self._popup.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse_event = event if isinstance(event, QMouseEvent) else None
                if (
                    mouse_event is not None
                    and mouse_event.button() == Qt.MouseButton.LeftButton
                ):
                    index = self._popup.indexAt(
                        mouse_event.position().toPoint()
                    )
                    if index.isValid():
                        self._line_edit.setFocus(
                            Qt.FocusReason.MouseFocusReason
                        )
                return False
            if event.type() == QEvent.Type.KeyPress:
                key_event = event if isinstance(event, QKeyEvent) else None
                if key_event is not None and key_event.key() in (
                    Qt.Key.Key_Up,
                    Qt.Key.Key_Down,
                ):
                    self._move_popup_selection(key_event.key())
                    return True
                if key_event is not None and key_event.key() in (
                    Qt.Key.Key_Return,
                    Qt.Key.Key_Enter,
                ):
                    index = self._popup.currentIndex()
                    if index.isValid():
                        self._insert_completion(index)
                    return True
            return False

        return False

    def _cursor_over_popup(self) -> bool:
        popup = self._popup
        return popup.isVisible() and popup.rect().contains(
            popup.mapFromGlobal(QCursor.pos())
        )

    def _move_popup_selection(self, key: int) -> bool:
        popup = self._popup
        count = self._model.rowCount()
        if count == 0:
            return False
        current_row = popup.currentIndex().row()
        if key == Qt.Key.Key_Down:
            row = 0 if current_row < 0 else min(current_row + 1, count - 1)
        elif key == Qt.Key.Key_Up:
            row = 0 if current_row < 0 else max(current_row - 1, 0)
        else:
            return False
        selection_model = popup.selectionModel()
        if selection_model is None:
            return False
        index = self._model.index(row, 0)
        selection_model.setCurrentIndex(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
        popup.scrollTo(index)
        return True

    def _clear_popup_selection(self) -> None:
        popup = self._popup
        selection_model = popup.selectionModel()
        if selection_model is None:
            return
        popup.clearSelection()
        popup.setCurrentIndex(QModelIndex())

    def _insert_completion(self, index) -> None:
        updated = self.pathFromIndex(index)
        self._completing = True
        try:
            self._line_edit.setText(updated)
            self._line_edit.setCursorPosition(len(self._line_edit.text()))
        finally:
            self._completing = False
            self._suppress_focus_refresh = True
            self._popup.hide()

    def refresh(self, text: str | None = None) -> None:
        value = self._line_edit.text() if text is None else text
        suggestions = self._library.suggestions(value)
        self._model.setStringList(suggestions)
        self._clear_popup_selection()
        if suggestions and self._line_edit.hasFocus() and not self._completing:
            self._show_popup()
        else:
            self._popup.hide()

    def _show_popup(self) -> None:
        popup = self._popup
        popup.ensurePolished()
        row_height = popup.sizeHintForRow(0) or self._line_edit.fontMetrics().height()
        visible_rows = min(self._model.rowCount(), 12)
        height = row_height * visible_rows + 2
        width = max(self._line_edit.width(), popup.sizeHintForColumn(0) + 24)
        top_left = self._line_edit.mapToGlobal(QPoint(0, self._line_edit.height()))
        popup.setGeometry(top_left.x(), top_left.y(), width, height)
        popup.show()
        popup.raise_()
        self._line_edit.setFocus()


class _TagCompletionPopup(QListView):
    item_double_clicked = Signal(QModelIndex)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            selection_model = self.selectionModel()
            if index.isValid() and selection_model is not None:
                selection_model.setCurrentIndex(
                    index,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect,
                )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                selection_model = self.selectionModel()
                if selection_model is not None:
                    selection_model.setCurrentIndex(
                        index,
                        QItemSelectionModel.SelectionFlag.ClearAndSelect,
                    )
                self.item_double_clicked.emit(index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def attach_tag_completer(
    line_edit: QLineEdit, library: TagLibrary | None
) -> TagCompleter | None:
    if library is None:
        return None
    completer = TagCompleter(line_edit, library)
    line_edit.setProperty("tag_completer", completer)
    return completer


class PlainTextTagCompleter(QObject):
    def __init__(self, edit: QPlainTextEdit, library: TagLibrary) -> None:
        super().__init__(edit)
        self._edit = edit
        self._library = library
        self._model = QStringListModel(self)
        self.completer = QCompleter(self._model, self)
        self.completer.setWidget(edit)
        self.completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion
        )
        self.completer.setMaxVisibleItems(12)
        self.completer.activated.connect(self._insert_completion)
        edit.textChanged.connect(self.refresh)
        library.changed.connect(self.refresh)

    def refresh(self) -> None:
        text = self._edit.toPlainText()
        suggestions = self._library.suggestions(text)
        self._model.setStringList(suggestions)
        popup = self.completer.popup()
        if suggestions and self._edit.hasFocus():
            rectangle = self._edit.cursorRect()
            if popup is not None:
                rectangle.setWidth(
                    popup.sizeHintForColumn(0)
                    + popup.verticalScrollBar().sizeHint().width()
                )
            self.completer.complete(rectangle)
        elif popup is not None:
            popup.hide()

    def _insert_completion(self, completion: str) -> None:
        cursor = self._edit.textCursor()
        text = self._edit.toPlainText()
        updated = replace_pending_tag(text, completion)
        self._edit.setPlainText(updated)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._edit.setTextCursor(cursor)


def attach_plain_text_tag_completer(
    edit: QPlainTextEdit, library: TagLibrary | None
) -> PlainTextTagCompleter | None:
    if library is None:
        return None
    completer = PlainTextTagCompleter(edit, library)
    edit.setProperty("tag_completer", completer)
    return completer
