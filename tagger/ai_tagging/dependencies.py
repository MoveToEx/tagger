from __future__ import annotations

from functools import cache
import importlib.util

from tagger.ai_tagging.models import AI_DEPENDENCIES


def missing_ai_dependencies() -> list[str]:
    return [name for name in AI_DEPENDENCIES if importlib.util.find_spec(name) is None]


@cache
def ai_dependencies_available() -> bool:
    return not missing_ai_dependencies()
