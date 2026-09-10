from __future__ import annotations

from tagger.settings.preferences import (
    CUSTOM_PROXY,
    NO_PROXY,
    PROXY_MODES,
    PROXY_MODE_SETTING,
    PROXY_SETTING,
    SYSTEM_PROXY,
)
from tagger.settings.store import JsonSettings


def _proxy_preferences(settings: JsonSettings) -> tuple[str, str]:
    proxy_value = settings.value(PROXY_SETTING, "", type=str)
    proxy = proxy_value.strip() if isinstance(proxy_value, str) else ""
    mode_value = settings.value(PROXY_MODE_SETTING, None, type=str)
    mode = (
        mode_value
        if isinstance(mode_value, str) and mode_value in PROXY_MODES
        else NO_PROXY
    )
    return mode, proxy


def _resolved_proxy(mode: str, proxy: str) -> str | None:
    if mode == SYSTEM_PROXY:
        return None
    if mode == CUSTOM_PROXY:
        return proxy.strip()
    return ""


def get_download_proxy(settings: JsonSettings) -> str | None:
    """Return None for system discovery, empty for direct, or a proxy URL."""
    mode, proxy = _proxy_preferences(settings)
    return _resolved_proxy(mode, proxy)
