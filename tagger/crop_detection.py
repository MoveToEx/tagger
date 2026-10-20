from __future__ import annotations

from math import isfinite

import numpy as np
from PIL import Image

from tagger.crop_storage import CropBox


DEFAULT_COLOR_TOLERANCE = 24


def detect_crop_box(
    image: Image.Image,
    box: CropBox,
    *,
    aspect_ratio: float | None = None,
    tolerance: int = DEFAULT_COLOR_TOLERANCE,
) -> CropBox:
    """Trim nearly solid border colors inside box, then fit the active ratio.

    Each uniform outer edge supplies a possible border color. Find content
    bounds while allowing small compression/color variations.
    Fully uniform images are left unchanged. Coordinates stay image-relative.
    """
    left, top, right, bottom = box
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError("The crop must be a nonempty rectangle inside the image.")
    if not 0 <= tolerance <= 255:
        raise ValueError("Color tolerance must be from 0 to 255.")
    if aspect_ratio is not None and (not isfinite(aspect_ratio) or aspect_ratio <= 0):
        raise ValueError("The aspect ratio must be positive and finite.")

    # Premultiply alpha so invisible RGB values do not hide transparent borders.
    pixels = np.asarray(image.crop(box).convert("RGBA").convert("RGBa"))
    colors: set[tuple[int, ...]] = set()
    for edge in (pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]):
        minimum = edge.min(axis=0).astype(np.int16)
        maximum = edge.max(axis=0).astype(np.int16)
        if np.all(maximum - minimum <= 2 * tolerance):
            colors.add(tuple(int(value) for value in (minimum + maximum) // 2))

    full_box = (0, 0, right - left, bottom - top)
    detected: CropBox | None = None
    for color in sorted(colors):
        reference = np.array(color, dtype=np.int16)
        foreground = np.any(
            (pixels < np.maximum(0, reference - tolerance))
            | (pixels > np.minimum(255, reference + tolerance)),
            axis=2,
        )
        rows = np.flatnonzero(foreground.any(axis=1))
        columns = np.flatnonzero(foreground.any(axis=0))
        if not rows.size or not columns.size:
            continue
        candidate = (int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1)
        # When opposite edges have different solid colors, prefer removing the
        # smaller border instead of mistaking the larger content for a border.
        if _area(candidate) < _area(full_box) and (
            detected is None or _area(candidate) > _area(detected)
        ):
            detected = candidate

    if detected is None:
        return box
    x1, y1, x2, y2 = detected
    if aspect_ratio is not None:
        width = min(float(x2 - x1), (y2 - y1) * aspect_ratio)
        height = width / aspect_ratio
        crop_width = max(1, min(x2 - x1, round(width)))
        crop_height = max(1, min(y2 - y1, round(height)))
        x1 += (x2 - x1 - crop_width) // 2
        y1 += (y2 - y1 - crop_height) // 2
        x2, y2 = x1 + crop_width, y1 + crop_height
    return left + x1, top + y1, left + x2, top + y2


def _area(box: CropBox) -> int:
    left, top, right, bottom = box
    return (right - left) * (bottom - top)
