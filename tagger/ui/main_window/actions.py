from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QSizePolicy, QToolBar, QToolButton, QWidget

from tagger.ai_tagging.dependencies import (
    ai_dependencies_available,
    missing_ai_dependencies,
)
from tagger.domain.models import TagOperation
from tagger.paths import PROJECT_ROOT
from tagger.ui.widgets import stabilize_checked_tool_button


if TYPE_CHECKING:
    from .window import MainWindow


TOOLBAR_ICON_DIRECTORY = PROJECT_ROOT / "assets" / "icons"


class WindowActions:
    """Build menus and toolbar actions and keep their enabled states in sync."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    def _create_actions(self) -> None:
        self.open_action = QAction(
            "Open Folder...",
            self.window,
        )
        self.open_action.setToolTip("Open folder")
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.window.folders.open_folder)

        self.close_folder_action = QAction("Close Folder", self.window)
        self.close_folder_action.setToolTip("Close folder")
        self.close_folder_action.setShortcut(QKeySequence.StandardKey.Close)
        self.close_folder_action.triggered.connect(self.window.folders.close_folder)

        self.rescan_action = QAction("Rescan", self.window)
        self.rescan_action.setShortcut(QKeySequence("F5"))
        self.rescan_action.triggered.connect(self.window.folders.rescan)

        self.tidy_action = QAction("Tidy", self.window)
        self.tidy_action.setToolTip(
            "Delete files not recognized as images or tag sidecars."
        )
        self.tidy_action.triggered.connect(self.window.files._tidy_folder)

        self.archive_action = QAction("Archive...", self.window)
        self.archive_action.triggered.connect(self.window.files._archive_folder)

        self.exit_action = QAction("Exit", self.window)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.window.close)

        self.global_search_action = QAction("Global Tag Search...", self.window)
        self.global_search_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.global_search_action.triggered.connect(self.window.dialogs._open_global_search)

        self.review_action = QAction("Review Tags...", self.window)
        self.review_action.setShortcut(QKeySequence("Ctrl+R"))
        self.review_action.triggered.connect(self.window.dialogs._open_review)

        self.complex_filter_action = QAction("Complex Filter...", self.window)
        self.complex_filter_action.setShortcut(QKeySequence("Ctrl+Alt+F"))
        self.complex_filter_action.triggered.connect(self.window.dialogs._open_complex_filter)

        self.bulk_operation_action = QAction("Bulk Operation...", self.window)
        self.bulk_operation_action.triggered.connect(self.window.dialogs._open_bulk_operation)

        self.delete_filter_action = QAction("Delete Filter...", self.window)
        self.delete_filter_action.triggered.connect(self.window.dialogs._open_delete_filter)

        self.deduplicate_action = QAction("Deduplicate...", self.window)
        self.deduplicate_action.triggered.connect(self.window.dialogs._open_deduplicate)

        self.settings_action = QAction("Settings...", self.window)
        self.settings_action.triggered.connect(self.window.dialogs._open_settings)

        self.ai_tagging_action = QAction("AI Tagging...", self.window)
        self.ai_tagging_action.triggered.connect(self.window.dialogs._open_ai_tagging)
        missing = missing_ai_dependencies()
        if missing:
            message = "Install the ai-tagger dependency group: " + ", ".join(missing)
            self.ai_tagging_action.setToolTip(message)

        self.first_action = QAction("First", self.window)
        self.previous_action = QAction(
            "Previous", self.window
        )
        self.next_action = QAction(
            "Next", self.window
        )
        self.last_action = QAction("Last", self.window)
        self.previous_action.setToolTip("Previous image")
        self.next_action.setToolTip("Next image")
        self.first_action.setShortcut(QKeySequence("Ctrl+Home"))
        self.previous_action.setShortcut(QKeySequence("PgUp"))
        self.next_action.setShortcut(QKeySequence("PgDown"))
        self.last_action.setShortcut(QKeySequence("Ctrl+End"))
        self.first_action.triggered.connect(
            lambda: self.window._select_optional_row(self.window.catalog.first_image_row())
        )
        self.previous_action.triggered.connect(lambda: self.window._move_selection(-1))
        self.next_action.triggered.connect(lambda: self.window._move_selection(1))
        self.last_action.triggered.connect(
            lambda: self.window._select_optional_row(self.window.catalog.last_image_row())
        )
        self.window.image_view.navigation_requested.connect(self.window._move_selection)

        self.folder_tag_actions: dict[TagOperation, QAction] = {}
        labels = {
            TagOperation.ADD: "Add Tags...",
            TagOperation.DELETE: "Delete Tags...",
            TagOperation.TOGGLE: "Toggle Tags...",
        }
        for operation, label in labels.items():
            action = QAction(label, self.window)
            action.triggered.connect(
                lambda checked=False, op=operation: self.window.dialogs._start_traversal(op)
            )
            self.folder_tag_actions[operation] = action

        self.normalize_action = QAction("Normalize All Tags...", self.window)
        self.normalize_action.triggered.connect(self.window.tags._normalize_all_tags)

        self.fit_action = QAction("Fit to Window", self.window)
        self.fit_action.setToolTip("Fit to window")
        self.fit_action.setCheckable(True)
        self.fit_action.setChecked(True)
        self.fit_action.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_action.toggled.connect(self.window.image_view.set_fit_to_window)
        self.window.image_view.fit_to_window_changed.connect(self.fit_action.setChecked)

        self.actual_size_action = QAction("Actual Size", self.window)
        self.actual_size_action.setShortcut(QKeySequence("Ctrl+1"))
        self.actual_size_action.triggered.connect(self.window._actual_size)

        self.zoom_in_action = QAction("Zoom In", self.window)
        self.zoom_in_action.setToolTip("Zoom in")
        self.zoom_in_action.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.zoom_in_action.triggered.connect(self.window._zoom_in)
        self.zoom_out_action = QAction("Zoom Out", self.window)
        self.zoom_out_action.setToolTip("Zoom out")
        self.zoom_out_action.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.zoom_out_action.triggered.connect(self.window._zoom_out)

        toolbar_icons = {
            self.open_action: "open.svg",
            self.close_folder_action: "close.svg",
            self.previous_action: "previous.svg",
            self.next_action: "next.svg",
            self.zoom_in_action: "zoom-in.svg",
            self.fit_action: "fit.svg",
            self.zoom_out_action: "zoom-out.svg",
        }
        for action, filename in toolbar_icons.items():
            action.setIcon(QIcon(str(TOOLBAR_ICON_DIRECTORY / filename)))
            action.setIconVisibleInMenu(False)

    def _create_menus_and_toolbar(self) -> None:
        file_menu = self.window.menuBar().addMenu("&File")
        file_menu.addAction(self.open_action)
        self.open_recent_menu = file_menu.addMenu("Open Recent")
        self.open_recent_action = self.open_recent_menu.menuAction()
        self.open_recent_menu.aboutToShow.connect(
            self.window.folders._update_recent_folder_menu
        )
        self.window.folders._update_recent_folder_menu()
        file_menu.addAction(self.close_folder_action)
        file_menu.addAction(self.rescan_action)
        file_menu.addAction(self.tidy_action)
        file_menu.addSeparator()
        file_menu.addAction(self.archive_action)
        file_menu.addSeparator()
        file_menu.addAction(self.settings_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        navigate_menu = self.window.menuBar().addMenu("&Navigate")
        navigate_menu.addActions(
            [
                self.first_action,
                self.previous_action,
                self.next_action,
                self.last_action,
            ]
        )
        image_menu = self.window.menuBar().addMenu("&Image")
        image_menu.addAction(self.delete_filter_action)
        image_menu.addAction(self.deduplicate_action)
        tags_menu = self.window.menuBar().addMenu("&Tags")
        tags_menu.addAction(self.global_search_action)
        tags_menu.addAction(self.review_action)
        tags_menu.addAction(self.complex_filter_action)
        tags_menu.addAction(self.bulk_operation_action)
        tags_menu.addSeparator()
        tags_menu.addAction(self.ai_tagging_action)
        tags_menu.addSeparator()
        for action in self.folder_tag_actions.values():
            tags_menu.addAction(action)
        tags_menu.addSeparator()
        tags_menu.addAction(self.normalize_action)

        view_menu = self.window.menuBar().addMenu("&View")
        view_menu.addAction(self.fit_action)
        view_menu.addAction(self.actual_size_action)
        view_menu.addSeparator()
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)

        toolbar = QToolBar("Main", self.window)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.close_folder_action)
        toolbar.addSeparator()
        toolbar.addAction(self.previous_action)
        toolbar.addAction(self.next_action)
        toolbar.addSeparator()
        toolbar.addAction(self.zoom_in_action)
        toolbar.addAction(self.fit_action)
        toolbar.addAction(self.zoom_out_action)
        fit_button = toolbar.widgetForAction(self.fit_action)
        if isinstance(fit_button, QToolButton):
            stabilize_checked_tool_button(fit_button)
        search_spacer = QWidget()
        search_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        toolbar.addWidget(search_spacer)
        toolbar.addWidget(self.window.search_input)
        self.window.addToolBar(toolbar)

    def _update_action_states(self) -> None:
        count = self.window.catalog.image_count
        row = self.window.catalog.row_for_index(self.window.image_list.currentIndex())
        has_current = row is not None
        current = self.window.catalog.entry(row) if row is not None else None
        editable = current is not None and current.editable

        has_directory = self.window.directory is not None
        self.close_folder_action.setEnabled(has_directory)
        self.rescan_action.setEnabled(has_directory)
        self.tidy_action.setEnabled(has_directory)
        self.archive_action.setEnabled(
            count > 0 and self.window.files._archive_dialog is None
        )
        self.window.search_input.setEnabled(count > 0)
        self.global_search_action.setEnabled(count > 0)
        self.delete_filter_action.setEnabled(count > 0)
        self.deduplicate_action.setEnabled(count >= 2)
        self.review_action.setEnabled(count > 0 and any(entry.editable and entry.tags for entry in self.window.catalog.entries))
        self.complex_filter_action.setEnabled(count > 0)
        has_previous = (
            row is not None and self.window.catalog.previous_image_row(row) is not None
        )
        has_next = row is not None and self.window.catalog.next_image_row(row) is not None
        self.first_action.setEnabled(has_previous)
        self.previous_action.setEnabled(has_previous)
        self.next_action.setEnabled(has_next)
        self.last_action.setEnabled(has_next)
        self.window.tag_input.setEnabled(editable)
        self.window.tag_list.setEnabled(editable)
        for button in self.window.inline_buttons:
            button.setEnabled(editable)
        any_editable = any(entry.editable for entry in self.window.catalog.entries)
        self.bulk_operation_action.setEnabled(any_editable)
        ai_available = ai_dependencies_available()
        self.ai_tagging_action.setEnabled(ai_available and any_editable)
        for action in self.folder_tag_actions.values():
            action.setEnabled(any_editable)
        self.normalize_action.setEnabled(any_editable)
        for action in [
            self.fit_action,
            self.actual_size_action,
            self.zoom_in_action,
            self.zoom_out_action,
        ]:
            action.setEnabled(has_current)
