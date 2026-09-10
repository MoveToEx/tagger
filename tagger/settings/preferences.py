from __future__ import annotations

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
NO_PROXY = "none"
SYSTEM_PROXY = "system"
CUSTOM_PROXY = "custom"
PROXY_MODES = {NO_PROXY, SYSTEM_PROXY, CUSTOM_PROXY}


def get_scrolling_behavior(settings: JsonSettings) -> str:
    behavior = settings.value(SCROLLING_BEHAVIOR_SETTING, None, type=str)
    if isinstance(behavior, str) and behavior in SCROLLING_BEHAVIORS:
        return behavior
    return SCROLL_PAN


def get_image_prefetch_count(settings: JsonSettings) -> int:
    count = settings.value(
        IMAGE_PREFETCH_COUNT_SETTING,
        DEFAULT_IMAGE_PREFETCH_COUNT,
        type=int,
    )
    if not isinstance(count, int):
        return DEFAULT_IMAGE_PREFETCH_COUNT
    return max(0, min(MAX_IMAGE_PREFETCH_COUNT, count))


def get_use_unlink(settings: JsonSettings, key: str) -> bool:
    use_unlink = settings.value(key, False, type=bool)
    return use_unlink if isinstance(use_unlink, bool) else False


def get_deletion_behavior(settings: JsonSettings, key: str) -> str:
    return UNLINK if get_use_unlink(settings, key) else SYSTEM_RECYCLE_BIN
