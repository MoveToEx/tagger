from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QByteArray

from tagger.paths import ensure_data_directory, get_settings_path


class JsonSettings:
    """Small settings store backed by a JSON object."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._values: dict[str, object] = {}
        try:
            with path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        if isinstance(data, dict):
            self._values = data

    def value(
        self,
        key: str,
        default: object = None,
        *,
        type: type | None = None,
    ) -> object:
        value = _decode_value(self._values.get(key, default))
        if type is None or value is None:
            return value
        if type is bool:
            if isinstance(value, str):
                return value.casefold() in {"1", "true", "yes", "on"}
            return bool(value)
        try:
            return type(value)
        except (TypeError, ValueError):
            return default

    def setValue(self, key: str, value: object) -> None:
        self._values[key] = _encode_value(value)

    def sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(
                file_descriptor, "w", encoding="utf-8", newline="\n"
            ) as stream:
                json.dump(self._values, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def fileName(self) -> str:
        return str(self.path)


def _encode_value(value: object) -> object:
    if isinstance(value, QByteArray):
        return {
            "__type__": "QByteArray",
            "value": base64.b64encode(value.data()).decode("ascii"),
        }
    if isinstance(value, dict):
        return {str(key): _encode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_encode_value(item) for item in value]
    return value


def _decode_value(value: object) -> object:
    if isinstance(value, dict):
        if value.get("__type__") == "QByteArray":
            encoded = value.get("value", "")
            if isinstance(encoded, str):
                return QByteArray.fromBase64(encoded.encode("ascii"))
        return {key: _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    return value


def create_app_settings() -> JsonSettings:
    ensure_data_directory()
    return JsonSettings(get_settings_path())
