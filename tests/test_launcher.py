from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from popup_notebook.launcher import PopupGeometry, tmux_popup_command


class LauncherTests(unittest.TestCase):
    def test_tmux_popup_command_uses_current_python_module_entrypoint(self) -> None:
        cwd = Path("/tmp/example")

        with patch.dict(os.environ, {}, clear=True):
            command = tmux_popup_command(cwd, PopupGeometry())

        self.assertEqual(command[:2], ["tmux", "popup"])
        shell_command = command[-1]
        self.assertIn(sys.executable, shell_command)
        self.assertIn("-m popup_notebook.cli ui", shell_command)
        self.assertIn(str(cwd), shell_command)

    def test_tmux_popup_command_forwards_pythonpath_when_present(self) -> None:
        cwd = Path("/tmp/example")

        with patch.dict(os.environ, {"PYTHONPATH": "src"}, clear=True):
            command = tmux_popup_command(cwd, PopupGeometry())

        shell_command = command[-1]
        self.assertIn("PYTHONPATH=src", shell_command)
        self.assertIn(sys.executable, shell_command)


if __name__ == "__main__":
    unittest.main()
