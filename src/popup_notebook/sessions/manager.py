from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from popup_notebook.project import build_project_context, load_project_notebook_settings
from popup_notebook.sessions.bootstrap import BOOTSTRAP_VERSION
from popup_notebook.sessions.kernel import KernelController
from popup_notebook.sessions.models import Cell, CellKind, SessionState
from popup_notebook.sessions.store import (
    delete_session_state,
    load_session_state,
    save_session_state,
    session_lock,
    session_state_path,
)

class SessionAttachedError(RuntimeError):
    """Raised when a session already has an active UI attachment."""


@dataclass(frozen=True)
class BatchExecutionResult:
    executed_cell_ids: tuple[str, ...]
    failed_cell_id: str | None = None


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
            else:
                session.interpreter = context.interpreter
                session.interpreter_source = context.interpreter_source
            save_session_state(session)
            return session

    def get(self, project_root: Path) -> SessionState | None:
        with session_lock(project_root):
            return load_session_state(project_root)

    def status(self, project_root: Path) -> dict[str, object]:
        with session_lock(project_root):
            session = load_session_state(project_root)
            kernel_alive = False
            kernel_pid = None
            connection_file = None
            if session is not None:
                kernel_pid = session.kernel_pid
                connection_file = str(session.connection_file) if session.connection_file else None
                if session.kernel_pid is not None:
                    kernel_alive = KernelController.is_alive(session.kernel_pid)
            return {
                "exists": session is not None,
                "attached": session.attached if session is not None else False,
                "kernel_generation": session.kernel_generation if session is not None else None,
                "kernel_alive": kernel_alive,
                "kernel_pid": kernel_pid,
                "connection_file": connection_file,
                "cell_count": len(session.cells) if session is not None else 0,
                "state_path": str(session_state_path(project_root)),
            }

    def attach(self, cwd: Path) -> tuple[SessionState, str]:
        context = build_project_context(cwd)
        token = str(uuid4())
        with session_lock(context.project_root):
            session = load_session_state(context.project_root)
            if session is None:
                session = SessionState(
                    project_root=context.project_root,
                    interpreter=context.interpreter,
                    interpreter_source=context.interpreter_source,
                    cells=[self._blank_cell()],
                )
            else:
                session.interpreter = context.interpreter
                session.interpreter_source = context.interpreter_source
            if session.attached:
                raise SessionAttachedError(
                    f"Session for {context.project_root} is already attached elsewhere."
                )
            session.attached = True
            session.attachment_token = token
            save_session_state(session)
            controller = self._controller(session)
            existing_pid = session.kernel_pid
            existing_connection_file = session.connection_file

        try:
            runtime = controller.ensure_running(
                existing_pid=existing_pid,
                existing_connection_file=existing_connection_file,
            )
        except Exception:
            with session_lock(context.project_root):
                session = load_session_state(context.project_root)
                if session is not None and session.attachment_token == token:
                    session.attached = False
                    session.attachment_token = None
                    save_session_state(session)
            raise

        with session_lock(context.project_root):
            session = load_session_state(context.project_root)
            if session is None:
                raise RuntimeError(f"Session for {context.project_root} disappeared during attach.")
            session.kernel_pid = runtime.pid
            session.connection_file = runtime.connection_file
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

    def update_cell_source(self, project_root: Path, cell_id: str, source: str) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            cell = self._find_cell(session, cell_id)
            if cell is None:
                return False
            cell.source = source
            save_session_state(session)
            return True

    def set_cell_kind(self, project_root: Path, cell_id: str, kind: CellKind) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            cell = self._find_cell(session, cell_id)
            if cell is None:
                return False
            cell.kind = kind
            if kind == "markdown":
                cell.output = ""
                cell.execution_count = None
            save_session_state(session)
            return True

    def toggle_cell_expanded(self, project_root: Path, cell_id: str) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            cell = self._find_cell(session, cell_id)
            if cell is None or not cell.output.strip():
                return False
            cell.expanded = not cell.expanded
            save_session_state(session)
            return True

    def insert_cell_before(
        self,
        project_root: Path,
        reference_cell_id: str | None,
        kind: CellKind = "python",
    ) -> Cell | None:
        return self._insert_cell(project_root, reference_cell_id, kind, before=True)

    def insert_cell_after(
        self,
        project_root: Path,
        reference_cell_id: str | None,
        kind: CellKind = "python",
    ) -> Cell | None:
        return self._insert_cell(project_root, reference_cell_id, kind, before=False)

    def execute_cell(self, project_root: Path, cell_id: str) -> Cell | None:
        batch_result = self.execute_cells(project_root, [cell_id])
        if cell_id not in batch_result.executed_cell_ids:
            return None
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return None
            cell = self._find_cell(session, cell_id)
            if cell is None:
                return None
            return cell

    def execute_cells(self, project_root: Path, cell_ids: list[str]) -> BatchExecutionResult:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return BatchExecutionResult(executed_cell_ids=())
            cells = {
                cell.id: cell
                for cell in session.cells
                if cell.id in cell_ids
            }
            execution_plan = [cells[cell_id] for cell_id in cell_ids if cell_id in cells]
            if not execution_plan:
                return BatchExecutionResult(executed_cell_ids=())
            controller = self._controller(session)
            existing_pid = session.kernel_pid
            existing_connection_file = session.connection_file
            startup_statements = load_project_notebook_settings(
                session.project_root
            ).startup_statements

        runtime = None
        if any(cell.kind == "python" for cell in execution_plan):
            runtime = controller.ensure_running(
                existing_pid=existing_pid,
                existing_connection_file=existing_connection_file,
            )
            with session_lock(project_root):
                session = load_session_state(project_root)
                if session is None:
                    return BatchExecutionResult(executed_cell_ids=())
                session.kernel_pid = runtime.pid
                session.connection_file = runtime.connection_file
                should_bootstrap = (
                    session.bootstrapped_kernel_pid != runtime.pid
                    or session.bootstrap_version != BOOTSTRAP_VERSION
                )
                if should_bootstrap:
                    session.bootstrapped_kernel_pid = None
                    session.bootstrap_version = None
                save_session_state(session)
            if should_bootstrap:
                controller.bootstrap(runtime.connection_file, startup_statements)
                with session_lock(project_root):
                    session = load_session_state(project_root)
                    if session is None:
                        return BatchExecutionResult(executed_cell_ids=())
                    session.bootstrapped_kernel_pid = runtime.pid
                    session.bootstrap_version = BOOTSTRAP_VERSION
                    save_session_state(session)

        executed_cell_ids: list[str] = []
        failed_cell_id = None

        for plan_cell in execution_plan:
            if plan_cell.kind == "markdown":
                output = ""
                execution_count = None
                success = True
            else:
                assert runtime is not None
                execution = controller.execute(runtime.connection_file, plan_cell.source)
                output = execution.output
                execution_count = execution.execution_count
                success = execution.success

            with session_lock(project_root):
                session = load_session_state(project_root)
                if session is None:
                    break
                current_cell = self._find_cell(session, plan_cell.id)
                if current_cell is None:
                    break
                current_cell.output = output
                current_cell.execution_count = execution_count
                current_cell.expanded = False
                save_session_state(session)

            executed_cell_ids.append(plan_cell.id)
            if not success:
                failed_cell_id = plan_cell.id
                break

        return BatchExecutionResult(
            executed_cell_ids=tuple(executed_cell_ids),
            failed_cell_id=failed_cell_id,
        )

    def reset(self, project_root: Path) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            controller = self._controller(session)
            existing_pid = session.kernel_pid
            existing_connection_file = session.connection_file

        runtime = controller.restart(
            existing_pid=existing_pid,
            existing_connection_file=existing_connection_file,
        )

        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            session.kernel_generation += 1
            session.kernel_pid = runtime.pid
            session.connection_file = runtime.connection_file
            session.bootstrapped_kernel_pid = None
            session.bootstrap_version = None
            save_session_state(session)
            return True

    def hard_reset(self, project_root: Path) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            controller = self._controller(session)
            existing_pid = session.kernel_pid
            existing_connection_file = session.connection_file

        runtime = controller.restart(
            existing_pid=existing_pid,
            existing_connection_file=existing_connection_file,
        )

        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            session.kernel_generation += 1
            session.kernel_pid = runtime.pid
            session.connection_file = runtime.connection_file
            session.bootstrapped_kernel_pid = None
            session.bootstrap_version = None
            session.cells = [self._blank_cell()]
            save_session_state(session)
            return True

    def interrupt_kernel(self, project_root: Path) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            controller = self._controller(session)
            existing_pid = session.kernel_pid

        return controller.interrupt(existing_pid)

    def clear_cell_output(self, project_root: Path, cell_id: str) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            cell = self._find_cell(session, cell_id)
            if cell is None or not cell.output.strip():
                return False
            cell.output = ""
            cell.expanded = False
            save_session_state(session)
            return True

    def delete_cell(self, project_root: Path, cell_id: str) -> str | None:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return None

            index = next(
                (position for position, cell in enumerate(session.cells) if cell.id == cell_id),
                None,
            )
            if index is None:
                return None

            if len(session.cells) == 1:
                session.cells = [self._blank_cell()]
                next_cell_id = session.cells[0].id
            else:
                del session.cells[index]
                next_index = min(index, len(session.cells) - 1)
                next_cell_id = session.cells[next_index].id

            save_session_state(session)
            return next_cell_id

    def restore_cell(
        self,
        project_root: Path,
        cell: Cell,
        index: int,
        *,
        replace_placeholder: bool = False,
    ) -> str | None:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return None

            restored = Cell.from_dict(cell.to_dict())
            if replace_placeholder and len(session.cells) == 1 and self._is_blank_cell(
                session.cells[0]
            ):
                session.cells[0] = restored
            else:
                insert_at = max(0, min(index, len(session.cells)))
                session.cells.insert(insert_at, restored)

            save_session_state(session)
            return restored.id

    def kill(self, project_root: Path) -> bool:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            controller = self._controller(session)
            existing_pid = session.kernel_pid
            existing_connection_file = session.connection_file

        controller.shutdown(existing_pid, existing_connection_file)

        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return False
            delete_session_state(project_root)
            return True

    @staticmethod
    def _blank_cell() -> Cell:
        return Cell(id=str(uuid4()), kind="python")

    @staticmethod
    def _controller(session: SessionState) -> KernelController:
        return KernelController(session.project_root, session.interpreter)

    @staticmethod
    def _find_cell(session: SessionState, cell_id: str) -> Cell | None:
        for cell in session.cells:
            if cell.id == cell_id:
                return cell
        return None

    @staticmethod
    def _is_blank_cell(cell: Cell) -> bool:
        return (
            cell.kind == "python"
            and cell.source == ""
            and cell.output == ""
            and cell.execution_count is None
        )

    def _insert_cell(
        self,
        project_root: Path,
        reference_cell_id: str | None,
        kind: CellKind,
        *,
        before: bool,
    ) -> Cell | None:
        with session_lock(project_root):
            session = load_session_state(project_root)
            if session is None:
                return None

            new_cell = Cell(id=str(uuid4()), kind=kind)
            if not session.cells or reference_cell_id is None:
                session.cells.append(new_cell)
            else:
                index = next(
                    (position for position, cell in enumerate(session.cells) if cell.id == reference_cell_id),
                    None,
                )
                if index is None:
                    session.cells.append(new_cell)
                else:
                    insert_at = index if before else index + 1
                    session.cells.insert(insert_at, new_cell)

            save_session_state(session)
            return new_cell
