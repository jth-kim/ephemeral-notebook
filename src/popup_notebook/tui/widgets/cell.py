from __future__ import annotations

from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, TextArea

from popup_notebook.sessions.models import Cell


class CellWidget(Vertical):
    """Notebook cell widget with inline editing and output display."""

    class Focused(Message):
        def __init__(self, cell_id: str) -> None:
            self.cell_id = cell_id
            super().__init__()

    class SourceChanged(Message):
        def __init__(self, cell_id: str, source: str) -> None:
            self.cell_id = cell_id
            self.source = source
            super().__init__()

    cell_kind = reactive("python")
    is_current = reactive(False)

    def __init__(self, cell: Cell, *, current: bool = False) -> None:
        super().__init__(id=f"cell-{cell.id}", classes="cell")
        self.cell = cell
        self._header = Static(classes="cell-header")
        self._editor = TextArea(
            text=cell.source,
            language="python" if cell.kind == "python" else None,
            show_line_numbers=False,
            soft_wrap=True,
            id=f"editor-{cell.id}",
        )
        self._output = Static(self._render_output(cell.output), classes="cell-output")
        self.cell_kind = cell.kind
        self.is_current = current

    def compose(self):
        yield self._header
        yield self._editor
        yield self._output

    def on_mount(self) -> None:
        self._refresh()

    def watch_cell_kind(self) -> None:
        self._refresh()

    def watch_is_current(self) -> None:
        self._refresh()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area is self._editor:
            self.post_message(self.SourceChanged(self.cell.id, self._editor.text))

    def on_text_area_focus(self, _event) -> None:
        self.post_message(self.Focused(self.cell.id))

    def focus_editor(self) -> None:
        self._editor.focus()

    def set_current(self, current: bool) -> None:
        self.is_current = current

    def sync_from_cell(self, cell: Cell) -> None:
        self.cell = cell
        self.cell_kind = cell.kind
        if self._editor.text != cell.source:
            self._editor.load_text(cell.source)
        self._editor.language = "python" if cell.kind == "python" else None
        self._output.update(self._render_output(cell.output))
        self._refresh()

    def _refresh(self) -> None:
        if not hasattr(self, "_header"):
            return
        kind_label = "Python" if self.cell_kind == "python" else "Markdown"
        marker = "Active" if self.is_current else "Cell"
        self.border_title = f" {marker} · {kind_label} "
        self._header.update(f"{kind_label} cell")
        self.set_class(self.is_current, "current")
        has_output = bool(self.cell.output.strip())
        self._output.display = has_output

    @staticmethod
    def _render_output(output: str) -> str:
        return output.rstrip() if output.strip() else ""
