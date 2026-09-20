from __future__ import annotations

from pathlib import Path

import pytest

from tagger.domain.models import ImageEntry
from tagger.probing import (
    BUILTIN_PROBE_RULES,
    CustomProbeRule,
    ProbeConfiguration,
    ProbeRuleError,
    compile_custom_probe_rule,
    get_enabled_probe_rules,
    get_probe_configuration,
    probe_entries,
    save_probe_configuration,
)
from tagger.settings.store import JsonSettings


def _entry(path: Path, tags: list[str]) -> ImageEntry:
    return ImageEntry(path, path.with_suffix(".txt"), tags, b"tags\n")


def test_builtin_rules_report_case_and_separator_variants() -> None:
    entry = _entry(
        Path("sample.png"),
        ["Blue_Eyes", "blue_eyes", "red hair", "red_hair"],
    )

    results = probe_entries([entry], BUILTIN_PROBE_RULES)

    assert len(results) == 1
    assert [issue.rule_identifier for issue in results[0].issues] == [
        "case-variants",
        "separator-variants",
    ]
    assert "Blue_Eyes" in results[0].issues[0].message
    assert "red hair" in results[0].issues[1].message


def test_people_count_rule_reports_number_and_single_multiple_conflicts() -> None:
    rule = next(
        rule
        for rule in BUILTIN_PROBE_RULES
        if rule.identifier == "people-count-conflicts"
    )
    entry = _entry(
        Path("sample.png"),
        [
            "1boy",
            "2boys",
            "3girls",
            "6+ girls",
            "1other",
            "multiple others",
            "1futa",
            "multiple_futas",
        ],
    )

    results = probe_entries([entry], [rule])

    assert len(results) == 1
    messages = [issue.message for issue in results[0].issues]
    assert messages == [
        "Conflicting number tags for boys: 1boy, 2boys",
        "Single and multiple tags conflict for futas: 1futa, multiple_futas",
        "Conflicting number tags for girls: 3girls, 6+ girls",
        "Single and multiple tags conflict for others: 1other, multiple others",
    ]


def test_people_count_rule_allows_consistent_multiple_and_number_tags() -> None:
    rule = next(
        rule
        for rule in BUILTIN_PROBE_RULES
        if rule.identifier == "people-count-conflicts"
    )
    entry = _entry(
        Path("sample.png"),
        ["2boys", "multiple boys", "1girl", "6+ others", "3futas"],
    )

    assert probe_entries([entry], [rule]) == []


@pytest.mark.parametrize(
    "tags",
    [
        ["@first", "@second"],
        ["artist:first", "artist:second"],
        ["@first", "artist:second"],
    ],
)
def test_artist_rule_reports_multiple_artist_tags(tags: list[str]) -> None:
    rule = next(
        rule
        for rule in BUILTIN_PROBE_RULES
        if rule.identifier == "artist-conflicts"
    )

    results = probe_entries([_entry(Path("sample.png"), tags)], [rule])

    assert len(results) == 1
    assert results[0].issues[0].message.startswith("Multiple artist tags: ")
    assert all(tag in results[0].issues[0].message for tag in tags)


def test_artist_rule_ignores_single_or_empty_artist_markers() -> None:
    rule = next(
        rule
        for rule in BUILTIN_PROBE_RULES
        if rule.identifier == "artist-conflicts"
    )

    assert probe_entries(
        [_entry(Path("sample.png"), ["@artist", "@", "artist:"])],
        [rule],
    ) == []


def test_custom_rule_accepts_none_string_and_list_and_receives_relative_path(
    tmp_path: Path,
) -> None:
    definition = CustomProbeRule(
        "required-tags",
        "def handler(fn, tags):\n"
        "    if fn == 'nested/ok.png':\n"
        "        return None\n"
        "    return ['Missing person', 'Missing rating'] if 'cat*' in tags else 'Missing cat'\n",
    )
    rule = compile_custom_probe_rule(definition)
    entries = [
        _entry(tmp_path / "nested" / "ok.png", ["catgirl"]),
        _entry(tmp_path / "bad.png", ["dog"]),
    ]

    results = probe_entries(entries, [rule], root_directory=tmp_path)

    assert len(results) == 1
    assert results[0].entry is entries[1]
    assert [issue.message for issue in results[0].issues] == ["Missing cat"]


def test_rule_return_type_is_validated() -> None:
    rule = compile_custom_probe_rule(
        CustomProbeRule("invalid", "def handler(fn, tags):\n    return True\n")
    )

    with pytest.raises(ProbeRuleError, match="expected None, str, or list"):
        probe_entries([_entry(Path("sample.png"), ["cat"])], [rule])


def test_probe_configuration_round_trips_and_filters_disabled_rules(
    tmp_path: Path,
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    configuration = ProbeConfiguration(
        tuple((rule.identifier, False) for rule in BUILTIN_PROBE_RULES),
        (
            CustomProbeRule(
                "enabled", "def handler(fn, tags):\n    return 'issue'\n"
            ),
            CustomProbeRule(
                "disabled",
                "def handler(fn, tags):\n    return 'issue'\n",
                False,
            ),
        ),
    )

    save_probe_configuration(settings, configuration)

    assert get_probe_configuration(JsonSettings(settings.path)) == configuration
    assert [rule.identifier for rule in get_enabled_probe_rules(settings)] == [
        "enabled"
    ]
