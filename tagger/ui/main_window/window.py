from __future__ import annotations

from pathlib import Path
from typing import cast, override

from PySide6.QtCore import QByteArray, QEvent, QItemSelectionModel, QObject, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QImage,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tagger.domain.models import ImageEntry
from tagger.domain.tags import tag_matches_pattern
from tagger.settings.preferences import (
    PARENTHESES_SETTING,
    UNDERSCORES_SETTING,
    get_scrolling_behavior,
)
from tagger.settings.store import create_app_settings
from tagger.tag_library.completion import attach_tag_completer
from tagger.tag_library.library import TagLibrary
from tagger.ui.catalog import ImageCatalogModel, ImageCatalogView
from tagger.ui.preview.loader import PreviewLoader
from tagger.ui.preview.view import ImageView

from .actions import WindowActions
from .dialogs import DialogController
from .files import FileActions
from .folders import FolderController
from .tags import TagEditor


class MainWindow(QMainWindow):
    """Own the main widgets, image selection, preview, and window settings."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Tagger")
        self.resize(1200, 760)
        self.setAcceptDrops(True)
        self.settings = create_app_settings()
        self.directory: Path | None = None
        self.commands = WindowActions(self)
        self.folders = FolderController(self)
        self.files = FileActions(self)
        self.dialogs = DialogController(self)
        self.tags = TagEditor(self)
        self.tag_library = TagLibrary(
            parent=self,
            underscores_to_spaces=cast(
                bool,
                self.settings.value(
                    UNDERSCORES_SETTING,
                    False,
                    type=bool,
                ),
            ),
            escape_parentheses=cast(
                bool,
                self.settings.value(
                    PARENTHESES_SETTING, False, type=bool
                ),
            ),
        )

        self.catalog = ImageCatalogModel(self)
        self.image_list = ImageCatalogView()
        self.image_list.setModel(self.catalog)
        self.image_list.setSelectionMode(
            ImageCatalogView.SelectionMode.SingleSelection
        )
        self.image_list.setMinimumWidth(220)
        self.image_list.setHeaderHidden(True)
        self.image_list.setUniformRowHeights(True)
        self.image_list.setAnimated(True)
        self.image_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.image_list.customContextMenuRequested.connect(
            self.files._show_image_context_menu
        )
        self.image_list.image_move_requested.connect(
            self.files._move_image_to_folder
        )
        self.image_list.installEventFilter(self)
        self.image_list.selectionModel().currentChanged.connect(
            self._current_image_changed
        )

        self.image_view = ImageView()
        self.preview_loader = PreviewLoader(self)
        self.preview_loader.loaded.connect(self._preview_loaded)
        self.image_info_label = QLabel("No image selected")
        self.image_info_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.image_info_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.image_info_label.setContentsMargins(10, 6, 10, 6)
        self.image_info_label.setStyleSheet(
            "QLabel { background: #e4e7ec; color: #344054; "
            "border-top: 1px solid #d0d5dd; }"
        )

        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)
        image_layout.addWidget(self.image_view, 1)
        image_layout.addWidget(self.image_info_label)

        self.tag_list = QListWidget()
        self.tag_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.tag_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tag_list.customContextMenuRequested.connect(
            self.tags._show_tag_context_menu
        )
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Comma-separated tags")
        self.tag_input.setClearButtonEnabled(True)
        self.tag_input.returnPressed.connect(self.tags._add_current_tags)
        self.tag_completer = attach_tag_completer(
            self.tag_input, self.tag_library
        )

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tags (* wildcard)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(180)
        self.search_input.setMaximumWidth(300)
        self.search_input.setToolTip(
            "Search tags in the opened folder. Use * as a wildcard. "
            "Press Enter for the next match or Shift+Enter for the previous match."
        )
        self.search_input.installEventFilter(self)
        self.search_completer = attach_tag_completer(
            self.search_input, self.tag_library
        )

        self.add_tag_button = QPushButton("+")
        self.add_tag_button.setToolTip("Add these tags to the current image")
        self.add_tag_button.setFixedWidth(34)
        self.delete_tag_button = QPushButton("Delete Selected")
        self.add_tag_button.clicked.connect(self.tags._add_current_tags)
        self.delete_tag_button.clicked.connect(self.tags._delete_selected_tags)
        self.inline_buttons = [self.add_tag_button, self.delete_tag_button]

        input_buttons = QHBoxLayout()
        input_buttons.setContentsMargins(0, 0, 0, 0)
        input_buttons.addWidget(self.tag_input, 1)
        input_buttons.addWidget(self.add_tag_button)

        tag_panel = QWidget()
        tag_layout = QVBoxLayout(tag_panel)
        tag_layout.setContentsMargins(8, 0, 0, 0)
        tag_layout.addWidget(QLabel("Current tags"))
        tag_layout.addWidget(self.tag_list, 1)
        tag_layout.addLayout(input_buttons)
        tag_layout.addWidget(self.delete_tag_button)
        tag_panel.setMinimumWidth(280)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.image_list)
        self.splitter.addWidget(image_panel)
        self.splitter.addWidget(tag_panel)
        self.splitter.setSizes([250, 650, 300])
        self.setCentralWidget(self.splitter)

        self.commands._create_actions()
        self.commands._create_menus_and_toolbar()
        self._restore_settings()
        self.folders._open_recent_folder_on_startup()
        self.commands._update_action_states()

    def _dropped_local_paths(self, event) -> list[Path] | None:
        if not event.mimeData().hasUrls():
            return None
        urls = event.mimeData().urls()
        if not urls or any(not url.isLocalFile() for url in urls):
            return None
        return [Path(url.toLocalFile()) for url in urls]

    def _dropped_directory(self, event) -> Path | None:
        paths = self._dropped_local_paths(event)
        if paths is None or len(paths) != 1:
            return None
        return paths[0] if paths[0].is_dir() else None

    def _dropped_image_files(self, event) -> list[Path] | None:
        if self.directory is None:
            return None
        paths = self._dropped_local_paths(event)
        if paths is None or any(not path.is_file() for path in paths):
            return None
        extensions = self.folders._supported_extensions()
        if not any(path.suffix.casefold() in extensions for path in paths):
            return None
        if any(
            path.suffix.casefold() not in extensions
            and path.suffix.casefold() != ".txt"
            for path in paths
        ):
            return None
        return paths

    @override
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_directory(event) is not None:
            event.acceptProposedAction()
        elif self._dropped_image_files(event) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    @override
    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._dropped_directory(event) is not None:
            event.acceptProposedAction()
        elif self._dropped_image_files(event) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    @override
    def dropEvent(self, event: QDropEvent) -> None:
        directory = self._dropped_directory(event)
        if directory is not None:
            event.acceptProposedAction()
            self.folders.close_folder()
            self.folders._load_directory(directory, show_issues=True)
            return

        sources = self._dropped_image_files(event)
        if sources is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.folders.import_images(sources)

    def _select_row(self, row: int) -> None:
        if self.catalog.entry(row) is None:
            return
        index = self.catalog.index_for_row(row)
        if not index.isValid():
            return
        parent = index.parent()
        while parent.isValid():
            self.image_list.expand(parent)
            parent = parent.parent()
        self.image_list.setCurrentIndex(index)
        self.image_list.selectionModel().select(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        self.image_list.scrollTo(index)

    def _select_optional_row(self, row: int | None) -> None:
        if row is not None:
            self._select_row(row)

    def _move_selection(self, offset: int) -> None:
        row = self.catalog.row_for_index(self.image_list.currentIndex())
        if row is None:
            return
        target = (
            self.catalog.next_image_row(row)
            if offset > 0
            else self.catalog.previous_image_row(row)
        )
        self._select_optional_row(target)

    def _current_entry(self) -> ImageEntry | None:
        return self.catalog.entry_for_index(self.image_list.currentIndex())

    def _focus_tag_search(self) -> None:
        self.search_input.setFocus()
        self.search_input.selectAll()

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.image_list and event.type() == QEvent.Type.KeyPress:
            if self._handle_image_catalog_key_press(cast(QKeyEvent, event)):
                return True
        if watched is self.search_input and event.type() == QEvent.Type.KeyPress:
            key_event = cast(QKeyEvent, event)
            if key_event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                direction = (
                    -1
                    if key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    else 1
                )
                self._find_tag(direction)
                return True
        return super().eventFilter(watched, event)

    def _handle_image_catalog_key_press(self, event: QKeyEvent) -> bool:
        current_index = self.image_list.currentIndex()
        if (
            event.modifiers() != Qt.KeyboardModifier.NoModifier
            or not self.image_list.selectionModel().isSelected(current_index)
            or self._current_entry() is None
        ):
            return False
        if event.key() == Qt.Key.Key_Delete:
            self.files._delete_current_image_and_tag()
            return True
        if event.key() == Qt.Key.Key_F2:
            self.files._rename_current_image_and_tag()
            return True
        return False

    def _find_tag(self, direction: int = 1) -> None:
        pattern = self.search_input.text().strip()
        if not pattern:
            self.statusBar().showMessage("Enter a tag pattern to search for.", 4000)
            return

        count = self.catalog.image_count
        if not count:
            self.statusBar().showMessage("Open a folder before searching tags.", 4000)
            return

        current_row = self.catalog.row_for_index(self.image_list.currentIndex())
        if current_row is None:
            current_row = -1
        current_entry = self.catalog.entry(current_row)
        current_tag_row = self.tag_list.currentRow()
        selected_tag = self.tag_list.currentItem()
        continue_in_current = (
            current_entry is not None
            and 0 <= current_tag_row < len(current_entry.tags)
            and selected_tag is not None
            and selected_tag.text() == current_entry.tags[current_tag_row]
            and tag_matches_pattern(selected_tag.text(), pattern)
        )

        candidates: list[tuple[int, int]] = []

        def append_rows(offsets: range) -> None:
            for offset in offsets:
                row = (current_row + offset) % count
                entry = self.catalog.entry(row)
                if entry is not None:
                    tag_rows = (
                        range(len(entry.tags))
                        if direction > 0
                        else range(len(entry.tags) - 1, -1, -1)
                    )
                    candidates.extend((row, tag_row) for tag_row in tag_rows)

        if continue_in_current:
            if direction > 0:
                candidates.extend(
                    (current_row, tag_row)
                    for tag_row in range(
                        current_tag_row + 1, len(current_entry.tags)
                    )
                )
                append_rows(range(1, count))
                candidates.extend(
                    (current_row, tag_row)
                    for tag_row in range(0, current_tag_row + 1)
                )
            else:
                candidates.extend(
                    (current_row, tag_row)
                    for tag_row in range(current_tag_row - 1, -1, -1)
                )
                append_rows(range(-1, -count, -1))
                candidates.extend(
                    (current_row, tag_row)
                    for tag_row in range(
                        len(current_entry.tags) - 1, current_tag_row - 1, -1
                    )
                )
        else:
            append_rows(
                range(1, count + 1)
                if direction > 0
                else range(-1, -count - 1, -1)
            )

        for row, tag_row in candidates:
            entry = self.catalog.entry(row)
            if entry is None:
                continue
            matched_tag = entry.tags[tag_row]
            if tag_matches_pattern(matched_tag, pattern):
                self._select_row(row)
                self._select_current_tag(matched_tag)
                self.statusBar().showMessage(
                    f'Tag search "{pattern}" matched {matched_tag} in '
                    f"{entry.image_path.name}",
                    4000,
                )
                return

        self.statusBar().showMessage(
            f'No tags match "{pattern}" in the opened folder.', 4000
        )

    def _select_current_tag(self, tag: str) -> None:
        self.tag_list.clearSelection()
        for row in range(self.tag_list.count()):
            item = self.tag_list.item(row)
            if item.text() == tag:
                self.tag_list.setCurrentItem(item)
                item.setSelected(True)
                self.tag_list.scrollToItem(item)
                return

    def _current_image_changed(self, current, _previous) -> None:
        entry = self.catalog.entry_for_index(current)
        self.tag_list.clear()
        if entry is None:
            self.preview_loader.clear()
            self.image_view.clear_image()
            self._set_image_info(None)
            self.commands._update_action_states()
            return

        row = self.catalog.row_for_index(current)
        if row is None:
            return
        self.tag_list.addItems(entry.tags)
        self.image_view.clear_image("Loading image...")
        self._set_image_info(entry)
        self.preview_loader.load(entry.image_path)
        details = [
            f"{self.catalog.image_position(row)}/{self.catalog.image_count}",
            entry.image_path.name,
            entry.tag_path.name,
        ]
        if entry.error:
            details.append(entry.error)
        elif entry.warnings:
            details.extend(entry.warnings)
        self.statusBar().showMessage(" | ".join(details))
        self.commands._update_action_states()

    def _preview_loaded(self, image: QImage, error: str) -> None:
        entry = self._current_entry()
        if error or image.isNull():
            self.image_view.clear_image(f"Could not display image\n{error}")
            self._set_image_info(entry, error=error or "Could not read image")
        else:
            self.image_view.set_image(image)
            self._set_image_info(entry, image)

    def _update_window_title(self) -> None:
        title = "Image Tagger"
        if self.directory is not None:
            folder_name = self.directory.name or str(self.directory)
            title = f"{folder_name} - {title}"
        self.setWindowTitle(title)

    def _set_image_info(
        self,
        entry: ImageEntry | None,
        image: QImage | None = None,
        *,
        error: str = "",
    ) -> None:
        if entry is None:
            self.image_info_label.setText("No image selected")
            self.image_info_label.setToolTip("")
            return

        details = []
        if image is not None and not image.isNull():
            details.append(f"{image.width()} × {image.height()} px")
        elif error:
            details.append("Dimensions unavailable")
        else:
            details.append("Loading dimensions...")

        image_format = entry.image_path.suffix.removeprefix(".").upper()
        if image_format:
            details.append(image_format)
        try:
            details.append(self._format_file_size(entry.image_path.stat().st_size))
        except OSError:
            details.append("Size unavailable")
        if error:
            details.append(error)

        self.image_info_label.setText(" | ".join(details))
        self.image_info_label.setToolTip(str(entry.image_path))

    @staticmethod
    def _format_file_size(size: int) -> str:
        value = float(size)
        units = ("B", "KB", "MB", "GB", "TB")
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def _actual_size(self) -> None:
        self.commands.fit_action.setChecked(False)
        self.image_view.actual_size()

    def _zoom_in(self) -> None:
        self.commands.fit_action.setChecked(False)
        self.image_view.zoom_in()

    def _zoom_out(self) -> None:
        self.commands.fit_action.setChecked(False)
        self.image_view.zoom_out()

    def _restore_settings(self) -> None:
        geometry = self.settings.value("main_geometry")
        if isinstance(geometry, (QByteArray, bytes, bytearray, memoryview)):
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("splitter_state")
        if isinstance(
            splitter_state, (QByteArray, bytes, bytearray, memoryview)
        ):
            self.splitter.restoreState(splitter_state)
        fit = cast(bool, self.settings.value("fit_to_window", True, type=bool))
        self.commands.fit_action.setChecked(fit)
        self.image_view.set_fit_to_window(fit)
        self.image_view.set_scrolling_behavior(
            get_scrolling_behavior(self.settings)
        )

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("main_geometry", self.saveGeometry())
        self.settings.setValue("splitter_state", self.splitter.saveState())
        self.settings.setValue("fit_to_window", self.commands.fit_action.isChecked())
        self.settings.sync()
        super().closeEvent(event)
