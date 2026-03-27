from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PopupGeometry:
    width: str = "92%"
    height: str = "92%"
    x: str = "C"
    y: str = "C"


def in_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def configure_tmux_keyboard() -> None:
    subprocess.run(
        ["tmux", "set-option", "-sq", "extended-keys", "always"],
        check=True,
    )
    subprocess.run(
        ["tmux", "set-option", "-sq", "extended-keys-format", "csi-u"],
        check=True,
    )
    client_termtype = subprocess.run(
        ["tmux", "display-message", "-p", "#{client_termtype}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not client_termtype:
        return
    term_feature = f"{client_termtype}:extkeys"
    existing_features = subprocess.run(
        ["tmux", "show-options", "-gqv", "terminal-features"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if term_feature in existing_features:
        return
    subprocess.run(
        ["tmux", "set-option", "-asq", "terminal-features", f",{term_feature}"],
        check=True,
    )


def tmux_popup_command(
    cwd: Path,
    geometry: PopupGeometry,
    *,
    key_debug: bool = False,
) -> list[str]:
    command_parts: list[str] = []
    python_path = os.environ.get("PYTHONPATH")
    if python_path:
        command_parts.extend(["env", f"PYTHONPATH={python_path}"])
    if key_debug:
        if not python_path:
            command_parts.append("env")
        command_parts.extend(["TEXTUAL_DEBUG=1", "EPHEMERAL_NOTEBOOK_KEY_DEBUG=1"])
    command_parts.extend([sys.executable, "-m", "ephemeral_notebook.cli", "ui", "--cwd", str(cwd)])
    if key_debug:
        command_parts.append("--key-debug")
    app_command = shlex.join(command_parts)
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
        f"exec {app_command}",
    ]


def launch_tmux_popup(cwd: Path, geometry: PopupGeometry, *, key_debug: bool = False) -> None:
    configure_tmux_keyboard()
    subprocess.run(tmux_popup_command(cwd, geometry, key_debug=key_debug), check=True)
