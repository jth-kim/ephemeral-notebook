from __future__ import annotations

import json
from contextlib import contextmanager
from hashlib import sha1
from pathlib import Path
from typing import Iterator

from popup_notebook.config import state_dir
from popup_notebook.sessions.models import SessionState


def session_store_dir(project_root: Path) -> Path:
    """Return a deterministic app-managed path for project session state."""
    resolved = project_root.resolve()
    slug_source = str(resolved)
    digest = sha1(slug_source.encode("utf-8")).hexdigest()[:12]
    slug = f"{resolved.name or 'root'}-{digest}"
    return state_dir() / "sessions" / slug


def session_state_path(project_root: Path) -> Path:
    return session_store_dir(project_root) / "state.json"


def session_connection_path(project_root: Path) -> Path:
    return session_store_dir(project_root) / "kernel-connection.json"


def session_log_path(project_root: Path) -> Path:
    return session_store_dir(project_root) / "kernel.log"


def ensure_state_dir() -> Path:
    root = state_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def session_lock(project_root: Path) -> Iterator[None]:
    """Lock a session directory while reading or writing state."""
    import fcntl

    session_dir = session_store_dir(project_root)
    session_dir.mkdir(parents=True, exist_ok=True)
    lock_path = session_dir / ".lock"
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_session_state(project_root: Path) -> SessionState | None:
    path = session_state_path(project_root)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SessionState.from_dict(payload)


def save_session_state(session: SessionState) -> Path:
    ensure_state_dir()
    session_dir = session_store_dir(session.project_root)
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_state_path(session.project_root)
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    return path


def delete_session_state(project_root: Path) -> None:
    session_dir = session_store_dir(project_root)
    if not session_dir.exists():
        return
    for child in session_dir.iterdir():
        child.unlink()
    session_dir.rmdir()
