from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

CellKind = Literal["python", "markdown"]


@dataclass
class Cell:
    id: str
    kind: CellKind
    source: str = ""
    output: str = ""
    expanded: bool = False
    execution_count: int | None = None

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "output": self.output,
            "expanded": self.expanded,
            "execution_count": self.execution_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | bool]) -> "Cell":
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            source=str(data.get("source", "")),
            output=str(data.get("output", "")),
            expanded=bool(data.get("expanded", False)),
            execution_count=(
                int(data["execution_count"]) if data.get("execution_count") is not None else None
            ),
        )


@dataclass
class SessionState:
    project_root: Path
    interpreter: Path
    interpreter_source: str
    kernel_generation: int = 1
    kernel_pid: int | None = None
    connection_file: Path | None = None
    connection_info: dict[str, object] | None = None
    bootstrapped_kernel_pid: int | None = None
    bootstrap_version: int | None = None
    attached: bool = False
    attachment_token: str | None = None
    cells: list[Cell] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "project_root": str(self.project_root),
            "interpreter": str(self.interpreter),
            "interpreter_source": self.interpreter_source,
            "kernel_generation": self.kernel_generation,
            "kernel_pid": self.kernel_pid,
            "connection_file": str(self.connection_file) if self.connection_file else None,
            "connection_info": self.connection_info,
            "bootstrapped_kernel_pid": self.bootstrapped_kernel_pid,
            "bootstrap_version": self.bootstrap_version,
            "attached": self.attached,
            "attachment_token": self.attachment_token,
            "cells": [cell.to_dict() for cell in self.cells],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SessionState":
        raw_cells = data.get("cells", [])
        cells = [Cell.from_dict(cell) for cell in raw_cells if isinstance(cell, dict)]
        return cls(
            project_root=Path(str(data["project_root"])),
            interpreter=Path(str(data["interpreter"])),
            interpreter_source=str(data.get("interpreter_source", "unknown")),
            kernel_generation=int(data.get("kernel_generation", 1)),
            kernel_pid=int(data["kernel_pid"]) if data.get("kernel_pid") is not None else None,
            connection_file=(
                Path(str(data["connection_file"]))
                if data.get("connection_file") is not None
                else None
            ),
            connection_info=(
                dict(data["connection_info"])
                if isinstance(data.get("connection_info"), dict)
                else None
            ),
            bootstrapped_kernel_pid=(
                int(data["bootstrapped_kernel_pid"])
                if data.get("bootstrapped_kernel_pid") is not None
                else None
            ),
            bootstrap_version=(
                int(data["bootstrap_version"])
                if data.get("bootstrap_version") is not None
                else None
            ),
            attached=bool(data.get("attached", False)),
            attachment_token=(
                str(data["attachment_token"]) if data.get("attachment_token") is not None else None
            ),
            cells=cells,
        )
