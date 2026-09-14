from __future__ import annotations

import pytest

from tagger.preprocess import (
    PreprocessOptions,
    bucket_resolutions,
    closest_bucket,
    create_preprocess_plan,
)


def test_arb_builds_bounded_buckets_and_selects_closest_aspect_ratio() -> None:
    options = PreprocessOptions(
        training_resolution=512,
        arb_enabled=True,
        arb_step=256,
        arb_min_size=256,
        arb_max_size=768,
    )

    assert bucket_resolutions(options) == (
        (256, 768),
        (512, 512),
        (768, 256),
    )
    assert closest_bucket((1200, 400), options) == (768, 256)


def test_preprocess_without_arb_resizes_to_cover_then_center_crops() -> None:
    plan = create_preprocess_plan(
        (1600, 800),
        PreprocessOptions(training_resolution=1024, arb_enabled=False),
    )

    assert plan.target_size == (1024, 1024)
    assert plan.resized_size == (2048, 1024)
    assert plan.crop_box == (512, 0, 1536, 1024)
    assert plan.output_size == (1024, 1024)


def test_arb_bucket_becomes_the_resize_and_crop_target() -> None:
    plan = create_preprocess_plan((1600, 900), PreprocessOptions())

    assert plan.target_size == (1344, 768)
    assert plan.resized_size == (1366, 768)
    assert plan.crop_box == (11, 0, 1355, 768)
    assert plan.output_size == plan.target_size


def test_no_upscale_keeps_small_axis_and_crops_oversized_axis() -> None:
    plan = create_preprocess_plan(
        (512, 1536),
        PreprocessOptions(
            training_resolution=1024,
            arb_enabled=False,
            no_upscale=True,
        ),
    )

    assert plan.resized_size == (512, 1536)
    assert plan.crop_box == (0, 256, 512, 1280)
    assert plan.output_size == (512, 1024)


def test_preprocess_rejects_empty_image_dimensions() -> None:
    with pytest.raises(ValueError, match="positive"):
        create_preprocess_plan((0, 100), PreprocessOptions())
