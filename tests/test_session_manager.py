from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
import sys
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
