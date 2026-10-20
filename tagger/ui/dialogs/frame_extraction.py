from __future__ import annotations

from pathlib import Path
from threading import Condition, Event
import time
from typing import override

from PySide6.QtCore import QThread, QTimer, Qt, QSize, Signal
from PySide6.QtGui import QCloseEvent, QFontMetrics, QIcon, QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLayout, QLineEdit, QListWidget,
    QListWidgetItem, QProgressBar, QPushButton, QSizePolicy, QSlider,
    QSplitter, QVBoxLayout, QWidget,
)

from tagger.frame_extraction import (
    ExtractionResult, VideoInfo, VideoReader, extract_frames,
)
from tagger.ui.widgets import stabilize_widget_size


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


class _PreviewThread(QThread):
    opened = Signal(object)
    loaded = Signal(int, QImage)
    failed = Signal(str)

    def __init__(self, path: Path, parent: QWidget) -> None:
        super().__init__(parent)
        self.path = path
        self._condition = Condition()
        self._pending: int | None = None

    def request_frame(self, index: int) -> None:
        with self._condition:
            self._pending = index
            self._condition.notify()

    def stop(self) -> None:
        self.requestInterruption()
        with self._condition:
            self._condition.notify()
        self.wait()

    @override
    def run(self) -> None:
        reader: VideoReader | None = None
        try:
            import cv2

            reader = VideoReader(self.path)
            self.opened.emit(reader.info)
            index = 0
            while not self.isInterruptionRequested():
                try:
                    frame = reader.read_frame(index)
                    height, width = frame.shape[:2]
                    scale = min(1.0, 1280 / width, 720 / height)
                    if scale < 1:
                        frame = cv2.resize(
                            frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                            interpolation=cv2.INTER_AREA,
                        )
                    height, width = frame.shape[:2]
                    image = QImage(
                        frame.data, width, height, frame.strides[0], QImage.Format.Format_BGR888,
                    ).copy()
                    self.loaded.emit(index, image)
                except (ValueError, cv2.error) as exc:
                    self.failed.emit(str(exc))
                with self._condition:
                    self._condition.wait_for(
                        lambda: self._pending is not None or self.isInterruptionRequested()
                    )
                    if self.isInterruptionRequested():
                        break
                    assert self._pending is not None
                    index, self._pending = self._pending, None
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
        finally:
            if reader is not None:
                reader.close()


class _VideoPreview(QLabel):
    def __init__(self) -> None:
        super().__init__("Loading video...")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 200)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet("background: #101828; color: white;")
        self._source = QPixmap()

    def set_image(self, image: QImage) -> None:
        self._source = QPixmap.fromImage(image)
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        if not self._source.isNull():
            self.setPixmap(self._source.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_pixmap()


class FrameExtractionVideoDialog(QDialog):
    """Choose and validate the source video before opening frame review."""

    def __init__(self, directory: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Frame Extraction — Select Video")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.video_path: Path | None = None
        self._preview_thread: _PreviewThread | None = None
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Choose a video file")
        self.file_input.setClearButtonEnabled(True)
        stabilize_widget_size(self.file_input, minimum_width=420)
        self.file_input.returnPressed.connect(self._open_video)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.file_input)
        row.addWidget(self.browse_button)
        prompt = QLabel("Select the video to extract frames from:")
        prompt.setBuddy(self.file_input)
        destination_label = QLabel(f"Save PNG frames to: {directory}")
        destination_label.setWordWrap(True)
        destination_label.setTextFormat(Qt.TextFormat.PlainText)
        destination_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setStyleSheet("color: #b42318;")
        self.error_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.error_label.hide()
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._open_video)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        layout.addWidget(prompt)
        layout.addLayout(row)
        layout.addWidget(destination_label)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "",
            "Video files (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.mpg *.mpeg *.wmv *.mts *.m2ts);;All files (*)",
        )
        if path:
            self.file_input.setText(path)

    def _open_video(self) -> None:
        if not self.next_button.isEnabled():
            return
        path = Path(self.file_input.text().strip())
        self.error_label.show()
        if not path.is_file():
            self.error_label.setText("Choose an existing video file.")
            return
        self._stop_preview()
        self.error_label.setText("Opening video...")
        self.next_button.setEnabled(False)
        self.file_input.setEnabled(False)
        self.browse_button.setEnabled(False)
        thread = _PreviewThread(path, self)
        thread.loaded.connect(self._video_loaded)
        thread.failed.connect(self._preview_failed)
        self.destroyed.connect(thread.stop)
        self._preview_thread = thread
        thread.start()

    def _video_loaded(self, index: int, image: QImage) -> None:
        if self.sender() is self._preview_thread and self._preview_thread is not None:
            self.video_path = self._preview_thread.path
            self.accept()

    def _preview_failed(self, message: str) -> None:
        if self.sender() is not self._preview_thread:
            return
        self.error_label.setText(message)
        self.next_button.setEnabled(True)
        self.file_input.setEnabled(True)
        self.browse_button.setEnabled(True)

    def _stop_preview(self) -> None:
        if self._preview_thread is not None:
            self._preview_thread.stop()
            self._preview_thread.deleteLater()
            self._preview_thread = None

    @override
    def done(self, result: int) -> None:
        if result == QDialog.DialogCode.Accepted and self.video_path is None:
            return
        self._stop_preview()
        super().done(result)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_preview()
        super().closeEvent(event)


class FrameExtractionDialog(QDialog):
    """Review a video and select individual frames."""

    def __init__(
        self, video_path: Path, directory: Path, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Frame Extraction — Select Frames")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1100, 680)
        self.video_path = video_path
        self.info: VideoInfo | None = None
        self.current_frame = 0
        self._target_frame = 0
        self._current_image = QImage()
        self._preview_thread: _PreviewThread | None = None
        self._selected: dict[int, QListWidgetItem] = {}
        self._playing = False
        self._ready = False
        self._request_time = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance_playback)

        review = self._create_review_panel()
        self.destination_label = QLabel(f"Save PNG frames to: {directory}")
        self.destination_label.setWordWrap(True)
        self.destination_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setStyleSheet("color: #b42318;")
        self.error_label.hide()
        self.finish_button = QPushButton("Finish")
        self.finish_button.clicked.connect(self.accept)
        self.finish_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.finish_button)
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.addWidget(review, 1)
        layout.addWidget(self.destination_label)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)
        self._update_controls()
        self._open_video()

    @property
    def selected_frames(self) -> list[int]:
        return sorted(self._selected)

    def _create_review_panel(self) -> QWidget:
        page = QWidget()
        self.video_label = QLabel()
        self.video_label.setTextFormat(Qt.TextFormat.PlainText)
        self.video_label.setWordWrap(True)
        self.preview = _VideoPreview()
        self.position_label = QLabel()
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setAccessibleName("Video position")
        self.position_slider.valueChanged.connect(self._seek)
        self.back_seconds_button = QPushButton("−2 s")
        self.back_frame_button = QPushButton("−1 frame")
        self.play_button = QPushButton("Play")
        self.forward_frame_button = QPushButton("+1 frame")
        self.forward_seconds_button = QPushButton("+2 s")
        self.select_button = QPushButton("Select Frame")
        self.back_seconds_button.setToolTip("Seek backward by 2 seconds")
        self.back_frame_button.setToolTip("Previous frame")
        self.forward_frame_button.setToolTip("Next frame")
        self.forward_seconds_button.setToolTip("Seek forward by 2 seconds")
        self.play_button.clicked.connect(self._toggle_playback)
        self.back_frame_button.clicked.connect(lambda: self._step(-1))
        self.forward_frame_button.clicked.connect(lambda: self._step(1))
        self.back_seconds_button.clicked.connect(lambda: self._step_seconds(-2))
        self.forward_seconds_button.clicked.connect(lambda: self._step_seconds(2))
        self.select_button.clicked.connect(self._toggle_frame)
        controls = QHBoxLayout()
        for button in (
            self.back_seconds_button, self.back_frame_button, self.play_button,
            self.forward_frame_button, self.forward_seconds_button,
        ):
            controls.addWidget(button)
        controls.addStretch(1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.video_label)
        left_layout.addWidget(self.preview, 1)
        left_layout.addWidget(self.position_slider)
        left_layout.addWidget(self.position_label)
        left_layout.addLayout(controls)
        left_layout.addWidget(self.select_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.selection_label = QLabel("Selected frames (0)")
        self.frame_list = QListWidget()
        self.frame_list.setMinimumWidth(240)
        self.frame_list.setIconSize(QSize(128, 80))
        self.frame_list.setSpacing(4)
        self.frame_list.itemClicked.connect(self._jump_to_selected)
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self._remove_selected)
        self.frame_list.currentItemChanged.connect(
            lambda current, previous: self.remove_button.setEnabled(current is not None)
        )
        right_layout.addWidget(self.selection_label)
        right_layout.addWidget(self.frame_list, 1)
        right_layout.addWidget(self.remove_button)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([740, 300])
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        return page

    def _open_video(self) -> None:
        self._stop_preview()
        self.info = None
        thread = _PreviewThread(self.video_path, self)
        thread.opened.connect(self._video_opened)
        thread.loaded.connect(self._frame_loaded)
        thread.failed.connect(self._preview_failed)
        self.destroyed.connect(thread.stop)
        self._preview_thread = thread
        self._request_time = time.monotonic()
        thread.start()

    def _video_opened(self, info: VideoInfo) -> None:
        if self.sender() is not self._preview_thread:
            return
        self.info = info
        self.position_slider.setRange(0, info.frame_count - 1)

    def _frame_loaded(self, index: int, image: QImage) -> None:
        if (
            self.sender() is not self._preview_thread
            or self.info is None or index != self._target_frame
        ):
            return
        self.current_frame = index
        self._current_image = image
        self._ready = True
        self.error_label.clear()
        self.error_label.hide()
        self.preview.set_image(image)
        self.video_label.setText(
            f"{self.video_path.name}  ·  "
            f"{self.info.width} × {self.info.height}  ·  {self.info.fps:g} fps"
        )
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(index)
        self.position_slider.blockSignals(False)
        self.position_label.setText(
            f"{_timestamp(index / self.info.fps)} / "
            f"{_timestamp((self.info.frame_count - 1) / self.info.fps)}   ·   "
            f"Frame {index + 1} / {self.info.frame_count}"
        )
        self._update_controls()
        if self._playing:
            if index == self.info.frame_count - 1:
                self._pause()
            else:
                elapsed = (time.monotonic() - self._request_time) * 1000
                self._timer.start(max(1, round(1000 / self.info.fps - elapsed)))

    def _preview_failed(self, message: str) -> None:
        if self.sender() is not self._preview_thread:
            return
        self._pause()
        self.error_label.setText(message)
        self.error_label.show()

    def _pause(self) -> None:
        self._playing = False
        self._timer.stop()
        self.play_button.setText("Play")

    def _toggle_playback(self) -> None:
        if self._playing:
            self._pause()
        elif self.info is not None:
            self._playing = True
            self.play_button.setText("Pause")
            if self.current_frame == self.info.frame_count - 1:
                self._request_frame(0)
            else:
                self._request_frame(self.current_frame + 1)

    def _advance_playback(self) -> None:
        if self._playing:
            self._request_frame(self.current_frame + 1)

    def _request_frame(self, index: int) -> None:
        if self.info is None or self._preview_thread is None:
            return
        self._target_frame = max(0, min(self.info.frame_count - 1, index))
        self._ready = False
        self._request_time = time.monotonic()
        self._update_controls()
        self._preview_thread.request_frame(self._target_frame)

    def _seek(self, index: int) -> None:
        self._pause()
        self._request_frame(index)

    def _step(self, delta: int) -> None:
        self._seek(self._target_frame + delta)

    def _step_seconds(self, seconds: int) -> None:
        if self.info is not None:
            self._step(round(seconds * self.info.fps))

    def _toggle_frame(self) -> None:
        if not self._ready:
            return
        self._pause()
        index = self.current_frame
        if index in self._selected:
            item = self._selected.pop(index)
            self.frame_list.takeItem(self.frame_list.row(item))
        else:
            assert self.info is not None
            thumbnail = QPixmap.fromImage(self._current_image).scaled(
                self.frame_list.iconSize(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            item = QListWidgetItem(
                QIcon(thumbnail), f"Frame {index + 1}\n{_timestamp(index / self.info.fps)}",
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.frame_list.insertItem(sum(frame < index for frame in self._selected), item)
            self._selected[index] = item
        self._update_controls()

    def _jump_to_selected(self, item: QListWidgetItem) -> None:
        self._seek(item.data(Qt.ItemDataRole.UserRole))

    def _remove_selected(self) -> None:
        item = self.frame_list.currentItem()
        if item is not None:
            self._selected.pop(item.data(Qt.ItemDataRole.UserRole))
            self.frame_list.takeItem(self.frame_list.row(item))
            self._update_controls()

    def _update_controls(self) -> None:
        self.select_button.setEnabled(self._ready)
        self.play_button.setEnabled(not self._current_image.isNull())
        self.position_slider.setEnabled(self.info is not None)
        self.select_button.setText(
            "Deselect Frame" if self.current_frame in self._selected else "Select Frame"
        )
        self.selection_label.setText(f"Selected frames ({len(self._selected)})")
        self.finish_button.setEnabled(bool(self._selected))
        if self.info is not None:
            self.back_frame_button.setEnabled(self._target_frame > 0)
            self.back_seconds_button.setEnabled(self._target_frame > 0)
            at_end = self._target_frame >= self.info.frame_count - 1
            self.forward_frame_button.setEnabled(not at_end)
            self.forward_seconds_button.setEnabled(not at_end)
        else:
            for button in (
                self.back_frame_button, self.back_seconds_button,
                self.forward_frame_button, self.forward_seconds_button,
            ):
                button.setEnabled(False)

    def _stop_preview(self) -> None:
        self._pause()
        if self._preview_thread is not None:
            self._preview_thread.stop()
            self._preview_thread.deleteLater()
            self._preview_thread = None

    @override
    def done(self, result: int) -> None:
        if result == QDialog.DialogCode.Accepted and not self._selected:
            return
        self._stop_preview()
        super().done(result)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_preview()
        super().closeEvent(event)


class _ExtractionThread(QThread):
    progress = Signal(int, int, int)

    def __init__(
        self, path: Path, frames: list[int], directory: Path, parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.path, self.frames, self.directory = path, frames, directory
        self.cancelled = Event()
        self.result = ExtractionResult()

    def stop(self) -> None:
        self.cancelled.set()
        self.wait()

    @override
    def run(self) -> None:
        try:
            self.result = extract_frames(
                self.path, self.frames, self.directory,
                progress=self.progress.emit, cancelled=self.cancelled.is_set,
            )
        except Exception as exc:
            self.result = ExtractionResult(failures=[str(exc) or type(exc).__name__])


class FrameExtractionProgressDialog(QDialog):
    def __init__(
        self, path: Path, frames: list[int], directory: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extracting Frames")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.label = QLabel("Preparing video...")
        longest_progress = (
            f"Extracting frame {max(frames, default=0) + 1} ({len(frames)}/{len(frames)})..."
        )
        metrics = QFontMetrics(self.label.font())
        self.label.setMinimumWidth(max(
            metrics.horizontalAdvance(message)
            for message in (longest_progress, "Cancelling after the current frame...")
        ))
        self.progress = QProgressBar()
        self.progress.setRange(0, len(frames))
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignRight)
        self._worker = _ExtractionThread(path, frames, directory, self)
        self._worker.progress.connect(self._update_progress)
        self._worker.finished.connect(self._complete)
        self.destroyed.connect(self._worker.stop)
        self._started = False
        self._running = False

    @property
    def result_data(self) -> ExtractionResult:
        return self._worker.result

    def start(self) -> None:
        if not self._started:
            self._started = True
            self._running = True
            self._worker.start()

    def _update_progress(self, completed: int, total: int, index: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(completed)
        if not self._worker.cancelled.is_set():
            self.label.setText(f"Extracting frame {index + 1} ({completed}/{total})...")

    def _complete(self) -> None:
        self._running = False
        self.accept()

    @override
    def reject(self) -> None:
        if self._running:
            self._worker.cancelled.set()
            self.label.setText("Cancelling after the current frame...")
            self.cancel_button.setEnabled(False)
        else:
            super().reject()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._running:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
