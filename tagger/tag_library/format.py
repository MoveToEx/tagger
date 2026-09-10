from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import struct
import tempfile


@dataclass(frozen=True)
class TagLibraryFileInfo:
    tag_count: int
    file_size: int
    modified_at: datetime


def get_tag_library_file_info(path: Path) -> TagLibraryFileInfo:
    stat = path.stat()
    return TagLibraryFileInfo(
        tag_count=len(_read_binary_records(path)),
        file_size=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone(),
    )


_BINARY_MAGIC = b"TAGGER_TAG_LIBRARY\x01"
_BINARY_COUNT = struct.Struct("<I")
_BINARY_RECORD = struct.Struct("<II")


def _read_binary_records(path: Path) -> list[tuple[str, int]]:
    data = path.read_bytes()
    if not data.startswith(_BINARY_MAGIC):
        raise ValueError("The tag library is not a supported binary file.")
    offset = len(_BINARY_MAGIC)
    if len(data) < offset + _BINARY_COUNT.size:
        raise ValueError("The binary tag library has an invalid header.")
    (record_count,) = _BINARY_COUNT.unpack_from(data, offset)
    offset += _BINARY_COUNT.size
    records: list[tuple[str, int]] = []
    for _index in range(record_count):
        if len(data) < offset + _BINARY_RECORD.size:
            raise ValueError("The binary tag library has a truncated record.")
        name_length, count = _BINARY_RECORD.unpack_from(data, offset)
        offset += _BINARY_RECORD.size
        end = offset + name_length
        if end > len(data):
            raise ValueError("The binary tag library has a truncated tag name.")
        try:
            name = data[offset:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "The binary tag library contains an invalid tag name."
            ) from exc
        records.append((name, count))
        offset = end
    if offset != len(data):
        raise ValueError("The binary tag library has trailing data.")
    return records


def write_tag_library(path: Path, records: Iterable[tuple[str, int]]) -> None:
    """Write a tag library atomically in the native binary format."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record_list = list(records)
    payload = bytearray(_BINARY_MAGIC)
    payload.extend(_BINARY_COUNT.pack(len(record_list)))
    for name, count in record_list:
        name_bytes = name.encode("utf-8")
        payload.extend(_BINARY_RECORD.pack(len(name_bytes), count))
        payload.extend(name_bytes)
    output_fd, output_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(output_fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(output_name, path)
    except BaseException:
        try:
            os.unlink(output_name)
        except FileNotFoundError:
            pass
        raise
