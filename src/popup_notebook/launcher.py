from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PopupGeometry:
    width: str = "80%"
    height: str = "80%"
    x: str = "C"
    y: str = "C"


def in_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def tmux_popup_command(cwd: Path, geometry: PopupGeometry) -> list[str]:
    command = shlex.join(["popup-notebook", "ui", "--cwd", str(cwd)])
    return [
        "tmux",
        "popup",
        "-d",
        str(cwd),
        "-w",
        geometry.width,
        "-h",
        geometry.height,
        "-x",
        geometry.x,
        "-y",
        geometry.y,
        "-E",
        command,
    ]


def launch_tmux_popup(cwd: Path, geometry: PopupGeometry) -> None:
    subprocess.run(tmux_popup_command(cwd, geometry), check=True)
