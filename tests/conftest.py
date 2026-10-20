from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from tagger.paths import DATA_DIRECTORY_ENV_VAR


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Create test data in a workspace directory with sandbox-safe permissions."""
    root = Path(__file__).resolve().parent / ".pytest-tmp-local"
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolate_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIRECTORY_ENV_VAR, str(tmp_path / "data"))


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    """A lossless video whose colors identify each of its 15 frames."""
    import cv2
    import numpy as np

    path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"FFV1"), 5, (64, 48))
    assert writer.isOpened()
    try:
        for index in range(15):
            frame = np.empty((48, 64, 3), dtype=np.uint8)
            frame[:] = (index * 10, 255 - index * 10, index * 5)
            writer.write(frame)
    finally:
        writer.release()
    return path
