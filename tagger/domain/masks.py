from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class MaskRegion:
    """An image-space polygon; regions earlier in a list have higher priority."""

    points: tuple[tuple[float, float], ...]
    alpha: float = 0.0
    color: str = "#e64b60"

    def __post_init__(self) -> None:
        if not isfinite(self.alpha) or not 0.0 <= self.alpha <= 1.0:
            raise ValueError("Alpha must be between 0 and 1.")
        if len(set(self.points)) < 3 or any(
            not isfinite(value) for point in self.points for value in point
        ):
            raise ValueError("A mask needs at least three distinct, finite points.")

    @property
    def alpha_byte(self) -> int:
        return round(self.alpha * 255)
