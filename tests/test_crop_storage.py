from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest

import tagger.crop_storage as crop_storage
from tagger.crop_storage import crop_disabled_reason, crop_image, file_stamp, load_crop_image


def test_crop_preserves_pixels_alpha_and_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    image = Image.new("RGBA", (12, 10))
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), (x * 20, y * 20, 50, x * 20))
    image.save(path)
    sidecar = path.with_suffix(".txt")
    sidecar.write_text("tag1, tag2", encoding="utf-8")
    assert crop_image(path, (2, 3, 10, 9), expected_stamp=file_stamp(path))
    with Image.open(path) as result:
        assert result.size == (8, 6)
        assert result.tobytes() == image.crop((2, 3, 10, 9)).tobytes()
    assert sidecar.read_text(encoding="utf-8") == "tag1, tag2"


def test_crop_uses_displayed_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (30, 20), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(path, exif=exif)
    assert load_crop_image(path).size == (20, 30)
    crop_image(path, (0, 10, 20, 30))
    with Image.open(path) as result:
        assert result.format == "JPEG"
        assert result.size == (20, 20)
        assert result.getexif().get(274, 1) == 1


@pytest.mark.parametrize("extension", ["png", "webp", "tiff", "bmp"])
def test_crop_retains_source_format(tmp_path: Path, extension: str) -> None:
    path = tmp_path / f"image.{extension}"
    Image.new("RGB", (30, 20), "red").save(path)
    with Image.open(path) as source:
        original_format = source.format
    crop_image(path, (4, 5, 20, 18))
    with Image.open(path) as result:
        assert result.format == original_format
        assert result.size == (16, 13)


def test_noop_invalid_box_and_changed_source_do_not_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    Image.new("RGB", (30, 20), "red").save(path)
    original = path.read_bytes()
    stamp = file_stamp(path)
    assert not crop_image(path, (0, 0, 30, 20))
    for box in [(0, 0, 0, 0), (-1, 0, 10, 10), (0, 0, 31, 20)]:
        with pytest.raises(ValueError):
            crop_image(path, box)
    assert path.read_bytes() == original
    Image.new("RGB", (10, 10), "blue").save(path)
    changed = path.read_bytes()
    with pytest.raises(OSError, match="changed"):
        crop_image(path, (0, 0, 5, 5), expected_stamp=stamp)
    assert path.read_bytes() == changed


def test_failed_replacement_keeps_original_and_cleans_temporary(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "image.png"
    Image.new("RGB", (30, 20), "red").save(path)
    original = path.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(crop_storage.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        crop_image(path, (0, 0, 10, 10))
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_animated_and_unreadable_images_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "animated.png"
    Image.new("RGB", (30, 20), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (30, 20), "blue")],
    )
    original = path.read_bytes()
    assert "single-frame" in (crop_disabled_reason(path) or "")
    with pytest.raises(ValueError, match="single-frame"):
        crop_image(path, (0, 0, 10, 10))
    assert path.read_bytes() == original
    assert crop_disabled_reason(tmp_path / "missing.png") is not None
