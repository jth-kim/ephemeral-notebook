from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty
from typing import Final

from popup_notebook.sessions.bootstrap import build_bootstrap_code
from popup_notebook.sessions.store import session_connection_path, session_log_path, session_store_dir


STARTUP_TIMEOUT: Final[float] = 10.0
EXECUTION_TIMEOUT: Final[float] = 60.0
SHUTDOWN_TIMEOUT: Final[float] = 5.0
ANSI_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:\x1b\[[0-?]*[ -/]*[@-~])|(?:\x1b\][^\x07\x1b]*(?:\x07|\x1b\\\\))"
)


class KernelLaunchError(RuntimeError):
    """Raised when the project interpreter cannot start an IPython kernel."""


class ExecutionTimeoutError(RuntimeError):
    """Raised when a cell execution takes too long to respond."""


class KernelBootstrapError(RuntimeError):
    """Raised when popup-notebook bootstrap code cannot initialize the kernel session."""


@dataclass(frozen=True)
class KernelRuntime:
    pid: int
    connection_file: Path
    connection_info: dict[str, object]


@dataclass(frozen=True)
class ExecutionResult:
    output: str
    execution_count: int | None
    success: bool


@dataclass(frozen=True)
class CompletionResult:
    matches: tuple[str, ...]
    cursor_start: int
    cursor_end: int


class LiveKernelClient:
    """Keep one async client connected for the lifetime of a popup session."""

    def __init__(self) -> None:
        self._client = None
        self._kernel_pid: int | None = None
        self._connection_file: Path | None = None
        self._lock = asyncio.Lock()

    async def ensure_connected(self, *, kernel_pid: int, connection_file: Path) -> None:
        async with self._lock:
            if (
                self._client is not None
                and self._kernel_pid == kernel_pid
                and self._connection_file == connection_file
            ):
                return

            self.close()

            from jupyter_client.asynchronous import AsyncKernelClient

            client = AsyncKernelClient(connection_file=str(connection_file))
            client.load_connection_file()
            client.start_channels()
            try:
                await client.wait_for_ready(timeout=STARTUP_TIMEOUT)
            except Exception:
                client.stop_channels()
                raise

            self._client = client
            self._kernel_pid = kernel_pid
            self._connection_file = connection_file

    def close(self) -> None:
        if self._client is not None:
            self._client.stop_channels()
        self._client = None
        self._kernel_pid = None
        self._connection_file = None

    async def execute(self, code: str) -> ExecutionResult:
        async with self._lock:
            try:
                return await self._execute_request(
                    code,
                    store_history=True,
                    silent=False,
                )
            except Exception:
                self.close()
                raise

    async def bootstrap(self, startup_statements: tuple[str, ...]) -> None:
        async with self._lock:
            try:
                result = await self._execute_request(
                    build_bootstrap_code(startup_statements),
                    store_history=False,
                    silent=True,
                )
            except Exception:
                self.close()
                raise
        if result.success:
            return
        message = result.output or "Failed to initialize popup-notebook kernel helpers."
        raise KernelBootstrapError(message)

    async def complete(self, code: str, cursor_pos: int) -> CompletionResult:
        async with self._lock:
            client = self._client
            if client is None:
                raise RuntimeError("Kernel client is not connected.")
            try:
                reply = await client.complete(
                    code=code,
                    cursor_pos=cursor_pos,
                    reply=True,
                    timeout=5,
                )
            except Exception:
                self.close()
                raise

        content = reply.get("content", {})
        matches = tuple(str(match) for match in content.get("matches", []) if isinstance(match, str))
        cursor_start = int(content.get("cursor_start", cursor_pos))
        cursor_end = int(content.get("cursor_end", cursor_pos))
        return CompletionResult(
            matches=matches,
            cursor_start=cursor_start,
            cursor_end=cursor_end,
        )

    async def _execute_request(
        self,
        code: str,
        *,
        store_history: bool,
        silent: bool,
    ) -> ExecutionResult:
        client = self._client
        if client is None:
            raise RuntimeError("Kernel client is not connected.")

        message_id = client.execute(
            code,
            store_history=store_history,
            silent=silent,
            stop_on_error=True,
        )
        outputs: list[str] = []
        success = True

        while True:
            try:
                message = await client.get_iopub_msg(timeout=EXECUTION_TIMEOUT)
            except Empty as exc:
                raise ExecutionTimeoutError(
                    "Execution timed out after 60s. The kernel may still be running; "
                    "wait, reopen the popup, or interrupt with ii."
                ) from exc
            if message.get("parent_header", {}).get("msg_id") != message_id:
                continue

            msg_type = message["msg_type"]
            content = message["content"]

            if msg_type == "stream":
                text = _clean_output_text(str(content.get("text", "")).rstrip())
                if text:
                    outputs.append(text)
            elif msg_type in {"execute_result", "display_data"}:
                rendered = _clean_output_text(
                    KernelController._render_output_data(content.get("data", {}))
                )
                if rendered:
                    outputs.append(rendered)
            elif msg_type == "error":
                success = False
                traceback = content.get("traceback", [])
                if traceback:
                    outputs.append(_clean_output_text("\n".join(str(line) for line in traceback)))
                else:
                    outputs.append(
                        _clean_output_text(
                            f"{content.get('ename', 'Error')}: {content.get('evalue', '')}".rstrip()
                        )
                    )
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

        try:
            reply = await client.get_shell_msg(timeout=EXECUTION_TIMEOUT)
        except Empty:
            reply = None

        execution_count = None
        if reply is not None:
            content = reply.get("content", {})
            execution_count_value = content.get("execution_count")
            if execution_count_value is not None:
                execution_count = int(execution_count_value)
            if content.get("status") == "error" and not outputs:
                success = False
                outputs.append(
                    _clean_output_text(
                        f"{content.get('ename', 'Error')}: {content.get('evalue', '')}".rstrip()
                    )
                )
            elif content.get("status") == "error":
                success = False

        return ExecutionResult(
            output="\n\n".join(part for part in outputs if part).strip(),
            execution_count=execution_count,
            success=success,
        )


class KernelController:
    """Manage a project-scoped kernel process that can outlive the TUI process."""

    def __init__(self, project_root: Path, interpreter: Path) -> None:
        self.project_root = project_root
        self.interpreter = interpreter
        self.session_dir = session_store_dir(project_root)
        self.connection_file = session_connection_path(project_root)
        self.log_file = session_log_path(project_root)

    def ensure_running(
        self,
        *,
        existing_pid: int | None,
        existing_connection_file: Path | None,
        existing_connection_info: dict[str, object] | None = None,
    ) -> KernelRuntime:
        if existing_pid is not None and existing_connection_file is not None:
            if self.is_alive(existing_pid):
                if existing_connection_file.exists():
                    connection_info = (
                        existing_connection_info
                        if existing_connection_info is not None
                        else self._load_connection_info(existing_connection_file)
                    )
                    return KernelRuntime(
                        pid=existing_pid,
                        connection_file=existing_connection_file,
                        connection_info=connection_info,
                    )
                if existing_connection_info is not None:
                    self._write_connection_info(existing_connection_file, existing_connection_info)
                    return KernelRuntime(
                        pid=existing_pid,
                        connection_file=existing_connection_file,
                        connection_info=existing_connection_info,
                    )
        if existing_pid is not None or existing_connection_file is not None:
            self.shutdown(existing_pid, existing_connection_file)
        return self.start()

    def start(self) -> KernelRuntime:
        from jupyter_client import BlockingKernelClient

        self.session_dir.mkdir(parents=True, exist_ok=True)
        process = None
        try:
            process = subprocess.Popen(
                [
                    str(self.interpreter),
                    "-m",
                    "ipykernel_launcher",
                    "-f",
                    str(self.connection_file),
                ],
                cwd=str(self.project_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = time.time() + STARTUP_TIMEOUT
            while time.time() < deadline:
                if process.poll() is not None:
                    raise KernelLaunchError(
                        "Failed to start project kernel. Ensure the resolved interpreter has "
                        f"ipykernel installed: {self.interpreter}"
                    )
                if self.connection_file.exists():
                    break
                time.sleep(0.05)
            if not self.connection_file.exists():
                raise KernelLaunchError(
                    "Timed out waiting for the project kernel connection file."
                )

            kernel_client = BlockingKernelClient(connection_file=str(self.connection_file))
            kernel_client.load_connection_file()
            kernel_client.start_channels()
            kernel_client.wait_for_ready(timeout=STARTUP_TIMEOUT)
            connection_info = self._normalize_connection_info(kernel_client.get_connection_info())
            self._write_connection_info(self.connection_file, connection_info)
            pid = process.pid
            process._child_created = False  # type: ignore[attr-defined]
        except Exception as exc:
            if "kernel_client" in locals():
                kernel_client.stop_channels()
            if process is not None and process.poll() is None:
                self._terminate_process(process.pid)
            raise KernelLaunchError(
                "Failed to start project kernel. Ensure the resolved interpreter has ipykernel "
                f"installed: {self.interpreter}"
            ) from exc
        finally:
            if "kernel_client" in locals():
                kernel_client.stop_channels()

        return KernelRuntime(
            pid=pid,
            connection_file=self.connection_file,
            connection_info=connection_info,
        )

    def restart(
        self,
        *,
        existing_pid: int | None,
        existing_connection_file: Path | None,
        existing_connection_info: dict[str, object] | None = None,
    ) -> KernelRuntime:
        self.shutdown(existing_pid, existing_connection_file)
        return self.start()

    def shutdown(self, pid: int | None, connection_file: Path | None) -> None:
        if pid is not None and self.is_alive(pid):
            self._terminate_process(pid)
        if connection_file is not None and connection_file.exists():
            connection_file.unlink()

    def interrupt(self, pid: int | None) -> bool:
        if pid is None or not self.is_alive(pid):
            return False
        try:
            os.killpg(pid, signal.SIGINT)
        except PermissionError:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            return False
        return True

    def execute(self, connection_file: Path, code: str) -> ExecutionResult:
        return self._execute_request(
            connection_file,
            code,
            store_history=True,
            silent=False,
        )

    def bootstrap(self, connection_file: Path, startup_statements: tuple[str, ...]) -> None:
        result = self._execute_request(
            connection_file,
            build_bootstrap_code(startup_statements),
            store_history=False,
            silent=True,
        )
        if result.success:
            return
        message = result.output or "Failed to initialize popup-notebook kernel helpers."
        raise KernelBootstrapError(message)

    def _execute_request(
        self,
        connection_file: Path,
        code: str,
        *,
        store_history: bool,
        silent: bool,
    ) -> ExecutionResult:
        from jupyter_client import BlockingKernelClient

        client = BlockingKernelClient(connection_file=str(connection_file))
        client.load_connection_file()
        client.start_channels()
        try:
            client.wait_for_ready(timeout=STARTUP_TIMEOUT)
            message_id = client.execute(
                code,
                store_history=store_history,
                silent=silent,
                stop_on_error=True,
            )
            outputs: list[str] = []
            success = True

            while True:
                try:
                    message = client.get_iopub_msg(timeout=EXECUTION_TIMEOUT)
                except Empty as exc:
                    raise ExecutionTimeoutError(
                        "Execution timed out after 60s. The kernel may still be running; "
                        "wait, reopen the popup, or interrupt with ii."
                    ) from exc
                if message.get("parent_header", {}).get("msg_id") != message_id:
                    continue

                msg_type = message["msg_type"]
                content = message["content"]

                if msg_type == "stream":
                    text = _clean_output_text(str(content.get("text", "")).rstrip())
                    if text:
                        outputs.append(text)
                elif msg_type in {"execute_result", "display_data"}:
                    rendered = _clean_output_text(self._render_output_data(content.get("data", {})))
                    if rendered:
                        outputs.append(rendered)
                elif msg_type == "error":
                    success = False
                    traceback = content.get("traceback", [])
                    if traceback:
                        outputs.append(_clean_output_text("\n".join(str(line) for line in traceback)))
                    else:
                        outputs.append(
                            _clean_output_text(
                                f"{content.get('ename', 'Error')}: {content.get('evalue', '')}".rstrip()
                            )
                        )
                elif msg_type == "status" and content.get("execution_state") == "idle":
                    break

            try:
                reply = client.get_shell_msg(timeout=EXECUTION_TIMEOUT)
            except Empty:
                reply = None

            execution_count = None
            if reply is not None:
                content = reply.get("content", {})
                execution_count_value = content.get("execution_count")
                if execution_count_value is not None:
                    execution_count = int(execution_count_value)
                if content.get("status") == "error" and not outputs:
                    success = False
                    outputs.append(
                        _clean_output_text(
                            f"{content.get('ename', 'Error')}: {content.get('evalue', '')}".rstrip()
                        )
                    )
                elif content.get("status") == "error":
                    success = False

            return ExecutionResult(
                output="\n\n".join(part for part in outputs if part).strip(),
                execution_count=execution_count,
                success=success,
            )
        finally:
            client.stop_channels()

    @staticmethod
    def is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _terminate_process(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except PermissionError:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        except ProcessLookupError:
            return

        deadline = time.time() + SHUTDOWN_TIMEOUT
        while time.time() < deadline:
            if not self.is_alive(pid):
                return
            time.sleep(0.1)

        try:
            os.killpg(pid, signal.SIGKILL)
        except PermissionError:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        except ProcessLookupError:
            return

    @staticmethod
    def _render_output_data(data: object) -> str:
        if not isinstance(data, dict):
            return ""
        if "text/plain" in data:
            return str(data["text/plain"]).rstrip()
        if "text/markdown" in data:
            return str(data["text/markdown"]).rstrip()
        if "text/html" in data:
            return str(data["text/html"]).rstrip()
        return ""

    @staticmethod
    def _normalize_connection_info(connection_info: dict[str, object]) -> dict[str, object]:
        normalized: dict[str, object] = {}
        for key, value in connection_info.items():
            if isinstance(value, bytes):
                normalized[key] = value.decode("utf-8")
            else:
                normalized[key] = value
        return normalized

    @staticmethod
    def _write_connection_info(connection_file: Path, connection_info: dict[str, object]) -> None:
        connection_file.parent.mkdir(parents=True, exist_ok=True)
        connection_file.write_text(json.dumps(connection_info, indent=2), encoding="utf-8")

    @staticmethod
    def _load_connection_info(connection_file: Path) -> dict[str, object]:
        return json.loads(connection_file.read_text(encoding="utf-8"))


def _clean_output_text(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text).replace("\r", "")
