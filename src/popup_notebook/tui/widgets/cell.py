from __future__ import annotations

import textwrap

from rich.text import Text
from rich.style import Style
from textual import events
from textual._text_area_theme import TextAreaTheme
from textual.containers import VerticalGroup
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Markdown, Static, TextArea

from popup_notebook.sessions.models import Cell

RUN_CELL_KEYS = ("ctrl+r",)
SELECTION_BG = "#4b6a8a"
SELECTION_FG = "#f8f8f2"


class NotebookTextArea(TextArea):
    """TextArea with notebook-oriented key events."""

    class ExitEdit(Message):
        def __init__(self, cell_id: str) -> None:
            self.cell_id = cell_id
            super().__init__()

    class RunRequested(Message):
        def __init__(self, cell_id: str, *, move_to_next: bool) -> None:
            self.cell_id = cell_id
            self.move_to_next = move_to_next
            super().__init__()

    class MoveToNeighbor(Message):
        def __init__(self, cell_id: str, *, direction: str) -> None:
            self.cell_id = cell_id
            self.direction = direction
            super().__init__()

    def __init__(self, cell_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cell_id = cell_id

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.ExitEdit(self.cell_id))
            return

        if event.key == "super+a":
            event.stop()
            event.prevent_default()
            self.action_select_all()
            return

        if event.key in {"ctrl+v", "super+v"}:
            load_clipboard = getattr(self.app, "load_system_clipboard", None)
            if callable(load_clipboard) and load_clipboard():
                event.stop()
                event.prevent_default()
                self.action_paste()
                return

        if event.key in RUN_CELL_KEYS:
            event.stop()
            event.prevent_default()
            self.post_message(self.RunRequested(self.cell_id, move_to_next=True))
            return

        if event.key == "up":
            current = self.cursor_location
            if self.get_cursor_up_location() == current:
                event.stop()
                event.prevent_default()
                self.post_message(self.MoveToNeighbor(self.cell_id, direction="up"))
                return

        if event.key == "down":
            current = self.cursor_location
            if self.get_cursor_down_location() == current:
                event.stop()
                event.prevent_default()
                self.post_message(self.MoveToNeighbor(self.cell_id, direction="down"))
                return

        await super()._on_key(event)


class CellWidget(VerticalGroup):
    """Notebook cell widget with inline editing and output display."""

    can_focus = True

    class Focused(Message):
        def __init__(self, cell_id: str, *, edit_mode: bool) -> None:
            self.cell_id = cell_id
            self.edit_mode = edit_mode
            super().__init__()

    class SelectNeighbor(Message):
        def __init__(self, cell_id: str, *, direction: str) -> None:
            self.cell_id = cell_id
            self.direction = direction
            super().__init__()

    class SourceChanged(Message):
        def __init__(self, cell_id: str, source: str) -> None:
            self.cell_id = cell_id
            self.source = source
            super().__init__()

    cell_kind = reactive("python")
    is_current = reactive(False)
    in_edit_mode = reactive(False)
    is_running = reactive(False)

    def __init__(
        self,
        cell: Cell,
        *,
        current: bool = False,
        edit_mode: bool = False,
        markdown_center: bool = False,
        output_max_lines: int = 12,
        code_theme: str = "monokai",
    ) -> None:
        super().__init__(id=f"cell-{cell.id}", classes="cell")
        self.cell = cell
        self._editor = NotebookTextArea(
            cell.id,
            text=cell.source,
            language=cell.kind if cell.kind in {"python", "markdown"} else None,
            show_line_numbers=False,
            soft_wrap=True,
            id=f"editor-{cell.id}",
            tab_behavior="indent",
        )
        self._markdown = Markdown(cell.source, classes="cell-markdown-render")
        self._output = Static(classes="cell-output")
        self._markdown_center = markdown_center
        self._output_max_lines = output_max_lines
        theme_name = self._register_editor_theme(code_theme)
        self._editor.theme = theme_name
        self.cell_kind = cell.kind
        self.is_current = current
        self.in_edit_mode = edit_mode

    def compose(self):
        yield self._editor
        yield self._markdown
        yield self._output

    def on_mount(self) -> None:
        self.call_after_refresh(self._update_editor_height)
        self._refresh()

    def on_focus(self) -> None:
        self.post_message(self.Focused(self.cell.id, edit_mode=False))

    async def _on_key(self, event: events.Key) -> None:
        if self.in_edit_mode:
            await super()._on_key(event)
            return

        if event.key == "up":
            event.stop()
            event.prevent_default()
            self.post_message(self.SelectNeighbor(self.cell.id, direction="up"))
            return

        if event.key == "down":
            event.stop()
            event.prevent_default()
            self.post_message(self.SelectNeighbor(self.cell.id, direction="down"))
            return

        await super()._on_key(event)

    def watch_cell_kind(self) -> None:
        self._refresh()

    def watch_is_current(self) -> None:
        self._refresh()

    def watch_in_edit_mode(self) -> None:
        self._refresh()

    def watch_is_running(self) -> None:
        self._refresh()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area is not self._editor:
            return
        if self.cell_kind == "markdown":
            self._markdown.update(self._editor.text)
        self.post_message(self.SourceChanged(self.cell.id, self._editor.text))
        self.call_after_refresh(self._update_editor_height)

    def on_text_area_focus(self, _event) -> None:
        self.post_message(self.Focused(self.cell.id, edit_mode=True))

    def on_resize(self) -> None:
        self.call_after_refresh(self._update_editor_height)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self._mouse_targets_editor(event.widget):
            return
        if bool(getattr(self.app, "edit_mode", False)):
            self._editor.focus()
            return
        self.focus()

    def focus_editor(self) -> None:
        self._editor.focus()

    def focus_cell(self) -> None:
        self.focus()

    def set_current(self, current: bool) -> None:
        self.is_current = current

    def set_edit_mode(self, edit_mode: bool) -> None:
        self.in_edit_mode = edit_mode

    def set_running(self, is_running: bool) -> None:
        self.is_running = is_running

    def sync_from_cell(self, cell: Cell) -> None:
        self.cell = cell
        self.cell_kind = cell.kind
        if self._editor.text != cell.source:
            self._editor.load_text(cell.source)
        self._editor.language = cell.kind if cell.kind in {"python", "markdown"} else None
        self._markdown.update(cell.source)
        self._output.update(self._render_output())
        self.call_after_refresh(self._update_editor_height)
        self._refresh()

    def _refresh(self) -> None:
        kind_label = "Python" if self.cell_kind == "python" else "Markdown"
        marker = "Editing" if self.in_edit_mode else ("Selected" if self.is_current else "")
        execution = ""
        if self.cell.execution_count is not None and self.cell_kind == "python":
            execution = f" [{self.cell.execution_count}]"
        title_parts = [part for part in (marker, f"{kind_label}{execution}") if part]
        self.border_title = f" {' · '.join(title_parts)} "
        show_markdown = self.cell_kind == "markdown" and not self.in_edit_mode
        self._editor.display = not show_markdown
        self._markdown.display = show_markdown
        self._editor.read_only = (not self.in_edit_mode) or self.is_running
        self._editor.show_cursor = self.in_edit_mode
        self.set_class(self.is_current, "current")
        self.set_class(self.in_edit_mode, "editing")
        self.set_class(self.is_running, "running")
        self.set_class(self.cell_kind == "python", "python")
        self.set_class(self.cell_kind == "markdown", "markdown")
        self._markdown.set_class(self._markdown_center, "centered")
        self._output.display = bool(self.cell.output.strip())
        if self._output.display:
            self._output.border_title = (
                " Output · Expanded " if self.cell.expanded else " Output "
            )
        else:
            self._output.border_title = ""
        self._output.update(self._render_output())

    def _render_output(self) -> Text | str:
        content = self.cell.output.rstrip()
        if not content:
            return ""
        lines = content.splitlines()
        truncated = not self.cell.expanded and len(lines) > self._output_max_lines
        visible_text = (
            "\n".join(lines[: self._output_max_lines]) if truncated else content
        )
        rendered = Text.from_ansi(visible_text)
        if truncated:
            rendered.append("\n\n")
            rendered.append("... output truncated", style="bold #d68c4f")
            rendered.append(" · press o to expand", style="#8a96a8")
        elif self.cell.expanded and len(lines) > self._output_max_lines:
            rendered.append("\n\n")
            rendered.append("press o to collapse", style="#8a96a8")
        return rendered

    def _mouse_targets_editor(self, widget) -> bool:
        current = widget
        while current is not None:
            if current is self._editor:
                return True
            current = getattr(current, "parent", None)
        return False

    def _update_editor_height(self) -> None:
        wrap_width = max(
            1,
            getattr(self._editor, "wrap_width", 0) or self._editor.content_region.width or 0,
        )
        if wrap_width <= 1:
            height = max(1, self._editor.text.count("\n") + 1)
        else:
            height = 0
            for line in self._editor.text.split("\n"):
                expanded = line.expandtabs(self._editor.indent_width)
                wrapped = textwrap.wrap(
                    expanded,
                    width=wrap_width,
                    drop_whitespace=False,
                    replace_whitespace=False,
                )
                height += len(wrapped) or 1
        self._editor.styles.height = height

    def _register_editor_theme(self, code_theme: str) -> str:
        base_name = code_theme if code_theme in self._editor.available_themes else "css"
        base_theme = TextAreaTheme.get_builtin_theme(base_name)
        if base_theme is None:
            return base_name
        derived_theme = TextAreaTheme(
            name=f"{base_name}-popup-notebook",
            base_style=base_theme.base_style,
            gutter_style=base_theme.gutter_style,
            cursor_style=base_theme.cursor_style,
            cursor_line_style=base_theme.cursor_line_style,
            cursor_line_gutter_style=base_theme.cursor_line_gutter_style,
            bracket_matching_style=base_theme.bracket_matching_style,
            selection_style=Style(color=SELECTION_FG, bgcolor=SELECTION_BG),
            syntax_styles=dict(base_theme.syntax_styles),
        )
        self._editor.register_theme(derived_theme)
        return derived_theme.name
