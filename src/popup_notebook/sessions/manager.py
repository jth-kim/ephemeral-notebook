from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from popup_notebook.project import build_project_context
from popup_notebook.sessions.models import Cell, SessionState
from popup_notebook.sessions.registry import SessionRegistry


_REGISTRY = SessionRegistry()


class SessionManager:
    """Manage one live session per project root."""

    def get_or_create(self, cwd: Path) -> SessionState:
        context = build_project_context(cwd)
        session = _REGISTRY.get(context.project_root)
        if session is not None:
            return session

        session = SessionState(
            project_root=context.project_root,
            interpreter=context.interpreter,
            cells=[Cell(id=str(uuid4()), kind="python")],
        )
        _REGISTRY.put(session)
        return session

    def reset(self, project_root: Path) -> None:
        session = _REGISTRY.get(project_root)
        if session is None:
            return
        for cell in session.cells:
            cell.output = ""
            cell.expanded = False

    def hard_reset(self, project_root: Path) -> None:
        session = _REGISTRY.get(project_root)
        if session is None:
            return
        session.cells = [Cell(id=str(uuid4()), kind="python")]

    def kill(self, project_root: Path) -> None:
        _REGISTRY.remove(project_root)
