from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tagger.trash import UNLINK


class TidyDialog(QDialog):
    """Show the complete list of unrecognized files before deleting them."""

    def __init__(
        self,
        directory: Path,
        candidates: list[Path],
        deletion_behavior: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tidy Folder")
        self.resize(680, 480)

        layout = QVBoxLayout(self)
        deleting_permanently = deletion_behavior == UNLINK
        self.summary_label = QLabel(
            (
                f"Permanently delete {len(candidates)} unrecognized file(s)?\n"
                "This cannot be undone."
                if deleting_permanently
                else (
                    f"Move {len(candidates)} unrecognized file(s) to the system "
                    "Recycle Bin?"
                )
            )
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        folder_label = QLabel(str(directory))
        folder_label.setTextFormat(Qt.TextFormat.PlainText)
        folder_label.setWordWrap(True)
        folder_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(folder_label)

        self.file_list = QListWidget()
        self.file_list.setAccessibleName("Files to delete")
        self.file_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        for path in candidates:
            item = QListWidgetItem(str(path.relative_to(directory)))
            item.setToolTip(str(path))
            self.file_list.addItem(item)
        layout.addWidget(self.file_list, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.delete_button = buttons.addButton(
            "Permanently Delete" if deleting_permanently else "Move to Recycle Bin",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.delete_button.setAutoDefault(False)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus()
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
