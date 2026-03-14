from __future__ import annotations

from pathlib import Path

from popup_notebook.project import build_project_context
from popup_notebook.sessions.manager import SessionAttachedError, SessionManager


def run_tui(cwd: Path) -> None:
    """Run the Textual app if available."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import VerticalScroll
        from textual.widgets import Footer, Header, Static
    except ImportError as exc:
        raise RuntimeError(
            "Textual is not installed. Install project dependencies before running the UI."
        ) from exc

    context = build_project_context(cwd)
    manager = SessionManager()
    try:
        session, attachment_token = manager.attach(cwd)
    except SessionAttachedError as exc:
        raise RuntimeError(str(exc)) from exc

    class PopupNotebookApp(App[None]):
        BINDINGS = [("q", "quit", "Hide")]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Static(
                f"Project: {context.project_root}\n"
                f"Interpreter: {context.interpreter} ({context.interpreter_source})",
                id="status",
            )
            with VerticalScroll():
                for index, cell in enumerate(session.cells, start=1):
                    yield Static(
                        f"[{index}] {cell.kind}\n{cell.source or '<empty>'}\n{cell.output}",
                        classes="cell",
                    )
            yield Footer()

    try:
        PopupNotebookApp().run()
    finally:
        manager.detach(context.project_root, attachment_token)
