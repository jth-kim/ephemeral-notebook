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


@dataclass
class SessionState:
    project_root: Path
    interpreter: Path
    attached: bool = False
    cells: list[Cell] = field(default_factory=list)
