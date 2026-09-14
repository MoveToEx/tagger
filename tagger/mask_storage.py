from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
import os
from pathlib import Path
import tempfile
import numpy as np

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
        if mask.fadeout_mode == "none" or mask.fadeout_width <= 0:
            draw.polygon(mask.points, fill=mask.alpha_byte)
            continue
        # Rasterize a signed distance to the polygon boundary.  This keeps
        # the fade independent of image scale and supports both directions.
        width, height = image.size
        yy, xx = np.mgrid[0:height, 0:width]
        inside = np.zeros((height, width), dtype=bool)
        polygon = Image.new("1", (width, height), 0)
        ImageDraw.Draw(polygon).polygon(mask.points, fill=1)
        inside[:] = np.asarray(polygon, dtype=bool)
        points = np.asarray(mask.points, dtype=float)
        distances = np.full((height, width), np.inf)
        for start, end in zip(points, np.roll(points, -1, axis=0)):
            vx, vy = end - start
            denom = vx * vx + vy * vy or 1.0
            t = np.clip(((xx - start[0]) * vx + (yy - start[1]) * vy) / denom, 0.0, 1.0)
            distances = np.minimum(distances, np.hypot(xx - (start[0] + t * vx), yy - (start[1] + t * vy)))
        signed = np.where(inside, distances, -distances)
        fade_width = mask.fadeout_width
        if mask.fadeout_mode == "outside":
            factor = np.clip((signed + fade_width) / fade_width, 0.0, 1.0)
        else:
            factor = np.where(inside, np.clip((fade_width - signed) / fade_width, 0.0, 1.0), 0.0)
        values = np.round((mask.destination_alpha + (mask.alpha - mask.destination_alpha) * factor) * 255).astype(np.uint8)
        covered = inside if mask.fadeout_mode == "inside" else (signed >= -fade_width)
        alpha.paste(Image.fromarray(values, mode="L"), (0, 0), Image.fromarray(covered.astype(np.uint8) * 255, mode="L"))
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
