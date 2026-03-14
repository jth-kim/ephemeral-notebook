from __future__ import annotations

from pathlib import Path

from popup_notebook.project import build_project_context
from popup_notebook.sessions.manager import SessionAttachedError, SessionManager
from popup_notebook.tui.notebook import NotebookViewModel
from popup_notebook.tui.widgets.cell import CellWidget
from popup_notebook.tui.widgets.status_bar import StatusBarWidget


def run_tui(cwd: Path) -> None:
    """Run the Textual app if available."""
    try:
        from textual.app import App, ComposeResult
        from textual.containers import VerticalScroll
        from textual.widgets import Footer, Header
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
        CSS = """
        Screen {
            background: $surface;
        }

        #status {
            dock: top;
            margin: 0 1 1 1;
            padding: 0 1;
            border: round $primary;
            background: $panel;
            color: $text;
        }

        #notebook {
            margin: 0 1 1 1;
        }

        .cell {
            margin: 0 0 1 0;
            padding: 0 1;
            border: round $panel;
            background: $boost;
        }

        .cell.current {
            border: round $primary;
            background: $surface-lighten-1;
        }

        .cell-header {
            color: $text-muted;
            padding: 0 0 1 0;
        }

        .cell-output {
            margin-top: 1;
            padding: 0 1;
            border: round $secondary;
            background: $surface-darken-1;
            color: $text;
        }

        TextArea {
            height: auto;
            min-height: 3;
            border: none;
            background: transparent;
        }
        """

        BINDINGS = [
            ("ctrl+q", "quit", "Hide"),
            ("a", "insert_above", "Insert Above"),
            ("b", "insert_below", "Insert Below"),
            ("m", "cell_markdown", "Markdown"),
            ("y", "cell_python", "Python"),
            ("shift+enter", "run_and_move", "Run + Move"),
            ("ctrl+enter", "run_and_stay", "Run"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.model = NotebookViewModel(manager, context.project_root, session)
            self._status = StatusBarWidget(id="status")

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield self._status
            with VerticalScroll(id="notebook"):
                pass
            yield Footer()

        def on_mount(self) -> None:
            self._rebuild_notebook()

        def action_insert_above(self) -> None:
            new_cell = manager.insert_cell_before(context.project_root, self.model.current_cell_id)
            if new_cell is not None:
                self.model.current_cell_id = new_cell.id
                self.model.reload()
                self._rebuild_notebook()

        def action_insert_below(self) -> None:
            new_cell = manager.insert_cell_after(context.project_root, self.model.current_cell_id)
            if new_cell is not None:
                self.model.current_cell_id = new_cell.id
                self.model.reload()
                self._rebuild_notebook()

        def action_cell_markdown(self) -> None:
            if self.model.current_cell_id is None:
                return
            if manager.set_cell_kind(context.project_root, self.model.current_cell_id, "markdown"):
                self.model.reload()
                self._sync_widgets()

        def action_cell_python(self) -> None:
            if self.model.current_cell_id is None:
                return
            if manager.set_cell_kind(context.project_root, self.model.current_cell_id, "python"):
                self.model.reload()
                self._sync_widgets()

        def action_run_and_stay(self) -> None:
            self._execute_current_cell(move_to_next=False)

        def action_run_and_move(self) -> None:
            self._execute_current_cell(move_to_next=True)

        def on_cell_widget_focused(self, message: CellWidget.Focused) -> None:
            self.model.current_cell_id = message.cell_id
            self._sync_widgets()

        def on_cell_widget_source_changed(self, message: CellWidget.SourceChanged) -> None:
            manager.update_cell_source(context.project_root, message.cell_id, message.source)

        def _execute_current_cell(self, *, move_to_next: bool) -> None:
            cell_id = self.model.current_cell_id
            if cell_id is None:
                return

            result = manager.execute_cell(context.project_root, cell_id)
            if result is None:
                self.notify("Unable to execute current cell.", severity="error")
                return

            self.model.reload()
            self._sync_widgets()

            if move_to_next:
                next_id = self._next_cell_id(cell_id)
                if next_id is None:
                    new_cell = manager.insert_cell_after(context.project_root, cell_id)
                    self.model.reload()
                    if new_cell is not None:
                        self.model.current_cell_id = new_cell.id
                        self._rebuild_notebook()
                        return
                else:
                    self.model.current_cell_id = next_id
                    self._sync_widgets()
                    self._focus_current_cell()

        def _next_cell_id(self, current_cell_id: str) -> str | None:
            for index, cell in enumerate(self.model.session.cells):
                if cell.id == current_cell_id and index + 1 < len(self.model.session.cells):
                    return self.model.session.cells[index + 1].id
            return None

        def _rebuild_notebook(self) -> None:
            self.model.reload()
            container = self.query_one("#notebook", VerticalScroll)
            container.remove_children()
            for cell in self.model.session.cells:
                container.mount(
                    CellWidget(cell, current=(cell.id == self.model.current_cell_id))
                )
            self._update_status()
            self.call_after_refresh(self._focus_current_cell)

        def _sync_widgets(self) -> None:
            self.model.reload()
            widgets = {
                widget.cell.id: widget for widget in self.query(CellWidget)
            }
            current_ids = set()
            for cell in self.model.session.cells:
                current_ids.add(cell.id)
                widget = widgets.get(cell.id)
                if widget is None:
                    self._rebuild_notebook()
                    return
                widget.set_current(cell.id == self.model.current_cell_id)
                widget.sync_from_cell(cell)
            for cell_id, widget in widgets.items():
                if cell_id not in current_ids:
                    widget.remove()
            self._update_status()
            self.call_after_refresh(self._focus_current_cell)

        def _focus_current_cell(self) -> None:
            cell_id = self.model.current_cell_id
            if cell_id is None:
                return
            try:
                widget = self.query_one(f"#cell-{cell_id}", CellWidget)
            except Exception:
                return
            widget.focus_editor()

        def _update_status(self) -> None:
            current_index = self.model.current_index()
            position = current_index + 1 if current_index >= 0 else 0
            total = len(self.model.session.cells)
            self._status.update(
                "  ".join(
                    [
                        f"Project: {context.project_root.name}",
                        f"Python: {context.interpreter.name}",
                        f"Cells: {total}",
                        f"Current: {position}/{total if total else 0}",
                    ]
                )
            )

    try:
        PopupNotebookApp().run()
    finally:
        manager.detach(context.project_root, attachment_token)
