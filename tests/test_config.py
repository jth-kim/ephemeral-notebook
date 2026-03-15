from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from popup_notebook.cli import app
from popup_notebook.config import DEFAULT_CONFIG, load_app_config


class ConfigTests(unittest.TestCase):
    def test_load_app_config_uses_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp_dir}):
                config = load_app_config()

            self.assertEqual(config, DEFAULT_CONFIG)

    def test_load_app_config_reads_popup_and_ui_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir) / "popup-notebook"
            config_dir.mkdir(parents=True)
            (config_dir / "config.toml").write_text(
                """
[popup]
width = "72%"
height = "88%"
x = "R"
y = "2"

[ui]
show_footer = false
status_verbosity = "full"
markdown_center = true
""".strip(),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp_dir}):
                config = load_app_config()

            self.assertEqual(config.popup.width, "72%")
            self.assertEqual(config.popup.height, "88%")
            self.assertEqual(config.popup.x, "R")
            self.assertEqual(config.popup.y, "2")
            self.assertFalse(config.ui.show_footer)
            self.assertEqual(config.ui.status_verbosity, "full")
            self.assertTrue(config.ui.markdown_center)
            self.assertEqual(config.ui.output_max_lines, 12)
            self.assertEqual(config.ui.code_theme, "monokai")

    def test_load_app_config_reads_output_and_theme_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = Path(tmp_dir) / "popup-notebook"
            config_dir.mkdir(parents=True)
            (config_dir / "config.toml").write_text(
                """
[ui]
output_max_lines = 20
code_theme = "vscode_dark"
""".strip(),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {"XDG_CONFIG_HOME": tmp_dir}):
                config = load_app_config()

            self.assertEqual(config.ui.output_max_lines, 20)
            self.assertEqual(config.ui.code_theme, "vscode_dark")

    def test_open_uses_config_popup_geometry_when_flags_omitted(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp_dir:
            cwd = Path(tmp_dir) / "project"
            config_dir = Path(tmp_dir) / "config" / "popup-notebook"
            cwd.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (config_dir / "config.toml").write_text(
                """
[popup]
width = "68%"
height = "76%"
x = "L"
y = "3"
""".strip(),
                encoding="utf-8",
            )

            with (
                patch.dict("os.environ", {"XDG_CONFIG_HOME": str(Path(tmp_dir) / "config")}),
                patch("popup_notebook.cli.in_tmux", return_value=True),
                patch("popup_notebook.cli.launch_tmux_popup") as launch_tmux_popup,
            ):
                result = runner.invoke(app, ["open", "--cwd", str(cwd)])

            self.assertEqual(result.exit_code, 0)
            launch_tmux_popup.assert_called_once()
            geometry = launch_tmux_popup.call_args.args[1]
            self.assertEqual(geometry.width, "68%")
            self.assertEqual(geometry.height, "76%")
            self.assertEqual(geometry.x, "L")
            self.assertEqual(geometry.y, "3")


if __name__ == "__main__":
    unittest.main()
