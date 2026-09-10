from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import override

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader


class _PreviewSignals(QObject):
    finished = Signal(object, int, QImage, str)


class _PreviewWorker(QRunnable):
    def __init__(self, generation: int, path: Path) -> None:
        super().__init__()
        self.generation = generation
        self.path = path
        self.signals = _PreviewSignals()

    @override
    def run(self) -> None:
        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)
        image = reader.read()
        error = "" if not image.isNull() else reader.errorString()
        self.signals.finished.emit(self.path, self.generation, image, error)


class PreviewLoader(QObject):
    loaded = Signal(QImage, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._generation = 0
        self._pool = QThreadPool.globalInstance()
        self._current_path: Path | None = None
        self._desired_paths: set[Path] = set()
        self._cache: dict[Path, tuple[QImage, str]] = {}
        self._inflight: dict[Path, int] = {}

    def clear(self) -> None:
        self._generation += 1
        self._current_path = None
        self._desired_paths.clear()
        self._cache.clear()
        self._inflight.clear()

    def wait_for_done(self) -> bool:
        return self._pool.waitForDone()

    def load(
        self,
        path: Path,
        prefetch_paths: Sequence[Path] = (),
    ) -> None:
        self._generation += 1
        self._current_path = path
        ordered_paths = dict.fromkeys((path, *prefetch_paths))
        self._desired_paths = set(ordered_paths)
        self._cache = {
            cached_path: result
            for cached_path, result in self._cache.items()
            if cached_path in self._desired_paths
        }

        cached = self._cache.get(path)
        if cached is not None:
            self.loaded.emit(*cached)

        for requested_path in ordered_paths:
            if (
                requested_path in self._cache
                or requested_path in self._inflight
            ):
                continue
            worker = _PreviewWorker(self._generation, requested_path)
            self._inflight[requested_path] = self._generation
            worker.signals.finished.connect(self._worker_finished)
            self._pool.start(worker)

    def _worker_finished(
        self,
        path: Path,
        generation: int,
        image: QImage,
        error: str,
    ) -> None:
        if self._inflight.get(path) != generation:
            return
        del self._inflight[path]
        if path not in self._desired_paths:
            return
        self._cache[path] = (image, error)
        if path == self._current_path:
            self.loaded.emit(image, error)
