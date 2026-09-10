from __future__ import annotations

from pathlib import Path
from threading import Event

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QSizePolicy
import pytest

from tagger.deduplication import DuplicatePair, DuplicateScanResult, KeepChoice
from tagger.domain.models import ImageEntry
from tagger.settings.preferences import USE_UNLINK_FOR_DEDUPLICATE_SETTING
from tagger.trash import SYSTEM_RECYCLE_BIN, UNLINK
from tagger.ui.dialogs.deduplicate import DeduplicateDialog
import tagger.ui.dialogs.deduplicate as deduplicate
from tagger.ui.dialogs.delete_filter import DeleteFilterCommitResult
import tagger.ui.main_window.dialogs as window_dialogs
import tagger.ui.main_window.window as main_window_module
from tagger.ui.preview.loader import PreviewLoader


@pytest.fixture
def entries(tmp_path: Path) -> list[ImageEntry]:
    result = []
    for name in ["a", "nested/b", "nested/c"]:
        path = tmp_path / f"{name}.png"
        path.parent.mkdir(exist_ok=True)
        Image.new("RGB", (32, 24), "blue").save(path)
        tag = path.with_suffix(".txt")
        tag.write_text("cat\n", encoding="utf-8")
        result.append(ImageEntry(path, tag, ["cat"], b"cat\n"))
    return result


@pytest.fixture
def dialog(qtbot, tmp_path: Path, entries, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Discard)
    window = DeduplicateDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(window)
    window.show()
    yield window
    window.left_loader.wait_for_done()
    window._allow_close = True
    window.close()


def start_review(dialog, entries) -> None:
    a, b, c = [entry.image_path for entry in entries]
    dialog._scan_completed(DuplicateScanResult([
        DuplicatePair(a, b, 0), DuplicatePair(a, c, 0), DuplicatePair(b, c, 0),
    ]))


def test_selection_tree_cascades_and_threshold_has_stable_size(dialog, entries) -> None:
    root = dialog.folder_tree.topLevelItem(0)
    assert root is not None
    assert dialog._checked_entries() == entries
    root.setCheckState(0, Qt.CheckState.Unchecked)
    assert dialog._checked_entries() == []
    assert not dialog.scan_button.isEnabled()
    folder = root.child(1)
    folder.setCheckState(0, Qt.CheckState.Checked)
    assert dialog._checked_entries() == entries[1:]
    assert root.checkState(0) == Qt.CheckState.PartiallyChecked
    assert dialog.scan_button.isEnabled()
    combo = dialog.threshold_combo
    assert [combo.itemData(index) for index in range(4)] == [0, 1, 2, 4]
    assert [combo.itemText(index) for index in range(4)] == [
        "Exact (0)", "Very similar (1)", "Similar (2)", "Speculative (4)",
    ]
    assert combo.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
    assert combo.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert combo.width() % 2 == combo.height() % 2 == 0


def test_background_scan_uses_selected_images_and_threshold(dialog, entries, qtbot, monkeypatch) -> None:
    captured = []

    def scan(paths, threshold, **kwargs):
        captured.append((paths, threshold))
        return DuplicateScanResult([DuplicatePair(paths[0], paths[1], 2)])

    monkeypatch.setattr(deduplicate, "find_duplicate_pairs", scan)
    dialog.folder_tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Unchecked)
    dialog.threshold_combo.setCurrentIndex(2)
    dialog.scan_button.click()
    qtbot.waitUntil(lambda: dialog.pages.currentWidget() is dialog.review_page)
    assert captured == [([entry.image_path for entry in entries[1:]], 2)]
    assert len(dialog.session.pairs) == 1


def test_background_scan_hashes_real_images_and_loads_both_previews(dialog, qtbot) -> None:
    dialog.scan_button.click()
    qtbot.waitUntil(
        lambda: dialog.pages.currentWidget() is dialog.review_page,
        timeout=15000,
    )
    assert len(dialog.session.pairs) == 3
    qtbot.waitUntil(
        lambda: dialog.left_view._pixmap is not None and dialog.right_view._pixmap is not None,
    )


def test_navigation_preserves_choices_and_skips_deleted_pairs(dialog, entries, qtbot) -> None:
    start_review(dialog, entries)
    assert dialog.finish_button.isEnabled()
    dialog.next_button.click()
    dialog.back_button.click()
    assert dialog.session.decisions == {}
    dialog.choice_buttons[KeepChoice.LEFT].click()
    assert dialog.current_index == 1
    assert dialog.session.pending_indices == [1]
    assert not dialog.next_button.isEnabled()
    dialog.choice_buttons[KeepChoice.BOTH].click()
    saved = dict(dialog.session.decisions)
    assert dialog.finish_button.isEnabled()
    dialog.back_button.click()
    assert dialog.choice_buttons[KeepChoice.LEFT].isChecked()
    dialog.next_button.click()
    assert dialog.choice_buttons[KeepChoice.BOTH].isChecked()
    assert dialog.session.decisions == saved
    dialog.back_button.click()
    dialog.choice_buttons[KeepChoice.BOTH].click()
    assert dialog.current_index == 2
    assert dialog.finish_button.isEnabled()
    assert all(entry.image_path.exists() and entry.tag_path.exists() for entry in entries)
    qtbot.waitUntil(lambda: dialog.left_view._pixmap is not None and dialog.right_view._pixmap is not None)


@pytest.mark.parametrize("complete_review", [False, True])
def test_finish_commits_only_marked_images_and_sidecars(
    dialog, entries, monkeypatch, complete_review: bool
) -> None:
    removed = []

    def delete(path):
        removed.append(path)
        path.unlink()
        return True

    dialog._file_deleter = delete
    start_review(dialog, entries)
    dialog.choice_buttons[KeepChoice.LEFT].click()
    if complete_review:
        dialog.choice_buttons[KeepChoice.BOTH].click()
    else:
        assert dialog.session.pending_indices == [1]
    saved = dict(dialog.session.decisions)
    assert removed == []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    dialog.finish_button.click()
    assert removed == []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.finish_button.click()
    assert removed == [entries[1].image_path, entries[1].tag_path]
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.commit_result.complete
    assert dialog.session.decisions == saved
    for entry in (entries[0], entries[2]):
        assert entry.image_path.exists() and entry.tag_path.exists()


def test_finish_without_decisions_keeps_all_images(dialog, entries) -> None:
    start_review(dialog, entries)
    assert dialog.session.pending_indices == [0, 1, 2]
    dialog.finish_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.commit_result is None
    assert dialog.session.decisions == {}
    assert all(entry.image_path.exists() and entry.tag_path.exists() for entry in entries)


def test_failed_image_deletion_preserves_sidecar_and_reports_failure(dialog, entries, monkeypatch) -> None:
    attempted = []
    warnings = []

    def fail(path):
        attempted.append(path)
        raise OSError("Access denied")

    dialog._file_deleter = fail
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    start_review(dialog, entries)
    dialog.choice_buttons[KeepChoice.LEFT].click()
    dialog.choice_buttons[KeepChoice.BOTH].click()
    dialog.finish_button.click()
    assert attempted == [entries[1].image_path]
    assert entries[1].tag_path.exists()
    assert "Access denied" in warnings[0]
    assert not dialog.commit_result.complete


def test_cancel_discards_decisions_without_deleting(dialog, entries) -> None:
    start_review(dialog, entries)
    dialog.choice_buttons[KeepChoice.RIGHT].click()
    dialog.cancel_button.click()
    assert dialog.result() == dialog.DialogCode.Rejected
    assert dialog.commit_result is None
    assert all(entry.image_path.exists() and entry.tag_path.exists() for entry in entries)


def test_cancel_running_scan(dialog, monkeypatch, qtbot) -> None:
    started = Event()
    stopped = Event()

    def scan(paths, threshold, *, progress, cancelled):
        started.set()
        while not cancelled():
            stopped.wait(0.01)
        stopped.set()
        return DuplicateScanResult()

    monkeypatch.setattr(deduplicate, "find_duplicate_pairs", scan)
    dialog.scan_button.click()
    qtbot.waitUntil(started.is_set)
    dialog.cancel_button.click()
    qtbot.waitUntil(stopped.is_set)
    assert dialog.result() == dialog.DialogCode.Rejected


def test_no_duplicates_can_finish_without_deletion(dialog) -> None:
    dialog._scan_completed(DuplicateScanResult())
    assert "No duplicate pairs" in dialog.progress_label.text()
    assert dialog.finish_button.isEnabled()
    assert not any(button.isEnabled() for button in dialog.choice_buttons.values())
    dialog.finish_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted


@pytest.mark.parametrize("use_unlink", [False, True])
def test_main_window_opens_deduplicate_and_refreshes_after_commit(
    qtbot, tmp_path, entries, monkeypatch, use_unlink: bool
) -> None:
    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.settings.setValue(USE_UNLINK_FOR_DEDUPLICATE_SETTING, use_unlink)
    assert not window.commands.deduplicate_action.isEnabled()
    window.folders._load_directory(tmp_path, show_issues=False)
    assert window.commands.deduplicate_action.isEnabled()
    opened = []

    class FakeDialog:
        DialogCode = DeduplicateDialog.DialogCode
        commit_result = DeleteFilterCommitResult([entries[1].image_path], [], {})

        def __init__(self, selected_entries, parent, *, root_directory, deletion_behavior):
            opened.append((selected_entries, root_directory, deletion_behavior))

        def exec(self):
            PreviewLoader().wait_for_done()
            entries[1].image_path.unlink()
            entries[1].tag_path.unlink()
            return self.DialogCode.Accepted

    monkeypatch.setattr(window_dialogs, "DeduplicateDialog", FakeDialog)
    window.commands.deduplicate_action.trigger()
    assert opened[0][1] == tmp_path
    assert len(opened[0][0]) == 3
    assert opened[0][2] == (UNLINK if use_unlink else SYSTEM_RECYCLE_BIN)
    assert ("Permanently deleted" if use_unlink else "Moved to Recycle Bin") in window.statusBar().currentMessage()
    assert {entry.image_path for entry in window.catalog.entries} == {
        entries[0].image_path, entries[2].image_path,
    }


@pytest.mark.parametrize("behavior", [SYSTEM_RECYCLE_BIN, UNLINK])
def test_deduplicate_uses_selected_deletion_behavior(
    qtbot, tmp_path, entries, monkeypatch, behavior: str
) -> None:
    calls = []
    prompts = []

    def delete(path, selected_behavior):
        calls.append((path, selected_behavior))
        path.unlink()
        return True

    def confirm(parent, title, message, *args):
        prompts.append((title, message))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(deduplicate, "delete_file", delete)
    monkeypatch.setattr(QMessageBox, "question", confirm)
    window = DeduplicateDialog(entries, root_directory=tmp_path, deletion_behavior=behavior)
    qtbot.addWidget(window)
    start_review(window, entries)
    window.choice_buttons[KeepChoice.LEFT].click()
    window.finish_button.click()
    assert calls == [(entries[1].image_path, behavior), (entries[1].tag_path, behavior)]
    if behavior == UNLINK:
        assert prompts[0][0] == "Permanently Delete Duplicate Images?"
        assert "This cannot be undone." in prompts[0][1]
    else:
        assert "system Recycle Bin" in prompts[0][1]
    assert entries[2].image_path.exists()
    assert window.commit_result is not None
    assert window.commit_result.complete
