from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "popup-notebook"


def state_dir() -> Path:
    """Return the app-managed state directory outside the project tree."""
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        base = Path(xdg_state_home)
    else:
        base = Path.home() / ".local" / "state"
    return base / APP_NAME
