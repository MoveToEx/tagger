from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QGuiApplication, QWheelEvent
from PySide6.QtWidgets import QMenu, QProxyStyle, QStyle, QToolBar, QToolButton

from tagger.settings.preferences import (
    CATALOG_CLICK_HOLD_BEHAVIOR_SETTING,
    CATALOG_NAVIGATE,
    SCROLLING_BEHAVIOR_SETTING,
)
from tagger.settings.store import JsonSettings
from tagger.ui.main_window.window import MainWindow
import tagger.ui.main_window.window as main_window_module
from tagger.ui.preview.config import SCROLL_NAVIGATE, SCROLL_ZOOM
from tagger.ui.widgets import _StableCheckedToolButtonStyle

from .helpers import create_png


def test_navigation_actions_stop_at_boundaries(qtbot, tmp_path: Path) -> None:
    create_png(tmp_path / "a.png")
    create_png(tmp_path / "b.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)

    assert not window.commands.previous_action.isEnabled()
    assert window.commands.next_action.isEnabled()
    window.commands.next_action.trigger()
    assert window.image_list.currentIndex().row() == 1
    assert not window.commands.next_action.isEnabled()
    assert window.commands.previous_action.isEnabled()


def test_toolbar_uses_navigation_and_zoom_icons(
    qtbot, tmp_path: Path
) -> None:
    create_png(tmp_path / "sample.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitUntil(lambda: window.image_view._pixmap is not None)
    toolbar = window.findChild(QToolBar)
    assert toolbar is not None

    toolbar_actions_with_icons = [
        window.commands.open_action,
        window.commands.close_folder_action,
        window.commands.previous_action,
        window.commands.next_action,
        window.commands.zoom_in_action,
        window.commands.fit_action,
        window.commands.zoom_out_action,
    ]
    buttons: dict[QAction, QToolButton] = {}
    for action in toolbar_actions_with_icons:
        widget = toolbar.widgetForAction(action)
        assert isinstance(widget, QToolButton)
        assert not action.icon().isNull()
        assert not action.isIconVisibleInMenu()
        assert (
            widget.toolButtonStyle()
            == Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        buttons[action] = widget

    toolbar_actions = toolbar.actions()
    assert toolbar_actions[:2] == [
        window.commands.open_action,
        window.commands.close_folder_action,
    ]
    assert toolbar_actions[2].isSeparator()
    assert toolbar_actions.index(window.commands.zoom_in_action) < toolbar_actions.index(
        window.commands.fit_action
    ) < toolbar_actions.index(window.commands.zoom_out_action)

    assert window.commands.previous_action.text() == "Previous"
    assert window.commands.next_action.text() == "Next"
    initial_zoom = window.image_view._zoom
    buttons[window.commands.zoom_in_action].click()
    assert window.image_view._zoom > initial_zoom
    buttons[window.commands.zoom_out_action].click()
    assert window.image_view._zoom == initial_zoom


def test_checked_toolbar_style_only_suppresses_released_button_shift(qtbot) -> None:
    class ShiftStyle(QProxyStyle):
        def pixelMetric(self, metric, option=None, widget=None) -> int:
            if metric in {
                QStyle.PixelMetric.PM_ButtonShiftHorizontal,
                QStyle.PixelMetric.PM_ButtonShiftVertical,
            }:
                return 2
            return super().pixelMetric(metric, option, widget)

    button = QToolButton()
    qtbot.addWidget(button)
    button.setCheckable(True)
    style = _StableCheckedToolButtonStyle(ShiftStyle())
    style.setParent(button)
    button.setStyle(style)
    horizontal_shift = QStyle.PixelMetric.PM_ButtonShiftHorizontal

    button.setChecked(True)
    button.setDown(False)
    assert style.pixelMetric(horizontal_shift, None, button) == 0

    button.setDown(True)
    assert style.pixelMetric(horizontal_shift, None, button) == 2

    button.setDown(False)
    button.setChecked(False)
    assert style.pixelMetric(horizontal_shift, None, button) == 2


def test_mouse_wheel_navigate_setting_changes_images_and_menu_item_is_removed(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "a.png")
    create_png(tmp_path / "b.png")
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(SCROLLING_BEHAVIOR_SETTING, SCROLL_NAVIGATE)
    monkeypatch.setattr(main_window_module, "create_app_settings", lambda: settings)
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    navigate_menu = next(
        menu
        for menu in window.menuBar().findChildren(QMenu)
        if menu.title() == "&Navigate"
    )
    assert all(
        action.text() != "Scroll to Navigate"
        for action in navigate_menu.actions()
    )
    assert window.image_view._scrolling_behavior == SCROLL_NAVIGATE
    wheel = QWheelEvent(
        window.image_view.viewport().rect().center(),
        window.image_view.viewport().mapToGlobal(
            window.image_view.viewport().rect().center()
        ),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QGuiApplication.sendEvent(window.image_view.viewport(), wheel)

    assert window.image_list.currentIndex().row() == 1


def test_catalog_navigate_click_hold_behavior_selects_without_dragging(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    create_png(tmp_path / "a.png")
    create_png(tmp_path / "b.png")
    settings = JsonSettings(tmp_path / "settings.json")
    settings.setValue(CATALOG_CLICK_HOLD_BEHAVIOR_SETTING, CATALOG_NAVIGATE)
    monkeypatch.setattr(main_window_module, "create_app_settings", lambda: settings)
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)

    assert not window.image_list.dragEnabled()
    assert window.image_list.click_hold_behavior == CATALOG_NAVIGATE
    assert (
        window.image_list.dragDropMode()
        == window.image_list.DragDropMode.DropOnly
    )

    target = window.catalog.index_for_row(1)
    qtbot.mouseClick(
        window.image_list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=window.image_list.visualRect(target).center(),
    )
    assert window.image_list.currentIndex() == target


def test_zoom_scroll_behavior_zooms_instead_of_navigating(
    qtbot, tmp_path: Path
) -> None:
    create_png(tmp_path / "a.png")
    create_png(tmp_path / "b.png")
    window = MainWindow()
    qtbot.addWidget(window)
    window.folders._load_directory(tmp_path, show_issues=False)
    window.show()
    qtbot.waitExposed(window)
    qtbot.waitUntil(lambda: window.image_view._pixmap is not None)
    window.image_view.set_scrolling_behavior(SCROLL_ZOOM)
    initial_zoom = window.image_view._zoom
    wheel = QWheelEvent(
        window.image_view.viewport().rect().center(),
        window.image_view.viewport().mapToGlobal(
            window.image_view.viewport().rect().center()
        ),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )

    QGuiApplication.sendEvent(window.image_view.viewport(), wheel)

    assert window.image_list.currentIndex().row() == 0
    assert not window.commands.fit_action.isChecked()
    assert window.image_view._zoom > initial_zoom
