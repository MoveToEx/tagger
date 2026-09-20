from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tagger.probing import (
    BUILTIN_PROBE_RULES,
    DEFAULT_CUSTOM_PROBE_HANDLER,
    CustomProbeRule,
    ProbeConfiguration,
    ProbeRuleError,
    compile_custom_probe_rule,
    validate_probe_identifier,
)
from tagger.ui.python_syntax import PythonSyntaxHighlighter
from tagger.ui.widgets import stabilize_widget_size


IDENTIFIER_ROLE = int(Qt.ItemDataRole.UserRole) + 1
HANDLER_ROLE = IDENTIFIER_ROLE + 1
RULE_TYPE_ROLE = HANDLER_ROLE + 1
BUILTIN_RULE_TYPE = "builtin"
USER_RULE_TYPE = "user"


class ProbeRuleEditorDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        rule: CustomProbeRule | None = None,
        existing_identifiers: Sequence[str] = (),
        use_tag_set: bool = True,
    ) -> None:
        super().__init__(parent)
        self._existing_identifiers = tuple(existing_identifiers)
        self.rule: CustomProbeRule | None = None
        self.setWindowTitle("Add Probing Rule" if rule is None else "Edit Probing Rule")
        self.resize(720, 520)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self.identifier_input = QLineEdit(rule.identifier if rule else "")
        self.identifier_input.setPlaceholderText("Unique rule identifier")
        self.identifier_input.setClearButtonEnabled(True)
        stabilize_widget_size(self.identifier_input, minimum_width=360)

        type_name = "TagSet" if use_tag_set else "set[str]"
        default_handler = DEFAULT_CUSTOM_PROBE_HANDLER.replace(
            "TagSet", type_name
        )
        self.handler_input = QPlainTextEdit()
        self.handler_input.setPlainText(
            rule.handler if rule is not None else default_handler
        )
        self.handler_input.setPlaceholderText(
            "Define handler(fn: str, tags: "
            f"{type_name}) -> list[str] | str | None here."
        )
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.handler_input.setFont(font)
        self.handler_input.setTabStopDistance(
            self.handler_input.fontMetrics().horizontalAdvance(" ") * 4
        )
        self.code_input = self.handler_input
        self.highlighter = PythonSyntaxHighlighter(
            self.handler_input.document()
        )

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("QLabel { color: #b42318; }")
        self.error_label.hide()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("Save")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._validate_and_accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Identifier"))
        layout.addWidget(self.identifier_input)
        layout.addWidget(QLabel("Handler"))
        layout.addWidget(self.handler_input, 1)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

    def _validate_and_accept(self) -> None:
        self.error_label.clear()
        self.error_label.hide()
        try:
            identifier = validate_probe_identifier(
                self.identifier_input.text(),
                existing_identifiers=self._existing_identifiers,
            )
            rule = CustomProbeRule(
                identifier,
                self.handler_input.toPlainText(),
                True,
            )
            compile_custom_probe_rule(rule)
        except ProbeRuleError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.rule = rule
        super().accept()


class ProbingSettingsPage(QWidget):
    changed = Signal()

    def __init__(
        self,
        configuration: ProbeConfiguration,
        parent: QWidget | None = None,
        *,
        use_tag_set: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._use_tag_set = use_tag_set or (lambda: True)
        self._updating_items = False

        self.rule_table = QTreeWidget()
        self.rule_table.setHeaderLabels(["Rule", "Type"])
        self.rule_table.setRootIsDecorated(False)
        self.rule_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.rule_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.rule_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        header = self.rule_table.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        italic_font = QFont(self.rule_table.font())
        italic_font.setItalic(True)
        type_metrics = QFontMetrics(italic_font)
        type_width = max(
            type_metrics.horizontalAdvance("Built-in"),
            type_metrics.horizontalAdvance("User"),
        ) + 36
        header.resizeSection(1, type_width)
        self.rules = self.rule_table
        self.rules_table = self.rule_table

        for rule in BUILTIN_PROBE_RULES:
            self._append_rule(
                identifier=rule.identifier,
                rule_type=BUILTIN_RULE_TYPE,
                enabled=configuration.builtin_enabled(rule.identifier),
                tooltip=rule.description,
            )
        for rule in configuration.custom_rules:
            self._append_custom_rule(rule)

        self.rule_table.currentItemChanged.connect(
            self._update_button_states
        )
        self.rule_table.itemDoubleClicked.connect(self._edit_rule)

        self.add_rule_button = QPushButton("Add...")
        self.add_rule_button.clicked.connect(self._add_rule)
        self.edit_rule_button = QPushButton("Edit...")
        self.edit_rule_button.clicked.connect(self._edit_selected_rule)
        self.delete_rule_button = QPushButton("Delete")
        self.delete_rule_button.clicked.connect(self._delete_selected_rule)
        self.add_probe_rule_button = self.add_rule_button
        self.edit_probe_rule_button = self.edit_rule_button
        self.delete_probe_rule_button = self.delete_rule_button

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.add_rule_button)
        buttons.addWidget(self.edit_rule_button)
        buttons.addWidget(self.delete_rule_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.rule_table, 1)
        layout.addLayout(buttons)

        self.rule_table.itemChanged.connect(self._item_changed)
        self._update_button_states()

    def configuration(self) -> ProbeConfiguration:
        builtin_states: list[tuple[str, bool]] = []
        custom_rules: list[CustomProbeRule] = []
        for row in range(self.rule_table.topLevelItemCount()):
            item = self.rule_table.topLevelItem(row)
            if item is None:
                continue
            identifier = item.data(0, IDENTIFIER_ROLE)
            rule_type = item.data(0, RULE_TYPE_ROLE)
            enabled = item.checkState(0) == Qt.CheckState.Checked
            if not isinstance(identifier, str):
                continue
            if rule_type == BUILTIN_RULE_TYPE:
                builtin_states.append((identifier, enabled))
            elif rule_type == USER_RULE_TYPE:
                handler = item.data(0, HANDLER_ROLE)
                if not isinstance(handler, str):
                    continue
                custom_rules.append(
                    CustomProbeRule(
                        identifier,
                        handler,
                        enabled,
                    )
                )
        return ProbeConfiguration(tuple(builtin_states), tuple(custom_rules))

    def _append_rule(
        self,
        *,
        identifier: str,
        rule_type: str,
        enabled: bool,
        handler: str | None = None,
        tooltip: str = "",
    ) -> QTreeWidgetItem:
        type_label = "Built-in" if rule_type == BUILTIN_RULE_TYPE else "User"
        item = QTreeWidgetItem([identifier, type_label])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            0,
            Qt.CheckState.Checked
            if enabled
            else Qt.CheckState.Unchecked
        )
        item.setData(0, IDENTIFIER_ROLE, identifier)
        item.setData(0, RULE_TYPE_ROLE, rule_type)
        if handler is not None:
            item.setData(0, HANDLER_ROLE, handler)
        for column in range(2):
            item.setToolTip(column, tooltip or identifier)
        self._update_item_style(item)
        self.rule_table.addTopLevelItem(item)
        return item

    def _append_custom_rule(self, rule: CustomProbeRule) -> QTreeWidgetItem:
        return self._append_rule(
            identifier=rule.identifier,
            rule_type=USER_RULE_TYPE,
            enabled=rule.enabled,
            handler=rule.handler,
        )

    def _identifiers(
        self, *, excluding_item: QTreeWidgetItem | None = None
    ) -> list[str]:
        identifiers: list[str] = []
        for row in range(self.rule_table.topLevelItemCount()):
            item = self.rule_table.topLevelItem(row)
            if item is None or item is excluding_item:
                continue
            identifier = item.data(0, IDENTIFIER_ROLE)
            if isinstance(identifier, str):
                identifiers.append(identifier)
        return identifiers

    def _add_rule(self) -> None:
        dialog = ProbeRuleEditorDialog(
            self,
            existing_identifiers=self._identifiers(),
            use_tag_set=self._use_tag_set(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.rule is None:
            return
        item = self._append_custom_rule(dialog.rule)
        self.rule_table.setCurrentItem(item)
        self.changed.emit()

    def _edit_selected_rule(self) -> None:
        item = self.rule_table.currentItem()
        if item is not None:
            self._edit_rule(item)

    def _edit_rule(
        self, item: QTreeWidgetItem, _column: int = 0
    ) -> None:
        if item.data(0, RULE_TYPE_ROLE) != USER_RULE_TYPE:
            return
        identifier = item.data(0, IDENTIFIER_ROLE)
        handler = item.data(0, HANDLER_ROLE)
        if not isinstance(identifier, str) or not isinstance(handler, str):
            return
        original = CustomProbeRule(
            identifier,
            handler,
            item.checkState(0) == Qt.CheckState.Checked,
        )
        dialog = ProbeRuleEditorDialog(
            self,
            rule=original,
            existing_identifiers=self._identifiers(excluding_item=item),
            use_tag_set=self._use_tag_set(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.rule is None:
            return
        item.setText(0, dialog.rule.identifier)
        item.setData(0, IDENTIFIER_ROLE, dialog.rule.identifier)
        item.setData(0, HANDLER_ROLE, dialog.rule.handler)
        item.setToolTip(0, dialog.rule.identifier)
        item.setToolTip(1, dialog.rule.identifier)
        self.changed.emit()

    def _delete_selected_rule(self) -> None:
        item = self.rule_table.currentItem()
        if item is None or item.data(0, RULE_TYPE_ROLE) != USER_RULE_TYPE:
            return
        row = self.rule_table.indexOfTopLevelItem(item)
        if row < 0:
            return
        self.rule_table.takeTopLevelItem(row)
        self.changed.emit()

    def _item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._updating_items:
            return
        self._updating_items = True
        try:
            self._update_item_style(item)
        finally:
            self._updating_items = False
        self.changed.emit()

    def _update_item_style(self, item: QTreeWidgetItem) -> None:
        enabled = item.checkState(0) == Qt.CheckState.Checked
        brush = QBrush() if enabled else QBrush(QColor("#667085"))
        for column in range(2):
            font = item.font(column)
            font.setItalic(not enabled)
            item.setFont(column, font)
            item.setForeground(column, brush)

    def _update_button_states(self, *_args: object) -> None:
        item = self.rule_table.currentItem()
        editable = (
            item is not None
            and item.data(0, RULE_TYPE_ROLE) == USER_RULE_TYPE
        )
        self.edit_rule_button.setEnabled(editable)
        self.delete_rule_button.setEnabled(editable)
