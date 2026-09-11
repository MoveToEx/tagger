from __future__ import annotations

import os
from pathlib import Path
from typing import override

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from tagger.ai_tagging.inference import _InferenceProcess
from tagger.ai_tagging.models import MODEL_REPOSITORIES
from tagger.domain.models import ImageEntry
from tagger.domain.tags import normalize_tags
from tagger.storage import (
    BatchCommitResult,
    BatchPreflightError,
    WriteRequest,
    write_tags_batch,
)
from tagger.ui.mouse_navigation import MouseNavigation
from tagger.ui.preview.config import DEFAULT_IMAGE_PREFETCH_COUNT
from tagger.ui.preview.loader import PreviewLoader
from tagger.ui.preview.view import ImageView
from tagger.ui.widgets import stabilize_widget_size

from . import cache


def _folder_ancestors(path: Path) -> list[Path]:
    if path == Path("."):
        return []
    return [Path(*path.parts[:length]) for length in range(1, len(path.parts) + 1)]


class AITaggingDialog(QDialog):
    def __init__(
        self,
        entries: list[ImageEntry],
        parent=None,
        *,
        root_directory: Path | None = None,
        proxy: str | None = None,
        image_prefetch_count: int = DEFAULT_IMAGE_PREFETCH_COUNT,
    ) -> None:
        super().__init__(parent)
        self._entries = [entry for entry in entries if entry.editable]
        self._root_directory = root_directory or self._common_root_directory()
        self._proxy = proxy.strip() if proxy is not None else None
        self._updating_checks = False
        self._selected_entries: list[ImageEntry] = []
        self._results: dict[str, list[tuple[str, float]]] = {}
        self._selected_additions: dict[int, list[str]] = {}
        self._current_index = 0
        self._image_prefetch_count = max(0, image_prefetch_count)
        self._inference_process: _InferenceProcess | None = None
        self.commit_result: BatchCommitResult | None = None

        self.setWindowTitle("AI Tagging")
        self.resize(1000, 700)
        self.pages = QStackedWidget()
        self.selection_page = self._create_selection_page()
        self.progress_page = self._create_progress_page()
        self.review_page = self._create_review_page()
        self.pages.addWidget(self.selection_page)
        self.pages.addWidget(self.progress_page)
        self.pages.addWidget(self.review_page)
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)
        self._populate_images()
        self._mouse_navigation = MouseNavigation(
            self, back=[self.back_button], forward=[self.next_button]
        )

    def _create_selection_page(self) -> QWidget:
        page = QWidget()
        self.image_selection = QTreeWidget()
        self.folder_tree = self.image_selection
        self.image_selection.setHeaderLabel("Folder / Image")
        self.image_selection.setSelectionMode(
            QTreeWidget.SelectionMode.NoSelection
        )
        self.image_selection.itemChanged.connect(self._selection_check_changed)
        self.selection_label = QLabel()
        self.model_input = QComboBox()
        first_available_index = -1
        for name, repo_id in MODEL_REPOSITORIES.items():
            self.model_input.addItem(name, repo_id)
            index = self.model_input.count() - 1
            available = bool(cache._cached_model_locations(repo_id))
            model = self.model_input.model()
            if isinstance(model, QStandardItemModel):
                item = model.item(index)
                if item is not None:
                    item.setEnabled(available)
            if available and first_available_index == -1:
                first_available_index = index
        self.model_input.setCurrentIndex(first_available_index)
        stabilize_widget_size(self.model_input)
        self.general_threshold_input = QDoubleSpinBox()
        self.general_threshold_input.setRange(0.0, 1.0)
        self.general_threshold_input.setSingleStep(0.05)
        self.general_threshold_input.setValue(0.35)
        stabilize_widget_size(self.general_threshold_input, vertical_padding=2)
        self.character_threshold_input = QDoubleSpinBox()
        self.character_threshold_input.setRange(0.0, 1.0)
        self.character_threshold_input.setSingleStep(0.05)
        self.character_threshold_input.setValue(0.75)
        stabilize_widget_size(self.character_threshold_input, vertical_padding=2)
        form = QFormLayout()
        form.addRow("Model", self.model_input)
        form.addRow("General threshold", self.general_threshold_input)
        form.addRow("Character threshold", self.character_threshold_input)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.start_button = QPushButton("Run Inference")
        self.start_button.clicked.connect(self._start_inference)
        self.model_input.currentIndexChanged.connect(self._update_start_button)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.start_button)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Target images"))
        layout.addWidget(self.image_selection, 1)
        layout.addWidget(self.selection_label)
        layout.addLayout(form)
        layout.addLayout(buttons)
        return page

    def _create_progress_page(self) -> QWidget:
        page = QWidget()
        self.inference_progress = QProgressBar()
        self.inference_status = QLabel("Preparing inference...")
        self.inference_status.setWordWrap(True)
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        layout.addWidget(self.inference_status)
        layout.addWidget(self.inference_progress)
        layout.addStretch(1)
        return page

    def _create_review_page(self) -> QWidget:
        page = QWidget()
        self.review_progress = QLabel()
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.image_view = ImageView()
        self.preview_loader = PreviewLoader(self)
        self.preview_loader.loaded.connect(self._preview_loaded)
        self.current_tags = QPlainTextEdit()
        self.current_tags.setReadOnly(True)
        self.current_tags.setMaximumHeight(100)
        self.ai_tags = QListWidget()
        self.ai_tags.installEventFilter(self)
        self.ai_tags.itemChanged.connect(self._update_result_tags)
        self.result_tags = QPlainTextEdit()
        self.result_tags.setReadOnly(True)
        self.result_tags.setMaximumHeight(100)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(10, 0, 0, 0)
        details_layout.addWidget(QLabel("Current tags"))
        details_layout.addWidget(self.current_tags)
        details_layout.addWidget(QLabel("AI tags"))
        details_layout.addWidget(self.ai_tags, 1)
        details_layout.addWidget(QLabel("Result"))
        details_layout.addWidget(self.result_tags)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.image_view)
        splitter.addWidget(details)
        splitter.setSizes([650, 350])

        self.back_button = QPushButton("Back")
        self.apply_all_button = QPushButton("Apply All")
        self.next_button = QPushButton("Next")
        self.finish_button = QPushButton("Finish")
        self.back_button.clicked.connect(self._back)
        self.apply_all_button.clicked.connect(self._apply_all)
        self.next_button.clicked.connect(self._next)
        self.finish_button.clicked.connect(self._finish)
        buttons = QHBoxLayout()
        buttons.addWidget(self.back_button)
        buttons.addWidget(self.apply_all_button)
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.finish_button)
        layout = QVBoxLayout(page)
        layout.addWidget(self.review_progress)
        layout.addWidget(self.path_label)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)
        return page

    def _populate_images(self) -> None:
        root_directory = self._root_directory
        root_label = root_directory.name or str(root_directory)
        root_item = QTreeWidgetItem([root_label])
        root_item.setFlags(root_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setData(0, Qt.ItemDataRole.UserRole, str(root_directory))
        root_item.setCheckState(0, Qt.CheckState.Unchecked)
        self.image_selection.addTopLevelItem(root_item)
        folder_items: dict[Path, QTreeWidgetItem] = {Path("."): root_item}
        relative_folders = {
            ancestor
            for entry in self._entries
            for ancestor in _folder_ancestors(
                entry.image_path.parent.relative_to(root_directory)
            )
        }
        for relative_folder in sorted(
            relative_folders,
            key=lambda path: (
                len(path.parts),
                tuple(part.casefold() for part in path.parts),
                path.as_posix(),
            ),
        ):
            item = QTreeWidgetItem([relative_folder.name])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                str(root_directory / relative_folder),
            )
            item.setCheckState(0, Qt.CheckState.Unchecked)
            folder_items[relative_folder.parent].addChild(item)
            folder_items[relative_folder] = item

        self._updating_checks = True
        for entry in self._entries:
            relative_parent = entry.image_path.parent.relative_to(root_directory)
            item = QTreeWidgetItem([entry.image_path.name])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, entry)
            item.setToolTip(0, str(entry.image_path))
            item.setCheckState(
                0,
                Qt.CheckState.Checked
                if not entry.tags
                else Qt.CheckState.Unchecked,
            )
            folder_items[relative_parent].addChild(item)
        self._refresh_folder_check_states(root_item)
        self._updating_checks = False
        self.image_selection.expandAll()
        self._update_start_button()

    def _common_root_directory(self) -> Path:
        if not self._entries:
            return Path(".")
        return Path(
            os.path.commonpath(
                [str(entry.image_path.parent) for entry in self._entries]
            )
        )

    def _refresh_folder_check_states(
        self, item: QTreeWidgetItem
    ) -> Qt.CheckState:
        child_states = [
            self._refresh_folder_check_states(child)
            if child.childCount()
            else child.checkState(0)
            for index in range(item.childCount())
            if (child := item.child(index)) is not None
        ]
        if child_states and all(
            state == Qt.CheckState.Checked for state in child_states
        ):
            state = Qt.CheckState.Checked
        elif child_states and all(
            state == Qt.CheckState.Unchecked for state in child_states
        ):
            state = Qt.CheckState.Unchecked
        else:
            state = Qt.CheckState.PartiallyChecked
        item.setCheckState(0, state)
        return state

    def _selection_check_changed(
        self, item: QTreeWidgetItem, column: int
    ) -> None:
        if self._updating_checks or column != 0:
            return
        self._updating_checks = True
        try:
            state = item.checkState(0)
            if state in {Qt.CheckState.Checked, Qt.CheckState.Unchecked}:
                self._set_descendant_check_state(item, state)
            self._update_ancestor_check_states(item.parent())
        finally:
            self._updating_checks = False
        self._update_start_button()

    def _set_descendant_check_state(
        self, item: QTreeWidgetItem, state: Qt.CheckState
    ) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            if child is None:
                continue
            child.setCheckState(0, state)
            self._set_descendant_check_state(child, state)

    def _update_ancestor_check_states(
        self, item: QTreeWidgetItem | None
    ) -> None:
        while item is not None:
            child_states = [
                child.checkState(0)
                for index in range(item.childCount())
                if (child := item.child(index)) is not None
            ]
            if child_states and all(
                state == Qt.CheckState.Checked for state in child_states
            ):
                state = Qt.CheckState.Checked
            elif child_states and all(
                state == Qt.CheckState.Unchecked for state in child_states
            ):
                state = Qt.CheckState.Unchecked
            else:
                state = Qt.CheckState.PartiallyChecked
            item.setCheckState(0, state)
            item = item.parent()

    def _checked_entries(self) -> list[ImageEntry]:
        checked_paths: set[Path] = set()
        iterator = QTreeWidgetItemIterator(self.image_selection)
        while iterator.value() is not None:
            item = iterator.value()
            if item.checkState(0) == Qt.CheckState.Checked:
                value = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if isinstance(value, ImageEntry):
                    checked_paths.add(value.image_path)
            iterator += 1
        return [
            entry for entry in self._entries if entry.image_path in checked_paths
        ]

    def _update_start_button(self, *_args) -> None:
        count = len(self._checked_entries())
        self.selection_label.setText(f"{count} image(s) selected.")
        self.start_button.setEnabled(
            count > 0 and self.model_input.currentIndex() >= 0
        )

    def _start_inference(self) -> None:
        if self._inference_process is not None:
            return
        entries = self._checked_entries()
        repo_id = self.model_input.currentData()
        if not entries or not isinstance(repo_id, str):
            return
        self._selected_entries = entries
        self.inference_progress.setRange(0, len(entries))
        self.inference_progress.setValue(0)
        self.inference_status.setText("Preparing inference...")
        self.pages.setCurrentWidget(self.progress_page)
        process = _InferenceProcess(
            [entry.image_path for entry in entries],
            repo_id,
            self.general_threshold_input.value(),
            self.character_threshold_input.value(),
            self._proxy,
            cache._preferred_model_cache_directory(repo_id),
            self,
        )
        process.progress.connect(self._inference_progressed)
        process.completed.connect(self._inference_completed)
        process.failed.connect(self._inference_failed)
        self._inference_process = process
        process.start()

    def _inference_progressed(self, value: int, total: int, message: str) -> None:
        self.inference_progress.setRange(0, total)
        self.inference_progress.setValue(value)
        self.inference_status.setText(message)

    def _inference_completed(self, results: object) -> None:
        self._release_inference_process()
        self._results = dict(results) if isinstance(results, dict) else {}
        self._selected_additions.clear()
        self._current_index = 0
        self.pages.setCurrentWidget(self.review_page)
        self._load_current()

    def _inference_failed(self, message: str) -> None:
        self._release_inference_process()
        self.pages.setCurrentWidget(self.selection_page)
        QMessageBox.critical(self, "AI Inference Failed", message)

    def _release_inference_process(self) -> None:
        process = self._inference_process
        self._inference_process = None
        if process is not None:
            process.deleteLater()

    def _load_current(self) -> None:
        entry = self._selected_entries[self._current_index]
        self.review_progress.setText(
            f"Image {self._current_index + 1} of {len(self._selected_entries)}"
        )
        self.path_label.setText(str(entry.image_path))
        self.current_tags.setPlainText(", ".join(entry.tags) or "(none)")
        self.ai_tags.clear()
        existing = set(entry.tags)
        selected = set(self._selected_additions.get(self._current_index, ()))
        for tag, probability in self._results.get(str(entry.image_path), ()):
            if tag in existing:
                continue
            item = QListWidgetItem(f"{tag} ({probability:.1%})")
            item.setData(Qt.ItemDataRole.UserRole, tag)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if tag in selected else Qt.CheckState.Unchecked
            )
            self.ai_tags.addItem(item)
        if self.ai_tags.count():
            self.ai_tags.setCurrentRow(0)
            self.ai_tags.setFocus()
        self.image_view.clear_image("Loading image...")
        next_index = self._current_index + 1
        prefetch_paths = [
            future_entry.image_path
            for future_entry in self._selected_entries[
                next_index : next_index + self._image_prefetch_count
            ]
        ]
        self.preview_loader.load(entry.image_path, prefetch_paths)
        self.back_button.setEnabled(self._current_index > 0)
        self.next_button.setEnabled(
            self._current_index + 1 < len(self._selected_entries)
        )
        self._update_result_tags()

    def _checked_tags(self) -> list[str]:
        return [
            str(item.data(Qt.ItemDataRole.UserRole))
            for row in range(self.ai_tags.count())
            if (item := self.ai_tags.item(row)).checkState() == Qt.CheckState.Checked
        ]

    def _stage_current(self) -> None:
        self._selected_additions[self._current_index] = self._checked_tags()

    def _update_result_tags(self, *_args) -> None:
        if not self._selected_entries:
            return
        entry = self._selected_entries[self._current_index]
        self.result_tags.setPlainText(", ".join(normalize_tags([*entry.tags, *self._checked_tags()])))

    def _toggle_current(self) -> None:
        item = self.ai_tags.currentItem()
        if item is None:
            return
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

    def _toggle_all(self) -> None:
        if not self.ai_tags.count():
            return
        all_checked = all(
            self.ai_tags.item(row).checkState() == Qt.CheckState.Checked
            for row in range(self.ai_tags.count())
        )
        state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        for row in range(self.ai_tags.count()):
            self.ai_tags.item(row).setCheckState(state)

    def _next(self) -> None:
        self._stage_current()
        if self._current_index + 1 < len(self._selected_entries):
            self._current_index += 1
            self._load_current()

    def _back(self) -> None:
        self._stage_current()
        if self._current_index > 0:
            self._current_index -= 1
            self._load_current()

    def _apply_all(self) -> None:
        if self.pages.currentWidget() is not self.review_page:
            return
        self._finish(ignore_decisions=True)

    def _finish(self, *, ignore_decisions: bool = False) -> None:
        self._stage_current()
        additions_by_index = self._selected_additions
        if ignore_decisions:
            additions_by_index = {
                index: [
                    tag
                    for tag, _probability in self._results.get(
                        str(entry.image_path), ()
                    )
                    if tag not in entry.tags
                ]
                for index, entry in enumerate(self._selected_entries)
            }
        requests: list[WriteRequest] = []
        for index, additions in additions_by_index.items():
            if not additions:
                continue
            entry = self._selected_entries[index]
            requests.append(
                WriteRequest(
                    entry.tag_path,
                    normalize_tags([*entry.tags, *additions]),
                    entry.source_bytes,
                )
            )
        if not requests:
            self.commit_result = BatchCommitResult([], {})
            self.accept()
            return
        try:
            self.commit_result = write_tags_batch(requests)
        except BatchPreflightError as exc:
            QMessageBox.critical(self, "Could Not Save AI Tags", str(exc))
            return
        if self.commit_result.failures:
            QMessageBox.warning(
                self,
                "Some AI Tags Were Not Saved",
                "\n".join(
                    f"{path.name}: {message}"
                    for path, message in self.commit_result.failures.items()
                ),
            )
        self.accept()

    def _preview_loaded(self, image, error: str) -> None:
        if error or image.isNull():
            self.image_view.clear_image(f"Could not display image\n{error}")
        else:
            self.image_view.set_image(image)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.ai_tags and event.type() == QEvent.Type.KeyPress:
            key = event.key() if isinstance(event, QKeyEvent) else None
            if key == Qt.Key.Key_Space:
                self._toggle_current()
                return True
            if key == Qt.Key.Key_A:
                self._toggle_all()
                return True
            if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right}:
                self._next()
                return True
            if key == Qt.Key.Key_Left:
                self._back()
                return True
        return super().eventFilter(watched, event)

    @override
    def reject(self) -> None:
        if self._inference_process is None:
            super().reject()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._inference_process is None:
            event.accept()
        else:
            event.ignore()
