from __future__ import annotations

import builtins
import keyword
import re
import textwrap

from rich.style import Style
from rich.text import Text
from textual import events
from textual._text_area_theme import TextAreaTheme
from textual.containers import VerticalGroup
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Markdown, Static, TextArea
from textual.widgets._text_area import Selection

from ephemeral_notebook.sessions.models import Cell

RUN_CELL_KEYS = ("ctrl+r",)
SELECTION_BG = "#4b6a8a"
SELECTION_FG = "#f8f8f2"
_REPR_LIKE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\(")


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

    _PYTHON_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
    _PYTHON_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    _PAIR_OPENERS = {"(": ")", "[": "]", "{": "}", "\"": "\"", "'": "'"}
    _PAIR_CLOSERS = {")", "]", "}", "\"", "'"}
    _PAIR_KEY_ALIASES = {
        "[": "[",
        "]": "]",
        "{": "{",
        "}": "}",
        "left_square_bracket": "[",
        "right_square_bracket": "]",
        "left_curly_bracket": "{",
        "right_curly_bracket": "}",
        "left_brace": "{",
        "right_brace": "}",
    }

    def __init__(self, cell_id: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cell_id = cell_id

    async def _on_key(self, event: events.Key) -> None:
        consume_nav_handoff = getattr(self.app, "consume_nav_handoff", None)
        if callable(consume_nav_handoff):
            consumed = await consume_nav_handoff(self.cell_id, event.key)
            if consumed:
                event.stop()
                event.prevent_default()
                return

        if event.key == "escape":
            event.stop()
            event.prevent_default()
            begin_nav_handoff = getattr(self.app, "begin_nav_handoff", None)
            if callable(begin_nav_handoff):
                begin_nav_handoff(self.cell_id)
            if self.parent is not None:
                self.parent.focus()
            self.post_message(self.ExitEdit(self.cell_id))
            return

        if event.key in {"ctrl+v", "super+v"}:
            load_clipboard = getattr(self.app, "load_system_clipboard", None)
            if callable(load_clipboard) and load_clipboard():
                event.stop()
                event.prevent_default()
                self.action_paste()
                return

        if event.key == "enter":
            if self._insert_pythonic_newline():
                event.stop()
                event.prevent_default()
                return

        pair_character = self._pair_character_from_event(event)
        if self.language == "python" and pair_character:
            if self._handle_python_pairing(pair_character):
                event.stop()
                event.prevent_default()
                return

        if event.key == "tab" and self.language == "python":
            if await self._autocomplete_python_token():
                event.stop()
                event.prevent_default()
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

    def _handle_python_pairing(self, character: str) -> bool:
        start, end = self.selection
        row, column = self.cursor_location
        line = self.document.get_line(row)
        next_character = line[column] if column < len(line) else ""

        if character in self._PAIR_OPENERS:
            closing = self._PAIR_OPENERS[character]
            if start != end:
                selected_text = self.selected_text
                self.replace(
                    f"{character}{selected_text}{closing}",
                    start,
                    end,
                    maintain_selection_offset=False,
                )
                self.selection = Selection((start[0], start[1] + 1), (end[0], end[1] + 1))
                return True
            if next_character and not next_character.isspace():
                return False
            self.insert(f"{character}{closing}", maintain_selection_offset=False)
            self.move_cursor((row, column + 1))
            return True

        if character in self._PAIR_CLOSERS and start == end and next_character == character:
            self.move_cursor((row, column + 1))
            return True

        return False

    @classmethod
    def _pair_character_from_event(cls, event: events.Key) -> str | None:
        if event.character in cls._PAIR_OPENERS or event.character in cls._PAIR_CLOSERS:
            return event.character
        for alias in getattr(event, "aliases", []):
            mapped = cls._PAIR_KEY_ALIASES.get(alias)
            if mapped is not None:
                return mapped
        return cls._PAIR_KEY_ALIASES.get(event.key)

    def _insert_pythonic_newline(self) -> bool:
        start, end = self.selection
        if start != end:
            return False

        row, column = self.cursor_location
        line = self.document.get_line(row)
        before_cursor = line[:column]
        if self.language == "python":
            base_indent = self._leading_whitespace(before_cursor)
            stripped = before_cursor.rstrip()
            extra_indent = ""
            if stripped.endswith((":",
                                  "(",
                                  "[",
                                  "{",
                                  "\\")):
                extra_indent = self._indent_unit()
            self.insert(f"\n{base_indent}{extra_indent}", maintain_selection_offset=False)
            return True

        self.insert(f"\n{self._leading_whitespace(before_cursor)}", maintain_selection_offset=False)
        return True

    async def _autocomplete_python_token(self) -> bool:
        start, end = self.selection
        if start != end:
            return False

        row, column = self.cursor_location
        line = self.document.get_line(row)
        before_cursor = line[:column]
        if not before_cursor.strip():
            return False
        if before_cursor.endswith((" ", "\t")):
            return False

        completion_result = await self._kernel_completion()
        if completion_result is not None:
            inserted = self._apply_kernel_completion(
                completion_result.matches,
                completion_result.cursor_start,
                completion_result.cursor_end,
            )
            if inserted:
                return True

        match = self._PYTHON_IDENTIFIER.search(before_cursor)
        if match is None:
            return False
        if match.start() > 0 and before_cursor[match.start() - 1] == ".":
            return False

        prefix = match.group(0)
        candidates = sorted(
            {
                candidate
                for candidate in self._python_completion_candidates()
                if candidate.startswith(prefix) and candidate != prefix
            }
        )
        if not candidates:
            return False

        if len(candidates) == 1:
            completion = candidates[0]
        else:
            completion = self._common_prefix(candidates)
            if completion == prefix:
                return False

        self.insert(completion[len(prefix) :], maintain_selection_offset=False)
        return True

    async def _kernel_completion(self):
        try:
            app = self.app
        except Exception:
            return None
        request_completion = getattr(app, "request_completion", None)
        if not callable(request_completion):
            return None
        return await request_completion(
            code=self.text,
            cursor_pos=self._cursor_offset(),
        )

    def _apply_kernel_completion(
        self,
        matches: tuple[str, ...],
        cursor_start: int,
        cursor_end: int,
    ) -> bool:
        if not matches:
            return False

        prefix = self.text[cursor_start:cursor_end]
        if len(matches) == 1:
            replacement = matches[0]
        else:
            replacement = self._common_prefix(list(matches))
            if replacement == prefix:
                preview = ", ".join(matches[:6])
                if len(matches) > 6:
                    preview += ", ..."
                self.app.notify(f"Completions: {preview}")
                return False

        if replacement == prefix:
            return False
        start = self._offset_to_location(cursor_start)
        end = self._offset_to_location(cursor_end)
        self.replace(replacement, start, end, maintain_selection_offset=False)
        return True

    def _python_completion_candidates(self) -> set[str]:
        document_words = set(self._PYTHON_WORD.findall(self.text))
        builtin_names = {name for name in dir(builtins) if not name.startswith("_")}
        keyword_names = set(keyword.kwlist)
        common_names = {
            "np",
            "pd",
            "plt",
            "math",
            "Path",
            "Series",
            "DataFrame",
            "self",
            "cls",
        }
        return document_words | builtin_names | keyword_names | common_names

    @staticmethod
    def _common_prefix(candidates: list[str]) -> str:
        prefix = candidates[0]
        for candidate in candidates[1:]:
            limit = min(len(prefix), len(candidate))
            index = 0
            while index < limit and prefix[index] == candidate[index]:
                index += 1
            prefix = prefix[:index]
            if not prefix:
                break
        return prefix

    def _indent_unit(self) -> str:
        if self.indent_type == "tabs":
            return "\t"
        return " " * self.indent_width

    def _cursor_offset(self) -> int:
        row, column = self.cursor_location
        offset = 0
        for line_index in range(row):
            offset += len(self.document.get_line(line_index)) + 1
        return offset + column

    def _offset_to_location(self, offset: int) -> tuple[int, int]:
        remaining = max(0, offset)
        line_count = len(self.document.lines)
        for row in range(line_count):
            line = self.document.get_line(row)
            if remaining <= len(line):
                return (row, remaining)
            remaining -= len(line)
            if row < line_count - 1:
                if remaining == 0:
                    return (row + 1, 0)
                remaining -= 1
        if line_count == 0:
            return (0, 0)
        last_line = self.document.get_line(line_count - 1)
        return (line_count - 1, len(last_line))

    @staticmethod
    def _leading_whitespace(text: str) -> str:
        return text[: len(text) - len(text.lstrip(" \t"))]


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

    class CursorMoved(Message):
        def __init__(self, cell_id: str, location: tuple[int, int]) -> None:
            self.cell_id = cell_id
            self.location = location
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
        show_line_numbers: bool = False,
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
            show_line_numbers=show_line_numbers,
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
        if self._editor.has_focus:
            return
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

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        if event.text_area is not self._editor:
            return
        self.post_message(self.CursorMoved(self.cell.id, event.selection.end))

    def on_text_area_focus(self, _event) -> None:
        self.post_message(self.Focused(self.cell.id, edit_mode=True))

    def on_resize(self) -> None:
        self.call_after_refresh(self._update_editor_height)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if self._mouse_targets_editor(event.widget):
            self._editor.focus()
            return
        if bool(getattr(self.app, "edit_mode", False)):
            self._editor.focus()
            return
        self.focus()

    def focus_editor(self, *, cursor_location: tuple[int, int] | None = None) -> None:
        if cursor_location is not None:
            self._editor.selection = Selection.cursor(cursor_location)
        self._editor.focus()

    def focus_cell(self) -> None:
        self.focus()

    def set_current(self, current: bool) -> None:
        self.is_current = current

    def set_edit_mode(self, edit_mode: bool) -> None:
        self.in_edit_mode = edit_mode

    def set_running(self, is_running: bool) -> None:
        self.is_running = is_running

    def set_show_line_numbers(self, show_line_numbers: bool) -> None:
        self._editor.show_line_numbers = show_line_numbers

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
        content = _pretty_repr_text(content)
        lines = content.splitlines()
        truncated = not self.cell.expanded and len(lines) > self._output_max_lines
        visible_text = (
            "\n".join(lines[: self._output_max_lines]) if truncated else content
        )
        rendered = Text(visible_text)
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
            name=f"{base_name}-ephemeral-notebook",
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


def _pretty_repr_text(text: str) -> str:
    stripped = text.strip()
    if not stripped or stripped.startswith("Traceback"):
        return text
    if not _REPR_LIKE_RE.match(stripped) or "=" not in stripped or not stripped.endswith(")"):
        return text

    head, sep, inner = stripped.partition("(")
    if not sep:
        return text
    inner = inner[:-1]
    parts = _split_top_level_fields(inner)
    if len(parts) < 2:
        return text

    formatted_parts = []
    for part in parts:
        field = part.strip()
        if not field:
            continue
        name, eq, value = field.partition("=")
        if not eq:
            return text
        value = value.strip()
        value_lines = value.splitlines() or [value]
        formatted_parts.append(
            f"  {name.strip()}={value_lines[0]}"
            + "".join(f"\n{textwrap.indent(line, '    ')}" for line in value_lines[1:])
        )
    if not formatted_parts:
        return text
    return f"{head}(\n" + ",\n".join(formatted_parts) + "\n)"


def _split_top_level_fields(text: str) -> list[str]:
    fields: list[str] = []
    current: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    quote: str | None = None
    escape = False

    for character in text:
        current.append(character)
        if quote is not None:
            if escape:
                escape = False
                continue
            if character == "\\":
                escape = True
                continue
            if character == quote:
                quote = None
            continue

        if character in {"'", '"'}:
            quote = character
            continue
        if character == "(":
            paren_depth += 1
            continue
        if character == ")":
            paren_depth = max(0, paren_depth - 1)
            continue
        if character == "[":
            bracket_depth += 1
            continue
        if character == "]":
            bracket_depth = max(0, bracket_depth - 1)
            continue
        if character == "{":
            brace_depth += 1
            continue
        if character == "}":
            brace_depth = max(0, brace_depth - 1)
            continue
        if (
            character == ","
            and paren_depth == 0
            and bracket_depth == 0
            and brace_depth == 0
        ):
            fields.append("".join(current[:-1]).strip())
            current = []

    tail = "".join(current).strip()
    if tail:
        fields.append(tail)
    return fields
