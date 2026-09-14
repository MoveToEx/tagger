from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent
from PySide6.QtWidgets import QMenu

from tagger.domain.models import ImageEntry
from tagger.preprocess import (
    VAE_LATENT_GRID,
    PreprocessOptions,
)
from tagger.settings.preferences import (
    SIMULATOR_ARB_ENABLED_SETTING,
    SIMULATOR_GRID_TYPE_SETTING,
    SIMULATOR_NO_UPSCALE_SETTING,
    SIMULATOR_TRAINING_RESOLUTION_SETTING,
)
from tagger.ui.dialogs.grid_preview import GridPreviewDialog
import tagger.ui.main_window.dialogs as window_dialogs
from tagger.ui.main_window.window import MainWindow
from tagger.ui.preview.config import SCROLL_PAN


def _entry(path: Path) -> ImageEntry:
    return ImageEntry(path, path.with_suffix(".txt"), [], b"")


def test_grid_preview_preprocesses_current_image_and_measures_grid_rectangle(
    qtbot, tmp_path: Path
) -> None:
    paths = [tmp_path / "wide.png", tmp_path / "tall.png"]
    Image.new("RGB", (160, 80), "red").save(paths[0])
    Image.new("RGB", (80, 160), "blue").save(paths[1])
    dialog = GridPreviewDialog(
        [_entry(path) for path in paths],
        options=PreprocessOptions(
            training_resolution=64, arb_enabled=False
        ),
        grid_type=VAE_LATENT_GRID,
        initial_image_path=paths[1],
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._plan is not None)

    assert dialog._current_index == 1
    assert dialog._plan is not None
    assert dialog._plan.source_size == (80, 160)
    assert dialog._plan.output_size == (64, 64)
    assert dialog.image_view._source_image is not None
    assert dialog.image_view._source_image.size().toTuple() == (64, 64)
    assert dialog.image_view._label._grid_size == 8
    assert "VAE latent grid 8 x 8" in dialog.status_label.text()
    assert dialog.image_view._scrolling_behavior == SCROLL_PAN
    assert not dialog.image_view._ctrl_wheel_zoom_enabled

    canvas = dialog.image_view._label
    draw_rect = canvas._source_draw_rect()
    scale = draw_rect.width() / 64
    start = QPoint(
        round(draw_rect.left() + 4 * scale),
        round(draw_rect.top() + 4 * scale),
    )
    end = QPoint(
        round(draw_rect.left() + 20 * scale),
        round(draw_rect.top() + 12 * scale),
    )
    qtbot.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(canvas, end)
    qtbot.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)

    assert dialog._measurement == (3, 2)
    assert canvas._grid_selection == (0, 0, 3, 2)
    assert "Selection 3 x 2 grids" in dialog.status_label.text()

    qtbot.keyClick(dialog, Qt.Key.Key_Left)
    qtbot.waitUntil(
        lambda: dialog._plan is not None
        and dialog._plan.source_size == (160, 80)
    )
    assert dialog._current_index == 0
    dialog.reject()


def test_grid_preview_wheel_pans_even_with_control_held(
    qtbot, tmp_path: Path
) -> None:
    path = tmp_path / "large.png"
    Image.new("RGB", (1200, 1200), "red").save(path)
    dialog = GridPreviewDialog(
        [_entry(path)],
        options=PreprocessOptions(
            training_resolution=1024, arb_enabled=False
        ),
    )
    dialog.resize(420, 320)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._plan is not None)
    dialog.image_view.actual_size()
    scrollbar = dialog.image_view.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum() // 2)
    initial_scroll = scrollbar.value()
    initial_zoom = dialog.image_view._zoom
    wheel = QWheelEvent(
        dialog.image_view.viewport().rect().center(),
        dialog.image_view.viewport().mapToGlobal(
            dialog.image_view.viewport().rect().center()
        ),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    QGuiApplication.sendEvent(dialog.image_view.viewport(), wheel)

    assert dialog.image_view._zoom == initial_zoom
    assert scrollbar.value() > initial_scroll
    dialog.reject()


def test_image_menu_opens_grid_preview_with_persisted_options(
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

    monkeypatch.setattr(
        window_dialogs, "GridPreviewDialog", FakeDialog
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.settings.setValue(SIMULATOR_TRAINING_RESOLUTION_SETTING, 768)
    window.settings.setValue(SIMULATOR_ARB_ENABLED_SETTING, False)
    window.settings.setValue(SIMULATOR_NO_UPSCALE_SETTING, True)
    window.settings.setValue(SIMULATOR_GRID_TYPE_SETTING, VAE_LATENT_GRID)
    window.folders._load_directory(tmp_path, show_issues=False)
    window._select_row(1)

    image_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&Image"
    )
    assert window.commands.grid_preview_action in image_menu.actions()
    assert window.commands.grid_preview_action.text() == "Grid Preview..."
    action_index = image_menu.actions().index(
        window.commands.grid_preview_action
    )
    assert image_menu.actions()[action_index - 1].isSeparator()

    window.commands.grid_preview_action.trigger()

    assert len(opened) == 1
    assert opened[0]["initial_image_path"] == paths[1]
    assert opened[0]["entries"] == list(window.catalog.entries)
    assert opened[0]["grid_type"] == VAE_LATENT_GRID
    assert opened[0]["options"] == PreprocessOptions(
        training_resolution=768,
        arb_enabled=False,
        no_upscale=True,
    )
