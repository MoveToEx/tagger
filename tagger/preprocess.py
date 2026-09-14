from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil


DEFAULT_TRAINING_RESOLUTION = 1024
DEFAULT_ARB_ENABLED = True
DEFAULT_ARB_STEP = 64
DEFAULT_ARB_MIN_SIZE = 256
DEFAULT_ARB_MAX_SIZE = 2048
DEFAULT_NO_UPSCALE = False
ANIMA_DIT_GRID = "anima_dit"
VAE_LATENT_GRID = "vae_latent"
GRID_TYPES = {
    ANIMA_DIT_GRID: ("Anima DiT (16 x 16 px)", 16),
    VAE_LATENT_GRID: ("VAE latent (8 x 8 px)", 8),
}
DEFAULT_GRID_TYPE = ANIMA_DIT_GRID


@dataclass(frozen=True)
class PreprocessOptions:
    training_resolution: int = DEFAULT_TRAINING_RESOLUTION
    arb_enabled: bool = DEFAULT_ARB_ENABLED
    arb_step: int = DEFAULT_ARB_STEP
    arb_min_size: int = DEFAULT_ARB_MIN_SIZE
    arb_max_size: int = DEFAULT_ARB_MAX_SIZE
    no_upscale: bool = DEFAULT_NO_UPSCALE


@dataclass(frozen=True)
class PreprocessPlan:
    source_size: tuple[int, int]
    target_size: tuple[int, int]
    resized_size: tuple[int, int]
    crop_box: tuple[int, int, int, int]

    @property
    def output_size(self) -> tuple[int, int]:
        left, top, right, bottom = self.crop_box
        return right - left, bottom - top


def bucket_resolutions(options: PreprocessOptions) -> tuple[tuple[int, int], ...]:
    """Build step-aligned buckets bounded by the configured pixel area."""
    resolution = max(1, options.training_resolution)
    step = max(1, options.arb_step)
    minimum = max(1, min(options.arb_min_size, options.arb_max_size))
    maximum = max(minimum, max(options.arb_min_size, options.arb_max_size))
    maximum_area = resolution * resolution
    first_width = (minimum + step - 1) // step * step
    candidates: set[tuple[int, int]] = set()

    for width in range(first_width, maximum + 1, step):
        height = min(maximum, maximum_area // width)
        height = height // step * step
        if height < minimum:
            continue
        candidates.add((width, height))
        candidates.add((height, width))

    if minimum <= resolution <= maximum:
        candidates.add((resolution, resolution))
    if not candidates:
        fallback = max(minimum, min(maximum, resolution))
        candidates.add((fallback, fallback))
    return tuple(sorted(candidates))


def closest_bucket(
    image_size: tuple[int, int], options: PreprocessOptions
) -> tuple[int, int]:
    """Select the candidate whose aspect ratio is closest to the image."""
    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions must be positive.")
    if not options.arb_enabled:
        resolution = max(1, options.training_resolution)
        return resolution, resolution

    image_ratio = width / height
    desired_area = max(1, options.training_resolution) ** 2
    return min(
        bucket_resolutions(options),
        key=lambda size: (
            abs(size[0] / size[1] - image_ratio),
            abs(size[0] * size[1] - desired_area),
            size,
        ),
    )


def create_preprocess_plan(
    image_size: tuple[int, int], options: PreprocessOptions
) -> PreprocessPlan:
    """Plan a cover resize followed by an axis-wise center crop."""
    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions must be positive.")
    target_width, target_height = closest_bucket(image_size, options)
    scale = max(
        Fraction(target_width, width), Fraction(target_height, height)
    )

    if options.no_upscale and scale > 1:
        resized_width, resized_height = width, height
    else:
        resized_width = ceil(width * scale)
        resized_height = ceil(height * scale)

    crop_width = min(target_width, resized_width)
    crop_height = min(target_height, resized_height)
    left = (resized_width - crop_width) // 2
    top = (resized_height - crop_height) // 2
    return PreprocessPlan(
        source_size=image_size,
        target_size=(target_width, target_height),
        resized_size=(resized_width, resized_height),
        crop_box=(left, top, left + crop_width, top + crop_height),
    )
