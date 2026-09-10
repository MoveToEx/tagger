from __future__ import annotations

from collections.abc import Callable
import threading
import zipfile
from pathlib import Path

import pytest

from PySide6.QtCore import (
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QImage,
    QPainter,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProxyStyle,
    QSizePolicy,
    QStyle,
    QStyleOptionSpinBox,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QWidget,
)

import tagger.main_window as main_window_module
import tagger.archive as archive_module
import tagger.ai_tagger as ai_tagger_module
import tagger.trash as trash_module
from tagger.ai_tagger import (
    AI_DEPENDENCIES,
    AITaggingDialog,
    MODEL_REPOSITORIES,
    ModelManagementDialog,
)
from tagger.storage import ArchiveResult
from tagger.bulk_operation import BulkOperationDialog
from tagger.domain import ImageEntry, TagOperation
from tagger.complex_filter import ComplexFilterDialog
from tagger.delete_filter import DeleteFilterDialog, DeleteFilterProgressDialog
from tagger.main_window import MAX_RECENT_FOLDERS, RECENT_FOLDERS_SETTING, MainWindow
from tagger.global_search import GlobalTagSearchDialog
from tagger.preview import (
    SCROLL_NAVIGATE,
    SCROLL_NAVIGATE_AT_END,
    SCROLL_PAN,
    SCROLL_ZOOM,
    ImageView,
    PreviewLoader,
)
from tagger.review import ReviewDialog
from tagger.settings import (
    IMAGE_PREFETCH_COUNT_SETTING,
    JsonSettings,
    OPEN_RECENT_FOLDER_ON_STARTUP_SETTING,
    PARENTHESES_SETTING,
    PROXY_MODE_SETTING,
    PROXY_SETTING,
    SCROLLING_BEHAVIOR_SETTING,
    SettingsDialog,
    UNDERSCORES_SETTING,
    USE_UNLINK_FOR_DELETE_FILTER_SETTING,
    USE_UNLINK_FOR_DEDUPLICATE_SETTING,
    USE_UNLINK_FOR_MANUAL_DELETE_SETTING,
    USE_UNLINK_FOR_TIDY_SETTING,
    get_deletion_behavior,
    get_image_prefetch_count,
    get_scrolling_behavior,
    get_use_unlink,
)
from tagger.tag_library import (
    DownloadTagsDialog,
    TagLibrary,
    attach_tag_completer,
    write_tag_library,
)
from tagger.traversal import TraversalDialog
from tagger.trash import SYSTEM_RECYCLE_BIN, UNLINK
from tagger.widgets import _StableCheckedToolButtonStyle


def create_png(path: Path, color: str = "#2f6fed") -> None:
    image = QImage(32, 24, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def create_cached_model(cache_directory: Path, repo_id: str) -> None:
    snapshot = (
        cache_directory
        / f"models--{repo_id.replace('/', '--')}"
        / "snapshots"
        / "revision"
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").touch()
    (snapshot / "selected_tags.csv").touch()


def test_ai_dependency_availability_is_cached(monkeypatch) -> None:
    checked: list[str] = []

    def find_spec(name: str):
        checked.append(name)
        return None if name == "torch" else object()

    ai_tagger_module.ai_dependencies_available.cache_clear()
    monkeypatch.setattr(ai_tagger_module.importlib.util, "find_spec", find_spec)
    try:
        assert not ai_tagger_module.ai_dependencies_available()
        assert not ai_tagger_module.ai_dependencies_available()
        assert checked == list(AI_DEPENDENCIES)
    finally:
        ai_tagger_module.ai_dependencies_available.cache_clear()


def assert_stable_widget_size(
    widget: QWidget,
    *,
    minimum_width: int = 0,
    vertical_padding: int = 0,
) -> None:
    assert widget.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
    assert widget.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert widget.minimumWidth() == widget.maximumWidth()
    assert widget.width() >= max(widget.sizeHint().width() + 8, minimum_width)
    assert widget.width() % 2 == 0
    assert widget.minimumHeight() == widget.maximumHeight()
    assert widget.height() >= widget.sizeHint().height() + vertical_padding
    assert widget.height() % 2 == 0


def render_spin_box_control(
    spin_box: QDoubleSpinBox, *, hovered: bool
) -> QImage:
    option = QStyleOptionSpinBox()
    spin_box.initStyleOption(option)
    option.state &= ~QStyle.StateFlag.State_MouseOver
    option.activeSubControls = QStyle.SubControl.SC_None
    if hovered:
        option.state |= QStyle.StateFlag.State_MouseOver
        option.activeSubControls = QStyle.SubControl.SC_SpinBoxUp

    image = QImage(spin_box.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    spin_box.style().drawComplexControl(
        QStyle.ComplexControl.CC_SpinBox, option, painter, spin_box
    )
    assert painter.end()
    return image


def test_model_settings_support_local_downloads_and_report_locations(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    repositories = list(MODEL_REPOSITORIES.values())
    user_cache = tmp_path / "user-cache"
    local_cache = tmp_path / "data" / "model"
    create_cached_model(user_cache, repositories[0])
    create_cached_model(local_cache, repositories[1])
    create_cached_model(user_cache, repositories[2])
    create_cached_model(local_cache, repositories[2])
    monkeypatch.setattr(
        ai_tagger_module,
        "_user_model_cache_directory",
        lambda: user_cache,
    )

    dialog = ModelManagementDialog()
    qtbot.addWidget(dialog)

    header = dialog.models.headerItem()
    assert header is not None
    assert [header.text(column) for column in range(4)] == [
        "Model",
        "Repository",
        "Status",
        "Location",
    ]
    rows = [
        dialog.models.topLevelItem(index)
        for index in range(dialog.models.topLevelItemCount())
    ]
    assert [item.text(2) for item in rows if item is not None] == [
        "Available",
        "Available",
        "Available",
        "Not downloaded",
    ]
    assert [item.text(3) for item in rows if item is not None] == [
        "User home",
        "Local data",
        "User home, Local data",
        "",
    ]
    assert dialog.download_location_input.currentText() == "User home directory"
    assert dialog.download_location_path_label.text() == str(user_cache)

    dialog.download_location_input.setCurrentIndex(1)

    assert dialog.download_location_input.currentText() == "Local data directory"
    assert dialog.download_location_path_label.text() == str(local_cache)
    assert dialog._selected_download_cache_directory() == local_cache
    assert ai_tagger_module._preferred_model_cache_directory(
        repositories[1]
    ) == local_cache


def test_model_download_worker_uses_selected_cache_directory(
    tmp_path: Path, monkeypatch
) -> None:
    destination = tmp_path / "data" / "model"
    calls: list[tuple[str, Path | None]] = []
    monkeypatch.setattr(
        ai_tagger_module,
        "_configure_huggingface_proxy",
        lambda _proxy: None,
    )

    import huggingface_hub

    monkeypatch.setattr(
        huggingface_hub,
        "snapshot_download",
        lambda *, repo_id, cache_dir: calls.append((repo_id, cache_dir)),
    )
    repo_id = next(iter(MODEL_REPOSITORIES.values()))
    worker = ai_tagger_module._ModelDownloadWorker(repo_id, "", destination)
    completed: list[str] = []
    worker.completed.connect(completed.append)

    worker.run()

    assert calls == [(repo_id, destination)]
    assert completed == [repo_id]


def test_ai_tagger_disables_absent_models_in_selector(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    repositories = list(MODEL_REPOSITORIES.values())
    available_repo = repositories[2]
    monkeypatch.setattr(
        ai_tagger_module,
        "_cached_model_locations",
        lambda repo_id: ["Local data"] if repo_id == available_repo else [],
    )
    entry = ImageEntry(
        tmp_path / "image.png",
        tmp_path / "image.txt",
        source_bytes=b"",
    )

    dialog = AITaggingDialog([entry], root_directory=tmp_path)
    qtbot.addWidget(dialog)

    assert_stable_widget_size(dialog.model_input)
    assert_stable_widget_size(
        dialog.general_threshold_input, vertical_padding=2
    )
    assert_stable_widget_size(
        dialog.character_threshold_input, vertical_padding=2
    )
    for threshold_input in (
        dialog.general_threshold_input,
        dialog.character_threshold_input,
    ):
        assert render_spin_box_control(
            threshold_input, hovered=False
        ) == render_spin_box_control(threshold_input, hovered=True)

    dialog.show()
    qtbot.mouseClick(
        dialog.general_threshold_input,
        Qt.MouseButton.LeftButton,
        pos=QPoint(dialog.general_threshold_input.width() - 8, 5),
    )
    assert dialog.general_threshold_input.value() == 0.4

    model = dialog.model_input.model()
    assert [
        bool(model.flags(model.index(index, 0)) & Qt.ItemFlag.ItemIsEnabled)
        for index in range(dialog.model_input.count())
    ] == [False, False, True, False]
    assert dialog.model_input.currentData() == available_repo
    assert dialog.start_button.isEnabled()

    monkeypatch.setattr(
        ai_tagger_module,
        "_cached_model_locations",
        lambda _repo_id: [],
    )
    empty_dialog = AITaggingDialog([entry], root_directory=tmp_path)
    qtbot.addWidget(empty_dialog)

    assert empty_dialog.model_input.currentIndex() == -1
    assert not empty_dialog.start_button.isEnabled()


def test_ai_tagger_apply_all_ignores_tag_decisions(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name, tags in {"first.png": ["cat"], "second.png": ["dog"]}.items():
        image_path = tmp_path / name
        tag_path = tmp_path / f"{Path(name).stem}.txt"
        create_png(image_path)
        source_bytes = (", ".join(tags) + "\n").encode()
        tag_path.write_bytes(source_bytes)
        entries.append(
            ImageEntry(
                image_path,
                tag_path,
                tags=tags,
                source_bytes=source_bytes,
            )
        )

    dialog = AITaggingDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)
    dialog._selected_entries = entries
    results = {
        str(entries[0].image_path): [("first", 0.9), ("second", 0.8)],
        str(entries[1].image_path): [("third", 0.95)],
    }
    dialog._inference_completed(results)

    assert dialog.apply_all_button.text() == "Apply All"
    dialog.ai_tags.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.next_button.click()
    dialog.apply_all_button.click()

    assert dialog.result() == AITaggingDialog.DialogCode.Accepted
    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "cat, first, second\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "dog, third\n"
    )


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
    ] == ["Navigate", "Pan", "Pan, Navigate at end", "Zoom"]
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


def test_tag_autocomplete_double_click_inserts_tag(qtbot, tmp_path: Path) -> None:
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("red_hair", 100), ("blue_eyes", 80)])
    library = TagLibrary(library_path)
    host = QWidget()
    line_edit = QLineEdit(host)
    line_edit.resize(240, 28)
    host.resize(240, 28)
    qtbot.addWidget(host)
    completer = attach_tag_completer(line_edit, library)
    assert completer is not None

    host.show()
    line_edit.setFocus()
    line_edit.setText("red")
    qtbot.waitUntil(lambda: completer.popup().isVisible())

    index = completer.popup().model().index(0, 0)
    qtbot.mouseDClick(
        completer.popup().viewport(),
        Qt.MouseButton.LeftButton,
        pos=completer.popup().visualRect(index).center(),
    )

    assert line_edit.text() == "red_hair"
    qtbot.wait(100)
    assert not completer.popup().isVisible()


def test_tag_autocomplete_single_click_keeps_popup_visible(
    qtbot, tmp_path: Path
) -> None:
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("red_hair", 100), ("blue_eyes", 80)])
    library = TagLibrary(library_path)
    host = QWidget()
    line_edit = QLineEdit(host)
    line_edit.resize(240, 28)
    host.resize(240, 28)
    qtbot.addWidget(host)
    completer = attach_tag_completer(line_edit, library)
    assert completer is not None

    host.show()
    line_edit.setFocus()
    line_edit.setText("red")
    qtbot.waitUntil(lambda: completer.popup().isVisible())

    index = completer.popup().model().index(0, 0)
    qtbot.mouseClick(
        completer.popup().viewport(),
        Qt.MouseButton.LeftButton,
        pos=completer.popup().visualRect(index).center(),
    )

    assert line_edit.text() == "red"
    assert completer.popup().isVisible()
    assert completer.popup().currentIndex() == index


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


def test_main_window_loads_folder_and_edits_current_tags(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog, cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)

    window._load_directory(tmp_path, show_issues=False)

    assert window.catalog.rowCount() == 1
    assert window.add_tag_button.text() == "+"
    assert window.add_tag_button.width() == 34
    assert window.image_list.currentIndex().row() == 0
    assert [window.tag_list.item(i).text() for i in range(window.tag_list.count())] == [
        "dog",
        "cat",
    ]
    assert window.windowTitle() == f"{tmp_path.name} - Image Tagger"
    assert window.bulk_operation_action.isEnabled()

    qtbot.waitUntil(lambda: "32 × 24 px" in window.image_info_label.text())
    image_info = window.image_info_label.text()
    assert "sample.png" not in image_info
    assert "PNG" in image_info
    assert image_info.endswith(" B")

    window.tag_input.setText("bird")
    window._add_current_tags()
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == (
        "bird, cat, dog\n"
    )


def test_file_menu_opens_recent_folder(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    current = tmp_path / "current"
    recent_a = tmp_path / "recent-a"
    recent_b = tmp_path / "recent-b"
    for folder in (current, recent_a, recent_b):
        folder.mkdir()
        create_png(folder / "sample.png")
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(
        RECENT_FOLDERS_SETTING,
        [str(recent_a), str(recent_b)],
    )
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.directory is None
    assert window.open_recent_action.text() == "Open Recent"
    assert window.open_recent_action.isEnabled()
    assert window.open_recent_menu.title() == "Open Recent"
    assert [action.text() for action in window.open_recent_menu.actions()] == [
        str(recent_a),
        str(recent_b),
    ]
    file_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&File"
    )
    assert file_menu is not None
    assert window.open_recent_action in file_menu.actions()

    window._load_directory(current, show_issues=False)

    assert window.directory == current
    assert window.open_recent_action.isEnabled()
    window._update_recent_folder_menu()
    recent_action = next(
        action
        for action in window.open_recent_menu.actions()
        if action.text() == str(recent_b)
    )
    recent_action.trigger()

    assert window.directory == recent_b
    assert window.open_recent_action.isEnabled()
    assert window.catalog.image_count == 1
    assert settings.value(RECENT_FOLDERS_SETTING) == [
        str(recent_b),
        str(current),
        str(recent_a),
    ]


def test_file_menu_tidy_deletes_unrecognized_files(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    unknown = tmp_path / "notes.json"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    unknown.write_text("{}", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)

    window._load_directory(tmp_path, show_issues=False)
    assert window.tidy_action.isEnabled()
    file_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&File"
    )
    assert window.tidy_action in file_menu.actions()

    prompts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message, *_args: (
            prompts.append((title, message))
            or QMessageBox.StandardButton.Yes
        ),
    )
    monkeypatch.setattr(
        main_window_module,
        "delete_file",
        lambda path, behavior: path.unlink() or True,
    )

    window.tidy_action.trigger()

    assert not unknown.exists()
    assert image_path.exists()
    assert tag_path.exists()
    assert prompts[0][0] == "Delete Unrecognized Files?"
    assert "1 unrecognized file(s)" in prompts[0][1]


def test_tidy_uses_unlink_setting(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    unknown = tmp_path / "notes.json"
    unknown.write_text("{}", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.settings.setValue(USE_UNLINK_FOR_TIDY_SETTING, True)
    window._load_directory(tmp_path, show_issues=False)
    behaviors: list[str] = []

    def fake_delete_file(path: Path, behavior: str) -> bool:
        behaviors.append(behavior)
        path.unlink()
        return True

    monkeypatch.setattr(main_window_module, "delete_file", fake_delete_file)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    window._tidy_folder()

    assert behaviors == [UNLINK]
    assert not unknown.exists()
    assert window.statusBar().currentMessage() == (
        "Permanently deleted 1 unrecognized file(s)."
    )


def test_open_folder_uses_most_recent_folder(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    recent = tmp_path / "recent"
    recent.mkdir()
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(RECENT_FOLDERS_SETTING, [str(recent)])
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )
    starts: list[str] = []

    def get_existing_directory(_parent, _title: str, start: str) -> str:
        starts.append(start)
        return ""

    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getExistingDirectory",
        get_existing_directory,
    )

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_folder()

    assert starts == [str(recent)]


def test_main_window_opens_most_recent_folder_on_startup(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    recent_a = tmp_path / "recent-a"
    recent_b = tmp_path / "recent-b"
    for folder in (recent_a, recent_b):
        folder.mkdir()
        create_png(folder / "sample.png")
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(OPEN_RECENT_FOLDER_ON_STARTUP_SETTING, True)
    settings.setValue(
        RECENT_FOLDERS_SETTING,
        [str(recent_a), str(recent_b)],
    )
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.directory == recent_a
    assert window.catalog.image_count == 1
    assert window.windowTitle() == f"{recent_a.name} - Image Tagger"
    qtbot.waitUntil(lambda: "32 × 24 px" in window.image_info_label.text())


def test_folder_load_emits_one_current_image_change(
    qtbot, tmp_path: Path
) -> None:
    for index in range(40):
        create_png(tmp_path / f"image-{index:02d}.png")
        (tmp_path / f"image-{index:02d}.txt").write_text(
            "cat, dog\n", encoding="utf-8"
        )
    window = MainWindow()
    qtbot.addWidget(window)
    current_changes: list[QModelIndex] = []
    window.image_list.selectionModel().currentChanged.connect(
        lambda current, _previous: current_changes.append(current)
    )

    window._load_directory(tmp_path, show_issues=False)

    assert len(current_changes) == 1
    assert window.catalog.entry_for_index(current_changes[0]) is not None
    assert window.preview_loader.wait_for_done()


def test_file_menu_disables_missing_recent_folder(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(
        RECENT_FOLDERS_SETTING,
        [str(tmp_path / "missing")],
    )
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.directory is None
    assert not window.open_recent_action.isEnabled()
    assert window.open_recent_menu.actions() == []
    assert window.open_recent_action.toolTip() == (
        "No recently opened folder is available."
    )


def test_recent_folders_are_deduplicated_and_capped(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    monkeypatch.setattr(
        main_window_module, "create_app_settings", lambda: settings
    )
    folders = [tmp_path / f"folder-{index}" for index in range(12)]
    for folder in folders:
        folder.mkdir()
    window = MainWindow()
    qtbot.addWidget(window)

    for folder in folders:
        window._record_recent_folder(folder)
    window._record_recent_folder(folders[-3])

    recent = settings.value(RECENT_FOLDERS_SETTING)
    assert isinstance(recent, list)
    assert recent == [
        str(folders[-3]),
        *[
            str(folder)
            for folder in reversed(folders)
            if folder != folders[-3]
        ][: MAX_RECENT_FOLDERS - 1],
    ]


def test_main_window_uses_saved_tag_transformations_before_settings_open(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(UNDERSCORES_SETTING, True)
    settings.setValue(PARENTHESES_SETTING, True)
    settings.sync()
    library_path = tmp_path / "tags.bin"
    write_tag_library(library_path, [("red_hair_(long)", 100)])

    def create_library(*, parent=None, **options):
        return TagLibrary(library_path, parent=parent, **options)

    monkeypatch.setattr(main_window_module, "create_app_settings", lambda: settings)
    monkeypatch.setattr(main_window_module, "TagLibrary", create_library)

    window = MainWindow()
    qtbot.addWidget(window)

    assert window.tag_library.suggestions("red") == [r"red hair \(long\)"]


def test_navigation_actions_stop_at_boundaries(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "a.png")
    create_png(tmp_path / "b.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)

    assert not window.previous_action.isEnabled()
    assert window.next_action.isEnabled()
    window.next_action.trigger()
    assert window.image_list.currentIndex().row() == 1
    assert not window.next_action.isEnabled()
    assert window.previous_action.isEnabled()


def test_toolbar_uses_navigation_and_zoom_icons(
    qtbot, tmp_path: Path
) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitUntil(lambda: window.image_view._pixmap is not None)
    toolbar = window.findChild(QToolBar)
    assert toolbar is not None

    toolbar_actions_with_icons = [
        window.open_action,
        window.close_folder_action,
        window.previous_action,
        window.next_action,
        window.zoom_in_action,
        window.fit_action,
        window.zoom_out_action,
    ]
    buttons: dict[QAction, QToolButton] = {}
    for action in toolbar_actions_with_icons:
        widget = toolbar.widgetForAction(action)
        assert isinstance(widget, QToolButton)
        assert not action.icon().isNull()
        assert not action.isIconVisibleInMenu()
        assert (
            widget.toolButtonStyle()
            == Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        buttons[action] = widget

    toolbar_actions = toolbar.actions()
    assert toolbar_actions[:2] == [
        window.open_action,
        window.close_folder_action,
    ]
    assert toolbar_actions[2].isSeparator()
    assert toolbar_actions.index(window.zoom_in_action) < toolbar_actions.index(
        window.fit_action
    ) < toolbar_actions.index(window.zoom_out_action)

    assert window.previous_action.text() == "Previous"
    assert window.next_action.text() == "Next"
    initial_zoom = window.image_view._zoom
    buttons[window.zoom_in_action].click()
    assert window.image_view._zoom > initial_zoom
    buttons[window.zoom_out_action].click()
    assert window.image_view._zoom == initial_zoom


def test_checked_toolbar_style_only_suppresses_released_button_shift(qtbot) -> None:
    class ShiftStyle(QProxyStyle):
        def pixelMetric(self, metric, option=None, widget=None) -> int:
            if metric in {
                QStyle.PixelMetric.PM_ButtonShiftHorizontal,
                QStyle.PixelMetric.PM_ButtonShiftVertical,
            }:
                return 2
            return super().pixelMetric(metric, option, widget)

    button = QToolButton()
    qtbot.addWidget(button)
    button.setCheckable(True)
    style = _StableCheckedToolButtonStyle(ShiftStyle())
    style.setParent(button)
    button.setStyle(style)
    horizontal_shift = QStyle.PixelMetric.PM_ButtonShiftHorizontal

    button.setChecked(True)
    button.setDown(False)
    assert style.pixelMetric(horizontal_shift, None, button) == 0

    button.setDown(True)
    assert style.pixelMetric(horizontal_shift, None, button) == 2

    button.setDown(False)
    button.setChecked(False)
    assert style.pixelMetric(horizontal_shift, None, button) == 2


def test_mouse_wheel_navigate_setting_changes_images_and_menu_item_is_removed(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "a.png")
    create_png(tmp_path / "b.png")
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(SCROLLING_BEHAVIOR_SETTING, SCROLL_NAVIGATE)
    monkeypatch.setattr(main_window_module, "create_app_settings", lambda: settings)
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    navigate_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&Navigate"
    )
    assert all(
        action.text() != "Scroll to Navigate"
        for action in navigate_menu.actions()
    )
    assert window.image_view._scrolling_behavior == SCROLL_NAVIGATE
    wheel = QWheelEvent(
        window.image_view.viewport().rect().center(),
        window.image_view.viewport().mapToGlobal(
            window.image_view.viewport().rect().center()
        ),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QGuiApplication.sendEvent(window.image_view.viewport(), wheel)

    assert window.image_list.currentIndex().row() == 1


def test_zoom_scroll_behavior_zooms_instead_of_navigating(
    qtbot, tmp_path: Path
) -> None:
    create_png(tmp_path / "a.png")
    create_png(tmp_path / "b.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)
    qtbot.waitUntil(lambda: window.image_view._pixmap is not None)
    window.image_view.set_scrolling_behavior(SCROLL_ZOOM)
    initial_zoom = window.image_view._zoom
    wheel = QWheelEvent(
        window.image_view.viewport().rect().center(),
        window.image_view.viewport().mapToGlobal(
            window.image_view.viewport().rect().center()
        ),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    QGuiApplication.sendEvent(window.image_view.viewport(), wheel)

    assert window.image_list.currentIndex().row() == 0
    assert not window.fit_action.isChecked()
    assert window.image_view._zoom > initial_zoom


def test_ctrl_wheel_keeps_zoom_override(qtbot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(800, 600, QImage.Format.Format_RGB32)
    image.fill(QColor("#2f6fed"))
    view.resize(400, 300)
    view.set_image(image)
    view.set_scrolling_behavior(SCROLL_PAN)
    view.show()
    qtbot.waitExposed(view)
    initial_zoom = view._zoom
    wheel = QWheelEvent(
        view.viewport().rect().center(),
        view.viewport().mapToGlobal(view.viewport().rect().center()),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    QGuiApplication.sendEvent(view.viewport(), wheel)

    assert view._zoom > initial_zoom
    assert not view.fit_to_window


def test_navigate_at_end_scrolls_until_directional_boundary_then_navigates(
    qtbot,
) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(800, 1200, QImage.Format.Format_RGB32)
    image.fill(QColor("#2f6fed"))
    view.resize(400, 300)
    view.set_fit_to_window(False)
    view.set_image(image)
    view.set_scrolling_behavior(SCROLL_NAVIGATE_AT_END)
    view.show()
    qtbot.waitExposed(view)
    navigation: list[int] = []
    view.navigation_requested.connect(navigation.append)
    scrollbar = view.verticalScrollBar()
    assert scrollbar.maximum() > scrollbar.minimum()
    scrollbar.setValue(scrollbar.maximum() // 2)
    initial_value = scrollbar.value()

    pan_event = QWheelEvent(
        view.viewport().rect().center(),
        view.viewport().mapToGlobal(view.viewport().rect().center()),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QGuiApplication.sendEvent(view.viewport(), pan_event)

    assert scrollbar.value() > initial_value
    assert navigation == []

    scrollbar.setValue(scrollbar.maximum())
    next_event = QWheelEvent(
        view.viewport().rect().center(),
        view.viewport().mapToGlobal(view.viewport().rect().center()),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QGuiApplication.sendEvent(view.viewport(), next_event)
    scrollbar.setValue(scrollbar.minimum())
    previous_event = QWheelEvent(
        view.viewport().rect().center(),
        view.viewport().mapToGlobal(view.viewport().rect().center()),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QGuiApplication.sendEvent(view.viewport(), previous_event)

    assert navigation == [1, -1]


def test_archive_action_compresses_open_folder_without_hierarchy(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    nested = source / "nested"
    destination = tmp_path / "archive.zip"
    nested.mkdir(parents=True)
    create_png(nested / "sample.png")
    (nested / "sample.txt").write_bytes(b"cat\n")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(source, show_issues=False)
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(destination), "Zip archives (*.zip)"),
    )

    assert window.archive_action.text() == "Archive..."
    assert window.archive_action.isEnabled()
    window.archive_action.trigger()

    assert window._archive_dialog is not None
    assert window._archive_dialog.isVisible()
    qtbot.waitUntil(lambda: destination.exists())
    qtbot.waitUntil(lambda: window._archive_dialog is None)
    with zipfile.ZipFile(destination) as archive:
        assert archive.namelist() == ["sample.png", "sample.txt"]
        assert archive.read("sample.txt") == b"cat\n"
    assert "Archived 1 image/tag pair" in window.statusBar().currentMessage()


def test_archive_progress_window_shows_current_file(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    create_png(source / "sample.png")
    (source / "sample.txt").write_bytes(b"cat\n")
    destination = tmp_path / "archive.zip"
    release_worker = threading.Event()

    def fake_archive_entries(entries, archive_path, progress):
        progress(1, 2, "sample.png")
        release_worker.wait(timeout=5)
        progress(2, 2, "sample.txt")
        return ArchiveResult([("sample.png", "sample.txt")])

    monkeypatch.setattr(archive_module, "archive_entries", fake_archive_entries)
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(destination), "Zip archives (*.zip)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(source, show_issues=False)

    window.archive_action.trigger()
    try:
        qtbot.waitUntil(
            lambda: window._archive_dialog is not None
            and window._archive_dialog.current_file_label.text()
            == "Archiving: sample.png"
        )
        assert window._archive_dialog is not None
        assert window._archive_dialog.progress_bar.value() == 1
        assert window._archive_dialog.progress_bar.maximum() == 2
        assert not window.archive_action.isEnabled()
    finally:
        release_worker.set()

    qtbot.waitUntil(lambda: window._archive_dialog is None)


def test_image_context_delete_moves_image_and_tag_to_trash(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    for name in ["first", "second"]:
        create_png(tmp_path / f"{name}.png")
        (tmp_path / f"{name}.txt").write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    moved: list[Path] = []

    def fake_delete_file(path: Path, behavior: str) -> bool:
        assert behavior == SYSTEM_RECYCLE_BIN
        moved.append(path)
        path.unlink()
        return True

    monkeypatch.setattr(main_window_module, "delete_file", fake_delete_file)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    assert (
        window.image_list.contextMenuPolicy()
        == Qt.ContextMenuPolicy.CustomContextMenu
    )
    window._delete_current_image_and_tag()

    assert moved == [tmp_path / "first.png", tmp_path / "first.txt"]
    assert not (tmp_path / "first.png").exists()
    assert not (tmp_path / "first.txt").exists()
    assert window.catalog.image_count == 1
    current = window._current_entry()
    assert current is not None
    assert current.image_path == tmp_path / "second.png"


def test_manual_delete_uses_unlink_setting(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.settings.setValue(USE_UNLINK_FOR_MANUAL_DELETE_SETTING, True)
    window._load_directory(tmp_path, show_issues=False)
    behaviors: list[str] = []
    prompts: list[tuple[str, str]] = []

    def fake_delete_file(path: Path, behavior: str) -> bool:
        behaviors.append(behavior)
        path.unlink()
        return True

    monkeypatch.setattr(main_window_module, "delete_file", fake_delete_file)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message, *_args: (
            prompts.append((title, message))
            or QMessageBox.StandardButton.Yes
        ),
    )

    window._delete_current_image_and_tag()

    assert behaviors == [UNLINK, UNLINK]
    assert prompts[0][0] == "Permanently Delete Image and Tag?"
    assert "This cannot be undone." in prompts[0][1]
    assert not image_path.exists()
    assert not tag_path.exists()


def test_image_context_menu_renames_selected_image_and_tag(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args: ("renamed", True),
    )

    menu = window._create_image_context_menu()
    assert [action.text() for action in menu.actions()] == [
        "Rename...",
        "Delete",
        "",
        "Reveal in Explorer",
    ]
    assert menu.actions()[2].isSeparator()
    menu.actions()[0].trigger()

    assert not image_path.exists()
    assert not tag_path.exists()
    assert (tmp_path / "renamed.png").exists()
    assert (tmp_path / "renamed.txt").read_text(encoding="utf-8") == "cat\n"
    current = window._current_entry()
    assert current is not None
    assert current.image_path == tmp_path / "renamed.png"
    assert "Renamed pair to renamed.png and renamed.txt" in (
        window.statusBar().currentMessage()
    )


def test_image_catalog_f2_renames_selected_image(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args: ("renamed", True),
    )

    window.image_list.setFocus()
    qtbot.keyClick(window.image_list, Qt.Key.Key_F2)

    assert not image_path.exists()
    assert not tag_path.exists()
    assert (tmp_path / "renamed.png").exists()
    assert (tmp_path / "renamed.txt").read_text(encoding="utf-8") == "cat\n"


def test_image_catalog_delete_confirms_and_deletes_selected_image(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    prompts: list[str] = []
    dialog_options: list[
        tuple[QMessageBox.StandardButton, QMessageBox.StandardButton]
    ] = []

    def confirm_delete(
        _parent,
        _title: str,
        message: str,
        buttons: QMessageBox.StandardButton,
        default_button: QMessageBox.StandardButton,
    ) -> QMessageBox.StandardButton:
        prompts.append(message)
        dialog_options.append((buttons, default_button))
        return QMessageBox.StandardButton.Yes

    def fake_delete_file(path: Path, behavior: str) -> bool:
        assert behavior == SYSTEM_RECYCLE_BIN
        path.unlink()
        return True

    monkeypatch.setattr(QMessageBox, "question", confirm_delete)
    monkeypatch.setattr(main_window_module, "delete_file", fake_delete_file)

    window.image_list.setFocus()
    qtbot.keyClick(window.image_list, Qt.Key.Key_Delete)

    assert len(prompts) == 1
    assert "sample.png" in prompts[0]
    assert "sample.txt" in prompts[0]
    assert dialog_options == [
        (
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
    ]
    assert not image_path.exists()
    assert not tag_path.exists()


def test_image_catalog_keys_require_selected_image(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.image_list.clearSelection()
    assert window.image_list.currentIndex().isValid()
    calls: list[str] = []
    monkeypatch.setattr(
        window,
        "_rename_current_image_and_tag",
        lambda: calls.append("rename"),
    )
    monkeypatch.setattr(
        window,
        "_delete_current_image_and_tag",
        lambda: calls.append("delete"),
    )

    window.image_list.setFocus()
    qtbot.keyClick(window.image_list, Qt.Key.Key_F2)
    qtbot.keyClick(window.image_list, Qt.Key.Key_Delete)

    assert calls == []


def test_image_context_menu_reveals_selected_image_in_explorer(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample image.png"
    create_png(image_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    started: list[tuple[str, list[str]]] = []

    class FakeQProcess:
        @staticmethod
        def startDetached(
            program: str, arguments: list[str]
        ) -> tuple[bool, int]:
            started.append((program, arguments))
            return True, 123

    monkeypatch.setattr(main_window_module, "QProcess", FakeQProcess)

    menu = window._create_image_context_menu()
    menu.actions()[3].trigger()

    assert started == [
        ("explorer.exe", ["/select,", str(image_path)]),
    ]


def test_image_context_rename_collision_keeps_pair(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    create_png(tmp_path / "taken.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args: ("taken", True),
    )
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, message: errors.append((title, message)),
    )

    window._rename_current_image_and_tag()

    assert image_path.exists()
    assert tag_path.read_text(encoding="utf-8") == "cat\n"
    assert errors
    assert errors[0][0] == "Could Not Rename Image and Tag"


def test_move_to_trash_uses_qfile_instance_api(monkeypatch, tmp_path: Path) -> None:
    opened: list[str] = []

    class FakeQFile:
        def __init__(self, path: str) -> None:
            opened.append(path)

        def moveToTrash(self) -> bool:
            return True

    monkeypatch.setattr(trash_module, "QFile", FakeQFile)
    path = tmp_path / "sample.png"

    assert trash_module.move_to_trash(path)
    assert opened == [str(path)]


def test_image_context_delete_can_be_cancelled(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Cancel,
    )
    monkeypatch.setattr(
        main_window_module,
        "delete_file",
        lambda _path, _behavior: (_ for _ in ()).throw(
            AssertionError("cancelled deletion must not move files")
        ),
    )

    window._delete_current_image_and_tag()

    assert image_path.exists()
    assert tag_path.exists()


def test_image_menu_exposes_delete_filter_for_open_folder(
    qtbot, tmp_path: Path
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    image_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&Image"
    )
    assert image_menu.actions() == [window.delete_filter_action, window.deduplicate_action]
    assert window.delete_filter_action.text() == "Delete Filter..."
    assert not window.delete_filter_action.isEnabled()

    create_png(tmp_path / "sample.png")
    window._load_directory(tmp_path, show_issues=False)

    assert window.delete_filter_action.isEnabled()


def test_delete_filter_uses_configured_deletion_behavior(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.settings.setValue(
        USE_UNLINK_FOR_DELETE_FILTER_SETTING, True
    )
    window.settings.setValue(IMAGE_PREFETCH_COUNT_SETTING, 4)
    window._load_directory(tmp_path, show_issues=False)
    captured_deleters: list[Callable[[Path], bool]] = []
    captured_behaviors: list[str] = []
    captured_prefetch_counts: list[int] = []

    class FakeDeleteFilterDialog:
        class DialogCode:
            Accepted = 1

        commit_result = None

        def __init__(
            self,
            _entries,
            _parent,
            *,
            file_deleter,
            deletion_behavior: str,
            image_prefetch_count: int,
        ) -> None:
            captured_deleters.append(file_deleter)
            captured_behaviors.append(deletion_behavior)
            captured_prefetch_counts.append(image_prefetch_count)

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(
        main_window_module, "DeleteFilterDialog", FakeDeleteFilterDialog
    )
    window._open_delete_filter()

    assert captured_behaviors == [UNLINK]
    assert captured_prefetch_counts == [4]
    delete_candidate = tmp_path / "delete-me.txt"
    delete_candidate.write_text("content", encoding="utf-8")
    assert captured_deleters[0](delete_candidate)
    assert not delete_candidate.exists()


def test_delete_filter_shortcuts_toggle_and_navigate(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second", "third"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_text("cat\n", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))
    dialog = DeleteFilterDialog(entries)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.current_index == 0
    assert not dialog.delete_checkbox.isChecked()
    assert dialog.findChildren(QGroupBox) == []
    assert dialog.delete_checkbox.styleSheet() == (
        "QCheckBox::indicator { width: 12px; height: 12px; }"
    )
    checkbox_position = dialog.delete_checkbox.mapTo(dialog, QPoint())
    cancel_position = dialog.cancel_button.mapTo(dialog, QPoint())
    back_position = dialog.back_button.mapTo(dialog, QPoint())
    next_position = dialog.next_button.mapTo(dialog, QPoint())
    finish_position = dialog.finish_button.mapTo(dialog, QPoint())
    assert checkbox_position.y() < back_position.y()
    assert cancel_position.x() < back_position.x()
    assert back_position.x() < next_position.x() < finish_position.x()
    assert cancel_position.y() == back_position.y()
    qtbot.keyClick(dialog, Qt.Key.Key_Space)
    assert dialog.delete_checkbox.isChecked()
    assert dialog.marked_for_deletion == {tmp_path / "first.png"}

    qtbot.keyClick(dialog, Qt.Key.Key_Right)
    assert dialog.current_index == 1
    assert not dialog.delete_checkbox.isChecked()
    qtbot.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.current_index == 2
    qtbot.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.current_index == 1
    dialog._back()
    assert dialog.current_index == 0
    assert dialog.delete_checkbox.isChecked()
    assert "Marked for deletion 1" in dialog.progress_label.text()


def test_delete_filter_uses_simple_fitted_image_click_decisions(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second", "third"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_text("cat\n", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))
    dialog = DeleteFilterDialog(entries)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    qtbot.waitUntil(
        lambda: dialog.image_view.pixmap() is not None
        and not dialog.image_view.pixmap().isNull()
    )

    assert isinstance(dialog.image_view, QLabel)
    assert not isinstance(dialog.image_view, ImageView)
    assert not hasattr(dialog.image_view, "zoom_in")
    assert not hasattr(dialog.image_view, "horizontalScrollBar")
    displayed = dialog.image_view.pixmap()
    assert displayed is not None
    assert displayed.width() <= dialog.image_view.contentsRect().width()
    assert displayed.height() <= dialog.image_view.contentsRect().height()
    dialog._toggle_current()
    qtbot.mouseClick(
        dialog.image_view,
        Qt.MouseButton.LeftButton,
    )

    assert dialog.current_index == 1
    assert tmp_path / "first.png" not in dialog.marked_for_deletion
    qtbot.waitUntil(
        lambda: dialog.image_view.pixmap() is not None
        and not dialog.image_view.pixmap().isNull()
    )
    qtbot.mouseClick(
        dialog.image_view,
        Qt.MouseButton.RightButton,
    )

    assert dialog.current_index == 2
    assert dialog.marked_for_deletion == {tmp_path / "second.png"}
    qtbot.waitUntil(
        lambda: dialog.image_view.pixmap() is not None
        and not dialog.image_view.pixmap().isNull()
    )
    qtbot.mouseClick(
        dialog.image_view,
        Qt.MouseButton.RightButton,
    )

    assert dialog.current_index == 2
    assert dialog.delete_checkbox.isChecked()
    assert dialog.marked_for_deletion == {
        tmp_path / "second.png",
        tmp_path / "third.png",
    }


def test_delete_filter_finishes_early_and_keeps_unreviewed_images(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second", "third"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_text("cat\n", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))
    moved: list[Path] = []

    def fake_move_to_trash(path: Path) -> bool:
        moved.append(path)
        path.unlink()
        return True

    dialog = DeleteFilterDialog(entries, file_deleter=fake_move_to_trash)
    qtbot.addWidget(dialog)
    dialog._toggle_current()
    prompts: list[tuple[str, str]] = []
    answers = iter(
        [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes]
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message, *_args: (
            prompts.append((title, message)) or next(answers)
        ),
    )

    dialog._finish()
    assert moved == []
    assert dialog.commit_result is None
    assert all(
        path.exists()
        for entry in entries
        for path in (entry.image_path, entry.tag_path)
    )
    dialog._finish()

    assert prompts == [
        (
            "Delete Marked Images?",
            "Move 1 marked image(s) and their tag files "
            "to the system Recycle Bin?",
        ),
        (
            "Delete Marked Images?",
            "Move 1 marked image(s) and their tag files "
            "to the system Recycle Bin?",
        ),
    ]
    assert moved == [tmp_path / "first.png", tmp_path / "first.txt"]
    assert dialog.result() == DeleteFilterDialog.DialogCode.Accepted
    assert dialog.commit_result is not None
    assert dialog.commit_result.complete
    assert dialog.commit_result.deleted_images == [tmp_path / "first.png"]
    for name in ["second", "third"]:
        assert (tmp_path / f"{name}.png").exists()
        assert (tmp_path / f"{name}.txt").exists()


def test_delete_filter_progress_dialog_updates_while_deleting(
    qtbot, tmp_path: Path
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    entry = ImageEntry(image_path, tag_path, ["cat"], b"cat\n")
    release_worker = threading.Event()

    def fake_move_to_trash(path: Path) -> bool:
        if path == image_path:
            release_worker.wait(timeout=5)
        path.unlink()
        return True

    dialog = DeleteFilterProgressDialog(
        [entry], fake_move_to_trash, lambda: True
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.start()
    try:
        qtbot.waitUntil(
            lambda: dialog.current_file_label.text()
            == "Moving to Recycle Bin: sample.png"
        )
        assert dialog.isVisible()
        assert dialog.progress_bar.value() == 0
        assert dialog.progress_bar.maximum() == 2
        dialog.reject()
        assert dialog.isVisible()
    finally:
        release_worker.set()

    qtbot.waitUntil(lambda: not dialog._running)
    assert dialog.commit_result is not None
    assert dialog.commit_result.complete
    assert dialog.commit_result.deleted_images == [image_path]
    assert dialog.commit_result.deleted_files == [image_path, tag_path]
    assert dialog.progress_bar.value() == 2


def test_delete_filter_unlink_confirmation_warns_deletion_is_permanent(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    dialog = DeleteFilterDialog(
        [ImageEntry(image_path, tag_path, ["cat"], b"cat\n")],
        file_deleter=lambda _path: True,
        deletion_behavior=UNLINK,
    )
    qtbot.addWidget(dialog)
    dialog._toggle_current()
    prompts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message, *_args: (
            prompts.append((title, message))
            or QMessageBox.StandardButton.Cancel
        ),
    )

    dialog._finish()

    assert prompts == [
        (
            "Permanently Delete Marked Images?",
            "Permanently delete 1 marked image(s) and their tag files?\n\n"
            "This cannot be undone.",
        )
    ]
    assert dialog.commit_result is None
    assert image_path.exists()
    assert tag_path.exists()


def test_delete_filter_cancel_confirms_staged_changes(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_text("cat\n", encoding="utf-8")
    dialog = DeleteFilterDialog(
        [ImageEntry(image_path, tag_path, ["cat"], b"cat\n")],
        file_deleter=lambda _path: False,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._toggle_current()
    answers = iter(
        [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Discard]
    )
    prompts: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, _title, message, *_args: (
            prompts.append(message) or next(answers)
        ),
    )

    dialog.reject()
    assert dialog.isVisible()
    dialog.reject()

    assert len(prompts) == 2
    assert all("uncommitted changes" in message for message in prompts)
    assert dialog.result() == DeleteFilterDialog.DialogCode.Rejected
    assert image_path.exists()
    assert tag_path.exists()


def test_image_list_groups_images_by_subfolder(qtbot, tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    deep = nested / "deep"
    nested.mkdir()
    deep.mkdir()
    create_png(tmp_path / "root.png")
    create_png(nested / "child.png")
    create_png(deep / "grandchild.png")
    window = MainWindow()
    qtbot.addWidget(window)

    window._load_directory(tmp_path, show_issues=False)

    assert window.catalog.rowCount() == 2
    nested_index = window.catalog.index(0, 0)
    assert window.catalog.data(nested_index) == "nested"
    assert window.catalog.entry_for_index(nested_index) is None
    assert window.catalog.rowCount(nested_index) == 2
    assert window.catalog.data(window.catalog.index(0, 0, nested_index)) == "deep"
    assert window.catalog.data(
        window.catalog.index(1, 0, nested_index)
    ).startswith("child.png")
    assert window.catalog.data(window.catalog.index(1, 0)).startswith("root.png")
    assert window.catalog.group_for_row(0) == "Root folder"
    assert window.catalog.group_for_row(1) == "nested"
    assert window.catalog.group_for_row(2) == "nested/deep"

    window.image_list.collapse(nested_index)
    assert not window.image_list.isExpanded(nested_index)
    window.image_list.expand(nested_index)
    assert window.image_list.isExpanded(nested_index)
    window.next_action.trigger()
    current = window._current_entry()
    assert current is not None
    assert current.image_path == nested / "child.png"
    window.next_action.trigger()
    current = window._current_entry()
    assert current is not None
    assert current.image_path == deep / "grandchild.png"
    assert not window.next_action.isEnabled()


def test_close_folder_empties_program_state(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog, cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.tag_input.setText("bird")
    window.search_input.setText("cat")

    assert window.close_folder_action.isEnabled()
    window.close_folder_action.trigger()

    assert window.directory is None
    assert window.catalog.rowCount() == 0
    assert not window.image_list.currentIndex().isValid()
    assert window.tag_list.count() == 0
    assert window.tag_input.text() == ""
    assert window.search_input.text() == ""
    assert window.image_view._pixmap is None
    assert window.image_view._label.text() == "Open a folder to begin"
    assert window.image_info_label.text() == "No image selected"
    assert window.windowTitle() == "Image Tagger"
    assert window.statusBar().currentMessage() == ""
    assert not window.close_folder_action.isEnabled()
    assert not window.rescan_action.isEnabled()
    assert not window.tidy_action.isEnabled()
    assert not window.archive_action.isEnabled()
    assert not window.search_input.isEnabled()
    assert not window.tag_input.isEnabled()
    assert not window.bulk_operation_action.isEnabled()


def test_image_view_zoom_scroll_and_drag_pan(qtbot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(800, 600, QImage.Format.Format_RGB32)
    image.fill(QColor("#2f6fed"))
    view.resize(400, 300)
    view.set_image(image)
    view.show()
    qtbot.waitExposed(view)

    assert view.fit_to_window
    initial_size = view._label.size()
    wheel = QWheelEvent(
        view.viewport().rect().center(),
        view.viewport().mapToGlobal(view.viewport().rect().center()),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    view.set_scrolling_behavior(SCROLL_ZOOM)
    QGuiApplication.sendEvent(view.viewport(), wheel)

    assert not view.fit_to_window
    assert view._label.width() > initial_size.width()
    assert view._label.pixmap().isNull()
    assert view._label._source_pixmap is view._pixmap
    scroll_before_drag = view.horizontalScrollBar().value()

    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(200, 150))
    qtbot.mouseMove(view.viewport(), QPoint(150, 150))
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(150, 150))

    assert view.horizontalScrollBar().value() > scroll_before_drag


def test_image_view_preserves_aspect_ratio_at_small_zoom(qtbot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(1000, 600, QImage.Format.Format_RGB32)
    image.fill(QColor("#2f6fed"))
    view.resize(400, 300)
    view.set_fit_to_window(False)
    view.set_image(image)
    view._zoom = 0.1
    view._update_pixmap()

    assert view._label.size() == QSize(100, 60)
    assert view._label.minimumSize() == QSize(0, 0)
    assert view._label.width() / view._label.height() == 1000 / 600


def test_close_folder_allows_another_folder_drop(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.close_folder()

    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(tmp_path))])
    drag_event = QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    window.dragEnterEvent(drag_event)

    assert drag_event.isAccepted()


def test_toolbar_tag_search_cycles_and_supports_wildcards(qtbot, tmp_path: Path) -> None:
    for name, tags in {
        "a.png": "cat\n",
        "b.png": "dog\n",
        "c.png": "cat, night_scene\n",
    }.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    window.search_input.setText("cat")
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 2
    assert [item.text() for item in window.tag_list.selectedItems()] == ["cat"]
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 0
    assert [item.text() for item in window.tag_list.selectedItems()] == ["cat"]

    window.search_input.setText("night*")
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 2
    assert [item.text() for item in window.tag_list.selectedItems()] == [
        "night_scene"
    ]


def test_toolbar_tag_search_enter_accepts_active_completion(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog\n", encoding="utf-8")
    library_path = tmp_path / "data" / "tag-lib" / "danbooru_tags.bin"
    write_tag_library(library_path, [("red", 100)])

    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    window.search_input.setFocus()
    window.search_input.setText("red")
    completer = window.search_completer
    assert completer is not None
    qtbot.waitUntil(lambda: completer.popup().isVisible())
    first_index = completer.popup().model().index(0, 0)
    completion = str(first_index.data())

    qtbot.keyClick(window.search_input, Qt.Key.Key_Down)
    assert completer.popup().currentIndex().isValid()

    searches: list[int] = []
    monkeypatch.setattr(
        window, "_find_tag", lambda direction=1: searches.append(direction)
    )
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)

    assert searches == []
    assert window.search_input.text() == completion


def test_toolbar_tag_search_finds_remaining_matches_in_current_file(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {
        "a.png": "\n",
        "b.png": "match_one, match_two\n",
        "c.png": "match_three\n",
    }.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    window.search_input.setText("match_*")
    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 1
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_one"]

    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 1
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_two"]

    qtbot.keyClick(window.search_input, Qt.Key.Key_Return)
    assert window.image_list.currentIndex().row() == 2
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_three"]


def test_toolbar_tag_search_moves_backwards_with_shift_enter(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {
        "a.png": "match_one\n",
        "b.png": "match_two, match_three\n",
        "c.png": "match_four\n",
    }.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")

    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)
    window.search_input.setText("match_*")

    qtbot.keyClick(
        window.search_input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.image_list.currentIndex().row() == 2
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_four"]

    qtbot.keyClick(
        window.search_input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.image_list.currentIndex().row() == 1
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_three"]

    qtbot.keyClick(
        window.search_input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.image_list.currentIndex().row() == 1
    assert [item.text() for item in window.tag_list.selectedItems()] == ["match_two"]


def test_global_tag_search_shows_matching_tag_counts(qtbot, tmp_path: Path) -> None:
    entries = [
        ImageEntry(tmp_path / "one.png", tmp_path / "one.txt", ["cat", "dog"]),
        ImageEntry(
            tmp_path / "two.png",
            tmp_path / "two.txt",
            ["cat", "cathedral"],
        ),
    ]
    dialog = GlobalTagSearchDialog(entries)
    qtbot.addWidget(dialog)

    dialog.pattern_input.setText("cat*")
    dialog.search()

    tag_header = dialog.results.horizontalHeaderItem(0)
    count_header = dialog.results.horizontalHeaderItem(1)
    assert tag_header is not None
    assert count_header is not None
    assert tag_header.text() == "Tag name"
    assert count_header.text() == "Tag count"
    assert dialog.count_label.text() == (
        "2 matching tag(s) across 3 image occurrence(s)."
    )
    assert dialog.results.rowCount() == 2
    values: list[tuple[str, str]] = []
    for row in range(dialog.results.rowCount()):
        tag_item = dialog.results.item(row, 0)
        count_item = dialog.results.item(row, 1)
        assert tag_item is not None
        assert count_item is not None
        values.append((tag_item.text(), count_item.text()))
    assert values == [("cat", "2"), ("cathedral", "1")]

    dialog.pattern_input.setText("dog")
    dialog.search()

    tag_header = dialog.results.horizontalHeaderItem(0)
    count_header = dialog.results.horizontalHeaderItem(1)
    assert tag_header is not None
    assert count_header is not None
    assert tag_header.text() == "Tag name"
    assert count_header.text() == "Tag count"


def test_global_tag_search_copies_selected_table_rows(qtbot, tmp_path: Path) -> None:
    entries = [
        ImageEntry(tmp_path / "one.png", tmp_path / "one.txt", ["cat", "dog"]),
        ImageEntry(tmp_path / "two.png", tmp_path / "two.txt", ["cat", "bird"]),
    ]
    dialog = GlobalTagSearchDialog(entries)
    qtbot.addWidget(dialog)
    dialog.pattern_input.setText("*")
    dialog.search()

    dialog.results.clearSelection()
    for row in (0, 2):
        dialog.results.selectionModel().select(
            dialog.results.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )
    dialog._copy_selected_tags()

    assert QGuiApplication.clipboard().text() == "bird, dog"


def test_global_search_action_requires_an_open_folder(qtbot, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window.global_search_action.isEnabled()

    create_png(tmp_path / "sample.png")
    window._load_directory(tmp_path, show_issues=False)

    assert window.global_search_action.isEnabled()


def test_complex_filter_is_modeless_and_keeps_main_window_available(
    qtbot, tmp_path: Path
) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)

    window._open_complex_filter()
    dialog = window._complex_filter_dialog
    assert dialog is not None
    assert not dialog.isModal()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert window.image_list.isEnabled()
    window._select_row(0)
    assert window._current_entry() is not None

    window._open_complex_filter()
    assert window._complex_filter_dialog is dialog


def test_complex_filter_double_click_selects_image_in_main_window(
    qtbot, tmp_path: Path
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    for name, folder in [("first.png", tmp_path), ("second.png", nested)]:
        create_png(folder / name)
        (folder / f"{Path(name).stem}.txt").write_text(
            "cat\n", encoding="utf-8"
        )

    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window._open_complex_filter()
    dialog = window._complex_filter_dialog
    assert dialog is not None

    dialog.run_filter()
    result_item = dialog.results.item(1, 0)
    assert result_item is not None
    dialog.results.itemDoubleClicked.emit(result_item)

    current = window._current_entry()
    assert current is not None
    assert current.image_path == nested / "second.png"


def test_normalize_applies_to_all_images_after_confirmation(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    for name, tags in {
        "first": "zebra, apple\n",
        "second": "night, bird\n",
    }.items():
        create_png(tmp_path / f"{name}.png")
        (tmp_path / f"{name}.txt").write_text(
            tags, encoding="utf-8", newline="\n"
        )

    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window._select_row(1)
    assert TagOperation.NORMALIZE not in window.folder_tag_actions
    assert window.normalize_action.isEnabled()
    confirmations: list[str] = []

    def cancel(_parent, _title, message, *_args):
        confirmations.append(message)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    window.normalize_action.trigger()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "zebra, apple\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "night, bird\n"
    )
    assert "all 2 editable image(s)" in confirmations[0]
    assert "2 sidecar file(s) will change" in confirmations[0]

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    window.normalize_action.trigger()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "apple, zebra\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "bird, night\n"
    )
    assert window.image_list.currentIndex().row() == 1
    assert window.statusBar().currentMessage() == "Normalized tags in 2 file(s)."


def test_dropped_folder_replaces_open_folder(qtbot, tmp_path: Path) -> None:
    first_folder = tmp_path / "first"
    second_folder = tmp_path / "second"
    first_folder.mkdir()
    second_folder.mkdir()
    create_png(first_folder / "first.png")
    create_png(second_folder / "second.png")
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(first_folder))])
    window = MainWindow()
    qtbot.addWidget(window)

    drag_event = QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(drag_event)
    assert drag_event.isAccepted()

    drop_event = QDropEvent(
        QPointF(20, 20),
        Qt.DropAction.CopyAction,
        mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop_event)
    assert drop_event.isAccepted()
    assert window.directory == first_folder
    assert window.catalog.rowCount() == 1

    window.tag_input.setText("stale tag")
    window.search_input.setText("stale search")
    replacement_mime_data = QMimeData()
    replacement_mime_data.setUrls([QUrl.fromLocalFile(str(second_folder))])
    second_drag = QDragEnterEvent(
        QPoint(20, 20),
        Qt.DropAction.CopyAction,
        replacement_mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(second_drag)
    assert second_drag.isAccepted()

    second_drop = QDropEvent(
        QPointF(20, 20),
        Qt.DropAction.CopyAction,
        replacement_mime_data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(second_drop)

    assert second_drop.isAccepted()
    assert window.directory == second_folder
    assert window.catalog.rowCount() == 1
    assert window.catalog.entries[0].image_path == second_folder / "second.png"
    assert window.tag_input.text() == ""
    assert window.search_input.text() == ""


def test_tag_context_copy_uses_comma_space_separator(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog, cat, bird\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)

    window.tag_list.item(0).setSelected(True)
    window.tag_list.item(2).setSelected(True)
    assert window.tag_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    window._copy_selected_tags()

    assert QGuiApplication.clipboard().text() == "dog, bird"


@pytest.mark.parametrize(
    ("label", "operation"),
    [
        ("Add tags", TagOperation.ADD),
        ("Delete tags", TagOperation.DELETE),
        ("Toggle tags", TagOperation.TOGGLE),
    ],
)
@pytest.mark.parametrize("selected_rows", [(1,), (2, 0)])
def test_tag_context_send_to_prefills_traversal(
    qtbot, tmp_path: Path, monkeypatch, label, operation, selected_rows
) -> None:
    create_png(tmp_path / "sample.png")
    tag_path = tmp_path / "sample.txt"
    tag_path.write_text("dog, cat, blue sky\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.tag_list.clearSelection()
    for row in selected_rows:
        window.tag_list.item(row).setSelected(True)
    opened: list[tuple[TagOperation, str]] = []

    def inspect_dialog(dialog):
        qtbot.addWidget(dialog)
        opened.append((dialog._operation, dialog.tag_input.text()))
        assert not dialog._started
        return TraversalDialog.DialogCode.Rejected

    monkeypatch.setattr(TraversalDialog, "exec", inspect_dialog)
    menu = window._create_tag_context_menu()
    assert menu.actions()[-2].isSeparator()
    send_to = menu.actions()[-1].menu()
    assert isinstance(send_to, QMenu)
    assert send_to.title() == "Send to"
    assert [action.text() for action in send_to.actions()] == [
        "Add tags", "Delete tags", "Toggle tags", "Global search"
    ]
    next(action for action in send_to.actions() if action.text() == label).trigger()

    expected_tags = ", ".join(
        window.tag_list.item(row).text() for row in sorted(selected_rows)
    )
    assert opened == [(operation, expected_tags)]
    assert tag_path.read_text(encoding="utf-8") == "dog, cat, blue sky\n"


@pytest.mark.parametrize("selected_rows", [(), (2,), (0, 2)])
def test_tag_context_send_to_global_search_requires_one_tag(
    qtbot, tmp_path: Path, monkeypatch, selected_rows
) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("dog, cat, blue sky\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    window.tag_list.clearSelection()
    for row in selected_rows:
        window.tag_list.item(row).setSelected(True)
    opened: list[str] = []

    def inspect_dialog(dialog):
        qtbot.addWidget(dialog)
        opened.append(dialog.pattern_input.text())
        return GlobalTagSearchDialog.DialogCode.Rejected

    monkeypatch.setattr(GlobalTagSearchDialog, "exec", inspect_dialog)
    send_to = window._create_tag_context_menu().actions()[-1].menu()
    assert isinstance(send_to, QMenu)
    assert send_to.isEnabled() == bool(selected_rows)
    search_action = send_to.actions()[-1]
    assert search_action.isEnabled() == (len(selected_rows) == 1)
    search_action.trigger()
    assert opened == (["blue sky"] if len(selected_rows) == 1 else [])

    window.global_search_action.trigger()
    assert opened[-1] == ""


def test_main_tag_deletion_requires_confirmation_from_button_and_context_menu(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    tag_path = tmp_path / "sample.txt"
    tag_path.write_text("dog, cat, bird\n", encoding="utf-8", newline="\n")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)

    window.tag_list.item(0).setSelected(True)
    window.tag_list.item(2).setSelected(True)
    confirmations: list[tuple[str, str]] = []
    answers = iter(
        [
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        ]
    )

    def confirm(_parent, title, message, *_args):
        confirmations.append((title, message))
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", confirm)

    window.delete_tag_button.click()
    assert tag_path.read_text(encoding="utf-8") == "dog, cat, bird\n"

    context_menu = window._create_tag_context_menu()
    assert context_menu.actions()[1].text() == "Delete"
    context_menu.actions()[1].trigger()

    assert tag_path.read_text(encoding="utf-8") == "cat\n"
    assert len(confirmations) == 2
    assert all(title == "Delete Selected Tags?" for title, _ in confirmations)
    assert all("2 selected tag(s)" in message for _, message in confirmations)
    assert all("dog, bird" in message for _, message in confirmations)
    assert [item.text() for item in window.tag_list.selectedItems()] == []


def test_preview_loader_ignores_stale_generation(qtbot, tmp_path: Path) -> None:
    loader = PreviewLoader()
    received: list[str] = []
    loader.loaded.connect(lambda _image, error: received.append(error))
    path = tmp_path / "sample.png"
    loader._current_path = path
    loader._desired_paths = {path}
    loader._inflight[path] = 2

    loader._worker_finished(path, 1, QImage(), "stale")
    loader._worker_finished(path, 2, QImage(), "current")

    assert received == ["current"]


def test_preview_loader_caches_prefetched_images_without_emitting_them(
    qtbot, tmp_path: Path
) -> None:
    paths = [tmp_path / f"image-{index}.png" for index in range(3)]
    for path in paths:
        create_png(path)
    loader = PreviewLoader()
    received: list[tuple[QImage, str]] = []
    loader.loaded.connect(
        lambda image, error: received.append((image, error))
    )

    loader.load(paths[0], paths[1:])

    qtbot.waitUntil(lambda: set(loader._cache) == set(paths))
    assert len(received) == 1
    assert not received[0][0].isNull()
    assert received[0][1] == ""

    loader.load(paths[1], paths[2:])

    assert len(received) == 2
    assert not received[1][0].isNull()
    assert received[1][1] == ""
    assert set(loader._cache) == set(paths[1:])


def test_traversal_does_not_write_until_finish(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    tag_path = tmp_path / "sample.txt"
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(
        image_path=tmp_path / "sample.png",
        tag_path=tag_path,
        tags=["cat"],
        source_bytes=b"cat\n",
    )
    dialog = TraversalDialog([entry], TagOperation.ADD, ["dog"])
    qtbot.addWidget(dialog)

    assert dialog.choices.item(0).checkState() == Qt.CheckState.Unchecked
    dialog.choices.item(0).setCheckState(Qt.CheckState.Checked)
    assert tag_path.read_bytes() == b"cat\n"
    assert dialog.finish_button.isEnabled()

    dialog._finish()
    assert tag_path.read_bytes() == b"cat, dog\n"


def test_toggle_traversal_checks_existing_tags_and_hides_apply_all(
    qtbot, tmp_path: Path
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat, bird\n")
    entry = ImageEntry(image_path, tag_path, ["cat", "bird"], b"cat, bird\n")

    dialog = TraversalDialog([entry], TagOperation.TOGGLE, ["cat", "dog"])
    qtbot.addWidget(dialog)

    checked = [
        dialog.choices.item(row).text()
        for row in range(dialog.choices.count())
        if dialog.choices.item(row).checkState() == Qt.CheckState.Checked
    ]
    assert checked == ["cat"]
    assert not dialog.apply_all_button.isVisible()
    assert not dialog.apply_all_button.isEnabled()


def test_traversal_apply_all_requires_confirmation_and_commits_all_options(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    entries: list[ImageEntry] = []
    for name, tags in {"first": "cat\n", "second": "bird\n"}.items():
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_bytes(tags.encode())
        entries.append(
            ImageEntry(
                image_path=image_path,
                tag_path=tag_path,
                tags=tags.strip().split(", "),
                source_bytes=tags.encode(),
            )
        )

    dialog = TraversalDialog(entries, TagOperation.ADD, ["dog", "night"])
    qtbot.addWidget(dialog)
    confirmations: list[str] = []

    def cancel(_parent, _title, message, *_args):
        confirmations.append(message)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", cancel)
    dialog.apply_all_button.click()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "cat\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "bird\n"
    assert "2 sidecar file(s) will change" in confirmations[0]

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    dialog.apply_all_button.click()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "cat, dog, night\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "bird, dog, night\n"
    )
    assert dialog.commit_result is not None
    assert dialog.commit_result.complete


def test_traversal_keyboard_navigation_selects_toggles_and_moves(qtbot, tmp_path: Path) -> None:
    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    create_png(first_image)
    create_png(second_image)
    first_tag = tmp_path / "first.txt"
    second_tag = tmp_path / "second.txt"
    first_tag.write_bytes(b"cat\n")
    second_tag.write_bytes(b"dog\n")
    entries = [
        ImageEntry(first_image, first_tag, ["cat"], b"cat\n"),
        ImageEntry(second_image, second_tag, ["dog"], b"dog\n"),
    ]
    dialog = TraversalDialog(entries, TagOperation.ADD, ["bird", "night"])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.choices.currentRow() == 0
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Down)
    assert dialog.choices.currentRow() == 1
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Up)
    assert dialog.choices.currentRow() == 0
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Down)
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Space)
    assert dialog.choices.item(1).checkState() == Qt.CheckState.Checked

    qtbot.keyClick(dialog.choices, Qt.Key.Key_Return)
    assert dialog.session.current_index == 1
    assert dialog.session.staged[0] == ("cat", "night")
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Left)
    assert dialog.session.current_index == 0
    assert dialog.choices.item(1).checkState() == Qt.CheckState.Checked
    qtbot.keyClick(dialog.choices, Qt.Key.Key_Right)
    assert dialog.session.current_index == 1


def test_traversal_a_shortcut_toggles_all_options(qtbot, tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(image_path, tag_path, ["cat"], b"cat\n")
    dialog = TraversalDialog(
        entries=[entry],
        operation=TagOperation.ADD,
        requested_tags=["dog", "bird"],
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert [
        dialog.choices.item(row).checkState()
        for row in range(dialog.choices.count())
    ] == [Qt.CheckState.Unchecked, Qt.CheckState.Unchecked]
    qtbot.keyClick(dialog.choices, Qt.Key.Key_A)
    assert all(
        dialog.choices.item(row).checkState() == Qt.CheckState.Checked
        for row in range(dialog.choices.count())
    )
    qtbot.keyClick(dialog.choices, Qt.Key.Key_A)
    assert all(
        dialog.choices.item(row).checkState() == Qt.CheckState.Unchecked
        for row in range(dialog.choices.count())
    )


def test_traversal_temporary_input_is_consumed_or_cleared_on_navigation(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_bytes(b"cat\n")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))

    dialog = TraversalDialog(entries, TagOperation.ADD, ["base"])
    qtbot.addWidget(dialog)
    assert not dialog.temporary_input.isHidden()

    dialog.temporary_input.setText("temporary, image_only")
    assert dialog.temporary_add_button.isEnabled()
    assert dialog.result_tags.toPlainText() == "cat"
    dialog.temporary_add_button.click()
    assert dialog.temporary_input.text() == ""
    assert dialog.result_tags.toPlainText() == "cat, image_only, temporary"
    assert dialog.session.extra_tags_for() == ["temporary", "image_only"]
    dialog.choices.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.temporary_input.setText("discard_me")
    dialog._next()

    assert dialog.session.current_index == 1
    assert dialog.temporary_input.text() == ""
    assert dialog.session.staged[0] == (
        "base",
        "cat",
        "image_only",
        "temporary",
    )
    dialog._back()
    assert dialog.temporary_input.text() == ""
    assert dialog.choices.item(0).checkState() == Qt.CheckState.Checked
    assert dialog.session.extra_tags_for() == ["temporary", "image_only"]


def test_traversal_finish_early_commits_applied_and_skips_remaining(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ["first", "second", "third"]:
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        tag_path.write_bytes(b"cat\n")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))

    dialog = TraversalDialog(entries, TagOperation.ADD, ["dog"])
    qtbot.addWidget(dialog)
    assert dialog.finish_button.isEnabled()
    assert dialog.next_button.text() == "Next"

    dialog.choices.item(0).setCheckState(Qt.CheckState.Checked)
    assert dialog.session.current_index == 0
    dialog._next()
    assert dialog.session.current_index == 1
    assert dialog.finish_button.isEnabled()
    dialog._finish()

    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "cat, dog\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "cat\n"
    assert (tmp_path / "third.txt").read_text(encoding="utf-8") == "cat\n"


def test_traversal_folder_tree_combines_checked_subtrees(
    qtbot, tmp_path: Path
) -> None:
    nested = tmp_path / "nested"
    deep = nested / "deep"
    other = tmp_path / "other"
    deep.mkdir(parents=True)
    other.mkdir()
    entries: list[ImageEntry] = []
    for image_path in [
        tmp_path / "root.png",
        nested / "child.png",
        deep / "grandchild.png",
        other / "other.png",
    ]:
        create_png(image_path)
        tag_path = image_path.with_suffix(".txt")
        tag_path.write_text("cat\n", encoding="utf-8")
        entries.append(ImageEntry(image_path, tag_path, ["cat"], b"cat\n"))

    dialog = TraversalDialog(
        entries,
        TagOperation.ADD,
        ["dog"],
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.folder_setup.isVisibleTo(dialog)
    assert not dialog.traversal_widget.isVisibleTo(dialog)
    assert dialog.tag_input.text() == "dog"
    assert dialog.focusWidget() is dialog.tag_input
    assert dialog.tag_input.selectedText() == "dog"
    root_item = dialog.folder_tree.topLevelItem(0)
    assert root_item is not None
    assert root_item.text(0) == tmp_path.name
    assert root_item.childCount() == 3
    nested_item = None
    for index in range(root_item.childCount()):
        child = root_item.child(index)
        if child is not None and child.text(0) == "nested":
            nested_item = child
            break
    assert nested_item is not None
    assert nested_item.childCount() == 2
    deep_item = nested_item.child(0)
    assert deep_item is not None
    assert deep_item.text(0) == "deep"
    child_image = nested_item.child(1)
    assert child_image is not None
    assert child_image.text(0) == "child.png"
    other_item = None
    for index in range(root_item.childCount()):
        child = root_item.child(index)
        if child is not None and child.text(0) == "other":
            other_item = child
            break
    assert other_item is not None

    assert root_item.checkState(0) == Qt.CheckState.Checked
    assert nested_item.checkState(0) == Qt.CheckState.Checked
    assert deep_item.checkState(0) == Qt.CheckState.Checked
    root_item.setCheckState(0, Qt.CheckState.Unchecked)
    nested_item.setCheckState(0, Qt.CheckState.Checked)
    assert deep_item.checkState(0) == Qt.CheckState.Checked
    assert child_image.checkState(0) == Qt.CheckState.Checked
    child_image.setCheckState(0, Qt.CheckState.Unchecked)
    assert dialog.folder_selection_label.text() == (
        "1 matching image(s) will be included."
    )
    child_image.setCheckState(0, Qt.CheckState.Checked)
    assert dialog.folder_selection_label.text() == (
        "2 matching image(s) will be included."
    )
    other_item.setCheckState(0, Qt.CheckState.Checked)
    assert root_item.checkState(0) == Qt.CheckState.PartiallyChecked
    assert dialog.folder_selection_label.text() == (
        "3 matching image(s) will be included."
    )
    dialog.start_button.click()

    assert dialog._started
    assert not dialog.folder_setup.isVisibleTo(dialog)
    assert dialog.traversal_widget.isVisibleTo(dialog)
    assert [item.image_path for item in dialog.session.items] == [
        nested / "child.png",
        deep / "grandchild.png",
        other / "other.png",
    ]


def test_review_keyboard_shortcuts_keep_delete_and_navigate(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name, tags in {"first": ["cat", "dog"], "second": ["bird"]}.items():
        image_path = tmp_path / f"{name}.png"
        tag_path = tmp_path / f"{name}.txt"
        create_png(image_path)
        source = (", ".join(tags) + "\n").encode()
        tag_path.write_bytes(source)
        entries.append(ImageEntry(image_path, tag_path, tags, source))

    dialog = ReviewDialog(entries)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.right_splitter.orientation() == Qt.Orientation.Vertical
    assert dialog.right_splitter.widget(0) is dialog.tag_panel
    assert dialog.right_splitter.widget(1) is dialog.controls_panel
    assert dialog.tag_label.minimumHeight() == dialog.tag_label.maximumHeight()
    assert dialog.tag_label.height() >= dialog.tag_label.fontMetrics().lineSpacing() * 3
    assert dialog.tag_status_list.minimumHeight() == 150
    assert dialog.tag_status_list.maximumHeight() == 150
    decision_group = dialog.keep_button.parentWidget()
    navigation_group = dialog.back_button.parentWidget()
    session_group = dialog.finish_button.parentWidget()
    assert isinstance(decision_group, QGroupBox)
    assert isinstance(navigation_group, QGroupBox)
    assert isinstance(session_group, QGroupBox)
    assert decision_group.title() == "Tag decision"
    assert navigation_group.title() == "Navigation"
    assert session_group.title() == "Review session"
    assert dialog.session.current_tag == "cat"
    assert [dialog.tag_status_list.item(row).text() for row in range(dialog.tag_status_list.count())] == [
        "[pending] cat",
        "[pending] dog",
    ]
    assert "#b42318" in dialog.delete_button.styleSheet()
    assert "Reviewed tags 0 of 3" in dialog.progress_label.text()
    qtbot.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.session.current_tag == "dog"
    assert [dialog.tag_status_list.item(row).text() for row in range(dialog.tag_status_list.count())] == [
        "[kept] cat",
        "[pending] dog",
    ]
    assert "Reviewed tags 1 of 3" in dialog.progress_label.text()
    qtbot.keyClick(dialog, Qt.Key.Key_Space)
    assert dialog.session.current_index == 1
    assert dialog.session.current_tag == "bird"
    qtbot.keyClick(dialog, Qt.Key.Key_Left)
    assert dialog.session.current_index == 0
    assert dialog.session.current_tag == "dog"
    qtbot.keyClick(dialog, Qt.Key.Key_Right)
    assert dialog.session.current_index == 1
    assert dialog.session.current_tag == "bird"
    assert dialog.session.working_tags[0] == ["cat"]


def test_review_extra_tag_input_accepts_spaces(qtbot, tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat\n")
    dialog = ReviewDialog(
        [ImageEntry(image_path, tag_path, ["cat"], b"cat\n")]
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.temporary_input.setFocus()

    assert_stable_widget_size(dialog.temporary_input, minimum_width=256)

    qtbot.keyClicks(dialog.temporary_input, "two words")

    assert dialog.temporary_input.text() == "two words"
    assert dialog.session.current_tags == ["cat"]


def test_review_discard_button_closes_without_writing(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(image_path, tag_path, ["cat"], b"cat\n")
    dialog = ReviewDialog([entry])
    qtbot.addWidget(dialog)

    dialog._delete()
    assert dialog.session.has_changes
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Discard,
    )
    dialog.discard_button.click()

    assert dialog.result() == ReviewDialog.DialogCode.Rejected
    assert tag_path.read_bytes() == b"cat\n"


def test_complex_filter_executes_check_and_shows_matching_images(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name, tags in {"cat.png": ["cat"], "dog.png": ["dog"]}.items():
        image_path = tmp_path / name
        tag_path = tmp_path / f"{Path(name).stem}.txt"
        create_png(image_path)
        source = (", ".join(tags) + "\n").encode()
        tag_path.write_bytes(source)
        entries.append(ImageEntry(image_path, tag_path, tags, source))

    dialog = ComplexFilterDialog(entries)
    qtbot.addWidget(dialog)
    assert dialog.code_input.tabStopDistance() == (
        dialog.code_input.fontMetrics().horizontalAdvance(" ") * 4
    )
    dialog.code_input.setPlainText(
        "def check(fn: str, tags: set[str]) -> bool:\n"
        "    return fn.endswith('.png') and 'cat' in tags\n"
    )
    dialog.run_filter()

    assert dialog.results.rowCount() == 1
    image_item = dialog.results.item(0, 0)
    assert image_item is not None
    assert image_item.text() == "cat.png"
    assert dialog.result_label.text() == "1 matching image(s) out of 2."
    assert dialog.error_label.isHidden()


def test_complex_filter_reports_missing_check_function(qtbot) -> None:
    dialog = ComplexFilterDialog([])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.code_input.setPlainText("value = True")
    dialog.run_filter()

    assert dialog.results.rowCount() == 0
    assert dialog.error_label.isVisible()
    assert "must define check" in dialog.error_label.text()


def test_bulk_operation_folder_selection_cascades(qtbot, tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    create_png(tmp_path / "root.png")
    create_png(nested / "child.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)

    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    assert dialog.pages.count() == 3
    assert dialog.pages.currentWidget() is dialog.selection_page
    assert dialog.code_input.tabStopDistance() == (
        dialog.code_input.fontMetrics().horizontalAdvance(" ") * 4
    )
    root_item = dialog.folder_tree.topLevelItem(0)
    assert root_item is not None
    assert len(dialog._checked_entries()) == 2

    nested_item = next(
        root_item.child(index)
        for index in range(root_item.childCount())
        if root_item.child(index).text(0) == "nested"
    )
    nested_item.setCheckState(0, Qt.CheckState.Unchecked)

    assert [entry.image_path.name for entry in dialog._checked_entries()] == [
        "root.png"
    ]
    assert root_item.checkState(0) == Qt.CheckState.PartiallyChecked
    assert dialog.folder_selection_label.text() == "1 image(s) selected."


def test_bulk_operation_runs_code_and_skips_unchanged_images(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {"cat.png": "cat\n", "dog.png": "dog\n"}.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)

    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'new'} if fn == 'cat.png' else tags\n"
    )
    dialog._run_code()

    assert dialog.pages.currentWidget() is dialog.approval_page
    assert len(dialog._changes) == 1
    assert dialog.current_change.entry.image_path.name == "cat.png"
    assert dialog.original_tags_input.toPlainText() == "cat"
    assert dialog.new_tags_input.toPlainText() == "cat, new"
    assert dialog.original_tags_input.maximumHeight() == 100
    assert dialog.new_tags_input.maximumHeight() == 100
    assert dialog.changes_text.toPlainText() == "[+] new"
    assert dialog.apply_change_checkbox.text() == "Apply change"
    assert dialog.apply_change_checkbox.isChecked()
    assert dialog.apply_change_checkbox.styleSheet() == (
        "QCheckBox::indicator { width: 12px; height: 12px; }"
    )
    assert dialog.discard_button.text() == "Back"
    assert dialog.apply_all_button.text() == "Apply All"
    assert dialog.previous_button.text() == "Previous"
    assert dialog.next_button.text() == "Next"
    assert not dialog.previous_button.isEnabled()
    assert not dialog.next_button.isEnabled()


def test_bulk_operation_reports_invalid_process_return(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return ['not', 'a', 'set']\n"
    )

    dialog._run_code()

    assert dialog.pages.currentWidget() is dialog.code_page
    assert dialog.code_error_label.isVisibleTo(dialog)
    assert "must return set[str]" in dialog.code_error_label.text()


def test_bulk_operation_updates_decisions_while_navigation_only_moves(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {"first.png": "cat\n", "second.png": "dog\n"}.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'processed'}\n"
    )
    dialog._run_code()
    dialog.new_tags_input.setPlainText("cat, edited")
    dialog.apply_change_checkbox.setChecked(False)

    assert not dialog._decisions[0].apply_change
    assert dialog._decisions[0].result_tags == ("cat", "edited")
    dialog.next_button.click()
    assert dialog.current_change.entry.image_path.name == "second.png"
    assert dialog.previous_button.isEnabled()
    assert not dialog.next_button.isEnabled()
    assert dialog.result() == 0
    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "cat\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "dog\n"

    dialog.previous_button.click()

    assert dialog.current_change.entry.image_path.name == "first.png"
    assert dialog.new_tags_input.toPlainText() == "cat, edited"
    assert not dialog.apply_change_checkbox.isChecked()
    assert not dialog.previous_button.isEnabled()
    assert dialog.next_button.isEnabled()


def test_bulk_operation_apply_all_ignores_apply_decisions(
    qtbot, tmp_path: Path
) -> None:
    for name, tags in {"first.png": "cat\n", "second.png": "dog\n"}.items():
        create_png(tmp_path / name)
        (tmp_path / f"{Path(name).stem}.txt").write_text(tags, encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'processed'}\n"
    )
    dialog._run_code()
    dialog.new_tags_input.setPlainText("cat, edited")
    dialog.apply_change_checkbox.setChecked(False)
    dialog.next_button.click()
    dialog.apply_change_checkbox.setChecked(False)

    dialog.apply_all_button.click()

    assert dialog.result() == BulkOperationDialog.DialogCode.Accepted
    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == (
        "cat, edited\n"
    )
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == (
        "dog, processed\n"
    )


def test_bulk_operation_discard_returns_to_code_without_writing(
    qtbot, tmp_path: Path
) -> None:
    for name in ["first", "second"]:
        create_png(tmp_path / f"{name}.png")
        (tmp_path / f"{name}.txt").write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_directory(tmp_path, show_issues=False)
    dialog = BulkOperationDialog(
        window.catalog.entries,
        root_directory=tmp_path,
    )
    qtbot.addWidget(dialog)
    dialog._show_code_page()
    dialog.code_input.setPlainText(
        "def process(fn: str, tags: set[str]) -> set[str]:\n"
        "    return tags | {'processed'}\n"
    )
    dialog._run_code()
    assert dialog._decisions

    dialog.discard_button.click()

    assert dialog.pages.currentWidget() is dialog.code_page
    assert not dialog._decisions
    assert (tmp_path / "first.txt").read_text(encoding="utf-8") == "cat\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "cat\n"


def test_review_temporary_tags_are_kept_and_consumed(
    qtbot, tmp_path: Path
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat\n")
    entry = ImageEntry(image_path, tag_path, ["cat"], b"cat\n")
    dialog = ReviewDialog([entry])
    qtbot.addWidget(dialog)

    dialog.temporary_input.setText("new, cat")
    assert dialog.temporary_add_button.isEnabled()
    dialog.temporary_add_button.click()

    assert dialog.temporary_input.text() == ""
    assert dialog.session.current_tags == ["cat", "new"]
    assert "new" in dialog.session.reviewed_tags[0]
    assert "[kept] new" in [
        dialog.tag_status_list.item(row).text()
        for row in range(dialog.tag_status_list.count())
    ]
    assert tag_path.read_bytes() == b"cat\n"


def test_review_finish_confirms_total_tag_deletions(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample.png"
    tag_path = tmp_path / "sample.txt"
    create_png(image_path)
    tag_path.write_bytes(b"cat, dog\n")
    entry = ImageEntry(image_path, tag_path, ["cat", "dog"], b"cat, dog\n")
    dialog = ReviewDialog([entry])
    qtbot.addWidget(dialog)
    dialog._delete()

    prompts: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, _title, message, *_args: (
            prompts.append(message) or QMessageBox.StandardButton.Cancel
        ),
    )
    dialog._finish()

    assert "delete 1 tag(s)" in prompts[0]
    assert tag_path.read_bytes() == b"cat, dog\n"
