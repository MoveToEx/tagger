from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QWheelEvent

from tagger.ui.preview.config import (
    SCROLL_NAVIGATE_AT_END,
    SCROLL_NAVIGATE_WHEN_FITTED,
    SCROLL_PAN,
    SCROLL_ZOOM,
)
from tagger.image_processing import apply_alpha_display_filter
from tagger.ui.preview.loader import PreviewLoader
from tagger.ui.preview.view import ImageView

from .helpers import create_png


def test_invert_alpha_display_filter_inverts_only_alpha() -> None:
    image = QImage(2, 1, QImage.Format.Format_RGBA8888)
    image.setPixelColor(0, 0, QColor(10, 20, 30, 0))
    image.setPixelColor(1, 0, QColor(40, 50, 60, 255))

    inverted = apply_alpha_display_filter(image, "invert")

    assert inverted.pixelColor(0, 0) == QColor(10, 20, 30, 255)
    assert inverted.pixelColor(1, 0) == QColor(40, 50, 60, 0)


@pytest.mark.parametrize("alpha", [0, 64, 128, 192, 255])
def test_overlay_alpha_blends_red_over_opaque_rgb(alpha: int) -> None:
    image = QImage(3, 2, QImage.Format.Format_RGBA8888)
    original = QColor(25, 75, 125, alpha)
    image.fill(original)

    result = apply_alpha_display_filter(image, "overlay")

    opacity = 0.8 * alpha / 255
    expected_rgb = (
        round(255 * opacity + 25 * (1 - opacity)),
        round(75 * (1 - opacity)),
        round(125 * (1 - opacity)),
    )
    assert result.size() == image.size()
    for y in range(result.height()):
        for x in range(result.width()):
            actual = result.pixelColor(x, y)
            assert actual.alpha() == 255
            assert (actual.red(), actual.green(), actual.blue()) == pytest.approx(
                expected_rgb, abs=1
            )
            assert image.pixelColor(x, y) == original


def test_overlay_alpha_treats_images_without_alpha_as_opaque() -> None:
    image = QImage(3, 2, QImage.Format.Format_RGB888)
    image.fill(QColor(25, 75, 125))

    result = apply_alpha_display_filter(image, "overlay")

    assert result.pixelColor(0, 0) == QColor(209, 15, 25)
    assert image.pixelColor(0, 0) == QColor(25, 75, 125)


def test_overlay_alpha_preview_updates_existing_and_new_images(qtbot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(2, 1, QImage.Format.Format_RGBA8888)
    image.fill(QColor(0, 0, 255, 0))
    view.set_image(image)

    view.set_alpha_mode("overlay")

    assert view._pixmap is not None
    assert view._pixmap.toImage().pixelColor(0, 0) == QColor(0, 0, 255)
    image.fill(QColor(0, 255, 0, 255))
    view.set_image(image)
    assert view._pixmap.toImage().pixelColor(0, 0) == QColor(204, 51, 0)
    view.set_alpha_mode("keep")
    assert view._source_image == image


def test_auto_alpha_keeps_images_without_alpha() -> None:
    image = QImage(3, 2, QImage.Format.Format_RGB888)
    image.fill(QColor(25, 75, 125))

    assert apply_alpha_display_filter(image, "auto") == image


@pytest.mark.parametrize("alpha", [0, 128, 254, 255])
@pytest.mark.parametrize(
    "image_format",
    [QImage.Format.Format_RGBA8888, QImage.Format.Format_ARGB32_Premultiplied],
)
def test_auto_alpha_uses_overlay_only_when_a_pixel_is_transparent(
    alpha: int, image_format: QImage.Format
) -> None:
    image = QImage(3, 2, image_format)
    image.fill(QColor(25, 75, 125, 255))
    image.setPixelColor(2, 1, QColor(25, 75, 125, alpha))
    original = image.copy()

    result = apply_alpha_display_filter(image, "auto")

    if alpha == 255:
        assert result == image
    else:
        assert result.pixelColor(0, 0) == QColor(209, 15, 25)
        assert result.pixelColor(2, 1).alpha() == 255
    assert image == original


def test_auto_alpha_preview_rechecks_transparency_between_images(qtbot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(2, 1, QImage.Format.Format_RGBA8888)
    image.fill(QColor(0, 255, 0, 255))
    view.set_image(image)
    view.set_alpha_mode("auto")

    assert view._pixmap is not None
    assert view._pixmap.toImage().pixelColor(0, 0) == QColor(0, 255, 0)

    transparent_image = image.copy()
    transparent_image.setPixelColor(1, 0, QColor(0, 0, 255, 0))
    view.set_image(transparent_image)
    assert view.alpha_mode == "auto"
    assert view._pixmap.toImage().pixelColor(0, 0) == QColor(204, 51, 0)
    assert view._pixmap.toImage().pixelColor(1, 0) == QColor(0, 0, 255)

    view.set_image(image)
    assert view._pixmap.toImage().pixelColor(0, 0) == QColor(0, 255, 0)
    view.set_image(image.convertToFormat(QImage.Format.Format_RGB32))
    assert view._pixmap.toImage().pixelColor(0, 0) == QColor(0, 255, 0)
    assert view.alpha_mode == "auto"


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


def test_navigate_when_fitted_pans_only_outside_fit_to_window(qtbot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(800, 1200, QImage.Format.Format_RGB32)
    image.fill(QColor("#2f6fed"))
    view.resize(400, 300)
    view.set_image(image)
    view.set_scrolling_behavior(SCROLL_NAVIGATE_WHEN_FITTED)
    view.show()
    qtbot.waitExposed(view)
    navigation: list[int] = []
    view.navigation_requested.connect(navigation.append)

    fitted_event = QWheelEvent(
        view.viewport().rect().center(),
        view.viewport().mapToGlobal(view.viewport().rect().center()),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QGuiApplication.sendEvent(view.viewport(), fitted_event)

    assert navigation == [1]

    view.set_fit_to_window(False)
    scrollbar = view.verticalScrollBar()
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
    assert navigation == [1]


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


def test_image_view_draws_source_pixel_grid(qtbot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor("black"))
    view.resize(64, 64)
    view.set_fit_to_window(False)
    view.set_image(image)
    view.set_grid_size(8)
    view.show()
    qtbot.waitExposed(view)

    canvas = view._label
    rendered = QImage(canvas.size(), QImage.Format.Format_RGB32)
    canvas.render(rendered)

    assert rendered.pixelColor(8, 4).lightness() > 0
    assert rendered.pixelColor(4, 4) == QColor("black")

    image.fill(QColor("white"))
    view.set_image(image)
    canvas.render(rendered)

    assert rendered.pixelColor(7, 4).lightness() < 255
    assert rendered.pixelColor(4, 4) == QColor("white")


def test_grid_badge_is_placed_outside_selection(qtbot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    canvas = view._label
    selection = QRectF(0, 0, 120, 80)
    bounds = QRectF(0, 0, 320, 240)

    badge = canvas._grid_badge_rect(selection, bounds, QSize(96, 24))

    assert badge is not None
    assert bounds.contains(badge)
    assert not badge.intersects(selection)


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
