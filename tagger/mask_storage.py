from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
import os
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw, ImageOps

from tagger.domain.masks import MaskRegion


SUPPORTED_MASK_FORMATS = {"PNG", "WEBP", "TIFF"}


def mask_editing_disabled_reason(path: Path) -> str | None:
    try:
        with Image.open(path) as image:
            if image.format == "JPEG":
                return "JPEG does not support an alpha channel. Convert to PNG first."
            if image.format not in SUPPORTED_MASK_FORMATS:
                return "Mask editing supports PNG, WebP, and TIFF. Convert to PNG first."
            if getattr(image, "n_frames", 1) != 1:
                return "Mask editing requires a single-frame image."
    except (OSError, ValueError) as exc:
        return f"Could not open image: {exc}"
    return None


def load_mask_image(path: Path) -> Image.Image:
    reason = mask_editing_disabled_reason(path)
    if reason:
        raise ValueError(reason)
    with Image.open(path) as image:
        # Work in displayed orientation, ignoring the old alpha channel.
        try:
            return ImageOps.exif_transpose(image).convert("RGB")
        finally:
            # TIFF can retain a memory map after its context manager exits.
            image.close()


def render_masks(
    image: Image.Image, masks: Sequence[MaskRegion], base_alpha: float = 1.0
) -> Image.Image:
    if not isfinite(base_alpha) or not 0.0 <= base_alpha <= 1.0:
        raise ValueError("Base alpha must be between 0 and 1.")
    result = image.convert("RGBA")
    alpha = Image.new("L", image.size, round(base_alpha * 255))
    draw = ImageDraw.Draw(alpha)
    for mask in reversed(masks):
        draw.polygon(mask.points, fill=mask.alpha_byte)
    result.putalpha(alpha)
    return result


def save_masks(
    path: Path, masks: Sequence[MaskRegion], base_alpha: float = 1.0
) -> None:
    """Replace alpha atomically, retaining RGB and the source image format."""
    image = load_mask_image(path)
    with Image.open(path) as source:
        image_format = source.format
    result = render_masks(image, masks, base_alpha)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        options: dict = {}
        if image_format == "WEBP":
            options.update(lossless=True, exact=True)
        for key in ("icc_profile", "exif", "dpi"):
            if image.info.get(key):
                options[key] = image.info[key]
        result.save(temporary, format=image_format, **options)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
