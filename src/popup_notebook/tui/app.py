from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Iterable

from popup_notebook.config import load_app_config
from popup_notebook.project import build_project_context
from popup_notebook.sessions.manager import SessionAttachedError, SessionManager
from popup_notebook.sessions.models import Cell
from popup_notebook.tui.notebook import NotebookViewModel
from popup_notebook.tui.widgets.cell import (
    RUN_STAY_KEYS,
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
    move_to_next: bool


def run_tui(cwd: Path, *, key_debug: bool = False) -> None:
    """Run the Textual app if available."""
    key_debug = key_debug or os.environ.get("POPUP_NOTEBOOK_KEY_DEBUG") == "1"
    try:
        from textual.app import App, ComposeResult
        from textual.app import SystemCommand
        from textual.binding import Binding
        from textual.containers import VerticalScroll
        from textual.screen import Screen
        from textual.widgets import Footer
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
            Binding("z", "undo_delete", show=False),
            Binding("up", "select_up", show=False),
            Binding("down", "select_down", show=False),
            Binding("pageup", "scroll_page_up", show=False),
            Binding("pagedown", "scroll_page_down", show=False),
            Binding("home", "scroll_home", show=False),
            Binding("end", "scroll_end", show=False),
            Binding("ctrl+u", "scroll_page_up", show=False),
            Binding("ctrl+d", "scroll_page_down", show=False),
            *[Binding(key, "run_and_stay", show=False) for key in RUN_STAY_KEYS],
        ]

        def __init__(self) -> None:
            super().__init__()
            self.model = NotebookViewModel(manager, context.project_root, session)
            self._status = StatusBarWidget(id="status")
            self.edit_mode = True
            self._pending_nav_sequence = ""
            self._pending_nav_timer = None
            self._deleted_cells: list[DeletedCellSnapshot] = []
            self._pending_execution: PendingExecution | None = None
            self._execution_worker = None

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
                "undo_delete",
                "enter_edit",
                "select_up",
                "select_down",
            }:
                return not self.edit_mode
            return super().check_action(action, parameters)

        async def on_mount(self) -> None:
            await self._rebuild_notebook()

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

        async def action_run_and_stay(self) -> None:
            await self._execute_current_cell(move_to_next=False)

        async def action_run_and_move(self) -> None:
            await self._execute_current_cell(move_to_next=True)

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
            if manager.reset(context.project_root):
                await self._sync_widgets()
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
            if key in {"d", "i", "0"}:
                return key
            return None

        async def _execute_current_cell(self, *, move_to_next: bool) -> None:
            cell_id = self.model.current_cell_id
            if cell_id is None:
                return
            if self._pending_execution is not None:
                self.notify("A cell is already running.", severity="warning")
                return

            self._pending_execution = PendingExecution(cell_id=cell_id, move_to_next=move_to_next)
            self._execution_worker = self.run_worker(
                lambda: manager.execute_cell(context.project_root, cell_id),
                name="execute-cell",
                group="execution",
                description=f"Execute {cell_id}",
                exit_on_error=False,
                exclusive=True,
                thread=True,
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
            await container.mount_all(
                [
                    CellWidget(
                        cell,
                        current=(cell.id == self.model.current_cell_id),
                        edit_mode=(cell.id == self.model.current_cell_id and self.edit_mode),
                        markdown_center=config.ui.markdown_center,
                    )
                    for cell in self.model.session.cells
                ]
            )
            self._update_status()
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
                widget.set_running(
                    self._pending_execution is not None and cell.id == self._pending_execution.cell_id
                )
                widget.sync_from_cell(cell)

            self._update_status()
            if refocus:
                self.call_after_refresh(self._focus_current_cell)

        def _apply_widget_state(self, *, refocus: bool = True) -> None:
            for widget in self.query(CellWidget):
                widget.set_current(widget.cell.id == self.model.current_cell_id)
                widget.set_edit_mode(widget.cell.id == self.model.current_cell_id and self.edit_mode)
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
                widget.focus_editor()
            else:
                widget.focus_cell()

        async def _enter_edit_mode(self) -> None:
            self.edit_mode = True
            self._clear_nav_sequence()
            self._apply_widget_state()

        async def _exit_edit_mode(self) -> None:
            self.edit_mode = False
            self._clear_nav_sequence()
            self._apply_widget_state()

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
            if result is None or pending_execution is None:
                self._apply_widget_state()
                self.notify("Unable to execute current cell.", severity="error")
                return

            await self._sync_widgets(refocus=False)

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
            running = "RUN" if self._pending_execution is not None else None
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
                    interpreter,
                    f"{'EDIT' if self.edit_mode else 'NAV'}",
                    f"Cell {position}/{total if total else 0}",
                    f"K{generation}",
                ]
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
            yield from self._shortcut_commands()

        def _shortcut_commands(self) -> Iterable[SystemCommand]:
            commands = [
                (
                    "Shortcut: Run current cell",
                    "Ctrl+R in nav or edit mode. Executes the selected cell and keeps focus in place.",
                ),
                (
                    "Shortcut: Run and move",
                    "R in nav mode. Executes the selected cell and moves to the next cell.",
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

    _configure_terminal_key_reporting()
    try:
        PopupNotebookApp().run()
    finally:
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
