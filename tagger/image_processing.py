from __future__ import annotations

from collections.abc import Callable
import os
import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QImageReader, QPainter


ImageFilter = Callable[[QImage], QImage]


def _keep(image: QImage) -> QImage:
    return image


def _ignore_alpha(image: QImage) -> QImage:
    if not image.hasAlphaChannel():
        return image
    return image.convertToFormat(QImage.Format.Format_RGB32)


def _exclusive_alpha(image: QImage) -> QImage:
    result = QImage(image.size(), QImage.Format.Format_RGB32)
    result.fill(QColor("white"))
    if not image.hasAlphaChannel():
        return result
    for y in range(image.height()):
        for x in range(image.width()):
            value = image.pixelColor(x, y).alpha()
            result.setPixelColor(x, y, QColor(value, value, value))
    return result


ALPHA_DISPLAY_FILTERS: dict[str, ImageFilter] = {
    "keep": _keep,
    "ignore": _ignore_alpha,
    "exclusive": _exclusive_alpha,
}


def register_alpha_display_filter(name: str, filter_function: ImageFilter) -> None:
    """Register a preview filter under a stable menu/action name."""
    if not name or not name.strip():
        raise ValueError("The filter name cannot be empty.")
    ALPHA_DISPLAY_FILTERS[name.casefold()] = filter_function


def apply_alpha_display_filter(image: QImage, mode: str) -> QImage:
    filter_function = ALPHA_DISPLAY_FILTERS.get(mode.casefold(), _keep)
    return filter_function(image)


def image_has_alpha(path: Path) -> bool:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    return not image.isNull() and image.hasAlphaChannel()


def _save_image(image: QImage, destination: Path, image_format: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=f".{image_format.casefold()}",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if not image.save(str(temporary)):
            raise OSError(f"Could not write {destination.name}.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def convert_image(
    source: Path,
    target_format: str,
    *,
    overwrite: bool = False,
) -> Path | None:
    """Convert one image, returning ``None`` when its format is unchanged."""
    source = Path(source)
    image_format = target_format.casefold().removeprefix(".")
    if source.suffix.casefold().removeprefix(".") == image_format:
        return None
    destination = source.with_suffix(f".{image_format}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"A file named {destination.name} already exists.")
    reader = QImageReader(str(source))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise OSError(reader.errorString() or f"Could not read {source.name}.")
    del reader
    if image_format in {"jpg", "jpeg"} and image.hasAlphaChannel():
        flattened = QImage(image.size(), QImage.Format.Format_RGB32)
        flattened.fill(QColor("white"))
        painter = QPainter(flattened)
        painter.drawImage(0, 0, image)
        painter.end()
        image = flattened
    _save_image(image, destination, image_format.upper())
    return destination


def remove_transparency(path: Path) -> bool:
    """Make an image opaque in place; return whether a rewrite was needed."""
    path = Path(path)
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise OSError(reader.errorString() or f"Could not read {path.name}.")
    del reader
    if not image.hasAlphaChannel():
        return False
    result = image.convertToFormat(QImage.Format.Format_RGB32)
    _save_image(result, path, path.suffix.removeprefix(".").upper())
    return True
