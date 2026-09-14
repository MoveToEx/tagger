from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
from typing import cast

from PIL import Image
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QMenu

from tagger.domain.models import ImageEntry
from tagger.ai_tagging.models import QWEN_IMAGE_VAE
from tagger.ui.dialogs import vae_preview as vae_preview_module
import tagger.ui.main_window.dialogs as window_dialogs
from tagger.ui.main_window.window import MainWindow
from tagger.ui.preview.config import SCROLL_ZOOM
from tagger.ui.preview.view import ImageView
import tagger.vae_preview.process as vae_process_module


class _FakeVaeProcess(QObject):
    progress = Signal(int, str)
    decoded = Signal(int, object, object)
    failed = Signal(int, str)

    def __init__(self, _model, _cache_dir=None, parent=None) -> None:
        super().__init__(parent)
        self.requests: list[tuple[int, Path]] = []
        self.stopped = False

    def start(self) -> None:
        pass

    def decode(self, image_path: Path) -> int:
        request_id = len(self.requests)
        self.requests.append((request_id, image_path))
        return request_id

    def stop(self) -> None:
        self.stopped = True


def _entry(path: Path) -> ImageEntry:
    return ImageEntry(path, path.with_suffix(".txt"), [], b"")


def test_vae_preview_controller_does_not_import_torch() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import tagger.vae_preview.process; "
                "import tagger.ui.dialogs.vae_preview; "
                "print('torch' in sys.modules)"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"


def test_vae_process_sends_requests_to_a_persistent_worker(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    worker_module = tmp_path / "fake_vae_worker.py"
    worker_module.write_text(
        """\
import json
from pathlib import Path
import shutil
import sys

prefix = "TAGGER_VAE:"
configuration = json.loads(sys.stdin.readline())
print(prefix + json.dumps({"type": "ready"}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request["type"] == "shutdown":
        break
    shutil.copyfile(request["image_path"], request["output_path"])
    print(prefix + json.dumps({
        "type": "result",
        "request_id": request["request_id"],
        "image_path": request["image_path"],
        "output_path": request["output_path"],
    }), flush=True)
""",
        encoding="utf-8",
    )
    python_path = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(
            [str(tmp_path), python_path] if python_path else [str(tmp_path)]
        ),
    )
    monkeypatch.setattr(
        vae_process_module, "_WORKER_MODULE", "fake_vae_worker"
    )
    source_path = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "red").save(source_path)
    process = vae_process_module.VaePreviewProcess(QWEN_IMAGE_VAE)
    decoded: list[tuple[int, Path, Path]] = []
    failures: list[tuple[int, str]] = []
    process.decoded.connect(
        lambda request_id, source, output: decoded.append(
            (request_id, source, output)
        )
    )
    process.failed.connect(
        lambda request_id, message: failures.append((request_id, message))
    )

    process.start()
    request_id = process.decode(source_path)
    qtbot.waitUntil(lambda: bool(decoded or failures), timeout=5_000)

    assert failures == []
    assert decoded[0][:2] == (request_id, source_path)
    assert decoded[0][2].read_bytes() == source_path.read_bytes()
    process.stop()


def test_comparison_view_splits_decoded_above_original_below_pointer(
    qtbot,
) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(200, 160)
    view.show()
    original = QImage(80, 80, QImage.Format.Format_RGB32)
    original.fill(QColor("blue"))
    decoded = QImage(80, 80, QImage.Format.Format_RGB32)
    decoded.fill(QColor("red"))
    view.set_comparison_images(original, decoded)
    qtbot.wait(10)

    canvas = view._label
    position = QPoint(canvas.width() // 2, canvas.height() // 2)
    qtbot.mouseMove(canvas, position)
    rendered = QImage(canvas.size(), QImage.Format.Format_RGB32)
    canvas.render(rendered)

    assert rendered.pixelColor(canvas.width() // 2, canvas.height() // 4) == QColor(
        "red"
    )
    assert rendered.pixelColor(
        canvas.width() // 2, canvas.height() * 3 // 4
    ) == QColor("blue")


def test_vae_dialog_starts_on_current_image_and_navigates(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    paths = [tmp_path / "first.png", tmp_path / "second.png"]
    Image.new("RGB", (32, 24), "red").save(paths[0])
    Image.new("RGB", (32, 24), "blue").save(paths[1])
    monkeypatch.setattr(
        vae_preview_module, "VaePreviewProcess", _FakeVaeProcess
    )
    dialog = vae_preview_module.VaePreviewDialog(
        [_entry(path) for path in paths],
        initial_image_path=paths[1],
        scrolling_behavior=SCROLL_ZOOM,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog._current_index == 1
    fake_process = cast(_FakeVaeProcess, dialog.vae_process)
    assert fake_process.requests == [(0, paths[1])]
    assert not dialog.next_button.isEnabled()

    qtbot.keyClick(dialog, Qt.Key.Key_Left)

    assert dialog._current_index == 0
    assert dialog.next_button.isEnabled()
    fake_process.decoded.emit(0, paths[1], paths[1])
    assert fake_process.requests[-1] == (1, paths[0])
    assert dialog.image_view._scrolling_behavior == SCROLL_ZOOM

    decoded_path = tmp_path / "decoded.png"
    Image.new("RGB", (32, 24), "green").save(decoded_path)
    fake_process.decoded.emit(1, paths[0], decoded_path)
    qtbot.waitUntil(lambda: dialog.image_view._comparison_pixmap is not None)

    qtbot.keyClick(dialog, Qt.Key.Key_Forward)
    assert dialog._current_index == 1
    qtbot.keyClick(dialog, Qt.Key.Key_Back)
    assert dialog._current_index == 0

    dialog.reject()
    assert fake_process.stopped


def test_image_menu_opens_vae_preview_on_the_current_image(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    paths = [tmp_path / "first.png", tmp_path / "second.png"]
    for path in paths:
        Image.new("RGB", (32, 24), "red").save(path)
    opened: list[dict[str, object]] = []

    class FakeDialog:
        def __init__(self, entries, parent, **kwargs) -> None:
            opened.append({"entries": entries, "parent": parent, **kwargs})

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(window_dialogs, "vae_dependencies_available", lambda: True)
    monkeypatch.setattr(
        window_dialogs.cache,
        "_cached_model_locations",
        lambda _repo_id, _required_files: ["Local data"],
    )
    monkeypatch.setattr(window_dialogs, "VaePreviewDialog", FakeDialog)
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window._select_row(1)

    image_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&Image"
    )
    assert window.commands.vae_preview_action in image_menu.actions()

    window.commands.vae_preview_action.trigger()

    assert len(opened) == 1
    assert opened[0]["initial_image_path"] == paths[1]
    assert opened[0]["entries"] == list(window.catalog.entries)
