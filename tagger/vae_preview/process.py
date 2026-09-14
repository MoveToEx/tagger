from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QTemporaryDir, Signal

from tagger.ai_tagging.models import ModelSpec


_PROTOCOL_PREFIX = b"TAGGER_VAE:"
_WORKER_MODULE = "tagger.vae_preview.worker"


class VaePreviewProcess(QObject):
    progress = Signal(int, str)
    decoded = Signal(int, object, object)
    failed = Signal(int, str)

    def __init__(
        self,
        model: ModelSpec,
        cache_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if model.filename is None:
            raise ValueError("A VAE model must identify a weights file.")
        self._configuration: dict[str, object] = {
            "type": "configure",
            "repo_id": model.repo_id,
            "filename": model.filename,
            "cache_dir": str(cache_dir) if cache_dir is not None else None,
        }
        self._stdout_buffer = b""
        self._stderr = ""
        self._next_request_id = 0
        self._pending_messages: list[dict[str, object]] = []
        self._configured = False
        self._stopping = False
        self._terminal_failure_emitted = False
        self._temporary_directory = QTemporaryDir("tagger-vae-preview-XXXXXX")
        if not self._temporary_directory.isValid():
            raise OSError("Could not create a temporary VAE preview directory.")

        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        self._process.started.connect(self._process_started)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.errorOccurred.connect(self._process_error)
        self._process.finished.connect(self._process_finished)

    def start(self) -> None:
        self._process.start(sys.executable, ["-u", "-m", _WORKER_MODULE])

    def decode(self, image_path: Path) -> int:
        request_id = self._next_request_id
        self._next_request_id += 1
        output_path = (
            Path(self._temporary_directory.path()) / f"decoded-{request_id}.png"
        )
        message: dict[str, object] = {
            "type": "decode",
            "request_id": request_id,
            "image_path": str(image_path),
            "output_path": str(output_path),
        }
        if self._configured:
            self._write_message(message)
        else:
            self._pending_messages.append(message)
        return request_id

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        if self._configured:
            self._write_message({"type": "shutdown"})
            self._process.closeWriteChannel()
        if not self._process.waitForFinished(300):
            self._process.terminate()
        if not self._process.waitForFinished(1_000):
            self._process.kill()
            self._process.waitForFinished(1_000)

    def _process_started(self) -> None:
        self._write_message(self._configuration)
        self._configured = True
        pending, self._pending_messages = self._pending_messages, []
        for message in pending:
            self._write_message(message)

    def _write_message(self, message: Mapping[str, object]) -> None:
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        self._process.write(payload)

    def _read_stdout(self) -> None:
        self._stdout_buffer += bytes(self._process.readAllStandardOutput().data())
        while b"\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split(b"\n", 1)
            self._handle_output_line(line.rstrip(b"\r"))

    def _read_stderr(self) -> None:
        chunk = bytes(self._process.readAllStandardError().data()).decode(
            "utf-8", errors="replace"
        )
        self._stderr = (self._stderr + chunk)[-16_384:]

    def _handle_output_line(self, line: bytes) -> None:
        prefix_index = line.find(_PROTOCOL_PREFIX)
        if prefix_index == -1:
            return
        try:
            payload = line[prefix_index + len(_PROTOCOL_PREFIX) :]
            message = json.loads(payload.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError
            message_type = message.get("type")
            request_id = message.get("request_id", -1)
            if not isinstance(request_id, int):
                raise ValueError
            if message_type == "progress":
                status = message.get("message")
                if not isinstance(status, str):
                    raise ValueError
                self.progress.emit(request_id, status)
            elif message_type == "result":
                image_path = message.get("image_path")
                output_path = message.get("output_path")
                if not isinstance(image_path, str) or not isinstance(
                    output_path, str
                ):
                    raise ValueError
                self.decoded.emit(
                    request_id, Path(image_path), Path(output_path)
                )
            elif message_type == "failed":
                error = message.get("message")
                if not isinstance(error, str) or not error:
                    raise ValueError
                if request_id == -1:
                    self._terminal_failure_emitted = True
                self.failed.emit(request_id, error)
            elif message_type != "ready":
                raise ValueError
        except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
            self._emit_terminal_failure(
                "The VAE preview process returned an invalid response."
            )

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._emit_terminal_failure(
                "Could not start the VAE preview process: "
                + self._process.errorString()
            )

    def _process_finished(
        self, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        self._read_stdout()
        if self._stdout_buffer:
            self._handle_output_line(self._stdout_buffer.rstrip(b"\r"))
            self._stdout_buffer = b""
        self._read_stderr()
        if self._stopping or self._terminal_failure_emitted:
            return
        detail = self._stderr.strip()
        message = "The VAE preview process ended unexpectedly."
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            message = "The VAE preview process stopped before the dialog closed."
        if detail:
            message = f"{message}\n\n{detail}"
        self._emit_terminal_failure(message)

    def _emit_terminal_failure(self, message: str) -> None:
        if self._terminal_failure_emitted:
            return
        self._terminal_failure_emitted = True
        self.failed.emit(-1, message)
