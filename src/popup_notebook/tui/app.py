from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Iterable

from popup_notebook.config import load_app_config
from popup_notebook.project import build_project_context
from popup_notebook.sessions.kernel import CompletionResult, LiveKernelClient
from popup_notebook.sessions.manager import BatchExecutionResult, SessionAttachedError, SessionManager
from popup_notebook.sessions.models import Cell
from popup_notebook.tui.notebook import NotebookViewModel
from popup_notebook.tui.widgets.cell import (
    RUN_CELL_KEYS,
    CellWidget,
    NotebookTextArea,
)
from popup_notebook.tui.widgets.status_bar import StatusBarWidget


@dataclass(frozen=True)
class DeletedCellSnapshot:
    cell: Cell
    index: int
    replace_placeholder: bool


@dataclass(frozen=True)
class PendingExecution:
    cell_id: str
    cell_ids: tuple[str, ...]
    label: str
    move_to_next: bool


_POPUP_PRESETS = {
    "focused": (0.72, 0.94),
    "expanded": (0.96, 0.96),
}


def run_tui(cwd: Path, *, key_debug: bool = False) -> None:
    """Run the Textual app if available."""
    key_debug = key_debug or os.environ.get("POPUP_NOTEBOOK_KEY_DEBUG") == "1"
    try:
        from textual.app import App, ComposeResult
        from textual.app import SystemCommand
        from textual.binding import Binding
        from textual.containers import VerticalScroll
        from textual.screen import Screen
        from textual.widgets import Footer, Static
        from textual.worker import Worker, WorkerState
    except ImportError as exc:
        raise RuntimeError(
            "Textual is not installed. Install project dependencies before running the UI."
        ) from exc

    context = build_project_context(cwd)
    config = load_app_config()
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
            background: rgb(24, 27, 31);
            color: rgb(221, 225, 229);
        }

        #notebook {
            height: 1fr;
            margin: 0 1 1 1;
            overflow-y: auto;
            scrollbar-size-vertical: 1;
            scrollbar-background: rgb(25, 27, 31);
            scrollbar-background-hover: rgb(25, 27, 31);
            scrollbar-background-active: rgb(25, 27, 31);
            scrollbar-color: rgb(95, 109, 124);
            scrollbar-color-hover: rgb(119, 137, 154);
            scrollbar-color-active: rgb(214, 140, 79);
        }

        #notebook-tail-spacer {
            height: 1;
            background: transparent;
        }

        .cell {
            margin: 0 0 1 0;
            padding: 0 1;
            height: auto;
            border: round rgb(124, 129, 136);
            background: rgb(40, 44, 50);
            color: rgb(228, 224, 216);
        }

        .cell.python {
            border: round rgb(126, 131, 140);
            background: rgb(40, 44, 50);
        }

        .cell.markdown {
            border: round rgb(92, 137, 131);
            background: rgb(35, 43, 46);
            color: rgb(223, 228, 225);
        }

        .cell.current {
            border: round rgb(214, 140, 79);
            background: rgb(52, 56, 62);
        }

        .cell.editing {
            border: round rgb(82, 160, 224);
            background: rgb(49, 56, 66);
        }

        .cell.running {
            border: round rgb(216, 182, 91);
        }

        .cell.markdown.current {
            background: rgb(43, 53, 56);
        }

        .cell.markdown.editing {
            background: rgb(46, 58, 62);
        }

        .cell-output {
            margin-top: 1;
            padding: 0 1;
            border: round rgb(95, 109, 124);
            background: rgb(24, 27, 32);
            color: rgb(225, 225, 219);
        }

        .cell-markdown-render {
            padding: 0 1;
            color: rgb(223, 228, 225);
        }

        .cell-markdown-render.centered {
            text-align: center;
        }

        TextArea {
            height: auto;
            min-height: 1;
            border: none;
            background: transparent;
            color: rgb(235, 231, 223);
            overflow-x: hidden;
            overflow-y: hidden;
        }

        .cell.markdown TextArea {
            color: rgb(218, 228, 223);
        }
        """

        BINDINGS = [
            Binding("ctrl+q", "quit", "Hide", priority=True),
            Binding("enter", "enter_edit", "Edit"),
            Binding("a", "insert_above", "Insert Above"),
            Binding("b", "insert_below", "Insert Below"),
            Binding("m", "cell_markdown", "Markdown"),
            Binding("y", "cell_python", "Python"),
            Binding("o", "toggle_output", show=False),
            Binding("l", "toggle_line_numbers", show=False),
            Binding("z", "undo_delete", show=False),
            Binding("up", "select_up", show=False),
            Binding("down", "select_down", show=False),
            Binding("pageup", "scroll_page_up", show=False),
            Binding("pagedown", "scroll_page_down", show=False),
            Binding("home", "scroll_home", show=False),
            Binding("end", "scroll_end", show=False),
            Binding("ctrl+u", "scroll_page_up", show=False),
            Binding("ctrl+d", "scroll_page_down", show=False),
            *[Binding(key, "run_and_move", show=False) for key in RUN_CELL_KEYS],
        ]

        def __init__(self) -> None:
            super().__init__()
            self.model = NotebookViewModel(manager, context.project_root, session)
            self._status = StatusBarWidget(id="status")
            self._live_kernel = LiveKernelClient()
            self.edit_mode = False
            self._pending_nav_sequence = ""
            self._pending_nav_timer = None
            self._deleted_cells: list[DeletedCellSnapshot] = []
            self._pending_execution: PendingExecution | None = None
            self._execution_worker = None
            self._nav_handoff_until = 0.0
            self._line_number_cells: set[str] = set()
            self._cursor_locations: dict[str, tuple[int, int]] = {}

        def compose(self) -> ComposeResult:
            yield self._status
            with VerticalScroll(id="notebook"):
                pass
            if config.ui.show_footer:
                yield Footer(compact=True)

        def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
            if action in {
                "insert_above",
                "insert_below",
                "cell_markdown",
                "cell_python",
                "toggle_output",
                "clear_output",
                "copy_cell_source",
                "copy_cell_output",
                "undo_delete",
                "enter_edit",
                "select_up",
                "select_down",
                "toggle_line_numbers",
            }:
                return not self.edit_mode
            return super().check_action(action, parameters)

        async def on_mount(self) -> None:
            await self._rebuild_notebook()
            self.run_worker(
                self._warm_kernel_client(),
                name="warm-kernel",
                group="kernel",
                exit_on_error=False,
            )

        async def on_key(self, event) -> None:
            if self.edit_mode:
                return
            if event.key == "R":
                event.stop()
                event.prevent_default()
                await self.action_run_and_move()
                return
            if event.key in {"up", "down"}:
                event.stop()
                event.prevent_default()
                self._clear_nav_sequence()
                await self._move_selection(event.key)
                return
            normalized_key = None
            if self._pending_nav_sequence == "r" and event.key in {"a", "b", "r"}:
                normalized_key = event.key
            elif self._pending_nav_sequence == "x" and event.key == "x":
                normalized_key = event.key
            elif self._pending_nav_sequence == "c" and event.key in {"c", "o"}:
                normalized_key = event.key
            else:
                normalized_key = self._normalize_nav_key(event.key)
            if normalized_key is None:
                if self._pending_nav_sequence and event.key == "escape":
                    event.stop()
                    event.prevent_default()
                    self._clear_nav_sequence()
                    self._update_status()
                elif self._pending_nav_sequence:
                    self._clear_nav_sequence()
                    self._update_status()
                return
            event.stop()
            event.prevent_default()
            await self._handle_nav_sequence(normalized_key)

        async def action_enter_edit(self) -> None:
            if self.model.current_cell_id is None:
                return
            await self._enter_edit_mode()

        async def action_insert_above(self) -> None:
            if self.edit_mode or self._pending_execution is not None:
                return
            new_cell = manager.insert_cell_before(context.project_root, self.model.current_cell_id)
            if new_cell is None:
                return
            self.model.current_cell_id = new_cell.id
            self.edit_mode = False
            await self._rebuild_notebook()

        async def action_insert_below(self) -> None:
            if self.edit_mode or self._pending_execution is not None:
                return
            new_cell = manager.insert_cell_after(context.project_root, self.model.current_cell_id)
            if new_cell is None:
                return
            self.model.current_cell_id = new_cell.id
            self.edit_mode = False
            await self._rebuild_notebook()

        async def action_cell_markdown(self) -> None:
            if (
                self.edit_mode
                or self.model.current_cell_id is None
                or self._pending_execution is not None
            ):
                return
            if manager.set_cell_kind(context.project_root, self.model.current_cell_id, "markdown"):
                await self._sync_widgets()

        async def action_cell_python(self) -> None:
            if (
                self.edit_mode
                or self.model.current_cell_id is None
                or self._pending_execution is not None
            ):
                return
            if manager.set_cell_kind(context.project_root, self.model.current_cell_id, "python"):
                await self._sync_widgets()

        async def action_toggle_output(self) -> None:
            if (
                self.edit_mode
                or self.model.current_cell_id is None
                or self._pending_execution is not None
            ):
                return
            if manager.toggle_cell_expanded(context.project_root, self.model.current_cell_id):
                await self._sync_widgets(refocus=False)

        async def action_clear_output(self) -> None:
            if (
                self.edit_mode
                or self.model.current_cell_id is None
                or self._pending_execution is not None
            ):
                return
            if manager.clear_cell_output(context.project_root, self.model.current_cell_id):
                await self._sync_widgets(refocus=False)

        def action_copy_cell_source(self) -> None:
            if self.edit_mode or self.model.current_cell_id is None:
                return
            self.model.reload()
            cell = next(
                (cell for cell in self.model.session.cells if cell.id == self.model.current_cell_id),
                None,
            )
            if cell is None:
                return
            self.copy_to_clipboard(cell.source)
            self.notify("Copied current cell to clipboard.")

        def action_copy_cell_output(self) -> None:
            if self.edit_mode or self.model.current_cell_id is None:
                return
            self.model.reload()
            cell = next(
                (cell for cell in self.model.session.cells if cell.id == self.model.current_cell_id),
                None,
            )
            if cell is None or not cell.output.strip():
                self.notify("Current cell has no output to copy.", severity="warning")
                return
            self.copy_to_clipboard(cell.output)
            self.notify("Copied current output to clipboard.")

        async def action_toggle_line_numbers(self) -> None:
            if (
                self.edit_mode
                or self.model.current_cell_id is None
                or self._pending_execution is not None
            ):
                return
            cell_id = self.model.current_cell_id
            if cell_id in self._line_number_cells:
                self._line_number_cells.remove(cell_id)
                enabled = False
            else:
                self._line_number_cells.add(cell_id)
                enabled = True
            self._apply_widget_state(refocus=False)
            self.notify(
                "Line numbers enabled for current cell."
                if enabled
                else "Line numbers hidden for current cell."
            )

        async def action_run_and_stay(self) -> None:
            await self._execute_current_cell(move_to_next=False)

        async def action_run_and_move(self) -> None:
            await self._execute_current_cell(move_to_next=True)

        async def action_run_all(self) -> None:
            self.model.reload()
            cell_ids = tuple(cell.id for cell in self.model.session.cells)
            await self._execute_cell_batch(cell_ids, label="RUN ALL")

        async def action_run_all_above(self) -> None:
            self.model.reload()
            current_index = self.model.current_index()
            if current_index <= 0:
                return
            cell_ids = tuple(cell.id for cell in self.model.session.cells[:current_index])
            await self._execute_cell_batch(cell_ids, label="RUN ABOVE")

        async def action_run_all_below(self) -> None:
            self.model.reload()
            current_index = self.model.current_index()
            if current_index < 0:
                return
            cell_ids = tuple(cell.id for cell in self.model.session.cells[current_index:])
            await self._execute_cell_batch(cell_ids, label="RUN BELOW")

        async def action_select_up(self) -> None:
            await self._move_selection("up")

        async def action_select_down(self) -> None:
            await self._move_selection("down")

        def action_scroll_page_up(self) -> None:
            self.query_one("#notebook", VerticalScroll).scroll_page_up(animate=False)

        def action_scroll_page_down(self) -> None:
            self.query_one("#notebook", VerticalScroll).scroll_page_down(animate=False)

        def action_scroll_home(self) -> None:
            self.query_one("#notebook", VerticalScroll).scroll_home(animate=False, immediate=True)

        def action_scroll_end(self) -> None:
            self.query_one("#notebook", VerticalScroll).scroll_end(animate=False, immediate=True)

        async def action_delete_cell(self) -> None:
            if self._pending_execution is not None:
                return
            cell_id = self.model.current_cell_id
            if cell_id is None:
                return
            self.model.reload()
            deleted_snapshot = None
            for index, cell in enumerate(self.model.session.cells):
                if cell.id != cell_id:
                    continue
                deleted_snapshot = DeletedCellSnapshot(
                    cell=Cell.from_dict(cell.to_dict()),
                    index=index,
                    replace_placeholder=(len(self.model.session.cells) == 1),
                )
                break
            if deleted_snapshot is None:
                return
            next_cell_id = manager.delete_cell(context.project_root, cell_id)
            if next_cell_id is None:
                return
            self._deleted_cells.append(deleted_snapshot)
            self.model.current_cell_id = next_cell_id
            self.edit_mode = False
            await self._rebuild_notebook()

        async def action_undo_delete(self) -> None:
            if self.edit_mode or not self._deleted_cells or self._pending_execution is not None:
                return
            snapshot = self._deleted_cells.pop()
            restored_cell_id = manager.restore_cell(
                context.project_root,
                snapshot.cell,
                snapshot.index,
                replace_placeholder=snapshot.replace_placeholder,
            )
            if restored_cell_id is None:
                self.notify("Unable to restore deleted cell.", severity="warning")
                return
            self.model.current_cell_id = restored_cell_id
            self.edit_mode = False
            await self._rebuild_notebook()

        async def action_interrupt_kernel(self) -> None:
            if manager.interrupt_kernel(context.project_root):
                self.notify("Kernel interrupted.")
            else:
                self.notify("Unable to interrupt kernel.", severity="warning")

        async def action_restart_kernel(self) -> None:
            if self._pending_execution is not None:
                self.notify("A cell is already running.", severity="warning")
                return
            if manager.reset(context.project_root):
                self._live_kernel.close()
                await self._sync_widgets()
                self.run_worker(
                    self._warm_kernel_client(),
                    name="warm-kernel",
                    group="kernel",
                    exit_on_error=False,
                )
                self.notify("Kernel restarted.")
            else:
                self.notify("Unable to restart kernel.", severity="warning")

        async def on_cell_widget_focused(self, message: CellWidget.Focused) -> None:
            if (
                self.model.current_cell_id == message.cell_id
                and self.edit_mode == message.edit_mode
            ):
                return
            self.model.current_cell_id = message.cell_id
            self.edit_mode = message.edit_mode
            self._clear_nav_sequence()
            self._apply_widget_state(refocus=False)

        async def on_cell_widget_select_neighbor(
            self, message: CellWidget.SelectNeighbor
        ) -> None:
            if self.edit_mode:
                return
            self.model.current_cell_id = message.cell_id
            await self._move_selection(message.direction)

        def on_cell_widget_cursor_moved(self, message: CellWidget.CursorMoved) -> None:
            self._cursor_locations[message.cell_id] = message.location

        def on_cell_widget_source_changed(self, message: CellWidget.SourceChanged) -> None:
            manager.update_cell_source(context.project_root, message.cell_id, message.source)

        async def on_notebook_text_area_exit_edit(self, message: NotebookTextArea.ExitEdit) -> None:
            self.model.current_cell_id = message.cell_id
            await self._exit_edit_mode()

        async def on_notebook_text_area_run_requested(
            self, message: NotebookTextArea.RunRequested
        ) -> None:
            self.model.current_cell_id = message.cell_id
            await self._execute_current_cell(move_to_next=message.move_to_next)

        async def on_notebook_text_area_move_to_neighbor(
            self, message: NotebookTextArea.MoveToNeighbor
        ) -> None:
            self.model.current_cell_id = message.cell_id
            target = self._neighbor_cell_id(message.cell_id, message.direction)
            if target is None:
                return
            self.model.current_cell_id = target
            await self._enter_edit_mode()

        async def _handle_nav_sequence(self, key: str) -> None:
            sequence = f"{self._pending_nav_sequence}{key}"[-2:]
            if sequence == "dd":
                self._clear_nav_sequence()
                await self.action_delete_cell()
                return
            if sequence == "ii":
                self._clear_nav_sequence()
                await self.action_interrupt_kernel()
                return
            if sequence == "00":
                self._clear_nav_sequence()
                await self.action_restart_kernel()
                return
            if sequence == "rr":
                self._clear_nav_sequence()
                await self.action_run_all()
                return
            if sequence == "ra":
                self._clear_nav_sequence()
                await self.action_run_all_above()
                return
            if sequence == "rb":
                self._clear_nav_sequence()
                await self.action_run_all_below()
                return
            if sequence == "xx":
                self._clear_nav_sequence()
                await self.action_clear_output()
                return
            if sequence == "cc":
                self._clear_nav_sequence()
                self.action_copy_cell_source()
                return
            if sequence == "co":
                self._clear_nav_sequence()
                self.action_copy_cell_output()
                return

            self._pending_nav_sequence = key
            self._update_status()
            self._arm_nav_sequence_reset()

        def _arm_nav_sequence_reset(self) -> None:
            if self._pending_nav_timer is not None:
                self._pending_nav_timer.stop()
            self._pending_nav_timer = self.set_timer(0.7, self._clear_nav_sequence)

        def _clear_nav_sequence(self) -> None:
            if self._pending_nav_timer is not None:
                self._pending_nav_timer.stop()
                self._pending_nav_timer = None
            self._pending_nav_sequence = ""
            if self.is_mounted:
                self._update_status()

        @staticmethod
        def _normalize_nav_key(key: str) -> str | None:
            if key == "kp_0":
                return "0"
            if key in {"d", "i", "0", "r", "x", "c"}:
                return key
            return None

        async def _execute_current_cell(self, *, move_to_next: bool) -> None:
            cell_id = self.model.current_cell_id
            if cell_id is None:
                return
            await self._execute_cell_batch((cell_id,), label="RUN", move_to_next=move_to_next)

        async def _execute_cell_batch(
            self,
            cell_ids: tuple[str, ...],
            *,
            label: str,
            move_to_next: bool = False,
        ) -> None:
            if not cell_ids:
                return
            if self._pending_execution is not None:
                self.notify("A cell is already running.", severity="warning")
                return

            current_cell_id = self.model.current_cell_id or cell_ids[0]
            self._pending_execution = PendingExecution(
                cell_id=current_cell_id,
                cell_ids=cell_ids,
                label=label,
                move_to_next=move_to_next,
            )
            self._execution_worker = self.run_worker(
                self._run_execution_batch(cell_ids),
                name="execute-cell",
                group="execution",
                description=f"{label} {len(cell_ids)} cell(s)",
                exit_on_error=False,
                exclusive=True,
            )
            self._apply_widget_state(refocus=False)

        async def _move_selection(self, direction: str) -> None:
            if self.edit_mode or self.model.current_cell_id is None:
                return
            neighbor = self._neighbor_cell_id(self.model.current_cell_id, direction)
            if neighbor is None:
                return
            self.model.current_cell_id = neighbor
            self._apply_widget_state()

        def _next_cell_id(self, current_cell_id: str) -> str | None:
            for index, cell in enumerate(self.model.session.cells):
                if cell.id == current_cell_id and index + 1 < len(self.model.session.cells):
                    return self.model.session.cells[index + 1].id
            return None

        def _neighbor_cell_id(self, current_cell_id: str, direction: str) -> str | None:
            for index, cell in enumerate(self.model.session.cells):
                if cell.id != current_cell_id:
                    continue
                if direction == "up" and index > 0:
                    return self.model.session.cells[index - 1].id
                if direction == "down" and index + 1 < len(self.model.session.cells):
                    return self.model.session.cells[index + 1].id
                return None
            return None

        async def _rebuild_notebook(self, *, refocus: bool = True) -> None:
            self.model.reload()
            container = self.query_one("#notebook", VerticalScroll)
            await container.remove_children()
            widgets = [
                CellWidget(
                    cell,
                    current=(cell.id == self.model.current_cell_id),
                    edit_mode=(cell.id == self.model.current_cell_id and self.edit_mode),
                    show_line_numbers=(cell.id in self._line_number_cells),
                    markdown_center=config.ui.markdown_center,
                    output_max_lines=config.ui.output_max_lines,
                    code_theme=config.ui.code_theme,
                )
                for cell in self.model.session.cells
            ]
            widgets.append(Static("", id="notebook-tail-spacer"))
            await container.mount_all(widgets)
            self._update_status()
            self.call_after_refresh(self._update_tail_spacer)
            if refocus:
                self.call_after_refresh(self._focus_current_cell)

        async def _sync_widgets(self, *, refocus: bool = True) -> None:
            self.model.reload()
            widgets = {widget.cell.id: widget for widget in self.query(CellWidget)}
            if set(widgets) != {cell.id for cell in self.model.session.cells}:
                await self._rebuild_notebook(refocus=refocus)
                return

            for cell in self.model.session.cells:
                widget = widgets[cell.id]
                widget.set_current(cell.id == self.model.current_cell_id)
                widget.set_edit_mode(cell.id == self.model.current_cell_id and self.edit_mode)
                widget.set_show_line_numbers(cell.id in self._line_number_cells)
                widget.set_running(
                    self._pending_execution is not None and cell.id == self._pending_execution.cell_id
                )
                widget.sync_from_cell(cell)

            self._update_status()
            self.call_after_refresh(self._update_tail_spacer)
            if refocus:
                self.call_after_refresh(self._focus_current_cell)

        def _apply_widget_state(self, *, refocus: bool = True) -> None:
            for widget in self.query(CellWidget):
                widget.set_current(widget.cell.id == self.model.current_cell_id)
                widget.set_edit_mode(widget.cell.id == self.model.current_cell_id and self.edit_mode)
                widget.set_show_line_numbers(widget.cell.id in self._line_number_cells)
                widget.set_running(
                    self._pending_execution is not None
                    and widget.cell.id == self._pending_execution.cell_id
                )
            self._update_status()
            if refocus:
                self.call_after_refresh(self._focus_current_cell)

        def _focus_current_cell(self) -> None:
            cell_id = self.model.current_cell_id
            if cell_id is None:
                return
            container = self.query_one("#notebook", VerticalScroll)
            try:
                widget = self.query_one(f"#cell-{cell_id}", CellWidget)
            except Exception:
                return
            container.scroll_to_widget(widget, animate=False, immediate=True, top=False)
            if self.edit_mode:
                widget.focus_editor(cursor_location=self._cursor_locations.get(cell_id))
            else:
                widget.focus_cell()

        def on_resize(self, _event) -> None:
            self.call_after_refresh(self._update_tail_spacer)

        def _update_tail_spacer(self) -> None:
            try:
                container = self.query_one("#notebook", VerticalScroll)
                spacer = self.query_one("#notebook-tail-spacer", Static)
            except Exception:
                return
            spacer.styles.height = max(6, container.content_region.height // 2)

        async def _enter_edit_mode(self) -> None:
            self._nav_handoff_until = 0.0
            self.edit_mode = True
            self._clear_nav_sequence()
            self._apply_widget_state()

        def fast_exit_edit_mode(self, cell_id: str) -> None:
            self.model.current_cell_id = cell_id
            self.edit_mode = False
            self._clear_nav_sequence()
            self._apply_widget_state(refocus=False)

        def begin_nav_handoff(self, cell_id: str) -> None:
            self.fast_exit_edit_mode(cell_id)
            self._nav_handoff_until = time.monotonic() + 0.75

        async def consume_nav_handoff(self, cell_id: str, key: str) -> bool:
            if time.monotonic() > self._nav_handoff_until:
                return False
            normalized_key = self._normalize_nav_key(key)
            if normalized_key is None:
                return False
            self.model.current_cell_id = cell_id
            self.edit_mode = False
            await self._handle_nav_sequence(normalized_key)
            return True

        async def _exit_edit_mode(self) -> None:
            self._nav_handoff_until = 0.0
            self.edit_mode = False
            self._clear_nav_sequence()
            self._apply_widget_state()

        async def _warm_kernel_client(self) -> None:
            try:
                await self._prepare_live_kernel()
            except Exception:
                return

        async def _prepare_live_kernel(self) -> bool:
            prepared = manager.prepare_kernel_session(context.project_root)
            if prepared is None:
                return False
            await self._live_kernel.ensure_connected(
                kernel_pid=prepared.runtime.pid,
                connection_file=prepared.runtime.connection_file,
            )
            if prepared.should_bootstrap:
                await self._live_kernel.bootstrap(prepared.startup_statements)
                manager.mark_kernel_bootstrapped(context.project_root, prepared.runtime.pid)
            return True

        async def _run_execution_batch(self, cell_ids: tuple[str, ...]) -> BatchExecutionResult:
            execution_plan = manager.load_cells(context.project_root, cell_ids)
            if not execution_plan:
                return BatchExecutionResult(executed_cell_ids=())

            if any(cell.kind == "python" for cell in execution_plan):
                prepared = await self._prepare_live_kernel()
                if not prepared:
                    return BatchExecutionResult(executed_cell_ids=())

            executed_cell_ids: list[str] = []
            failed_cell_id = None

            for plan_cell in execution_plan:
                if plan_cell.kind == "markdown":
                    output = ""
                    execution_count = None
                    success = True
                else:
                    execution = await self._live_kernel.execute(plan_cell.source)
                    output = execution.output
                    execution_count = execution.execution_count
                    success = execution.success

                if not manager.persist_execution_result(
                    context.project_root,
                    plan_cell.id,
                    output=output,
                    execution_count=execution_count,
                ):
                    break

                executed_cell_ids.append(plan_cell.id)
                if not success:
                    failed_cell_id = plan_cell.id
                    break

            return BatchExecutionResult(
                executed_cell_ids=tuple(executed_cell_ids),
                failed_cell_id=failed_cell_id,
            )

        async def request_completion(
            self,
            *,
            code: str,
            cursor_pos: int,
        ) -> CompletionResult | None:
            try:
                prepared = await self._prepare_live_kernel()
                if not prepared:
                    return None
                return await self._live_kernel.complete(code, cursor_pos)
            except Exception:
                return None

        async def on_worker_state_changed(self, message: Worker.StateChanged) -> None:
            if message.worker is not self._execution_worker:
                return
            if message.state not in {
                WorkerState.SUCCESS,
                WorkerState.ERROR,
                WorkerState.CANCELLED,
            }:
                return

            pending_execution = self._pending_execution
            self._execution_worker = None
            self._pending_execution = None

            if message.state == WorkerState.ERROR:
                self._apply_widget_state()
                error = message.worker.error
                self.notify(
                    str(error) or "Unable to execute current cell.",
                    severity="error",
                )
                return

            if message.state == WorkerState.CANCELLED:
                self._apply_widget_state()
                self.notify("Execution cancelled.", severity="warning")
                return

            result = message.worker.result
            if not isinstance(result, BatchExecutionResult) or pending_execution is None:
                self._apply_widget_state()
                self.notify("Unable to execute current cell.", severity="error")
                return

            await self._sync_widgets(refocus=False)

            if result.failed_cell_id is not None:
                self.model.current_cell_id = result.failed_cell_id
                self._apply_widget_state()
                self.notify("Execution stopped on error.", severity="warning")
                return

            if not pending_execution.move_to_next:
                self._apply_widget_state()
                return

            next_id = self._next_cell_id(pending_execution.cell_id)
            if next_id is None:
                new_cell = manager.insert_cell_after(context.project_root, pending_execution.cell_id)
                if new_cell is None:
                    self._apply_widget_state()
                    return
                self.model.current_cell_id = new_cell.id
                self.edit_mode = True
                await self._rebuild_notebook()
                return

            self.model.current_cell_id = next_id
            await self._enter_edit_mode()

        def _update_status(self) -> None:
            current_index = self.model.current_index()
            position = current_index + 1 if current_index >= 0 else 0
            total = len(self.model.session.cells)
            generation = self.model.session.kernel_generation
            pending = f"Pending: {self._pending_nav_sequence}" if self._pending_nav_sequence else None
            location = context.project_root.name or str(context.project_root)
            interpreter = context.interpreter.name
            running = self._pending_execution.label if self._pending_execution is not None else None
            if config.ui.status_verbosity == "full":
                status_parts = [
                    f"Project {context.project_root}",
                    f"Python {context.interpreter}",
                    f"Source {context.interpreter_source}",
                    f"Mode {'EDIT' if self.edit_mode else 'NAV'}",
                    f"Cell {position}/{total if total else 0}",
                    f"Kernel {generation}",
                ]
            else:
                status_parts = [
                    location,
                    f"{'EDIT' if self.edit_mode else 'NAV'}",
                    f"Cell {position}/{total if total else 0}",
                ]
                if generation > 1:
                    status_parts.append(f"Kernel {generation}")
            self._status.update(
                "  ".join(
                    status_parts
                    + [
                        *([running] if running else []),
                        *(["KeyDebug: keys.log"] if key_debug else []),
                    ]
                    + ([pending] if pending else [])
                )
            )

        def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
            yield from super().get_system_commands(screen)
            yield SystemCommand(
                "Run all cells",
                "Execute every cell in notebook order and stop on the first error.",
                lambda: self._queue_palette_action(self.action_run_all, "run-all"),
            )
            yield SystemCommand(
                "Run all above",
                "Execute cells above the current selection.",
                lambda: self._queue_palette_action(self.action_run_all_above, "run-all-above"),
            )
            yield SystemCommand(
                "Run all below",
                "Execute the current cell and all cells below it.",
                lambda: self._queue_palette_action(self.action_run_all_below, "run-all-below"),
            )
            yield SystemCommand(
                "Clear current output",
                "Clear the selected cell output without deleting the cell source.",
                lambda: self._queue_palette_action(self.action_clear_output, "clear-output"),
            )
            yield SystemCommand(
                "Toggle current cell line numbers",
                "Show or hide line numbers for the selected cell.",
                lambda: self._queue_palette_action(
                    self.action_toggle_line_numbers,
                    "toggle-line-numbers",
                ),
            )
            yield SystemCommand(
                "Resize popup: focused",
                "Shrink the popup into a thinner tall layout for code-first work.",
                lambda: self._resize_popup("focused"),
            )
            yield SystemCommand(
                "Resize popup: expanded",
                "Expand the popup closer to full-screen when you need more room.",
                lambda: self._resize_popup("expanded"),
            )
            yield from self._shortcut_commands()

        def _shortcut_commands(self) -> Iterable[SystemCommand]:
            commands = [
                (
                    "Shortcut: Run and move",
                    "Ctrl+R in nav or edit mode, or R in nav mode. Executes the selected cell and moves down, creating a new cell if needed.",
                ),
                (
                    "Shortcut: Enter edit mode",
                    "Enter in nav mode. Focuses the selected cell for typing.",
                ),
                (
                    "Shortcut: Exit edit mode",
                    "Escape in edit mode. Returns to nav mode on the current cell.",
                ),
                (
                    "Shortcut: Add cells",
                    "a inserts above and b inserts below in nav mode. Selection stays in nav mode.",
                ),
                (
                    "Shortcut: Switch cell type",
                    "y makes the current cell Python and m makes it Markdown in nav mode.",
                ),
                (
                    "Shortcut: Delete and restore",
                    "dd deletes the current cell and z restores the most recently deleted cell in nav mode.",
                ),
                (
                    "Shortcut: Copy current cell",
                    "cc copies the current cell source and co copies the current output in nav mode.",
                ),
                (
                    "Shortcut: Toggle output",
                    "o expands or collapses the current cell output in nav mode.",
                ),
                (
                    "Shortcut: Toggle line numbers",
                    "l shows or hides line numbers for the current cell in nav mode.",
                ),
                (
                    "Shortcut: Run ranges",
                    "rr runs all cells, ra runs all above, and rb runs the selected cell and everything below.",
                ),
                (
                    "Shortcut: Clear output",
                    "xx clears the current cell output in nav mode.",
                ),
                (
                    "Shortcut: Kernel control",
                    "ii interrupts the kernel and 00 restarts it in nav mode.",
                ),
                (
                    "Shortcut: Navigate cells",
                    "Up and down move between cells in nav mode. PageUp, PageDown, Ctrl+U, Ctrl+D, Home, and End scroll the notebook.",
                ),
                (
                    "Shortcut: Hide popup",
                    "Ctrl+Q detaches the popup and keeps the background session alive.",
                ),
                (
                    "Config: Global config file",
                    "Global settings live in ~/.config/popup-notebook/config.toml or XDG_CONFIG_HOME.",
                ),
            ]
            for title, help_text in commands:
                yield SystemCommand(title, help_text, lambda message=help_text: self.notify(message))

        def _queue_palette_action(self, action, name: str) -> None:
            self.run_worker(
                action(),
                name=name,
                group="palette",
                exit_on_error=False,
            )

        def _resize_popup(self, preset_name: str) -> None:
            preset = _POPUP_PRESETS.get(preset_name)
            if preset is None:
                return
            if _resize_tmux_popup(*preset):
                self.notify(f"Popup resized: {preset_name}.")
            else:
                self.notify("Unable to resize popup in this session.", severity="warning")

        def copy_to_clipboard(self, text: str) -> None:
            super().copy_to_clipboard(text)
            _copy_to_system_clipboard(text)

        def load_system_clipboard(self) -> bool:
            clipboard_text = _read_from_system_clipboard()
            if clipboard_text is None:
                return False
            self.clipboard = clipboard_text
            return True

    _configure_terminal_key_reporting()
    app = PopupNotebookApp()
    try:
        app.run()
    finally:
        app._live_kernel.close()
        _restore_terminal_key_reporting()
        manager.detach(context.project_root, attachment_token)


def _configure_terminal_key_reporting() -> None:
    _write_terminal_control("\x1b[>4;1m")
    _write_terminal_control("\x1b[>7;1m")


def _restore_terminal_key_reporting() -> None:
    _write_terminal_control("\x1b[>4n")
    _write_terminal_control("\x1b[>7n")


def _write_terminal_control(sequence: str) -> None:
    try:
        os.write(sys.__stderr__.fileno(), sequence.encode("ascii"))
    except OSError:
        return


def _copy_to_system_clipboard(text: str) -> None:
    commands = []
    if shutil.which("pbcopy"):
        commands.append(["pbcopy"])
    if shutil.which("wl-copy"):
        commands.append(["wl-copy"])
    if shutil.which("xclip"):
        commands.append(["xclip", "-selection", "clipboard"])
    if shutil.which("xsel"):
        commands.append(["xsel", "--clipboard", "--input"])

    for command in commands:
        try:
            subprocess.run(
                command,
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (OSError, subprocess.CalledProcessError):
            continue


def _read_from_system_clipboard() -> str | None:
    commands = []
    if shutil.which("pbpaste"):
        commands.append(["pbpaste"])
    if shutil.which("wl-paste"):
        commands.append(["wl-paste", "--no-newline"])
    if shutil.which("xclip"):
        commands.append(["xclip", "-selection", "clipboard", "-o"])
    if shutil.which("xsel"):
        commands.append(["xsel", "--clipboard", "--output"])

    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        return completed.stdout
    return None


def _resize_tmux_popup(width_ratio: float, height_ratio: float) -> bool:
    tmux_pane = os.environ.get("TMUX_PANE")
    if not os.environ.get("TMUX") or not tmux_pane:
        return False
    try:
        dimensions = subprocess.run(
            ["tmux", "display-message", "-p", "-t", tmux_pane, "#{client_width} #{client_height}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        client_width_str, client_height_str = dimensions.split()
        client_width = int(client_width_str)
        client_height = int(client_height_str)
        target_width = max(80, int(client_width * width_ratio))
        target_height = max(24, int(client_height * height_ratio))
        subprocess.run(
            [
                "tmux",
                "resize-pane",
                "-t",
                tmux_pane,
                "-x",
                str(target_width),
                "-y",
                str(target_height),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False
    return True
