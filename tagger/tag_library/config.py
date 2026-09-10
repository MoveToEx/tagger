from __future__ import annotations

from tagger.paths import get_tag_library_path


DEFAULT_TAG_LIBRARY_PATH = get_tag_library_path()
DATASET_ID = "qdlabs/danbooru-tags"
DATASET_TAGS_URL = (
    f"https://huggingface.co/datasets/{DATASET_ID}/resolve/main/tags.jsonl"
)
_RankedTag = tuple[str, str, int]
