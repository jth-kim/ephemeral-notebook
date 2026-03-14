from __future__ import annotations

from pathlib import Path

from popup_notebook.sessions.models import SessionState


class SessionRegistry:
    """In-process registry placeholder for one session per project root."""

    def __init__(self) -> None:
        self._sessions: dict[Path, SessionState] = {}

    def get(self, project_root: Path) -> SessionState | None:
        return self._sessions.get(project_root)

    def put(self, session: SessionState) -> None:
        self._sessions[session.project_root] = session

    def remove(self, project_root: Path) -> None:
        self._sessions.pop(project_root, None)

    def has(self, project_root: Path) -> bool:
        return project_root in self._sessions
