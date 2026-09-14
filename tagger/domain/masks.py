from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite


@dataclass(frozen=True)
class MaskRegion:
    """An image-space polygon; regions earlier in a list have higher priority."""

    points: tuple[tuple[float, float], ...]
    alpha: float = 0.0
    color: str = "#e64b60"
    fadeout_mode: str = "none"
    destination_alpha: float = 0.0
    fadeout_width: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.alpha) or not 0.0 <= self.alpha <= 1.0:
            raise ValueError("Alpha must be between 0 and 1.")
        if self.fadeout_mode not in {"none", "outside", "inside"}:
            raise ValueError("Fadeout mode must be none, outside, or inside.")
        if not isfinite(self.destination_alpha) or not 0.0 <= self.destination_alpha <= 1.0:
            raise ValueError("Destination alpha must be between 0 and 1.")
        if not isfinite(self.fadeout_width) or self.fadeout_width < 0.0:
            raise ValueError("Fadeout width must be non-negative.")
        if len(set(self.points)) < 3 or any(
            not isfinite(value) for point in self.points for value in point
        ):
            raise ValueError("A mask needs at least three distinct, finite points.")

    @property
    def alpha_byte(self) -> int:
        return round(self.alpha * 255)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs, ys = zip(*self.points)
        return min(xs), min(ys), max(xs), max(ys)

    def resized(self, bounds: tuple[float, float, float, float]) -> MaskRegion:
        """Scale vertices from the tight axis-aligned bounds into new bounds."""
        left, top, right, bottom = bounds
        old_left, old_top, old_right, old_bottom = self.bounds
        if (not all(isfinite(value) for value in bounds)
                or right <= left or bottom <= top
                or old_right <= old_left or old_bottom <= old_top):
            raise ValueError("Resize bounds must have positive width and height.")
        return replace(self, points=tuple(
            (
                left + (x - old_left) * (right - left) / (old_right - old_left),
                top + (y - old_top) * (bottom - top) / (old_bottom - old_top),
            )
            for x, y in self.points
        ))

    def translated(self, dx: float, dy: float) -> MaskRegion:
        """Move all vertices equally, preserving the shape and mask attributes."""
        return replace(self, points=tuple((x + dx, y + dy) for x, y in self.points))
