from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import call, patch

from popup_notebook.launcher import PopupGeometry, configure_tmux_keyboard, tmux_popup_command


class LauncherTests(unittest.TestCase):
    def test_tmux_popup_command_uses_current_python_module_entrypoint(self) -> None:
        cwd = Path("/tmp/example")

        with patch.dict(os.environ, {}, clear=True):
            command = tmux_popup_command(cwd, PopupGeometry())

        self.assertEqual(command[:2], ["tmux", "popup"])
        shell_command = command[-1]
        self.assertTrue(shell_command.startswith("exec "))
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

    def test_tmux_popup_command_enables_key_debug_when_requested(self) -> None:
        cwd = Path("/tmp/example")

        with patch.dict(os.environ, {}, clear=True):
            command = tmux_popup_command(cwd, PopupGeometry(), key_debug=True)

        shell_command = command[-1]
        self.assertIn("TEXTUAL_DEBUG=1", shell_command)
        self.assertIn("POPUP_NOTEBOOK_KEY_DEBUG=1", shell_command)
        self.assertIn("--key-debug", shell_command)

    def test_configure_tmux_keyboard_sets_extkeys_before_popup(self) -> None:
        responses = [
            CompletedProcess(
                ["tmux", "display-message", "-p", "#{client_termtype}"],
                0,
                stdout="xterm-256color\n",
            ),
            CompletedProcess(
                ["tmux", "show-options", "-gqv", "terminal-features"],
                0,
                stdout="screen-256color:RGB\n",
            ),
        ]

        def fake_run(args, **kwargs):
            if args[:3] == ["tmux", "display-message", "-p"]:
                return responses[0]
            if args[:4] == ["tmux", "show-options", "-gqv", "terminal-features"]:
                return responses[1]
            return CompletedProcess(args, 0, stdout="")

        with patch("popup_notebook.launcher.subprocess.run", side_effect=fake_run) as run:
            configure_tmux_keyboard()

        self.assertEqual(
            run.call_args_list,
            [
                call(
                    ["tmux", "set-option", "-sq", "extended-keys", "always"],
                    check=True,
                ),
                call(
                    ["tmux", "set-option", "-sq", "extended-keys-format", "csi-u"],
                    check=True,
                ),
                call(
                    ["tmux", "display-message", "-p", "#{client_termtype}"],
                    check=True,
                    capture_output=True,
                    text=True,
                ),
                call(
                    ["tmux", "show-options", "-gqv", "terminal-features"],
                    check=True,
                    capture_output=True,
                    text=True,
                ),
                call(
                    ["tmux", "set-option", "-asq", "terminal-features", ",xterm-256color:extkeys"],
                    check=True,
                ),
            ],
        )

    def test_configure_tmux_keyboard_skips_existing_term_feature(self) -> None:
        def fake_run(args, **kwargs):
            if args[:3] == ["tmux", "display-message", "-p"]:
                return CompletedProcess(args, 0, stdout="xterm-256color\n")
            if args[:4] == ["tmux", "show-options", "-gqv", "terminal-features"]:
                return CompletedProcess(args, 0, stdout="xterm-256color:extkeys\n")
            return CompletedProcess(args, 0, stdout="")

        with patch("popup_notebook.launcher.subprocess.run", side_effect=fake_run) as run:
            configure_tmux_keyboard()

        self.assertNotIn(
            call(
                ["tmux", "set-option", "-asq", "terminal-features", ",xterm-256color:extkeys"],
                check=True,
            ),
            run.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()
