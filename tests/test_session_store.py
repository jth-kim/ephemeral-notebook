from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ephemeral_notebook.project import ProjectContext
from ephemeral_notebook.sessions.manager import SessionManager
from ephemeral_notebook.sessions.store import load_session_state, session_state_path

REPO_PYTHON = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"


class SessionStoreTests(unittest.TestCase):
    def test_load_session_state_quarantines_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            project.mkdir()

            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                manager = SessionManager()
                with patch(
                    "ephemeral_notebook.sessions.manager.build_project_context",
                    return_value=ProjectContext(
                        cwd=project.resolve(),
                        project_root=project.resolve(),
                        interpreter=REPO_PYTHON,
                        interpreter_source="test interpreter",
                    ),
                ):
                    manager.get_or_create(project)

                state_path = session_state_path(project)
                state_path.write_text("{not valid json", encoding="utf-8")

                loaded = load_session_state(project)

                self.assertIsNone(loaded)
                self.assertFalse(state_path.exists())
                self.assertTrue(state_path.with_name("state.json.corrupt").exists())


if __name__ == "__main__":
    unittest.main()
