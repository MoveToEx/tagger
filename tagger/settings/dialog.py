from __future__ import annotations

from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tagger.ai_tagging.dependencies import (
    ai_dependencies_available,
    missing_ai_dependencies,
)
from tagger.ai_tagging.model_dialog import ModelManagementDialog
from tagger.paths import get_tag_library_path
from tagger.settings.dialog_helpers import _format_byte_size, _stabilize_checkbox
from tagger.settings.preferences import (
    CATALOG_CLICK_HOLD_BEHAVIOR_SETTING,
    CATALOG_DRAG_AND_DROP,
    CATALOG_NAVIGATE,
    CUSTOM_PROXY,
    IMAGE_PREFETCH_COUNT_SETTING,
    NO_PROXY,
    OPEN_RECENT_FOLDER_ON_STARTUP_SETTING,
    PARENTHESES_SETTING,
    PROXY_MODE_SETTING,
    PROXY_SETTING,
    SCRIPTING_PLAIN_SET,
    SCRIPTING_TAG_SET,
    SCRIPTING_TAGS_TYPE_SETTING,
    SCROLLING_BEHAVIOR_SETTING,
    SYSTEM_PROXY,
    UNDERSCORES_SETTING,
    USE_UNLINK_FOR_DEDUPLICATE_SETTING,
    USE_UNLINK_FOR_DELETE_FILTER_SETTING,
    USE_UNLINK_FOR_MANUAL_DELETE_SETTING,
    USE_UNLINK_FOR_TIDY_SETTING,
    get_catalog_click_hold_behavior,
    get_image_prefetch_count,
    get_scripting_tags_type,
    get_scrolling_behavior,
    get_use_unlink,
)
from tagger.settings.proxy import _proxy_preferences, _resolved_proxy
from tagger.settings.store import JsonSettings, create_app_settings
from tagger.tag_library.download_dialog import DownloadTagsDialog
from tagger.tag_library.format import get_tag_library_file_info
from tagger.tag_library.library import TagLibrary
from tagger.ui.preview.config import (
    MAX_IMAGE_PREFETCH_COUNT,
    SCROLL_NAVIGATE,
    SCROLL_NAVIGATE_AT_END,
    SCROLL_NAVIGATE_WHEN_FITTED,
    SCROLL_PAN,
    SCROLL_ZOOM,
)
from tagger.ui.widgets import stabilize_widget_size


class _LegacyGroupAlias:
    """Expose the old settings-group accessors after the groups were merged."""

    def __init__(self, target: QGroupBox, legacy_title: str) -> None:
        self._target = target
        self._legacy_title = legacy_title

    def title(self) -> str:
        return self._legacy_title

    def layout(self) -> QLayout | None:
        return self._target.layout()

    def __getattr__(self, name: str) -> object:
        return getattr(self._target, name)


class SettingsDialog(QDialog):
    scrolling_behavior_changed = Signal(str)
    click_hold_behavior_changed = Signal(str)
    catalog_click_hold_behavior_changed = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings: JsonSettings | None = None,
        tag_library: TagLibrary | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings or create_app_settings()
        self.tag_library = tag_library
        self.tag_library_path = (
            tag_library.library_path
            if tag_library is not None
            else get_tag_library_path()
        )
        self._applied_transform_options = (
            cast(
                bool,
                self.settings.value(UNDERSCORES_SETTING, False, type=bool),
            ),
            cast(
                bool,
                self.settings.value(PARENTHESES_SETTING, False, type=bool),
            ),
        )
        (
            self._applied_proxy_mode,
            self._applied_proxy_url,
        ) = _proxy_preferences(self.settings)
        self._applied_scrolling_behavior = get_scrolling_behavior(self.settings)
        self._applied_catalog_click_hold_behavior = (
            get_catalog_click_hold_behavior(self.settings)
        )
        self._applied_image_prefetch_count = get_image_prefetch_count(
            self.settings
        )
        self._applied_scripting_tags_type = get_scripting_tags_type(
            self.settings
        )
        self._applied_open_recent_folder_on_startup = cast(
            bool,
            self.settings.value(
                OPEN_RECENT_FOLDER_ON_STARTUP_SETTING,
                False,
                type=bool,
            ),
        )
        self._applied_use_unlink_options = (
            get_use_unlink(
                self.settings, USE_UNLINK_FOR_DELETE_FILTER_SETTING
            ),
            get_use_unlink(
                self.settings, USE_UNLINK_FOR_MANUAL_DELETE_SETTING
            ),
            get_use_unlink(self.settings, USE_UNLINK_FOR_TIDY_SETTING),
            get_use_unlink(self.settings, USE_UNLINK_FOR_DEDUPLICATE_SETTING),
        )
        self.setWindowTitle("Settings")
        self.resize(760, 520)

        self.navigation_tree = QTreeWidget()
        self.navigation_tree.setHeaderHidden(True)
        self.navigation_tree.setRootIsDecorated(True)
        self.navigation_tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection
        )
        self.navigation_tree.setFixedWidth(160)
        self.tabs = self.navigation_tree
        self.pages = QStackedWidget()
        self.navigation_list = self.navigation_tree
        self.stacked_widget = self.pages

        self.general_page = self._create_general_page()
        self.models_page = self._create_models_page()
        self.tag_library_dialog: DownloadTagsDialog | None = None
        self.autocomplete_page = self._create_autocomplete_page()
        self.scripting_page = self._create_scripting_page()
        self.proxy_page = self._create_proxy_page()
        self.pages.addWidget(self.general_page)
        self.pages.addWidget(self.models_page)
        self.pages.addWidget(self.autocomplete_page)
        self.pages.addWidget(self.scripting_page)
        self.pages.addWidget(self.proxy_page)

        self.general_item = self._add_navigation_item(
            "General", self.general_page
        )
        self.models_item = self._add_navigation_item(
            "Models", self.models_page
        )
        self.autocomplete_item = self._add_navigation_item(
            "Autocomplete", self.autocomplete_page
        )
        self.scripting_item = self._add_navigation_item(
            "Scripting", self.scripting_page, parent=self.general_item
        )
        self.general_item.setExpanded(True)
        self.network_item = QTreeWidgetItem(["Network"])
        self.network_item.setFlags(
            self.network_item.flags() & ~Qt.ItemFlag.ItemIsSelectable
        )
        self.navigation_tree.addTopLevelItem(self.network_item)
        self.proxy_item = self._add_navigation_item(
            "Proxy", self.proxy_page, parent=self.network_item
        )
        self.network_item.setExpanded(True)
        self.navigation_tree.currentItemChanged.connect(
            self._navigation_changed
        )
        self.navigation_tree.setCurrentItem(self.general_item)

        content = QHBoxLayout()
        content.addWidget(self.navigation_tree)
        content.addWidget(self.pages, 1)

        self.ok_button = QPushButton("OK")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self._apply_and_accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.apply_button)

        layout = QVBoxLayout(self)
        layout.addLayout(content)
        layout.addLayout(buttons)

    def _add_navigation_item(
        self,
        label: str,
        page: QWidget,
        *,
        parent: QTreeWidgetItem | None = None,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, self.pages.indexOf(page))
        if parent is None:
            self.navigation_tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    def _navigation_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        page_index = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(page_index, int):
            self.pages.setCurrentIndex(page_index)

    def _create_general_page(self) -> QWidget:
        page = QWidget()
        self.startup_group = QGroupBox("Startup")
        self.open_recent_folder_checkbox = QCheckBox(
            "Open the most recent folder when the app starts"
        )
        self.open_recent_folder_checkbox.setChecked(
            self._applied_open_recent_folder_on_startup
        )
        _stabilize_checkbox(self.open_recent_folder_checkbox)
        startup_layout = QVBoxLayout(self.startup_group)
        startup_layout.addWidget(self.open_recent_folder_checkbox)

        self.behavior_group = QGroupBox("Behavior")
        self.scrolling_behavior_input = QComboBox()
        self.scrolling_behavior_input.addItem("Navigate", SCROLL_NAVIGATE)
        self.scrolling_behavior_input.addItem("Pan", SCROLL_PAN)
        self.scrolling_behavior_input.addItem(
            "Pan, Navigate when fitted to window",
            SCROLL_NAVIGATE_WHEN_FITTED,
        )
        self.scrolling_behavior_input.addItem(
            "Pan, Navigate at end", SCROLL_NAVIGATE_AT_END
        )
        self.scrolling_behavior_input.addItem("Zoom", SCROLL_ZOOM)
        stabilize_widget_size(self.scrolling_behavior_input)
        selected_index = self.scrolling_behavior_input.findData(
            self._applied_scrolling_behavior
        )
        self.scrolling_behavior_input.setCurrentIndex(selected_index)

        self.click_hold_behavior_input = QComboBox()
        self.click_hold_behavior_input.addItem(
            "Drag and drop", CATALOG_DRAG_AND_DROP
        )
        self.click_hold_behavior_input.addItem("Navigate", CATALOG_NAVIGATE)
        self.catalog_click_hold_behavior_input = self.click_hold_behavior_input
        self.image_catalog_click_hold_behavior_input = (
            self.click_hold_behavior_input
        )
        stabilize_widget_size(self.click_hold_behavior_input)
        selected_index = self.click_hold_behavior_input.findData(
            self._applied_catalog_click_hold_behavior
        )
        self.click_hold_behavior_input.setCurrentIndex(selected_index)

        # Keep the old attribute names as lightweight compatibility views for
        # integrations that inspect the pre-merged settings groups.
        self.scrolling_behavior_group = _LegacyGroupAlias(
            self.behavior_group, "Scrolling behavior"
        )
        self.deletion_behavior_group = _LegacyGroupAlias(
            self.behavior_group, "Deletion behavior"
        )

        behavior_layout = QVBoxLayout(self.behavior_group)
        behavior_form = QFormLayout()
        behavior_form.addRow("Mouse wheel", self.scrolling_behavior_input)
        behavior_form.addRow(
            "Image catalog click and hold", self.click_hold_behavior_input
        )

        self.traversal_group = QGroupBox("Traversal")
        self.image_prefetch_count_input = QSpinBox()
        self.image_prefetch_count_input.setRange(0, MAX_IMAGE_PREFETCH_COUNT)
        self.image_prefetch_count_input.setValue(
            self._applied_image_prefetch_count
        )
        self.image_prefetch_count_input.setSpecialValueText("Disabled")
        stabilize_widget_size(
            self.image_prefetch_count_input,
            minimum_width=96,
            vertical_padding=2,
        )
        traversal_layout = QFormLayout(self.traversal_group)
        traversal_layout.addRow(
            "Images to prefetch", self.image_prefetch_count_input
        )

        self.use_unlink_label = QLabel("Use unlink for...")
        self.use_unlink_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.delete_filter_use_unlink_checkbox = QCheckBox("Delete filter")
        self.delete_filter_use_unlink_checkbox.setChecked(
            self._applied_use_unlink_options[0]
        )
        self.manual_delete_use_unlink_checkbox = QCheckBox("Manual delete")
        self.manual_delete_use_unlink_checkbox.setChecked(
            self._applied_use_unlink_options[1]
        )
        self.tidy_use_unlink_checkbox = QCheckBox("Tidy")
        self.tidy_use_unlink_checkbox.setChecked(
            self._applied_use_unlink_options[2]
        )
        self.deduplicate_use_unlink_checkbox = QCheckBox("Deduplicate")
        self.deduplicate_use_unlink_checkbox.setChecked(
            self._applied_use_unlink_options[3]
        )
        for checkbox in (
            self.delete_filter_use_unlink_checkbox,
            self.manual_delete_use_unlink_checkbox,
            self.tidy_use_unlink_checkbox,
            self.deduplicate_use_unlink_checkbox,
        ):
            _stabilize_checkbox(checkbox)

        deletion_options_layout = QHBoxLayout()
        deletion_options_layout.addWidget(
            self.delete_filter_use_unlink_checkbox
        )
        deletion_options_layout.addWidget(
            self.manual_delete_use_unlink_checkbox
        )
        deletion_options_layout.addWidget(self.tidy_use_unlink_checkbox)
        deletion_options_layout.addWidget(self.deduplicate_use_unlink_checkbox)
        deletion_options_layout.addStretch(1)

        self.recycle_bin_default_label = QLabel(
            "System recycle bin is used by default if available"
        )
        self.recycle_bin_default_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        behavior_form.addRow(self.use_unlink_label)
        behavior_layout.addLayout(behavior_form)
        behavior_layout.addLayout(deletion_options_layout)
        behavior_layout.addWidget(self.recycle_bin_default_label)

        page_layout = QVBoxLayout(page)
        page_layout.addWidget(self.startup_group)
        page_layout.addWidget(self.behavior_group)
        page_layout.addWidget(self.traversal_group)
        page_layout.addStretch(1)
        self.open_recent_folder_checkbox.toggled.connect(
            self._settings_changed
        )
        self.scrolling_behavior_input.currentIndexChanged.connect(
            self._settings_changed
        )
        self.click_hold_behavior_input.currentIndexChanged.connect(
            self._settings_changed
        )
        self.image_prefetch_count_input.valueChanged.connect(
            self._settings_changed
        )
        self.delete_filter_use_unlink_checkbox.toggled.connect(
            self._settings_changed
        )
        self.manual_delete_use_unlink_checkbox.toggled.connect(
            self._settings_changed
        )
        self.tidy_use_unlink_checkbox.toggled.connect(
            self._settings_changed
        )
        self.deduplicate_use_unlink_checkbox.toggled.connect(
            self._settings_changed
        )
        return page

    def _create_models_page(self) -> QWidget:
        if not ai_dependencies_available():
            page = QWidget()
            layout = QVBoxLayout(page)
            missing = ", ".join(missing_ai_dependencies())
            layout.addWidget(
                QLabel(
                    "AI tagging model management requires these dependencies: "
                    + missing
                )
            )
            layout.addStretch(1)
            return page

        page = ModelManagementDialog(
            self,
            proxy=_resolved_proxy(
                self._applied_proxy_mode, self._applied_proxy_url
            ),
        )
        # The old management dialog is used as a page; Settings owns closing.
        page.setWindowFlags(Qt.WindowType.Widget)
        page.close_button.hide()
        return page

    def _create_autocomplete_page(self) -> QWidget:
        page = QWidget()
        self.library_group = QGroupBox("Tag Library")
        self.library_info_label = QLabel()
        self.library_info_label.setWordWrap(True)
        self.library_info_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.delete_library_button = QPushButton("Delete")
        self.delete_library_button.setStyleSheet(
            "QPushButton { color: #b42318; } "
            "QPushButton:disabled { color: #d0d5dd; }"
        )
        self.delete_library_button.clicked.connect(self._delete_tag_library)
        self.manage_tag_library_button = QPushButton("Download...")
        self.manage_tag_library_button.clicked.connect(
            self._open_tag_library_dialog
        )

        library_buttons = QHBoxLayout()
        library_buttons.addWidget(self.delete_library_button)
        library_buttons.addStretch(1)
        library_buttons.addWidget(self.manage_tag_library_button)
        library_layout = QVBoxLayout(self.library_group)
        library_layout.addWidget(self.library_info_label)
        library_layout.addLayout(library_buttons)

        self.underscores_checkbox = QCheckBox(
            "Transform underscores into spaces"
        )
        self.parentheses_checkbox = QCheckBox(
            r"Add '\' before parentheses"
        )
        _stabilize_checkbox(self.underscores_checkbox)
        _stabilize_checkbox(self.parentheses_checkbox)
        underscores, parentheses = self._applied_transform_options
        self.underscores_checkbox.setChecked(underscores)
        self.parentheses_checkbox.setChecked(parentheses)
        self.underscores_checkbox.toggled.connect(
            self._transform_options_changed
        )
        self.parentheses_checkbox.toggled.connect(
            self._transform_options_changed
        )

        self.transformation_group = QGroupBox("Transformation")
        transformation_layout = QVBoxLayout(self.transformation_group)
        transformation_layout.addWidget(self.underscores_checkbox)
        transformation_layout.addWidget(self.parentheses_checkbox)

        page_layout = QVBoxLayout(page)
        page_layout.addWidget(self.library_group)
        page_layout.addWidget(self.transformation_group)
        page_layout.addStretch(1)
        self._refresh_library_info()
        return page

    def _refresh_library_info(self) -> None:
        try:
            info = get_tag_library_file_info(self.tag_library_path)
        except FileNotFoundError:
            self.library_info_label.setText(
                "No local Danbooru tag library is installed.\n"
                f"{self.tag_library_path}"
            )
            exists = False
        except (OSError, ValueError) as exc:
            self.library_info_label.setText(
                "The local Danbooru tag library could not be read.\n"
                f"{self.tag_library_path}\n{exc}"
            )
            exists = True
        else:
            modified = info.modified_at.strftime("%Y-%m-%d %H:%M")
            self.library_info_label.setText(
                f"{info.tag_count:,} tags, "
                f"{_format_byte_size(info.file_size)}, updated {modified}.\n"
                f"{self.tag_library_path}"
            )
            exists = True
        self.delete_library_button.setEnabled(exists)

    def _delete_tag_library(self) -> None:
        if not self.tag_library_path.exists():
            self._refresh_library_info()
            return
        answer = QMessageBox.question(
            self,
            "Delete Tag Library?",
            f"Delete the local tag library?\n\n{self.tag_library_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.tag_library_path.unlink()
        except OSError as exc:
            QMessageBox.critical(self, "Could Not Delete Tag Library", str(exc))
            return
        self._library_changed(str(self.tag_library_path))

    def _open_tag_library_dialog(self) -> None:
        if self.tag_library_dialog is not None:
            self.tag_library_dialog.raise_()
            self.tag_library_dialog.activateWindow()
            return

        proxy = _resolved_proxy(
            self._applied_proxy_mode, self._applied_proxy_url
        )
        dialog = DownloadTagsDialog(
            self,
            destination=self.tag_library_path,
            proxy=proxy,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.library_changed.connect(self._library_changed)
        dialog.finished.connect(self._tag_library_dialog_finished)
        self.tag_library_dialog = dialog
        dialog.open()

    def _tag_library_dialog_finished(self, _result: int) -> None:
        self.tag_library_dialog = None

    def _create_scripting_page(self) -> QWidget:
        page = QWidget()
        self.scripting_group = QGroupBox("Python scripting")
        self.scripting_tags_input = QComboBox()
        self.scripting_tags_input.addItem(
            "TagSet", SCRIPTING_TAG_SET
        )
        self.scripting_tags_input.addItem(
            "set[str]", SCRIPTING_PLAIN_SET
        )
        stabilize_widget_size(self.scripting_tags_input)
        selected_index = self.scripting_tags_input.findData(
            self._applied_scripting_tags_type
        )
        self.scripting_tags_input.setCurrentIndex(selected_index)
        self.scripting_tag_type_input = self.scripting_tags_input
        self.scripting_mode_input = self.scripting_tags_input
        self.tags_input = self.scripting_tags_input

        form = QFormLayout(self.scripting_group)
        form.addRow("Tags parameter", self.scripting_tags_input)

        page_layout = QVBoxLayout(page)
        page_layout.addWidget(self.scripting_group)
        page_layout.addStretch(1)
        self.scripting_tags_input.currentIndexChanged.connect(
            self._settings_changed
        )
        return page

    def _create_proxy_page(self) -> QWidget:
        page = QWidget()
        self.proxy_server_group = QGroupBox("Proxy server")
        self.proxy_mode_group = QButtonGroup(page)
        self.no_proxy_radio = QRadioButton("No proxy")
        self.system_proxy_radio = QRadioButton("Use system proxy")
        self.custom_proxy_radio = QRadioButton("Custom proxy")
        for radio in (
            self.no_proxy_radio,
            self.system_proxy_radio,
            self.custom_proxy_radio,
        ):
            self.proxy_mode_group.addButton(radio)

        self.proxy_input = QLineEdit(self._applied_proxy_url)
        self.proxy_input.setPlaceholderText("http://127.0.0.1:7890")
        self.proxy_input.setClearButtonEnabled(True)
        stabilize_widget_size(self.proxy_input, minimum_width=426)
        selected_radio = {
            NO_PROXY: self.no_proxy_radio,
            SYSTEM_PROXY: self.system_proxy_radio,
            CUSTOM_PROXY: self.custom_proxy_radio,
        }[self._applied_proxy_mode]
        selected_radio.setChecked(True)
        self.proxy_input.setEnabled(self.custom_proxy_radio.isChecked())

        custom_proxy_row = QHBoxLayout()
        custom_proxy_row.setContentsMargins(0, 0, 0, 0)
        custom_proxy_row.addWidget(self.custom_proxy_radio)
        custom_proxy_row.addWidget(self.proxy_input, 1)
        group_layout = QVBoxLayout(self.proxy_server_group)
        group_layout.addWidget(self.no_proxy_radio)
        group_layout.addWidget(self.system_proxy_radio)
        group_layout.addLayout(custom_proxy_row)
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(self.proxy_server_group)
        page_layout.addStretch(1)

        self.no_proxy_radio.toggled.connect(self._proxy_selection_changed)
        self.system_proxy_radio.toggled.connect(self._proxy_selection_changed)
        self.custom_proxy_radio.toggled.connect(self._proxy_selection_changed)
        self.proxy_input.textChanged.connect(self._settings_changed)
        return page

    def _proxy_selection_changed(self, _checked: bool) -> None:
        self.proxy_input.setEnabled(self.custom_proxy_radio.isChecked())
        self._settings_changed()

    def _transform_options_changed(self, _checked: bool) -> None:
        self._settings_changed()

    def _settings_changed(self, *_args: object) -> None:
        self.apply_button.setEnabled(
            self._scrolling_behavior() != self._applied_scrolling_behavior
            or self._catalog_click_hold_behavior()
            != self._applied_catalog_click_hold_behavior
            or self.image_prefetch_count_input.value()
            != self._applied_image_prefetch_count
            or self.open_recent_folder_checkbox.isChecked()
            != self._applied_open_recent_folder_on_startup
            or self._use_unlink_options()
            != self._applied_use_unlink_options
            or self._transform_options() != self._applied_transform_options
            or self._scripting_tags_type()
            != self._applied_scripting_tags_type
            or self._proxy_preferences()
            != (self._applied_proxy_mode, self._applied_proxy_url)
        )

    def _transform_options(self) -> tuple[bool, bool]:
        return (
            self.underscores_checkbox.isChecked(),
            self.parentheses_checkbox.isChecked(),
        )

    def _scrolling_behavior(self) -> str:
        behavior = self.scrolling_behavior_input.currentData()
        return behavior if isinstance(behavior, str) else SCROLL_PAN

    def _catalog_click_hold_behavior(self) -> str:
        behavior = self.click_hold_behavior_input.currentData()
        return (
            behavior
            if isinstance(behavior, str)
            else CATALOG_DRAG_AND_DROP
        )

    def _use_unlink_options(self) -> tuple[bool, bool, bool, bool]:
        return (
            self.delete_filter_use_unlink_checkbox.isChecked(),
            self.manual_delete_use_unlink_checkbox.isChecked(),
            self.tidy_use_unlink_checkbox.isChecked(),
            self.deduplicate_use_unlink_checkbox.isChecked(),
        )

    def _scripting_tags_type(self) -> str:
        tags_type = self.scripting_tags_input.currentData()
        return tags_type if isinstance(tags_type, str) else SCRIPTING_TAG_SET

    def _proxy_preferences(self) -> tuple[str, str]:
        if self.system_proxy_radio.isChecked():
            mode = SYSTEM_PROXY
        elif self.custom_proxy_radio.isChecked():
            mode = CUSTOM_PROXY
        else:
            mode = NO_PROXY
        return mode, self.proxy_input.text().strip()

    def _apply(self) -> None:
        scrolling_behavior = self._scrolling_behavior()
        catalog_click_hold_behavior = self._catalog_click_hold_behavior()
        image_prefetch_count = self.image_prefetch_count_input.value()
        open_recent_folder_on_startup = (
            self.open_recent_folder_checkbox.isChecked()
        )
        underscores = self.underscores_checkbox.isChecked()
        parentheses = self.parentheses_checkbox.isChecked()
        use_unlink_options = self._use_unlink_options()
        scripting_tags_type = self._scripting_tags_type()
        proxy_mode, proxy_url = self._proxy_preferences()
        proxy = _resolved_proxy(proxy_mode, proxy_url)
        self.settings.setValue(SCROLLING_BEHAVIOR_SETTING, scrolling_behavior)
        self.settings.setValue(
            CATALOG_CLICK_HOLD_BEHAVIOR_SETTING,
            catalog_click_hold_behavior,
        )
        self.settings.setValue(
            IMAGE_PREFETCH_COUNT_SETTING,
            image_prefetch_count,
        )
        self.settings.setValue(
            OPEN_RECENT_FOLDER_ON_STARTUP_SETTING,
            open_recent_folder_on_startup,
        )
        self.settings.setValue(UNDERSCORES_SETTING, underscores)
        self.settings.setValue(PARENTHESES_SETTING, parentheses)
        self.settings.setValue(
            USE_UNLINK_FOR_DELETE_FILTER_SETTING,
            use_unlink_options[0],
        )
        self.settings.setValue(
            USE_UNLINK_FOR_MANUAL_DELETE_SETTING,
            use_unlink_options[1],
        )
        self.settings.setValue(
            USE_UNLINK_FOR_TIDY_SETTING,
            use_unlink_options[2],
        )
        self.settings.setValue(
            USE_UNLINK_FOR_DEDUPLICATE_SETTING,
            use_unlink_options[3],
        )
        self.settings.setValue(
            SCRIPTING_TAGS_TYPE_SETTING, scripting_tags_type
        )
        self.settings.setValue(PROXY_MODE_SETTING, proxy_mode)
        self.settings.setValue(PROXY_SETTING, proxy_url)
        self.settings.sync()
        if self.tag_library is not None:
            self.tag_library.set_transform_options(
                underscores_to_spaces=underscores,
                escape_parentheses=parentheses,
            )
        if self.tag_library_dialog is not None:
            self.tag_library_dialog.set_proxy(proxy)
        if isinstance(self.models_page, ModelManagementDialog):
            self.models_page.set_proxy(proxy)
        self.scrolling_behavior_changed.emit(scrolling_behavior)
        self.click_hold_behavior_changed.emit(catalog_click_hold_behavior)
        self.catalog_click_hold_behavior_changed.emit(
            catalog_click_hold_behavior
        )
        self._applied_scrolling_behavior = scrolling_behavior
        self._applied_catalog_click_hold_behavior = catalog_click_hold_behavior
        self._applied_image_prefetch_count = image_prefetch_count
        self._applied_open_recent_folder_on_startup = (
            open_recent_folder_on_startup
        )
        self._applied_transform_options = (underscores, parentheses)
        self._applied_use_unlink_options = use_unlink_options
        self._applied_scripting_tags_type = scripting_tags_type
        self._applied_proxy_mode = proxy_mode
        self._applied_proxy_url = proxy_url
        self.apply_button.setEnabled(False)

    def _apply_and_accept(self) -> None:
        if self._busy():
            return
        self._apply()
        super().accept()

    def _library_changed(self, _path: str) -> None:
        if self.tag_library is not None:
            self.tag_library.reload_danbooru()
        self._refresh_library_info()

    def _busy(self) -> bool:
        pages = [self.models_page]
        if self.tag_library_dialog is not None:
            pages.append(self.tag_library_dialog)
        return any(
            getattr(page, "_thread", None) is not None for page in pages
        )

    def accept(self) -> None:
        if not self._busy():
            super().accept()

    def reject(self) -> None:
        if not self._busy():
            super().reject()
