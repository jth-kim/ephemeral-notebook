from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from popup_notebook.launcher import PopupGeometry, in_tmux, launch_tmux_popup
from popup_notebook.project import build_project_context
from popup_notebook.sessions.manager import SessionManager
from popup_notebook.tui.app import run_tui


app = typer.Typer(no_args_is_help=True, help="Notebook-like terminal scratchpad for Python.")
console = Console()


@app.command()
def status(cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Working directory to inspect.")) -> None:
    """Show the resolved project and interpreter."""
    manager = SessionManager()
    context = build_project_context(cwd)
    session_status = manager.status(context.project_root)
    table = Table(title="popup-notebook status")
    table.add_column("Field")
    table.add_column("Value", overflow="fold")
    table.add_row("cwd", str(context.cwd))
    table.add_row("project root", str(context.project_root))
    table.add_row("interpreter", str(context.interpreter))
    table.add_row("interpreter source", context.interpreter_source)
    table.add_row("session exists", str(session_status["exists"]))
    table.add_row("session attached", str(session_status["attached"]))
    table.add_row("kernel generation", str(session_status["kernel_generation"]))
    table.add_row("kernel alive", str(session_status["kernel_alive"]))
    table.add_row("kernel pid", str(session_status["kernel_pid"]))
    table.add_row("connection file", str(session_status["connection_file"]))
    table.add_row("cell count", str(session_status["cell_count"]))
    table.add_row("state path", str(session_status["state_path"]))
    console.print(table)


@app.command()
def open(
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Working directory to open from."),
    width: str = typer.Option("80%", "--width", help="Popup width."),
    height: str = typer.Option("80%", "--height", help="Popup height."),
    x: str = typer.Option("C", "--x", help="Popup x position."),
    y: str = typer.Option("C", "--y", help="Popup y position."),
    key_debug: bool = typer.Option(False, "--key-debug", help="Write raw key input to keys.log."),
) -> None:
    """Open the scratchpad UI, using a tmux popup when possible."""
    if key_debug:
        _prepare_key_debug(cwd.resolve())
    geometry = PopupGeometry(width=width, height=height, x=x, y=y)
    if in_tmux():
        launch_tmux_popup(cwd.resolve(), geometry, key_debug=key_debug)
        return
    run_tui(cwd.resolve(), key_debug=key_debug)


@app.command("ui", hidden=True)
def ui(
    cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Working directory for the UI."),
    key_debug: bool = typer.Option(False, "--key-debug", help="Write raw key input to keys.log."),
) -> None:
    """Internal entrypoint for the TUI client."""
    if key_debug:
        _enable_key_debug()
    run_tui(cwd.resolve(), key_debug=key_debug)


@app.command()
def reset(cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Working directory to reset.")) -> None:
    """Restart kernel state while preserving notebook structure."""
    manager = SessionManager()
    context = build_project_context(cwd)
    if manager.reset(context.project_root):
        console.print(f"Reset kernel state for {context.project_root}")
        return
    console.print(f"No existing session for {context.project_root}")


@app.command("hard-reset")
def hard_reset(cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Working directory to hard reset.")) -> None:
    """Clear notebook contents and recreate a blank notebook."""
    manager = SessionManager()
    context = build_project_context(cwd)
    if manager.hard_reset(context.project_root):
        console.print(f"Hard-reset notebook state for {context.project_root}")
        return
    console.print(f"No existing session for {context.project_root}")


@app.command()
def kill(cwd: Path = typer.Option(Path.cwd(), "--cwd", help="Working directory to kill.")) -> None:
    """Destroy the current project session."""
    manager = SessionManager()
    context = build_project_context(cwd)
    if manager.kill(context.project_root):
        console.print(f"Killed session for {context.project_root}")
        return
    console.print(f"No existing session for {context.project_root}")


def _prepare_key_debug(cwd: Path) -> None:
    _enable_key_debug()
    key_log = cwd / "keys.log"
    if key_log.exists():
        key_log.unlink()


def _enable_key_debug() -> None:
    os.environ["TEXTUAL_DEBUG"] = "1"
    os.environ["POPUP_NOTEBOOK_KEY_DEBUG"] = "1"


if __name__ == "__main__":
    app()
