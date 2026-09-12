from __future__ import annotations

from tagger.settings.preferences import (
    CUSTOM_PROXY as CUSTOM_PROXY,
    CATALOG_CLICK_HOLD_BEHAVIOR_SETTING as CATALOG_CLICK_HOLD_BEHAVIOR_SETTING,
    CATALOG_CLICK_HOLD_BEHAVIORS as CATALOG_CLICK_HOLD_BEHAVIORS,
    CATALOG_DRAG_AND_DROP as CATALOG_DRAG_AND_DROP,
    CATALOG_NAVIGATE as CATALOG_NAVIGATE,
    DEFAULT_CATALOG_CLICK_HOLD_BEHAVIOR as DEFAULT_CATALOG_CLICK_HOLD_BEHAVIOR,
    IMAGE_PREFETCH_COUNT_SETTING as IMAGE_PREFETCH_COUNT_SETTING,
    NO_PROXY as NO_PROXY,
    OPEN_RECENT_FOLDER_ON_STARTUP_SETTING as OPEN_RECENT_FOLDER_ON_STARTUP_SETTING,
    PARENTHESES_SETTING as PARENTHESES_SETTING,
    PROXY_MODES as PROXY_MODES,
    PROXY_MODE_SETTING as PROXY_MODE_SETTING,
    PROXY_SETTING as PROXY_SETTING,
    SCRIPTING_PLAIN_SET as SCRIPTING_PLAIN_SET,
    SCRIPTING_SET as SCRIPTING_SET,
    SCRIPTING_TAG_SET as SCRIPTING_TAG_SET,
    SCRIPTING_TAG_TYPE_SETTING as SCRIPTING_TAG_TYPE_SETTING,
    SCRIPTING_TAGS_SETTING as SCRIPTING_TAGS_SETTING,
    SCRIPTING_TAGS_TYPE_SETTING as SCRIPTING_TAGS_TYPE_SETTING,
    SCRIPTING_TAG_TYPES as SCRIPTING_TAG_TYPES,
    SCRIPTING_TAGS_TYPES as SCRIPTING_TAGS_TYPES,
    SCROLLING_BEHAVIOR_SETTING as SCROLLING_BEHAVIOR_SETTING,
    SYSTEM_PROXY as SYSTEM_PROXY,
    UNDERSCORES_SETTING as UNDERSCORES_SETTING,
    USE_UNLINK_FOR_DEDUPLICATE_SETTING as USE_UNLINK_FOR_DEDUPLICATE_SETTING,
    USE_UNLINK_FOR_DELETE_FILTER_SETTING as USE_UNLINK_FOR_DELETE_FILTER_SETTING,
    USE_UNLINK_FOR_MANUAL_DELETE_SETTING as USE_UNLINK_FOR_MANUAL_DELETE_SETTING,
    USE_UNLINK_FOR_TIDY_SETTING as USE_UNLINK_FOR_TIDY_SETTING,
    get_deletion_behavior as get_deletion_behavior,
    get_catalog_click_hold_behavior as get_catalog_click_hold_behavior,
    get_image_prefetch_count as get_image_prefetch_count,
    get_scrolling_behavior as get_scrolling_behavior,
    get_scripting_tag_type as get_scripting_tag_type,
    get_scripting_tags_type as get_scripting_tags_type,
    get_scripting_use_tag_set as get_scripting_use_tag_set,
    get_use_unlink as get_use_unlink,
)
from tagger.settings.proxy import get_download_proxy as get_download_proxy
from tagger.settings.store import (
    JsonSettings as JsonSettings,
    create_app_settings as create_app_settings,
)



