from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from popup_notebook.sessions.manager import SessionAttachedError, SessionManager


class SessionManagerTests(unittest.TestCase):
    def test_get_or_create_persists_state_across_manager_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("", encoding="utf-8")
            python = project / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                first_manager = SessionManager()
                second_manager = SessionManager()

                created = first_manager.get_or_create(project)
                loaded = second_manager.get_or_create(project)

                self.assertEqual(created.project_root, loaded.project_root)
                self.assertEqual(len(loaded.cells), 1)
                self.assertEqual(loaded.interpreter, python.resolve())

    def test_reset_increments_kernel_generation_without_changing_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("", encoding="utf-8")
            python = project / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                manager = SessionManager()
                session = manager.get_or_create(project)
                original_generation = session.kernel_generation
                original_cell_id = session.cells[0].id

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
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("", encoding="utf-8")
            python = project / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                manager = SessionManager()
                session = manager.get_or_create(project)
                session.cells.append(session.cells[0].__class__(id="second", kind="markdown"))
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
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("", encoding="utf-8")
            python = project / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                manager = SessionManager()
                session, token = manager.attach(project)

                self.assertTrue(session.attached)
                with self.assertRaises(SessionAttachedError):
                    manager.attach(project)

                manager.detach(project.resolve(), token)
                reattached, _ = manager.attach(project)
                self.assertTrue(reattached.attached)

    def test_kill_removes_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            project.mkdir()
            (project / "pyproject.toml").write_text("", encoding="utf-8")
            python = project / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                manager = SessionManager()
                manager.get_or_create(project)

                killed = manager.kill(project.resolve())

                self.assertTrue(killed)
                self.assertIsNone(manager.get(project.resolve()))


if __name__ == "__main__":
    unittest.main()
