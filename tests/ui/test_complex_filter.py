from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from tagger.domain.models import ImageEntry
from tagger.ui.dialogs.complex_filter import ComplexFilterDialog
from tagger.ui.main_window.window import MainWindow

from .helpers import create_png


def test_complex_filter_is_modeless_and_keeps_main_window_available(
    qtbot, tmp_path: Path
) -> None:
    create_png(tmp_path / "sample.png")
    (tmp_path / "sample.txt").write_text("cat\n", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)

    window.dialogs._open_complex_filter()
    dialog = window.dialogs._complex_filter_dialog
    assert dialog is not None
    assert not dialog.isModal()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert window.image_list.isEnabled()
    window._select_row(0)
    assert window._current_entry() is not None

    window.dialogs._open_complex_filter()
    assert window.dialogs._complex_filter_dialog is dialog


def test_complex_filter_double_click_selects_image_in_main_window(
    qtbot, tmp_path: Path
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    for name, folder in [("first.png", tmp_path), ("second.png", nested)]:
        create_png(folder / name)
        (folder / f"{Path(name).stem}.txt").write_text(
            "cat\n", encoding="utf-8"
        )

    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.dialogs._open_complex_filter()
    dialog = window.dialogs._complex_filter_dialog
    assert dialog is not None

    dialog.run_filter()
    result_item = dialog.results.item(1, 0)
    assert result_item is not None
    dialog.results.itemDoubleClicked.emit(result_item)

    current = window._current_entry()
    assert current is not None
    assert current.image_path == nested / "second.png"


def test_complex_filter_executes_check_and_shows_matching_images(
    qtbot, tmp_path: Path
) -> None:
    entries: list[ImageEntry] = []
    for name, tags in {"cat.png": ["cat"], "dog.png": ["dog"]}.items():
        image_path = tmp_path / name
        tag_path = tmp_path / f"{Path(name).stem}.txt"
        create_png(image_path)
        source = (", ".join(tags) + "\n").encode()
        tag_path.write_bytes(source)
        entries.append(ImageEntry(image_path, tag_path, tags, source))

    dialog = ComplexFilterDialog(entries)
    qtbot.addWidget(dialog)
    assert dialog.code_input.tabStopDistance() == (
        dialog.code_input.fontMetrics().horizontalAdvance(" ") * 4
    )
    dialog.code_input.setPlainText(
        "def check(fn: str, tags: set[str]) -> bool:\n"
        "    return fn.endswith('.png') and 'cat' in tags\n"
    )
    dialog.run_filter()

    assert dialog.results.rowCount() == 1
    image_item = dialog.results.item(0, 0)
    assert image_item is not None
    assert image_item.text() == "cat.png"
    assert dialog.result_label.text() == "1 matching image(s) out of 2."
    assert dialog.error_label.isHidden()


def test_complex_filter_reports_missing_check_function(qtbot) -> None:
    dialog = ComplexFilterDialog([])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.code_input.setPlainText("value = True")
    dialog.run_filter()

    assert dialog.results.rowCount() == 0
    assert dialog.error_label.isVisible()
    assert "must define check" in dialog.error_label.text()
