from __future__ import annotations


def _search_key(tag: str) -> str:
    return tag.strip().casefold().replace(" ", "_")


def transform_tag_name(
    name: str,
    *,
    underscores_to_spaces: bool = False,
    escape_parentheses: bool = False,
) -> str:
    if underscores_to_spaces:
        name = name.replace("_", " ")
    if escape_parentheses:
        name = name.replace("(", r"\(").replace(")", r"\)")
    return name


def pending_tag(text: str) -> str:
    return text.rsplit(",", 1)[-1].strip()


def replace_pending_tag(text: str, tag: str) -> str:
    head, separator, _pending = text.rpartition(",")
    return f"{head}, {tag}" if separator else tag
