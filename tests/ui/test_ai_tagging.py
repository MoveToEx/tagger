from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QPoint, QProcess, Qt

import tagger.ai_tagging.cache as ai_cache
import tagger.ai_tagging.dependencies as ai_dependencies
import tagger.ai_tagging.inference as ai_inference
from tagger.ai_tagging.dialog import AITaggingDialog
from tagger.ai_tagging.model_dialog import ModelManagementDialog
import tagger.ai_tagging.model_dialog as model_dialog_module
from tagger.ai_tagging.models import AI_DEPENDENCIES, MODEL_REPOSITORIES
from tagger.domain.models import ImageEntry

from .helpers import (
    assert_stable_widget_size,
    create_cached_model,
    create_png,
    render_spin_box_control,
)


def test_inference_controller_does_not_import_torch() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import tagger.ai_tagging.inference; "
                "print('torch' in sys.modules)"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"


def test_inference_results_are_emitted_after_subprocess_exit(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    worker_module = tmp_path / "fake_ai_inference_worker.py"
    worker_module.write_text(
        """\
import json
import sys

request = json.load(sys.stdin)
path = request["image_paths"][0]
prefix = "TAGGER_AI:"
print(prefix + json.dumps({"type": "progress", "value": 0, "total": 1, "message": "Loading model..."}), flush=True)
print(prefix + json.dumps({"type": "result", "path": path, "tags": [["cat", 0.9]]}), flush=True)
print(prefix + json.dumps({"type": "completed"}), flush=True)
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
        ai_inference, "_WORKER_MODULE", "fake_ai_inference_worker"
    )
    image_path = tmp_path / "image.png"
    controller = ai_inference._InferenceProcess(
        [image_path],
        "example/model",
        0.35,
        0.75,
        None,
    )
    progress: list[tuple[int, int, str]] = []
    completed: list[object] = []
    completion_states: list[QProcess.ProcessState] = []
    failures: list[str] = []

    def inference_completed(results: object) -> None:
        completed.append(results)
        completion_states.append(controller._process.state())

    controller.progress.connect(
        lambda value, total, message: progress.append((value, total, message))
    )
    controller.completed.connect(inference_completed)
    controller.failed.connect(failures.append)

    controller.start()
    qtbot.waitUntil(lambda: bool(completed or failures), timeout=5_000)

    assert failures == []
    assert progress == [(0, 1, "Loading model...")]
    assert completed == [{str(image_path): [("cat", 0.9)]}]
    assert completion_states == [QProcess.ProcessState.NotRunning]


def test_ai_dependency_availability_is_cached(monkeypatch) -> None:
    checked: list[str] = []

    def find_spec(name: str):
        checked.append(name)
        return None if name == "torch" else object()

    ai_dependencies.ai_dependencies_available.cache_clear()
    monkeypatch.setattr(ai_dependencies.importlib.util, "find_spec", find_spec)
    try:
        assert not ai_dependencies.ai_dependencies_available()
        assert not ai_dependencies.ai_dependencies_available()
        assert checked == list(AI_DEPENDENCIES)
    finally:
        ai_dependencies.ai_dependencies_available.cache_clear()


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
        ai_cache,
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
    assert ai_cache._preferred_model_cache_directory(
        repositories[1]
    ) == local_cache


def test_model_download_worker_uses_selected_cache_directory(
    tmp_path: Path, monkeypatch
) -> None:
    destination = tmp_path / "data" / "model"
    calls: list[tuple[str, Path | None]] = []
    monkeypatch.setattr(
        ai_cache,
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
    worker = model_dialog_module._ModelDownloadWorker(repo_id, "", destination)
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
        ai_cache,
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
        ai_cache,
        "_cached_model_locations",
        lambda _repo_id: [],
    )
    empty_dialog = AITaggingDialog([entry], root_directory=tmp_path)
    qtbot.addWidget(empty_dialog)

    assert empty_dialog.model_input.currentIndex() == -1
    assert not empty_dialog.start_button.isEnabled()


def test_ai_tagger_can_check_only_an_initial_image(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name in ("first.png", "second.png"):
        image_path = tmp_path / name
        entries.append(
            ImageEntry(
                image_path,
                image_path.with_suffix(".txt"),
                source_bytes=b"",
            )
        )

    dialog = AITaggingDialog(
        entries,
        root_directory=tmp_path,
        initial_image_path=entries[1].image_path,
    )
    qtbot.addWidget(dialog)

    assert dialog._checked_entries() == [entries[1]]
    assert dialog.selection_label.text() == "1 image(s) selected."


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
