from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QWheelEvent

from tagger.ui.preview.config import SCROLL_NAVIGATE_AT_END, SCROLL_PAN, SCROLL_ZOOM
from tagger.ui.preview.loader import PreviewLoader
from tagger.ui.preview.view import ImageView

from .helpers import create_png


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
