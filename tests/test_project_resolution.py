from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from popup_notebook.project import (
    build_project_context,
    load_project_notebook_settings,
    resolve_interpreter,
    resolve_project_root,
)


class ProjectResolutionTests(unittest.TestCase):
    def test_prefers_nearest_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            nested = project / "src" / "module"
            nested.mkdir(parents=True)
            (project / "pyproject.toml").write_text("", encoding="utf-8")

            result = resolve_project_root(nested)

            self.assertEqual(result, project.resolve())

    def test_falls_back_to_nearest_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project = root / "project"
            nested = project / "src"
            nested.mkdir(parents=True)
            (project / ".git").mkdir()

            result = resolve_project_root(nested)

            self.assertEqual(result, project.resolve())

    def test_falls_back_to_cwd_when_no_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = Path(tmp_dir)

            result = resolve_project_root(cwd)

            self.assertEqual(result, cwd.resolve())

    def test_prefers_project_venv_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project = Path(tmp_dir)
            python = project / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            interpreter, source = resolve_interpreter(project, project)

            self.assertEqual(interpreter, python)
            self.assertEqual(source, "project .venv")

    def test_falls_back_to_current_runtime_before_system_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = Path(tmp_dir)
            runtime = cwd / "runtime-python"
            runtime.write_text("", encoding="utf-8")
            with patch("popup_notebook.project.sys.executable", str(runtime)):
                interpreter, source = resolve_interpreter(cwd, cwd)

            self.assertEqual(interpreter, runtime)
            self.assertEqual(source, "current runtime")

    def test_falls_back_to_system_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = Path(tmp_dir)
            with (
                patch("popup_notebook.project.sys.executable", ""),
                patch("popup_notebook.project.which", return_value="/usr/bin/python3"),
            ):
                interpreter, source = resolve_interpreter(cwd, cwd)

            self.assertEqual(interpreter, Path("/usr/bin/python3"))
            self.assertEqual(source, "system python3")

    def test_build_context_collects_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project = Path(tmp_dir)
            (project / "pyproject.toml").write_text("", encoding="utf-8")
            python = project / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")

            context = build_project_context(project)

            self.assertEqual(context.project_root, project.resolve())
            self.assertEqual(context.interpreter, project.resolve() / ".venv" / "bin" / "python")

    def test_load_project_notebook_settings_reads_startup_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project = Path(tmp_dir)
            (project / "pyproject.toml").write_text(
                """
[tool.popup-notebook]
startup_imports = ["numpy as np", "pandas as pd"]
startup = ["from math import sqrt"]
startup_code = ["GREETING = 'hi'"]
""".strip(),
                encoding="utf-8",
            )

            settings = load_project_notebook_settings(project)

            self.assertEqual(
                settings.startup_statements,
                (
                    "import numpy as np",
                    "import pandas as pd",
                    "from math import sqrt",
                    "GREETING = 'hi'",
                ),
            )


if __name__ == "__main__":
    unittest.main()
