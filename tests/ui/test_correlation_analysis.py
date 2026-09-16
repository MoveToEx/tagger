from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.correlation_analysis import CorrelationAnalysisDialog
from tagger.ui.main_window.window import MainWindow

from .helpers import create_png


def test_correlation_analysis_selection_and_results(qtbot, tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    entries = [
        ImageEntry(tmp_path / "one.png", tmp_path / "one.txt", ["query", "cat"]),
        ImageEntry(nested / "two.png", nested / "two.txt", ["cat"]),
        ImageEntry(nested / "three.png", nested / "three.txt", ["query", "bird"]),
    ]
    dialog = CorrelationAnalysisDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)

    assert dialog.pages.currentWidget() is dialog.selection_page
    assert len(dialog._checked_entries()) == 3
    root_item = dialog.folder_tree.topLevelItem(0)
    assert root_item is not None
    nested_item = next(
        root_item.child(index)
        for index in range(root_item.childCount())
        if root_item.child(index).text(0) == "nested"
    )
    nested_item.setCheckState(0, Qt.CheckState.Unchecked)
    assert len(dialog._checked_entries()) == 1
    assert dialog.folder_selection_label.text() == "1 image(s) selected."

    nested_item.setCheckState(0, Qt.CheckState.Checked)
    dialog.tag_input.setText("query")
    dialog._show_results_page()

    assert dialog.pages.currentWidget() is dialog.results_page
    assert dialog.result_label.text() == (
        "3 image(s) analyzed: 2 positive, 1 negative for 'query'."
    )
    values: list[list[str]] = []
    for row in range(dialog.results.rowCount()):
        row_values: list[str] = []
        for column in range(4):
            item = dialog.results.item(row, column)
            assert item is not None
            row_values.append(item.text())
        values.append(row_values)
    assert values == [
        ["cat", "1 (33.3%)", "1 (33.3%)", "50.0%"],
        ["bird", "1 (33.3%)", "0 (0.0%)", "100.0%"],
    ]
    first_tag_item = dialog.results.item(0, 0)
    second_tag_item = dialog.results.item(1, 0)
    assert first_tag_item is not None
    assert second_tag_item is not None
    assert first_tag_item.background().color() != QColor("#e0f2fe")
    assert second_tag_item.background().color() != QColor("#e0f2fe")


def test_correlation_analysis_highlights_only_above_90_percent(
    qtbot, tmp_path: Path
) -> None:
    entries = [
        ImageEntry(
            tmp_path / f"positive_{index}.png",
            tmp_path / f"positive_{index}.txt",
            ["query", "strong"],
        )
        for index in range(10)
    ]
    entries.append(
        ImageEntry(tmp_path / "negative.png", tmp_path / "negative.txt", ["strong"])
    )
    dialog = CorrelationAnalysisDialog(entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)

    dialog.tag_input.setText("query")
    dialog.analyze()

    tag_item = dialog.results.item(0, 0)
    positive_item = dialog.results.item(0, 1)
    negative_item = dialog.results.item(0, 2)
    percentage_item = dialog.results.item(0, 3)
    assert tag_item is not None
    assert positive_item is not None
    assert negative_item is not None
    assert percentage_item is not None
    assert tag_item.text() == "strong"
    assert positive_item.text() == "10 (90.9%)"
    assert negative_item.text() == "1 (9.1%)"
    assert percentage_item.text() == "90.9%"
    assert tag_item.background().color() == QColor("#e0f2fe")

    exact_entries = [
        *entries[:9],
        ImageEntry(
            tmp_path / "exact_negative.png",
            tmp_path / "exact_negative.txt",
            ["strong"],
        ),
    ]
    dialog = CorrelationAnalysisDialog(exact_entries, root_directory=tmp_path)
    qtbot.addWidget(dialog)
    dialog.tag_input.setText("query")
    dialog.analyze()
    exact_tag_item = dialog.results.item(0, 0)
    assert exact_tag_item is not None
    assert exact_tag_item.background().color() != QColor("#e0f2fe")


def test_correlation_analysis_limits_related_tags_to_100(qtbot, tmp_path: Path) -> None:
    related_tags = [f"tag_{index:03d}" for index in range(101)]
    entry = ImageEntry(
        tmp_path / "sample.png",
        tmp_path / "sample.txt",
        ["query", *related_tags],
    )
    dialog = CorrelationAnalysisDialog([entry], root_directory=tmp_path)
    qtbot.addWidget(dialog)

    dialog.tag_input.setText("query")
    dialog.analyze()

    assert dialog.results.rowCount() == 100
    assert len(dialog._results) == 100
    for row in range(dialog.results.rowCount()):
        item = dialog.results.item(row, 3)
        assert item is not None
        assert item.text() == "100.0%"


def test_correlation_analysis_action_requires_open_folder(qtbot, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window.commands.correlation_analysis_action.isEnabled()

    create_png(tmp_path / "sample.png")
    window.folders._load_directory(tmp_path, show_issues=False)

    assert window.commands.correlation_analysis_action.isEnabled()
