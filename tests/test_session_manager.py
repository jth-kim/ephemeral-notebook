from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from popup_notebook.project import ProjectContext
from popup_notebook.sessions.manager import SessionAttachedError, SessionManager
from popup_notebook.sessions.store import save_session_state

REPO_PYTHON = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"


class SessionManagerTests(unittest.TestCase):
    def _make_project(self, root: Path, *, real_python: bool = False) -> tuple[Path, Path]:
        project = root / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text("", encoding="utf-8")
        python = project / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        if real_python:
            python.write_text(
                "#!/bin/sh\n"
                f"exec {Path(sys.executable)} \"$@\"\n",
                encoding="utf-8",
            )
            python.chmod(0o755)
        else:
            python.write_text("", encoding="utf-8")
        return project, python

    @contextmanager
    def _patched_context(self, project: Path):
        with patch(
            "popup_notebook.sessions.manager.build_project_context",
            return_value=ProjectContext(
                cwd=project.resolve(),
                project_root=project.resolve(),
                interpreter=REPO_PYTHON,
                interpreter_source="test interpreter",
            ),
        ):
            yield

    def test_get_or_create_persists_state_across_manager_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    first_manager = SessionManager()
                    second_manager = SessionManager()

                    created = first_manager.get_or_create(project)
                    loaded = second_manager.get_or_create(project)

                    self.assertEqual(created.project_root, loaded.project_root)
                    self.assertEqual(len(loaded.cells), 1)
                    self.assertEqual(loaded.interpreter, REPO_PYTHON)

    def test_reset_increments_kernel_generation_without_changing_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session = manager.get_or_create(project)
                    original_generation = session.kernel_generation
                    original_cell_id = session.cells[0].id
                    manager.attach(project)
                    manager.detach(project.resolve())

                    reset = manager.reset(project.resolve())
                    updated = manager.get(project.resolve())

                    self.assertTrue(reset)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertEqual(updated.kernel_generation, original_generation + 1)
                    self.assertEqual(updated.cells[0].id, original_cell_id)

    def test_hard_reset_recreates_blank_notebook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session = manager.get_or_create(project)
                    session.cells.append(session.cells[0].__class__(id="second", kind="markdown"))
                    save_session_state(session)
                    manager.attach(project)
                    manager.detach(project.resolve())

                    hard_reset = manager.hard_reset(project.resolve())
                    updated = manager.get(project.resolve())

                    self.assertTrue(hard_reset)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertEqual(len(updated.cells), 1)
                    self.assertEqual(updated.cells[0].kind, "python")

    def test_attach_blocks_second_attachment_until_detach(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session, token = manager.attach(project)

                    self.assertTrue(session.attached)
                    with self.assertRaises(SessionAttachedError):
                        manager.attach(project)

                    manager.detach(project.resolve(), token)
                    reattached, _ = manager.attach(project)
                    self.assertTrue(reattached.attached)
                    manager.kill(project.resolve())

    def test_attach_starts_kernel_and_updates_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    _session, token = manager.attach(project)
                    status = manager.status(project.resolve())

                    self.assertTrue(status["kernel_alive"])
                    self.assertIsNotNone(status["kernel_pid"])
                    self.assertIsNotNone(status["connection_file"])

                    manager.detach(project.resolve(), token)
                    manager.kill(project.resolve())

    def test_cell_mutation_and_execution_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session, token = manager.attach(project)
                    cell_id = session.cells[0].id

                    self.assertTrue(manager.update_cell_source(project.resolve(), cell_id, "1 + 1"))
                    executed = manager.execute_cell(project.resolve(), cell_id)

                    self.assertIsNotNone(executed)
                    assert executed is not None
                    self.assertIn("2", executed.output)
                    self.assertEqual(executed.execution_count, 1)

                    inserted = manager.insert_cell_after(project.resolve(), cell_id)
                    self.assertIsNotNone(inserted)
                    assert inserted is not None
                    self.assertTrue(
                        manager.set_cell_kind(
                            project.resolve(), inserted.id, "markdown"
                        )
                    )

                    updated = manager.get(project.resolve())
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertEqual(len(updated.cells), 2)
                    self.assertEqual(updated.cells[1].kind, "markdown")
                    self.assertIsNone(updated.cells[1].execution_count)

                    manager.detach(project.resolve(), token)
                    manager.kill(project.resolve())

    def test_execute_cells_runs_batch_and_stops_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session, token = manager.attach(project)
                    first_id = session.cells[0].id
                    second = manager.insert_cell_after(project.resolve(), first_id)
                    third = manager.insert_cell_after(
                        project.resolve(), second.id if second else None
                    )
                    assert second is not None
                    assert third is not None

                    manager.update_cell_source(project.resolve(), first_id, "value = 10\nvalue")
                    manager.update_cell_source(
                        project.resolve(),
                        second.id,
                        "raise RuntimeError('boom')",
                    )
                    manager.update_cell_source(project.resolve(), third.id, "value + 5")

                    result = manager.execute_cells(
                        project.resolve(),
                        [first_id, second.id, third.id],
                    )
                    updated = manager.get(project.resolve())

                    self.assertEqual(result.executed_cell_ids, (first_id, second.id))
                    self.assertEqual(result.failed_cell_id, second.id)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertIn("10", updated.cells[0].output)
                    self.assertIn("RuntimeError", updated.cells[1].output)
                    self.assertEqual(updated.cells[2].output, "")

                    manager.detach(project.resolve(), token)
                    manager.kill(project.resolve())

    def test_execute_cell_bootstraps_only_once_per_live_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session, token = manager.attach(project)
                    cell_id = session.cells[0].id
                    manager.update_cell_source(project.resolve(), cell_id, "1 + 1")

                    with patch(
                        "popup_notebook.sessions.manager.KernelController.bootstrap"
                    ) as bootstrap:
                        bootstrap.return_value = None
                        manager.execute_cell(project.resolve(), cell_id)
                        manager.execute_cell(project.resolve(), cell_id)

                    self.assertEqual(bootstrap.call_count, 1)

                    manager.detach(project.resolve(), token)
                    manager.kill(project.resolve())

    def test_delete_cell_preserves_single_blank_notebook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session = manager.get_or_create(project)
                    remaining = manager.delete_cell(project.resolve(), session.cells[0].id)

                    updated = manager.get(project.resolve())

                    self.assertIsNotNone(remaining)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertEqual(len(updated.cells), 1)
                    self.assertEqual(updated.cells[0].kind, "python")
                    self.assertEqual(updated.cells[0].id, remaining)

    def test_restore_cell_replaces_placeholder_after_last_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session = manager.get_or_create(project)
                    deleted = session.cells[0]
                    manager.delete_cell(project.resolve(), deleted.id)

                    restored_id = manager.restore_cell(
                        project.resolve(),
                        deleted,
                        0,
                        replace_placeholder=True,
                    )
                    updated = manager.get(project.resolve())

                    self.assertEqual(restored_id, deleted.id)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertEqual(len(updated.cells), 1)
                    self.assertEqual(updated.cells[0].id, deleted.id)

    def test_restore_cell_reinserts_deleted_cell_at_original_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session = manager.get_or_create(project)
                    first = session.cells[0]
                    second = manager.insert_cell_after(project.resolve(), first.id)
                    assert second is not None
                    manager.update_cell_source(project.resolve(), first.id, "first")
                    manager.update_cell_source(project.resolve(), second.id, "second")

                    manager.delete_cell(project.resolve(), first.id)
                    restored_id = manager.restore_cell(project.resolve(), first, 0)
                    updated = manager.get(project.resolve())

                    self.assertEqual(restored_id, first.id)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertEqual([cell.id for cell in updated.cells], [first.id, second.id])

    def test_interrupt_kernel_uses_live_kernel_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    _session, token = manager.attach(project)

                    interrupted = manager.interrupt_kernel(project.resolve())

                    self.assertTrue(interrupted)

                    manager.detach(project.resolve(), token)
                    manager.kill(project.resolve())

    def test_toggle_cell_expanded_persists_output_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session = manager.get_or_create(project)
                    cell_id = session.cells[0].id
                    manager.update_cell_source(project.resolve(), cell_id, "print('hello')")
                    saved = manager.get(project.resolve())
                    assert saved is not None
                    saved.cells[0].output = "line1\nline2\nline3"
                    save_session_state(saved)

                    toggled = manager.toggle_cell_expanded(project.resolve(), cell_id)
                    updated = manager.get(project.resolve())

                    self.assertTrue(toggled)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertTrue(updated.cells[0].expanded)

    def test_clear_cell_output_preserves_execution_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session = manager.get_or_create(project)
                    session.cells[0].output = "hello"
                    session.cells[0].execution_count = 3
                    save_session_state(session)

                    cleared = manager.clear_cell_output(project.resolve(), session.cells[0].id)
                    updated = manager.get(project.resolve())

                    self.assertTrue(cleared)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertEqual(updated.cells[0].output, "")
                    self.assertEqual(updated.cells[0].execution_count, 3)

    def test_execute_cell_recovers_missing_connection_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    session, token = manager.attach(project)
                    first_id = session.cells[0].id
                    second = manager.insert_cell_after(project.resolve(), first_id)
                    assert second is not None
                    original_pid = session.kernel_pid
                    connection_file = session.connection_file
                    assert connection_file is not None
                    manager.update_cell_source(project.resolve(), first_id, "value = 40")
                    first = manager.execute_cell(project.resolve(), first_id)

                    self.assertIsNotNone(first)
                    assert first is not None
                    connection_file.unlink()
                    manager.update_cell_source(project.resolve(), second.id, "value + 2")
                    executed = manager.execute_cell(project.resolve(), second.id)
                    updated = manager.get(project.resolve())

                    self.assertIsNotNone(executed)
                    assert executed is not None
                    self.assertIn("42", executed.output)
                    self.assertIsNotNone(updated)
                    assert updated is not None
                    self.assertEqual(updated.kernel_pid, original_pid)

                    manager.detach(project.resolve(), token)
                    manager.kill(project.resolve())

    def test_kill_removes_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project, _python = self._make_project(root, real_python=True)

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                with self._patched_context(project):
                    manager = SessionManager()
                    manager.attach(project)
                    manager.detach(project.resolve())

                    killed = manager.kill(project.resolve())

                    self.assertTrue(killed)
                    self.assertIsNone(manager.get(project.resolve()))


if __name__ == "__main__":
    unittest.main()
