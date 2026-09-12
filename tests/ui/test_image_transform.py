from __future__ import annotations

from pathlib import Path
import threading

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.image_transform import ConvertProgressDialog, ImageTransformDialog
import tagger.ui.dialogs.image_transform as image_transform

from .helpers import assert_stable_widget_size, create_png


def _entry(path: Path) -> ImageEntry:
    return ImageEntry(path, path.with_suffix(".txt"), [], b"")


def test_transform_runs_conversion_off_the_gui_thread(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.png"
    create_png(source)
    output = tmp_path / "source.jpg"
    calls: list[tuple[Path, str, bool]] = []
    thread_ids: list[int] = []
    started = threading.Event()
    release = threading.Event()

    def slow_convert(path: Path, target_format: str, *, overwrite: bool = False) -> Path:
        calls.append((path, target_format, overwrite))
        thread_ids.append(threading.get_ident())
        started.set()
        assert release.wait(timeout=5)
        return output

    monkeypatch.setattr(image_transform, "convert_image", slow_convert)
    selection = ImageTransformDialog([_entry(source)])
    qtbot.addWidget(selection)
    assert_stable_widget_size(selection.format_combo)
    selection.format_combo.setCurrentText("JPEG")
    selection.remove_button.click()
    assert selection.result() == selection.DialogCode.Accepted
    assert selection.selected_paths_for_conversion == [source]
    assert selection.target_format == "jpg"
    assert calls == []
    dialog = ConvertProgressDialog(selection.selected_paths_for_conversion, selection.target_format)
    qtbot.addWidget(dialog)
    results = []
    dialog.completed.connect(results.append)
    try:
        dialog.start()
        qtbot.waitUntil(started.is_set, timeout=3000)
        assert dialog._running
        assert len(thread_ids) == 1
        assert thread_ids[0] != threading.get_ident()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not dialog._running, timeout=3000)
    assert calls == [(source, "jpg", False)]
    assert results == [([output], [])]
    assert dialog.progress.value() == 1
    assert dialog.result() == dialog.DialogCode.Accepted
