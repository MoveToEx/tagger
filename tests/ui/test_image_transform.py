from __future__ import annotations

from pathlib import Path
import time

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.image_transform import ImageTransformDialog
import tagger.ui.dialogs.image_transform as image_transform


def _entry(path: Path) -> ImageEntry:
    return ImageEntry(path, path.with_suffix(".txt"), [], b"")


def test_transform_runs_conversion_off_the_gui_thread(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    output = tmp_path / "source.jpg"
    calls: list[tuple[Path, str, bool]] = []

    def slow_convert(path: Path, target_format: str, *, overwrite: bool) -> Path:
        calls.append((path, target_format, overwrite))
        time.sleep(0.15)
        return output

    monkeypatch.setattr(image_transform, "convert_image", slow_convert)
    dialog = ImageTransformDialog([_entry(source)])
    qtbot.addWidget(dialog)

    dialog._start()
    assert dialog._running
    assert dialog._worker is not None
    assert dialog.status_label.text() == "Choose an output format."

    qtbot.waitUntil(lambda: not dialog._running, timeout=3000)
    assert calls == [(source, "jpg", False)]
    assert dialog.converted_paths == [output]
    assert dialog.progress_bar.value() == 1
