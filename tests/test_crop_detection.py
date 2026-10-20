from __future__ import annotations

import numpy as np
from PIL import Image
import pytest

from tagger.crop_detection import detect_crop_box


@pytest.mark.parametrize("color", ["black", "white", "#307050"])
@pytest.mark.parametrize("mode", ["RGB", "RGBA", "P"])
def test_detects_solid_borders_of_any_color_and_preserves_pixels(color, mode) -> None:
    image = Image.new("RGB", (100, 80), color)
    image.paste("#d02090", (8, 5, 90, 70))
    image = image.convert(mode, palette=Image.Palette.ADAPTIVE)
    original = image.tobytes()

    assert detect_crop_box(image, (0, 0, 100, 80)) == (8, 5, 90, 70)
    assert image.tobytes() == original


@pytest.mark.parametrize("content", [(0, 6, 100, 74), (8, 0, 90, 80), (0, 0, 100, 72)])
def test_detects_borders_on_only_some_edges(content) -> None:
    image = Image.new("RGB", (100, 80), "white")
    image.paste("blue", content)
    assert detect_crop_box(image, (0, 0, 100, 80)) == content


def test_detection_is_relative_to_current_selection() -> None:
    image = Image.new("RGB", (120, 100), "green")
    image.paste("black", (10, 15, 110, 90))
    image.paste("red", (20, 25, 100, 80))

    assert detect_crop_box(image, (10, 15, 110, 90)) == (20, 25, 100, 80)
    assert detect_crop_box(image, (30, 15, 90, 90)) == (30, 25, 90, 80)


def test_detection_tolerates_compression_noise_in_border() -> None:
    pixels = np.random.default_rng(42).integers(5, 20, size=(80, 100, 3), dtype=np.uint8)
    pixels[7:74, 9:92] = (180, 90, 220)
    image = Image.fromarray(pixels)

    assert detect_crop_box(image, (0, 0, 100, 80)) == (9, 7, 92, 74)


def test_detection_ignores_hidden_colors_in_transparent_border() -> None:
    pixels = np.random.default_rng(42).integers(0, 256, size=(80, 100, 4), dtype=np.uint8)
    pixels[:, :, 3] = 0
    pixels[7:74, 9:92] = (180, 90, 220, 255)
    image = Image.fromarray(pixels)

    assert detect_crop_box(image, (0, 0, 100, 80)) == (9, 7, 92, 74)


@pytest.mark.parametrize("size", [(100, 80), (1, 10), (10, 1), (1, 1)])
def test_uniform_images_are_not_trimmed(size) -> None:
    image = Image.new("RGB", size, "blue")
    box = (0, 0, *size)
    assert detect_crop_box(image, box) == box


def test_no_border_leaves_current_selection_unchanged() -> None:
    image = Image.new("RGB", (100, 80), "blue")
    for y in range(image.height):
        for x in range(image.width):
            if (x + y) % 2:
                image.putpixel((x, y), (255, 0, 0))
    box = (5, 9, 95, 70)
    assert detect_crop_box(image, box) == box


@pytest.mark.parametrize("ratio, expected", [(2, (10, 20, 90, 60)), (1, (20, 10, 80, 70))])
def test_detection_fits_ratio_inside_content_without_reintroducing_border(ratio, expected) -> None:
    image = Image.new("RGB", (100, 80), "black")
    image.paste("blue", (10, 10, 90, 70))
    assert detect_crop_box(image, (0, 0, 100, 80), aspect_ratio=ratio) == expected


def test_detection_rejects_invalid_bounds_and_constraints() -> None:
    image = Image.new("RGB", (100, 80), "blue")
    for box in [(0, 0, 0, 0), (-1, 0, 10, 10), (0, 0, 101, 80)]:
        with pytest.raises(ValueError, match="rectangle"):
            detect_crop_box(image, box)
    for ratio in [0, -1, float("inf"), float("nan")]:
        with pytest.raises(ValueError, match="ratio"):
            detect_crop_box(image, (0, 0, 100, 80), aspect_ratio=ratio)
    for tolerance in [-1, 256]:
        with pytest.raises(ValueError, match="tolerance"):
            detect_crop_box(image, (0, 0, 100, 80), tolerance=tolerance)
