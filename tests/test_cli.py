from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from ephemeral_notebook import __version__
from ephemeral_notebook.cli import app


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_version_option_prints_installed_version(self) -> None:
        result = self.runner.invoke(app, ["--version"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), __version__)

    def test_open_reports_runtime_errors_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = Path(tmp_dir)
            with patch("ephemeral_notebook.cli.in_tmux", return_value=False):
                with patch(
                    "ephemeral_notebook.cli.run_tui",
                    side_effect=RuntimeError("Session is already attached elsewhere."),
                ):
                    result = self.runner.invoke(app, ["open", "--cwd", str(cwd)])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Error: Session is already attached elsewhere.", result.stdout)
        self.assertNotIn("Traceback", result.stdout)


if __name__ == "__main__":
    unittest.main()
