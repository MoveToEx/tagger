from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest

from tagger.domain.masks import MaskRegion
from tagger.mask_storage import load_mask_image, render_masks, save_masks


RECTANGLE = ((1.0, 1.0), (6.0, 1.0), (6.0, 6.0), (1.0, 6.0))


def test_translation_preserves_shape_alpha_and_color() -> None:
    mask = MaskRegion(((10, 20), (30, 10), (50, 40), (20, 30)), 0.35, "#123456")
    moved = mask.translated(-5, 12)
    assert moved.points == ((5, 32), (25, 22), (45, 52), (15, 42))
    assert moved.alpha == mask.alpha
    assert moved.color == mask.color
    assert mask.points[0] == (10, 20)


def test_polygon_resize_uses_tight_bounds_and_preserves_vertex_positions() -> None:
    mask = MaskRegion(((10, 20), (30, 10), (50, 40), (20, 30)), 0.35, "#123456")
    assert mask.bounds == (10, 10, 50, 40)
    resized = mask.resized((5, 15, 85, 30))
    assert resized.points == ((5, 20), (45, 15), (85, 30), (25, 25))
    assert resized.alpha == mask.alpha
    assert resized.color == mask.color
    assert mask.bounds == (10, 10, 50, 40)


@pytest.mark.parametrize("bounds", [(0, 0, 0, 10), (0, 5, 10, 4), (0, 0, float("inf"), 10)])
def test_resize_rejects_collapsed_or_invalid_bounds(bounds) -> None:
    with pytest.raises(ValueError, match="bounds"):
        MaskRegion(RECTANGLE).resized(bounds)


@pytest.mark.parametrize("alpha", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_alpha_is_rejected(alpha: float) -> None:
    with pytest.raises(ValueError, match="Alpha"):
        MaskRegion(RECTANGLE, alpha)


def test_rasterization_replaces_old_alpha_and_uses_top_polygon_at_overlaps() -> None:
    image = Image.new("RGBA", (10, 10), (20, 40, 60, 30))
    result = render_masks(image, [
        MaskRegion(RECTANGLE, 0.5),
        MaskRegion(((4, 4), (8, 4), (4, 8)), 0.0),
    ])
    assert result.getpixel((0, 0)) == (20, 40, 60, 255)
    assert result.getpixel((2, 2)) == (20, 40, 60, 128)
    assert result.getpixel((5, 5)) == (20, 40, 60, 128)
    assert result.getpixel((7, 4)) == (20, 40, 60, 0)
    assert result.getpixel((8, 8)) == (20, 40, 60, 255)


@pytest.mark.parametrize("alpha", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_base_alpha_is_rejected(alpha: float) -> None:
    with pytest.raises(ValueError, match="Base alpha"):
        render_masks(Image.new("RGB", (10, 10)), [], alpha)


@pytest.mark.parametrize("base_alpha, expected", [(0.0, 0), (0.25, 64), (1.0, 255)])
def test_base_alpha_applies_only_outside_masks(base_alpha: float, expected: int) -> None:
    result = render_masks(
        Image.new("RGBA", (10, 10), (20, 40, 60, 30)),
        [MaskRegion(RECTANGLE, 0.5)], base_alpha,
    )
    assert result.getpixel((0, 0)) == (20, 40, 60, expected)
    assert result.getpixel((2, 2)) == (20, 40, 60, 128)


@pytest.mark.parametrize("suffix", ["png", "webp", "tiff"])
def test_save_preserves_format_rgb_and_writes_integer_alpha(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"image.{suffix}"
    Image.new("RGBA", (10, 10), (20, 40, 60, 70)).save(path)
    with Image.open(path) as before:
        rgb = before.convert("RGB").getpixel((2, 2))
        assert isinstance(rgb, tuple)
        image_format = before.format
        before.close()
    save_masks(path, [MaskRegion(RECTANGLE, 0.5)])
    with Image.open(path) as after:
        assert after.format == image_format
        assert after.convert("RGBA").getpixel((2, 2)) == (*rgb, 128)
        assert after.convert("RGBA").getchannel("A").getpixel((0, 0)) == 255


def test_save_failure_leaves_original_and_cleans_temporary(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "image.png"
    Image.new("RGBA", (10, 10), (20, 40, 60, 70)).save(path)
    original = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", fail)
    with pytest.raises(OSError, match="disk full"):
        save_masks(path, [MaskRegion(RECTANGLE)])
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_jpeg_disguised_as_png_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    Image.new("RGB", (10, 10)).save(path, format="JPEG")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="JPEG"):
        save_masks(path, [MaskRegion(RECTANGLE)])
    assert path.read_bytes() == original


def test_saved_masks_use_displayed_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "rotated.png"
    image = Image.new("RGB", (10, 20), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(path, exif=exif)
    assert load_mask_image(path).size == (20, 10)
    save_masks(path, [MaskRegion(RECTANGLE)])
    with Image.open(path) as result:
        assert result.size == (20, 10)
        assert result.getexif().get(274, 1) == 1
        assert result.getchannel("A").getpixel((2, 2)) == 0
