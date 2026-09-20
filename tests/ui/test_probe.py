from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import QMessageBox

from tagger.domain.models import ImageEntry
from tagger.probing import (
    BUILTIN_PROBE_RULES,
    CustomProbeRule,
    ProbeConfiguration,
    ProbeIssue,
    ProbeResult,
    get_probe_configuration,
)
from tagger.settings.dialog import SettingsDialog
from tagger.settings.probing import ProbeRuleEditorDialog
from tagger.settings.store import JsonSettings
from tagger.ui.dialogs.probe import ProbeDialog
from tagger.ui.main_window.window import MainWindow

from .helpers import assert_stable_widget_size, create_png


def test_rule_editor_validates_identifier_and_handler(qtbot) -> None:
    dialog = ProbeRuleEditorDialog(existing_identifiers=["existing"])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert_stable_widget_size(dialog.identifier_input, minimum_width=360)
    assert dialog.handler_input.tabStopDistance() == (
        dialog.handler_input.fontMetrics().horizontalAdvance(" ") * 4
    )

    dialog.identifier_input.setText("existing")
    dialog.save_button.click()
    assert dialog.error_label.isVisible()
    assert "already exists" in dialog.error_label.text()

    dialog.identifier_input.setText("new-rule")
    dialog.handler_input.setPlainText("value = True")
    dialog.save_button.click()
    assert "must define handler" in dialog.error_label.text()

    dialog.handler_input.setPlainText(
        "def handler(fn, tags):\n    return 'Questionable tag'\n"
    )
    dialog.save_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.rule is not None
    assert dialog.rule.identifier == "new-rule"


def test_probing_settings_stage_rule_states_until_apply(
    qtbot, tmp_path: Path
) -> None:
    settings = JsonSettings(tmp_path / "settings.json")
    dialog = SettingsDialog(settings=settings)
    qtbot.addWidget(dialog)

    dialog.navigation_tree.setCurrentItem(dialog.probing_item)
    assert dialog.pages.currentWidget() is dialog.probing_page
    table = dialog.probing_page.rule_table
    assert [table.headerItem().text(column) for column in range(2)] == [
        "Rule",
        "Type",
    ]
    italic_font = QFont(table.font())
    italic_font.setItalic(True)
    type_width = table.header().sectionSize(1)
    assert type_width >= QFontMetrics(italic_font).horizontalAdvance("Built-in") + 36
    builtin_item = table.topLevelItem(0)
    assert builtin_item is not None
    assert builtin_item.text(1) == "Built-in"
    builtin_item.setCheckState(0, Qt.CheckState.Unchecked)
    assert builtin_item.font(0).italic()
    assert builtin_item.font(1).italic()
    assert builtin_item.foreground(0).color() == QColor("#667085")
    assert table.header().sectionSize(1) == type_width
    custom = CustomProbeRule(
        "custom", "def handler(fn, tags):\n    return None\n"
    )
    custom_item = dialog.probing_page._append_custom_rule(custom)
    assert custom_item.text(1) == "User"
    table.setCurrentItem(custom_item)
    assert dialog.probing_page.edit_rule_button.isEnabled()
    assert dialog.probing_page.delete_rule_button.isEnabled()
    dialog.probing_page.changed.emit()

    assert dialog.apply_button.isEnabled()
    staged = get_probe_configuration(settings)
    assert staged.builtin_enabled(BUILTIN_PROBE_RULES[0].identifier)
    assert staged.custom_rules == ()

    dialog.apply_button.click()

    persisted = get_probe_configuration(JsonSettings(settings.path))
    assert not persisted.builtin_enabled(BUILTIN_PROBE_RULES[0].identifier)
    assert persisted.custom_rules == (custom,)


def test_probe_results_switch_problem_list_with_selected_image(qtbot) -> None:
    entries = [
        ImageEntry(Path("one.png"), Path("one.txt")),
        ImageEntry(Path("two.png"), Path("two.txt")),
    ]
    results = [
        ProbeResult(entries[0], (ProbeIssue("first", "One issue"),)),
        ProbeResult(
            entries[1],
            (
                ProbeIssue("second", "Two issue A"),
                ProbeIssue("second", "Two issue B"),
            ),
        ),
    ]
    dialog = ProbeDialog(results, scanned_count=4)
    qtbot.addWidget(dialog)

    assert dialog.image_list.count() == 2
    assert dialog.problem_list.count() == 1
    assert dialog.problem_list.item(0).text() == "first: One issue"
    assert "2 of 4" in dialog.summary_label.text()

    dialog.image_list.setCurrentRow(1)
    assert dialog.problem_list.count() == 2
    assert dialog.problem_list.item(1).text() == "second: Two issue B"


def test_probe_action_shows_progress_then_questionable_images(
    qtbot, tmp_path: Path
) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text(
        "Blue_Eyes, blue_eyes\n", encoding="utf-8"
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)

    assert window.commands.probe_action.isEnabled()
    window.commands.probe_action.trigger()
    qtbot.waitUntil(lambda: window.dialogs._probe_dialog is not None)

    assert window.dialogs._probe_progress_dialog is None
    dialog = window.dialogs._probe_dialog
    assert dialog is not None
    assert dialog.isVisible()
    assert not dialog.isModal()
    assert dialog.image_list.count() == 1
    assert dialog.problem_list.count() == 1
    assert "case-variants" in dialog.problem_list.item(0).text()
    assert not window.commands.probe_action.isEnabled()


def test_probe_action_reports_when_no_issues_are_found(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("blue_eyes\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, message: messages.append((title, message)),
    )

    window.commands.probe_action.trigger()
    qtbot.waitUntil(lambda: bool(messages))

    assert messages == [("No Issues Found", "No tag issues were found.")]
    assert window.dialogs._probe_progress_dialog is None
    assert window.dialogs._probe_dialog is None
    assert window.commands.probe_action.isEnabled()
