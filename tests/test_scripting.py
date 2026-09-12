from __future__ import annotations

from tagger.scripting import TagSet


def test_tag_set_membership_supports_asterisk_patterns() -> None:
    tags = TagSet(["blue_eyes", "red_hair"])

    assert "blue_eyes" in tags
    assert "*_eyes" in tags
    assert "red*" in tags
    assert "green*" not in tags


def test_tag_set_matching_returns_wildcard_captures() -> None:
    tags = TagSet(["dsads", "blue_eyes"])

    assert list(tags.matching("*a*")) == [("dsads", ["ds", "ds"])]
    assert list(tags.matching("blue*")) == [("blue_eyes", "_eyes")]
    assert list(tags.matching("blue_eyes")) == [("blue_eyes", [])]


def test_tag_set_retains_set_operations() -> None:
    tags = TagSet(["cat"])

    assert isinstance(tags | {"dog"}, set)
    assert tags | {"dog"} == {"cat", "dog"}
