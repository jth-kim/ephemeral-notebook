from __future__ import annotations

from pathlib import Path
from typing import Any


class KernelController:
    """Thin wrapper placeholder around jupyter_client kernel lifecycle."""

    def __init__(self, interpreter: Path) -> None:
        self.interpreter = interpreter
        self.kernel_manager: Any | None = None

    def start(self) -> None:
        # Delayed import keeps the rest of the scaffold usable before deps are installed.
        from jupyter_client import KernelManager

        self.kernel_manager = KernelManager(kernel_name="python3")
        self.kernel_manager.start_kernel()

    def restart(self) -> None:
        if self.kernel_manager is not None:
            self.kernel_manager.restart_kernel(now=True)

    def stop(self) -> None:
        if self.kernel_manager is not None:
            self.kernel_manager.shutdown_kernel(now=True)
            self.kernel_manager = None
