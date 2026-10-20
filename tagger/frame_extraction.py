from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


@dataclass(frozen=True)
class VideoInfo:
    frame_count: int
    fps: float
    width: int
    height: int


class VideoReader:
    """Own one OpenCV capture; use it from one thread and close it explicitly."""

    def __init__(self, path: Path) -> None:
        import cv2

        self._capture = cv2.VideoCapture(str(path))
        self._next_frame = 0
        try:
            if not self._capture.isOpened():
                raise ValueError("Could not open this video. Choose a supported video file.")
            fps = self._capture.get(cv2.CAP_PROP_FPS)
            count = self._capture.get(cv2.CAP_PROP_FRAME_COUNT)
            if not math.isfinite(fps) or fps <= 0 or not math.isfinite(count) or count < 1:
                raise ValueError("The video does not have a readable frame count or frame rate.")
            self.info = VideoInfo(
                int(count), fps,
                int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            )
        except Exception:
            self.close()
            raise

    def read_frame(self, index: int) -> NDArray[np.uint8]:
        import cv2

        if not 0 <= index < self.info.frame_count:
            raise ValueError(f"Frame {index + 1} is outside the video.")
        if index != self._next_frame:
            if not self._capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                raise ValueError(f"Could not seek to frame {index + 1}.")
        success, frame = self._capture.read()
        if not success or frame is None:
            self._next_frame = -1
            raise ValueError(f"Could not decode frame {index + 1}.")
        self._next_frame = index + 1
        return cast("NDArray[np.uint8]", frame)

    def close(self) -> None:
        self._capture.release()


@dataclass
class ExtractionResult:
    paths: list[Path] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    cancelled: bool = False


def _write_png(directory: Path, stem: str, data: bytes) -> Path:
    """Reserve each name exclusively, including when another import is running."""
    suffix = 0
    while True:
        path = directory / f"{stem}{'_' + str(suffix) if suffix else ''}.png"
        try:
            stream = path.open("xb")
        except FileExistsError:
            suffix += 1
            continue
        try:
            with stream:
                stream.write(data)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return path


def extract_frames(
    video_path: Path,
    frame_indices: Iterable[int],
    directory: Path,
    *,
    progress: Callable[[int, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ExtractionResult:
    """Write full-resolution PNGs in frame order, without overwriting existing files."""
    import cv2

    indices = sorted(set(frame_indices))
    if not directory.is_dir():
        raise ValueError("The destination folder no longer exists.")
    result = ExtractionResult()
    if not indices:
        return result
    reader = VideoReader(video_path)
    try:
        if any(index < 0 or index >= reader.info.frame_count for index in indices):
            raise ValueError("A selected frame is outside the video.")
        for completed, index in enumerate(indices):
            if cancelled is not None and cancelled():
                result.cancelled = True
                break
            if progress is not None:
                progress(completed, len(indices), index)
            try:
                frame = reader.read_frame(index)
                success, encoded = cv2.imencode(".png", frame)
                if not success:
                    raise ValueError("Could not encode the frame as PNG.")
                if cancelled is not None and cancelled():
                    result.cancelled = True
                    break
                result.paths.append(_write_png(
                    directory, f"{video_path.stem}_frame_{index + 1:06d}", encoded.tobytes(),
                ))
            except (OSError, ValueError, cv2.error) as exc:
                result.failures.append(f"Frame {index + 1}: {exc}")
            if progress is not None:
                progress(completed + 1, len(indices), index)
    finally:
        reader.close()
    return result
