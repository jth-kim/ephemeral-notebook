from __future__ import annotations

from pathlib import Path

from popup_notebook.sessions.manager import SessionManager
from popup_notebook.sessions.models import SessionState


class NotebookViewModel:
    """Small helper around session state for the first interactive TUI slice."""

    def __init__(self, manager: SessionManager, project_root: Path, session: SessionState) -> None:
        self.manager = manager
        self.project_root = project_root
        self.session = session
        self.current_cell_id = session.cells[0].id if session.cells else None

    def reload(self) -> SessionState:
        session = self.manager.get(self.project_root)
        if session is None:
            raise RuntimeError(f"Session for {self.project_root} is no longer available.")
        self.session = session
        if self.current_cell_id is None and session.cells:
            self.current_cell_id = session.cells[0].id
        return session

    def current_index(self) -> int:
        if self.current_cell_id is None:
            return -1
        for index, cell in enumerate(self.session.cells):
            if cell.id == self.current_cell_id:
                return index
        return -1
