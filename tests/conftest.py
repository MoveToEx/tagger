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
