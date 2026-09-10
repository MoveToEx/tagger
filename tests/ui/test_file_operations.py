from __future__ import annotations

from pathlib import Path
import threading
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox

from tagger.settings.preferences import (
    USE_UNLINK_FOR_MANUAL_DELETE_SETTING,
    USE_UNLINK_FOR_TIDY_SETTING,
)
from tagger.storage import ArchiveResult
from tagger.trash import SYSTEM_RECYCLE_BIN, UNLINK
import tagger.trash as trash_module
import tagger.ui.dialogs.archive as archive_module
import tagger.ui.main_window.files as window_files
from tagger.ui.main_window.window import MainWindow

from .helpers import create_png


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

    window.folders._load_directory(tmp_path, show_issues=False)
    assert window.commands.tidy_action.isEnabled()
    file_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&File"
    )
    assert window.commands.tidy_action in file_menu.actions()

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
        window_files,
        "delete_file",
        lambda path, behavior: path.unlink() or True,
    )

    window.commands.tidy_action.trigger()

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
    window.folders._load_directory(tmp_path, show_issues=False)
    behaviors: list[str] = []

    def fake_delete_file(path: Path, behavior: str) -> bool:
        behaviors.append(behavior)
        path.unlink()
        return True

    monkeypatch.setattr(window_files, "delete_file", fake_delete_file)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    window.files._tidy_folder()

    assert behaviors == [UNLINK]
    assert not unknown.exists()
    assert window.statusBar().currentMessage() == (
        "Permanently deleted 1 unrecognized file(s)."
    )


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
    window.folders._load_directory(source, show_issues=False)
    monkeypatch.setattr(
        window_files.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(destination), "Zip archives (*.zip)"),
    )

    assert window.commands.archive_action.text() == "Archive..."
    assert window.commands.archive_action.isEnabled()
    window.commands.archive_action.trigger()

    assert window.files._archive_dialog is not None
    assert window.files._archive_dialog.isVisible()
    qtbot.waitUntil(lambda: destination.exists())
    qtbot.waitUntil(lambda: window.files._archive_dialog is None)
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
        window_files.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(destination), "Zip archives (*.zip)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(source, show_issues=False)

    window.commands.archive_action.trigger()
    try:
        qtbot.waitUntil(
            lambda: window.files._archive_dialog is not None
            and window.files._archive_dialog.current_file_label.text()
            == "Archiving: sample.png"
        )
        assert window.files._archive_dialog is not None
        assert window.files._archive_dialog.progress_bar.value() == 1
        assert window.files._archive_dialog.progress_bar.maximum() == 2
        assert not window.commands.archive_action.isEnabled()
    finally:
        release_worker.set()

    qtbot.waitUntil(lambda: window.files._archive_dialog is None)


def test_image_context_delete_moves_image_and_tag_to_trash(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    for name in ["first", "second"]:
        create_png(tmp_path / f"{name}.png")
        (tmp_path / f"{name}.txt").write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    moved: list[Path] = []

    def fake_delete_file(path: Path, behavior: str) -> bool:
        assert behavior == SYSTEM_RECYCLE_BIN
        moved.append(path)
        path.unlink()
        return True

    monkeypatch.setattr(window_files, "delete_file", fake_delete_file)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    assert (
        window.image_list.contextMenuPolicy()
        == Qt.ContextMenuPolicy.CustomContextMenu
    )
    window.files._delete_current_image_and_tag()

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
    window.folders._load_directory(tmp_path, show_issues=False)
    behaviors: list[str] = []
    prompts: list[tuple[str, str]] = []

    def fake_delete_file(path: Path, behavior: str) -> bool:
        behaviors.append(behavior)
        path.unlink()
        return True

    monkeypatch.setattr(window_files, "delete_file", fake_delete_file)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message, *_args: (
            prompts.append((title, message))
            or QMessageBox.StandardButton.Yes
        ),
    )

    window.files._delete_current_image_and_tag()

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
    window.folders._load_directory(tmp_path, show_issues=False)
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args: ("renamed", True),
    )

    menu = window.files._create_image_context_menu()
    assert [action.text() for action in menu.actions()] == [
        "Rename...",
        "Delete",
        "",
        "Edit",
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
    window.folders._load_directory(tmp_path, show_issues=False)
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
    window.folders._load_directory(tmp_path, show_issues=False)
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
    monkeypatch.setattr(window_files, "delete_file", fake_delete_file)

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
    window.folders._load_directory(tmp_path, show_issues=False)
    window.image_list.clearSelection()
    assert window.image_list.currentIndex().isValid()
    calls: list[str] = []
    monkeypatch.setattr(
        window.files,
        "_rename_current_image_and_tag",
        lambda: calls.append("rename"),
    )
    monkeypatch.setattr(
        window.files,
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
    window.folders._load_directory(tmp_path, show_issues=False)
    started: list[tuple[str, list[str]]] = []

    class FakeQProcess:
        @staticmethod
        def startDetached(
            program: str, arguments: list[str]
        ) -> tuple[bool, int]:
            started.append((program, arguments))
            return True, 123

    monkeypatch.setattr(window_files, "QProcess", FakeQProcess)

    menu = window.files._create_image_context_menu()
    menu.actions()[4].trigger()

    assert started == [
        ("explorer.exe", ["/select,", str(image_path)]),
    ]


def test_image_context_menu_edits_and_refreshes_displayed_image(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    image_path = tmp_path / "sample image.png"
    create_png(image_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    processes = []

    class FakeSignal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback) -> None:
            self.callback = callback

        def emit(self, *args) -> None:
            assert self.callback is not None
            self.callback(*args)

    class FakeQProcess:
        def __init__(self, parent) -> None:
            assert parent is window
            self.finished = FakeSignal()
            self.errorOccurred = FakeSignal()
            self.started_with = None
            self.deleted = False
            processes.append(self)

        def start(self, program: str, arguments: list[str]) -> None:
            self.started_with = (program, arguments)

        def deleteLater(self) -> None:
            self.deleted = True

    monkeypatch.setattr(window_files, "QProcess", FakeQProcess)
    cleared: list[bool] = []
    loaded: list[Path] = []
    monkeypatch.setattr(window.preview_loader, "clear", lambda: cleared.append(True))
    monkeypatch.setattr(window.preview_loader, "load", loaded.append)

    menu = window.files._create_image_context_menu()
    menu.actions()[3].trigger()

    assert len(processes) == 1
    process = processes[0]
    assert process.started_with == ("mspaint.exe", [str(image_path)])
    assert process in window.files._image_editor_processes

    process.finished.emit(0, None)

    assert cleared == [True]
    assert loaded == [image_path]
    assert process.deleted
    assert process not in window.files._image_editor_processes


def test_image_editor_exit_does_not_refresh_another_displayed_image(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    create_png(first_path)
    create_png(second_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    processes = []

    class FakeSignal:
        def __init__(self) -> None:
            self.callback = None

        def connect(self, callback) -> None:
            self.callback = callback

        def emit(self, *args) -> None:
            assert self.callback is not None
            self.callback(*args)

    class FakeQProcess:
        def __init__(self, _parent) -> None:
            self.finished = FakeSignal()
            self.errorOccurred = FakeSignal()
            processes.append(self)

        def start(self, _program: str, _arguments: list[str]) -> None:
            pass

        def deleteLater(self) -> None:
            pass

    monkeypatch.setattr(window_files, "QProcess", FakeQProcess)
    window.files._edit_current_image()
    window._select_row(1)
    cleared: list[bool] = []
    loaded: list[Path] = []
    monkeypatch.setattr(window.preview_loader, "clear", lambda: cleared.append(True))
    monkeypatch.setattr(window.preview_loader, "load", loaded.append)

    processes[0].finished.emit(0, None)

    current = window._current_entry()
    assert current is not None
    assert current.image_path == second_path
    assert cleared == []
    assert loaded == []


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
    window.folders._load_directory(tmp_path, show_issues=False)
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

    window.files._rename_current_image_and_tag()

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
    window.folders._load_directory(tmp_path, show_issues=False)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Cancel,
    )
    monkeypatch.setattr(
        window_files,
        "delete_file",
        lambda _path, _behavior: (_ for _ in ()).throw(
            AssertionError("cancelled deletion must not move files")
        ),
    )

    window.files._delete_current_image_and_tag()

    assert image_path.exists()
    assert tag_path.exists()
