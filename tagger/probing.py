from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import cast

from tagger.domain.models import ImageEntry
from tagger.scripting import TagSet
from tagger.settings.preferences import (
    PROBING_BUILTIN_RULES_SETTING,
    PROBING_CUSTOM_RULES_SETTING,
)
from tagger.settings.store import JsonSettings


ProbeTags = TagSet | set[str]
ProbeHandler = Callable[[str, ProbeTags], object]
ProbeProgress = Callable[[int, int, str], None]


@dataclass(frozen=True)
class ProbeRule:
    identifier: str
    handler: ProbeHandler
    description: str = ""
    builtin: bool = False


@dataclass(frozen=True)
class CustomProbeRule:
    identifier: str
    handler: str
    enabled: bool = True


@dataclass(frozen=True)
class ProbeConfiguration:
    builtin_states: tuple[tuple[str, bool], ...]
    custom_rules: tuple[CustomProbeRule, ...]

    def builtin_enabled(self, identifier: str) -> bool:
        return dict(self.builtin_states).get(identifier, True)


@dataclass(frozen=True)
class ProbeIssue:
    rule_identifier: str
    message: str


@dataclass(frozen=True)
class ProbeResult:
    entry: ImageEntry
    issues: tuple[ProbeIssue, ...]


class ProbeRuleError(ValueError):
    pass


def _case_variants(_filename: str, tags: ProbeTags) -> list[str] | None:
    groups: dict[str, list[str]] = {}
    for tag in sorted(tags, key=lambda value: (value.casefold(), value)):
        groups.setdefault(tag.casefold(), []).append(tag)
    conflicts = [values for values in groups.values() if len(values) > 1]
    if not conflicts:
        return None
    return [
        "Tags differ only by letter case: " + ", ".join(values)
        for values in conflicts
    ]


def _separator_variants(_filename: str, tags: ProbeTags) -> list[str] | None:
    groups: dict[str, list[str]] = {}
    for tag in sorted(tags, key=lambda value: (value.casefold(), value)):
        key = tag.replace(" ", "_").casefold()
        groups.setdefault(key, []).append(tag)
    conflicts = [
        values
        for values in groups.values()
        if len(values) > 1 and any(" " in value for value in values)
    ]
    if not conflicts:
        return None
    return [
        "Tags use both spaces and underscores: " + ", ".join(values)
        for values in conflicts
    ]


_PEOPLE_COUNT_PATTERN = re.compile(
    r"^(?P<count>[1-5]|6\+)[ _]?(?P<category>boys?|girls?|others?|futas?)$",
    flags=re.IGNORECASE,
)
_MULTIPLE_PEOPLE_PATTERN = re.compile(
    r"^multiple[ _]+(?P<category>boys?|girls?|others?|futas?)$",
    flags=re.IGNORECASE,
)


def _people_category(value: str) -> str:
    return value.casefold().removesuffix("s")


def _people_category_label(category: str) -> str:
    return f"{category}s"


def _people_count_conflicts(
    _filename: str, tags: ProbeTags
) -> list[str] | None:
    numbered: dict[str, list[tuple[str, str]]] = {}
    multiple: dict[str, list[str]] = {}
    for tag in sorted(tags, key=lambda value: (value.casefold(), value)):
        number_match = _PEOPLE_COUNT_PATTERN.fullmatch(tag)
        if number_match is not None:
            category = _people_category(number_match.group("category"))
            numbered.setdefault(category, []).append(
                (number_match.group("count"), tag)
            )
            continue
        multiple_match = _MULTIPLE_PEOPLE_PATTERN.fullmatch(tag)
        if multiple_match is not None:
            category = _people_category(multiple_match.group("category"))
            multiple.setdefault(category, []).append(tag)

    issues: list[str] = []
    for category in sorted(set(numbered) | set(multiple)):
        numbered_tags = numbered.get(category, [])
        counts = {count for count, _tag in numbered_tags}
        if len(counts) > 1:
            issues.append(
                f"Conflicting number tags for {_people_category_label(category)}: "
                + ", ".join(tag for _count, tag in numbered_tags)
            )
        single_tags = [
            tag for count, tag in numbered_tags if count == "1"
        ]
        multiple_tags = multiple.get(category, [])
        if single_tags and multiple_tags:
            issues.append(
                "Single and multiple tags conflict for "
                f"{_people_category_label(category)}: "
                + ", ".join([*single_tags, *multiple_tags])
            )
    return issues or None


def _artist_conflicts(_filename: str, tags: ProbeTags) -> str | None:
    artist_tags = sorted(
        (
            tag
            for tag in tags
            if (tag.startswith("@") and len(tag) > 1)
            or (tag.casefold().startswith("artist:") and len(tag) > 7)
        ),
        key=lambda value: (value.casefold(), value),
    )
    if len(artist_tags) < 2:
        return None
    return "Multiple artist tags: " + ", ".join(artist_tags)

BUILTIN_PROBE_RULES: tuple[ProbeRule, ...] = (
    ProbeRule(
        "case-variants",
        _case_variants,
        "Find tags that differ only by letter case.",
        builtin=True,
    ),
    ProbeRule(
        "separator-variants",
        _separator_variants,
        "Find equivalent tags written with spaces and underscores.",
        builtin=True,
    ),
    ProbeRule(
        "people-count-conflicts",
        _people_count_conflicts,
        "Find conflicting counts for boys, girls, others, and futas.",
        builtin=True,
    ),
    ProbeRule(
        "artist-conflicts",
        _artist_conflicts,
        "Find images with more than one @name or artist:name tag.",
        builtin=True,
    ),
)


DEFAULT_CUSTOM_PROBE_HANDLER = '''def handler(
    fn: str, tags: TagSet
) -> list[str] | str | None:
    return None
'''


def default_probe_configuration() -> ProbeConfiguration:
    return ProbeConfiguration(
        tuple((rule.identifier, True) for rule in BUILTIN_PROBE_RULES),
        (),
    )


def get_probe_configuration(settings: JsonSettings) -> ProbeConfiguration:
    raw_states = settings.value(PROBING_BUILTIN_RULES_SETTING, {})
    stored_states = raw_states if isinstance(raw_states, dict) else {}
    builtin_states = tuple(
        (
            rule.identifier,
            stored_states.get(rule.identifier, True)
            if isinstance(stored_states.get(rule.identifier, True), bool)
            else True,
        )
        for rule in BUILTIN_PROBE_RULES
    )

    raw_custom_rules = settings.value(PROBING_CUSTOM_RULES_SETTING, [])
    custom_rules: list[CustomProbeRule] = []
    identifiers = {rule.identifier.casefold() for rule in BUILTIN_PROBE_RULES}
    if isinstance(raw_custom_rules, list):
        for value in raw_custom_rules:
            if not isinstance(value, dict):
                continue
            identifier = value.get("identifier")
            handler = value.get("handler")
            enabled = value.get("enabled", True)
            if (
                not isinstance(identifier, str)
                or not identifier.strip()
                or not isinstance(handler, str)
                or not handler.strip()
                or not isinstance(enabled, bool)
            ):
                continue
            identifier = identifier.strip()
            key = identifier.casefold()
            if key in identifiers:
                continue
            identifiers.add(key)
            custom_rules.append(CustomProbeRule(identifier, handler, enabled))
    return ProbeConfiguration(builtin_states, tuple(custom_rules))


def save_probe_configuration(
    settings: JsonSettings,
    configuration: ProbeConfiguration,
    *,
    sync: bool = True,
) -> None:
    settings.setValue(
        PROBING_BUILTIN_RULES_SETTING,
        dict(configuration.builtin_states),
    )
    settings.setValue(
        PROBING_CUSTOM_RULES_SETTING,
        [
            {
                "identifier": rule.identifier,
                "handler": rule.handler,
                "enabled": rule.enabled,
            }
            for rule in configuration.custom_rules
        ],
    )
    if sync:
        settings.sync()


def validate_probe_identifier(
    identifier: str, *, existing_identifiers: Sequence[str] = ()
) -> str:
    normalized = identifier.strip()
    if not normalized:
        raise ProbeRuleError("Enter a rule identifier.")
    if any(character in normalized for character in "\r\n\t"):
        raise ProbeRuleError("The rule identifier must fit on one line.")
    occupied = {value.casefold() for value in existing_identifiers}
    if normalized.casefold() in occupied:
        raise ProbeRuleError(f"A rule named {normalized!r} already exists.")
    return normalized


def compile_custom_probe_rule(
    definition: CustomProbeRule,
) -> ProbeRule:
    try:
        code = compile(
            definition.handler,
            f"<probe-rule:{definition.identifier}>",
            "exec",
        )
        namespace: dict[str, object] = {"TagSet": TagSet}
        exec(code, namespace)
    except Exception as exc:
        raise ProbeRuleError(
            f"Could not compile or execute rule {definition.identifier!r}: {exc}"
        ) from exc
    handler = namespace.get("handler")
    if not callable(handler):
        raise ProbeRuleError(
            f"Rule {definition.identifier!r} must define "
            "handler(fn: str, tags: TagSet) -> list[str] | str | None."
        )
    return ProbeRule(
        definition.identifier,
        cast(ProbeHandler, handler),
    )


def get_enabled_probe_rules(settings: JsonSettings) -> tuple[ProbeRule, ...]:
    configuration = get_probe_configuration(settings)
    rules = [
        rule
        for rule in BUILTIN_PROBE_RULES
        if configuration.builtin_enabled(rule.identifier)
    ]
    rules.extend(
        compile_custom_probe_rule(definition)
        for definition in configuration.custom_rules
        if definition.enabled
    )
    return tuple(rules)


def _filename_for_entry(entry: ImageEntry, root_directory: Path | None) -> str:
    if root_directory is not None:
        try:
            return entry.image_path.relative_to(root_directory).as_posix()
        except ValueError:
            pass
    return entry.image_path.name


def _issue_messages(
    value: object, *, rule_identifier: str, filename: str
) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        messages = [value]
    elif isinstance(value, list) and all(
        isinstance(item, str) for item in value
    ):
        messages = cast(list[str], value)
    else:
        raise ProbeRuleError(
            f"Rule {rule_identifier!r} returned {type(value).__name__} for "
            f"{filename}; expected None, str, or list[str]."
        )
    normalized = [message.strip() for message in messages]
    if any(not message for message in normalized):
        raise ProbeRuleError(
            f"Rule {rule_identifier!r} returned an empty issue for {filename}."
        )
    return normalized


def probe_entries(
    entries: Sequence[ImageEntry],
    rules: Sequence[ProbeRule],
    progress: ProbeProgress | None = None,
    *,
    root_directory: Path | None = None,
    use_tag_set: bool = True,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    total = len(entries)
    for index, entry in enumerate(entries):
        filename = _filename_for_entry(entry, root_directory)
        if progress is not None:
            progress(index, total, filename)
        tags: ProbeTags = (
            TagSet(entry.tags) if use_tag_set else set(entry.tags)
        )
        issues: list[ProbeIssue] = []
        for rule in rules:
            try:
                value = rule.handler(filename, tags)
            except Exception as exc:
                raise ProbeRuleError(
                    f"Rule {rule.identifier!r} failed for {filename}: {exc}"
                ) from exc
            issues.extend(
                ProbeIssue(rule.identifier, message)
                for message in _issue_messages(
                    value,
                    rule_identifier=rule.identifier,
                    filename=filename,
                )
            )
        if issues:
            results.append(ProbeResult(entry, tuple(issues)))
        if progress is not None:
            progress(index + 1, total, filename)
    return results
