from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from shutil import which


@dataclass(frozen=True)
class ProjectContext:
    cwd: Path
    project_root: Path
    interpreter: Path
    interpreter_source: str


@dataclass(frozen=True)
class ProjectNotebookSettings:
    startup_statements: tuple[str, ...] = ()


def resolve_project_root(start: Path) -> Path:
    """Resolve the project root from the cwd using the v1 rules."""
    start = start.resolve()

    pyproject_root = _find_ancestor_with(start, "pyproject.toml")
    if pyproject_root is not None:
        return pyproject_root

    git_root = _find_ancestor_with(start, ".git")
    if git_root is not None:
        return git_root

    return start


def resolve_interpreter(start: Path, project_root: Path) -> tuple[Path, str]:
    """Resolve the Python interpreter according to the v1 search order."""
    project_venv = project_root / ".venv" / "bin" / "python"
    if project_venv.exists():
        return project_venv, "project .venv"

    ancestor_venv = _find_ancestor_python(start)
    if ancestor_venv is not None:
        return ancestor_venv, "ancestor .venv"

    current_runtime = Path(sys.executable) if sys.executable else None
    if current_runtime is not None and current_runtime.exists():
        return current_runtime, "current runtime"

    system_python = which("python3")
    if system_python is None:
        raise RuntimeError("Could not find python3 on PATH.")

    return Path(system_python), "system python3"


def build_project_context(start: Path) -> ProjectContext:
    cwd = start.resolve()
    project_root = resolve_project_root(cwd)
    interpreter, interpreter_source = resolve_interpreter(cwd, project_root)
    return ProjectContext(
        cwd=cwd,
        project_root=project_root,
        interpreter=interpreter,
        interpreter_source=interpreter_source,
    )


def load_project_notebook_settings(project_root: Path) -> ProjectNotebookSettings:
    """Load ephemeral-notebook project settings from pyproject.toml when present."""
    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        return ProjectNotebookSettings()

    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ProjectNotebookSettings()

    tool_section = payload.get("tool", {})
    if not isinstance(tool_section, dict):
        return ProjectNotebookSettings()
    notebook_section = tool_section.get("ephemeral-notebook", {})
    if not isinstance(notebook_section, dict):
        return ProjectNotebookSettings()

    startup_imports = _string_list(notebook_section.get("startup_imports"))
    startup_statements = _string_list(notebook_section.get("startup"))
    startup_statements.extend(_string_list(notebook_section.get("startup_code")))
    imports_as_statements = [f"import {target}" for target in startup_imports]
    return ProjectNotebookSettings(
        startup_statements=tuple(imports_as_statements + startup_statements)
    )


def _find_ancestor_with(start: Path, marker: str) -> Path | None:
    current = start
    while True:
        if (current / marker).exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _find_ancestor_python(start: Path) -> Path | None:
    current = start
    while True:
        candidate = current / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]
