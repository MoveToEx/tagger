from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QTreeWidget

from tagger.ai_tagging.model_dialog import ModelManagementDialog
from tagger.settings.dialog import SettingsDialog
from tagger.settings.preferences import (
    CATALOG_CLICK_HOLD_BEHAVIOR_SETTING,
    CATALOG_DRAG_AND_DROP,
    CATALOG_NAVIGATE,
    IMAGE_PREFETCH_COUNT_SETTING,
    OPEN_RECENT_FOLDER_ON_STARTUP_SETTING,
    PARENTHESES_SETTING,
    PROXY_MODE_SETTING,
    PROXY_SETTING,
    SCROLLING_BEHAVIOR_SETTING,
    UNDERSCORES_SETTING,
    USE_UNLINK_FOR_DEDUPLICATE_SETTING,
    USE_UNLINK_FOR_DELETE_FILTER_SETTING,
    USE_UNLINK_FOR_MANUAL_DELETE_SETTING,
    USE_UNLINK_FOR_TIDY_SETTING,
    get_deletion_behavior,
    get_catalog_click_hold_behavior,
    get_image_prefetch_count,
    get_scrolling_behavior,
    get_use_unlink,
)
from tagger.settings.store import JsonSettings
from tagger.tag_library.download_dialog import DownloadTagsDialog
from tagger.tag_library.format import write_tag_library
from tagger.tag_library.library import TagLibrary
from tagger.trash import SYSTEM_RECYCLE_BIN, UNLINK
from tagger.ui.preview.config import (
    SCROLL_NAVIGATE,
    SCROLL_NAVIGATE_AT_END,
    SCROLL_NAVIGATE_WHEN_FITTED,
    SCROLL_PAN,
)

from .helpers import assert_stable_widget_size


def test_settings_changes_only_take_effect_when_applied(
    qtbot, tmp_path: Path
) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    settings.setValue(UNDERSCORES_SETTING, False)
    settings.setValue(PARENTHESES_SETTING, False)
    settings.sync()
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("red_hair_(long)", 100)])
    tag_library = TagLibrary(library_path)
    dialog = SettingsDialog(settings=settings, tag_library=tag_library)
    qtbot.addWidget(dialog)

    assert not dialog.apply_button.isEnabled()
    assert tag_library.suggestions("red") == ["red_hair_(long)"]

    dialog.underscores_checkbox.setChecked(True)
    assert dialog.apply_button.isEnabled()
    dialog.underscores_checkbox.setChecked(False)
    assert not dialog.apply_button.isEnabled()

    dialog.underscores_checkbox.setChecked(True)
    dialog.parentheses_checkbox.setChecked(True)

    assert settings.value(UNDERSCORES_SETTING, type=bool) is False
    assert settings.value(PARENTHESES_SETTING, type=bool) is False
    persisted = JsonSettings(settings_path)
    assert persisted.value(UNDERSCORES_SETTING, type=bool) is False
    assert persisted.value(PARENTHESES_SETTING, type=bool) is False
    assert tag_library.suggestions("red") == ["red_hair_(long)"]

    dialog.apply_button.click()

    assert not dialog.apply_button.isEnabled()
    assert settings.value(UNDERSCORES_SETTING, type=bool) is True
    assert settings.value(PARENTHESES_SETTING, type=bool) is True
    persisted = JsonSettings(settings_path)
    assert persisted.value(UNDERSCORES_SETTING, type=bool) is True
    assert persisted.value(PARENTHESES_SETTING, type=bool) is True
    assert tag_library.suggestions("red") == [r"red hair \(long\)"]


def test_general_settings_stages_scrolling_behavior(qtbot, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    settings.setValue(SCROLLING_BEHAVIOR_SETTING, SCROLL_NAVIGATE_AT_END)
    settings.sync()
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)
    applied: list[str] = []
    dialog.scrolling_behavior_changed.connect(applied.append)

    assert dialog.pages.currentWidget() is dialog.general_page
    assert dialog.scrolling_behavior_group.title() == "Scrolling behavior"
    assert [
        dialog.scrolling_behavior_input.itemText(index)
        for index in range(dialog.scrolling_behavior_input.count())
    ] == [
        "Navigate",
        "Pan",
        "Pan, Navigate when fitted to window",
        "Pan, Navigate at end",
        "Zoom",
    ]
    assert dialog.scrolling_behavior_input.currentData() == SCROLL_NAVIGATE_AT_END

    dialog.scrolling_behavior_input.setCurrentIndex(
        dialog.scrolling_behavior_input.findData(SCROLL_NAVIGATE)
    )

    assert dialog.apply_button.isEnabled()
    assert get_scrolling_behavior(settings) == SCROLL_NAVIGATE_AT_END
    dialog.apply_button.click()

    assert not dialog.apply_button.isEnabled()
    assert get_scrolling_behavior(settings) == SCROLL_NAVIGATE
    assert get_scrolling_behavior(JsonSettings(settings_path)) == SCROLL_NAVIGATE
    assert applied == [SCROLL_NAVIGATE]


def test_general_settings_stages_catalog_click_hold_behavior(
    qtbot, tmp_path: Path
) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    settings.setValue(CATALOG_CLICK_HOLD_BEHAVIOR_SETTING, CATALOG_NAVIGATE)
    settings.sync()
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.behavior_group.title() == "Behavior"
    assert [
        dialog.click_hold_behavior_input.itemText(index)
        for index in range(dialog.click_hold_behavior_input.count())
    ] == ["Drag and drop", "Navigate"]
    assert dialog.click_hold_behavior_input.currentData() == CATALOG_NAVIGATE

    dialog.click_hold_behavior_input.setCurrentIndex(
        dialog.click_hold_behavior_input.findData(CATALOG_DRAG_AND_DROP)
    )
    assert dialog.apply_button.isEnabled()
    assert get_catalog_click_hold_behavior(settings) == CATALOG_NAVIGATE

    dialog.apply_button.click()

    assert not dialog.apply_button.isEnabled()
    assert get_catalog_click_hold_behavior(settings) == CATALOG_DRAG_AND_DROP
    assert (
        get_catalog_click_hold_behavior(JsonSettings(settings_path))
        == CATALOG_DRAG_AND_DROP
    )


def test_scrolling_behavior_accepts_navigate_when_fitted(
    tmp_path: Path,
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(
        SCROLLING_BEHAVIOR_SETTING, SCROLL_NAVIGATE_WHEN_FITTED
    )

    assert get_scrolling_behavior(settings) == SCROLL_NAVIGATE_WHEN_FITTED


def test_general_settings_stages_traversal_image_prefetch_count(
    qtbot, tmp_path: Path
) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.traversal_group.title() == "Traversal"
    assert dialog.image_prefetch_count_input.value() == 2
    assert get_image_prefetch_count(settings) == 2
    assert_stable_widget_size(
        dialog.image_prefetch_count_input,
        minimum_width=96,
        vertical_padding=2,
    )

    dialog.image_prefetch_count_input.setValue(5)

    assert dialog.apply_button.isEnabled()
    assert get_image_prefetch_count(settings) == 2
    dialog.apply_button.click()

    assert not dialog.apply_button.isEnabled()
    assert get_image_prefetch_count(settings) == 5
    persisted = JsonSettings(settings_path)
    assert persisted.value(IMAGE_PREFETCH_COUNT_SETTING, type=int) == 5
    assert get_image_prefetch_count(persisted) == 5


def test_general_settings_stages_startup_folder_preference(
    qtbot, tmp_path: Path
) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.startup_group.title() == "Startup"
    assert dialog.open_recent_folder_checkbox.text() == (
        "Open the most recent folder when the app starts"
    )
    assert not dialog.open_recent_folder_checkbox.isChecked()

    dialog.open_recent_folder_checkbox.setChecked(True)

    assert dialog.apply_button.isEnabled()
    assert settings.value(
        OPEN_RECENT_FOLDER_ON_STARTUP_SETTING, False, type=bool
    ) is False
    dialog.apply_button.click()

    assert not dialog.apply_button.isEnabled()
    assert settings.value(
        OPEN_RECENT_FOLDER_ON_STARTUP_SETTING, type=bool
    ) is True
    assert JsonSettings(settings_path).value(
        OPEN_RECENT_FOLDER_ON_STARTUP_SETTING, type=bool
    ) is True


def test_general_settings_stages_use_unlink_options(
    qtbot, tmp_path: Path
) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    settings.setValue(USE_UNLINK_FOR_DELETE_FILTER_SETTING, True)
    settings.sync()
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.deletion_behavior_group.title() == "Deletion behavior"
    assert dialog.use_unlink_label.text() == "Use unlink for..."
    assert dialog.use_unlink_label.alignment() & Qt.AlignmentFlag.AlignLeft
    checkboxes = [
        dialog.delete_filter_use_unlink_checkbox,
        dialog.manual_delete_use_unlink_checkbox,
        dialog.tidy_use_unlink_checkbox,
        dialog.deduplicate_use_unlink_checkbox,
    ]
    assert [checkbox.text() for checkbox in checkboxes] == [
        "Delete filter",
        "Manual delete",
        "Tidy",
        "Deduplicate",
    ]
    deletion_layout = dialog.deletion_behavior_group.layout()
    assert deletion_layout is not None
    checkbox_layout_item = deletion_layout.itemAt(1)
    assert checkbox_layout_item is not None
    checkbox_layout = checkbox_layout_item.layout()
    assert checkbox_layout is not None
    arranged_checkboxes = []
    for index in range(4):
        checkbox_item = checkbox_layout.itemAt(index)
        assert checkbox_item is not None
        arranged_checkboxes.append(checkbox_item.widget())
    assert arranged_checkboxes == checkboxes
    assert dialog.recycle_bin_default_label.text() == (
        "System recycle bin is used by default if available"
    )
    assert (
        dialog.recycle_bin_default_label.alignment()
        & Qt.AlignmentFlag.AlignRight
    )
    assert dialog.delete_filter_use_unlink_checkbox.isChecked()
    assert not dialog.manual_delete_use_unlink_checkbox.isChecked()
    assert not dialog.deduplicate_use_unlink_checkbox.isChecked()

    dialog.deduplicate_use_unlink_checkbox.setChecked(True)
    assert dialog.apply_button.isEnabled()
    assert get_deletion_behavior(
        settings, USE_UNLINK_FOR_DEDUPLICATE_SETTING
    ) == SYSTEM_RECYCLE_BIN

    dialog.delete_filter_use_unlink_checkbox.setChecked(False)
    dialog.manual_delete_use_unlink_checkbox.setChecked(True)

    assert dialog.apply_button.isEnabled()
    assert (
        get_deletion_behavior(
            settings, USE_UNLINK_FOR_DELETE_FILTER_SETTING
        )
        == UNLINK
    )
    assert (
        get_deletion_behavior(settings, USE_UNLINK_FOR_MANUAL_DELETE_SETTING)
        == SYSTEM_RECYCLE_BIN
    )
    dialog.apply_button.click()

    persisted = JsonSettings(settings_path)
    assert persisted.value(
        USE_UNLINK_FOR_DELETE_FILTER_SETTING, type=bool
    ) is False
    assert persisted.value(
        USE_UNLINK_FOR_MANUAL_DELETE_SETTING, type=bool
    ) is True
    assert get_deletion_behavior(
        persisted, USE_UNLINK_FOR_DELETE_FILTER_SETTING
    ) == SYSTEM_RECYCLE_BIN
    assert get_deletion_behavior(
        persisted, USE_UNLINK_FOR_MANUAL_DELETE_SETTING
    ) == UNLINK
    assert not dialog.apply_button.isEnabled()

    assert get_deletion_behavior(
        persisted, USE_UNLINK_FOR_DEDUPLICATE_SETTING
    ) == UNLINK
    reopened = SettingsDialog(settings=persisted)
    qtbot.addWidget(reopened)
    assert reopened.deduplicate_use_unlink_checkbox.isChecked()
    reopened.deduplicate_use_unlink_checkbox.setChecked(False)
    reopened.reject()
    assert get_deletion_behavior(
        JsonSettings(settings_path), USE_UNLINK_FOR_DEDUPLICATE_SETTING
    ) == UNLINK


def test_general_settings_ignores_legacy_deletion_behavior(
    qtbot, tmp_path: Path
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue("general/delete_filter_deletion_behavior", UNLINK)

    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert not dialog.delete_filter_use_unlink_checkbox.isChecked()
    assert (
        get_deletion_behavior(
            settings, USE_UNLINK_FOR_DELETE_FILTER_SETTING
        )
        == SYSTEM_RECYCLE_BIN
    )


def test_general_settings_stages_tidy_use_unlink(
    qtbot, tmp_path: Path
) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    settings.setValue(USE_UNLINK_FOR_TIDY_SETTING, True)
    settings.sync()
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.tidy_use_unlink_checkbox.isChecked()

    dialog.tidy_use_unlink_checkbox.setChecked(False)
    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()

    persisted = JsonSettings(settings_path)
    assert persisted.value(USE_UNLINK_FOR_TIDY_SETTING, type=bool) is False
    assert (
        get_deletion_behavior(persisted, USE_UNLINK_FOR_TIDY_SETTING)
        == SYSTEM_RECYCLE_BIN
    )


def test_settings_select_controls_use_stable_geometry(
    qtbot, tmp_path: Path
) -> None:
    settings_dialog = SettingsDialog(
        settings=JsonSettings(tmp_path / "settings.json")
    )
    model_dialog = ModelManagementDialog()
    qtbot.addWidget(settings_dialog)
    qtbot.addWidget(model_dialog)

    for combo_box in (
        settings_dialog.scrolling_behavior_input,
        model_dialog.download_location_input,
    ):
        assert_stable_widget_size(combo_box)


def test_scrolling_behavior_defaults_to_pan(tmp_path: Path) -> None:
    settings = JsonSettings(tmp_path / "settings.json")

    assert get_scrolling_behavior(settings) == SCROLL_PAN


def test_deletion_behavior_defaults_to_system_recycle_bin(
    tmp_path: Path
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")

    assert (
        get_deletion_behavior(
            settings, USE_UNLINK_FOR_DELETE_FILTER_SETTING
        )
        == SYSTEM_RECYCLE_BIN
    )
    assert (
        get_deletion_behavior(settings, USE_UNLINK_FOR_MANUAL_DELETE_SETTING)
        == SYSTEM_RECYCLE_BIN
    )
    assert not get_use_unlink(settings, USE_UNLINK_FOR_TIDY_SETTING)


def test_settings_ok_applies_and_cancel_discards(qtbot, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.ok_button.text() == "OK"
    assert dialog.cancel_button.text() == "Cancel"
    dialog.underscores_checkbox.setChecked(True)
    dialog.ok_button.click()

    assert dialog.result() == SettingsDialog.DialogCode.Accepted
    assert settings.value(UNDERSCORES_SETTING, type=bool) is True
    persisted = JsonSettings(settings_path)
    assert persisted.value(UNDERSCORES_SETTING, type=bool) is True

    cancel_dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(cancel_dialog)
    cancel_dialog.underscores_checkbox.setChecked(False)
    cancel_dialog.cancel_button.click()

    assert cancel_dialog.result() == SettingsDialog.DialogCode.Rejected
    assert settings.value(UNDERSCORES_SETTING, type=bool) is True
    persisted = JsonSettings(settings_path)
    assert persisted.value(UNDERSCORES_SETTING, type=bool) is True


def test_tag_library_settings_separate_transformations_and_downloads(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("red_hair", 100), ("blue_eyes", 80)])
    tag_library = TagLibrary(library_path)
    dialog = SettingsDialog(
        settings=JsonSettings(tmp_path / "settings.json"),
        tag_library=tag_library,
    )
    qtbot.addWidget(dialog)

    assert dialog.transformation_group.title() == "Transformation"
    assert dialog.library_group.title() == "Tag Library"
    assert "2 tags" in dialog.library_info_label.text()
    assert f"{library_path.stat().st_size} B" in dialog.library_info_label.text()
    assert str(library_path) in dialog.library_info_label.text()
    assert dialog.delete_library_button.isEnabled()
    assert dialog.transformation_group.isAncestorOf(
        dialog.underscores_checkbox
    )
    assert dialog.transformation_group.isAncestorOf(
        dialog.parentheses_checkbox
    )
    for checkbox in (
        dialog.underscores_checkbox,
        dialog.parentheses_checkbox,
    ):
        assert "width: 12px" in checkbox.styleSheet()
        assert "height: 12px" in checkbox.styleSheet()
    assert not isinstance(dialog.autocomplete_page, DownloadTagsDialog)
    assert dialog.tag_library_dialog is None

    dialog.manage_tag_library_button.click()

    manager = dialog.tag_library_dialog
    assert isinstance(manager, DownloadTagsDialog)
    assert manager.isVisible()
    assert manager.destination == library_path
    assert not hasattr(manager, "existing_library_label")
    assert not hasattr(manager, "delete_button")
    manager.reject()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    dialog.delete_library_button.click()

    assert not library_path.exists()
    assert "No local Danbooru tag library" in dialog.library_info_label.text()
    assert not dialog.delete_library_button.isEnabled()
    assert tag_library.suggestions("red") == []


def test_settings_tree_stages_proxy_until_applied(qtbot, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    settings.setValue(PROXY_MODE_SETTING, "custom")
    settings.setValue(PROXY_SETTING, "http://old-proxy:8080")
    settings.sync()
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert isinstance(dialog.navigation_tree, QTreeWidget)
    top_level_items = [
        dialog.navigation_tree.topLevelItem(index)
        for index in range(dialog.navigation_tree.topLevelItemCount())
    ]
    assert [
        item.text(0) for item in top_level_items if item is not None
    ] == ["General", "Models", "Autocomplete", "Network"]
    assert dialog.network_item.childCount() == 1
    assert dialog.network_item.child(0).text(0) == "Proxy"
    assert dialog.network_item.isExpanded()
    assert not hasattr(dialog.autocomplete_page, "proxy_input")

    dialog.manage_tag_library_button.click()
    manager = dialog.tag_library_dialog
    assert manager is not None
    assert manager.proxy == "http://old-proxy:8080"
    manager.reject()

    dialog.navigation_tree.setCurrentItem(dialog.proxy_item)
    assert dialog.pages.currentWidget() is dialog.proxy_page
    assert dialog.proxy_server_group.title() == "Proxy server"
    assert dialog.custom_proxy_radio.isChecked()
    assert dialog.proxy_input.isEnabled()
    assert dialog.proxy_input.text() == "http://old-proxy:8080"
    assert_stable_widget_size(dialog.proxy_input, minimum_width=426)

    dialog.proxy_input.setText("  http://new-proxy:3128  ")

    assert dialog.apply_button.isEnabled()
    assert settings.value(PROXY_SETTING, type=str) == "http://old-proxy:8080"
    persisted = JsonSettings(settings_path)
    assert persisted.value(PROXY_SETTING, type=str) == "http://old-proxy:8080"

    dialog.apply_button.click()

    assert not dialog.apply_button.isEnabled()
    assert settings.value(PROXY_MODE_SETTING, type=str) == "custom"
    assert settings.value(PROXY_SETTING, type=str) == "http://new-proxy:3128"
    persisted = JsonSettings(settings_path)
    assert persisted.value(PROXY_SETTING, type=str) == "http://new-proxy:3128"

    dialog.manage_tag_library_button.click()
    manager = dialog.tag_library_dialog
    assert manager is not None
    assert manager.proxy == "http://new-proxy:3128"
    manager.reject()


def test_proxy_url_without_mode_defaults_to_no_proxy(
    qtbot, tmp_path: Path
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(PROXY_SETTING, "http://old-proxy:8080")
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.no_proxy_radio.isChecked()
    assert not dialog.proxy_input.isEnabled()

    dialog.manage_tag_library_button.click()
    manager = dialog.tag_library_dialog
    assert manager is not None
    assert manager.proxy == ""
    manager.reject()


def test_proxy_page_supports_none_system_and_custom_modes(
    qtbot, tmp_path: Path
) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.no_proxy_radio.text() == "No proxy"
    assert dialog.system_proxy_radio.text() == "Use system proxy"
    assert dialog.custom_proxy_radio.text() == "Custom proxy"
    assert dialog.no_proxy_radio.isChecked()
    assert not dialog.proxy_input.isEnabled()

    dialog.system_proxy_radio.click()

    assert dialog.system_proxy_radio.isChecked()
    assert not dialog.proxy_input.isEnabled()
    dialog.apply_button.click()
    assert settings.value(PROXY_MODE_SETTING, type=str) == "system"

    dialog.manage_tag_library_button.click()
    manager = dialog.tag_library_dialog
    assert manager is not None
    assert manager.proxy is None
    manager.reject()

    dialog.custom_proxy_radio.click()
    dialog.proxy_input.setText("http://localhost:7890")

    assert dialog.custom_proxy_radio.isChecked()
    assert dialog.proxy_input.isEnabled()
    dialog.apply_button.click()
    assert settings.value(PROXY_MODE_SETTING, type=str) == "custom"

    dialog.manage_tag_library_button.click()
    manager = dialog.tag_library_dialog
    assert manager is not None
    assert manager.proxy == "http://localhost:7890"
    manager.reject()

    dialog.no_proxy_radio.click()

    assert dialog.no_proxy_radio.isChecked()
    assert not dialog.proxy_input.isEnabled()
    dialog.apply_button.click()
    assert settings.value(PROXY_MODE_SETTING, type=str) == "none"

    dialog.manage_tag_library_button.click()
    manager = dialog.tag_library_dialog
    assert manager is not None
    assert manager.proxy == ""
    manager.reject()
