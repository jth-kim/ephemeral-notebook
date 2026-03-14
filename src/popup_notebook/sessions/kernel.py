from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty
from typing import Final

from popup_notebook.sessions.store import session_connection_path, session_log_path, session_store_dir


STARTUP_TIMEOUT: Final[float] = 10.0
SHUTDOWN_TIMEOUT: Final[float] = 5.0


class KernelLaunchError(RuntimeError):
    """Raised when the project interpreter cannot start an IPython kernel."""


@dataclass(frozen=True)
class KernelRuntime:
    pid: int
    connection_file: Path


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
    ) -> KernelRuntime:
        if existing_pid is not None and existing_connection_file is not None:
            if self.is_alive(existing_pid) and existing_connection_file.exists():
                return KernelRuntime(pid=existing_pid, connection_file=existing_connection_file)
        return self.start()

    def start(self) -> KernelRuntime:
        from jupyter_client import KernelManager
        from jupyter_client.kernelspec import KernelSpec

        self.session_dir.mkdir(parents=True, exist_ok=True)
        kernel_manager = KernelManager(kernel_name="python3", connection_file=str(self.connection_file))
        kernel_manager._kernel_spec = KernelSpec(  # type: ignore[attr-defined]
            argv=[
                str(self.interpreter),
                "-m",
                "ipykernel_launcher",
                "-f",
                "{connection_file}",
            ],
            display_name="popup-notebook",
            language="python",
            env={},
            resource_dir=str(self.session_dir),
        )
        try:
            kernel_manager.start_kernel(
                cwd=str(self.project_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            kernel_client = kernel_manager.client()
            kernel_client.load_connection_file()
            kernel_client.start_channels()
            kernel_client.wait_for_ready(timeout=STARTUP_TIMEOUT)
            pid = kernel_manager.provisioner.pid
            assert pid is not None
        except Exception as exc:
            if "kernel_client" in locals():
                kernel_client.stop_channels()
            kernel_manager.shutdown_kernel(now=True)
            raise KernelLaunchError(
                "Failed to start project kernel. Ensure the resolved interpreter has ipykernel "
                f"installed: {self.interpreter}"
            ) from exc
        finally:
            if "kernel_client" in locals():
                kernel_client.stop_channels()

        return KernelRuntime(pid=pid, connection_file=self.connection_file)

    def restart(
        self,
        *,
        existing_pid: int | None,
        existing_connection_file: Path | None,
    ) -> KernelRuntime:
        self.shutdown(existing_pid, existing_connection_file)
        return self.start()

    def shutdown(self, pid: int | None, connection_file: Path | None) -> None:
        if pid is not None and self.is_alive(pid):
            self._terminate_process(pid)
        if connection_file is not None and connection_file.exists():
            connection_file.unlink()

    def execute(self, connection_file: Path, code: str) -> str:
        from jupyter_client import BlockingKernelClient

        client = BlockingKernelClient(connection_file=str(connection_file))
        client.load_connection_file()
        client.start_channels()
        try:
            client.wait_for_ready(timeout=STARTUP_TIMEOUT)
            message_id = client.execute(code, store_history=True, stop_on_error=True)
            outputs: list[str] = []

            while True:
                message = client.get_iopub_msg(timeout=STARTUP_TIMEOUT)
                if message.get("parent_header", {}).get("msg_id") != message_id:
                    continue

                msg_type = message["msg_type"]
                content = message["content"]

                if msg_type == "stream":
                    text = str(content.get("text", "")).rstrip()
                    if text:
                        outputs.append(text)
                elif msg_type in {"execute_result", "display_data"}:
                    rendered = self._render_output_data(content.get("data", {}))
                    if rendered:
                        outputs.append(rendered)
                elif msg_type == "error":
                    traceback = content.get("traceback", [])
                    if traceback:
                        outputs.append("\n".join(str(line) for line in traceback))
                    else:
                        outputs.append(
                            f"{content.get('ename', 'Error')}: {content.get('evalue', '')}".rstrip()
                        )
                elif msg_type == "status" and content.get("execution_state") == "idle":
                    break

            try:
                reply = client.get_shell_msg(timeout=STARTUP_TIMEOUT)
            except Empty:
                reply = None

            if reply is not None:
                content = reply.get("content", {})
                if content.get("status") == "error" and not outputs:
                    outputs.append(
                        f"{content.get('ename', 'Error')}: {content.get('evalue', '')}".rstrip()
                    )

            return "\n\n".join(part for part in outputs if part).strip()
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
