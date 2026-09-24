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
    PROBING_MINIMUM_LEVEL_SETTING,
)
from tagger.settings.store import JsonSettings


ProbeTags = TagSet | set[str]
ProbeHandler = Callable[[str, ProbeTags], object]
ProbeProgress = Callable[[int, int, str], None]
PROBE_ISSUE_LEVELS = ("info", "warning", "error")
DEFAULT_PROBE_MINIMUM_LEVEL = "warning"


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


@dataclass(frozen=True, init=False)
class ProbeConfiguration:
    builtin_states: tuple[tuple[str, bool], ...]
    custom_rules: tuple[CustomProbeRule, ...]
    minimum_level: str = DEFAULT_PROBE_MINIMUM_LEVEL

    def __init__(
        self,
        builtin_states: tuple[tuple[str, bool], ...],
        custom_rules: tuple[CustomProbeRule, ...],
        minimum_level: str = DEFAULT_PROBE_MINIMUM_LEVEL,
        *,
        minimum_issue_level: str | None = None,
    ) -> None:
        if minimum_issue_level is not None:
            minimum_level = minimum_issue_level
        object.__setattr__(self, "builtin_states", builtin_states)
        object.__setattr__(self, "custom_rules", custom_rules)
        object.__setattr__(
            self, "minimum_level", normalize_probe_level(minimum_level)
        )

    def builtin_enabled(self, identifier: str) -> bool:
        return dict(self.builtin_states).get(identifier, True)

    @property
    def minimum_issue_level(self) -> str:
        return self.minimum_level


@dataclass(frozen=True, init=False)
class ProbeIssue:
    rule_identifier: str
    level: str
    message: str

    def __init__(
        self,
        rule_identifier: str,
        message: str,
        level: str | None = None,
    ) -> None:
        # Accept the historical (rule, message) form and the natural
        # (rule, level, message) form while exposing one stable model.
        if (
            level is not None
            and message.casefold() in PROBE_ISSUE_LEVELS
            and level.casefold() not in PROBE_ISSUE_LEVELS
        ):
            message, level = level, message
        object.__setattr__(self, "rule_identifier", rule_identifier)
        object.__setattr__(
            self,
            "level",
            normalize_probe_level(level or "warning"),
        )
        object.__setattr__(self, "message", message)


@dataclass(frozen=True)
class ProbeResult:
    entry: ImageEntry
    issues: tuple[ProbeIssue, ...]


class ProbeRuleError(ValueError):
    pass


def normalize_probe_level(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in PROBE_ISSUE_LEVELS:
            return normalized
    raise ProbeRuleError(
        f"Invalid issue level {value!r}; expected one of "
        + ", ".join(PROBE_ISSUE_LEVELS)
        + "."
    )


def probe_level_rank(level: str) -> int:
    return PROBE_ISSUE_LEVELS.index(normalize_probe_level(level))


def _case_variants(
    _filename: str, tags: ProbeTags
) -> list[tuple[str, str]] | None:
    groups: dict[str, list[str]] = {}
    for tag in sorted(tags, key=lambda value: (value.casefold(), value)):
        groups.setdefault(tag.casefold(), []).append(tag)
    conflicts = [values for values in groups.values() if len(values) > 1]
    if not conflicts:
        return None
    return [
        ("warning", "Tags differ only by letter case: " + ", ".join(values))
        for values in conflicts
    ]


def _separator_variants(
    _filename: str, tags: ProbeTags
) -> list[tuple[str, str]] | None:
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
        (
            "warning",
            "Tags use both spaces and underscores: " + ", ".join(values),
        )
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

_HAIR_COLORS = frozenset(
    {
        "aqua",
        "black",
        "blonde",
        "blue",
        "brown",
        "green",
        "grey",
        "orange",
        "pink",
        "purple",
        "red",
        "white",
    }
)
_EYE_COLORS = frozenset(
    {
        "aqua",
        "black",
        "blue",
        "brown",
        "green",
        "orange",
        "purple",
        "pink",
        "red",
        "white",
        "yellow",
    }
)


def _people_category(value: str) -> str:
    return value.casefold().removesuffix("s")


def _people_category_label(category: str) -> str:
    return f"{category}s"


def _people_count_conflicts(
    _filename: str, tags: ProbeTags
) -> list[tuple[str, str]] | None:
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

    issues: list[tuple[str, str]] = []
    for category in sorted(set(numbered) | set(multiple)):
        numbered_tags = numbered.get(category, [])
        counts = {count for count, _tag in numbered_tags}
        if len(counts) > 1:
            issues.append(
                (
                    "warning",
                    f"Conflicting number tags for {_people_category_label(category)}: "
                    + ", ".join(tag for _count, tag in numbered_tags),
                )
            )
        single_tags = [
            tag for count, tag in numbered_tags if count == "1"
        ]
        multiple_tags = multiple.get(category, [])
        if single_tags and multiple_tags:
            issues.append(
                (
                    "warning",
                    "Single and multiple tags conflict for "
                    f"{_people_category_label(category)}: "
                    + ", ".join([*single_tags, *multiple_tags]),
                )
            )
    return issues or None


def _is_single_character_image(tags: ProbeTags) -> bool:
    single_categories: set[str] = set()
    has_multiple_characters = False
    for tag in tags:
        number_match = _PEOPLE_COUNT_PATTERN.fullmatch(tag)
        if number_match is not None:
            category = _people_category(number_match.group("category"))
            if number_match.group("count") == "1":
                single_categories.add(category)
            else:
                has_multiple_characters = True
            continue
        if _MULTIPLE_PEOPLE_PATTERN.fullmatch(tag) is not None:
            has_multiple_characters = True
    return (
        bool(single_categories)
        and len(single_categories) == 1
        and not has_multiple_characters
    )


def _normalized_style_tag(tag: str) -> str:
    return tag.replace("_", " ").casefold()


def _style_color_tags(
    tags: ProbeTags, suffix: str, colors: frozenset[str]
) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    for tag in sorted(tags, key=lambda value: (value.casefold(), value)):
        normalized = _normalized_style_tag(tag)
        if " " not in normalized:
            continue
        color, tag_suffix = normalized.rsplit(" ", 1)
        if tag_suffix != suffix or color not in colors:
            continue
        matches.setdefault(color, []).append(tag)
    return matches


def _hair_eye_style_conflicts(
    _filename: str, tags: ProbeTags
) -> list[tuple[str, str]] | None:
    if not _is_single_character_image(tags):
        return None

    normalized_tags = {_normalized_style_tag(tag) for tag in tags}
    issues: list[tuple[str, str]] = []

    hair_tags = _style_color_tags(tags, "hair", _HAIR_COLORS)
    if len(hair_tags) > 1 and "multicolored hair" not in normalized_tags:
        issues.append(
            (
                "warning",
                "Conflicting hair colors: "
                + ", ".join(
                    tag
                    for tags_for_color in hair_tags.values()
                    for tag in tags_for_color
                ),
            )
        )

    eye_tags = _style_color_tags(tags, "eyes", _EYE_COLORS)
    if len(eye_tags) > 1 and not {
        "heterochromia",
        "multicolored eyes",
    }.intersection(normalized_tags):
        issues.append(
            (
                "warning",
                "Conflicting eye colors: "
                + ", ".join(
                    tag
                    for tags_for_color in eye_tags.values()
                    for tag in tags_for_color
                ),
            )
        )

    return issues or None


def _artist_tags(tags: ProbeTags) -> list[str]:
    return sorted(
        (
            tag
            for tag in tags
            if (tag.startswith("@") and len(tag) > 1)
            or (tag.casefold().startswith("artist:") and len(tag) > 7)
        ),
        key=lambda value: (value.casefold(), value),
    )


def _artist_conflicts(
    _filename: str, tags: ProbeTags
) -> tuple[str, str] | None:
    artist_tags = _artist_tags(tags)
    if len(artist_tags) < 2:
        return None
    return "warning", "Multiple artist tags: " + ", ".join(artist_tags)


def _artist_missing(_filename: str, tags: ProbeTags) -> tuple[str, str] | None:
    if _artist_tags(tags):
        return None
    return "info", "No artist tag"

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
        "hair-eye-style-conflicts",
        _hair_eye_style_conflicts,
        "Find conflicting hair or eye colors on single-character images.",
        builtin=True,
    ),
    ProbeRule(
        "artist-conflicts",
        _artist_conflicts,
        "Find images with more than one @name or artist:name tag.",
        builtin=True,
    ),
    ProbeRule(
        "artist-missing",
        _artist_missing,
        "Find images without an @name or artist:name tag.",
        builtin=True,
    ),
)


DEFAULT_CUSTOM_PROBE_HANDLER = '''def handler(
    fn: str, tags: TagSet
) -> list[tuple[str, str]] | tuple[str, str] | None:
    return None
'''


def default_probe_configuration() -> ProbeConfiguration:
    return ProbeConfiguration(
        tuple((rule.identifier, True) for rule in BUILTIN_PROBE_RULES),
        (),
        DEFAULT_PROBE_MINIMUM_LEVEL,
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
    raw_minimum_level = settings.value(
        PROBING_MINIMUM_LEVEL_SETTING, DEFAULT_PROBE_MINIMUM_LEVEL
    )
    try:
        minimum_level = normalize_probe_level(raw_minimum_level)
    except ProbeRuleError:
        minimum_level = DEFAULT_PROBE_MINIMUM_LEVEL
    return ProbeConfiguration(
        builtin_states, tuple(custom_rules), minimum_level
    )


def get_probe_minimum_level(settings: JsonSettings) -> str:
    return get_probe_configuration(settings).minimum_level


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
    settings.setValue(
        PROBING_MINIMUM_LEVEL_SETTING,
        normalize_probe_level(configuration.minimum_level),
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
            "handler(fn: str, tags: TagSet) -> "
            "list[tuple[str, str]] | tuple[str, str] | None."
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
) -> list[tuple[str, str]]:
    if value is None:
        return []
    if isinstance(value, str):
        messages = [("warning", value)]
    elif (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(item, str) for item in value)
    ):
        messages = [cast(tuple[str, str], value)]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        messages = [("warning", message) for message in cast(list[str], value)]
    elif isinstance(value, list) and all(
        isinstance(item, tuple)
        and len(item) == 2
        and all(isinstance(part, str) for part in item)
        for item in value
    ):
        messages = cast(list[tuple[str, str]], value)
    else:
        raise ProbeRuleError(
            f"Rule {rule_identifier!r} returned {type(value).__name__} for "
            f"{filename}; expected None, str, or list of issues such as "
            "tuple[level, message], "
            "or list[tuple[level, message]]."
        )
    normalized: list[tuple[str, str]] = []
    for level, message in messages:
        normalized_message = message.strip()
        if not normalized_message:
            raise ProbeRuleError(
                f"Rule {rule_identifier!r} returned an empty issue for {filename}."
            )
        normalized.append((normalize_probe_level(level), normalized_message))
    if any(not message for _level, message in normalized):
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
    minimum_level: str = DEFAULT_PROBE_MINIMUM_LEVEL,
) -> list[ProbeResult]:
    minimum_rank = probe_level_rank(minimum_level)
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
                ProbeIssue(rule.identifier, message, level)
                for level, message in _issue_messages(
                    value,
                    rule_identifier=rule.identifier,
                    filename=filename,
                )
                if probe_level_rank(level) >= minimum_rank
            )
        if issues:
            results.append(ProbeResult(entry, tuple(issues)))
        if progress is not None:
            progress(index + 1, total, filename)
    return results
