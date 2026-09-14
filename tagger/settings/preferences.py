from __future__ import annotations

from tagger.preprocess import (
    DEFAULT_ARB_ENABLED,
    DEFAULT_ARB_MAX_SIZE,
    DEFAULT_ARB_MIN_SIZE,
    DEFAULT_ARB_STEP,
    DEFAULT_NO_UPSCALE,
    DEFAULT_TRAINING_RESOLUTION,
    DEFAULT_GRID_TYPE,
    GRID_TYPES,
    PreprocessOptions,
)
from tagger.settings.store import JsonSettings
from tagger.trash import SYSTEM_RECYCLE_BIN, UNLINK
from tagger.ui.preview.config import (
    DEFAULT_IMAGE_PREFETCH_COUNT,
    MAX_IMAGE_PREFETCH_COUNT,
    SCROLLING_BEHAVIORS,
    SCROLL_PAN,
)


UNDERSCORES_SETTING = "autocomplete/transform_underscores_to_spaces"
PARENTHESES_SETTING = "autocomplete/escape_parentheses"
SCROLLING_BEHAVIOR_SETTING = "general/scrolling_behavior"
CATALOG_CLICK_HOLD_BEHAVIOR_SETTING = "general/catalog_click_hold_behavior"
IMAGE_PREFETCH_COUNT_SETTING = "general/traversal_image_prefetch_count"
OPEN_RECENT_FOLDER_ON_STARTUP_SETTING = (
    "general/open_recent_folder_on_startup"
)
USE_UNLINK_FOR_DELETE_FILTER_SETTING = "general/use_unlink_for_delete_filter"
USE_UNLINK_FOR_MANUAL_DELETE_SETTING = "general/use_unlink_for_manual_delete"
USE_UNLINK_FOR_TIDY_SETTING = "general/use_unlink_for_tidy"
USE_UNLINK_FOR_DEDUPLICATE_SETTING = "general/use_unlink_for_deduplicate"
PROXY_SETTING = "network/http_proxy"
PROXY_MODE_SETTING = "network/proxy_mode"
SCRIPTING_TAGS_TYPE_SETTING = "scripting/tags_type"
SIMULATOR_TRAINING_RESOLUTION_SETTING = (
    "simulator/preprocess/training_resolution"
)
SIMULATOR_ARB_ENABLED_SETTING = "simulator/preprocess/arb_enabled"
SIMULATOR_ARB_STEP_SETTING = "simulator/preprocess/arb_step"
SIMULATOR_ARB_MIN_SIZE_SETTING = "simulator/preprocess/arb_min_size"
SIMULATOR_ARB_MAX_SIZE_SETTING = "simulator/preprocess/arb_max_size"
SIMULATOR_NO_UPSCALE_SETTING = "simulator/preprocess/no_upscale"
SIMULATOR_GRID_TYPE_SETTING = "simulator/grid_type"
NO_PROXY = "none"
SYSTEM_PROXY = "system"
CUSTOM_PROXY = "custom"
PROXY_MODES = {NO_PROXY, SYSTEM_PROXY, CUSTOM_PROXY}

CATALOG_DRAG_AND_DROP = "drag_and_drop"
CATALOG_NAVIGATE = "navigate"
CATALOG_CLICK_HOLD_BEHAVIORS = {
    CATALOG_DRAG_AND_DROP,
    CATALOG_NAVIGATE,
}
DEFAULT_CATALOG_CLICK_HOLD_BEHAVIOR = CATALOG_DRAG_AND_DROP

SCRIPTING_TAG_SET = "tag_set"
SCRIPTING_PLAIN_SET = "set"
SCRIPTING_TAGS_TYPES = {SCRIPTING_TAG_SET, SCRIPTING_PLAIN_SET}
DEFAULT_SCRIPTING_TAGS_TYPE = SCRIPTING_TAG_SET
# Singular aliases keep the setting easy to discover for integrations.
SCRIPTING_TAG_TYPE_SETTING = SCRIPTING_TAGS_TYPE_SETTING
SCRIPTING_TAGS_SETTING = SCRIPTING_TAGS_TYPE_SETTING
SCRIPTING_TAG_TYPES = SCRIPTING_TAGS_TYPES
SCRIPTING_SET = SCRIPTING_PLAIN_SET


def get_scrolling_behavior(settings: JsonSettings) -> str:
    behavior = settings.value(SCROLLING_BEHAVIOR_SETTING, None, type=str)
    if isinstance(behavior, str) and behavior in SCROLLING_BEHAVIORS:
        return behavior
    return SCROLL_PAN


def get_catalog_click_hold_behavior(settings: JsonSettings) -> str:
    behavior = settings.value(
        CATALOG_CLICK_HOLD_BEHAVIOR_SETTING, None, type=str
    )
    if (
        isinstance(behavior, str)
        and behavior in CATALOG_CLICK_HOLD_BEHAVIORS
    ):
        return behavior
    return DEFAULT_CATALOG_CLICK_HOLD_BEHAVIOR


def get_image_prefetch_count(settings: JsonSettings) -> int:
    count = settings.value(
        IMAGE_PREFETCH_COUNT_SETTING,
        DEFAULT_IMAGE_PREFETCH_COUNT,
        type=int,
    )
    if not isinstance(count, int):
        return DEFAULT_IMAGE_PREFETCH_COUNT
    return max(0, min(MAX_IMAGE_PREFETCH_COUNT, count))


def get_preprocess_options(settings: JsonSettings) -> PreprocessOptions:
    def integer_value(
        key: str, default: int, minimum: int, maximum: int
    ) -> int:
        value = settings.value(key, default, type=int)
        if not isinstance(value, int):
            return default
        return max(minimum, min(maximum, value))

    minimum = integer_value(
        SIMULATOR_ARB_MIN_SIZE_SETTING, DEFAULT_ARB_MIN_SIZE, 64, 8192
    )
    maximum = integer_value(
        SIMULATOR_ARB_MAX_SIZE_SETTING, DEFAULT_ARB_MAX_SIZE, 64, 8192
    )
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    arb_enabled = settings.value(
        SIMULATOR_ARB_ENABLED_SETTING, DEFAULT_ARB_ENABLED, type=bool
    )
    no_upscale = settings.value(
        SIMULATOR_NO_UPSCALE_SETTING, DEFAULT_NO_UPSCALE, type=bool
    )
    return PreprocessOptions(
        training_resolution=integer_value(
            SIMULATOR_TRAINING_RESOLUTION_SETTING,
            DEFAULT_TRAINING_RESOLUTION,
            64,
            8192,
        ),
        arb_enabled=(
            arb_enabled if isinstance(arb_enabled, bool) else DEFAULT_ARB_ENABLED
        ),
        arb_step=integer_value(
            SIMULATOR_ARB_STEP_SETTING, DEFAULT_ARB_STEP, 8, 1024
        ),
        arb_min_size=minimum,
        arb_max_size=maximum,
        no_upscale=(
            no_upscale if isinstance(no_upscale, bool) else DEFAULT_NO_UPSCALE
        ),
    )


def get_grid_type(settings: JsonSettings) -> str:
    grid_type = settings.value(
        SIMULATOR_GRID_TYPE_SETTING, DEFAULT_GRID_TYPE, type=str
    )
    if isinstance(grid_type, str) and grid_type in GRID_TYPES:
        return grid_type
    return DEFAULT_GRID_TYPE


def get_use_unlink(settings: JsonSettings, key: str) -> bool:
    use_unlink = settings.value(key, False, type=bool)
    return use_unlink if isinstance(use_unlink, bool) else False


def get_scripting_tags_type(settings: JsonSettings) -> str:
    tags_type = settings.value(SCRIPTING_TAGS_TYPE_SETTING, None, type=str)
    if isinstance(tags_type, str) and tags_type in SCRIPTING_TAGS_TYPES:
        return tags_type
    return DEFAULT_SCRIPTING_TAGS_TYPE


def get_scripting_tag_type(settings: JsonSettings) -> str:
    return get_scripting_tags_type(settings)


def get_scripting_use_tag_set(settings: JsonSettings) -> bool:
    return get_scripting_tags_type(settings) == SCRIPTING_TAG_SET


def get_deletion_behavior(settings: JsonSettings, key: str) -> str:
    return UNLINK if get_use_unlink(settings, key) else SYSTEM_RECYCLE_BIN
