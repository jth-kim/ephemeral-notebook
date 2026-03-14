from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "popup-notebook"


def state_dir() -> Path:
    """Return the app-managed state directory outside the project tree."""
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        path = Path(xdg_state_home) / APP_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    primary = Path.home() / ".local" / "state" / APP_NAME
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except OSError:
        fallback = Path("/tmp") / APP_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
