from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from popup_notebook.project import build_project_context
from popup_notebook.sessions.models import Cell, SessionState
from popup_notebook.sessions.store import (
    delete_session_state,
    load_session_state,
    save_session_state,
    session_lock,
    session_state_path,
)

class SessionAttachedError(RuntimeError):
    """Raised when a session already has an active UI attachment."""


class SessionManager:
    """Manage one live session per project root using app-managed persistent state."""

    def get_or_create(self, cwd: Path) -> SessionState:
        context = build_project_context(cwd)
        with session_lock(context.project_root):
            session = load_session_state(context.project_root)
            if session is None:
                session = SessionState(
                    project_root=context.project_root,
                    interpreter=context.interpreter,
                    interpreter_source=context.interpreter_source,
                    cells=[self._blank_cell()],
                )
                save_session_state(session)
            return session

    def get(self, project_root: Path) -> SessionState | None:
        with session_lock(project_root):
            return load_session_state(project_root)

    def status(self, project_root: Path) -> dict[str, object]:
        with session_lock(project_root):
            session = load_session_state(project_root)
            return {
                "exists": session is not None,
                "attached": session.attached if session is not None else False,
                "kernel_generation": session.kernel_generation if session is not None else None,
                "cell_count": len(session.cells) if session is not None else 0,
                "state_path": str(session_state_path(project_root)),
            }

    def attach(self, cwd: Path) -> tuple[SessionState, str]:
        context = build_project_context(cwd)
        with session_lock(context.project_root):
            session = load_session_state(context.project_root)
            if session is None:
                session = SessionState(
                    project_root=context.project_root,
                    interpreter=context.interpreter,
                    interpreter_source=context.interpreter_source,
                    cells=[self._blank_cell()],
                )
            if session.attached:
                raise SessionAttachedError(
                    f"Session for {context.project_root} is already attached elsewhere."
                )
            token = str(uuid4())
            session.attached = True
            session.attachment_token = token
            save_session_state(session)
            return session, token

    def detach(self, project_root: Path, token: str | None = None) -> None:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return
            if token is not None and session.attachment_token not in {None, token}:
                return
            session.attached = False
            session.attachment_token = None
            save_session_state(session)

    def reset(self, project_root: Path) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            session.kernel_generation += 1
            save_session_state(session)
            return True

    def hard_reset(self, project_root: Path) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            session.kernel_generation += 1
            session.cells = [self._blank_cell()]
            save_session_state(session)
            return True

    def kill(self, project_root: Path) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            delete_session_state(project_root)
            return True

    @staticmethod
    def _blank_cell() -> Cell:
        return Cell(id=str(uuid4()), kind="python")
