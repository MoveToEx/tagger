from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from tagger.frame_extraction import VideoReader, extract_frames
import tagger.frame_extraction as extraction_module


def test_reader_seeks_to_exact_frames_in_both_directions(video_file: Path) -> None:
    reader = VideoReader(video_file)
    try:
        assert reader.info.frame_count == 15
        assert reader.info.fps == 5
        assert (reader.info.width, reader.info.height) == (64, 48)
        for index in [0, 1, 7, 3, 14, 0]:
            frame = reader.read_frame(index)
            assert frame.shape == (48, 64, 3)
            assert tuple(frame[0, 0]) == (index * 10, 255 - index * 10, index * 5)
    finally:
        reader.close()


def test_reader_rejects_unreadable_video(tmp_path: Path) -> None:
    path = tmp_path / "invalid.mp4"
    path.write_text("not a video")
    with pytest.raises(ValueError, match="Could not open"):
        VideoReader(path)


def test_extracts_sorted_unique_full_resolution_frames_with_unicode_paths(
    video_file: Path, tmp_path: Path,
) -> None:
    source = video_file.rename(tmp_path / "视频.avi")
    destination = tmp_path / "图像"
    destination.mkdir()
    progress: list[tuple[int, int, int]] = []
    result = extract_frames(
        source, [14, 0, 7, 7], destination,
        progress=lambda *values: progress.append(values),
    )
    assert not result.failures
    assert not result.cancelled
    assert [path.name for path in result.paths] == [
        "视频_frame_000001.png", "视频_frame_000008.png", "视频_frame_000015.png",
    ]
    for path, index in zip(result.paths, [0, 7, 14]):
        assert path.parent == destination
        frame = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        assert frame is not None
        assert frame.shape == (48, 64, 3)
        assert tuple(frame[0, 0]) == (index * 10, 255 - index * 10, index * 5)
    assert progress == [(0, 3, 0), (1, 3, 0), (1, 3, 7), (2, 3, 7), (2, 3, 14), (3, 3, 14)]


def test_extraction_preserves_existing_files(video_file: Path, tmp_path: Path) -> None:
    original = tmp_path / "sample_frame_000001.png"
    original.write_bytes(b"existing image")
    first = extract_frames(video_file, [0], tmp_path)
    second = extract_frames(video_file, [0], tmp_path)
    assert original.read_bytes() == b"existing image"
    assert [p.name for p in first.paths] == ["sample_frame_000001_1.png"]
    assert [p.name for p in second.paths] == ["sample_frame_000001_2.png"]


def test_cancellation_keeps_completed_frames(video_file: Path, tmp_path: Path) -> None:
    completed = 0

    def progress(value: int, total: int, frame: int) -> None:
        nonlocal completed
        completed = value

    result = extract_frames(
        video_file, [0, 4, 8], tmp_path,
        progress=progress, cancelled=lambda: completed >= 1,
    )
    assert result.cancelled
    assert len(result.paths) == 1
    assert result.paths[0].is_file()
    assert not result.failures


def test_frame_failure_reports_error_and_continues(
    video_file: Path, tmp_path: Path, monkeypatch,
) -> None:
    write_png = extraction_module._write_png

    def fail_one(directory: Path, stem: str, data: bytes) -> Path:
        if stem.endswith("000005"):
            raise OSError("Disk write failed")
        return write_png(directory, stem, data)

    monkeypatch.setattr(extraction_module, "_write_png", fail_one)
    result = extract_frames(video_file, [0, 4, 8], tmp_path)
    assert len(result.paths) == 2
    assert result.failures == ["Frame 5: Disk write failed"]
    assert not result.cancelled


@pytest.mark.parametrize("indices", [[-1, 0], [0, 15]])
def test_invalid_selection_writes_nothing(
    video_file: Path, tmp_path: Path, indices: list[int],
) -> None:
    with pytest.raises(ValueError, match="outside the video"):
        extract_frames(video_file, indices, tmp_path)
    assert not list(tmp_path.glob("*.png"))


def test_missing_destination_is_reported(video_file: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no longer exists"):
        extract_frames(video_file, [0], tmp_path / "removed")
