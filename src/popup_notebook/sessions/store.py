from __future__ import annotations

from pathlib import Path

from popup_notebook.config import state_dir


def session_store_dir(project_root: Path) -> Path:
    """Return a deterministic app-managed path for project session state."""
    slug = str(project_root).replace("/", "_").strip("_") or "root"
    return state_dir() / slug
