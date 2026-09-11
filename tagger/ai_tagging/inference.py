from __future__ import annotations

import json
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, Signal


_PROTOCOL_PREFIX = b"TAGGER_AI:"
_WORKER_MODULE = "tagger.ai_tagging.inference_worker"


class _InferenceProcess(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        image_paths: list[Path],
        repo_id: str,
        general_threshold: float,
        character_threshold: float,
        proxy: str | None,
        cache_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._request = {
            "image_paths": [str(path) for path in image_paths],
            "repo_id": repo_id,
            "general_threshold": general_threshold,
            "character_threshold": character_threshold,
            "proxy": proxy,
            "cache_dir": str(cache_dir) if cache_dir is not None else None,
        }
        self._results: dict[str, list[tuple[str, float]]] = {}
        self._stdout_buffer = b""
        self._stderr = ""
        self._failure: str | None = None
        self._saw_completion = False
        self._terminal_signal_emitted = False

        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        self._process.started.connect(self._send_request)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.errorOccurred.connect(self._process_error)
        self._process.finished.connect(self._process_finished)

    def start(self) -> None:
        self._process.start(sys.executable, ["-u", "-m", _WORKER_MODULE])

    def _send_request(self) -> None:
        payload = json.dumps(self._request, ensure_ascii=False).encode("utf-8")
        self._process.write(payload)
        self._process.closeWriteChannel()

    def _read_stdout(self) -> None:
        self._stdout_buffer += bytes(
            self._process.readAllStandardOutput().data()
        )
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
            if message_type == "progress":
                value = message.get("value")
                total = message.get("total")
                text = message.get("message")
                if not isinstance(value, int) or not isinstance(total, int):
                    raise ValueError
                if not isinstance(text, str):
                    raise ValueError
                self.progress.emit(value, total, text)
            elif message_type == "result":
                path = message.get("path")
                raw_tags = message.get("tags")
                if not isinstance(path, str) or not isinstance(raw_tags, list):
                    raise ValueError
                tags: list[tuple[str, float]] = []
                for raw_tag in raw_tags:
                    if not isinstance(raw_tag, list) or len(raw_tag) != 2:
                        raise ValueError
                    name, probability = raw_tag
                    if not isinstance(name, str) or not isinstance(
                        probability, int | float
                    ):
                        raise ValueError
                    tags.append((name, float(probability)))
                self._results[path] = tags
            elif message_type == "completed":
                self._saw_completion = True
            elif message_type == "failed":
                error = message.get("message")
                if not isinstance(error, str) or not error:
                    raise ValueError
                self._failure = error
            else:
                raise ValueError
        except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
            self._failure = "The AI inference process returned an invalid response."

    def _process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._emit_failed(
                f"Could not start the AI inference process: {self._process.errorString()}"
            )

    def _process_finished(
        self, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        self._read_stdout()
        if self._stdout_buffer:
            self._handle_output_line(self._stdout_buffer.rstrip(b"\r"))
            self._stdout_buffer = b""
        self._read_stderr()

        if self._terminal_signal_emitted:
            return
        if self._failure is not None:
            self._emit_failed(self._failure)
            return
        if (
            exit_status != QProcess.ExitStatus.NormalExit
            or exit_code != 0
            or not self._saw_completion
        ):
            detail = self._stderr.strip()
            message = "The AI inference process ended unexpectedly."
            if detail:
                message = f"{message}\n\n{detail}"
            self._emit_failed(message)
            return

        self._terminal_signal_emitted = True
        self.completed.emit(self._results)

    def _emit_failed(self, message: str) -> None:
        if self._terminal_signal_emitted:
            return
        self._terminal_signal_emitted = True
        self.failed.emit(message)
