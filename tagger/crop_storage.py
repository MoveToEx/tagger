from __future__ import annotations

import os
from pathlib import Path
import tempfile

from PIL import Image, ImageOps


CropBox = tuple[int, int, int, int]
FileStamp = tuple[int, int]
SUPPORTED_CROP_FORMATS = {"PNG", "JPEG", "WEBP", "TIFF", "BMP"}


def crop_disabled_reason(path: Path) -> str | None:
    try:
        with Image.open(path) as image:
            if image.format not in SUPPORTED_CROP_FORMATS:
                return "Cropping supports PNG, JPEG, WebP, TIFF, and BMP."
            if getattr(image, "n_frames", 1) != 1:
                return "Cropping requires a single-frame image."
    except (OSError, ValueError) as exc:
        return f"Could not open image: {exc}"
    return None


def file_stamp(path: Path) -> FileStamp:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def load_crop_image(path: Path) -> Image.Image:
    """Load pixels in displayed orientation, retaining their alpha channel."""
    reason = crop_disabled_reason(path)
    if reason:
        raise ValueError(reason)
    with Image.open(path) as image:
        try:
            return ImageOps.exif_transpose(image)
        finally:
            image.close()


def crop_image(
    path: Path, box: CropBox, *, expected_stamp: FileStamp | None = None,
) -> bool:
    """Crop in displayed coordinates and atomically replace the original file."""
    if expected_stamp is not None and file_stamp(path) != expected_stamp:
        raise OSError("Image changed since it was opened. Reopen the crop dialog.")
    image = load_crop_image(path)
    left, top, right, bottom = box
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError("The crop must be a nonempty rectangle inside the image.")
    if box == (0, 0, image.width, image.height):
        return False
    with Image.open(path) as source:
        image_format = source.format
    result = image.crop(box)
    options: dict = {}
    if image_format == "WEBP":
        options.update(lossless=True, exact=True)
    elif image_format == "JPEG":
        options.update(quality=95, subsampling=0)
    for key in ("icc_profile", "dpi"):
        if image.info.get(key):
            options[key] = image.info[key]
    exif = image.getexif()
    if exif:
        for key, size in ((256, result.width), (257, result.height),
                          (40962, result.width), (40963, result.height)):
            if key in exif:
                exif[key] = size
        options["exif"] = exif.tobytes()
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        result.save(temporary, format=image_format, **options)
        if expected_stamp is not None and file_stamp(path) != expected_stamp:
            raise OSError("Image changed since it was opened. Reopen the crop dialog.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True
