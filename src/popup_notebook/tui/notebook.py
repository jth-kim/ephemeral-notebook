from __future__ import annotations

from popup_notebook.sessions.models import SessionState


class NotebookViewModel:
    """Minimal view model placeholder for notebook state."""

    def __init__(self, session: SessionState) -> None:
        self.session = session
