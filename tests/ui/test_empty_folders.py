from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

from tagger.settings.preferences import (
    REMOVE_EMPTY_FOLDER_ALWAYS,
    REMOVE_EMPTY_FOLDER_ASK,
    REMOVE_EMPTY_FOLDER_NEVER,
    REMOVE_EMPTY_FOLDER_SETTING,
    get_remove_empty_folder_behavior,
)
from tagger.settings.dialog import SettingsDialog
from tagger.settings.store import JsonSettings
from tagger.ui.main_window.empty_folders import maybe_remove_empty_folder


def test_settings_dialog_persists_empty_folder_behavior(
    qtbot, tmp_path: Path
) -> None:
    settings_path = tmp_path / "settings.json"
    settings = JsonSettings(settings_path)
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert [
        dialog.remove_empty_folder_input.itemText(index)
        for index in range(dialog.remove_empty_folder_input.count())
    ] == ["Always", "Never", "Ask"]
    assert dialog.remove_empty_folder_input.currentData() == (
        REMOVE_EMPTY_FOLDER_NEVER
    )

    dialog.remove_empty_folder_input.setCurrentIndex(
        dialog.remove_empty_folder_input.findData(REMOVE_EMPTY_FOLDER_ASK)
    )
    assert dialog.apply_button.isEnabled()
    dialog.apply_button.click()

    assert get_remove_empty_folder_behavior(settings) == REMOVE_EMPTY_FOLDER_ASK
    assert (
        get_remove_empty_folder_behavior(JsonSettings(settings_path))
        == REMOVE_EMPTY_FOLDER_ASK
    )


def test_empty_folder_setting_controls_cleanup(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    settings = JsonSettings(tmp_path / "settings.json")
    parent = QWidget()
    qtbot.addWidget(parent)

    never = root / "never"
    never.mkdir()
    settings.setValue(REMOVE_EMPTY_FOLDER_SETTING, REMOVE_EMPTY_FOLDER_NEVER)
    assert not maybe_remove_empty_folder(
        never,
        root_directory=root,
        settings=settings,
        parent=parent,
    )
    assert never.is_dir()

    always = root / "always"
    always.mkdir()
    settings.setValue(REMOVE_EMPTY_FOLDER_SETTING, REMOVE_EMPTY_FOLDER_ALWAYS)
    assert maybe_remove_empty_folder(
        always,
        root_directory=root,
        settings=settings,
        parent=parent,
    )
    assert not always.exists()

    ask_no = root / "ask-no"
    ask_no.mkdir()
    settings.setValue(REMOVE_EMPTY_FOLDER_SETTING, REMOVE_EMPTY_FOLDER_ASK)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    assert not maybe_remove_empty_folder(
        ask_no,
        root_directory=root,
        settings=settings,
        parent=parent,
    )
    assert ask_no.is_dir()

    ask_yes = root / "ask-yes"
    ask_yes.mkdir()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    assert maybe_remove_empty_folder(
        ask_yes,
        root_directory=root,
        settings=settings,
        parent=parent,
    )
    assert not ask_yes.exists()


def test_empty_folder_cleanup_keeps_open_root(
    qtbot, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(REMOVE_EMPTY_FOLDER_SETTING, REMOVE_EMPTY_FOLDER_ALWAYS)
    parent = QWidget()
    qtbot.addWidget(parent)

    assert not maybe_remove_empty_folder(
        root,
        root_directory=root,
        settings=settings,
        parent=parent,
    )
    assert root.is_dir()
